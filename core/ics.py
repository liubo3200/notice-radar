"""
日历导出：把一条通知变成可导入手机日历的事件，并自带提前提醒。
这是作品"有实物产出"的部分 —— 演示时点一下，手机上真的会多一个日程。
"""

import datetime
import hashlib

TODAY = datetime.date.today()


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


def build_ics(fields, evaluation=None):
    name = fields.get("event_name") or "校园通知"
    deadline = fields.get("deadline")
    # 讲座/线上课没有截止日，用举办日生成"活动"事件
    kind = "截止" if deadline else "活动"
    date_str = deadline or fields.get("event_date")
    if not date_str:
        raise ValueError("这条通知没有可用的日期，无法生成日历事件")

    d = datetime.date.fromisoformat(date_str)
    uid = hashlib.md5(f"{name}{date_str}".encode("utf-8")).hexdigest()[:16]
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%SZ")

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
        "BEGIN:VEVENT",
        f"UID:{uid}@notice-radar",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
        f"SUMMARY:{_escape('【' + kind + '】' + name)}",
        f"DESCRIPTION:{_escape(chr(10).join(desc_parts))}",
        "TRANSP:TRANSPARENT",
        "BEGIN:VALARM",
        "TRIGGER:-P3D",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_escape('还有3天' + kind + '：' + name)}",
        "END:VALARM",
        "BEGIN:VALARM",
        "TRIGGER:-P1D",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_escape('明天' + kind + '：' + name)}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"
