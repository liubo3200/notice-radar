"""
Agent 5 · 自审（Critic）
职责：不生产任何结论，只审查其他 Agent 的输出。发现矛盾就打回重跑。

存在意义（答辩要点）：单独一个 LLM 调用的作品，错了没人管；
这里有第五个 Agent 专职跟结果对账，矛盾会被拦下并标明原因，可现场演示。

三类硬矛盾（error，必须打回）：
  E1 已过期却判"可以报名"
  E2 活动时间早于截止日期（活动都结束了还能报名）
  E3 标题都没抽到，却给出"强烈建议"

三类软问题（warning，提示不阻断）：
  W1 存在多个截止日，只报了其中一个
  W2 没有报名截止，只有举办时间（别把举办日当倒计时）
  W3 置信度低却给出强结论
"""

import datetime
import re

from core import clock

DATE_FULL = re.compile(r"(20\d{2})\s*[年\-/\.]\s*(\d{1,2})\s*[月\-/\.]\s*(\d{1,2})\s*日?")
DATE_CN = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
DATE_SLASH = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)")

STRONG = ("强烈建议", "可以考虑")


def _date_in(s, today):
    if not s:
        return None
    m = DATE_FULL.search(s)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = DATE_CN.search(s) or DATE_SLASH.search(s)
    if m:
        try:
            return datetime.date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def _issue(level, code, message, fix=""):
    return {"level": level, "code": code, "message": message, "fix": fix}


def review(fields, evaluation, check, text="", today=None, round_no=1):
    """返回 {"verdict", "issues", "patches"}。verdict=reject 时上游必须重跑。"""
    today = today or clock.today()
    issues, patches = [], {}

    name = (fields.get("event_name") or "").strip()
    worth = evaluation.get("worth") or ""
    deadline = fields.get("deadline")
    days_left = fields.get("days_left")
    category = fields.get("category") or "其他"
    event_time = fields.get("event_time") or ""

    # ---- E1 已过期却判可以报名
    if deadline and days_left is not None and days_left < 0 and worth in STRONG:
        issues.append(_issue(
            "error", "E1_EXPIRED",
            f"截止日期 {deadline} 已过 {-days_left} 天，却给出「{worth}」",
            "改为「已截止」，不再推荐投入时间",
        ))
        patches.update({"worth": "已截止", "score": 0})

    # ---- E2 活动时间早于截止日期（只在结论是正面时必须拦；已判"不建议"就别再改结论）
    t = _date_in(event_time, today)
    if deadline and t and category != "讲座" and worth in STRONG:
        try:
            d = datetime.date.fromisoformat(deadline)
        except ValueError:
            d = None
        if d and t < d:
            issues.append(_issue(
                "error", "E2_TIME_CONFLICT",
                f"活动时间（{t.isoformat()}）早于截止日期（{deadline}），字段互相矛盾",
                "结论降级为「待核实」，等人工核对原文后再判断",
            ))
            # 只标"存疑"不改结论，会出现"已拦截 + 强烈建议"同时上屏，自相矛盾。
            # 所以这里必须把结论一起降级。
            patches.update({"deadline_uncertain": True, "worth": "待核实"})

    # ---- E3 标题为空却强结论
    if not name and worth in STRONG:
        issues.append(_issue(
            "error", "E3_NO_TITLE",
            "没有抽到通知标题，却给出强结论：结论建立在不完整信息上",
            "改判「信息不足」，要求补齐原文",
        ))
        patches.update({"worth": "信息不足", "score": 0})

    # ---- W1 多个截止日
    deadlines = fields.get("deadlines") or []
    if len(deadlines) >= 2:
        labels = "、".join(f"{d['label']} {d['date']}" for d in deadlines[:3])
        issues.append(_issue(
            "warning", "W1_MULTI_DEADLINE",
            f"原文有 {len(deadlines)} 个截止节点（{labels}），只按最早的一个倒计时",
            "两个节点都要标在日历里，别只记一个",
        ))

    # ---- W2 没有报名截止，只有举办时间
    if not deadline and fields.get("event_date"):
        issues.append(_issue(
            "warning", "W2_NO_DEADLINE",
            f"原文没有报名截止日，这个日期（{fields['event_date']}）是举办时间，不是截止",
            "按举办日提醒，别当成报名倒计时",
        ))

    # ---- W3 低置信度 + 强结论
    if check.get("confidence") == "低" and worth == "强烈建议":
        issues.append(_issue(
            "warning", "W3_LOW_CONF_STRONG",
            "字段置信度为低，却给出「强烈建议」",
            "先把原文补全再下结论",
        ))

    has_error = any(i["level"] == "error" for i in issues)
    return {
        "verdict": "reject" if has_error else "pass",
        "issues": issues,
        "patches": patches,
        "round": round_no,
    }
