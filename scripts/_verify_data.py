"""数据正确性核验 v2：按接口真实字段名取值，重点看修复后的情绪/主线/报告。"""
import asyncio, json
import httpx

BASE = "http://127.0.0.1:8088"


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=240, trust_env=False) as c:
        ov = (await c.get("/api/market/overview")).json()
        t = ov.get("turnover") or {}
        b = ov.get("breadth") or {}
        print("== 大盘 ==")
        for i in (ov.get("indices") or [])[:3]:
            print(f"  {i.get('key')} {i.get('name')} {i.get('price')} {i.get('pct')}% 额{i.get('amount_yi')}亿")
        print("  成交额:", t.get("total_yi"), "亿 estimated=", t.get("estimated"),
              "level=", (t.get("level") or {}).get("label"))
        print("  涨跌:", b.get("up"), "/", b.get("down"), "平", b.get("flat"), "占比", b.get("up_ratio"), "%")

        s = (await c.get("/api/sentiment")).json()
        m = s.get("metrics") or {}
        print("\n== 情绪 ==")
        print("  date=", s.get("date"), "score=", s.get("score"), s.get("label"), "hist=", s.get("historical"))
        for k in ("limit_up", "limit_down", "zhaban", "max_boards", "up_ratio", "promote_rate",
                  "first_promote_rate", "promoted_first", "prev_premium", "open_premium",
                  "open_entry_return", "unbuyable_count", "unknown_board_count", "prev_limit_up"):
            print(f"  {k} = {m.get(k)}")
        print("  dq=", s.get("data_quality"))
        print("  sources=", s.get("sources"))

        print("\n== 涨停池 ==")
        for d in ("", "2026-10-22"):
            q = {"kind": "zt"}
            if d:
                q["date"] = d
            r = (await c.get("/api/limitup", params=q)).json()
            print(f"  date={d or '默认'} -> 返回日期={r.get('date')} 数量={r.get('total')} src={r.get('source')}")

        ml = (await c.get("/api/sectors/mainline")).json()
        print("\n== 板块/主线 ==")
        print("  sources=", ml.get("sources"), "taxonomy_ok=", ml.get("taxonomy_ok"))
        print("  warnings=", ml.get("warnings"))
        print("  main=", len(ml.get("main_lines") or []), "confirmed=", len(ml.get("confirmed_lines") or []))
        for l in (ml.get("main_lines") or [])[:3]:
            print(f"   {l['name']} zt={l['zt_count']} maxb={l['max_boards']} "
                  f"pct={l.get('pct')} flow={l.get('main_flow_yi')} confirmed={l.get('confirmed')} gaps={l.get('confirm_gaps')}")

        gl = (await c.get("/api/global")).json()
        sig = gl.get("signal") or {}
        print("\n== 外围 ==")
        print("  signal.score=", sig.get("score"), "excluded=", sig.get("excluded"), "overall=", sig.get("overall"))
        for i in (gl.get("items") or [])[:5]:
            print(f"   {i.get('name')} pct={i.get('pct')} stale={i.get('stale')} src={i.get('source')}")

        au = (await c.get("/api/auction")).json()
        print("\n== 竞价 ==")
        print("  session=", (au.get("session") or {}).get("label"), "actionable=", (au.get("session") or {}).get("actionable"),
              "can_confirm=", au.get("can_confirm"), "cand_date=", au.get("candidate_date"))
        print("  summary=", au.get("summary"))

        r = await c.get("/api/report")
        print("\n== 报告 ==", r.status_code)
        if r.status_code == 200:
            rep = r.json()
            q = rep.get("data_quality") or {}
            print("  date=", rep.get("date"), "final=", rep.get("is_final"), "quality=", q.get("level"),
                  "decision=", q.get("decision_enabled"))
            print("  score=", (rep.get("composite") or {}).get("score"),
                  "position=", (rep.get("composite") or {}).get("position"))
            print("  blockers=", [x.get("code") for x in (q.get("blockers") or [])])
            print("  warnings=", [x.get("code") for x in (q.get("warnings") or [])])
            print("  parts=", [(p["name"], p["score"], p.get("neutral")) for p in (rep.get("composite") or {}).get("parts", [])])
            md = rep.get("markdown") or ""
            i = md.find("## 五、主线与板块")
            print("  --- markdown 主线段 ---")
            print(md[i:i + 420] if i > 0 else "  (未找到)")
        else:
            print("  ", r.text[:300])


asyncio.run(main())
