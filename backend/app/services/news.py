"""资讯服务：多源 7x24 快讯聚合 + 去重 + 题材打标 + 关键词热度。

游资看消息的方式不是「读新闻」，而是「找催化」：
把消息映射到板块/个股，再和当天涨停结构对照，判断题材是「新催化」还是「旧闻发酵」。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from ..core import cache
from ..core.config import settings
from ..sources import cls_source, eastmoney as em, mock, sina, wallstcn

TAG_RULES: list[tuple[str, list[str]]] = [
    ("政策", ["证监会", "央行", "国务院", "发改委", "财政部", "工信部", "政策", "会议", "条例", "监管",
              "降准", "降息", "LPR", "MLF", "印花税", "国常会", "政治局", "十四五", "补贴", "专项债"]),
    ("半导体", ["芯片", "半导体", "晶圆", "光刻", "存储", "DRAM", "NAND", "HBM", "封装", "封测",
                "EDA", "台积电", "英伟达", "ASML", "先进制程", "国产替代"]),
    ("AI算力", ["AI", "人工智能", "算力", "光模块", "液冷", "数据中心", "大模型", "GPU", "CPO",
                "智算", "服务器", "英伟达", "OpenAI", "推理", "IDC"]),
    ("机器人", ["机器人", "人形", "减速器", "丝杠", "伺服", "灵巧手", "特斯拉Optimus", "具身智能"]),
    ("新能源", ["光伏", "锂电", "电池", "储能", "风电", "氢能", "固态电池", "充电桩", "新能源车", "碳酸锂"]),
    ("军工", ["军工", "航天", "导弹", "无人机", "低空经济", "商业航天", "卫星", "国防"]),
    ("医药", ["医药", "创新药", "生物", "疫苗", "医疗器械", "CXO", "集采", "GLP-1", "减肥药"]),
    ("消费", ["消费", "白酒", "食品", "零售", "旅游", "免税", "家电", "汽车", "以旧换新"]),
    ("金融地产", ["银行", "券商", "保险", "地产", "房地产", "城投", "REITs"]),
    ("周期资源", ["有色", "稀土", "黄金", "原油", "煤炭", "钢铁", "化工", "锂", "铜", "铝"]),
    ("海外", ["美联储", "美股", "纳斯达克", "标普", "关税", "出口管制", "制裁", "日元", "欧央行",
              "特朗普", "拜登", "美债", "通胀数据", "非农", "地缘"]),
    ("宏观数据", ["CPI", "PPI", "GDP", "PMI", "社融", "M2", "M1", "就业", "失业率", "进出口", "工业增加值"]),
    ("公司事件", ["公告", "中标", "增持", "减持", "回购", "业绩预增", "业绩预告", "定增", "重组",
                  "收购", "停牌", "立案", "处罚", "解禁", "分红", "股权激励"]),
]

CODE_RE = re.compile(r"(?<!\d)(6\d{5}|0\d{5}|3\d{5}|8\d{5}|4\d{5}|9\d{5})(?!\d)")
BRACKET_RE = re.compile(r"[【\[]([^】\]]{2,12})[】\]]")

# 题材热度词典（用于统计当日消息面在炒什么）
HOT_WORDS = [
    "半导体", "存储", "HBM", "算力", "光模块", "液冷", "CPO", "AI", "大模型", "机器人", "人形机器人",
    "固态电池", "光伏", "储能", "锂电", "新能源车", "军工", "低空经济", "商业航天", "创新药", "减肥药",
    "国企改革", "并购重组", "化债", "房地产", "消费", "白酒", "有色", "黄金", "稀土", "煤炭",
    "券商", "数字货币", "数据要素", "信创", "华为", "苹果", "英伟达", "特斯拉", "关税", "美联储",
    "降准", "降息", "反内卷", "并购六条", "科创板", "北交所", "退市", "减持", "回购",
]


def _tag(text: str) -> list[str]:
    tags = []
    for tag, kws in TAG_RULES:
        if any(k.lower() in text.lower() for k in kws):
            tags.append(tag)
    return tags[:3]


def _extract(text: str) -> dict:
    codes = list(dict.fromkeys(CODE_RE.findall(text)))[:6]
    names = [n for n in BRACKET_RE.findall(text) if 2 <= len(n) <= 8][:4]
    return {"codes": codes, "names": names}


def _dedupe_key(title: str) -> str:
    t = re.sub(r"[\s【】\[\]（）()：:，,。.、!！?？\-—]", "", title or "")[:40]
    return hashlib.md5(t.encode("utf-8")).hexdigest()[:12]


async def _src_wallstcn(limit: int) -> list[dict]:
    rows = await wallstcn.lives("global", limit)
    rows += await wallstcn.lives("a股", max(10, limit // 2))
    return rows


async def _src_em(limit: int) -> list[dict]:
    return await em.fast_news(limit)


async def _src_sina(limit: int) -> list[dict]:
    return await sina.news(limit)


async def _src_cls(limit: int) -> list[dict]:
    return await cls_source.telegraph(limit)


def _src_mock(limit: int) -> list[dict]:
    return mock.news()


REGISTRY = {"wallstcn": _src_wallstcn, "eastmoney": _src_em, "sina": _src_sina, "cls": _src_cls, "mock": _src_mock}


async def aggregate(limit: int = 120, force: bool = False, sources: list[str] | None = None) -> dict:
    """并发拉取多个资讯源，合并去重后按时间倒序。"""
    import asyncio

    names = sources or [n for n, _ in cache.order_providers("news", REGISTRY) if n != "mock"]
    tasks = []
    used: list[str] = []
    for n in names:
        fn = REGISTRY.get(n)
        if not fn:
            continue
        used.append(n)
        tasks.append(_safe(fn, limit))
    results = await asyncio.gather(*tasks) if tasks else []
    rows: list[dict] = []
    ok_sources = []
    for n, res in zip(used, results):
        if res:
            ok_sources.append(n)
            rows.extend(res)
    if not rows:
        rows = _src_mock(limit)
        ok_sources = ["mock"]

    seen: set[str] = set()
    merged: list[dict] = []
    for r in rows:
        title = (r.get("title") or "").strip()
        summary = (r.get("summary") or "").strip()
        if not title and not summary:
            continue
        k = _dedupe_key(title or summary)
        if k in seen:
            continue
        seen.add(k)
        text = f"{title} {summary}"
        ex = _extract(text)
        important = bool(r.get("important")) or _is_important(title, summary)
        merged.append({
            "title": title or summary[:60],
            "summary": summary,
            "time": r.get("time") or "",
            "url": r.get("url") or "",
            "source": r.get("source") or n,
            "tags": sorted(set((r.get("tags") or []) + _tag(text))),
            "codes": ex["codes"],
            "names": ex["names"],
            "important": important,
        })
    merged.sort(key=lambda x: x["time"] or "", reverse=True)
    merged = merged[:limit]

    return {
        "items": merged,
        "count": len(merged),
        "sources_ok": ok_sources,
        "sources_tried": used,
        "hot_words": hot_words(merged),
        "tag_stat": tag_stat(merged),
    }


IMPORTANT_KW = ["证监会", "央行", "国务院", "政治局", "国常会", "降准", "降息", "LPR", "财政部",
                "发改委", "印花税", "关税", "出口管制", "制裁", "美联储", "加息", "降息",
                "立案", "退市", "停牌", "重组", "并购", "国务院常务会议", "中央经济工作会议"]


def _is_important(title: str, summary: str) -> bool:
    text = f"{title} {summary}"
    if title.startswith("【") and any(k in text for k in IMPORTANT_KW):
        return True
    return any(k in title for k in IMPORTANT_KW)


async def _safe(fn: Any, limit: int) -> list[dict]:
    try:
        res = await fn(limit)
        return res if isinstance(res, list) else []
    except Exception:  # noqa: BLE001
        return []


def hot_words(items: list[dict], top: int = 24) -> list[dict]:
    cnt: dict[str, int] = {}
    for it in items:
        text = f"{it.get('title','')} {it.get('summary','')}"
        for w in HOT_WORDS:
            if w.lower() in text.lower():
                cnt[w] = cnt.get(w, 0) + 1
    return [{"word": k, "count": v} for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])[:top] if v >= 1]


def tag_stat(items: list[dict]) -> list[dict]:
    cnt: dict[str, int] = {}
    for it in items:
        for t in it.get("tags") or []:
            cnt[t] = cnt.get(t, 0) + 1
    return [{"tag": k, "count": v} for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])]


async def feed(limit: int = 120, source: str = "", tag: str = "", keyword: str = "",
               force: bool = False) -> dict:
    data = await cache.chain(
        [("multi", lambda: aggregate(limit=max(limit, 150), force=force))],
        cache_key=f"news:{max(limit,150)}", ttl=settings.ttl_news, force=force,
        validator=lambda r: bool(r) and bool(r.get("items")),
    )
    d: dict = data.data or {"items": [], "hot_words": [], "tag_stat": [], "sources_ok": []}
    items = d.get("items") or []
    if source:
        items = [i for i in items if source in (i.get("source") or "")]
    if tag:
        items = [i for i in items if tag in (i.get("tags") or [])]
    if keyword:
        kw = keyword.lower()
        items = [i for i in items if kw in (i.get("title", "") + i.get("summary", "")).lower()]
    return {**d, "items": items[:limit], "filter": {"source": source, "tag": tag, "keyword": keyword},
            "meta": data.meta()}