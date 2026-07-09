from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from vrstudy.paths import app_data_dir, restrict_private_dir, restrict_private_file

from .security import hash_password, verify_password


USER_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
DEFAULT_USERS = ("zzoiraek", "bingary", "yangssu90")


@dataclass(frozen=True)
class WebUser:
    username: str
    password_hash: str
    role: str = "user"
    remember_token_hash: str = ""


def web_data_dir() -> Path:
    path = app_data_dir() / "web"
    path.mkdir(parents=True, exist_ok=True)
    restrict_private_dir(path)
    return path


def users_path() -> Path:
    return web_data_dir() / "users.json"


def user_data_dir(username: str) -> Path:
    if not USER_RE.fullmatch(username):
        raise ValueError("invalid username")
    path = app_data_dir() / "users" / username
    path.mkdir(parents=True, exist_ok=True)
    restrict_private_dir(path)
    return path


def user_db_path(username: str) -> Path:
    return user_data_dir(username) / "vrstudy.duckdb"


def session_secret_path() -> Path:
    return web_data_dir() / "session_secret.key"


def ensure_user_dirs() -> None:
    for username in DEFAULT_USERS:
        user_data_dir(username)


def load_users() -> dict[str, WebUser]:
    raw = _load_users_raw()
    users: dict[str, WebUser] = {}
    for item in raw.get("users", []):
        username = str(item.get("username", ""))
        password_hash = str(item.get("password_hash", ""))
        if USER_RE.fullmatch(username) and password_hash:
            users[username] = WebUser(
                username=username,
                password_hash=password_hash,
                role=str(item.get("role", "user")),
                remember_token_hash=str(item.get("remember_token_hash", "")),
            )
    return users


def _load_users_raw() -> dict[str, list[dict[str, object]]]:
    path = users_path()
    if not path.exists():
        return {"users": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = raw.get("users", [])
    if not isinstance(records, list):
        return {"users": []}
    sanitized: list[dict[str, object]] = []
    for item in records:
        if isinstance(item, dict):
            sanitized.append(dict(item))
    return {"users": sanitized}


def _save_users_raw(raw: dict[str, list[dict[str, object]]]) -> None:
    path = users_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    restrict_private_file(path)


def _find_user_record(
    raw: dict[str, list[dict[str, object]]], username: str
) -> dict[str, object] | None:
    if not USER_RE.fullmatch(username):
        return None
    for item in raw.get("users", []):
        item_username = str(item.get("username", ""))
        if item_username == username:
            return item
    return None


def authenticate(username: str, password: str) -> WebUser | None:
    users = load_users()
    user = users.get(username)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def change_password(username: str, current_password: str, new_password: str) -> bool:
    raw = _load_users_raw()
    record = _find_user_record(raw, username)
    if record is None:
        return False
    password_hash = str(record.get("password_hash", ""))
    if not verify_password(current_password, password_hash):
        return False
    record["password_hash"] = hash_password(new_password)
    record.pop("remember_token_hash", None)
    _save_users_raw(raw)
    return True


def _remember_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_remember_token(username: str) -> str | None:
    raw = _load_users_raw()
    record = _find_user_record(raw, username)
    if record is None:
        return None
    token = secrets.token_urlsafe(32)
    record["remember_token_hash"] = _remember_token_hash(token)
    _save_users_raw(raw)
    return f"{username}:{token}"


def authenticate_remember_token(cookie_value: str | None) -> WebUser | None:
    if not cookie_value or ":" not in cookie_value:
        return None
    username, token = cookie_value.split(":", 1)
    if not USER_RE.fullmatch(username) or not token:
        return None
    user = load_users().get(username)
    if user is None or not user.remember_token_hash:
        return None
    if not secrets.compare_digest(
        _remember_token_hash(token), user.remember_token_hash
    ):
        return None
    return user


def revoke_remember_token(username: str) -> None:
    raw = _load_users_raw()
    record = _find_user_record(raw, username)
    if record is None:
        return
    if "remember_token_hash" in record:
        record.pop("remember_token_hash", None)
        _save_users_raw(raw)
