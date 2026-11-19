"""
Agent 3 · 评估（Evaluator）
职责：把"这条通知是什么"升级成"这条通知对你值不值得"。
这是本作品与普通信息提取工具的分界线：工具帮你记，Agent 帮你决定。
"""

import re

from core import clock

DEFAULT_PROFILE = {
    "identity": "北京邮电大学 通信工程 大一本科生",
    "goal": "保研；走通信 + 软件复合路线",
    "concerns": "时间成本、是否能加分、是否与专业方向相关",
    # 明确不参加的类型（个人选择，写成规则比让模型猜更稳）
    "exclude_topics": ["入团", "团校", "党校", "党建", "党员", "积极分子"],
    "exclude_roles": ["青年教师", "教职工", "工会会员", "辅导员", "班主任"],
}

TECH_KEYS = ["编程", "算法", "开发", "人工智能", "AI", "程序", "软件", "数据", "技术", "创新"]
FREE_KEYS = ["免费", "0元", "￥0", "无报名费", "不收取", "公益"]
TEAM_KEYS = ["组队", "团队", "小队", "每队", "1-3人", "3-5人"]
MENTOR_KEYS = ["指导教师", "指导老师", "导师"]
# 强制参与的事务：不是"机会"，不该用匹配度衡量
DUTY_KEYS = ["选举", "投票", "选民证", "签到", "集合", "务必", "严肃对待"]

# 抬头是"各学院/各教学单位"且通篇不出现"同学"，基本就是面向单位报送，不是面向学生个人
ORG_HEAD = re.compile(r"^\s*各(学院|教学单位|单位|部门|分党委|团委)", re.M)


def _fit_check(fields, text, profile):
    """先判"能不能参加"，再判"值不值得"。

    教训来自 10 条真实通知：打分算法再细，面向对象不符也是白搭——
    青年教师赛、面向学院报送的案例征集、入团培训，按关键词打分都能上 80 分。
    """
    cat = fields.get("category") or "其他"
    title = fields.get("event_name") or ""
    target = fields.get("target") or ""
    head = "\n".join(text.split("\n")[:15])

    if cat == "事务":
        return True, "这是后勤/事务类通知，不是一个可以选择参加的机会"

    # 抬头写"各学院：""各教学单位工会："且通篇不出现"同学"，基本是面向单位报送。
    # 但如果正文明确写了面向本科生/研究生（如资助类），那就是给学生看的，不能一棍子打死。
    student_target = bool(re.search(r"本科生|研究生|在校生|全体学生", target))
    if ORG_HEAD.search(head) and "同学" not in text[:300] and not student_target:
        return True, "抬头是「各学院/各单位」，属于面向单位报送，不是面向学生个人"

    for k in profile.get("exclude_topics", []):
        if k in title or k in target:
            return True, f"属于{k}相关培训，不在你的参与范围"

    for k in profile.get("exclude_roles", []):
        if k in target or k in title:
            return True, f"面向对象是「{k}」，不是你"

    for k in ("女教职工", "女大学生", "限女性", "仅限女生"):
        if k in target:
            return True, f"面向对象限定为「{k}」，不适用"

    if "研究生" in target and "本科" not in target:
        return True, "只面向研究生，你暂不符合资格"

    return False, ""


def evaluate(fields, text="", profile=None, retrieval=None):
    """retrieval 为 Retriever 的召回结果；有料就引用条款，没料就明说没料。"""
    profile = profile or DEFAULT_PROFILE
    days_left = fields.get("days_left")
    category = fields.get("category") or "其他"
    target = fields.get("target") or ""
    blob = f"{fields.get('event_name') or ''} {text}"

    # ---- 硬性不适配先判：资格不符 / 不是机会，说"不建议"比说"已截止"更有用
    unfit, why = _fit_check(fields, text, profile)
    if unfit:
        return {
            "worth": "不建议",
            "priority": "P3",
            "score": 18,
            "summary": f"不建议投入：{why}。",
            "reasons": [why],
            "risks": ["参与资格不符，报上去大概率被退回"],
            "actions": ["直接跳过", "确实需要时，先找发布部门确认能否例外"],
            "basis": [],
            "grounded": False,
            "score_parts": [{"label": "资格不符，直接封顶", "delta": 18}],
        }

    if days_left is not None and days_left < 0:
        return {
            "worth": "已截止",
            "priority": "P3",
            "score": 0,
            "summary": f"已于 {fields.get('deadline')} 截止，不要再投入时间。",
            "reasons": [],
            "risks": ["已过期"],
            "actions": ["如需参加，留意下一届的报名窗口"],
            "basis": [],
            "grounded": False,
            "score_parts": [{"label": "已截止，不再计分", "delta": 0}],
        }

    # 强制参与的事务（投票、集合、签到）不是"机会"，用分数衡量它本身就不对。
    # 实测：一条要求明早 8:10 集合的选举通知被判成「可以考虑 50」，用户当场质疑。
    is_duty = any(k in blob for k in DUTY_KEYS)

    score = 50
    reasons, risks, actions = [], [], []
    # 分数构成逐项留痕：用户最不信的就是"凭什么这么多分"，把加减项摊开给他看
    parts = [{"label": "基础分", "delta": 50}]

    # ---- 类别
    cat_score = {"竞赛": 25, "招募": 10, "活动": 5, "讲座": 0, "其他": 0}
    score += cat_score.get(category, 0)
    if cat_score.get(category, 0):
        parts.append({"label": f"类别为{category}", "delta": cat_score[category]})
    if category == "竞赛":
        reasons.append("属于竞赛类，可沉淀为可复用的作品或获奖经历")
    elif category == "招募":
        reasons.append("属于招募类，通常可折算志愿服务或实践时长")
    elif category == "讲座":
        reasons.append("属于讲座类，投入时间短，适合顺带参加")

    # ---- 成本
    if any(k in blob for k in FREE_KEYS):
        score += 10
        reasons.append("零报名成本，试错代价极低")
        parts.append({"label": "零报名成本", "delta": 10})

    # ---- 资格
    if "研究生" in target and "本科" not in target:
        score -= 40
        parts.append({"label": "面向研究生", "delta": -40})
        risks.append("面向研究生，你可能不符合报名资格")
    elif target and re.search(r"\d+\s*[-–—~至]\s*\d+\s*班|\d+\s*班", target):
        # 限定到具体班级（"11-13 班同学"）时不能说"你符合条件"——用户是否在范围内
        # 只有他自己知道。给分不如给提醒，实测用户最不信的就是这类越权判断。
        risks.append(f"面向对象限定为「{target}」，确认你所在班级或学院在范围内")
        parts.append({"label": "面向班级限定，未加分", "delta": 0})
    elif target and ("本科" in target or "学生" in target or "同学" in target or "全体" in target):
        score += 10
        reasons.append(f"面向对象为「{target}」，你符合条件")
        parts.append({"label": "面向对象包含你", "delta": 10})
    elif not target:
        reasons.append("原文未写面向对象，默认向全校学生开放，建议报名前确认")

    # ---- 方向相关
    hits = [k for k in TECH_KEYS if k in blob]
    if hits:
        score += 8
        reasons.append(f"内容涉及{hits[0]}，与你的技术路线相关")
        parts.append({"label": f"涉及{hits[0]}", "delta": 8})

    # ---- 志愿时长
    if "志愿" in blob or "服务时长" in blob:
        score += 8
        reasons.append("可认定志愿服务时长，对劳动教育学时有用")
        parts.append({"label": "可认定志愿时长", "delta": 8})

    # ---- 时间
    is_lecture = category == "讲座"
    d_event = fields.get("days_to_event")
    if days_left is None and d_event is not None:
        # 讲座/线上课/活动没有报名截止，只有举办时间——不能拿"倒计时"吓唬人
        if d_event >= 0:
            risks.append(f"原文没有报名截止，{d_event} 天后举办，确认与课程是否冲突")
        else:
            risks.append("活动已经举办过了")
    elif days_left is not None:
        if is_lecture:
            # 讲座没有"报名截止"，这个日期是活动时间，措辞要改
            risks.append(f"{days_left} 天后举行，确认是否与课程冲突")
        elif days_left <= 1:
            score -= 5
            parts.append({"label": f"距截止仅剩 {days_left} 天", "delta": -5})
            risks.append(f"距截止仅剩 {days_left} 天，材料准备时间非常紧")
        elif days_left <= 3:
            risks.append(f"距截止 {days_left} 天，需要立刻动手")
        else:
            score += 5
            reasons.append(f"距截止还有 {days_left} 天，准备时间充足")
            parts.append({"label": f"距截止还有 {days_left} 天", "delta": 5})

    # ---- 门槛
    if any(k in blob for k in TEAM_KEYS):
        # 原文写了"1-3 人"就是可以单人成队，不能一律提示"确认能否单人参加"
        if re.search(r"[1１一]\s*[-–—~至]\s*[3３三]\s*人", blob) or "个人参赛" in blob:
            risks.append("可 1 人成队也可组队（1-3 人），组队能分担开发量")
        else:
            risks.append("需要组队，确认能否单人参加或尽快找人")
    if any(k in blob for k in MENTOR_KEYS):
        risks.append("需要指导教师，提前联系老师")

    score = max(0, min(100, score))

    if score >= 70:
        worth, priority = "强烈建议", ("P0" if (days_left is not None and days_left <= 3) else "P1")
    elif score >= 50:
        worth, priority = "可以考虑", "P2"
    else:
        worth, priority = "不建议", "P3"

    # ---- 行动清单
    # 注意：已截止的情况在第 90 行就早返回了，不走这里。
    if fields.get("deadline"):
        d = fields["deadline"]
        # 主倒计时可能落在"提交截止"上（报名已过），文案不能一律写"完成报名"，
        # 否则界面会出现"在 11-20 前完成报名"而实际报名 11-14 就关了。
        nodes = fields.get("deadlines") or []
        node = next((n for n in nodes if n.get("date") == d), {})
        label = node.get("label") or "截止"
        today_s = clock.today().isoformat()
        signup_passed = any(
            "报名" in (n.get("label") or "") and (n.get("date") or "9999") < today_s
            for n in nodes
        )
        if is_lecture:
            actions.append(f"把 {d} 的活动记入日历，确认与课程不冲突")
        elif "提交" in label:
            head = "报名窗口已关闭，" if signup_passed else ""
            actions.append(f"在 {d} 前完成作品提交（{head}只剩提交窗口）")
        elif days_left is not None and days_left <= 3:
            actions.append(f"今天之内完成报名，截止 {d}")
        else:
            actions.append(f"在 {d} 前完成报名，建议提前 3 天")
    else:
        if fields.get("event_date"):
            actions.append(f"把 {fields['event_date']} 的活动记入日历（无报名截止）")
        else:
            actions.append("原文未写截止日期，先去官网或群里确认时间")

    if category == "竞赛":
        actions.append("确认赛制与提交材料清单，按截止日倒排开发计划")
    elif category == "讲座":
        actions.append("提前确认地点，冲突则找录播")
    elif category == "招募":
        actions.append("确认服务时长能否认定，留存签到或证明")

    actions.append("下载日历事件，设置提前 1 天提醒")

    # ---- 条款依据：召回得到就引用，召回不到就明说"知识库里没有"，不编
    basis, grounded = [], False
    hits = (retrieval or {}).get("hits") or []
    if hits:
        grounded = True
        for h in hits[:2]:
            basis.append({"source": h["source"], "excerpt": _trim(h["text"], 110)})
        reasons.insert(0, f"判断有出处：{hits[0]['source']}")
    elif category in ("竞赛", "招募", "活动"):
        risks.append("知识库暂无对应认定条款，加分/时长结论待向学院核实")

    if is_duty:
        reasons.insert(0, "属于统一安排的事务（投票 / 集合 / 签到），不是可选机会：按时到场即可")
        risks.insert(0, "这条不用判断值不值得——按上面的时间地点到场，漏了要补办")
        parts.append({"label": "义务事务，不计机会价值", "delta": 0})

    summary = ("这是必须执行的事务通知，不是机会：按上面的时间到场，不用看匹配度。"
               if is_duty else _summary(worth, fields, days_left))

    return {
        "worth": worth,
        "priority": priority,
        "score": score,
        "summary": summary,
        "reasons": reasons[:4],
        "risks": risks[:3],
        "actions": actions[:3],
        "basis": basis,
        "grounded": grounded,
        "score_parts": parts,
        "profile": profile.get("identity", ""),
    }


def _trim(s, n):
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def _summary(worth, fields, days_left):
    name = fields.get("event_name") or "这条通知"
    if worth == "强烈建议":
        tail = f"，距截止还有 {days_left} 天" if days_left is not None else ""
        return f"{name} 值得投入：成本低、与你当前阶段匹配{tail}。"
    if worth == "可以考虑":
        return f"{name} 可以参加，但优先级不高，建议先把手上的主线任务排完。"
    return f"{name} 与你的当前目标匹配度较低，不建议投入时间。"
