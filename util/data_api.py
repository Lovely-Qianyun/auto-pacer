# -*- coding: utf8 -*-
"""数据提交域：绑定设备查询与当日步数提交（api-mifit*.huami.com 主机域）

提交样本是抓包得到的完整当日数据（心率/睡眠/活动）URL 编码模板，
资产存放在 assets/fake_band_payload，运行时只替换日期、步数与设备号。
"""

import re
import time
import uuid
from pathlib import Path

import requests

from util.timeutil import get_time

UA_MIFIT_ANDROID = "MiFit6.14.0 (M2007J1SC; Android 12; Density/2.75)"

# 未绑定设备时的内置虚拟设备（平台首次提交成功后会自动登记）
DEFAULT_VIRTUAL_DEVICE = "DA932FFFFE8816E7"

_PAYLOAD_FILE = Path(__file__).resolve().parent.parent / "assets" / "fake_band_payload"
_payload_cache = None


def _load_payload() -> str:
    """读取抓包模板（惰性加载，内容不参与代码 diff）"""
    global _payload_cache
    if _payload_cache is None:
        _payload_cache = _PAYLOAD_FILE.read_text(encoding="utf-8")
    return _payload_cache


def _patch_payload(template: str, step, device_id, today: str) -> str:
    """把抓包模板里的日期/总步数/设备号替换为本次取值（纯函数，便于测试）"""
    find_date = re.compile(r".*?date%22%3A%22(.*?)%22%2C%22data.*?")
    find_step = re.compile(r".*?ttl%5C%22%3A(.*?)%2C%5C%22dis.*?")

    dates = find_date.findall(template)
    steps = find_step.findall(template)
    if not dates or not steps:
        raise ValueError("payload 模板格式异常：缺少 date 或 ttl 占位")

    template = re.sub(dates[0], today, template)
    template = re.sub(steps[0], str(step), template)
    if device_id:
        template = template.replace(DEFAULT_VIRTUAL_DEVICE, device_id)
    return template


# 查询用户在华米云端绑定的手环/手表设备ID
def get_user_device_id(app_token, userid):
    url = f"https://api-mifit-cn.huami.com/v1/device/binds.json?userid={userid}"
    headers = {
        "apptoken": app_token,
        "User-Agent": UA_MIFIT_ANDROID
    }
    try:
        resp = requests.get(url, headers=headers, timeout=5).json()
        items = resp.get("items", [])
        if items:
            # 1. 优先匹配 deviceType == 0 (手环/手表)
            for item in items:
                if item.get("deviceType") == 0:
                    dev_id = item.get("deviceId") or item.get("mac")
                    if dev_id:
                        return str(dev_id).replace(":", "").upper()
            # 2. 备选：按名称匹配
            for item in items:
                name = str(item.get("productName", "")).lower()
                if any(k in name for k in ["band", "watch", "手环", "手表"]):
                    dev_id = item.get("deviceId") or item.get("mac")
                    if dev_id:
                        return str(dev_id).replace(":", "").upper()
    except Exception as e:
        print(f"查询设备列表异常: {e}")
    return None


def post_fake_brand_data(step, app_token, userid, device_id=None):
    t = get_time()
    today = time.strftime("%F")

    data_json = _patch_payload(_load_payload(), step, device_id, today)

    url = f'https://api-mifit-cn.huami.com/v1/data/band_data.json?&t={t}&r={str(uuid.uuid4())}'
    head = {
        "apptoken": app_token,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    target_dev_id = device_id if device_id else DEFAULT_VIRTUAL_DEVICE
    data = f'userid={userid}&last_sync_data_time=1597306380&device_type=0&last_deviceid={target_dev_id}&data_json={data_json}'

    response = requests.post(url, data=data, headers=head, timeout=(3, 15))
    if response.status_code != 200:
        return False, "请求修改步数异常：%d" % response.status_code
    response = response.json()
    message = response["message"]
    if message == "success":
        return True, message
    else:
        return False, message
