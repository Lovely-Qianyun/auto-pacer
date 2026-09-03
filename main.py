# -*- coding: utf8 -*-
"""Zepp Life (原小米运动) 一键刷步数

在 [MIN_STEP, MAX_STEP] 范围内随机生成一个步数，提交到 Zepp Life 云端，
已关联的微信运动/支付宝运动会随之同步。成功/失败仅在命令行提示，不做任何消息推送。

配置：唯一来源是用户主目录下的 .auto-pacer.json（Windows 为 %USERPROFILE%
下同名文件，见 util/config_store.py），不读取任何环境变量；min_step/max_step
字段缺失时用默认 18000 ~ 25000。

登录采用"令牌梯子"逐级复用，避免每次运行都用账号密码登录：
    1. 本地 app_token 在信任窗口内（25 天）→ 直接复用，免网络校验
       （超窗口或时间戳缺失 → 调 getUserInfo 校验一次）
    2. app_token 失效 → 用 login_token 续期 app_token
    3. login_token 失效 → 用 access_token 换新的 login_token + app_token
    4. 全部失效 → 才用账号密码全量登录
login_token 距上次获取/续期超过 20 天时自动提前续期（令牌约 30 天过期）。
若提交失败且本次用的是"免校验信任"的令牌，会作废时间戳、重走一次令牌
阶梯（网络校验）后重试一次提交。

命令：python main.py [--dry-run]
  --dry-run   只加载/校验配置并打印计划，不发起任何网络请求（排障用）
"""

import random
import sys
import time
import uuid

import util.account_api as account_api
import util.data_api as data_api
from util.config_store import DEFAULT_MAX_STEP, DEFAULT_MIN_STEP, config_path, load_config, save_config
from util.timeutil import format_now

# login_token 距上次获取/续期超过该天数时提前续期（令牌约 30 天过期）
TOKEN_RENEW_DAYS = 20
# app_token 本地信任窗口：期内免网络校验；超期/无时间戳则走 getUserInfo 校验
APP_TOKEN_TRUST_DAYS = 25
MS_PER_DAY = 24 * 60 * 60 * 1000
# 步数硬上限：防误填/防平台风控（向导层还应在写入前与用户确认更大值）
STEP_LIMIT_MAX = 90000


# 账号脱敏，避免日志泄露完整账号
def desensitize(user):
    if len(user) <= 8:
        ln = max(len(user) // 3, 1)
        return f'{user[:ln]}***{user[-ln:]}'
    return f'{user[:3]}****{user[-4:]}'


# 手机号统一加 +86 前缀（邮箱保持不变）
def normalize_user(user):
    user = str(user).strip()
    if not user.startswith("+86") and "@" not in user:
        user = "+86" + user
    return user


def _as_int(value):
    """严格整数转换：拒绝浮点(1.5)、布尔、非数字串，避免被 int() 静默截断"""
    if isinstance(value, bool):
        raise ValueError("步数必须是整数")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        return int(value)
    raise ValueError("步数必须是整数")


def validate_step_range(lo, hi):
    """校验并返回排序后的 (最小, 最大) 元组；非法/越界抛 ValueError"""
    lo, hi = _as_int(lo), _as_int(hi)
    if lo < 1 or hi < 1:
        raise ValueError("步数必须 >= 1")
    if max(lo, hi) > STEP_LIMIT_MAX:
        raise ValueError(f"步数不能超过 {STEP_LIMIT_MAX}")
    lo, hi = sorted([lo, hi])
    return lo, hi


def app_token_can_be_trusted_locally(cfg) -> bool:
    """app_token 是否在信任窗口内：有 token、有时间戳且未超过 25 天"""
    if not (cfg.get("app_token") and cfg.get("user_id")):
        return False
    try:
        issued_ms = float(cfg.get("app_token_time"))
    except (TypeError, ValueError):
        return False  # 无时间戳（旧缓存等）→ 不信任，走一次网络校验
    return (time.time() * 1000 - issued_ms) <= APP_TOKEN_TRUST_DAYS * MS_PER_DAY


def now_ms():
    return "%.0f" % (time.time() * 1000)


def get_app_token(user, password, is_phone, cfg):
    """令牌梯子：逐级尝试复用/续期，最后才回退到账号密码登录。

    返回 (app_token, user_id, 说明, trusted)。
    trusted=True 表示本次令牌未经网络校验（信任窗口内直接复用）——
    调用方在提交失败时应重走一次完整校验流程。
    """
    # 1. 本地保存的 app_token 有效则直接复用
    app_token = cfg.get("app_token")
    user_id = cfg.get("user_id")
    if app_token and user_id:
        if app_token_can_be_trusted_locally(cfg):
            return app_token, user_id, "复用本地 app_token（信任窗口内，免校验）", True
        ok, _ = account_api.check_app_token(app_token)
        if ok:
            return app_token, user_id, "复用本地 app_token（网络校验通过）", False

    # 快到期的 login_token 提前续期（滑动有效期）
    login_token = cfg.get("login_token")
    login_time = cfg.get("login_token_time")
    stale = True
    try:
        stale = (time.time() * 1000 - float(login_time)
                 ) > TOKEN_RENEW_DAYS * MS_PER_DAY
    except (TypeError, ValueError):
        pass  # 无/坏时间戳一律视为需要续期
    if login_token and stale:
        new_login_token, msg = account_api.renew_login_token(login_token)
        if new_login_token:
            cfg["login_token"] = new_login_token
            cfg["login_token_time"] = now_ms()
            login_token = new_login_token
            print("login_token 即将过期，已提前续期")

    # 2. 用 login_token 续期 app_token
    if login_token:
        new_app_token, msg = account_api.grant_app_token(login_token)
        if new_app_token:
            cfg["app_token"] = new_app_token
            cfg["app_token_time"] = now_ms()
            return new_app_token, cfg.get("user_id"), "app_token 已过期，用 login_token 续期", False

    # 3. 用 access_token 换新的 login_token + app_token
    device_id = cfg.get("device_id") or str(uuid.uuid4())
    cfg["device_id"] = device_id
    access_token = cfg.get("access_token")
    if access_token:
        new_login_token, new_app_token, new_user_id, msg = account_api.grant_login_tokens(
            access_token, device_id, is_phone)
        if new_login_token and new_app_token and new_user_id:
            cfg.update({
                "login_token": new_login_token,
                "app_token": new_app_token,
                "user_id": new_user_id,
                "login_token_time": now_ms(),
                "app_token_time": now_ms(),
            })
            return new_app_token, new_user_id, "login_token 已过期，用 access_token 换新", False

    # 4. 全部失效，账号密码全量登录
    new_access_token, msg = account_api.login_access_token(user, password)
    if new_access_token is None:
        return None, None, f"账号密码登录失败: {msg}", False
    new_login_token, new_app_token, new_user_id, msg = account_api.grant_login_tokens(
        new_access_token, device_id, is_phone)
    if new_login_token is None or new_app_token is None or new_user_id is None:
        return None, None, f"登录换取令牌失败: {msg}", False
    cfg.update({
        "access_token": new_access_token,
        "login_token": new_login_token,
        "app_token": new_app_token,
        "user_id": new_user_id,
        "login_token_time": now_ms(),
        "app_token_time": now_ms(),
    })
    return new_app_token, new_user_id, "本地令牌全部失效，账号密码重新登录", False


def main():
    dry_run = "--dry-run" in sys.argv
    path = config_path()
    cfg = load_config()

    user = cfg.get("user", "")
    password = cfg.get("pwd", "")
    if not user or not password:
        print(f"未配置账号：请编辑 {path}（字段 user/pwd，密码不回显）后重试")
        sys.exit(1)

    user = normalize_user(user)
    is_phone = user.startswith("+86")
    print(f"[{format_now()}] 账号: {desensitize(user)}")

    min_raw = cfg.get("min_step", DEFAULT_MIN_STEP)
    max_raw = cfg.get("max_step", DEFAULT_MAX_STEP)
    try:
        lo, hi = validate_step_range(min_raw, max_raw)
    except ValueError as e:
        print(f"步数范围无效: {e}")
        sys.exit(1)

    if dry_run:
        has_tokens = bool(cfg.get("app_token") or cfg.get("login_token"))
        print(f"[dry-run] 配置文件: {path}")
        print(
            f"[dry-run] 账号范围校验通过，步数范围: {lo} ~ {hi}，本地令牌缓存: {'有' if has_tokens else '无'}")
        print("[dry-run] 仅校验配置，未发起任何登录/提交请求。执行完成: 成功")
        sys.exit(0)

    # 在完整范围内直接随机，不随时间缩放
    step = random.randint(lo, hi)
    print(f"随机步数: {step}")

    bound_device_id = cfg.get("bound_device_id")
    ok, last_msg, trusted = False, "", False
    for attempt in (1, 2):
        app_token, token_user_id, msg, trusted = get_app_token(
            user, password, is_phone, cfg)
        if app_token is None or token_user_id is None:
            print(msg)
            sys.exit(1)
        print(msg)

        # 查询已绑定设备并缓存（存在时按真实设备提交，保证能同步到微信/支付宝）
        if not bound_device_id:
            bound_device_id = data_api.get_user_device_id(
                app_token, token_user_id)
            if bound_device_id:
                cfg["bound_device_id"] = bound_device_id
                print(f"查找到已绑定设备: {bound_device_id}")
            else:
                print("未查到绑定设备，回退到内置虚拟设备提交（首次成功后平台会自动登记该虚拟设备）")

        ok, last_msg = data_api.post_fake_brand_data(str(step), app_token, token_user_id,
                                                     device_id=bound_device_id)
        print(f"提交结果: {last_msg}")
        if ok or not trusted or attempt == 2:
            break
        # 免校验信任的令牌提交失败 → 疑似令牌已失效：作废时间戳后重走令牌阶梯（网络校验）
        cfg.pop("app_token_time", None)
        print("提交失败且令牌未经网络校验，将重走令牌阶梯校验后重试一次")

    # 配置/令牌有更新则写回本地，供下次复用
    save_config(cfg)
    print("执行完成: " + ("成功" if ok else "失败"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
