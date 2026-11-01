"""板块 / 题材 / 资金流服务：找主线，是游资选股的第一步。

主线三要素：涨幅居前 + 主力净流入为正 + 板块内涨停家数多（且有连板）。
"""
from __future__ import annotations

from typing import Any

from ..core import cache, http
from ..core.config import settings
from ..core.utils import fnum, yi
from ..sources import akshare_source as aks
from ..sources import eastmoney as em
from ..sources import mock
from ..sources import sina as sina_src
from ..sources import tencent as tx
from . import industry_map
from . import limitup

FS = {
    "industry": "m:90+t:2+f:!50",   # 东财行业板块
    "concept": "m:90+t:3+f:!50",    # 东财概念板块
    "region": "m:90+t:1+f:!50",     # 地域板块
}
FIELDS = "f2,f3,f8,f12,f14,f20,f62,f66,f72,f78,f104,f105,f128,f136,f140,f184"
ALL_A_FS = ("m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,"
            "m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:7+f:!2,m:1+t:3+f:!2")


# 这一列上游缺字段时必须是 None，不能是 0。
# 「0 家上涨」是一个确定的事实陈述（全板块无一只上涨，极罕见）；
# 「缺字段」是不知道。把后者写成前者，用户会据此判断板块强弱，而那个数字是假的。
REQUIRED_COUNT_FIELDS = ("f104", "f105")


def _icount(v: Any) -> int | None:
    n = fnum(v, None)
    return int(n) if n is not None else None


def _norm_board(r: dict) -> dict:
    return {
        "code": r.get("f12"),
        "name": r.get("f14"),
        "price": fnum(r.get("f2")),
        "pct": fnum(r.get("f3")),
        "turnover": fnum(r.get("f8")),
        "total_mv": fnum(r.get("f20")),
        "main_flow": fnum(r.get("f62"), 0.0),
        "main_flow_yi": yi(fnum(r.get("f62"), 0.0)),
        "main_flow_ratio": fnum(r.get("f184")),
        "super_flow": fnum(r.get("f66"), 0.0),
        "big_flow": fnum(r.get("f72"), 0.0),
        "up_count": _icount(r.get("f104")),
        "down_count": _icount(r.get("f105")),
        "lead_stock": r.get("f128"),
        "lead_code": r.get("f140"),
        "lead_pct": fnum(r.get("f136")),
    }


async def _boards_em(kind: str, sort: str, limit: int) -> list[dict] | None:
    fid = {"pct": "f3", "flow": "f62", "turnover": "f8"}.get(sort, "f3")
    # require：涨跌家数这两个统计字段必须真的回来了，否则换下一个镜像主机再试
    rows, meta = await em.clist_detail(FS.get(kind, FS["industry"]), FIELDS,
                                       fid=fid, pz=limit, require=REQUIRED_COUNT_FIELDS)
    if not rows:
        return None
    out = [_norm_board(r) for r in rows]
    if out and meta.get("missing_fields"):
        # 把上游缺字段的事实挂在首行，交由 field_health() 汇总后告知前端
        out[0]["_field_meta"] = meta
    return out


async def _boards_ak(kind: str, sort: str, limit: int) -> list[dict] | None:
    if not aks.available():
        return None
    rows = await aks.sector_fund_flow("今日")
    if not rows:
        return None
    out = []
    for r in rows[:limit]:
        out.append({
            "code": str(r.get("名称")), "name": str(r.get("名称")),
            "pct": fnum(r.get("今日涨跌幅")), "main_flow": fnum(r.get("今日主力净流入-净额"), 0.0),
            "main_flow_yi": yi(fnum(r.get("今日主力净流入-净额"), 0.0)),
            # akshare 的板块资金流接口本身不含涨跌家数，只能是未知，不能填 0
            "lead_stock": r.get("今日主力净流入-净占比"), "up_count": None, "down_count": None,
        })
    return out


async def _boards_mock(kind: str, sort: str, limit: int) -> list[dict]:
    rows = mock.boards("industry" if kind != "concept" else "concept")
    return [{
        "code": r["f12"], "name": r["f14"], "pct": r["f3"], "main_flow": r["f62"],
        "main_flow_yi": yi(r["f62"]), "up_count": r["f104"], "down_count": r["f105"],
        "lead_stock": r["f128"], "lead_code": r["f140"], "lead_pct": r["f136"],
        "price": r["f2"], "main_flow_ratio": None, "turnover": None, "total_mv": None,
        "super_flow": None, "big_flow": None,
    } for r in rows[:limit]]


_SORT_KEY = {"pct": "pct", "flow": "main_flow_yi", "turnover": "turnover"}


def _sort_rows(rows: list[dict], sort: str) -> list[dict]:
    key = _SORT_KEY.get(sort, "pct")
    return sorted(rows, key=lambda r: -(r.get(key) if r.get(key) is not None else -1e9))


async def _boards_tx(kind: str, sort: str, limit: int) -> list[dict] | None:
    """腾讯板块：申万一级行业 / 概念题材。带主力净流入。"""
    rows = await tx.board_rank("hy" if kind != "concept" else "gn", limit=max(40, limit))
    if not rows:
        return None
    return _sort_rows(rows, sort)[:limit]


async def _boards_sina(kind: str, sort: str, limit: int) -> list[dict] | None:
    """新浪行业（49 个旧版分类）。只有涨幅与成交额，没有主力资金。"""
    if kind == "concept":
        return None
    rows = await sina_src.industry_rank()
    if not rows:
        return None
    return _sort_rows(rows, sort)[:limit]


REGISTRY = {"eastmoney": _boards_em, "tencent": _boards_tx, "sina": _boards_sina,
            "akshare": _boards_ak, "mock": _boards_mock}


async def boards(kind: str = "industry", sort: str = "pct", limit: int = 40, force: bool = False) -> cache.Sourced:
    kind = kind if kind in FS else "industry"
    ordered = cache.order_providers("sector", REGISTRY)
    providers = [(n, (lambda k=kind, s=sort, l=limit, fn=f: fn(k, s, l))) for n, f in ordered]
    return await cache.chain(
        providers, cache_key=f"boards:{kind}:{sort}:{limit}", ttl=settings.ttl_sector, force=force,
        validator=lambda r: isinstance(r, list) and len(r) > 0,
    )


def field_health(rows: list[dict] | None) -> dict[str, Any]:
    """检查这批板块数据里哪些列整体缺失，供界面显示「—」并告警。

    区分三种情况：列全有、列部分缺、列整体缺。只有「整体缺」才值得告警——
    那说明上游接口没给这个字段，而不是某个板块恰好没有数据。
    """
    rows = rows or []
    n = len(rows)
    meta = (rows[0].get("_field_meta") if rows and isinstance(rows[0], dict) else None) or {}
    out: dict[str, Any] = {"rows": n, "upstream": meta, "columns": {}}
    for col in ("up_count", "down_count", "main_flow_yi", "turnover", "lead_stock"):
        missing = len([r for r in rows if r.get(col) is None])
        out["columns"][col] = {
            "missing": missing,
            "state": "ok" if missing == 0 else ("all_missing" if missing == n and n else "partial"),
        }
    counts_gone = all(out["columns"][c]["state"] == "all_missing" for c in ("up_count", "down_count"))
    out["counts_unavailable"] = bool(counts_gone and n)
    if counts_gone and n:
        hosts = "、".join(f"{h['host']}({h['rows']}行"
                          + (f"，缺{','.join(h['missing_fields'])}" if h.get("missing_fields") else "")
                          + ")" for h in (meta.get("hosts_tried") or []))
        out["note"] = ("涨/跌家数本次未取到：上游接口没有返回 f104/f105 字段，界面显示「—」而不是 0。"
                       + (f"已尝试的主机：{hosts}。" if hosts else "")
                       + "若数据源为 akshare，该接口本身不含这两列。"
                       "可在「数据源设置」把 sector 优先级调成 eastmoney 优先，"
                       "或用 /api/sectors/probe 看原始响应。")
    return out


async def probe(kind: str = "industry", pz: int = 3) -> dict[str, Any]:
    """字段级探针：逐个镜像主机看原始响应里到底带回了哪些字段。

    为什么需要它：涨跌家数显示异常时，光看界面无法区分三种原因——
    东财改了字段号、这个镜像主机不给统计字段、或者落到了没有该列的备用源。
    这个接口把原始行直接吐出来，用证据定位，而不是猜。
    """
    requested = [f for f in FIELDS.split(",") if f]
    tried: list[dict[str, Any]] = []
    for host in em.QUOTE_HOSTS:
        params = {"pn": 1, "pz": pz, "po": 1, "np": "1", "ut": em.UT, "fltt": "2", "invt": "2",
                  "fid": "f3", "fs": FS.get(kind, FS["industry"]), "fields": FIELDS}
        data = await http.fetch_json(f"https://{host}/api/qt/clist/get",
                                     source="eastmoney-probe", params=params)
        rows = em._rows_of(data)
        present = sorted({k for r in rows for k, v in r.items() if v not in em.FIELD_EMPTY})
        tried.append({
            "host": host,
            "reachable": data is not None,
            "rows": len(rows),
            "present_fields": present,
            "missing_requested": [f for f in requested if f not in present],
            "first_row": rows[0] if rows else None,
        })
    return {
        "kind": kind, "requested_fields": requested,
        "field_meaning": {"f104": "上涨家数", "f105": "下跌家数", "f3": "涨跌幅",
                          "f62": "主力净流入", "f128": "领涨股", "f8": "换手率"},
        "hosts": tried,
        "how_to_read": ("某主机 rows>0 但 missing_requested 含 f104/f105 → 该镜像不提供涨跌家数，"
                        "换主机即可；所有主机都缺 → 东财改了字段号，需要更新 sectors.FIELDS；"
                        "全部 reachable=false → 网络或限流问题，看 /api/health 的 hosts 熔断状态。"),
    }


async def stock_flow(limit: int = 50, sort: str = "f62", force: bool = False) -> cache.Sourced:
    """个股主力资金净流入榜（找资金真正在买什么）"""
    async def _em():
        rows = await em.clist(ALL_A_FS, "f2,f3,f12,f14,f62,f66,f72,f78,f184,f8,f20", fid=sort, pz=limit)
        return [{
            "code": r.get("f12"), "name": r.get("f14"), "price": fnum(r.get("f2")),
            "pct": fnum(r.get("f3")), "main_flow": fnum(r.get("f62"), 0.0),
            "main_flow_yi": yi(fnum(r.get("f62"), 0.0)), "main_flow_ratio": fnum(r.get("f184")),
            "super_flow_yi": yi(fnum(r.get("f66"), 0.0)), "big_flow_yi": yi(fnum(r.get("f72"), 0.0)),
            "turnover": fnum(r.get("f8")), "total_mv_yi": yi(fnum(r.get("f20"), 0.0)),
        } for r in rows] if rows else None

    def _mock():
        return [{"code": "002185", "name": "华天科技", "price": 18.03, "pct": 10.01,
                 "main_flow_yi": 26.35, "main_flow_ratio": 41.26, "turnover": 12.1, "total_mv_yi": 580}]

    return await cache.chain(
        [("eastmoney", _em), ("tencent", lambda: tx.stock_flow(limit)), ("mock", _mock)],
        cache_key=f"stockflow:{limit}:{sort}", ttl=settings.ttl_sector, force=force,
        validator=lambda r: bool(r),
    )


async def zt_by_industry(date: str | None = None, force: bool = False) -> dict[str, dict]:
    """按行业统计涨停家数与最高连板（主线判定的关键证据）"""
    res = await limitup.pool("zt", date, force=force)
    items = (res.data or {}).get("items") or []
    agg: dict[str, dict] = {}
    for it in items:
        k = it.get("industry") or "其他"
        a = agg.setdefault(k, {"name": k, "count": 0, "max_boards": 0, "stocks": [], "fund": 0.0})
        a["count"] += 1
        a["max_boards"] = max(a["max_boards"], it.get("boards") or 1)
        a["fund"] += it.get("fund") or 0
        a["stocks"].append({"code": it["code"], "name": it["name"], "boards": it.get("boards"),
                            "board_type": it.get("board_type"), "fund": it.get("fund"),
                            "first_min": it.get("first_min"), "first_time": it.get("first_time")})
    for a in agg.values():
        a["fund_yi"] = round(a["fund"] / 1e8, 2)
        a["stocks"].sort(key=lambda x: -(x.get("boards") or 0))
    return dict(sorted(agg.items(), key=lambda kv: (-kv[1]["count"], -kv[1]["max_boards"])))


def line_confirm(zt_count: int | None, max_boards: int | None,
                 pct: float | None, flow: float | None) -> list[str]:
    """主线四维确认：涨停家数、连板高度、板块涨幅、主力净流入，缺一不可。

    返回缺口说明；空列表表示四项同时成立。数据缺失（None）必须与「数值为 0」
    区分开：前者是没拿到，后者是真的弱。
    """
    gaps: list[str] = []
    if (zt_count or 0) < 4:
        gaps.append(f"涨停仅{zt_count or 0}家")
    if (max_boards or 0) < 2:
        gaps.append("无连板龙头")
    if pct is None:
        gaps.append("缺少板块涨幅")
    elif pct <= 2:
        gaps.append(f"板块涨幅{pct:.2f}%未超2%")
    if flow is None:
        gaps.append("缺少主力资金")
    elif flow <= 0:
        gaps.append("主力净流出")
    return gaps


def position_ladder(zt_ind: dict[str, dict], top_n: int = 3) -> dict[str, list[dict]]:
    """板块内身位：同板块按「连板高度 → 封单额 → 首封时间」定龙一/龙二/跟风。

    只用涨停池的真实字段，不引入任何外部口径，所以板块数据源挂掉也照样可用。
    """
    out: dict[str, list[dict]] = {}
    for name, agg in zt_ind.items():
        rows = sorted(
            agg.get("stocks") or [],
            key=lambda r: (-(r.get("boards") or 1), -(r.get("fund") or 0),
                           r.get("first_min") or 9999),
        )
        if not rows:
            continue
        leader_boards = rows[0].get("boards") or 1
        out[name] = [{
            "code": r.get("code"), "name": r.get("name"), "boards": r.get("boards"),
            "board_type": r.get("board_type"),
            "fund_yi": round((r.get("fund") or 0) / 1e8, 2),
            "seat": i + 1,
            "seat_label": ("龙一" if i == 0 else "龙二" if i == 1 else "跟风" if i < top_n else "后排"),
            "board_gap": leader_boards - (r.get("boards") or 1),
        } for i, r in enumerate(rows)]
    return out


async def main_line(force: bool = False) -> dict:
    """主线判定：把「板块涨幅 + 资金流 + 涨停结构」三张表交叉验证。"""
    import asyncio

    ind, cpt, zt_ind = await asyncio.gather(
        boards("industry", "pct", 60, force=force),
        boards("concept", "pct", 60, force=force),
        zt_by_industry(force=force),
    )

    ind_rows = ind.data or []
    cpt_rows = cpt.data or []
    by_name = {r["name"]: r for r in ind_rows + cpt_rows}

    # 口径对齐：涨停行业是东财细分（通用设备/汽车零部），板块榜可能是申万一级
    # （机械设备/汽车）。名字对不上时先把细分归并到一级再匹配；只做分类归并，
    # 不改任何数值，归并不上的原样保留并标为缺口。
    mapping: dict = {"applied": False, "unmapped": [], "merged": {}}
    if by_name and any(n not in by_name for n in zt_ind):
        merged: dict[str, dict] = {}
        unmapped: list[str] = []
        for name, zt in zt_ind.items():
            sw = industry_map.to_sw(name)
            if not sw or sw not in by_name:
                unmapped.append(name)
                continue
            a = merged.setdefault(sw, {"name": sw, "count": 0, "max_boards": 0,
                                       "stocks": [], "fund_yi": 0.0, "members": []})
            a["count"] += zt["count"]
            a["max_boards"] = max(a["max_boards"], zt["max_boards"])
            a["stocks"].extend(zt["stocks"])
            a["fund_yi"] = round(a["fund_yi"] + (zt.get("fund_yi") or 0), 2)
            a["members"].append(name)
        if merged:
            for a in merged.values():
                a["stocks"].sort(key=lambda x: (-(x.get("boards") or 0), -(x.get("fund") or 0)))
            for name in unmapped:
                if name not in merged:
                    merged[name] = dict(zt_ind[name], members=[name])
            mapping = {"applied": True, "unmapped": unmapped,
                       "merged": {k: v["members"] for k, v in merged.items() if len(v["members"]) > 1}}
            zt_ind = merged

    scored: list[dict] = []
    for name, zt in zt_ind.items():
        row = by_name.get(name) or {}
        # 板块名对不上时不能拿 0 顶替：那会把「没数据」算成「涨幅0%、资金0亿」，
        # 四维确认看起来跑了，其实只用了两维。
        pct = row.get("pct")
        flow = row.get("main_flow_yi")
        gaps = line_confirm(zt["count"], zt["max_boards"], pct, flow)
        # 归并后单个申万一级可能合并十几家涨停，家数项封顶 10，避免主线分被顶满
        cnt = min(zt["count"], 10)
        score = (cnt * 6 + zt["max_boards"] * 5 + (pct or 0) * 4
                 + min(max(flow or 0, -10), 20) * 1.2)
        scored.append({
            "name": name, "zt_count": zt["count"], "max_boards": zt["max_boards"],
            "members": zt.get("members") or [name],
            "pct": pct, "main_flow_yi": flow, "fund_yi": zt["fund_yi"],
            "score": round(score, 1),
            "confirmed": not gaps,
            "confirm_gaps": gaps,
            "stocks": zt["stocks"][:8],
            "reason": _line_reason(zt["count"], zt["max_boards"], pct, flow),
        })
    scored.sort(key=lambda x: -x["score"])
    top = scored[:5]
    confirmed = [x for x in scored if x["confirmed"]][:5]

    matched = sum(1 for n in zt_ind if n in by_name)
    taxonomy_ok = None if not by_name else matched > 0
    taxonomies = sorted({str(r.get("taxonomy")) for r in ind_rows + cpt_rows if r.get("taxonomy")})
    warnings: list[str] = []
    if not by_name:
        warnings.append("板块榜单为空：缺少板块涨幅与主力净流入，主线四维无法验证")
    elif not taxonomy_ok:
        warnings.append("涨停行业名与板块榜单口径（" + "、".join(taxonomies)
                        + "）不一致：pct/资金无法归因，主线仅按涨停结构排序")
    if mapping.get("applied"):
        warnings.append("涨停行业已按申万一级归并后与板块榜对齐（如 "
                        + "、".join(f"{k}={'/'.join(v)}" for k, v in list(mapping["merged"].items())[:2])
                        + "）；板块涨幅与资金为申万一级口径，不是细分行业口径")
        if mapping.get("unmapped"):
            warnings.append("以下细分行业无法归并，已保留但缺板块涨幅/资金："
                            + "、".join(mapping["unmapped"][:8]))

    return {
        "main_lines": top,
        "confirmed_lines": confirmed,
        "confirm_mode": "full" if confirmed else "structure_only",
        "taxonomy_ok": taxonomy_ok,
        "industry_mapping": mapping,
        "board_taxonomy": taxonomies,
        "board_counts": {"industry": len(ind_rows), "concept": len(cpt_rows)},
        "warnings": warnings,
        "hot_concepts": sorted([r for r in cpt_rows if not str(r.get("name") or "").startswith("昨日")],
                               key=lambda r: -(r.get("pct") or -99))[:20],
        "hot_industries": sorted(ind_rows, key=lambda r: -(r.get("pct") or -99))[:20],
        "flow_in_top": sorted(ind_rows + cpt_rows, key=lambda r: -(r.get("main_flow_yi") or -999))[:20],
        "flow_out_top": sorted(ind_rows + cpt_rows, key=lambda r: (r.get("main_flow_yi") or 999))[:15],
        "zt_industry": list(zt_ind.values())[:20],
        "positions": position_ladder(zt_ind),
        "sources": {"industry": ind.source, "concept": cpt.source},
    }


def _line_reason(count: int, max_b: int, pct: float | None, flow: float | None) -> str:
    bits = []
    bits.append(f"涨停{count}家" if count else "无涨停")
    if max_b >= 3:
        bits.append(f"最高{max_b}板有龙头")
    elif max_b == 2:
        bits.append("仅二板、缺龙头")
    else:
        bits.append("全首板、题材偏散")
    if pct and pct >= 3:
        bits.append(f"板块+{pct:.1f}%强势")
    elif pct and pct < 0:
        bits.append(f"板块{pct:.1f}%走弱(背离)")
    if flow and flow > 5:
        bits.append(f"主力净流入{flow:.1f}亿")
    elif flow and flow < -5:
        bits.append(f"主力净流出{abs(flow):.1f}亿(拉高出货嫌疑)")
    return "，".join(bits)