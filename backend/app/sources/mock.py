"""离线演示数据源。

作用：
1. REVIEW_OFFLINE=1 时整套系统可脱网演示（出差、内网、断网调试都能跑）；
2. 所有在线源都失败时作为最后兜底，避免前端白屏。
数据为结构真实的样例，非实时。
"""
from __future__ import annotations

import random

INDICES = [
    ("1.000001", "sh000001", "上证指数", 3911.87, 0.94, 994169450166),
    ("0.399001", "sz399001", "深证成指", 13640.87, 1.72, 1082930845525),
    ("0.399006", "sz399006", "创业板指", 3372.68, 2.25, 563_000_000_000),
    ("1.000688", "sh000688", "科创50", 1180.42, 3.10, 96_000_000_000),
    ("0.899050", "bj899050", "北证50", 1420.66, -0.85, 12_000_000_000),
    ("1.000852", "sh000852", "中证1000", 6820.15, 2.05, 210_000_000_000),
    ("0.399303", "sz399303", "国证2000", 8210.44, 2.38, 180_000_000_000),
    ("1.000985", "sh000985", "中证全指", 5320.18, 1.55, 2_100_000_000_000),
]

ZT_SAMPLE = [
    ("001216", "华瓷股份", 4, "家居用品", 21.87, 4.96e8, 5.4e9, 9.3, 93009, 95639, 9.83e7, 1),
    ("603248", "锡华科技", 4, "专用设备", 24.57, 5.65e8, 1.76e9, 33.2, 93058, 95255, 4.89e7, 1),
    ("002285", "世运电路", 3, "房地产服", 2.89, 7.11e8, 5.72e9, 12.9, 93515, 132506, 4.10e7, 1),
    ("002185", "华天科技", 2, "半导体", 18.03, 6.39e9, 5.8e10, 12.1, 93012, 94501, 3.3e8, 0),
    ("603986", "兆易创新", 2, "半导体", 388.18, 4.2e9, 2.6e11, 6.4, 93101, 100233, 2.1e8, 0),
    ("300502", "新易盛", 1, "通信设备", 445.00, 8.1e9, 3.6e11, 9.8, 100512, 103015, 1.5e8, 0),
    ("001376", "中通能源", 1, "电力", 12.66, 1.47e8, 2.72e9, 5.4, 92500, 92500, 1.07e8, 0),
    ("002453", "华软科技", 1, "化学制品", 5.34, 4.47e8, 3.43e9, 13.4, 92500, 104115, 3.92e7, 1),
]

SECTORS = [
    ("BK1121", "文化传媒半导体", 4.96, 1.22e8, 4, 0, "东微半导", "688261", 15.16),
    ("BK0501", "半导体", 4.66, 3.67e9, 157, 5, "锡华科技", "001233", 9.99),
    ("BK1326", "半导体设备", 4.83, 1.82e9, 23, 2, "华海清科", "301583", 9.98),
    ("BK1331", "存储芯片概念", 4.68, 7.54e9, 53, 1, "南大光电", "603316", 9.97),
    ("BK1051", "算力租赁", 3.88, -3.78e8, 6, 3, "锡华科技", "603248", 9.98),
    ("BK0736", "光伏设备", -2.14, -1.25e9, 3, 41, "隆基绿能", "601012", -3.21),
    ("BK0475", "银行", -0.62, -8.6e8, 2, 30, "招商银行", "600036", -0.88),
]

LHB = [
    ("000002", "万科A", 9.93, 3.32, 6.71e8, 1.45e8, 5.25e8, "日涨幅偏离值达到7%的前5只证券"),
    ("002185", "华天科技", 10.01, 18.03, 3.34e8, 1.47e8, 1.86e8, "日涨幅偏离值达到7%的前5只证券"),
    ("000978", "桂林旅游", 4.89, 8.36, 1.84e8, 9.13e7, 9.30e7, "连续三个交易日内涨幅偏离值累计达到15%"),
    ("603248", "锡华科技", 10.00, 24.57, 2.10e8, 1.02e8, 1.08e8, "日涨幅偏离值达到7%的前5只证券"),
]

SEATS = [
    ("机构专用", 3.31e8, 0.0, 3.31e8, "000002"),
    ("国泰海通证券股份有限公司上海江苏路证券营业部", 2.10e8, 1.20e7, 1.98e8, "002185"),
    ("东方财富证券股份有限公司拉萨团结路第二证券营业部", 1.55e8, 8.60e7, 6.90e7, "603248"),
    ("中国银河证券股份有限公司绍兴证券营业部", 1.20e8, 3.00e6, 1.17e8, "001216"),
    ("中信证券股份有限公司上海溧阳路证券营业部", 9.80e7, 2.40e7, 7.40e7, "002285"),
]

GLOBAL = [
    ("道琼斯", "美股", 51682.64, -0.18, -95.40),
    ("纳斯达克", "美股", 26522.55, 0.39, 104.25),
    ("标普500", "美股", 7650.50, 0.17, 12.74),
    ("费城半导体", "美股", 11921.69, 2.78, 322.19),
    ("纳斯达克中国金龙", "中概", 5787.39, 0.76, 43.77),
    ("日经225", "亚太", 65018.95, 1.38, 882.70),
    ("韩国KOSPI", "亚太", 6894.23, 2.66, 178.82),
    ("台湾加权", "亚太", 47180.75, 1.93, 892.75),
    ("恒生指数", "港股", 24750.78, 0.60, 146.49),
    ("恒生科技指数", "港股", 4405.50, 2.20, 94.76),
    ("美元指数", "汇率商品", 100.22, -0.01, -0.01),
    ("离岸人民币", "汇率商品", 6.6943, 0.02, 0.00),
    ("NYMEX原油", "汇率商品", 95.41, -1.87, -1.82),
    ("COMEX黄金", "汇率商品", 4418.56, 0.43, 18.86),
    ("富时中国A50期货", "期货", 14484.50, 0.62, 89.00),
]

NEWS = [
    ("证监会：进一步扩大资本市场高水平对外开放", "强调持续深化资本市场投融资综合改革，稳步扩大制度型开放。", "政策"),
    ("国产存储厂商扩产超预期，设备招标量环比+45%", "多家晶圆厂上调 2026 年资本开支指引，刻蚀/薄膜设备订单饱满。", "行业"),
    ("英伟达发布新一代推理芯片，性能提升 3 倍", "带动美股费城半导体指数收涨 2.78%。", "海外"),
    ("央行开展 6000 亿元 MLF 操作，利率维持不变", "本月有 4000 亿元 MLF 到期，实现净投放 2000 亿元。", "宏观"),
    ("华为新品发布会定档，产业链公司获机构调研", "消费电子、光学、结构件环节受关注。", "行业"),
]


def quotes() -> list[dict]:
    rnd = random.Random(20260918)
    out = []
    for secid, sym, name, price, pctv, amount in INDICES:
        prev = round(price / (1 + pctv / 100), 2)
        out.append({
            "code": secid, "symbol": sym, "name": name, "price": price, "prev_close": prev,
            "open": round(prev * (1 + rnd.uniform(-0.003, 0.006)), 2),
            "high": round(price * 1.004, 2), "low": round(prev * 0.996, 2),
            "change": round(price - prev, 2), "pct": pctv,
            "volume": round(amount / price / 100, 0), "amount": float(amount),
            "turnover": None, "float_mv": None, "total_mv": None, "time": "20260918150000",
        })
    return out


def zt_pool() -> dict:
    pool = []
    for code, name, lbc, hy, price, amount, ltsz, hs, fbt, lbt, fund, zbc in ZT_SAMPLE:
        pool.append({
            "c": code, "n": name, "lbc": lbc, "hybk": hy, "p": price * 1000, "zdp": 10.0,
            "amount": amount, "ltsz": ltsz, "tshare": ltsz * 1.4, "hs": hs,
            "fbt": fbt, "lbt": lbt, "fund": fund, "zbc": zbc,
            "zttj": {"days": lbc, "ct": lbc},
        })
    return {"tc": len(pool), "qdate": 20260918, "pool": pool}


def zb_pool() -> dict:
    return {"tc": 2, "qdate": 20260918, "pool": [
        {"c": "002080", "n": "中材科技", "p": 60220, "ztp": 64560, "zdp": 2.61,
         "amount": 6.87e9, "ltsz": 1.01e11, "hs": 6.8, "fbt": 93812, "zbc": 2, "hybk": "电池"},
        {"c": "600100", "n": "同方股份", "p": 8120, "ztp": 8860, "zdp": 1.25,
         "amount": 1.2e9, "ltsz": 2.4e10, "hs": 5.1, "fbt": 101523, "zbc": 1, "hybk": "计算机"},
    ]}


def dt_pool() -> dict:
    return {"tc": 0, "qdate": 20260918, "pool": []}


def zdfenbu() -> dict:
    fenbu = {"11": 78, "10": 53, "9": 19, "8": 51, "7": 71, "6": 121, "5": 196, "4": 387,
             "3": 684, "2": 1153, "1": 1292, "0": 154, "-1": 730, "-2": 261, "-3": 62,
             "-4": 24, "-5": 11, "-6": 3, "-7": 1, "-8": 1, "-9": 1, "-10": 0, "-11": 0}
    return {"qdate": 20260918, "fenbu": [{str(k): v} for k, v in fenbu.items()]}


def boards(kind: str = "industry") -> list[dict]:
    rows = SECTORS if kind == "industry" else SECTORS[::-1]
    return [{"f12": c, "f14": n, "f3": pctv, "f62": flow, "f104": up, "f105": down,
             "f128": lead, "f140": lead_code, "f136": lead_pct,
             "f2": round(1000 + i * 137.5, 2)} for i, (c, n, pctv, flow, up, down, lead, lead_code, lead_pct) in enumerate(rows)]


def lhb() -> list[dict]:
    return [{"SECURITY_CODE": c, "SECURITY_NAME_ABBR": n, "CHANGE_RATE": chg, "CLOSE_PRICE": close,
             "BILLBOARD_BUY_AMT": buy, "BILLBOARD_SELL_AMT": sell, "BILLBOARD_NET_AMT": net,
             "EXPLANATION": reason, "TRADE_DATE": "2026-09-18 00:00:00", "ACCUM_AMOUNT": buy * 3}
            for c, n, chg, close, buy, sell, net, reason in LHB]


def seats() -> list[dict]:
    return [{"OPERATEDEPT_NAME": name, "BUY": buy, "SELL": sell, "NET": net, "SECURITY_CODE": code,
             "TRADE_DATE": "2026-09-18 00:00:00", "RISE_PROBABILITY_3DAY": 55.0,
             "TOTAL_BUYER_SALESTIMES_3DAY": 20} for name, buy, sell, net, code in SEATS]


def global_quotes() -> list[dict]:
    return [{"name": n, "group": g, "price": p, "pct": pctv, "change": chg, "time": "2026-09-19 05:00:00"}
            for n, g, p, pctv, chg in GLOBAL]


def news() -> list[dict]:
    return [{"title": t, "summary": s, "time": f"2026-09-19 0{i}:1{i}:00", "url": "", "source": "样例数据",
             "tags": [tag]} for i, (t, s, tag) in enumerate(NEWS)]


def kline(n: int = 120) -> list[list]:
    rnd = random.Random(7)
    out, price, base = [], 3700.0, 4.5e11
    for i in range(n):
        chg = rnd.uniform(-0.018, 0.019)
        o = price
        c = round(price * (1 + chg), 2)
        h = round(max(o, c) * (1 + rnd.uniform(0, 0.006)), 2)
        l = round(min(o, c) * (1 - rnd.uniform(0, 0.006)), 2)
        v = base * rnd.uniform(0.7, 1.4)
        d = (1750000000 + i * 86400)
        import datetime as dt

        out.append([dt.datetime.utcfromtimestamp(d).strftime("%Y-%m-%d"), o, c, h, l, round(v / 100, 0), v])
        price = c
    return out