from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from vrstudy.paths import app_data_dir, restrict_private_dir

from .security import verify_password


USER_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
DEFAULT_USERS = ("zzoiraek", "bingary", "yangssu90")


@dataclass(frozen=True)
class WebUser:
    username: str
    password_hash: str
    role: str = "user"


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
    path = users_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    users: dict[str, WebUser] = {}
    for item in raw.get("users", []):
        username = str(item.get("username", ""))
        password_hash = str(item.get("password_hash", ""))
        if USER_RE.fullmatch(username) and password_hash:
            users[username] = WebUser(
                username=username,
                password_hash=password_hash,
                role=str(item.get("role", "user")),
            )
    return users


def authenticate(username: str, password: str) -> WebUser | None:
    users = load_users()
    user = users.get(username)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
