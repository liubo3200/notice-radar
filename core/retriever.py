"""
Agent 4 · 检索（Retriever）
职责：把校内真实规则文档做成知识库，评估时召回原文条款，让每个结论都有出处。

实现取舍（答辩要点）：
- 用中文**二元组 BM25**，纯标准库，不引入向量数据库、不依赖 embedding 服务。
  切片只有几十条，BM25 的精度与向量检索相当，但零部署成本、可解释（能打印命中词）。
- 切片粒度按 `##` 小节切，200–500 字，每片带来源标注（文件名 § 小节）。
- 检索不到就返回空，让上游明说"知识库里没有这条规定"，而不是编一条。
"""

import math
import os
import re
from collections import Counter

KB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")

K1 = 1.4
B = 0.72
# 两道闸：绝对分 + 相对首条的比例。宁可判"知识库没这条规定"，也不要硬凑一条引用。
# 实测：本校竞赛通知 ≈ 73 分，讲座类 ≈ 11 分，标定阈值取 14。
MIN_SCORE = 14.0
REL_CUT = 0.35

_IDX = {"mtime": None, "slices": [], "df": Counter(), "avg_len": 0.0, "n": 0}


def _tokenize(text):
    """中文取二元组，英文/数字按词。不引入分词库。"""
    text = (text or "").lower()
    toks = []
    for m in re.finditer(r"[a-z0-9]+|[\u4e00-\u9fff]+", text):
        w = m.group(0)
        if w[0].isascii():
            toks.append(w)
        else:
            for i in range(len(w) - 1):
                toks.append(w[i:i + 2])
    return toks


def _split_slices(path):
    """按 `##` 小节切片；没有小节的文档整篇作为一片。"""
    with open(path, encoding="utf-8") as f:
        raw = f.read()

    name = os.path.basename(path)[:-3]
    m = re.search(r"(?m)^#\s+(.+)$", raw)
    title = m.group(1).strip() if m else name

    out = []
    parts = re.split(r"(?m)^##\s+", raw)
    for i, part in enumerate(parts):
        if i == 0:
            body = re.sub(r"(?m)^#\s+.+$", "", part)
            section = "概述"
        else:
            lines = part.split("\n", 1)
            section = lines[0].strip()
            body = lines[1] if len(lines) > 1 else ""

        body = body.strip()
        # 去掉引用块里的使用说明，避免污染检索
        body = re.sub(r"(?m)^>.*$", "", body).strip()
        if len(body) < 20:
            continue
        out.append({
            "file": os.path.basename(path),
            "doc_title": title,
            "section": section,
            "source": f"《{title}》§{section}",
            "text": body,
        })
    return out


def _build():
    slices, df = [], Counter()
    paths = []
    if os.path.isdir(KB_DIR):
        paths = sorted(
            os.path.join(KB_DIR, f) for f in os.listdir(KB_DIR) if f.endswith(".md")
        )
    newest = 0.0
    for p in paths:
        newest = max(newest, os.path.getmtime(p))
        for s in _split_slices(p):
            s["tokens"] = Counter(_tokenize(f"{s['doc_title']} {s['section']} {s['text']}"))
            s["len"] = sum(s["tokens"].values())
            slices.append(s)
            for t in s["tokens"]:
                df[t] += 1

    _IDX.update({
        "mtime": newest,
        "slices": slices,
        "df": df,
        "n": len(slices),
        "avg_len": (sum(s["len"] for s in slices) / len(slices)) if slices else 0.0,
    })


def _ensure_fresh():
    """文件改了自动重建索引，改知识库不用重启服务（现场演示要用）。"""
    paths = []
    if os.path.isdir(KB_DIR):
        paths = [os.path.join(KB_DIR, f) for f in os.listdir(KB_DIR) if f.endswith(".md")]
    newest = max((os.path.getmtime(p) for p in paths), default=0.0)
    if _IDX["mtime"] != newest or not _IDX["slices"]:
        _build()


def _idf(token):
    n, df = _IDX["n"], _IDX["df"].get(token, 0)
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


def search(query, top_k=3, min_score=MIN_SCORE):
    """返回 {"hits": [...], "hit_terms": [...], "empty": bool}。"""
    _ensure_fresh()
    if not _IDX["slices"] or not query:
        return {"hits": [], "hit_terms": [], "empty": True}

    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return {"hits": [], "hit_terms": [], "empty": True}

    scored = []
    for s in _IDX["slices"]:
        score, matched = 0.0, []
        for t in q_tokens:
            tf = s["tokens"].get(t, 0)
            if not tf:
                continue
            denom = tf + K1 * (1 - B + B * s["len"] / (_IDX["avg_len"] or 1))
            score += _idf(t) * (tf * (K1 + 1)) / denom
            matched.append(t)
        # 命中词太散时（只有"通知""关于"这类）不值得引用
        if matched:
            score *= min(1.0, len(matched) / 8.0)
        if score >= min_score:
            scored.append((score, matched, s))

    scored.sort(key=lambda x: -x[0])
    if scored:
        floor = max(min_score, scored[0][0] * REL_CUT)
        scored = [x for x in scored if x[0] >= floor]

    hits = [
        {
            "source": s["source"],
            "file": s["file"],
            "section": s["section"],
            "text": s["text"],
            "score": round(score, 2),
            "matched": matched[:8],
        }
        for score, matched, s in scored[:top_k]
    ]
    terms = sorted({t for _, m, _ in scored[:top_k] for t in m})[:10]
    return {"hits": hits, "hit_terms": terms, "empty": not hits}


def stats():
    _ensure_fresh()
    files = sorted({s["file"] for s in _IDX["slices"]})
    return {"slices": _IDX["n"], "files": files}
