"""规则参数的唯一来源：权重、阈值、统计设置、成本模型。

为什么要把参数从代码里抽出来单独成文件？
因为散落在代码里的魔法数无法做三件专业研究必须做的事：
1. **版本化**——报告里必须能写清"这个分数是哪一版规则算的"，否则昨天和今天
   的分数不可比，历史快照也无法解释。
2. **指纹化**——参数哈希（digest）进入冻结的信号记录后，别人（或半年后的你）
   才能验证"当时用的确实是这组参数"，这是防止事后调参的唯一技术手段。
3. **敏感性扫描**——专业团队判断一组阈值是过拟合还是稳健，靠的是把参数整体
   扰动 ±N% 再看结论是否翻转（参数高原 vs 参数尖峰）。参数必须可被程序整体
   替换，这件事才做得到。

本文件只放"人为选定的数字"。所有数字都是经验先验，没有任何一个经过本项目
内的统计估计，因此 `evidence` 字段统一标为 prior。
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

# 规则版本：任何阈值/权重改动都必须手工 +1，否则历史分数不可比。
PARAM_VERSION = "params-2026.10-r2"

# ---------------------------------------------------------------- 情绪因子
# weight：加权总分里的占比（会在使用处归一化，便于扰动后仍然求和为 1）
# 其余键：该因子从原始值折算到 0-100 分的形状参数
SENTIMENT: dict[str, dict[str, Any]] = {
    "limit_up": {
        "weight": 0.18, "scale": 90.0,
        "desc": "涨停家数 / scale * 100，封顶 100",
    },
    "max_boards": {
        "weight": 0.15,
        "ladder": {0: 0.0, 1: 15.0, 2: 38.0, 3: 55.0, 4: 70.0, 5: 80.0, 6: 88.0, 7: 94.0},
        "cap": 96.0,
        "desc": "最高连板高度查表打分",
    },
    "broken_rate": {
        "weight": 0.13, "slope": 1.7,
        "desc": "100 - 炸板率 * slope",
    },
    "limit_down": {
        "weight": 0.12,
        "steps": [[0, 100.0], [3, 85.0], [8, 60.0], [20, 35.0]], "floor": 12.0,
        "desc": "跌停家数分档",
    },
    "tradable_premium": {
        "weight": 0.17, "center": 50.0, "slope": 12.0, "missing": 55.0,
        "desc": "昨日涨停样本中『今日开盘确实可买入』部分的开盘->收盘收益",
    },
    "up_ratio": {
        "weight": 0.15, "slope": 1.25, "offset": 25.0,
        "desc": "上涨家数占比 * slope - offset",
    },
    "promote_rate": {
        "weight": 0.10, "slope": 2.2, "missing": 45.0,
        "desc": "晋级率 * slope",
    },
}

# ---------------------------------------------------------------- 综合评分
COMPOSITE: dict[str, float] = {
    "sentiment": 0.50,
    "turnover": 0.20,
    "global": 0.15,
    "main_line": 0.15,
}

# ---------------------------------------------------------------- 选股器阈值
SCREENER: dict[str, dict[str, Any]] = {
    "first_board": {
        "base": 40.0,
        "seal_ratio": [[30.0, 30.0], [10.0, 20.0]], "seal_ratio_weak": [3.0, -15.0],
        "float_mv_sweet": [20.0, 120.0, 20.0], "float_mv_large": [300.0, -10.0],
        "turnover_sweet": [5.0, 20.0, 15.0], "turnover_high": [35.0, -10.0],
        "early_seal_minute": 600, "early_seal_bonus": 15.0,
        "no_break_bonus": 10.0, "break_penalty": 10.0,
        "hot_sector_bonus": 20.0,
    },
    "relay": {
        "board_mult": 12.0, "no_break_bonus": 20.0, "break_penalty": 15.0,
        "big_fund": [1e8, 18.0], "hot_sector_bonus": 20.0,
        "one_word_penalty": 5.0, "early_seal_minute": 580, "early_seal_bonus": 12.0,
    },
    "auction": {
        "max_gap": {"first_board": 6.5, "default": 7.5},
        "min_amount_ratio": {"first_board": 2.0, "default": 3.0},
        "give_up_gap": -3.0, "sealed_gap": 9.5,
    },
}

# ---------------------------------------------------------------- 统计设置
STATS: dict[str, Any] = {
    # 低于这个样本量只报中位数与区间，禁止把均值当结论（小样本均值被单只极端值主导）
    "min_sample": 30,
    "bootstrap_iters": 2000,
    "permutation_iters": 5000,
    "ci": 0.95,
    # 固定随机种子：同一输入必须复算出同一 p 值，否则第三方无法复核
    "seed": 20261024,
    # 参数敏感性扫描幅度
    "perturb": 0.20,
}

# ---------------------------------------------------------------- 交易成本
# 单位 bps（万分之一）。短线策略的生死线常常就在这里，必须版本化而不是口算。
COST: dict[str, float] = {
    "commission_bps": 2.5,      # 佣金（双边各收，万 2.5）
    "min_commission": 5.0,      # 单笔最低佣金（元）
    "stamp_duty_bps": 5.0,      # 印花税（仅卖出，千分之 0.5）
    "transfer_bps": 0.1,        # 过户费（双边，万分之 0.1）
    "slippage_bps": 30.0,       # 滑点假设（短线打板冲击成本，保守值）
}

PRIOR_NOTE = ("本文件所有数字均为经验先验（prior），未经本项目内的统计估计或样本外验证。"
              "任何基于它们的评分只能解释为『规则排序』，不能解释为收益概率。")


def snapshot() -> dict[str, Any]:
    """返回当前全部参数的深拷贝，用于写入冻结记录与敏感性扫描。"""
    return copy.deepcopy({
        "version": PARAM_VERSION,
        "sentiment": SENTIMENT,
        "composite": COMPOSITE,
        "screener": SCREENER,
        "stats": STATS,
        "cost": COST,
    })


def digest(params: dict[str, Any] | None = None) -> str:
    """参数指纹：规范化 JSON 的 sha256 前 12 位。

    冻结信号时写入这个值，日后就能验证"当天用的是不是这组参数"。
    sort_keys 保证同一组参数在任何机器上得到同一指纹。
    """
    p = params or snapshot()
    blob = json.dumps(p, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _scale_numbers(obj: Any, factor: float, skip_keys: tuple[str, ...] = ("weight",)) -> Any:
    """递归地把数值按 factor 缩放；weight 单独处理，避免破坏归一化。"""
    if isinstance(obj, dict):
        return {k: (obj[k] if k in skip_keys else _scale_numbers(obj[k], factor, skip_keys))
                for k in obj}
    if isinstance(obj, list):
        return [_scale_numbers(x, factor, skip_keys) for x in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (int, float)):
        return obj * factor
    return obj


def perturb_weights(weights: dict[str, float], factor: float) -> dict[str, float]:
    """把一组权重相对均匀分布放大/缩小 factor 倍后重新归一化。

    factor=1 原样返回；factor<1 让权重更接近等权；factor>1 让差异更极端。
    综合评分的 0.5/0.2/0.15/0.15 同样是人为先验，需要同一套扰动检验。
    """
    keys = list(weights.keys())
    if not keys:
        return {}
    even = 1.0 / len(keys)
    raw = {k: max(1e-6, even + (weights[k] - even) * factor) for k in keys}
    total = sum(raw.values())
    return {k: raw[k] / total for k in keys}


def perturbed(factor: float) -> dict[str, Any]:
    """把全部阈值按 factor 缩放，权重按 factor 偏移后重新归一化。

    用途：score(params) 在 factor=0.8 / 1.0 / 1.2 下跑三遍，得到一个分数区间。
    一个只在某个整数阈值上成立的结论，会在这里立刻暴露。
    """
    p = snapshot()
    p["sentiment"] = _scale_numbers(p["sentiment"], factor)
    # 权重：把偏离均匀分布的部分放大/缩小 factor 倍，再归一化
    keys = list(p["sentiment"].keys())
    even = 1.0 / len(keys)
    raw = {}
    for k in keys:
        w = SENTIMENT[k]["weight"]
        raw[k] = max(1e-6, even + (w - even) * factor)
    total = sum(raw.values())
    for k in keys:
        p["sentiment"][k]["weight"] = raw[k] / total
    p["composite"] = {k: v for k, v in COMPOSITE.items()}
    p["version"] = f"{PARAM_VERSION}+perturb{factor:g}"
    return p
