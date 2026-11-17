"""
日历导出：把一条通知变成可导入手机日历的事件，并自带提前提醒。
这是作品"有实物产出"的部分 —— 演示时点一下，手机上真的会多一个日程。
"""

import datetime
import hashlib

from core import clock

TODAY = clock.today()


def _escape(s):
    return (
        str(s or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(line, limit=73):
    """按 RFC5545 折叠长行，避免中文描述把日历撑坏。"""
    if len(line.encode("utf-8")) <= limit:
        return line
    out, buf = [], ""
    for ch in line:
        if len((buf + ch).encode("utf-8")) > limit:
            out.append(buf)
            buf = "  " + ch
        else:
            buf += ch
    out.append(buf)
    return "\r\n".join(out)


def _nodes(fields):
    """取出全部需要写进日历的时间节点：多个截止节点各一个事件，没有截止才退回举办日。"""
    out, seen = [], set()
    for n in (fields.get("deadlines") or []):
        d = (n.get("date") or "").strip()
        if not d:
            continue
        label = (n.get("label") or "截止").strip() or "截止"
        key = (label, d)
        if key in seen:
            continue
        seen.add(key)
        out.append((label, d))
    if out:
        return out
    if fields.get("deadline"):
        return [("截止", fields["deadline"])]
    if fields.get("event_date"):
        return [("活动", fields["event_date"])]
    return []


def build_ics(fields, evaluation=None):
    name = fields.get("event_name") or "校园通知"
    nodes = _nodes(fields)
    if not nodes:
        raise ValueError("这条通知没有可用的日期，无法生成日历事件")

    stamp = clock.now().strftime("%Y%m%dT%H%M%SZ")

    desc_parts = []
    if evaluation:
        desc_parts.append(f"建议：{evaluation.get('worth')}（匹配度 {evaluation.get('score')}）")
        if evaluation.get("actions"):
            desc_parts.append("下一步：" + "；".join(evaluation["actions"]))
    if fields.get("organizer"):
        desc_parts.append(f"主办：{fields['organizer']}")
    if fields.get("link"):
        desc_parts.append(f"链接：{fields['link']}")
    desc_parts.append("由 通知雷达 NoticeRadar 生成")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//NoticeRadar//BUPT//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    # 一个截止节点 = 一个 VEVENT；每个事件自带提前 3 天 + 提前 1 天两条提醒
    for label, date_str in nodes:
        d = datetime.date.fromisoformat(date_str)
        uid = hashlib.md5(f"{name}{label}{date_str}".encode("utf-8")).hexdigest()[:16]
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}@notice-radar",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
            f"SUMMARY:{_escape('【' + label + '】' + name)}",
            f"DESCRIPTION:{_escape(chr(10).join(desc_parts))}",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM",
            "TRIGGER:-P3D",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escape('还有3天' + label + '：' + name)}",
            "END:VALARM",
            "BEGIN:VALARM",
            "TRIGGER:-P1D",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escape('明天' + label + '：' + name)}",
            "END:VALARM",
            "END:VEVENT",
        ])

    lines.extend(["END:VCALENDAR"])
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"
