# app/security/job_tokens.py
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


class TokenError(Exception):
    pass


class TokenExpired(TokenError):
    pass


class TokenInvalid(TokenError):
    pass


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("utf-8")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("utf-8"))


@dataclass(frozen=True)
class JobTokenConfig:
    secret: str
    ttl_seconds: int = 7 * 24 * 3600  # 7 days


def mint_job_token(cfg: JobTokenConfig, *, job_id: str, now: Optional[int] = None) -> str:
    """
    Token format: base64url(payload).base64url(sig)
    payload: {"v":1,"job":"KR-XXXXXX","iat":<unix>,"exp":<unix>}
    sig: HMAC-SHA256(secret, payload_bytes)
    """
    if not cfg.secret or len(cfg.secret) < 16:
        raise RuntimeError("JOB_TOKEN_SECRET is missing or too short (use 32+ chars).")

    ts = int(now or time.time())
    payload = {
        "v": 1,
        "job": job_id,
        "iat": ts,
        "exp": ts + int(cfg.ttl_seconds),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(cfg.secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()

    return f"{_b64url_encode(payload_bytes)}.{_b64url_encode(sig)}"


def verify_job_token(cfg: JobTokenConfig, *, token: str, job_id: str, now: Optional[int] = None) -> Dict[str, Any]:
    """
    Returns decoded payload if valid; raises TokenExpired/TokenInvalid otherwise.
    """
    if not token or "." not in token:
        raise TokenInvalid("Missing or malformed token.")

    try:
        p_b64, s_b64 = token.split(".", 1)
        payload_bytes = _b64url_decode(p_b64)
        sig = _b64url_decode(s_b64)
    except Exception as e:
        raise TokenInvalid("Malformed token encoding.") from e

    expected = hmac.new(cfg.secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise TokenInvalid("Invalid signature.")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        raise TokenInvalid("Invalid payload JSON.") from e

    if payload.get("v") != 1:
        raise TokenInvalid("Unsupported token version.")

    if payload.get("job") != job_id:
        raise TokenInvalid("Token job mismatch.")

    ts = int(now or time.time())
    exp = int(payload.get("exp") or 0)
    if exp <= ts:
        raise TokenExpired("Token expired.")

    return payload