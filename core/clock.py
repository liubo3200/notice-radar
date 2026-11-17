"""
统一的时间基准。

为什么需要它：测试集是 2026-11-06 至 11-13 采集的固定样本，而"最早未过期节点"必然随
真实日期漂移——今天跑 30/30，两个月后跑就不是了。评测要可复现，就必须能固定基准日。

优先级：环境变量 NOTICE_RADAR_TODAY > 系统当天日期。
生产运行不设该变量，行为与从前一致。
"""

import datetime
import os

_ENV_KEY = "NOTICE_RADAR_TODAY"


def today():
    raw = (os.environ.get(_ENV_KEY) or "").strip()
    if raw:
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError:
            pass
    return datetime.date.today()


def now():
    d = today()
    if d == datetime.date.today():
        return datetime.datetime.now()
    return datetime.datetime.combine(d, datetime.time(12, 0, 0))
