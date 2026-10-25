"""标的与指数清单（含各家数据源的代码映射）。

一个资产 = 多个来源的代码，任何一个来源挂了都能自动切换。
role 字段是「游资视角」下这个指标为什么要看，前端会作为提示展示。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Asset:
    key: str
    name: str
    group: str
    tx: str | None = None       # 腾讯代码
    sina: str | None = None     # 新浪代码
    sina_kind: str = "stock"    # stock/us/int/znb/b/hf/fx
    em: str | None = None       # 东财 secid
    yahoo: str | None = None
    stooq: str | None = None
    role: str = ""
    unit: str = ""
    extra: dict = field(default_factory=dict)


# ---------------- A股核心指数 ----------------
A_INDEXES: list[Asset] = [
    Asset("sh000001", "上证指数", "A股指数", "sh000001", "sh000001", "stock", "1.000001",
          role="权重/银行石油风向标；3000-4000点区间的箱体位置决定仓位上限"),
    Asset("sz399001", "深证成指", "A股指数", "sz399001", "sz399001", "stock", "0.399001",
          role="中盘成长代表，与创业板共同判断成长风格强弱"),
    Asset("sz399006", "创业板指", "A股指数", "sz399006", "sz399006", "stock", "0.399006",
          role="游资主战场的beta；创业板走强时连板高度才打得开"),
    Asset("sh000688", "科创50", "A股指数", "sh000688", "sh000688", "stock", "1.000688",
          role="硬科技/半导体主线温度计，与费城半导体联动"),
    Asset("bj899050", "北证50", "A股指数", "bj899050", "bj899050", "stock", "0.899050",
          role="小票情绪极端放大器，北证大涨常是情绪高潮/透支信号"),
    Asset("sh000300", "沪深300", "A股指数", "sh000300", "sh000300", "stock", "1.000300",
          role="机构定价锚；沪深300强而中证1000弱=风格切大盘，游资要降仓"),
    Asset("sh000905", "中证500", "A股指数", "sh000905", "sh000905", "stock", "1.000905",
          role="中盘风格"),
    Asset("sh000852", "中证1000", "A股指数", "sh000852", "sh000852", "stock", "1.000852",
          role="小盘股beta，游资最敏感的风格指数"),
    Asset("sz399303", "国证2000", "A股指数", "sz399303", "sz399303", "stock", "0.399303",
          role="微盘/题材股风向，2000走强才有普涨连板行情"),
    Asset("sh000985", "中证全指", "A股指数", "sh000985", "sh000985", "stock", "1.000985",
          role="全市场等权感受，判断普涨还是权重护盘"),
    Asset("sz399101", "中小综指", "A股指数", "sz399101", "sz399101", "stock", "0.399101",
          role="中小盘综合"),
]

# ---------------- 外围市场 ----------------
GLOBAL_ASSETS: list[Asset] = [
    # 美股（隔夜直接影响A股开盘情绪，费半→半导体、金龙→中概/港股）
    Asset("DJI", "道琼斯", "美股", "usDJI", "gb_$dji", "us", "100.DJIA", "^DJI", "^dji",
          role="隔夜美股风险偏好；道指与纳指背离时看结构"),
    Asset("IXIC", "纳斯达克", "美股", "usIXIC", "gb_$ixic", "us", "100.NDX", "^IXIC", "^ndq",
          role="科技股风向，决定A股AI/算力/半导体开盘溢价"),
    Asset("SPX", "标普500", "美股", "usINX", "gb_$inx", "us", "100.SPX", "^GSPC", "^spx",
          role="全球风险资产总开关"),
    Asset("SOX", "费城半导体", "美股", None, "gb_$sox", "us", None, "^SOX", None,
          role="★半导体主线最直接的外盘锚，费半大涨A股芯片高开概率极高"),
    Asset("VIX", "VIX恐慌指数", "美股", "usVIX", None, "", None, "^VIX", None,
          role=">20 警惕全球risk-off，>30 应大幅降仓", unit=""),
    Asset("HXC", "纳斯达克中国金龙", "中概", "usHXC", "gb_$hxc", "us", None, None,
          role="★中概隔夜表现，与港股/A股情绪高度同步，是A股开盘前最好的先行指标"),
    Asset("N225", "日经225", "亚太", None, "int_nikkei", "int", "100.N225", "^N225", "^nkx",
          role="亚太风险偏好+日元套息交易；日经大跌常伴随全球科技股调整"),
    Asset("KS11", "韩国KOSPI", "亚太", None, "znb_KOSPI", "znb", "100.KS11", "^KS11", "^kospi",
          role="★存储/半导体产业链同步指标（三星、海力士权重高）"),
    Asset("TWII", "台湾加权", "亚太", None, "b_TWSE", "b", "100.TWII", None, None,
          role="台积电权重，代工/先进制程景气度"),
    Asset("HSI", "恒生指数", "港股", "hkHSI", "int_hangseng", "int", "100.HSI", "^HSI", None,
          role="与A股同步开盘，港股弱A股难独立走强"),
    Asset("HSTECH", "恒生科技", "港股", "hkHSTECH", None, "", None, None,
          role="★互联网/AI应用情绪，A股TMT板块的日内参照"),
    Asset("HSCEI", "国企指数", "港股", "hkHSCEI", None, "", None, None,
          role="中资资产折溢价，AH价差影响蓝筹"),
    Asset("UDI", "美元指数", "汇率商品", None, None, "", "100.UDI", "DX-Y.NYB", "usd_i",
          role="美元走强→人民币承压→外资流出+有色/成长承压"),
    Asset("USDCNH", "离岸人民币", "汇率商品", None, "fx_susdcnh", "fx", None, "CNH=X", None,
          role="★贬值加速时警惕权重护盘失败、题材杀跌", unit=""),
    Asset("CL", "NYMEX原油", "汇率商品", None, "hf_CL", "hf", None, "CL=F", "cl.f",
          role="通胀与石油石化板块，油价急涨利空航空/化工下游"),
    Asset("GC", "COMEX黄金", "汇率商品", None, "hf_GC", "hf", None, "GC=F", "gc.f",
          role="避险情绪，金价大涨常对应股票risk-off"),
    Asset("SI", "COMEX白银", "汇率商品", None, "hf_SI", "hf", None, "SI=F", "si.f",
          role="工业+避险双属性，弹性大于黄金"),
    Asset("A50", "富时中国A50期货", "期货", None, "hf_CHA50CFD", "hf", None, None, None,
          role="★★A股开盘前唯一的实时先行指标，9:00前看它定开盘策略"),
    Asset("FTSE", "英国富时100", "欧美", None, None, "", "100.FTSE", None, None, role="欧洲风险偏好"),
    Asset("GDAXI", "德国DAX", "欧美", None, None, None, "100.GDAXI", "^GDAXI", None, role="欧洲风险偏好"),
    Asset("US10Y", "美国10年期国债收益率", "利率", None, None, "", None, "^TNX", "10yusy.b",
          role="★全球估值分母；快速上行压制高估值成长（创业板/科创）", unit="%"),
]

# 两市成交额构成（用于计算「两市总成交」）
TURNOVER_KEYS = ["sh000001", "sz399001"]

ASSET_MAP: dict[str, Asset] = {a.key: a for a in A_INDEXES + GLOBAL_ASSETS}


def by_keys(keys: list[str]) -> list[Asset]:
    return [ASSET_MAP[k] for k in keys if k in ASSET_MAP]