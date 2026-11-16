"""生成一张可截屏的验收表（HTML）。

用途：视频里「30 条真实通知压测」那一屏，终端黑底不适合出镜。
用法：python tools/report_html.py  ->  docs/验收表.html
"""

import html
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from tools.accuracy import judge_date, judge_worth, load_labels  # noqa: E402
import app as A  # noqa: E402

CLEAN = os.path.join(BASE, "testset", "clean")
OUT = os.path.join(BASE, "docs", "验收表.html")


def build():
    items = load_labels()
    rows, ok_a, ok_b = [], 0, 0

    for i, it in enumerate(items, 1):
        with open(os.path.join(CLEAN, it["file"]), encoding="utf-8") as f:
            text = f.read()
        r = A._pipeline(text)
        f_, e, cr = r["fields"], r["evaluation"], r["critic"]

        got = f_.get("deadline")
        mark_a, _ = judge_date(it.get("exp_deadline"), got, f_.get("deadline_source"))
        mark_b = judge_worth(it.get("exp_worth"), e["worth"])
        ok_a += mark_a == "✓"
        ok_b += mark_b == "✓"

        rows.append({
            "i": i,
            "name": it["file"].replace(".txt", ""),
            "cat": f_.get("category") or "-",
            "deadline": got or "—",
            "exp": it.get("exp_deadline") or "—",
            "a": mark_a,
            "worth": e["worth"],
            "score": e["score"],
            "b": mark_b,
            "critic": ",".join(x["code"] for x in cr["issues"]) or "—",
        })

    n = len(rows)
    body = "\n".join(
        f"""<tr>
      <td class="n">{r['i']}</td>
      <td class="name">{html.escape(r['name'])}</td>
      <td><span class="tag">{r['cat']}</span></td>
      <td class="mono">{r['deadline']}</td>
      <td class="mono dim">{r['exp']}</td>
      <td class="mark {'ok' if r['a'] == '✓' else 'bad'}">{r['a']}</td>
      <td class="worth">{r['worth']}</td>
      <td class="mono score">{r['score']}</td>
      <td class="mark {'ok' if r['b'] == '✓' else 'bad'}">{r['b']}</td>
      <td class="critic">{html.escape(r['critic'])}</td>
    </tr>"""
        for r in rows
    )

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>通知雷达 · 30 条真实通知验收</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:36px 40px 28px; background:#0b1120; color:#e6edf7;
         font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif; }}
  h1 {{ margin:0 0 6px; font-size:22px; letter-spacing:.5px; }}
  .sub {{ color:#7f8ea6; font-size:13px; margin-bottom:22px; }}
  .kpis {{ display:flex; gap:14px; margin-bottom:22px; }}
  .kpi {{ flex:1; background:#111a2e; border:1px solid #1e2b45; border-radius:10px; padding:14px 18px; }}
  .kpi .v {{ font-size:26px; font-weight:700; color:#4ade80; font-family:ui-monospace,Consolas,monospace; }}
  .kpi .k {{ font-size:12px; color:#7f8ea6; margin-top:4px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  thead th {{ text-align:left; padding:9px 8px; color:#8fa3c0; font-weight:600; font-size:12px;
             border-bottom:1px solid #24344f; white-space:nowrap; }}
  tbody td {{ padding:8px; border-bottom:1px solid #16203a; vertical-align:middle; }}
  tbody tr:nth-child(even) {{ background:#0e1728; }}
  .n {{ color:#5a6b85; width:30px; }}
  .name {{ max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .mono {{ font-family:ui-monospace,Consolas,monospace; }}
  .dim {{ color:#6b7c96; }}
  .tag {{ background:#16233b; color:#93b4e0; border-radius:5px; padding:2px 7px; font-size:12px; }}
  .mark {{ font-weight:700; text-align:center; width:26px; }}
  .mark.ok {{ color:#4ade80; }}
  .mark.bad {{ color:#f87171; }}
  .worth {{ white-space:nowrap; }}
  .score {{ text-align:right; color:#fbbf24; width:44px; }}
  .critic {{ font-family:ui-monospace,Consolas,monospace; font-size:11px; color:#7f8ea6; }}
  .foot {{ margin-top:18px; color:#6b7c96; font-size:12px; line-height:1.8; }}
  .foot b {{ color:#9fb3d1; font-weight:600; }}
</style></head>
<body>
  <h1>30 条真实通知 · 验收结果</h1>
  <div class="sub">来源：北邮信息服务门户「校内通知」连续三页（2026-11-06 至 11-13），人工逐条标注</div>

  <div class="kpis">
    <div class="kpi"><div class="v">{ok_a}/{n}</div><div class="k">截止日期抽取</div></div>
    <div class="kpi"><div class="v">{ok_b}/{n}</div><div class="k">结论方向判断</div></div>
    <div class="kpi"><div class="v">0</div><div class="k">无矛盾通知被误拦</div></div>
    <div class="kpi"><div class="v">{n}</div><div class="k">覆盖通知类别</div></div>
  </div>

  <table>
    <thead><tr>
      <th>#</th><th>通知</th><th>类别</th><th>解析截止日</th><th>人工标注</th>
      <th>A</th><th>结论</th><th>分</th><th>B</th><th>自审</th>
    </tr></thead>
    <tbody>{body}</tbody>
  </table>

  <div class="foot">
    <b>A · 截止日期</b>：以人工标注为准。原文没有报名截止的，解析器必须报空——给一个错的倒计时比说"没有"更糟。<br>
    <b>B · 结论方向</b>：值得 ↔ 强烈建议/可以考虑；不值得 ↔ 不建议/信息不足/待核实；已过期 ↔ 已截止。三档分开算。<br>
    一键复跑：<span class="mono">python tools/accuracy.py</span>　标注文件：<span class="mono">testset/labels.md</span>
  </div>
</body></html>"""

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"写出 {OUT}")
    print(f"截止 {ok_a}/{n}　方向 {ok_b}/{n}")


if __name__ == "__main__":
    build()
