"""中国金融期货交易所（中金所）每日持仓排名（免费、无需 token）。

为什么接它：股指期货（IF/IH/IC/IM）前 20 名会员的多单、空单持仓，是公开数据里
唯一能看到"大机构在期货端怎么站队"的窗口。市场常盯的"中信期货空单"就出自这里。

接口：http://www.cffex.com.cn/sj/ccpm/{YYYYMM}/{DD}/{品种}_1.csv
- GBK 编码；每个交易日 16:30 左右更新，当天未公布时返回 404
- 每行：交易日,合约,排名,成交量会员,成交量,增减,持买会员,持买单量,增减,持卖会员,持卖单量,增减
- 按合约分别排名（IF2511、IF2512…），同一会员会出现在多个合约里，需要按会员汇总

注意：本仓库所在环境无法直连该站，格式依据公开资料编写，首次运行请用 /api/macro/probe 核对。
"""
from __future__ import annotations

from ..core import http
from ..core.utils import fnum

HOST = "http://www.cffex.com.cn"

# 股指期货品种 → 对应现货指数
VARIETIES: dict[str, str] = {"IF": "沪深300", "IH": "上证50", "IC": "中证500", "IM": "中证1000"}


def _int(v: str) -> int | None:
    """持仓数字可能带千分位逗号或空格；无法解析返回 None（不能当 0）。"""
    x = fnum(str(v).replace(",", "").strip())
    return int(x) if x is not None else None


def parse_rank_csv(text: str) -> list[dict]:
    """解析持仓排名 CSV → 每个合约每个名次一行。

    只认"第 1 列是 8 位日期、第 3 列是名次数字"的数据行，表头、合计行、
    以及 2020-03 前后两种排版的差异都会被自然跳过。
    """
    out: list[dict] = []
    for line in (text or "").splitlines():
        cells = [c.strip() for c in line.split(",")]
        if len(cells) < 12 or not (len(cells[0]) == 8 and cells[0].isdigit()) or not cells[2].isdigit():
            continue
        out.append({
            "date": f"{cells[0][:4]}-{cells[0][4:6]}-{cells[0][6:]}",
            "contract": cells[1], "rank": int(cells[2]),
            "vol_name": cells[3], "vol": _int(cells[4]), "vol_chg": _int(cells[5]),
            "long_name": cells[6], "long": _int(cells[7]), "long_chg": _int(cells[8]),
            "short_name": cells[9], "short": _int(cells[10]), "short_chg": _int(cells[11]),
        })
    return out


async def rank(date: str, variety: str) -> list[dict]:
    """某交易日（YYYY-MM-DD）某品种全部合约的前 20 会员排名；未公布或非交易日返回空列表。"""
    ym, dd = date[:4] + date[5:7], date[8:10]
    # 404（当天还没公布）会被 http.fetch 直接判失败、不重试，由上层往前找交易日
    text = await http.fetch(f"{HOST}/sj/ccpm/{ym}/{dd}/{variety}_1.csv", source="cffex",
                            encoding="gbk", headers={"Referer": f"{HOST}/ccpm/"})
    return parse_rank_csv(text or "")
