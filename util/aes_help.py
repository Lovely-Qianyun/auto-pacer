# -*- coding: utf8 -*-
"""AES-128-CBC 工具：平台登录请求体加密（协议必需）

账号密码登录时，请求体须按官方 App 同款算法加密后才被服务器接受；
HM_AES_KEY/HM_AES_IV 是客户端内置固定值，人人相同（见 util/account_api.py），
它保证协议合规而非保密——传输保密靠 HTTPS。

令牌与账号密码同文件明文落盘（~/.auto-pacer.json），本地文件即信任边界，
故不再提供任何"本地加密"选项。
"""

from Crypto.Cipher import AES

# 平台登录传输加密使用的固定密钥和IV
HM_AES_KEY = b'xeNtBVqzDc6tuNTh'  # 16 bytes
HM_AES_IV = b'MAAAYAAAAAAAAABg'  # 16 bytes

AES_BLOCK_SIZE = AES.block_size  # 16


def _pkcs7_pad(data: bytes) -> bytes:
    pad_len = AES_BLOCK_SIZE - (len(data) % AES_BLOCK_SIZE)
    return data + bytes([pad_len]) * pad_len


def _validate_key(key: bytes):
    if not isinstance(key, (bytes, bytearray)):
        raise TypeError("key must be bytes")
    if len(key) != 16:
        raise ValueError("key must be 16 bytes for AES-128")


def encrypt_data(plain: bytes, key: bytes, iv: bytes) -> bytes:
    """使用固定 IV 进行 AES-128-CBC 加密（PKCS7 填充）"""
    _validate_key(key)
    if not isinstance(plain, (bytes, bytearray)):
        raise TypeError("plain must be bytes")
    if len(iv) != AES_BLOCK_SIZE:
        raise ValueError(f"iv must be {AES_BLOCK_SIZE} bytes")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = _pkcs7_pad(plain)
    return cipher.encrypt(padded)
