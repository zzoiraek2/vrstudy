from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from .paths import app_data_dir


PROFILE_KINDS = ("vr", "infinite")


@dataclass(frozen=True)
class KiwoomCredentials:
    investment_type: str = "실전투자"
    account_number: str = ""
    app_key: str = ""
    app_secret: str = ""
    expires_at: str = ""
    memo: str = ""


def kiwoom_credentials_path() -> Path:
    return app_data_dir() / "secrets" / "kiwoom_api_credentials.json"


def load_kiwoom_credentials_store(path: Path | None = None) -> dict:
    path = path or kiwoom_credentials_path()
    if not path.exists():
        return {kind: {} for kind in PROFILE_KINDS}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Kiwoom credentials file is not valid JSON: {path}") from exc
    return {
        kind: dict(data.get(kind) or {})
        for kind in PROFILE_KINDS
    }


def save_kiwoom_credentials_store(data: dict, path: Path | None = None) -> Path:
    path = path or kiwoom_credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = {kind: dict(data.get(kind) or {}) for kind in PROFILE_KINDS}
    path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_kiwoom_credentials(
    profile_kind: str, profile_name: str, path: Path | None = None
) -> KiwoomCredentials:
    store = load_kiwoom_credentials_store(path)
    raw = dict(store.get(profile_kind, {}).get(profile_name) or {})
    allowed = set(KiwoomCredentials.__dataclass_fields__)
    return KiwoomCredentials(**{key: value for key, value in raw.items() if key in allowed})


def save_kiwoom_credentials(
    profile_kind: str,
    profile_name: str,
    credentials: KiwoomCredentials,
    path: Path | None = None,
) -> Path:
    if profile_kind not in PROFILE_KINDS:
        raise ValueError(f"Unknown Kiwoom profile kind: {profile_kind}")
    store = load_kiwoom_credentials_store(path)
    store.setdefault(profile_kind, {})[profile_name] = asdict(credentials)
    return save_kiwoom_credentials_store(store, path)


def rename_kiwoom_credentials(
    profile_kind: str, old_name: str, new_name: str, path: Path | None = None
) -> Path | None:
    store = load_kiwoom_credentials_store(path)
    profiles = store.setdefault(profile_kind, {})
    if old_name not in profiles:
        return None
    profiles[new_name] = profiles.pop(old_name)
    return save_kiwoom_credentials_store(store, path)


def delete_kiwoom_credentials(
    profile_kind: str, profile_name: str, path: Path | None = None
) -> Path | None:
    store = load_kiwoom_credentials_store(path)
    profiles = store.setdefault(profile_kind, {})
    if profile_name not in profiles:
        return None
    profiles.pop(profile_name, None)
    return save_kiwoom_credentials_store(store, path)
