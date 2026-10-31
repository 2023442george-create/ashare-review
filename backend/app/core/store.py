"""SQLite 本地存储：情绪历史、每日快照、复盘笔记、自选/席位自定义。

只用标准库 sqlite3，避免额外依赖；写入均为 upsert，可反复重跑。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .config import settings

# 必须用可重入锁：save_xxx()/load_xxx() 会在持锁状态下调用 conn()，而 conn() 内部也要加锁
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentiment_daily(
    trade_date TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS market_daily(
    trade_date TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS snapshot(
    trade_date TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS note(
    trade_date TEXT PRIMARY KEY,
    content    TEXT,
    updated_at TEXT
);
-- macro_daily：宏观温度每日快照（只存精简摘要，不存序列），用于画温度分历史曲线
CREATE TABLE IF NOT EXISTS macro_daily(
    trade_date TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS watchlist(
    code       TEXT PRIMARY KEY,
    name       TEXT,
    tag        TEXT,
    created_at TEXT
);

-- ===================== 结果账本（研究的核心资产） =====================
-- signal_log：收盘后把"当天规则看到的全部可选标的"连同选中标记一起冻住。
-- 为什么要连未选中的也存？因为置换检验需要"决策时点真实可选的全集"做零分布，
-- 只存选中的票就永远无法回答"规则是否优于乱选"。
-- frozen_at 是真实写入时间戳，用于证明记录不是事后补的；
-- param_digest 是参数指纹，用于证明当时用的确实是那组阈值。
CREATE TABLE IF NOT EXISTS signal_log(
    trade_date    TEXT NOT NULL,      -- 候选日（信号生成日，收盘后）
    strategy      TEXT NOT NULL,
    code          TEXT NOT NULL,
    name          TEXT,
    selected      INTEGER NOT NULL,   -- 1=规则选中 0=在可选池但未入选
    rank          INTEGER,
    score         REAL,
    payload       TEXT,
    param_version TEXT,
    param_digest  TEXT,
    rule_version  TEXT,
    frozen_at     TEXT NOT NULL,
    PRIMARY KEY (trade_date, strategy, code)
);
CREATE INDEX IF NOT EXISTS idx_signal_log_date ON signal_log(trade_date);

-- signal_outcome：前瞻结果。entry 固定为候选日次一交易日开盘（可成交口径），
-- 不使用候选日收盘价，因为那是做决策时已知、但买不到的价格。
CREATE TABLE IF NOT EXISTS signal_outcome(
    trade_date   TEXT NOT NULL,
    strategy     TEXT NOT NULL,
    code         TEXT NOT NULL,
    horizon      INTEGER NOT NULL,    -- 持有 N 个交易日
    entry_date   TEXT,
    entry_price  REAL,
    exit_date    TEXT,
    exit_price   REAL,
    ret_pct      REAL,                -- 毛收益
    ret_net_pct  REAL,                -- 扣费后
    base_ret_pct REAL,                -- 同期基准
    excess_pct   REAL,                -- 扣费后超额
    tradable     INTEGER,             -- 1=次日开盘可买入 0=开盘即封死/无报价
    reason       TEXT,
    benchmark    TEXT,
    price_source TEXT,
    cost_digest  TEXT,
    settled_at   TEXT,
    PRIMARY KEY (trade_date, strategy, code, horizon)
);
CREATE INDEX IF NOT EXISTS idx_outcome_strategy ON signal_outcome(strategy, horizon);

-- research_trial：试错台账。多重检验校正需要知道"一共试过多少次"，
-- 否则 p<0.05 毫无意义。任何一次策略/参数调整都应在这里留痕。
CREATE TABLE IF NOT EXISTS research_trial(
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT,
    strategy      TEXT,
    horizon       INTEGER,
    param_digest  TEXT,
    hypothesis    TEXT,
    n_sample      INTEGER,
    p_value       REAL,
    outcome       TEXT
);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path: Path = settings.db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        with _lock:
            _conn.executescript(SCHEMA)
            _conn.commit()
    return _conn


def _now() -> str:
    from .utils import now_cn

    return now_cn().strftime("%Y-%m-%d %H:%M:%S")


def save_sentiment(trade_date: str, payload: dict[str, Any]) -> None:
    from .utils import normalize_date

    trade_date = normalize_date(trade_date)
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO sentiment_daily(trade_date,payload,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(trade_date) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
            (trade_date, json.dumps(payload, ensure_ascii=False), _now()),
        )
        c.commit()


def save_market(trade_date: str, payload: dict[str, Any]) -> None:
    from .utils import normalize_date

    trade_date = normalize_date(trade_date)
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO market_daily(trade_date,payload,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(trade_date) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
            (trade_date, json.dumps(payload, ensure_ascii=False), _now()),
        )
        c.commit()


def save_snapshot(trade_date: str, payload: dict[str, Any]) -> None:
    from .utils import normalize_date

    trade_date = normalize_date(trade_date)
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO snapshot(trade_date,payload,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(trade_date) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
            (trade_date, json.dumps(payload, ensure_ascii=False), _now()),
        )
        c.commit()


def load_snapshot(trade_date: str) -> dict[str, Any] | None:
    from .utils import normalize_date

    with _lock:
        r = conn().execute("SELECT payload FROM snapshot WHERE trade_date=?", (normalize_date(trade_date),)).fetchone()
    if not r:
        return None
    try:
        data = json.loads(r["payload"])
    except Exception:
        return None
    data["trade_date"] = normalize_date(trade_date)
    return data


def load_sentiment_history(days: int = 60) -> list[dict[str, Any]]:
    from .utils import normalize_date

    with _lock:
        rows = conn().execute("SELECT trade_date,payload,updated_at FROM sentiment_daily").fetchall()
    # 旧版本可能混存 20261023 / 2026-10-23 两行，统一日期后同一天只保留最后写入的那条，
    # 否则情绪曲线同一天出现两个点，周期判定也会把它们当成两个交易日。
    latest: dict[str, tuple[str, dict[str, Any]]] = {}
    for r in rows:
        try:
            d = json.loads(r["payload"])
        except Exception:
            continue
        key = normalize_date(r["trade_date"])
        d["trade_date"] = key
        stamp = r["updated_at"] or ""
        if key not in latest or stamp >= latest[key][0]:
            latest[key] = (stamp, d)
    out = [v for _, v in latest.values()]
    out.sort(key=lambda x: x["trade_date"])
    return out[-days:]


def load_market_history(days: int = 60) -> list[dict[str, Any]]:
    with _lock:
        rows = conn().execute(
            "SELECT trade_date,payload FROM market_daily ORDER BY trade_date DESC LIMIT ?", (days,)
        ).fetchall()
    out = []
    for r in reversed(rows):
        try:
            d = json.loads(r["payload"])
        except Exception:
            continue
        d["trade_date"] = r["trade_date"]
        out.append(d)
    return out


def save_macro(trade_date: str, payload: dict[str, Any]) -> None:
    """写入（或覆盖）某交易日的宏观温度摘要。同一天多次计算以最后一次为准。"""
    from .utils import normalize_date

    trade_date = normalize_date(trade_date)
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO macro_daily(trade_date,payload,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(trade_date) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
            (trade_date, json.dumps(payload, ensure_ascii=False), _now()),
        )
        c.commit()


def load_macro_history(days: int = 250) -> list[dict[str, Any]]:
    """最近 days 条宏观温度摘要，按日期升序。"""
    with _lock:
        rows = conn().execute(
            "SELECT trade_date,payload,updated_at FROM macro_daily ORDER BY trade_date DESC LIMIT ?", (days,)
        ).fetchall()
    out = []
    for r in reversed(rows):
        try:
            d = json.loads(r["payload"])
        except Exception:
            continue
        d["trade_date"] = r["trade_date"]
        d["updated_at"] = r["updated_at"]
        out.append(d)
    return out


def save_note(trade_date: str, content: str) -> None:
    from .utils import normalize_date

    trade_date = normalize_date(trade_date)
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO note(trade_date,content,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(trade_date) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at",
            (trade_date, content, _now()),
        )
        c.commit()


def load_note(trade_date: str) -> str:
    from .utils import normalize_date

    with _lock:
        r = conn().execute("SELECT content FROM note WHERE trade_date=?", (normalize_date(trade_date),)).fetchone()
    return r["content"] if r else ""


def list_watch() -> list[dict[str, Any]]:
    with _lock:
        rows = conn().execute("SELECT code,name,tag,created_at FROM watchlist ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def add_watch(code: str, name: str = "", tag: str = "") -> None:
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO watchlist(code,name,tag,created_at) VALUES(?,?,?,?) "
            "ON CONFLICT(code) DO UPDATE SET name=excluded.name, tag=excluded.tag",
            (code, name, tag, _now()),
        )
        c.commit()


def del_watch(code: str) -> None:
    with _lock:
        c = conn()
        c.execute("DELETE FROM watchlist WHERE code=?", (code,))
        c.commit()

# ===================== 结果账本读写 =====================
def freeze_signals(trade_date: str, strategy: str, rows: list[dict[str, Any]],
                   param_version: str, param_digest: str, rule_version: str) -> int:
    """冻结某交易日某策略的全部可选标的（含未选中），幂等可重跑。

    rows 每项需含：code / name / selected / rank / score / payload。
    frozen_at 一旦写入就不再更新（ON CONFLICT 不覆盖 frozen_at），
    这样"记录是什么时候冻的"无法被后来的重跑篡改。
    """
    from .utils import normalize_date

    d = normalize_date(trade_date)
    ts = _now()
    with _lock:
        c = conn()
        for r in rows:
            c.execute(
                "INSERT INTO signal_log(trade_date,strategy,code,name,selected,rank,score,payload,"
                "param_version,param_digest,rule_version,frozen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(trade_date,strategy,code) DO UPDATE SET "
                "name=excluded.name, selected=excluded.selected, rank=excluded.rank, "
                "score=excluded.score, payload=excluded.payload, "
                "param_version=excluded.param_version, param_digest=excluded.param_digest, "
                "rule_version=excluded.rule_version",
                (d, strategy, str(r.get("code") or ""), r.get("name") or "",
                 1 if r.get("selected") else 0, r.get("rank"), r.get("score"),
                 json.dumps(r.get("payload") or {}, ensure_ascii=False),
                 param_version, param_digest, rule_version, ts),
            )
        c.commit()
    return len(rows)


def load_signals(trade_date: str | None = None, strategy: str | None = None,
                 only_selected: bool = False) -> list[dict[str, Any]]:
    from .utils import normalize_date

    sql = "SELECT * FROM signal_log WHERE 1=1"
    args: list[Any] = []
    if trade_date:
        sql += " AND trade_date=?"
        args.append(normalize_date(trade_date))
    if strategy:
        sql += " AND strategy=?"
        args.append(strategy)
    if only_selected:
        sql += " AND selected=1"
    sql += " ORDER BY trade_date DESC, strategy, selected DESC, rank"
    with _lock:
        rows = conn().execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.get("payload") or "{}")
        except Exception:
            d["payload"] = {}
        out.append(d)
    return out


def signal_dates(limit: int = 400) -> list[str]:
    """已冻结的候选日列表（升序）。"""
    with _lock:
        rows = conn().execute(
            "SELECT DISTINCT trade_date FROM signal_log ORDER BY trade_date DESC LIMIT ?", (limit,)
        ).fetchall()
    return sorted(r["trade_date"] for r in rows)


def save_outcomes(rows: list[dict[str, Any]]) -> int:
    """写入前瞻结果，幂等。"""
    ts = _now()
    with _lock:
        c = conn()
        for r in rows:
            c.execute(
                "INSERT INTO signal_outcome(trade_date,strategy,code,horizon,entry_date,entry_price,"
                "exit_date,exit_price,ret_pct,ret_net_pct,base_ret_pct,excess_pct,tradable,reason,"
                "benchmark,price_source,cost_digest,settled_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(trade_date,strategy,code,horizon) DO UPDATE SET "
                "entry_date=excluded.entry_date, entry_price=excluded.entry_price, "
                "exit_date=excluded.exit_date, exit_price=excluded.exit_price, "
                "ret_pct=excluded.ret_pct, ret_net_pct=excluded.ret_net_pct, "
                "base_ret_pct=excluded.base_ret_pct, excess_pct=excluded.excess_pct, "
                "tradable=excluded.tradable, reason=excluded.reason, benchmark=excluded.benchmark, "
                "price_source=excluded.price_source, cost_digest=excluded.cost_digest, "
                "settled_at=excluded.settled_at",
                (r["trade_date"], r["strategy"], r["code"], int(r["horizon"]),
                 r.get("entry_date"), r.get("entry_price"), r.get("exit_date"), r.get("exit_price"),
                 r.get("ret_pct"), r.get("ret_net_pct"), r.get("base_ret_pct"), r.get("excess_pct"),
                 (1 if r.get("tradable") else 0) if r.get("tradable") is not None else None,
                 r.get("reason") or "", r.get("benchmark") or "", r.get("price_source") or "",
                 r.get("cost_digest") or "", ts),
            )
        c.commit()
    return len(rows)


def load_outcomes(strategy: str | None = None, horizon: int | None = None,
                  trade_date: str | None = None, limit: int = 20000) -> list[dict[str, Any]]:
    """结果账本与冻结记录 join：同时带回 selected 标记、评分与参数指纹。"""
    from .utils import normalize_date

    sql = ("SELECT o.*, l.selected, l.rank, l.score, l.name, l.param_digest, l.frozen_at "
           "FROM signal_outcome o JOIN signal_log l "
           "ON o.trade_date=l.trade_date AND o.strategy=l.strategy AND o.code=l.code WHERE 1=1")
    args: list[Any] = []
    if strategy:
        sql += " AND o.strategy=?"
        args.append(strategy)
    if horizon is not None:
        sql += " AND o.horizon=?"
        args.append(int(horizon))
    if trade_date:
        sql += " AND o.trade_date=?"
        args.append(normalize_date(trade_date))
    sql += " ORDER BY o.trade_date, o.strategy, o.horizon LIMIT ?"
    args.append(int(limit))
    with _lock:
        rows = conn().execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def pending_settlement(horizon: int, max_dates: int = 60) -> list[str]:
    """返回已冻结但该 horizon 尚未结算完的候选日（升序）。"""
    with _lock:
        rows = conn().execute(
            "SELECT l.trade_date, COUNT(*) AS total, "
            "SUM(CASE WHEN o.code IS NULL THEN 1 ELSE 0 END) AS missing "
            "FROM signal_log l LEFT JOIN signal_outcome o "
            "ON o.trade_date=l.trade_date AND o.strategy=l.strategy AND o.code=l.code "
            "AND o.horizon=? GROUP BY l.trade_date HAVING missing > 0 "
            "ORDER BY l.trade_date DESC LIMIT ?", (int(horizon), int(max_dates))
        ).fetchall()
    return sorted(r["trade_date"] for r in rows)


def outcome_summary(horizon: int = 1) -> dict[str, Any]:
    """用 SQL 聚合给出账本概况，不把几十万行搬进内存。

    复盘报告每次生成都会读这个（展示验证状态），所以必须是常数级开销；
    早期版本直接 load_outcomes(limit=50000) 再在 Python 里统计，
    账本攒到两年就会让每份报告都慢下来。
    """
    with _lock:
        c = conn()
        row = c.execute(
            "SELECT COUNT(DISTINCT trade_date) AS days, COUNT(*) AS rows FROM signal_outcome "
            "WHERE horizon=?", (int(horizon),)
        ).fetchone()
        digests = [r["param_digest"] for r in c.execute(
            "SELECT DISTINCT l.param_digest AS param_digest FROM signal_outcome o "
            "JOIN signal_log l ON o.trade_date=l.trade_date AND o.strategy=l.strategy "
            "AND o.code=l.code WHERE o.horizon=? AND l.param_digest IS NOT NULL",
            (int(horizon),)).fetchall()]
        per = [dict(r) for r in c.execute(
            "SELECT o.strategy AS strategy, COUNT(DISTINCT o.trade_date) AS days, "
            "SUM(CASE WHEN l.selected=1 THEN 1 ELSE 0 END) AS selected, "
            "SUM(CASE WHEN l.selected=1 AND o.tradable=0 THEN 1 ELSE 0 END) AS untradable "
            "FROM signal_outcome o JOIN signal_log l "
            "ON o.trade_date=l.trade_date AND o.strategy=l.strategy AND o.code=l.code "
            "WHERE o.horizon=? GROUP BY o.strategy", (int(horizon),)).fetchall()]
    for p_ in per:
        sel = p_.get("selected") or 0
        p_["untradable_rate"] = round((p_.get("untradable") or 0) / sel * 100, 1) if sel else None
    return {"days": (row["days"] if row else 0) or 0, "rows": (row["rows"] if row else 0) or 0,
            "param_digests": sorted(d for d in digests if d), "per_strategy": per}


def log_trial(strategy: str, horizon: int, param_digest: str, hypothesis: str,
              n_sample: int, p_value: float | None, outcome: str) -> None:
    """登记一次检验，供多重检验校正使用。"""
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO research_trial(created_at,strategy,horizon,param_digest,hypothesis,"
            "n_sample,p_value,outcome) VALUES(?,?,?,?,?,?,?,?)",
            (_now(), strategy, int(horizon), param_digest, hypothesis, int(n_sample), p_value, outcome),
        )
        c.commit()


def list_trials(limit: int = 500) -> list[dict[str, Any]]:
    with _lock:
        rows = conn().execute(
            "SELECT * FROM research_trial ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [dict(r) for r in rows]
