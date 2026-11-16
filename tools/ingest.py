"""
把规则原文切成知识库切片。

用法（Windows）：
    python tools/ingest.py "C:\\路径\\推免规定.txt" --title "北京邮电大学推荐优秀应届本科毕业生免试攻读研究生管理规定" --out 04-推免-规定全文.md

切分规则：优先按「第X条」「一、二、三、」「## 」标题切；都没有就按 400 字硬切。
切完直接写进 knowledge/，服务无需重启（retriever 会检测文件改动自动重建索引）。
"""

import argparse
import os
import re

KB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")

SPLIT_PATTERNS = [
    r"(?m)^\s*(第[一二三四五六七八九十百]+条)",
    r"(?m)^\s*([一二三四五六七八九十]+、)",
    r"(?m)^\s*(\d+[\.、]\s)",
    r"(?m)^##\s+",
]


def read_any(path):
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"读不了这个编码：{path}")


def split(text, max_len=500):
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    for pat in SPLIT_PATTERNS:
        parts = re.split(pat, text)
        if len(parts) >= 6:
            # re.split 带捕获组：奇偶交替是分隔符与内容
            segs, buf = [], ""
            for i, p in enumerate(parts):
                if i % 2 == 1:
                    if buf.strip():
                        segs.append(buf.strip())
                    buf = p
                else:
                    buf += p
            if buf.strip():
                segs.append(buf.strip())
            return _merge(segs, max_len)
    return _merge([text[i:i + 400] for i in range(0, len(text), 400)], max_len)


def _merge(segs, max_len):
    """太短的片段并到下一段，避免切片碎成一句话。"""
    out, buf = [], ""
    for s in segs:
        s = s.strip()
        if not s:
            continue
        if buf and len(buf) + len(s) > max_len:
            out.append(buf)
            buf = s
        else:
            buf = (buf + "\n" + s).strip()
    if buf:
        out.append(buf)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--title", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    text = read_any(args.src)
    title = args.title or os.path.splitext(os.path.basename(args.src))[0]
    segs = split(text)

    out_name = args.out or f"99-导入-{title[:20]}.md"
    path = os.path.join(KB, out_name)
    os.makedirs(KB, exist_ok=True)

    lines = [f"# {title}", ""]
    for i, s in enumerate(segs, 1):
        first = s.split("\n")[0][:18].strip(" 　#")
        lines.append(f"## {first or f'第{i}段'}")
        lines.append(s)
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"写入 {path}：{len(segs)} 条切片，{sum(len(s) for s in segs)} 字")


if __name__ == "__main__":
    main()
