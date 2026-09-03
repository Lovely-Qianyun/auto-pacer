# -*- coding: utf8 -*-
"""账号/认证域接口：登录与各级令牌的获取、续期、校验（account*/auth*.huami.com / zepp.com）

令牌梯子见 main.py：app_token → login_token → access_token → 账号密码。
所有函数只返回 (结果, 错误信息)，不打印敏感内容（token_info 绝不落 stdout）。
"""

import json
import re
import traceback
import urllib
import uuid

import requests

from util.aes_help import HM_AES_IV, HM_AES_KEY, encrypt_data
from util.timeutil import get_time

UA_MIFIT_ANDROID = "MiFit6.14.0 (M2007J1SC; Android 12; Density/2.75)"
UA_MIFIT_IOS = "MiFit/5.3.0 (iPhone; iOS 14.7.1; Scale/3.00)"


def _safe_summary(resp):
    """只保留响应中的非敏感字段，杜绝把 token_info 打进日志"""
    if not isinstance(resp, dict):
        return str(resp)
    return {k: resp.get(k) for k in ("result", "error_code", "message", "error_description")
            if k in resp}


# 通过账号密码获取 access_token（refresh_token 平台未暴露使用方式，仅作记录）
def login_access_token(user, password):
    headers = {
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "user-agent": UA_MIFIT_ANDROID,
        "app_name": "com.xiaomi.hm.health",
        "appname": "com.xiaomi.hm.health",
        "appplatform": "android_phone",
        "x-hm-ekv": "1",
        "hm-privacy-ceip": "false"
    }
    login_data = {
        'emailOrPhone': user,
        'password': password,
        'state': 'REDIRECTION',
        'client_id': 'HuaMi',
        'country_code': 'CN',
        'token': 'access',
        'redirect_uri': 'https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html',
    }
    # 等同 http_build_query，默认使用 quote_plus 将空格转为 '+'
    query = urllib.parse.urlencode(login_data)
    plaintext = query.encode('utf-8')
    # 官方协议要求：请求体用固定密钥 AES-128-CBC 加密（密钥为客户端内置值，非用户级机密）
    cipher_data = encrypt_data(plaintext, HM_AES_KEY, HM_AES_IV)

    url1 = 'https://api-user.zepp.com/v2/registrations/tokens'
    r1 = requests.post(url1, data=cipher_data, headers=headers, allow_redirects=False, timeout=5)
    if r1.status_code != 303:
        return None, "登录异常，status: %d" % r1.status_code
    try:
        location = r1.headers["Location"]
        code = get_access_token(location)
        if code is None:
            return None, "获取accessToken失败 %s" % get_error_code(location)
    except Exception:
        return None, f"获取accessToken异常:{traceback.format_exc()}"
    return code, None


# 从 303 Location 中解析 access token
def get_access_token(location):
    code_pattern = re.compile("(?<=access=).*?(?=&)")
    result = code_pattern.findall(location)
    if result is None or len(result) == 0:
        return None
    return result[0]


def get_error_code(location):
    code_pattern = re.compile("(?<=error=).*?(?=&)")
    result = code_pattern.findall(location)
    if result is None or len(result) == 0:
        return None
    return result[0]


# 用 access_token 换 login_token + app_token + user_id
def grant_login_tokens(access_token, device_id, is_phone=False):
    url = "https://account.huami.com/v2/client/login"
    headers = {
        "app_name": "com.xiaomi.hm.health",
        "x-request-id": f"{str(uuid.uuid4())}",
        "accept-language": "zh-CN",
        "appname": "com.xiaomi.hm.health",
        "cv": "50818_6.14.0",
        "v": "2.0",
        "appplatform": "android_phone",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    if is_phone:
        data = {
            "app_name": "com.xiaomi.hm.health",
            "app_version": "6.14.0",
            "code": access_token,
            "country_code": "CN",
            "device_id": device_id,
            "device_model": "phone",
            "grant_type": "access_token",
            "third_name": "huami_phone",
        }
    else:
        # 注意 "allow_registration=" 键名带尾随等号是协议原样，勿改
        data = {
            "allow_registration=": "false",
            "app_name": "com.xiaomi.hm.health",
            "app_version": "6.14.0",
            "code": access_token,
            "country_code": "CN",
            "device_id": device_id,
            "device_model": "android_phone",
            "dn": "account.zepp.com,api-user.zepp.com,api-mifit.zepp.com,api-watch.zepp.com,app-analytics.zepp.com,api-analytics.huami.com,auth.zepp.com",
            "grant_type": "access_token",
            "lang": "zh_CN",
            "os_version": "1.5.0",
            "source": "com.xiaomi.hm.health:6.14.0:50818",
            "third_name": "email",
        }
    resp = requests.post(url, data=data, headers=headers, timeout=(3, 15)).json()
    _login_token, _userid, _app_token = None, None, None
    try:
        result = resp.get("result")
        if result != "ok":
            return None, None, None, "客户端登录失败：%s" % result
        _login_token = resp["token_info"]["login_token"]
        _app_token = resp["token_info"]["app_token"]
        _userid = resp["token_info"]["user_id"]
    except Exception:
        # 只打印非敏感字段，完整响应可能含 token_info
        print("提取login_token失败：%s" % json.dumps(_safe_summary(resp), ensure_ascii=False))
    return _login_token, _app_token, _userid, None


# 用 login_token 续期 app_token（用于提交数据变更）
def grant_app_token(login_token: str):
    url = (f"https://account-cn.huami.com/v1/client/app_tokens?app_name=com.xiaomi.hm.health"
           f"&dn=api-user.huami.com%2Capi-mifit.huami.com%2Capp-analytics.huami.com&login_token={login_token}")
    headers = {'User-Agent': UA_MIFIT_IOS}
    resp = requests.get(url, headers=headers, timeout=(3, 15))
    if resp.status_code != 200:
        return None, "请求异常：%d" % resp.status_code
    resp = resp.json()

    result = resp.get("result")
    if result != "ok":
        error_code = resp.get("error_code")
        return None, "请求失败：%s" % error_code
    app_token = resp['token_info']['app_token']
    return app_token, None


# 校验 app_token 是否仍有效
def check_app_token(app_token):
    url = "https://api-mifit-cn3.zepp.com/huami.health.getUserInfo.json"

    params = {
        "r": "00b7912b-790a-4552-81b1-3742f9dd1e76",
        # 抓包残留的用户级参数：服务端以 header 中的 apptoken 为准，保留以免行为变化
        "userid": "1188760659",
        "appid": "428135909242707968",
        "channel": "Normal",
        "country": "CN",
        "cv": "50818_6.14.0",
        "device": "android_31",
        "device_type": "android_phone",
        "lang": "zh_CN",
        "timezone": "Asia/Shanghai",
        "v": "2.0"
    }

    headers = {
        "User-Agent": UA_MIFIT_ANDROID,
        "Accept-Encoding": "gzip",
        "hm-privacy-diagnostics": "false",
        "country": "CN",
        "appplatform": "android_phone",
        "hm-privacy-ceip": "true",
        "x-request-id": str(uuid.uuid4()),
        "timezone": "Asia/Shanghai",
        "channel": "Normal",
        "cv": "50818_6.14.0",
        "appname": "com.xiaomi.hm.health",
        "v": "2.0",
        "apptoken": app_token,
        "lang": "zh_CN",
        "clientid": "428135909242707968"
    }
    response = requests.get(url, params=params, headers=headers, timeout=(3, 15))
    if response.status_code != 200:
        return False, "请求异常：%d" % response.status_code
    response = response.json()
    message = response["message"]
    if message == "success":
        return True, None
    else:
        return False, message


# 续期 login_token（令牌约 30 天过期，main.py 在超期前提前续期）
def renew_login_token(login_token):
    url = "https://account-cn3.zepp.com/v1/client/renew_login_token"
    params = {
        "os_version": "v0.8.1",
        "dn": "account.zepp.com,api-user.zepp.com,api-mifit.zepp.com,api-watch.zepp.com,app-analytics.zepp.com,api-analytics.huami.com,auth.zepp.com",
        "login_token": login_token,
        "source": "com.xiaomi.hm.health:6.14.0:50818",
        "timestamp": get_time()
    }
    headers = {
        "User-Agent": UA_MIFIT_ANDROID,
        "Accept-Encoding": "gzip",
        "app_name": "com.xiaomi.hm.health",
        "hm-privacy-ceip": "false",
        "x-request-id": str(uuid.uuid4()),
        "accept-language": "zh-CN",
        "appname": "com.xiaomi.hm.health",
        "cv": "50818_6.14.0",
        "v": "2.0",
        "appplatform": "android_phone"
    }

    resp = requests.get(url, params=params, headers=headers, timeout=(3, 15))
    if resp.status_code != 200:
        return None, "请求异常：%d" % resp.status_code
    resp = resp.json()
    result = resp["result"]

    if result != "ok":
        return None, "请求失败：%s" % result
    login_token = resp["token_info"]["login_token"]
    return login_token, None
