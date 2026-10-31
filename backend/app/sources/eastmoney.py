"""东方财富系列接口（免费、无需 token）。

包含四组域名，互为备份：
- push2.eastmoney.com        实时行情/板块/资金流（部分网络环境会被限流）
- push2delay.eastmoney.com   延时行情（稳定性最好，复盘场景完全够用）
- push2ex.eastmoney.com      涨跌停池/涨跌分布（复盘核心数据）
- datacenter-web.eastmoney.com  龙虎榜/两融/沪深港通等统计数据
"""
from __future__ import annotations

from typing import Any

from ..core import http
from ..core.utils import fnum, yyyymmdd

UT = "7eea3edcaed734bea9cbfc24409ed989"
QUOTE_HOSTS = ("push2.eastmoney.com", "push2delay.eastmoney.com", "82.push2.eastmoney.com", "17.push2.eastmoney.com")
KLINE_HOSTS = ("push2his.eastmoney.com", "push2delay.eastmoney.com")
EX_HOST = "push2ex.eastmoney.com"
DC_HOST = "datacenter-web.eastmoney.com"
NEWS_HOST = "np-weblist.eastmoney.com"

BASE_FIELDS = "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f62,f184"


async def quote_list(secids: list[str], fields: str = BASE_FIELDS) -> list[dict]:
    """批量行情。secids 形如 ['1.000001','0.399001','100.N225']"""
    if not secids:
        return []
    params = {
        "ut": UT, "fltt": "2", "invt": "2",
        "secids": ",".join(secids),
        "fields": fields,
    }
    for host in QUOTE_HOSTS:
        data = await http.fetch_json(f"https://{host}/api/qt/ulist.np/get", source="eastmoney", params=params)
        rows = ((data or {}).get("data") or {}).get("diff") or []
        if rows:
            return rows
    return []


# 东财把"没有这个值"表示成空串或短横线，和真正的 0 是两回事。
FIELD_EMPTY = ("", "-", "--", "—", None)


def _rows_of(data: Any) -> list[dict]:
    """取出 data.diff。个别镜像会返回 {"0": {...}, "1": {...}} 而不是数组。"""
    diff = ((data or {}).get("data") or {}).get("diff")
    if isinstance(diff, dict):
        def _k(x: Any) -> int:
            sx = str(x)
            return int(sx) if sx.isdigit() else 0
        return [diff[k] for k in sorted(diff, key=_k) if isinstance(diff[k], dict)]
    return [r for r in (diff or []) if isinstance(r, dict)]


def _field_present(rows: list[dict], field: str, sample: int = 8) -> bool:
    for r in rows[:sample]:
        if r.get(field) not in FIELD_EMPTY:
            return True
    return False


async def clist_detail(fs: str, fields: str, fid: str = "f3", pz: int = 50, pn: int = 1,
                       po: int = 1, require: tuple[str, ...] = ()) -> tuple[list[dict], dict]:
    """通用榜单，并检查响应里**真的带回了**要求的字段。

    为什么要加 require：原来的实现是"第一个返回了行的主机就采用"。
    但几个镜像主机返回的字段并不一致——某些主机（尤其延时镜像）会给出行情字段、
    却整列不返回涨跌家数之类的统计字段。于是链路在第一个主机就结束了，
    下游拿到一堆空值，再被 `fnum(..., 0)` 变成 0，界面上显示"0 家上涨"。
    这是一个"看起来有数据、其实字段缺失"的静默错误，比直接报错难查得多。

    现在：字段不全的响应不被立即采用，继续试下一个主机；全都不全时退回最完整的那个，
    并在 meta.missing_fields 里如实报告缺了什么，由上层决定显示"—"还是告警。

    返回 (rows, meta)。meta = {host, missing_fields, hosts_tried}
    """
    params = {
        "pn": pn, "pz": pz, "po": po, "np": "1", "ut": UT, "fltt": "2", "invt": "2",
        "fid": fid, "fs": fs, "fields": fields,
    }
    tried: list[dict] = []
    best: tuple[list[dict], dict] | None = None
    for host in QUOTE_HOSTS:
        data = await http.fetch_json(f"https://{host}/api/qt/clist/get", source="eastmoney", params=params)
        rows = _rows_of(data)
        info = {"host": host, "rows": len(rows)}
        tried.append(info)
        if not rows:
            continue
        missing = [f for f in require if not _field_present(rows, f)]
        info["missing_fields"] = missing
        if not missing:
            return rows, {"host": host, "missing_fields": [], "hosts_tried": tried}
        if best is None or len(missing) < len(best[1]["missing_fields"]):
            best = (rows, {"host": host, "missing_fields": missing, "hosts_tried": tried})
    if best:
        return best[0], {**best[1], "hosts_tried": tried}
    return [], {"host": "", "missing_fields": list(require), "hosts_tried": tried}


async def clist(fs: str, fields: str, fid: str = "f3", pz: int = 50, pn: int = 1, po: int = 1) -> list[dict]:
    """通用榜单：行业板块 m:90+t:2 / 概念板块 m:90+t:3 / 全A m:0+t:6,..."""
    rows, _meta = await clist_detail(fs, fields, fid=fid, pz=pz, pn=pn, po=po)
    return rows


async def kline(secid: str, klt: int = 101, fqt: int = 1, lmt: int = 120) -> list[list]:
    """K线：klt=101日/102周/103月，fqt=1前复权。返回 [[date,open,close,high,low,volume,amount],...]"""
    params = {
        "secid": secid, "ut": UT, "klt": klt, "fqt": fqt, "lmt": lmt, "end": "20500101",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    for host in KLINE_HOSTS:
        data = await http.fetch_json(f"https://{host}/api/qt/stock/kline/get", source="eastmoney", params=params)
        klines = ((data or {}).get("data") or {}).get("klines") or []
        if klines:
            out = []
            for line in klines:
                parts = str(line).split(",")
                out.append([parts[0]] + [fnum(x, 0.0) for x in parts[1:7]])
            return out
    return []


async def _pool(api: str, date: str | None, sort: str, pagesize: int = 300) -> dict:
    params = {
        "ut": UT, "dpt": "wz.ztzt", "Pageindex": "0", "pagesize": pagesize,
        "sort": sort, "date": yyyymmdd(date),
    }
    data = await http.fetch_json(f"https://{EX_HOST}/{api}", source="eastmoney", params=params)
    return (data or {}).get("data") or {}


async def zt_pool(date: str | None = None) -> dict:
    """涨停池"""
    return await _pool("getTopicZTPool", date, "fbt:asc")


async def zb_pool(date: str | None = None) -> dict:
    """炸板池（曾涨停未封住）"""
    return await _pool("getTopicZBPool", date, "fbt:asc")


async def dt_pool(date: str | None = None) -> dict:
    """跌停池"""
    return await _pool("getTopicDTPool", date, "fund:asc")


async def zdfenbu(date: str | None = None) -> dict:
    """全市场涨跌分布（用于统计涨跌家数）"""
    params = {"ut": UT, "dpt": "wz.ztzt", "date": yyyymmdd(date)}
    data = await http.fetch_json(f"https://{EX_HOST}/getTopicZDFenBu", source="eastmoney", params=params)
    return (data or {}).get("data") or {}


async def datacenter(report_name: str, *, filter_: str = "", sort_columns: str = "", sort_types: str = "-1",
                     page_size: int = 100, page_number: int = 1, columns: str = "ALL") -> list[dict]:
    params = {
        "reportName": report_name, "columns": columns, "source": "WEB", "client": "WEB",
        "pageSize": page_size, "pageNumber": page_number,
        "sortColumns": sort_columns, "sortTypes": sort_types,
    }
    if filter_:
        params["filter"] = filter_
    data = await http.fetch_json(f"https://{DC_HOST}/api/data/v1/get", source="eastmoney", params=params)
    return ((data or {}).get("result") or {}).get("data") or []


async def lhb_list(date: str) -> list[dict]:
    """龙虎榜每日明细"""
    return await datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_=f"(TRADE_DATE>='{date}')(TRADE_DATE<='{date}')",
        sort_columns="BILLBOARD_NET_AMT", sort_types="-1", page_size=500,
    )


async def lhb_seats(date: str, side: str = "BUY") -> list[dict]:
    """龙虎榜营业部买卖席位明细"""
    report = "RPT_BILLBOARD_DAILYDETAILSBUY" if side.upper() == "BUY" else "RPT_BILLBOARD_DAILYDETAILSSELL"
    return await datacenter(
        report,
        filter_=f"(TRADE_DATE>='{date}')(TRADE_DATE<='{date}')",
        sort_columns=side.upper(), sort_types="-1", page_size=1000,
    )


async def margin_history(days: int = 30) -> list[dict]:
    """两融余额历史（沪深京合计）"""
    return await datacenter(
        "RPTA_RZRQ_LSHJ", sort_columns="DIM_DATE", sort_types="-1", page_size=days,
    )


async def hsgt_history(days: int = 30) -> list[dict]:
    """沪深港通历史成交（北向实时净买入已停发，保留成交额口径）"""
    return await datacenter(
        "RPT_MUTUAL_DEAL_HISTORY",
        filter_="(MUTUAL_TYPE=\"001\")",
        sort_columns="TRADE_DATE", sort_types="-1", page_size=days,
    )


async def fast_news(limit: int = 60) -> list[dict]:
    """东财 7x24 快讯"""
    import time as _t

    params = {
        "client": "web", "biz": "web_724", "fastColumn": "102", "sortEnd": "",
        "pageSize": limit, "req_trace": str(int(_t.time() * 1000)),
    }
    data: Any = await http.fetch_json(f"https://{NEWS_HOST}/comm/web/getFastNewsList", source="eastmoney", params=params)
    rows = ((data or {}).get("data") or {}).get("fastNewsList") or []
    out = []
    for r in rows:
        out.append({
            "title": r.get("title") or (r.get("summary") or "")[:60],
            "summary": r.get("summary") or "",
            "time": r.get("showTime") or r.get("publishDate") or "",
            "url": r.get("url_w") or r.get("url_h5") or "",
            "source": "东方财富",
        })
    return out


# ---------------- 中美国债收益率（宏观水位用） ----------------
# 字段代码 → 含义。东财经济数据库的指标代码，长期稳定。
TREASURY_FIELDS = {
    "EMM00588704": "cn2y", "EMM00166466": "cn10y", "EMM00166469": "cn30y",
    "EMG00001306": "us2y", "EMG00001310": "us10y",
}
LEGACY_DC_URL = "https://datacenter.eastmoney.com/api/data/get"
LEGACY_TOKEN = "894050c76af8597a853f5b408b759f5d"


def parse_treasury(rows: list[dict]) -> list[dict]:
    """把国债收益率原始行转成 [{date, cn10y, us10y, ...}]（升序，单位 %）。

    某天某国休市时对应字段为空：保留 None，不能补 0，否则利差会出现假跳变。
    """
    out = []
    for r in rows or []:
        d = str(r.get("SOLAR_DATE") or "")[:10]
        if not d:
            continue
        item = {"date": d}
        for k, name in TREASURY_FIELDS.items():
            item[name] = fnum(r.get(k))
        out.append(item)
    out.sort(key=lambda x: x["date"])
    return out


async def treasury_yield(pages: int = 6, page_size: int = 500) -> list[dict]:
    """中美国债收益率历史（新版 datacenter-web 接口），默认取约 10 年。

    按日期倒序分页拉取，每页 500 行；某页为空就停止，不再继续请求。
    """
    rows: list[dict] = []
    for p in range(1, pages + 1):
        # 复用通用 datacenter 方法，按 SOLAR_DATE 倒序取第 p 页
        batch = await datacenter("RPTA_WEB_TREASURYYIELD", sort_columns="SOLAR_DATE", sort_types="-1",
                                 page_size=page_size, page_number=p)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
    return parse_treasury(rows)


async def treasury_yield_legacy(pages: int = 6, page_size: int = 500) -> list[dict]:
    """同一份数据的旧版接口（datacenter.eastmoney.com + 固定 token），作为新版不可用时的备用。"""
    rows: list[dict] = []
    for p in range(1, pages + 1):
        params = {"type": "RPTA_WEB_TREASURYYIELD", "sty": "ALL", "st": "SOLAR_DATE", "sr": "-1",
                  "token": LEGACY_TOKEN, "p": p, "ps": page_size, "pageNo": p, "pageNum": p}
        data = await http.fetch_json(LEGACY_DC_URL, source="eastmoney", params=params)
        batch = ((data or {}).get("result") or {}).get("data") or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
    return parse_treasury(rows)


# ---------------- 南向资金（港股通） ----------------
async def southbound_history(days: int = 250) -> list[list]:
    """南向资金（港股通沪+深合计）每日成交净买额 → [[date, 净买入(亿元)], ...] 升序。

    MUTUAL_TYPE="006" 是南向合计；NET_DEAL_AMT 单位为百万元。
    北向每日净买入已于 2024-08 停发，但南向仍每日公布。
    """
    rows = await datacenter("RPT_MUTUAL_DEAL_HISTORY", filter_='(MUTUAL_TYPE="006")',
                            sort_columns="TRADE_DATE", sort_types="-1", page_size=days)
    return parse_southbound(rows)


def parse_southbound(rows: list[dict]) -> list[list]:
    """净买额为空（港股休市、单边休市）的日子跳过，不按 0 计。"""
    out = []
    for r in rows or []:
        d = str(r.get("TRADE_DATE") or "")[:10]
        v = fnum(r.get("NET_DEAL_AMT"))
        if d and v is not None:
            out.append([d, round(v / 100, 2)])
    out.sort(key=lambda x: x[0])
    return out


# ---------------- 限售股解禁（按日汇总） ----------------
LIFT_CAP_KEYS = ("ACTUAL_FREE_MARKET_CAP", "FREE_MARKET_CAP", "LIFT_MARKET_CAP")
LIFT_NUM_KEYS = ("LIFT_NUM", "FREE_NUM", "STOCK_NUM")


def parse_lift_days(rows: list[dict]) -> list[dict]:
    """解析每日解禁汇总 → [{date, count, cap_yi}]（升序）。

    字段名没有公开文档：先按候选名取，取不到时按列序取（第 2 列家数、第 4 列实际解禁市值，
    与东财页面表头顺序一致）。实际解禁市值单位为万元。
    """
    out = []
    for r in rows or []:
        keys = list(r.keys())
        d = str(r.get("FREE_DATE") or (r.get(keys[0]) if keys else "") or "")[:10]
        cap_key = next((k for k in LIFT_CAP_KEYS if k in r), None) or (keys[3] if len(keys) > 3 else None)
        num_key = next((k for k in LIFT_NUM_KEYS if k in r), None) or (keys[1] if len(keys) > 1 else None)
        cap = fnum(r.get(cap_key)) if cap_key else None
        if not d or cap is None:
            continue
        num = fnum(r.get(num_key)) if num_key else None
        out.append({"date": d, "count": int(num) if num is not None else None, "cap_yi": round(cap / 1e4, 2)})
    out.sort(key=lambda x: x["date"])
    return out


async def lift_days(start: str, end: str) -> list[dict]:
    """[start, end]（YYYY-MM-DD）期间每天的限售股解禁家数与实际解禁市值（全部 A 股）。"""
    rows = await datacenter(
        "RPT_LIFTDAY_STA",
        filter_=f"(INDEX_CODE=\"000300\")(FREE_DATE>='{start}')(FREE_DATE<='{end}')",
        sort_columns="FREE_DATE", sort_types="1", page_size=500,
    )
    return parse_lift_days(rows)

