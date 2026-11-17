"""
Agent 2 · 校验（Validator）
职责：抽取结果不能直接信。这里检查字段合法性、日期合理性，并给出置信度。
对应比赛里的"多 Agent 协作"：抽取负责广度，校验负责准确度。

真实通知跑出来的教训：讲座、线上课、活动本来就没有"报名截止"，只有举办时间。
拿 deadline 当必填，会把 8 条正常通知全标成"缺字段、置信度低"。
所以必填项按类别变：只有竞赛/招募才要求有截止日。
"""

import datetime
import re

from core import clock

TODAY = clock.today()
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

OPTIONAL = ["event_time", "target", "organizer", "category", "link"]
CATEGORIES = ("竞赛", "讲座", "招募", "活动", "事务", "其他")
NEED_DEADLINE = ("竞赛", "招募")


def validate(fields):
    warnings = []
    filled = 0

    # ---- 类别合法性（先定类别，才能决定哪些字段是必填）
    if fields.get("category") not in CATEGORIES:
        fields["category"] = "其他"
    category = fields["category"]

    required = ["event_name"] + (["deadline"] if category in NEED_DEADLINE else [])

    for key in required + OPTIONAL:
        if fields.get(key):
            filled += 1

    total = len(required) + len(OPTIONAL)
    completeness = round(filled / total, 2)

    for key in required:
        if not fields.get(key):
            name = "活动/赛事标题" if key == "event_name" else "截止日期"
            warnings.append(f"未识别到{name}，请人工核对原文")

    # ---- 截止日期
    deadline = fields.get("deadline")
    days_left = None
    if deadline:
        if not DATE_RE.match(str(deadline)):
            warnings.append("截止日期格式异常，已忽略")
            fields["deadline"] = None
        else:
            d = datetime.date.fromisoformat(deadline)
            days_left = (d - TODAY).days
            if days_left < 0:
                warnings.append(f"截止日期已过（{-days_left} 天前）")
            elif days_left > 365:
                warnings.append("截止日期超过一年，疑似年份解析错误")

    # ---- 活动举办日（讲座、线上课只有这个）
    days_to_event = None
    ed = fields.get("event_date")
    if ed and DATE_RE.match(str(ed)):
        d = datetime.date.fromisoformat(ed)
        days_to_event = (d - TODAY).days
        if days_to_event < 0 and not fields.get("deadline"):
            warnings.append(f"活动已于 {-days_to_event} 天前举办")

    # ---- Critic 打回标记：日期与活动时间矛盾，不能当准数用
    if fields.get("deadline_uncertain"):
        warnings.append("截止日期与活动时间互相矛盾，请按原文核对后再信赖倒计时")

    fields["days_left"] = days_left
    fields["days_to_event"] = days_to_event

    # ---- 置信度
    has_a_date = bool(deadline or ed)
    if fields.get("fallback"):
        confidence = "中" if completeness >= 0.6 and has_a_date else "低"
        if confidence == "中":
            warnings.append("当前为规则解析结果，日期建议人工复核一次")
    else:
        confidence = "高" if completeness >= 0.7 and has_a_date else "中"

    return {
        "confidence": confidence,
        "completeness": completeness,
        "warnings": warnings,
    }
