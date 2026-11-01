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
          role="沪市全部股票，银行石油等权重占比大；它涨而多数股票跌=权重护盘，赚钱效应差"),
    Asset("sz399001", "深证成指", "A股指数", "sz399001", "sz399001", "stock", "0.399001",
          role="深市市值最大的 500 只，偏新能源、消费、科技；和上证对比看资金偏哪边"),
    Asset("sz399006", "创业板指", "A股指数", "sz399006", "sz399006", "stock", "0.399006",
          role="创业板前 100 大成长股，涨跌幅限制 20%；走强时连板高度才容易打开"),
    Asset("sh000688", "科创50", "A股指数", "sh000688", "sh000688", "stock", "1.000688",
          role="科创板前 50 大硬科技，半导体权重高；常与费城半导体联动"),
    Asset("bj899050", "北证50", "A股指数", "bj899050", "bj899050", "stock", "0.899050",
          role="北交所前 50 大，涨跌幅限制 30%、波动大；急涨常见于小票情绪高潮"),
    Asset("sh000016", "上证50", "A股指数", "sh000016", "sh000016", "stock", "1.000016",
          role="沪市最大的 50 只蓝筹，是股指期货 IH 的标的；走强多为权重护盘或资金避险"),
    Asset("sh000300", "沪深300", "A股指数", "sh000300", "sh000300", "stock", "1.000300",
          role="两市最大的 300 只，机构定价锚；它强而中证1000弱=资金偏大盘，题材环境变差"),
    Asset("sh000905", "中证500", "A股指数", "sh000905", "sh000905", "stock", "1.000905",
          role="沪深300之后的 500 只中盘股，是股指期货 IC 的标的；代表中盘风格"),
    Asset("sh000852", "中证1000", "A股指数", "sh000852", "sh000852", "stock", "1.000852",
          role="中证500之后的 1000 只小盘股，是股指期货 IM 的标的；对题材资金最敏感"),
    Asset("sz399303", "国证2000", "A股指数", "sz399303", "sz399303", "stock", "0.399303",
          role="市值更小的 2000 只，代表小微盘和题材股；走强才有普涨和连板行情"),
    Asset("sh000985", "中证全指", "A股指数", "sh000985", "sh000985", "stock", "1.000985",
          role="几乎全部 A 股、按市值加权，代表市场总貌；跌幅大于上证说明中小盘更弱"),
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
    # 腾讯 usVIX 停更在 2026-09，且排在新浪之前会挡住可用数据，所以不配腾讯代码
    Asset("VIX", "VIX恐慌指数", "美股", None, "znb_VIX", "znb", None, "^VIX", None,
          role="标普期权隐含的未来波动，越高越恐慌；>20 警惕全球避险，>30 应大幅降仓", unit=""),
    Asset("HXC", "纳斯达克中国金龙", "中概", "usHXC", "gb_$hxc", "us", None, None,
          role="★中概隔夜表现，与港股/A股情绪高度同步，是A股开盘前最好的先行指标"),
    # 新浪 int_nikkei、b_TWSE 已停更（后者停在 2025-09-26），改用 znb_ 系列
    Asset("N225", "日经225", "亚太", None, "znb_NKY", "znb", "100.N225", "^N225", "^nkx",
          role="亚太风险偏好+日元套息交易；日经大跌常伴随全球科技股调整"),
    Asset("KS11", "韩国KOSPI", "亚太", None, "znb_KOSPI", "znb", "100.KS11", "^KS11", "^kospi",
          role="★存储/半导体产业链同步指标（三星、海力士权重高）"),
    Asset("TWII", "台湾加权", "亚太", None, "znb_TWJQ", "znb", "100.TWII", None, None,
          role="台积电权重，代工/先进制程景气度"),
    Asset("HSI", "恒生指数", "港股", "hkHSI", "znb_HSI", "znb", "100.HSI", "^HSI", None,
          role="与A股同步开盘，港股弱A股难独立走强"),
    Asset("HSTECH", "恒生科技", "港股", "hkHSTECH", None, "", None, None,
          role="★互联网/AI应用情绪，A股TMT板块的日内参照"),
    Asset("HSCEI", "国企指数", "港股", "hkHSCEI", None, "", None, None,
          role="中资资产折溢价，AH价差影响蓝筹"),
    Asset("UDI", "美元指数", "汇率商品", None, "DINIW", "dini", "100.UDI", "DX-Y.NYB", "usd_i",
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
    Asset("US10Y", "美国10年期国债收益率", "利率", None, "globalbd_us10yt", "bond", None, "^TNX", "10yusy.b",
          role="★全球估值分母；快速上行压制高估值成长（创业板/科创）", unit="%"),
]

ASSET_MAP: dict[str, Asset] = {a.key: a for a in A_INDEXES + GLOBAL_ASSETS}