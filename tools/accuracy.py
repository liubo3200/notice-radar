"""
在真实通知测试集上跑准确率。

评测口径（写进作品说明，别含糊）：
  A · 截止日期：以人工标注为准。通知没有截止日的，解析器也不该编一个截止日出来。
      ✓ 完全一致　⚠ 偏差（把活动举办日当截止日）　✗ 错
  B · 结论方向：值得 ↔ 强烈建议/可以考虑；不值得 ↔ 不建议/已截止/信息不足/待核实
  C · 自审：是否触发 Critic（有矛盾必须触发，无矛盾不该误报）

用法：python tools/accuracy.py
"""

import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import app as A  # noqa: E402

CLEAN = os.path.join(BASE, "testset", "clean")
LABELS = os.path.join(BASE, "testset", "labels.md")

WORTH_OK = ("强烈建议", "可以考虑")
WORTH_NO = ("不建议", "信息不足", "待核实")


def judge_worth(exp, got):
    """exp 三档：值得 / 不值得 / 已过期（内容值得，但时间窗口已关）。"""
    if exp == "已过期":
        return "✓" if got == "已截止" else "✗"
    ok = WORTH_OK if exp == "值得" else WORTH_NO
    return "✓" if got in ok else "✗"


def load_labels():
    items, cur = [], None
    with open(LABELS, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = re.match(r"^- file:\s*(.+)$", line)
            if m:
                if cur:
                    items.append(cur)
                cur = {"file": m.group(1).strip()}
                continue
            m = re.match(r"^\s+(title|exp_deadline|exp_worth|note):\s*(.*)$", line)
            if m and cur is not None:
                key, val = m.group(1), m.group(2).strip()
                if val in ("null", ""):
                    cur[key] = None
                else:
                    cur[key] = val.strip('"')
    if cur:
        items.append(cur)
    return items


def judge_date(exp, got, source):
    if exp and got:
        if exp == got:
            return "✓", ""
        return "✗", f"标注 {exp} / 解析 {got}"
    if not exp and not got:
        return "✓", ""
    if not exp and got:
        if source == "fallback":
            return "⚠", f"无截止日，取了日期 {got} 当倒计时（活动举办日）"
        return "✗", f"无截止日，却报 {got}"
    return "✗", f"标注 {exp} / 解析为空"


def main():
    items = load_labels()
    rows = []
    ok_a = ok_b = 0

    for it in items:
        path = os.path.join(CLEAN, it["file"])
        with open(path, encoding="utf-8") as f:
            text = f.read()
        r = A._pipeline(text)
        f_, e, ck, cr = r["fields"], r["evaluation"], r["check"], r["critic"]

        got = f_.get("deadline")
        mark_a, why_a = judge_date(it.get("exp_deadline"), got, f_.get("deadline_source"))
        exp_worth = it.get("exp_worth")
        mark_b = judge_worth(exp_worth, e["worth"])
        ok_a += mark_a == "✓"
        ok_b += mark_b == "✓"

        rows.append({
            "name": it.get("file"),
            "cat": f_.get("category"),
            "deadline": got or "-",
            "exp": it.get("exp_deadline") or "-",
            "a": f"{mark_a}{(why_a and ' ' + why_a) or ''}",
            "worth": e["worth"],
            "score": e["score"],
            "exp_worth": exp_worth,
            "b": mark_b,
            "critic": ",".join(i["code"] for i in cr["issues"]) or "-",
        })

    print(f"\n{'文件':34} {'类别':4} {'截止':12} {'结论':6} {'分':>3} {'期望':4} {'A':4} {'B':2} 自审")
    print("-" * 118)
    for r in rows:
        print(f"{r['name'][:32]:34} {r['cat']:4} {r['deadline']:12} {r['worth']:6} "
              f"{r['score']:>3} {r['exp_worth'] or '-':4} {r['a'][:1]:4} {r['b']:2} {r['critic']}")

    print("\n偏差明细：")
    for r in rows:
        if r["a"][0] != "✓" or r["b"] != "✓":
            print(f"  · {r['name']}\n      A: {r['a']}\n      B: 期望 {r['exp_worth']} / 给出 {r['worth']}")

    n = len(rows)
    print(f"\n截止日期严格命中： {ok_a}/{n}   ({ok_a / n * 100:.0f}%)")
    print(f"结论方向命中：     {ok_b}/{n}   ({ok_b / n * 100:.0f}%)")


if __name__ == "__main__":
    main()
