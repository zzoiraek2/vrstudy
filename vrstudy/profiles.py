from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
import json
from pathlib import Path

from .paths import app_data_dir


DEFAULT_PROFILE_NAME = "default"


@dataclass(frozen=True)
class Profile:
    name: str
    profile_no: int = 0
    start_date: str = "2026-06-08"
    start_week_no: int = 2
    symbol: str = "TQQQ"
    account_number: str = ""
    calculation_paused: bool = False
    g_initial: float = 15.0
    g_base_week: int = 0
    g_step_weeks: int = 26
    g_step_value: float = 1.0
    min_ratio: float = 0.85
    max_ratio: float = 1.15
    buy_limit_ratio: float = 0.25
    buy_limit_config: str = ""
    buy_limit_start_week_no: int = 2
    investment_type: str = "lump_sum"
    contribution_amount: float = 0.0
    initial_v: float = 0.0
    initial_pool: float = 0.0
    initial_principal: float = 0.0
    initial_shares: int = 0
    quantity_step: int = 4


def default_profiles_dir() -> Path:
    return app_data_dir() / "profiles" / "vr"


def ensure_default_profile(profiles_dir: str | Path | None = None) -> Profile:
    directory = _profiles_dir(profiles_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = _profile_path(directory, DEFAULT_PROFILE_NAME)
    if not path.exists():
        profile = Profile(name=DEFAULT_PROFILE_NAME)
        save_profile(profile, directory)
        return profile
    return load_profile(DEFAULT_PROFILE_NAME, directory)


def create_profile(name: str, profiles_dir: str | Path | None = None) -> Profile:
    directory = _profiles_dir(profiles_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = _profile_path(directory, name)
    if path.exists():
        raise ValueError(f"Profile already exists: {name}")
    profile = Profile(name=name, profile_no=next_profile_no(directory))
    save_profile(profile, directory)
    return profile


def load_profile(name: str, profiles_dir: str | Path | None = None) -> Profile:
    directory = _profiles_dir(profiles_dir)
    path = _profile_path(directory, name)
    if not path.exists():
        raise ValueError(f"Profile not found: {name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("profile_no", 0)
    data.setdefault("start_date", "2026-06-08")
    data.setdefault("start_week_no", 2)
    data.setdefault("account_number", "")
    data.setdefault("calculation_paused", False)
    data.setdefault("g_base_week", 0)
    data.setdefault("investment_type", "lump_sum")
    data.setdefault("contribution_amount", 0.0)
    data.setdefault("initial_v", 0.0)
    data.setdefault("initial_pool", 0.0)
    data.setdefault("initial_principal", 0.0)
    data.setdefault("initial_shares", 0)
    data.setdefault("buy_limit_config", "")
    data.setdefault("buy_limit_start_week_no", 2)
    allowed = {field.name for field in fields(Profile)}
    return Profile(**{key: value for key, value in data.items() if key in allowed})


def save_profile(profile: Profile, profiles_dir: str | Path | None = None) -> None:
    directory = _profiles_dir(profiles_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = _profile_path(directory, profile.name)
    path.write_text(
        json.dumps(asdict(profile), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def list_profiles(profiles_dir: str | Path | None = None) -> list[Profile]:
    directory = _profiles_dir(profiles_dir)
    if not directory.exists():
        return []

    profiles: list[Profile] = []
    for path in sorted(directory.glob("*.json")):
        profiles.append(load_profile(path.stem, directory))
    return ensure_profile_numbers(profiles, directory)


def rename_profile(
    old_name: str, new_name: str, profiles_dir: str | Path | None = None
) -> Profile:
    directory = _profiles_dir(profiles_dir)
    old_path = _profile_path(directory, old_name)
    new_path = _profile_path(directory, new_name)
    if not old_path.exists():
        raise ValueError(f"Profile not found: {old_name}")
    if new_path.exists():
        raise ValueError(f"Profile already exists: {new_name}")

    profile = replace(load_profile(old_name, directory), name=new_name)
    old_path.unlink()
    save_profile(profile, directory)
    return profile


def delete_profile(name: str, profiles_dir: str | Path | None = None) -> None:
    directory = _profiles_dir(profiles_dir)
    path = _profile_path(directory, name)
    if not path.exists():
        raise ValueError(f"Profile not found: {name}")
    path.unlink()


def update_profile(
    profile: Profile,
    *,
    symbol: str | None = None,
    start_date: str | None = None,
    start_week_no: int | None = None,
    account_number: str | None = None,
    calculation_paused: bool | None = None,
    g_initial: float | None = None,
    g_base_week: int | None = None,
    g_step_weeks: int | None = None,
    g_step_value: float | None = None,
    min_ratio: float | None = None,
    max_ratio: float | None = None,
    buy_limit_ratio: float | None = None,
    buy_limit_config: str | None = None,
    buy_limit_start_week_no: int | None = None,
    investment_type: str | None = None,
    contribution_amount: float | None = None,
    initial_v: float | None = None,
    initial_pool: float | None = None,
    initial_principal: float | None = None,
    initial_shares: int | None = None,
    quantity_step: int | None = None,
) -> Profile:
    return replace(
        profile,
        start_date=start_date or profile.start_date,
        start_week_no=profile.start_week_no if start_week_no is None else start_week_no,
        symbol=(symbol or profile.symbol).upper(),
        account_number=profile.account_number if account_number is None else account_number,
        calculation_paused=profile.calculation_paused
        if calculation_paused is None
        else calculation_paused,
        g_initial=profile.g_initial if g_initial is None else g_initial,
        g_base_week=profile.g_base_week if g_base_week is None else g_base_week,
        g_step_weeks=profile.g_step_weeks if g_step_weeks is None else g_step_weeks,
        g_step_value=profile.g_step_value if g_step_value is None else g_step_value,
        min_ratio=profile.min_ratio if min_ratio is None else min_ratio,
        max_ratio=profile.max_ratio if max_ratio is None else max_ratio,
        buy_limit_ratio=profile.buy_limit_ratio
        if buy_limit_ratio is None
        else buy_limit_ratio,
        buy_limit_config=profile.buy_limit_config
        if buy_limit_config is None
        else buy_limit_config,
        buy_limit_start_week_no=profile.buy_limit_start_week_no
        if buy_limit_start_week_no is None
        else buy_limit_start_week_no,
        investment_type=investment_type or profile.investment_type,
        contribution_amount=profile.contribution_amount
        if contribution_amount is None
        else contribution_amount,
        initial_v=profile.initial_v if initial_v is None else initial_v,
        initial_pool=profile.initial_pool if initial_pool is None else initial_pool,
        initial_principal=profile.initial_principal
        if initial_principal is None
        else initial_principal,
        initial_shares=profile.initial_shares if initial_shares is None else initial_shares,
        quantity_step=profile.quantity_step if quantity_step is None else quantity_step,
    )


def next_profile_no(profiles_dir: str | Path | None = None) -> int:
    used = {
        profile.profile_no
        for profile in list_profiles(profiles_dir)
        if profile.name != DEFAULT_PROFILE_NAME and profile.profile_no > 0
    }
    value = 1
    while value in used:
        value += 1
    return value


def ensure_profile_numbers(
    profiles: list[Profile], profiles_dir: str | Path | None = None
) -> list[Profile]:
    directory = _profiles_dir(profiles_dir)
    used: set[int] = set()
    changed = False
    result: list[Profile] = []

    for profile in profiles:
        if profile.name == DEFAULT_PROFILE_NAME:
            updated = profile if profile.profile_no == 0 else replace(profile, profile_no=0)
        elif profile.profile_no > 0 and profile.profile_no not in used:
            updated = profile
        else:
            updated = replace(profile, profile_no=_smallest_available_no(used))

        used.add(updated.profile_no) if updated.profile_no > 0 else None
        if updated != profile:
            save_profile(updated, directory)
            changed = True
        result.append(updated)

    return list_profiles(directory) if changed else result


def _smallest_available_no(used: set[int]) -> int:
    value = 1
    while value in used:
        value += 1
    return value


def _profiles_dir(profiles_dir: str | Path | None) -> Path:
    return Path(profiles_dir) if profiles_dir is not None else default_profiles_dir()


def _profile_path(directory: Path, name: str) -> Path:
    return directory / f"{_safe_filename(name)}.json"


def _safe_filename(name: str) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if char in invalid else char for char in name).strip()
    cleaned = cleaned.strip(". ")
    if not cleaned:
        raise ValueError("Profile name cannot be empty")
    return cleaned
