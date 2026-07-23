"""认证原语：密码哈希（stdlib pbkdf2）+ JWT（手写 HS256，零外部依赖）。

刻意不引入 PyJWT/passlib：避免离线环境装包失败（与 bm25_local 同类决策）。
HS256 仅 ~30 行即可正确签发/校验；签名比较用 hmac.compare_digest 防时序攻击。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Mapping

from app.core.config import settings

_PBKDF2_ITER = 200_000


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


# ===== 密码哈希 =====
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITER)
    return f"pbkdf2_sha256${_PBKDF2_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iter_s, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iter_s))
    return hmac.compare_digest(dk, expected)


# ===== JWT (HS256) =====
def create_access_token(
    claims: Mapping[str, Any], *, expires_minutes: int | None = None
) -> str:
    if settings.jwt_algorithm != "HS256":
        raise ValueError(f"unsupported jwt_algorithm: {settings.jwt_algorithm}")
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    exp_minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    payload = dict(claims)
    payload["iat"] = now
    payload["exp"] = now + exp_minutes * 60
    seg_header = _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    seg_payload = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{seg_header}.{seg_payload}".encode("ascii")
    sig = hmac.new(settings.jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{seg_header}.{seg_payload}.{_b64url_encode(sig)}"


class TokenError(Exception):
    """JWT 解析/校验失败。"""


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        seg_header, seg_payload, seg_sig = token.split(".")
    except ValueError:
        raise TokenError("malformed token")
    signing_input = f"{seg_header}.{seg_payload}".encode("ascii")
    expected = hmac.new(settings.jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        got = _b64url_decode(seg_sig)
    except Exception as e:  # noqa: BLE001 — 畸形 base64 一律视为坏签名
        raise TokenError(f"bad signature encoding: {e}")
    if not hmac.compare_digest(expected, got):
        raise TokenError("bad signature")
    try:
        payload = json.loads(_b64url_decode(seg_payload))
    except Exception as e:  # noqa: BLE001
        raise TokenError(f"bad payload: {e}")
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and exp < time.time():
        raise TokenError("expired")
    return payload
