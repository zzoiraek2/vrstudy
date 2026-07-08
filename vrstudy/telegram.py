from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import shutil
import ssl
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi

from .paths import app_data_dir, restrict_private_file, runtime_base_dir


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str = ""
    chat_id: str = ""
    auto_send_on_calculation: bool = True
    auto_send_vr_orders: bool = True
    auto_send_infinite_orders: bool = True
    send_order_table: bool = True
    order_row_limit: int = 10
    send_due: bool = True
    send_dashboard: bool = True
    send_vr_summary: bool = True
    send_infinite_summary: bool = True
    send_order_status: bool = True
    send_api_order_result: bool = True
    scheduled_send_enabled: bool = False
    scheduled_send_time: str = "08:30"
    scheduled_send_weekdays: list[int] = field(
        default_factory=lambda: [0, 1, 2, 3, 4]
    )
    scheduled_last_attempt_date: str = ""
    scheduled_last_run_at: str = ""
    scheduled_last_status: str = ""
    scheduled_last_message: str = ""
    include_paused: bool = False


def telegram_settings_path() -> Path:
    return app_data_dir() / "telegram_settings.json"


def fallback_telegram_settings_paths(path: Path) -> list[Path]:
    candidates = [
        runtime_base_dir().parent / "data" / path.name,
        runtime_base_dir() / "data" / path.name,
        Path.cwd() / "data" / path.name,
    ]
    seen: set[Path] = set()
    result: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved == path.resolve() or resolved in seen:
            continue
        seen.add(resolved)
        result.append(candidate)
    return result


def recover_telegram_settings_file(path: Path) -> Path | None:
    for candidate in fallback_telegram_settings_paths(path):
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if not (data.get("bot_token") or data.get("chat_id")):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, path)
        return candidate
    return None


def load_telegram_settings(path: Path | None = None) -> TelegramSettings:
    path = path or telegram_settings_path()
    if not path.exists():
        recover_telegram_settings_file(path)
    if not path.exists():
        return TelegramSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return TelegramSettings()
    allowed = set(TelegramSettings.__dataclass_fields__)
    return TelegramSettings(**{key: value for key, value in data.items() if key in allowed})


def backup_telegram_settings(path: Path) -> None:
    if not path.exists():
        return
    backup_path = path.with_name(
        f"{path.stem}.bak-{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix}"
    )
    try:
        shutil.copy2(path, backup_path)
    except Exception:
        pass


def save_telegram_settings(
    settings: TelegramSettings, path: Path | None = None
) -> Path:
    path = path or telegram_settings_path()
    existing = load_telegram_settings(path)
    if not settings.bot_token.strip() and existing.bot_token.strip():
        settings = TelegramSettings(**{**asdict(settings), "bot_token": existing.bot_token})
    if not settings.chat_id.strip() and existing.chat_id.strip():
        settings = TelegramSettings(**{**asdict(settings), "chat_id": existing.chat_id})
    backup_telegram_settings(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    restrict_private_file(path)
    return path


def send_telegram_message(settings: TelegramSettings, text: str) -> dict:
    token = settings.bot_token.strip()
    chat_id = settings.chat_id.strip()
    if not token:
        raise ValueError("Telegram Bot Token is empty.")
    if not chat_id:
        raise ValueError("Telegram Chat ID is empty.")
    payload = urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        method="POST",
    )
    context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(request, timeout=15, context=context) as response:
        body = response.read().decode("utf-8")
    result = json.loads(body)
    if not result.get("ok"):
        description = result.get("description") or "Telegram API error"
        raise RuntimeError(str(description))
    return result
