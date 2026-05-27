#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成Webhook签名的辅助脚本

用法:
    python3 generate_sign.py {timestamp=default(int(time.time() * 1000))}
    
示例:
    python3 generate_sign.py 1648291200000
"""

import time
import hmac
import hashlib
import os
import sys


SIGN_SECRET_KEY = os.getenv("SIGN_SECRET_KEY", "123abc")

# 签名有效期（毫秒），默认 30 分钟
SIGN_EXPIRE_MS = 30 * 60 * 1000


def generate_sign(timestamp: int | None = None) -> tuple[int, str]:
    """
    生成 HMAC-SHA256 签名

    Args:
        timestamp: 毫秒级时间戳，默认取当前时间

    Returns:
        tuple[int, str]: (timestamp_ms, sign_hex)
    """
    if timestamp is None:
        timestamp = int(time.time() * 1000)

    sign = hmac.new(
        SIGN_SECRET_KEY.encode("utf-8"),
        str(timestamp).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return timestamp, sign


def verify_sign(timestamp: int | str, sign: str, expire_ms: int = SIGN_EXPIRE_MS) -> bool:
    """
    验证签名是否合法（含时效性校验）

    Args:
        timestamp:  毫秒级时间戳（int 或数字字符串）
        sign:       待验证的签名字符串（十六进制）
        expire_ms:  允许的最大时间偏差（毫秒），默认 30 分钟

    Returns:
        bool: True 表示签名合法且未过期，False 反之
    """
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False

    # 时效性校验：拒绝过期或未来时间戳
    now_ms = int(time.time() * 1000)
    if abs(now_ms - ts) > expire_ms:
        return False

    # 签名正确性校验（使用 compare_digest 防止时序攻击）
    expected = hmac.new(
        SIGN_SECRET_KEY.encode("utf-8"),
        str(ts).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(sign, expected)


def generate_sign_main():
    args = sys.argv[1:]

    if args and args[0].isdigit():
        timestamp = int(args[0])
    else:
        timestamp = None

    ts, sign = generate_sign(timestamp)

    print(f"timestamp : {ts}")
    print(f"sign      : {sign}")

if __name__ == "__main__":
    generate_sign_main()
