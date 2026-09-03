# -*- coding: utf8 -*-
"""北京时间工具：提交接口要求东八区时间戳"""
from datetime import datetime

import pytz


def get_beijing_time():
    target_timezone = pytz.timezone('Asia/Shanghai')
    # 获取当前时间
    return datetime.now().astimezone(target_timezone)


def format_now():
    return get_beijing_time().strftime("%Y-%m-%d %H:%M:%S")


def get_time():
    """毫秒级时间戳字符串（平台接口参数）"""
    current_time = get_beijing_time()
    return "%.0f" % (current_time.timestamp() * 1000)
