from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Any


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000
SESSION_TTL_SECONDS = 60 * 60 * 12


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        PASSWORD_ITERATIONS,
    )
    return "$".join(
        [
            PASSWORD_ALGORITHM,
            str(PASSWORD_ITERATIONS),
            salt,
            _b64_encode(digest),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(_b64_encode(digest), expected)


def ensure_session_secret(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip().encode("utf-8")


def sign_session(secret: bytes, username: str) -> str:
    payload: dict[str, Any] = {
        "sub": username,
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(12),
    }
    body = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64_encode(signature)}"


def verify_session(secret: bytes, token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    body, signature = token.split(".", 1)
    expected = _b64_encode(
        hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64_decode(body).decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    username = payload.get("sub")
    return username if isinstance(username, str) else None

