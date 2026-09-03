# -*- coding: utf8 -*-
"""单文件配置存储：用户主目录下的 .auto-pacer.json

  - 保存走"临时文件 + os.replace"原子替换
  - 临时文件写入后尽力收紧权限为 0600
  - 跨进程写入用 .lock 尽力互斥；拿不到锁也照常执行（双方令牌都有效时 last-write-wins）

字段一览（令牌与配置同级平铺）：
  user / pwd                        —— Zepp Life 登录账号与密码
  min_step / max_step               —— 步数随机范围；字段缺失时 main.py 用默认 18000 ~ 25000
  access_token / login_token / app_token / user_id /
  login_token_time / app_token_time —— 登录令牌缓存（约 30 天自动续期）
  device_id / bound_device_id       —— 客户端标识 / 绑定设备 ID
"""

import json
import os
from pathlib import Path

CONFIG_FILE = "~/.auto-pacer.json"  # 固定位置：用户主目录（Windows 即 %USERPROFILE%）

DEFAULT_MIN_STEP = 18000
DEFAULT_MAX_STEP = 25000


def config_path() -> Path:
    return Path(os.path.expanduser(CONFIG_FILE))


def load_config() -> dict:
    """读取配置；文件不存在返回 {}，损坏则先备份为 .corrupt 再返回 {}"""
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        backup = Path(str(path) + ".corrupt")
        try:
            path.replace(backup)
            print(f"配置文件无法解析，已备份到 {backup}，将重新生成")
        except OSError:
            print(f"配置文件无法解析，且备份失败：{path}")
        return {}


def _try_lock(path: Path):
    """跨进程写锁（尽力而为）：成功返回 fd（保存后关闭即释放），失败返回 None。

    同一时刻两个进程都在刷新令牌时，未拿到锁的一方照常执行，
    后写覆盖先写（双方令牌都有效，last-write-wins 可接受）。
    """
    try:
        fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return None
    try:
        if os.name == "nt":
            import msvcrt
            # msvcrt.locking 要求文件至少 1 字节，先补一个 NUL
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def save_config(cfg: dict) -> None:
    """原子保存：写 .tmp → 收紧权限 → 加锁 → os.replace 换入"""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(tmp, 0o600)  # 尽力收紧权限，Windows 无意义则忽略
        except OSError:
            pass
        lock_fd = _try_lock(path)
        try:
            os.replace(tmp, path)
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
