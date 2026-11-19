"""
Agent 1 · 抽取（Extractor）
职责：从一段杂乱的通知文本里，抽取出结构化字段。
策略：优先调用大模型；不可用时自动降级为规则解析，保证永远有输出。
"""

import json
import os
import re
import datetime

import requests

from core import clock

# ---------------------------------------------------------------- 基础配置

TODAY = clock.today()

DATE_FULL = re.compile(r"(20\d{2})\s*[年\-/\.]\s*(\d{1,2})\s*[月\-/\.]\s*(\d{1,2})\s*日?")
DATE_CN = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
DATE_SLASH = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)")
TIME_RANGE = re.compile(r"(\d{1,2}[:：]\d{2})\s*[—\-~至到]+\s*(\d{1,2}[:：]\d{2})")
TIME_CN = re.compile(r"(上午|下午|晚上|中午)?\s*(\d{1,2})\s*[点時时]\s*(半|\d{1,2}\s*分?)?")

DEADLINE_KEYS = [
    "报名截止", "截止时间", "截止日期", "截止至", "截至", "请于", "前完成",
    "报名时间", "deadline", "报名日期", "提交截止", "提交", "截止", "报名",
    "比赛时间", "参赛时间",
    "办理时间", "申报时间", "报送时间", "申请时间", "缴费时间", "集中办理",
]
# 门户页面自带的噪声行（只认行首的元信息，避免误伤正文里提到"附件"的句子）
NOISE_RE = re.compile(r"^\s*(发布部门|发布时间|浏览|来源|点击量|扫一扫|分享到)")
NOISE_LINE = ("发布部门", "发布时间", "扫一扫")


def _is_noise(s):
    return bool(NOISE_RE.match(s)) or any(k in s for k in NOISE_LINE)

# "于 11 月 13 日下班前将……报送"这类写法，中文通知里极常见，
# 关键词表覆盖不全，用模式兜一层。
BEFORE_RE = re.compile(
    r"(20\d{2}\s*[年\-/\.]\s*\d{1,2}\s*[月\-/\.]\s*\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*[日号])"
    r"[^。；\n]{0,12}?前"
)
TITLE_SKIP = ("各位", "同学", "同学们", "各部门", "各学院", "根据", "按照", "为进一步", "现将")

CATEGORY_RULES = [
    # 事务类放最前：停水停电这类通知里常夹带"时间/地点"，容易被误判成活动机会
    ("事务", ["停水", "停电", "停暖", "停气", "维修", "施工", "招标", "采购", "聘任",
              "任免", "工作要点", "放假", "调课", "体检", "报销", "收费", "供暖",
              "售房", "出售", "房源", "充值", "房屋", "通行证", "车证", "通停证"]),
    ("竞赛", ["大赛", "竞赛", "比赛", "挑战赛", "擂台", "选拔赛", "评选"]),
    ("讲座", ["讲座", "报告会", "学术报告", "分享会", "论坛", "沙龙", "宣讲会", "讲坛"]),
    ("招募", ["招募", "招新", "征集", "纳新", "志愿者"]),
    ("活动", ["活动", "打卡", "训练营", "工作坊", "展览", "培训", "课程", "运动会"]),
]

FIELD_SCHEMA = {
    "event_name": "活动/赛事全称",
    "deadline": "报名或提交截止日期，格式 YYYY-MM-DD，没有就 null",
    "event_time": "活动举办时间，尽量保留原文表述，没有就 null",
    "target": "面向对象/参赛资格，没有就 null",
    "organizer": "主办或承办单位，没有就 null",
    "category": "类别，只能取：竞赛 / 讲座 / 招募 / 活动 / 其他",
    "link": "原文中的网址，没有就 null",
}


# ---------------------------------------------------------------- 规则抽取

def _clean_lines(text):
    lines = [l.strip() for l in text.replace("\r", "").split("\n")]
    return [l for l in lines if l]


def _find_date(s, allow_slash=True):
    """从一段文字里找日期，缺年份时按当年补全。"""
    m = DATE_FULL.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe_date(y, mo, d)
    m = DATE_CN.search(s)
    if m:
        return _safe_date(TODAY.year, int(m.group(1)), int(m.group(2)))
    if allow_slash:
        m = DATE_SLASH.search(s)
        if m:
            return _safe_date(TODAY.year, int(m.group(1)), int(m.group(2)))
    return None


def _safe_date(y, m, d):
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None


_BRACKET_PREFIX = re.compile(r"^(?:【[^】]{0,12}】|\[[^\]]{0,12}\])\s*")
_GENERIC_WORD = re.compile(
    r"^(?:竞赛|讲座|活动|工作|学术|招募|培训|会议|报告|公示|评选)(?:通知|公告|告示|信息)[:：丨|]?\s*"
)


def _strip_prefix(s):
    """剥掉标题开头的分类前缀。

    原文第一行常写成「【竞赛通知】北京邮电大学…的通知」，
    只删括号符号会留下"竞赛通知"，和页面上的分类标签重复，标题白白长 4 个字。
    """
    prev = None
    while prev != s:
        prev = s
        s = _BRACKET_PREFIX.sub("", s)
        s = _GENERIC_WORD.sub("", s)
    return s.strip(" 　")


_SYMBOL_ONLY = re.compile(r"[^\w\u4e00-\u9fff]+")


def _pick_title(lines):
    # 0) 「【人大代表选举投票】❗️❗️❗️」：整行只有括号和表情时，括号里就是标题。
    #    （【竞赛通知】北京邮电大学…这种括号后面还有正文的，不适用，走下面的规则）
    if lines:
        m = re.match(r"^[【\[《]([^】\]》]{2,30})[】\]》]\s*[^\w\u4e00-\u9fff]*$", lines[0].strip())
        if m:
            t = _GENERIC_WORD.sub("", m.group(1)).strip()
            if 4 <= len(t) <= 30:
                return t

    # 1) 优先取"……通知 / 招募 / 大赛"这类标题行
    for line in lines[:8]:
        # 「【人大代表选举投票】❗️❗️❗️」剥掉括号后只剩表情，会把整条标题带偏
        s = _SYMBOL_ONLY.sub(" ", _strip_prefix(line)).strip()
        if 4 <= len(s) <= 50 and re.search(r"(通知|公告|告示|招募|大赛|竞赛|章程|方案)$", s):
            return s
    # 2) 退化为第一行像标题的文本
    for line in lines[:8]:
        # "投票时间：本周五 8:00-10:00" 是字段行，不是标题
        if re.match(r"^[^：:]{1,10}[：:]", line.strip()):
            continue
        s = _SYMBOL_ONLY.sub(" ", _strip_prefix(line)).strip()
        if len(s) < 6 or s.startswith(TITLE_SKIP):
            continue
        if re.match(r"^[一二三四五六七八九十]、", s):
            continue
        if s.startswith(("报名截止", "截止", "时间", "地点")):
            return ""
        return s[:60]
    return (lines[0][:60] if lines else "")


# 一条通知常有多个截止节点（报名截止 / 提交截止 / 推荐单位盖章……），
# 只报一个会误导，所以这里把全部节点抽出来，由上层决定主倒计时并全部展示。
LABEL_RULES = [
    ("提交截止", ("提交截止", "作品提交", "提交时间", "提交", "报送作品")),
    ("比赛截止", ("比赛时间", "参赛时间")),
    # "请于" 不再单独算报名：讲座、评教、交材料都写"请于 X 前完成"，
    # 一律标成"报名截止"会凭空造出一个不存在的报名环节（用户实测反馈过）。
    ("报名截止", ("报名截止", "报名时间", "之前报名", "报名")),
    ("截止", ("截止", "截至", "前完成")),
]


def _all_dates(s):
    """一行里可能写了多个日期，全部取出来。"""
    out = []
    for m in DATE_FULL.finditer(s):
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            out.append(d)
    for m in DATE_CN.finditer(s):
        d = _safe_date(TODAY.year, int(m.group(1)), int(m.group(2)))
        if d:
            out.append(d)
    if not out:
        for m in DATE_SLASH.finditer(s):
            d = _safe_date(TODAY.year, int(m.group(1)), int(m.group(2)))
            if d:
                out.append(d)
    return out


def _label_for(line):
    for label, keys in LABEL_RULES:
        if any(k in line for k in keys):
            return label
    return "截止"


def _pick_deadlines(text, lines):
    """返回 (deadlines, source)。只认真正的"截止/报名/比赛"表述，不再兜底猜日期。

    之前的兜底猜测会把"发布时间"或"活动举办日"当截止日，真实通知里 8/10 条全中招。
    宁可报"没有截止日"，也不要给一个错的倒计时。
    """
    found = []
    total = len(lines)
    for i, line in enumerate(lines):
        if _is_noise(line):
            continue
        if not any(k in line for k in DEADLINE_KEYS) and not BEFORE_RE.search(line):
            continue
        label = _label_for(line)
        dates = _all_dates(line)
        if not dates and len(line.strip()) <= 20 and re.search(
            r"(报名|提交|办理|申报|报送|申请|截止|时间|日期)", line
        ):
            # 表格型通知每个单元格独占一行、中间夹空行。只看紧跟的第一个非空行，
            # 且该行必须"几乎只有日期"。原来取 i+1/i+2 会越界读到下一节点的日期，
            # 导致两个节点被标成同一个标签（"校赛启动与报名"读到了提交节点）。
            for j in range(i + 1, min(i + 4, total)):
                nxt = lines[j]
                if not nxt.strip() or _is_noise(nxt):
                    continue
                rest = DATE_FULL.sub("", DATE_CN.sub("", DATE_SLASH.sub("", nxt)))
                rest = re.sub(r"[\s、,，.．:：\-—~～至到日]", "", rest)
                if len(rest) <= 8:
                    dates = _all_dates(nxt)
                break
        for d in dates:
            found.append((d, label))

    source = "keyword" if found else None

    # 同一日期只留一次，标签取先出现的
    seen, uniq = set(), []
    for d, label in found:
        if d in seen:
            continue
        seen.add(d)
        uniq.append({"date": d.isoformat(), "label": label, "_d": d})

    uniq.sort(key=lambda x: x["_d"])
    # 过滤明显跑飞的日期（多于一年），避免把"2027年"之类当截止
    uniq = [x for x in uniq if abs((x["_d"] - TODAY).days) <= 400]
    for x in uniq:
        x.pop("_d", None)

    # 有明确的报名/提交截止时，"比赛时间/参赛时间"只是赛程，不再算截止节点
    # （否则"报名 11-13 已过、比赛 11-28 未到"，会把比赛日当成还能报名的截止日）
    if any(x["label"] in ("报名截止", "提交截止") for x in uniq):
        uniq = [x for x in uniq if x["label"] != "比赛截止"]

    return uniq, (source if uniq else None)


def _pick_event_date(text):
    """活动举办日（不是截止日）。讲座/线上课只有这个，没有截止。"""
    t = _pick_time(text)
    if not t:
        return None
    d = _find_date(t)
    return d.isoformat() if d else None


REL_WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6, "七": 6}


def _relative_date(text, today=None):
    """群通知常写"明天""本周五"，没有绝对日期。

    这类通知在测试集里抽不到时间就会退化成"没有截止日期"，倒计时整块消失——
    用户实测里最刺眼的就是这一点（一条要求明早 8:10 集合的通知，界面上没有时间）。
    """
    today = today or TODAY
    if "大后天" in text:
        return today + datetime.timedelta(days=3)
    if re.search(r"(?<!大)后天", text):
        return today + datetime.timedelta(days=2)
    if re.search(r"明天|明日", text):
        return today + datetime.timedelta(days=1)
    m = re.search(r"(下下|下|本|这|上)?\s*(?:周|星期|礼拜)\s*([一二三四五六日天七])", text)
    if m:
        mod, cn = m.group(1) or "", m.group(2)
        cur = today.weekday()
        delta = REL_WEEKDAY[cn] - cur
        if mod == "下下":
            delta += 14
        elif mod == "下":
            delta += 7
        elif mod == "上":
            delta -= 7
        elif delta < 0:          # "本周五"说在周日之后，只有可能是下周
            delta += 7
        return today + datetime.timedelta(days=delta)
    return None


def _pick_target(text):
    lines = _clean_lines(text)
    # 0) 标签行没写值（"二、培训对象" 换行写对象）→ 取下一行
    for i, line in enumerate(lines):
        s = line.strip()
        if len(s) <= 22 and re.search(r"(对象|范围|资格)[：:]?\s*$", s) and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if 2 <= len(nxt) <= 60 and not re.match(r"^[一二三四五六七八九十]、", nxt):
                return nxt.strip(" ：:，,")

    m = re.search(r"(面向|参赛对象|参加对象|参与对象|参赛资格|参加人员|培训对象|征集对象|招募对象|参赛人员范围|申请条件|申请对象|资助对象|招新对象)[：:\s]*([^\n。；;]{2,40})", text)
    if m:
        val = m.group(2).strip(" ：:，,")
        # 去掉"对象：""人员："这类残留前缀
        val = re.sub(r"^(对象|人员|范围|资格|要求)[：:]\s*", "", val)
        # 截断到下一个字段关键词，避免把"主办：xxx"一起吃进来；
        # 也要在逗号/"请"/"需"处断开——实测"面向 11-13 班同学，请于11月25日前完成"
        # 会把整句当对象，用户一眼就看穿这是错的
        val = re.split(r"\s*(主办|承办|时间|地点|报名|联系|请|需|要求|务必)", val)[0]
        val = re.split(r"[，,；;]", val)[0]
        return val.strip(" ：:，,")
    # 没有"面向/对象"这类前缀，但写了具体班级：「明天请11-13班同学于8:10集合」
    m = re.search(r"(\d{1,2}\s*[-–—~至]\s*\d{1,2}\s*班(?:同学|学生)?)", text)
    if m:
        return m.group(1).replace(" ", "")
    if "全体" in text and "学生" in text:
        return "全体学生"
    return None


def _pick_organizer(text):
    m = re.search(r"(主办单位|承办单位|主办|承办)[：:\s]*([^\n，,。；;]{2,30})", text)
    if m:
        return m.group(2).strip(" ：:，,")
    m = re.search(r"由\s*([^\n，,。；;]{2,25})\s*(主办|承办|举办)", text)
    if m:
        return m.group(1).strip()
    return None


def _pick_category(text, title):
    # 标题里直接写"招新/招募/征集"的，优先按招募算，别被正文里的"比赛"带走
    if title and any(k in title for k in ("招新", "招募", "征集", "纳新")):
        return "招募"
    blob = (title or "") + text[:400]
    for cat, keys in CATEGORY_RULES:
        if any(k in blob for k in keys):
            return cat
    return "其他"


def _pick_time(text):
    """活动时间。真实通知里"标签一行、日期另起一行"极常见，必须跨行取。"""
    lines = _clean_lines(text)
    for i, line in enumerate(lines):
        s = line.strip()
        if len(s) > 60 or _is_noise(s):
            continue
        if not re.search(r"时间[）)]*[：:]?\s*$|时间[：:]", s):
            continue
        # "报名时间/截止时间/申请时间"是截止类字段，不能当成活动举办时间
        if re.search(r"报名|截止|提交|请于|申请|报送", s):
            continue

        tail = re.sub(r"^.*?时间[）)]*[：:]\s*", "", s).strip()
        if tail and (_find_date(tail) or TIME_RANGE.search(tail) or TIME_CN.search(tail)):
            return tail[:50]
        # 值在下面一两行
        for j in (i + 1, i + 2):
            if j >= len(lines):
                break
            nxt = lines[j].strip()
            if _is_noise(nxt):
                continue
            if _find_date(nxt) or TIME_RANGE.search(nxt):
                return nxt[:50]
    m = TIME_RANGE.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def _pick_link(text):
    m = re.search(r"https?://[^\s，,。）)】\]\"']+", text)
    return m.group(0) if m else None


def _pick_primary(deadlines):
    """主倒计时取最早一个未过期的节点；全部过期则保留最近一个，让「已截止」可见。"""
    dates = []
    for x in deadlines or []:
        try:
            dates.append(datetime.date.fromisoformat(x["date"]))
        except (KeyError, ValueError):
            continue
    if not dates:
        return None
    future = [d for d in dates if d >= TODAY]
    return (min(future) if future else max(dates)).isoformat()


def parse_by_rules(text):
    """不依赖任何外部服务，纯规则抽取。永远能返回结果。"""
    lines = _clean_lines(text)
    title = _pick_title(lines)
    deadlines, dl_source = _pick_deadlines(text, lines)
    event_date = _pick_event_date(text)
    if not deadlines and not event_date:
        rel = _relative_date(text)
        if rel:
            event_date = rel.isoformat()
            dl_source = "relative"
    return {
        "event_name": title or None,
        "deadline": _pick_primary(deadlines),
        "deadlines": deadlines,
        "deadline_source": dl_source,
        "event_date": event_date,
        "event_time": _pick_time(text),
        "target": _pick_target(text),
        "organizer": _pick_organizer(text),
        "category": _pick_category(text, title),
        "link": _pick_link(text),
        "fallback": True,
    }


# ---------------------------------------------------------------- 大模型抽取

SYSTEM_PROMPT = """你是校园通知信息抽取器。从用户给的通知文本中抽取字段，只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块。

字段与要求：
{schema}

规则：
1. 原文没有的信息一律填 null，绝对不要编造。
2. deadline 必须是 YYYY-MM-DD；原文只写"11月14日"这类缺年份的，按 {year} 年补全。
3. 若出现多个日期，deadline 取"报名/提交截止"那个，不是活动举办日期。
4. category 只能是：竞赛 / 讲座 / 招募 / 活动 / 其他。
5. event_name 取通知标题，去掉【】等符号，不超过 40 字。
"""


def _llm_config():
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "").rstrip("/"),
        "api_key": os.environ.get("LLM_API_KEY", ""),
        "model": os.environ.get("LLM_MODEL", ""),
    }


def llm_available():
    c = _llm_config()
    return bool(c["base_url"] and c["api_key"] and c["model"])


def parse_by_llm(text, timeout=20):
    """调用 OpenAI 兼容接口抽取。任何异常返回 None，由上层降级。"""
    cfg = _llm_config()
    if not llm_available():
        return None

    schema = "\n".join(f"- {k}: {v}" for k, v in FIELD_SCHEMA.items())
    payload = {
        "model": cfg["model"],
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.format(schema=schema, year=TODAY.year)},
            {"role": "user", "content": text[:4000]},
        ],
    }
    try:
        r = requests.post(
            f"{cfg['base_url']}/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg['api_key']}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.M).strip()
        data = json.loads(content)
    except Exception:
        return None

    out = {k: data.get(k) for k in FIELD_SCHEMA}
    out["fallback"] = False
    return out


def extract(text):
    """对外入口：LLM 优先，失败自动降级。两种通道都补上多截止节点。"""
    if not text or len(text.strip()) < 10:
        return {"error": "文本太短，至少粘一段完整通知"}
    result = parse_by_llm(text)
    if result is None:
        return parse_by_rules(text)

    # LLM 通道只给一个 deadline，多节点明细仍由规则补齐（两条通道互为校验）
    deadlines, dl_source = _pick_deadlines(text, _clean_lines(text))
    result["deadlines"] = deadlines
    result["deadline_source"] = dl_source
    result.setdefault("event_date", _pick_event_date(text))
    return result
