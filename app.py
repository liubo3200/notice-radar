"""
通知雷达 NoticeRadar
校园通知的机会匹配 Agent —— 粘一条通知，告诉你截止日、值不值得参加、下一步做什么。

三个 Agent 串成一条链：
    extract（抽取）→ validate（校验）→ evaluate（评估）
"""

import datetime
import os
from urllib.parse import quote

from flask import Flask, jsonify, render_template, request, Response

from core import clock
from core import critic as critic_agent
from core import ics as ics_builder
from core import retriever
from core.evaluator import DEFAULT_PROFILE, evaluate
from core.parser import extract, llm_available
from core.validator import validate

app = Flask(__name__)

def _cn(days):
    # 每次调用都取当前基准日：示例通知里的日期随当天滚动，
    # 服务连跑几天也不会把「矛盾通知」演成过期通知。
    d = clock.today() + datetime.timedelta(days=days)
    return f"{d.month}月{d.day}日"


SAMPLES = {
    "竞赛": f"""【关于举办北京邮电大学第一届人机协作编程大赛的通知】

各学院、各位同学：

为培养学生人工智能应用开发能力，学校将于近期举办第一届人机协作编程大赛，
作为华为开发者大赛北京邮电大学站分站赛。本次比赛采用开放命题，参赛者基于华为云码道
编程智能体，自选校园学习、办公效率、生活服务等方向，开发一个可实际运行的 AI Agent 应用。

一、参赛对象
在校本科生、研究生均可参赛，不限专业。

二、报名方式
以团队形式参赛，每队1-3人，每位参赛者只能加入一支队伍。
请于{_cn(2)}前登录大赛官网完成报名及组队。

三、赛程安排
作品提交截止时间：{_cn(7)}
校赛决赛评审与答辩：{_cn(20)}

四、奖项设置
一等奖2项、二等奖4项、三等奖8项。

主办单位：北京邮电大学教务部
承办单位：计算机学院
报名网址：https://developer.huaweicloud.com/competition/information/1300000356/introduction
""",
    "讲座": f"""学术报告通知

题目：6G 通感一体化技术进展与挑战
报告人：张教授（信息与通信工程学院）
时间：{_cn(3)}（周三）下午14:00-15:30
地点：教学实验综合楼 N411

面向对象：全体本科生、研究生
主办单位：信息与通信工程学院

本次报告将介绍通感一体化的研究现状与关键问题，欢迎感兴趣的同学参加。
""",
    "招募": f"""关于开展校园开放日志愿者招募的通知

各位同学：

为做好校园开放日接待工作，现面向全校招募志愿者若干名。

一、招募对象
全体在校本科生

二、服务时间
{_cn(7)} 8:00-17:00

三、报名方式
请于{_cn(5)}前填写报名表报名，名额有限，先到先得。

四、保障
提供志愿服务时长认定与午餐。

主办单位：校团委
""",
    "陷阱": f"""关于举办信息安全知识竞赛的通知

各位同学：

为提高学生网络安全意识，学院将举办信息安全知识竞赛，现将有关事项通知如下。

一、报名方式
请于{_cn(4)}前在班级群内接龙报名。

二、竞赛时间
{_cn(-2)} 14:00-16:00，地点：教三 301

三、参赛对象
全体本科生

主办单位：信息与通信工程学院

竞赛设一等奖 3 名、二等奖 5 名，欢迎同学们踊跃参加。
""",
}


def _force_verdict(ev, worth):
    """Critic 一票否决后，把结论文案、分数、行动清单一并改掉。

    只改字段不改话，会出现"自审已拦截 + 强烈建议 90 分"同时上屏 —— 自己打自己的脸。
    """
    ev["worth"] = worth
    ev["priority"] = "P3"
    if worth == "已截止":
        ev["score"] = 0
        ev["summary"] = "截止日期已过，不要再投入时间。"
        ev["actions"] = ["如需参加，留意下一届的报名窗口"]
    elif worth == "信息不足":
        ev["score"] = 0
        ev["summary"] = "通知关键信息缺失（标题/日期），无法给出判断，建议补齐原文重试。"
        ev["actions"] = ["把通知标题和截止日期一起重新粘贴一次"]
    elif worth == "待核实":
        ev["score"] = min(ev.get("score") or 0, 35)
        ev["summary"] = "原文日期自相矛盾，先核对再决定；不要按这个倒计时安排时间。"
        ev["reasons"] = ["自审发现活动时间与截止日期冲突，原有匹配度判断已作废"]
        ev["actions"] = [
            "回到通知原文，核对活动时间与截止日期哪个写错了",
            "确认无误后重新解析一次，再决定要不要投入",
        ]
    return ev


def _pipeline(text):
    """抽取 → 校验 → 检索 → 评估 → 自审（不过就打回重跑）。"""
    fields = extract(text)
    if fields.get("error"):
        return {"error": fields["error"]}

    check = validate(fields)
    retrieval = retriever.search(text)
    ev = evaluate(fields, text, retrieval=retrieval)

    critic = critic_agent.review(fields, ev, check, text, round_no=1)
    issues = list(critic["issues"])

    if critic["verdict"] == "reject":
        # 打回重跑：先按 Critic 的意见修正，再重新校验与评估
        patches = critic["patches"]
        for k, v in patches.items():
            if k not in ("worth", "score"):
                fields[k] = v
        check = validate(fields)
        ev = evaluate(fields, text, retrieval=retrieval)
        if patches.get("worth"):
            ev = _force_verdict(ev, patches["worth"])

        again = critic_agent.review(fields, ev, check, text, round_no=2)
        seen = {i["code"] for i in issues}
        issues += [i for i in again["issues"] if i["code"] not in seen]
        verdict, rounds = again["verdict"], 2
        if again["verdict"] == "reject":
            # 修正不了就明确说修正不了，不装作已经审过了
            issues.append({
                "level": "warning",
                "code": "RETRY_LIMIT",
                "message": "两轮审查后矛盾仍未消除，结论仅供草稿参考",
                "fix": "回到原文人工核对日期后再用",
            })
    else:
        verdict, rounds = "pass", 1

    return {
        "fields": fields,
        "check": check,
        "evaluation": ev,
        "retrieval": {
            "hits": retrieval["hits"],
            "hit_terms": retrieval["hit_terms"],
            "empty": retrieval["empty"],
        },
        "critic": {"verdict": verdict, "rounds": rounds, "issues": issues},
        "engine": "规则解析（备用）" if fields.get("fallback") else "AI 解析",
        "llm_ready": llm_available(),
        "profile": DEFAULT_PROFILE,
    }


@app.route("/")
def index():
    return render_template("index.html", samples=list(SAMPLES.keys()))


@app.route("/api/samples")
def samples():
    return jsonify(SAMPLES)


@app.route("/api/parse", methods=["POST"])
def parse():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "请先粘贴一段通知文本"}), 400
    if len(text) < 10:
        return jsonify({"error": "文本太短，至少粘一段完整通知"}), 400

    try:
        return jsonify(_pipeline(text))
    except Exception as e:  # 兜底，绝不让页面白屏
        return jsonify({"error": f"解析失败：{e}"}), 500


@app.route("/api/ics", methods=["POST"])
def export_ics():
    data = request.get_json(silent=True) or {}
    fields = data.get("fields") or {}
    ev = data.get("evaluation")
    try:
        content = ics_builder.build_ics(fields, ev)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    name = (fields.get("event_name") or "notice")[:20].replace(" ", "_")
    # 响应头必须是 ASCII，中文名要 percent-encode，否则 werkzeug 会抛 UnicodeEncodeError
    utf8_name = quote(f"{name}.ics", safe="")
    return Response(
        content,
        mimetype="text/calendar",
        headers={
            "Content-Disposition": f"attachment; filename=\"reminder.ics\"; filename*=UTF-8''{utf8_name}"
        },
    )


@app.route("/api/health")
def health():
    kb = retriever.stats()
    return jsonify({"ok": True, "llm_ready": llm_available(),
                    "kb_slices": kb["slices"], "kb_files": kb["files"]})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("DEBUG")))
