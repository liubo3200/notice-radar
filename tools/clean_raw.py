"""
把从门户网页 Ctrl+A 复制下来的文本，清洗成"通知原文"。

门户页面会带一堆导航和页脚，直接喂给解析器等于作弊（真实场景是用户只粘正文）。
清洗规则：取「正文」到「相关通知 / 公告附件如下 / 最新通知」之间的内容。
"""

import glob
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "testset", "raw")
CLEAN = os.path.join(BASE, "testset", "clean")

END_MARKERS = ["相关通知", "公告附件如下", "最新通知", "院系机构", "版权所有"]


def clean(text):
    text = text.replace("\r\n", "\n").replace("\u00a0", " ")
    # 去掉门户头部：从"正文"标记之后开始
    m = re.search(r"正文\s*\n", text)
    if m:
        text = text[m.end():]
    # 去掉尾部
    for mk in END_MARKERS:
        i = text.find(mk)
        if i > 100:
            text = text[:i]
    # 折叠多余空格与空行
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main():
    os.makedirs(CLEAN, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(RAW, "*.txt"))):
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        out = clean(raw)
        dst = os.path.join(CLEAN, os.path.basename(path))
        with open(dst, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"{os.path.basename(path)}  {len(raw)} → {len(out)} 字")


if __name__ == "__main__":
    main()
