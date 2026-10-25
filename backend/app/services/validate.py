"""统计检验层：Bootstrap 区间、置换检验、分层单调性、因子有效自由度。

为什么需要这一层，以及为什么是这几种方法？

传统做法是算个均值、再配一句"胜率不错"。问题在于：短线复盘的样本天天都很小
（某天只有 12 只昨日涨停股），分布又厚尾（一只 20% 的票能把均值整体抬起来），
而"我挑出来的票"和"当天所有票"之间的差异可能纯粹是运气。于是：

- **Bootstrap 置信区间**（Efron, 1979）为什么存在：小样本下无法假设正态，
  t 区间不可靠。Bootstrap 不假设分布形状，直接用重采样让数据自己给出区间。
  在这里的作用非常直接——"均值 3.2%"和"均值 3.2%，95% 区间 [-1.8%, 8.4%]"
  是完全不同的两个结论，后者说明你什么都没证明。

- **置换检验（permutation test）** 为什么存在：要回答"规则是否优于乱选"，
  必须知道"乱选会是什么样"。参数检验要先假设分布，而置换检验直接把标签打乱
  成千上万次，构造出零假设下的经验分布。**它的关键优势是只需要当天的横截面，
  不需要历史面板数据**——所以在历史快照还没攒够的阶段，它是唯一能立刻产出
  真统计量的工具。

- **分层单调性（quintile spread）** 为什么存在：均值可以被少数样本操纵，但
  "评分越高、后续收益越高"这种单调阶梯很难被偶然制造出来。它检验的是排序
  能力本身，比检验某个阈值更稳健。

- **因子有效自由度**（相关矩阵特征值的参与率）为什么存在：七个高度同向的因子
  配七档权重，看起来精密，实际自由度可能不到 2。先量出有效自由度，才知道精心
  调权重是在建模还是在装饰。

- **BH 多重检验校正**（Benjamini-Hochberg, 1995）为什么存在：试 20 个策略，
  总有一个 p<0.05。BH 控制错误发现率，是"试了很多次"之后唯一诚实的报法。

全部用标准库实现（random / math / statistics），不引入 numpy/scipy，保证在
用户的 Windows + Python 3.10/3.12 环境下零额外依赖即可复现。
"""
from __future__ import annotations

import math
import random
import statistics as st
from typing import Any, Iterable, Sequence

from ..core.params import STATS


def _clean(values: Iterable[Any]) -> list[float]:
    """剔除 None / NaN / inf，保证统计量不被脏值污染。"""
    out = []
    for v in values:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f or f in (float("inf"), float("-inf")):
            continue
        out.append(f)
    return out


def quantile(sorted_vals: Sequence[float], q: float) -> float | None:
    """线性插值分位数；输入必须已排序。"""
    n = len(sorted_vals)
    if n == 0:
        return None
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = min(n - 1, lo + 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def bootstrap_ci(values: Iterable[Any], *, stat: str = "mean",
                 iters: int | None = None, ci: float | None = None,
                 seed: int | None = None) -> dict[str, Any]:
    """对均值或中位数做 Bootstrap 百分位区间。

    seed 固定 → 同一输入必然得到同一区间，第三方才能复核。
    """
    vals = _clean(values)
    n = len(vals)
    if n < 2:
        return {"n": n, "point": vals[0] if n else None, "lo": None, "hi": None,
                "ci": ci or STATS["ci"], "method": f"bootstrap-{stat}",
                "note": "样本量不足，不输出区间"}
    iters = int(iters or STATS["bootstrap_iters"])
    level = float(ci or STATS["ci"])
    rnd = random.Random(seed if seed is not None else STATS["seed"])
    fn = st.fmean if stat == "mean" else st.median
    draws = []
    for _ in range(iters):
        sample = [vals[rnd.randrange(n)] for _ in range(n)]
        draws.append(fn(sample))
    draws.sort()
    alpha = (1 - level) / 2
    return {"n": n, "point": round(fn(vals), 4),
            "lo": round(quantile(draws, alpha) or 0.0, 4),
            "hi": round(quantile(draws, 1 - alpha) or 0.0, 4),
            "ci": level, "iters": iters, "method": f"bootstrap-{stat}", "note": ""}


def describe(values: Iterable[Any], *, label: str = "", min_sample: int | None = None) -> dict[str, Any]:
    """样本的完整画像：n、均值、中位数、四分位、胜率、Bootstrap 区间、是否可报。

    reportable=False 时，调用方必须拒绝把均值当结论（只能展示中位数和区间）。
    这条硬门槛的作用是：把"今天只有 9 只昨涨停股，平均溢价 6.1%"这类
    看起来很好的数字，在源头上标成不可用。
    """
    vals = _clean(values)
    n = len(vals)
    floor = int(min_sample if min_sample is not None else STATS["min_sample"])
    if n == 0:
        return {"label": label, "n": 0, "reportable": False,
                "note": "无有效样本", "mean": None, "median": None,
                "p25": None, "p75": None, "stdev": None, "win_rate": None, "ci": None}
    s = sorted(vals)
    wins = len([v for v in vals if v > 0])
    return {
        "label": label,
        "n": n,
        "mean": round(st.fmean(vals), 4),
        "median": round(st.median(vals), 4),
        "p25": round(quantile(s, 0.25) or 0.0, 4),
        "p75": round(quantile(s, 0.75) or 0.0, 4),
        "min": round(s[0], 4), "max": round(s[-1], 4),
        "stdev": round(st.stdev(vals), 4) if n >= 2 else None,
        "win_rate": round(wins / n * 100, 1),
        "ci": bootstrap_ci(vals, stat="mean") if n >= 2 else None,
        "median_ci": bootstrap_ci(vals, stat="median") if n >= 2 else None,
        "reportable": n >= floor,
        "min_sample": floor,
        "note": "" if n >= floor else f"样本量 {n} < {floor}，均值不可作为结论，只看中位数与区间",
    }


def permutation_test(selected: Iterable[Any], universe: Iterable[Any], *,
                     iters: int | None = None, seed: int | None = None,
                     alternative: str = "greater") -> dict[str, Any]:
    """检验"规则选出的子集"是否优于"从同一可选池随机抽同样多只"。

    零假设：规则没有任何排序能力，selected 的收益与从 universe 随机抽取
    len(selected) 只的收益同分布。
    做法：无放回随机抽样 iters 次，构造均值的零分布，p = 零分布中不劣于
    实际观测值的比例（加 1 平滑，避免 p=0 这种不可能的结论）。

    注意三件事，否则结论无效：
    1. universe 必须是**决策时点真实可选的全集**，不能是事后筛过的池子；
    2. selected 必须是 universe 的子集，否则比较的不是同一天同一市场；
    3. 单日 p 值几乎永远不显著（样本太少），本函数的正确用法是按日积累
       p 值序列，再看它是否整体偏离均匀分布。
    """
    sel = _clean(selected)
    uni = _clean(universe)
    k, m = len(sel), len(uni)
    if k < 3 or m < k + 3:
        return {"n_selected": k, "n_universe": m, "p_value": None,
                "observed": round(st.fmean(sel), 4) if sel else None,
                "note": "样本不足，无法构造零分布（需 selected>=3 且 universe>=selected+3）"}
    iters = int(iters or STATS["permutation_iters"])
    rnd = random.Random(seed if seed is not None else STATS["seed"])
    observed = st.fmean(sel)
    null = []
    for _ in range(iters):
        null.append(st.fmean(rnd.sample(uni, k)))
    if alternative == "greater":
        hits = len([v for v in null if v >= observed])
    elif alternative == "less":
        hits = len([v for v in null if v <= observed])
    else:
        hits = len([v for v in null if abs(v - st.fmean(uni)) >= abs(observed - st.fmean(uni))])
    p = (hits + 1) / (iters + 1)
    null.sort()
    null_mean = st.fmean(null)
    null_sd = st.stdev(null) if len(null) >= 2 else 0.0
    return {
        "n_selected": k, "n_universe": m, "iters": iters,
        "observed": round(observed, 4),
        "universe_mean": round(st.fmean(uni), 4),
        "excess_vs_universe": round(observed - st.fmean(uni), 4),
        "null_mean": round(null_mean, 4),
        "null_p05": round(quantile(null, 0.05) or 0.0, 4),
        "null_p95": round(quantile(null, 0.95) or 0.0, 4),
        "effect_size": round((observed - null_mean) / null_sd, 3) if null_sd > 1e-9 else None,
        "p_value": round(p, 4),
        "alternative": alternative,
        "significant_005": bool(p < 0.05),
        "note": ("单日 p 值不构成证据，需按日累计后检验 p 序列是否偏离均匀分布"),
    }


def quintile_spread(pairs: Iterable[tuple[Any, Any]], *, buckets: int = 5) -> dict[str, Any]:
    """按评分分档，看后续收益是否随档位单调上升。

    pairs = [(score, forward_return), ...]
    单调性比"最高档均值高"更难伪造：要靠运气造出 5 档整齐的阶梯很难。
    """
    rows = [(float(s), float(r)) for s, r in pairs
            if s is not None and r is not None
            and float(s) == float(s) and float(r) == float(r)]
    n = len(rows)
    if n < buckets * 3:
        return {"n": n, "buckets": [], "monotonic": None,
                "note": f"样本 {n} 不足以分 {buckets} 档（每档至少 3 个）"}
    rows.sort(key=lambda x: x[0])
    size = n / buckets
    out = []
    for b in range(buckets):
        lo = int(round(b * size))
        hi = int(round((b + 1) * size)) if b < buckets - 1 else n
        chunk = [r for _, r in rows[lo:hi]]
        if not chunk:
            continue
        out.append({"bucket": b + 1, "n": len(chunk),
                    "score_lo": round(rows[lo][0], 2), "score_hi": round(rows[hi - 1][0], 2),
                    "mean": round(st.fmean(chunk), 4), "median": round(st.median(chunk), 4),
                    "win_rate": round(len([c for c in chunk if c > 0]) / len(chunk) * 100, 1)})
    means = [b["mean"] for b in out]
    rising = all(means[i] <= means[i + 1] for i in range(len(means) - 1))
    return {"n": n, "buckets": out,
            "spread_top_minus_bottom": round(means[-1] - means[0], 4) if len(means) >= 2 else None,
            "monotonic": bool(rising),
            "note": "单调上升才说明评分具备排序能力；仅最高档高可能来自少数极端样本"}


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    pairs = [(a, b) for a, b in zip(xs, ys)
             if a is not None and b is not None and a == a and b == b]
    n = len(pairs)
    if n < 3:
        return None
    ax = st.fmean([p[0] for p in pairs])
    ay = st.fmean([p[1] for p in pairs])
    num = sum((p[0] - ax) * (p[1] - ay) for p in pairs)
    dx = math.sqrt(sum((p[0] - ax) ** 2 for p in pairs))
    dy = math.sqrt(sum((p[1] - ay) ** 2 for p in pairs))
    if dx < 1e-12 or dy < 1e-12:
        return None
    return round(num / (dx * dy), 4)


def _jacobi_eigenvalues(mat: list[list[float]], iters: int = 100) -> list[float]:
    """对称矩阵特征值（Jacobi 旋转法）。

    为什么自己写：只为了求一个 7x7 相关矩阵的特征值而引入 numpy 不值得，
    而 Jacobi 法对小规模对称矩阵既简单又数值稳定。
    """
    n = len(mat)
    a = [row[:] for row in mat]
    for _ in range(iters):
        # 找最大的非对角元素
        p = q = 0
        off = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                if abs(a[i][j]) > off:
                    off, p, q = abs(a[i][j]), i, j
        if off < 1e-10:
            break
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        theta = 0.5 * math.atan2(2 * apq, app - aqq) if abs(app - aqq) > 1e-15 else math.pi / 4
        c, s = math.cos(theta), math.sin(theta)
        for k in range(n):
            akp, akq = a[k][p], a[k][q]
            a[k][p] = c * akp + s * akq
            a[k][q] = -s * akp + c * akq
        for k in range(n):
            apk, aqk = a[p][k], a[q][k]
            a[p][k] = c * apk + s * aqk
            a[q][k] = -s * apk + c * aqk
    return sorted((a[i][i] for i in range(n)), reverse=True)


def factor_independence(series: dict[str, Sequence[float]]) -> dict[str, Any]:
    """量化一组因子到底有多少独立信息。

    effective_factors = (Σλ)² / Σλ²（特征值的参与率）。
    7 个因子若得到 1.8，意味着它们实质上只提供不到 2 个因子的信息；
    此时继续精调 7 档权重属于伪精度，应合并或删减因子。
    """
    keys = [k for k, v in series.items() if len(_clean(v)) >= 3]
    if len(keys) < 2:
        return {"keys": keys, "effective_factors": None,
                "note": "有效序列不足 2 条，无法估计相关结构（需要先积累历史情绪快照）"}
    cols = {k: _clean(series[k]) for k in keys}
    n = min(len(v) for v in cols.values())
    cols = {k: v[-n:] for k, v in cols.items()}
    mat = [[1.0 if i == j else (pearson(cols[keys[i]], cols[keys[j]]) or 0.0)
            for j in range(len(keys))] for i in range(len(keys))]
    eig = [max(0.0, e) for e in _jacobi_eigenvalues(mat)]
    s1, s2 = sum(eig), sum(e * e for e in eig)
    eff = (s1 * s1 / s2) if s2 > 1e-12 else None
    pairs = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            pairs.append({"a": keys[i], "b": keys[j], "corr": mat[i][j]})
    pairs.sort(key=lambda x: -abs(x["corr"]))
    return {
        "keys": keys, "sample": n,
        "matrix": mat,
        "eigenvalues": [round(e, 4) for e in eig],
        "effective_factors": round(eff, 2) if eff else None,
        "nominal_factors": len(keys),
        "top_collinear": pairs[:5],
        "note": ("有效因子数显著低于名义因子数 → 权重微调属于伪精度，"
                 "应考虑合并同向因子或改用单一主成分"),
    }


def benjamini_hochberg(p_values: Sequence[float], alpha: float = 0.05) -> dict[str, Any]:
    """BH 多重检验校正：试过 N 个策略之后，唯一诚实的显著性报法。"""
    ps = [(i, float(p)) for i, p in enumerate(p_values) if p is not None]
    m = len(ps)
    if m == 0:
        return {"m": 0, "adjusted": [], "rejected": [], "alpha": alpha}
    ps.sort(key=lambda x: x[1])
    adj = [0.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        idx, p = ps[rank - 1]
        val = min(prev, p * m / rank)
        adj[rank - 1] = val
        prev = val
    out = [None] * len(p_values)
    rejected = []
    for rank, (idx, _p) in enumerate(ps):
        out[idx] = round(adj[rank], 4)
        if adj[rank] <= alpha:
            rejected.append(idx)
    return {"m": m, "alpha": alpha, "adjusted": out, "rejected": sorted(rejected),
            "note": f"共 {m} 次检验；未校正的 p<0.05 在多重检验下不构成发现"}


def excess_returns(returns: Sequence[Any], baseline: Sequence[Any]) -> list[float | None]:
    """逐样本扣除同日基准，得到超额收益。

    不做这一步，普涨日的 beta 会被当成策略 alpha。
    """
    out: list[float | None] = []
    for r, b in zip(returns, baseline):
        rv = _clean([r])
        bv = _clean([b])
        out.append(round(rv[0] - bv[0], 4) if rv and bv else None)
    return out


def stratified_permutation_test(groups: Sequence[dict[str, Sequence[Any]]], *,
                                iters: int | None = None, seed: int | None = None) -> dict[str, Any]:
    """按交易日分层的置换检验——跨多天累计证据的正确做法。

    为什么不能把所有天的收益混在一起直接置换？
    因为"哪一天"本身是最强的解释变量：普涨日所有票都涨。把全部天数混池后随机抽样，
    等于允许"从大涨那天抽票、和小跌那天的实际持仓比较"，这会凭空造出显著性。
    分层置换在**每一天各自的可选池内部**重抽同样多的票，再把各天结果按实际
    样本数加权合成，于是日期效应在零分布和观测值里被同等抵消，剩下的差异才是
    排序能力。这与临床试验按中心分层随机化是同一个思路。

    groups = [{"selected": [...收益...], "universe": [...同日全部可选标的收益...]}, ...]
    """
    rows = []
    for g in groups:
        sel = _clean(g.get("selected") or [])
        uni = _clean(g.get("universe") or [])
        if len(sel) >= 1 and len(uni) > len(sel):
            rows.append((sel, uni))
    if len(rows) < 3:
        return {"days": len(rows), "p_value": None,
                "note": "可用交易日不足 3 天，无法做分层置换（继续积累账本即可）"}
    iters = int(iters or STATS["permutation_iters"])
    rnd = random.Random(seed if seed is not None else STATS["seed"])
    total_n = sum(len(s) for s, _ in rows)
    observed = sum(sum(s) for s, _ in rows) / total_n
    null = []
    for _ in range(iters):
        acc = 0.0
        for sel, uni in rows:
            acc += sum(rnd.sample(uni, len(sel)))
        null.append(acc / total_n)
    hits = len([v for v in null if v >= observed])
    p = (hits + 1) / (iters + 1)
    null.sort()
    null_mean = st.fmean(null)
    null_sd = st.stdev(null) if len(null) >= 2 else 0.0
    return {
        "days": len(rows), "n_selected": total_n,
        "n_universe": sum(len(u) for _, u in rows),
        "iters": iters,
        "observed": round(observed, 4),
        "null_mean": round(null_mean, 4),
        "null_p05": round(quantile(null, 0.05) or 0.0, 4),
        "null_p95": round(quantile(null, 0.95) or 0.0, 4),
        "effect_size": round((observed - null_mean) / null_sd, 3) if null_sd > 1e-9 else None,
        "p_value": round(p, 4),
        "significant_005": bool(p < 0.05),
        "stratified_by": "trade_date",
        "note": "按交易日分层，日期效应（普涨/普跌）已被抵消；仍需用 BH 对多次检验做校正",
    }


def uniformity_of_pvalues(p_values: Sequence[Any]) -> dict[str, Any]:
    """检验一串逐日 p 值是否整体偏离均匀分布（KS 单样本检验的统计量）。

    为什么要看这个：单日样本太小，p 值几乎永远不显著，所以逐日检验单看毫无意义。
    但在零假设下，p 值应当服从 U(0,1)。若累积几十天后 p 值明显堆在左侧，
    那就是"规则有效"的集体证据——这是把一堆弱证据合法地汇总起来的方式。
    这里只给 KS 统计量 D 与样本量，不给精确 p 值（避免引入 scipy），
    判读用临界值 D > 1.36/sqrt(n) 约对应 alpha=0.05。
    """
    ps = sorted(_clean(p_values))
    n = len(ps)
    if n < 5:
        return {"n": n, "ks_d": None, "note": "p 值序列不足 5 天，无法判读"}
    d = 0.0
    for i, p in enumerate(ps, start=1):
        d = max(d, abs(p - (i - 0.5) / n))
    crit = 1.36 / math.sqrt(n)
    return {"n": n, "ks_d": round(d, 4), "critical_005": round(crit, 4),
            "left_skewed": bool(st.fmean(ps) < 0.5),
            "deviates_from_uniform": bool(d > crit),
            "mean_p": round(st.fmean(ps), 4),
            "note": "D 超过临界值且均值明显小于 0.5 → p 值整体左偏，是正向集体证据"}
