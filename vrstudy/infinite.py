from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from datetime import date, timedelta
import json
from math import ceil, floor
from pathlib import Path

import duckdb

from .db import next_id
from .paths import app_data_dir
from .storage import find_close_price


DEFAULT_SETTING_NAME = "default"
INFINITE_SYMBOLS = ("TQQQ", "SOXL")


@dataclass(frozen=True)
class InfiniteSetting:
    name: str = DEFAULT_SETTING_NAME
    profile_no: int = 0
    account_number: str = ""
    symbol: str = "TQQQ"
    start_date: date = date(2026, 5, 27)
    initial_principal: float = 150000.0
    initial_cumulative_amount: float = 0.0
    initial_cumulative_qty: int = 0
    target_rate: float = 0.10
    split_count: int = 40
    fee_rate: float = 0.00044
    mode: str = "기본"
    calculation_paused: bool = False


def default_infinite_profiles_dir() -> Path:
    return app_data_dir() / "profiles" / "infinite"


def ensure_infinite_profile_storage(
    con: duckdb.DuckDBPyConnection, profiles_dir: str | Path | None = None
) -> None:
    directory = _infinite_profiles_dir(profiles_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _export_db_infinite_profiles_to_json(con, directory)
    if not _infinite_profile_path(directory, DEFAULT_SETTING_NAME).exists():
        _write_infinite_setting_json(InfiniteSetting(), directory)
    _ensure_infinite_profile_numbers_json(directory)
    _sync_infinite_json_profiles_to_db(con, directory)


def load_infinite_setting(
    con: duckdb.DuckDBPyConnection, name: str = DEFAULT_SETTING_NAME
) -> InfiniteSetting:
    ensure_infinite_profile_storage(con)
    directory = default_infinite_profiles_dir()
    path = _infinite_profile_path(directory, name)
    if not path.exists():
        setting = InfiniteSetting(name=name)
        save_infinite_setting(con, setting)
        return setting
    setting = _read_infinite_setting_json(path)
    _save_infinite_setting_to_db(con, setting)
    return setting


def ensure_infinite_profile(
    con: duckdb.DuckDBPyConnection, name: str = DEFAULT_SETTING_NAME
) -> InfiniteSetting:
    return load_infinite_setting(con, name)


def list_infinite_profile_names(con: duckdb.DuckDBPyConnection) -> list[str]:
    ensure_infinite_profile_storage(con)
    return [setting.name for setting in _list_infinite_settings_json()]


def create_infinite_profile(
    con: duckdb.DuckDBPyConnection, name: str
) -> InfiniteSetting:
    if not name.strip():
        raise ValueError("Profile name cannot be empty")
    ensure_infinite_profile_storage(con)
    if _infinite_profile_path(default_infinite_profiles_dir(), name.strip()).exists():
        raise ValueError(f"Profile already exists: {name}")
    setting = InfiniteSetting(name=name.strip(), profile_no=next_infinite_profile_no(con))
    save_infinite_setting(con, setting)
    return setting


def save_infinite_setting(con: duckdb.DuckDBPyConnection, setting: InfiniteSetting) -> None:
    ensure_infinite_profile_storage(con)
    profile_no = normalize_infinite_profile_no(con, setting)
    setting = replace(setting, profile_no=profile_no, symbol=setting.symbol.upper())
    _validate_infinite_setting(setting)
    _write_infinite_setting_json(setting, default_infinite_profiles_dir())
    _save_infinite_setting_to_db(con, setting)


def _save_infinite_setting_to_db(
    con: duckdb.DuckDBPyConnection, setting: InfiniteSetting
) -> None:
    profile_no = normalize_infinite_profile_no(con, setting)
    if setting.split_count <= 0:
        raise ValueError("분할 수는 1 이상이어야 합니다.")
    if setting.initial_principal <= 0:
        raise ValueError("기준원금은 0보다 커야 합니다.")
    if setting.initial_cumulative_qty < 0:
        raise ValueError("초기 누적개수는 0 이상이어야 합니다.")
    if setting.target_rate <= 0:
        raise ValueError("수익기준율은 0보다 커야 합니다.")
    if setting.fee_rate < 0:
        raise ValueError("수수료는 0 이상이어야 합니다.")

    existing = con.execute(
        "SELECT id FROM infinite_settings WHERE name = ?", [setting.name]
    ).fetchone()
    if existing:
        con.execute(
            """
            UPDATE infinite_settings
            SET profile_no = ?,
                account_number = ?,
                symbol = ?,
                start_date = ?,
                initial_principal = ?,
                initial_cumulative_amount = ?,
                initial_cumulative_qty = ?,
                target_rate = ?,
                split_count = ?,
                fee_rate = ?,
                mode = ?,
                calculation_paused = ?,
                updated_at = current_timestamp
            WHERE name = ?
            """,
            [
                profile_no,
                setting.account_number,
                setting.symbol.upper(),
                setting.start_date,
                setting.initial_principal,
                setting.initial_cumulative_amount,
                setting.initial_cumulative_qty,
                setting.target_rate,
                setting.split_count,
                setting.fee_rate,
                setting.mode,
                setting.calculation_paused,
                setting.name,
            ],
        )
    else:
        con.execute(
            """
            INSERT INTO infinite_settings (
                id, name, profile_no, account_number, symbol, start_date, initial_principal,
                initial_cumulative_amount, initial_cumulative_qty,
                target_rate, split_count, fee_rate, mode, calculation_paused,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
            """,
            [
                next_id(con, "infinite_settings"),
                setting.name,
                profile_no,
                setting.account_number,
                setting.symbol.upper(),
                setting.start_date,
                setting.initial_principal,
                setting.initial_cumulative_amount,
                setting.initial_cumulative_qty,
                setting.target_rate,
                setting.split_count,
                setting.fee_rate,
                setting.mode,
                setting.calculation_paused,
            ],
        )
    commit_if_possible(con)


def normalize_infinite_profile_no(
    con: duckdb.DuckDBPyConnection, setting: InfiniteSetting
) -> int:
    if setting.name == DEFAULT_SETTING_NAME:
        return 0
    if setting.profile_no > 0:
        return setting.profile_no
    return next_infinite_profile_no(con)


def next_infinite_profile_no(con: duckdb.DuckDBPyConnection) -> int:
    used = {
        setting.profile_no
        for setting in _list_infinite_settings_json()
        if setting.name != DEFAULT_SETTING_NAME and setting.profile_no > 0
    }
    value = 1
    while value in used:
        value += 1
    return value


def ensure_infinite_profile_numbers(con: duckdb.DuckDBPyConnection) -> None:
    ensure_infinite_profile_storage(con)


def _validate_infinite_setting(setting: InfiniteSetting) -> None:
    if setting.symbol.upper() not in INFINITE_SYMBOLS:
        raise ValueError("무한매수법 종목은 TQQQ 또는 SOXL만 선택할 수 있습니다.")
    if setting.split_count <= 0:
        raise ValueError("분할 수는 1 이상이어야 합니다.")
    if setting.initial_principal <= 0:
        raise ValueError("기준원금은 0보다 커야 합니다.")
    if setting.initial_cumulative_qty < 0:
        raise ValueError("초기 누적개수는 0 이상이어야 합니다.")
    if setting.target_rate <= 0:
        raise ValueError("수익기준율은 0보다 커야 합니다.")
    if setting.fee_rate < 0:
        raise ValueError("수수료는 0 이상이어야 합니다.")


def _ensure_infinite_profile_numbers_json(directory: Path) -> None:
    settings = sorted(
        [_read_infinite_setting_json(path) for path in directory.glob("*.json")],
        key=lambda item: (item.profile_no, item.name),
    )
    used: set[int] = set()
    for setting in settings:
        if setting.name == DEFAULT_SETTING_NAME:
            updated = setting if setting.profile_no == 0 else replace(setting, profile_no=0)
        elif setting.profile_no > 0 and setting.profile_no not in used:
            updated = setting
        else:
            number = 1
            while number in used:
                number += 1
            updated = replace(setting, profile_no=number)
        if updated.profile_no > 0:
            used.add(updated.profile_no)
        if updated != setting:
            _write_infinite_setting_json(updated, directory)


def _list_infinite_settings_json(
    profiles_dir: str | Path | None = None,
) -> list[InfiniteSetting]:
    directory = _infinite_profiles_dir(profiles_dir)
    if not directory.exists():
        return []
    settings = [_read_infinite_setting_json(path) for path in directory.glob("*.json")]
    return sorted(settings, key=lambda item: (item.profile_no, item.name))


def _export_db_infinite_profiles_to_json(
    con: duckdb.DuckDBPyConnection, directory: Path
) -> None:
    try:
        cursor = con.execute(
            """
            SELECT name, profile_no, account_number, symbol, start_date, initial_principal,
                   initial_cumulative_amount, initial_cumulative_qty, target_rate,
                   split_count, fee_rate, mode, calculation_paused
            FROM infinite_settings
            ORDER BY profile_no, name
            """
        )
    except Exception:
        return
    for row in cursor.fetchall():
        setting = _row_to_infinite_setting(row)
        path = _infinite_profile_path(directory, setting.name)
        if not path.exists():
            _write_infinite_setting_json(setting, directory)


def _sync_infinite_json_profiles_to_db(
    con: duckdb.DuckDBPyConnection, directory: Path
) -> None:
    json_names = []
    for setting in _list_infinite_settings_json(directory):
        _save_infinite_setting_to_db(con, setting)
        json_names.append(setting.name)
    if json_names:
        placeholders = ",".join("?" for _ in json_names)
        con.execute(
            f"DELETE FROM infinite_settings WHERE name NOT IN ({placeholders})",
            json_names,
        )
        commit_if_possible(con)


def _row_to_infinite_setting(row: tuple) -> InfiniteSetting:
    return InfiniteSetting(
        name=str(row[0]),
        profile_no=int(row[1] or 0),
        account_number=str(row[2] or ""),
        symbol=str(row[3] or "TQQQ"),
        start_date=row[4],
        initial_principal=float(row[5]),
        initial_cumulative_amount=float(row[6] or 0),
        initial_cumulative_qty=int(row[7] or 0),
        target_rate=float(row[8]),
        split_count=int(row[9]),
        fee_rate=float(row[10]),
        mode=str(row[11]),
        calculation_paused=bool(row[12]),
    )


def _read_infinite_setting_json(path: Path) -> InfiniteSetting:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("name", path.stem)
    data.setdefault("profile_no", 0)
    data.setdefault("account_number", "")
    data.setdefault("symbol", "TQQQ")
    data.setdefault("start_date", "2026-05-27")
    data.setdefault("initial_principal", 150000.0)
    data.setdefault("initial_cumulative_amount", 0.0)
    data.setdefault("initial_cumulative_qty", 0)
    data.setdefault("target_rate", 0.10)
    data.setdefault("split_count", 40)
    data.setdefault("fee_rate", 0.00044)
    data.setdefault("mode", InfiniteSetting().mode)
    data.setdefault("calculation_paused", False)
    if isinstance(data["start_date"], str):
        data["start_date"] = date.fromisoformat(data["start_date"])
    allowed = {field.name for field in fields(InfiniteSetting)}
    return InfiniteSetting(**{key: value for key, value in data.items() if key in allowed})


def _write_infinite_setting_json(
    setting: InfiniteSetting, profiles_dir: str | Path | None = None
) -> None:
    directory = _infinite_profiles_dir(profiles_dir)
    directory.mkdir(parents=True, exist_ok=True)
    data = asdict(setting)
    data["start_date"] = setting.start_date.isoformat()
    _infinite_profile_path(directory, setting.name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _delete_infinite_setting_json(
    name: str, profiles_dir: str | Path | None = None
) -> None:
    path = _infinite_profile_path(_infinite_profiles_dir(profiles_dir), name)
    if path.exists():
        path.unlink()


def _infinite_profiles_dir(profiles_dir: str | Path | None = None) -> Path:
    return Path(profiles_dir) if profiles_dir is not None else default_infinite_profiles_dir()


def _infinite_profile_path(directory: Path, name: str) -> Path:
    return directory / f"{_safe_filename(name)}.json"


def _safe_filename(name: str) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if char in invalid else char for char in name).strip()
    cleaned = cleaned.strip(". ")
    if not cleaned:
        raise ValueError("Profile name cannot be empty")
    return cleaned


def save_infinite_execution(
    con: duckdb.DuckDBPyConnection,
    setting: InfiniteSetting,
    trade_date: date,
    avg_price: float,
    buy_qty: int,
    sell_qty: int,
    cash_flow_amount: float = 0.0,
) -> None:
    if trade_date < setting.start_date:
        raise ValueError("입력일은 시작일 이후여야 합니다.")
    if trade_date >= date.today():
        raise ValueError("무한매수법 체결 입력은 어제 날짜까지만 저장할 수 있습니다.")
    if avg_price <= 0:
        raise ValueError("평단가는 0보다 커야 합니다.")
    if buy_qty < 0 or sell_qty < 0:
        raise ValueError("매수개수와 매도개수는 0 이상이어야 합니다.")
    trade_qty = int(buy_qty) - int(sell_qty)
    withdrawal_amount = -float(cash_flow_amount or 0.0)
    con.execute(
        """
        INSERT INTO infinite_rows (
            id, setting_name, trade_date, weekday, close_price, avg_price, trade_qty,
            buy_qty, sell_qty,
            cumulative_qty, t_value, star_price, return_rate, fee, stop_loss,
            trade_amount, cumulative_amount, withdrawal_amount, cash_flow_amount
        )
        VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 0, 0, NULL, 0, 0, 0, 0, 0, ?, ?)
        ON CONFLICT(setting_name, trade_date) DO UPDATE SET
            avg_price = excluded.avg_price,
            trade_qty = excluded.trade_qty,
            buy_qty = excluded.buy_qty,
            sell_qty = excluded.sell_qty,
            withdrawal_amount = excluded.withdrawal_amount,
            cash_flow_amount = excluded.cash_flow_amount
        """,
        [
            next_id(con, "infinite_rows"),
            setting.name,
            trade_date,
            weekday_name(trade_date),
            avg_price,
            trade_qty,
            buy_qty,
            sell_qty,
            withdrawal_amount,
            cash_flow_amount,
        ],
    )
    commit_if_possible(con)


def generate_infinite_rows(
    con: duckdb.DuckDBPyConnection,
    setting: InfiniteSetting,
    through: date | None = None,
) -> None:
    through = through or date.today()
    if through < setting.start_date:
        through = setting.start_date

    existing_inputs = {
        row[0]: (row[1], row[2], row[3], row[4])
        for row in con.execute(
            """
            SELECT trade_date, avg_price, buy_qty, sell_qty, cash_flow_amount
            FROM infinite_rows
            WHERE setting_name = ?
              AND (
                  avg_price IS NOT NULL
                  OR coalesce(buy_qty, 0) <> 0
                  OR coalesce(sell_qty, 0) <> 0
                  OR coalesce(cash_flow_amount, 0) <> 0
              )
            """,
            [setting.name],
        ).fetchall()
    }

    con.execute("DELETE FROM infinite_rows WHERE setting_name = ?", [setting.name])

    previous_avg: float | None = None
    cumulative_qty = int(setting.initial_cumulative_qty or 0)
    cumulative_amount = float(setting.initial_cumulative_amount or 0.0)
    cumulative_net_profit = 0.0
    cumulative_principal_effect = 0.0
    cumulative_cash_flow = 0.0
    day = setting.start_date
    while day <= through:
        avg_price, buy_qty, sell_qty, cash_flow_amount = existing_inputs.get(
            day, (None, 0, 0, 0.0)
        )
        buy_qty = int(buy_qty or 0)
        sell_qty = int(sell_qty or 0)
        cash_flow_amount = float(cash_flow_amount or 0.0)
        trade_qty = buy_qty - sell_qty
        withdrawal_amount = -cash_flow_amount
        close_price = close_on_or_before(con, setting.symbol, day)

        if day in existing_inputs:
            cumulative_qty += trade_qty
        trade_amount = trade_cash(close_price, previous_avg, avg_price, buy_qty, sell_qty)
        if cumulative_qty == 0 and day in existing_inputs and trade_qty != 0:
            cumulative_amount = 0.0
        elif avg_price is not None and cumulative_qty > 0:
            cumulative_amount = round(float(avg_price) * cumulative_qty, 2)
        else:
            cumulative_amount = round(cumulative_amount + trade_amount, 2)

        basis_avg = avg_price if avg_price is not None else previous_avg
        return_rate = round_up((close_price or 0) / basis_avg - 1, 4) if basis_avg else 0.0
        fee = trade_fee(close_price, previous_avg, avg_price, buy_qty, sell_qty, setting.fee_rate)
        stop_loss = 0.0
        if sell_qty > 0 and close_price is not None and previous_avg is not None:
            stop_loss = round((close_price - floor(previous_avg)) * sell_qty, 2)
        cumulative_net_profit += stop_loss - fee
        cumulative_principal_effect += principal_profit_effect(stop_loss, fee)
        principal_before_withdrawal = principal_amount(
            setting, cumulative_principal_effect, cumulative_cash_flow
        )
        principal_after_withdrawal = max(
            0.0,
            round(principal_before_withdrawal + cash_flow_amount, 2),
        )
        cumulative_cash_flow += cash_flow_amount
        per_buy = per_buy_amount_from_principal(setting, principal_after_withdrawal)
        if cumulative_qty == 0:
            t_value = 0.0
        else:
            t_value = roundup(cumulative_amount / per_buy, 1) if per_buy else 0.0
        star_price = calc_star_price(basis_avg, t_value, setting)

        con.execute(
            """
            INSERT INTO infinite_rows (
                id, setting_name, trade_date, weekday, close_price, avg_price, trade_qty,
                buy_qty, sell_qty,
                cumulative_qty, t_value, star_price, return_rate, fee, stop_loss,
                trade_amount, cumulative_amount, principal_before_withdrawal,
                withdrawal_amount, cash_flow_amount, principal_after_withdrawal, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
            """,
            [
                next_id(con, "infinite_rows"),
                setting.name,
                day,
                weekday_name(day),
                close_price,
                avg_price,
                trade_qty,
                buy_qty,
                sell_qty,
                cumulative_qty,
                t_value,
                star_price,
                return_rate,
                fee,
                stop_loss,
                trade_amount,
                cumulative_amount,
                principal_before_withdrawal,
                withdrawal_amount,
                cash_flow_amount,
                principal_after_withdrawal,
            ],
        )
        if avg_price is not None:
            previous_avg = float(avg_price)
        day += timedelta(days=1)
    commit_if_possible(con)


def commit_if_possible(con: duckdb.DuckDBPyConnection) -> None:
    try:
        con.commit()
    except Exception:
        pass


def rename_infinite_profile_records(
    con: duckdb.DuckDBPyConnection, old_name: str, new_name: str
) -> None:
    ensure_infinite_profile_storage(con)
    directory = default_infinite_profiles_dir()
    old_path = _infinite_profile_path(directory, old_name)
    new_path = _infinite_profile_path(directory, new_name)
    if new_path.exists():
        raise ValueError(f"Profile already exists: {new_name}")
    if old_path.exists():
        setting = replace(_read_infinite_setting_json(old_path), name=new_name)
        old_path.unlink()
        _write_infinite_setting_json(setting, directory)
    con.execute(
        "UPDATE infinite_settings SET name = ? WHERE name = ?",
        [new_name, old_name],
    )
    con.execute(
        "UPDATE infinite_rows SET setting_name = ? WHERE setting_name = ?",
        [new_name, old_name],
    )
    commit_if_possible(con)


def delete_infinite_profile_records(
    con: duckdb.DuckDBPyConnection, profile_name: str
) -> None:
    _delete_infinite_setting_json(profile_name)
    con.execute("DELETE FROM infinite_rows WHERE setting_name = ?", [profile_name])
    con.execute("DELETE FROM infinite_settings WHERE name = ?", [profile_name])
    commit_if_possible(con)


def infinite_rows(con: duckdb.DuckDBPyConnection, setting_name: str) -> list[dict]:
    cursor = con.execute(
        """
        SELECT *
        FROM infinite_rows
        WHERE setting_name = ?
        ORDER BY trade_date
        """,
        [setting_name],
    )
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def latest_input_date(con: duckdb.DuckDBPyConnection, setting_name: str) -> date | None:
    row = con.execute(
        """
        SELECT max(trade_date)
        FROM infinite_rows
        WHERE setting_name = ? AND avg_price IS NOT NULL AND trade_qty IS NOT NULL
        """,
        [setting_name],
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def order_basis_row(
    con: duckdb.DuckDBPyConnection, setting: InfiniteSetting
) -> dict | None:
    basis_date = latest_input_date(con, setting.name)
    if basis_date is None:
        basis_date = setting.start_date
    else:
        basis_date = min(basis_date + timedelta(days=1), date.today())
    if basis_date < setting.start_date:
        basis_date = setting.start_date
    cursor = con.execute(
        """
        SELECT *
        FROM infinite_rows
        WHERE setting_name = ? AND trade_date = ?
        """,
        [setting.name, basis_date],
    )
    row = cursor.fetchone()
    if row is None:
        generate_infinite_rows(con, setting, basis_date)
        cursor = con.execute(
            "SELECT * FROM infinite_rows WHERE setting_name = ? AND trade_date = ?",
            [setting.name, basis_date],
        )
        row = cursor.fetchone()
    if row is None:
        return None
    columns = [item[0] for item in cursor.description]
    return dict(zip(columns, row))


def required_execution_date(today: date | None = None) -> date:
    return (today or date.today()) - timedelta(days=1)


def execution_ready_for_order(
    con: duckdb.DuckDBPyConnection, setting: InfiniteSetting, today: date | None = None
) -> tuple[bool, date | None]:
    required_day = required_execution_date(today)
    if required_day < setting.start_date:
        return True, None
    row = con.execute(
        """
        SELECT avg_price
        FROM infinite_rows
        WHERE setting_name = ? AND trade_date = ?
        """,
        [setting.name, required_day],
    ).fetchone()
    return bool(row and row[0] is not None), required_day


def infinite_order_plan(
    con: duckdb.DuckDBPyConnection, setting: InfiniteSetting
) -> dict[str, object]:
    row = order_basis_row(con, setting)
    if row is None:
        return {"title": "", "per_buy_amount": per_buy_amount(setting, con), "buy": [], "sell": []}

    ready, required_day = execution_ready_for_order(con, setting)
    if not ready:
        return {
            "title": f"\uc8fc\ubb38\ubd88\uac00: {required_day} \uc804\uc77c \ud3c9\ub2e8 \ubbf8\uc785\ub825",
            "per_buy_amount": per_buy_amount_from_principal(
                setting, row.get("principal_after_withdrawal")
            ),
            "buy": [],
            "sell": [],
        }

    previous = previous_row_with_avg(con, setting.name, row["trade_date"])
    avg_price = float(previous["avg_price"]) if previous and previous["avg_price"] else None
    close_price = float(row["close_price"] or 0)
    basis_price = avg_price or close_price
    if basis_price <= 0:
        return {"title": "", "per_buy_amount": per_buy_amount(setting, con), "buy": [], "sell": []}

    t_value = float(row["t_value"])
    split_count = setting.split_count
    per_buy = per_buy_amount_from_principal(setting, row.get("principal_after_withdrawal"))
    qty = int(row["cumulative_qty"])
    star_price = calc_star_price(basis_price, t_value, setting) or basis_price
    target_price = round(basis_price * (1 + setting.target_rate), 2)

    buy: list[dict] = []
    sell: list[dict] = []
    title = order_phase_title(t_value, split_count)
    if t_value == 0:
        buy = buy_orders("\ub9e4\uc218", star_price, per_buy, first_multiplier=1.0, levels=11)
    elif 0 < t_value < split_count / 2:
        buy = front_half_buy_orders(star_price, basis_price, per_buy)
    elif split_count / 2 <= t_value <= split_count - 1:
        buy = buy_orders(
            "\ub9e4\uc218", round(star_price - 0.01, 2), per_buy, first_multiplier=1.0, levels=9
        )

    if qty > 0 and 0 < t_value <= split_count - 1:
        loc_qty = max(1, floor(qty / 4))
        sell.append(order("\ub9e4\ub3c4", "LOC", star_price, loc_qty))
        sell.append(order("\ub9e4\ub3c4", "\uc9c0\uc815\uac00", target_price, max(0, qty - loc_qty)))
    elif qty > 0 and split_count - 1 < t_value <= split_count:
        moc_qty = max(1, floor(qty / 4))
        sell.append(order("\ub9e4\ub3c4", "MOC", None, moc_qty))
        sell.append(order("\ub9e4\ub3c4", "\uc9c0\uc815\uac00", target_price, max(0, qty - moc_qty)))

    return {
        "title": title,
        "per_buy_amount": per_buy,
        "buy": [item for item in buy if item["quantity"] > 0],
        "sell": [item for item in sell if item["quantity"] > 0],
    }


def order_phase_title(t_value: float, split_count: int) -> str:
    if t_value == 0:
        return "\uc0c8\uc0ac\uc774\ud074"
    if 0 < t_value < split_count / 2:
        return "\uc804\ubc18\uc804"
    if split_count / 2 <= t_value <= split_count - 1:
        return "\ud6c4\ubc18\uc804"
    if split_count - 1 < t_value <= split_count:
        return "MOC\ub9e4\ub3c4"
    return ""


def infinite_status_view(
    con: duckdb.DuckDBPyConnection, setting: InfiniteSetting, today: date | None = None
) -> dict:
    today = today or date.today()
    rows = infinite_rows(con, setting.name)
    latest = rows[-1] if rows else None
    latest_avg = latest_row_with_avg(con, setting.name)
    current_close, previous_close = latest_two_closes(con, setting.symbol, today)
    t_value = float(latest["t_value"]) if latest else 0.0
    per_buy = per_buy_amount_from_principal(
        setting, latest.get("principal_after_withdrawal") if latest else None
    )
    cumulative_profit = realized_profit(con, setting.name)
    cumulative_cash_flow = cash_flow_sum(con, setting.name)
    repeat_principal = adjusted_principal(setting, con)
    phase = phase_name(t_value, setting.split_count)
    avg_price = float(latest_avg["avg_price"]) if latest_avg and latest_avg["avg_price"] else None
    cumulative_qty = int(latest["cumulative_qty"]) if latest else 0
    fx_rate = latest_fx_rate(con, today)
    cumulative_value = cumulative_qty * fx_rate * (avg_price or 0.0)
    day_change = None
    if current_close is not None and previous_close is not None and previous_close:
        day_change = round_up(current_close / previous_close - 1, 4)
    return {
        "today": today,
        "phase": phase,
        "progress": t_value / setting.split_count if setting.split_count else 0.0,
        "cumulative_qty": cumulative_qty,
        "cumulative_value": cumulative_value,
        "avg_price": avg_price,
        "current_price": current_close,
        "return_rate": latest["return_rate"] if latest else None,
        "day_change": day_change,
        "t_value": t_value,
        "fx_rate": fx_rate,
        "per_buy_amount": per_buy,
        "cumulative_profit": cumulative_profit,
        "cumulative_withdrawal": cumulative_cash_flow,
        "repeat_principal": repeat_principal,
    }


def phase_name(t_value: float, split_count: int) -> str:
    if t_value == 0:
        return "\uc2dc\uc791"
    if 0 < t_value < split_count / 2:
        return "\uc804\ubc18\uc804"
    if split_count / 2 <= t_value <= split_count - 1:
        return "\ud6c4\ubc18\uc804"
    if split_count - 1 < t_value <= split_count:
        return "\uc190\uc808\uad6c\uac04"
    return ""


def latest_row_with_avg(
    con: duckdb.DuckDBPyConnection, setting_name: str
) -> dict | None:
    cursor = con.execute(
        """
        SELECT *
        FROM infinite_rows
        WHERE setting_name = ? AND avg_price IS NOT NULL
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        [setting_name],
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [item[0] for item in cursor.description]
    return dict(zip(columns, row))


def latest_two_closes(
    con: duckdb.DuckDBPyConnection, symbol: str, today: date
) -> tuple[float | None, float | None]:
    rows = con.execute(
        """
        SELECT close
        FROM prices
        WHERE symbol = ? AND price_date <= ?
        ORDER BY price_date DESC
        LIMIT 2
        """,
        [symbol.upper(), today],
    ).fetchall()
    current = float(rows[0][0]) if rows else None
    previous = float(rows[1][0]) if len(rows) > 1 else None
    return current, previous


def latest_fx_rate(con: duckdb.DuckDBPyConnection, today: date) -> float:
    try:
        return find_close_price(con, "KRW=X", today)
    except Exception:
        return 1.0


def previous_row_with_avg(
    con: duckdb.DuckDBPyConnection, setting_name: str, before_day: date
) -> dict | None:
    cursor = con.execute(
        """
        SELECT *
        FROM infinite_rows
        WHERE setting_name = ? AND trade_date < ? AND avg_price IS NOT NULL
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        [setting_name, before_day],
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [item[0] for item in cursor.description]
    return dict(zip(columns, row))


def buy_orders(
    side: str, first_price: float, budget: float, *, first_multiplier: float, levels: int
) -> list[dict]:
    rows: list[dict] = []
    first_budget = budget * first_multiplier
    first_qty = max(1, floor(first_budget / first_price))
    rows.append(order(side, "LOC", round(first_price, 2), first_qty))
    total_qty = first_qty
    for _ in range(levels - 1):
        price = round_down(budget / max(1, total_qty + 1), 2)
        rows.append(order(side, "LOC", price, 1))
        total_qty += 1
    return rows


def front_half_buy_orders(star_price: float, avg_price: float, budget: float) -> list[dict]:
    rows: list[dict] = []
    first_price = round(float(star_price) - 0.01, 2)
    first_qty = max(1, floor(budget / 2 / first_price))
    rows.append(order("\ub9e4\uc218", "LOC", first_price, first_qty))

    second_price = round(float(avg_price), 2)
    second_qty = max(0, floor(budget / second_price) - first_qty)
    if second_qty > 0:
        rows.append(order("\ub9e4\uc218", "LOC", second_price, second_qty))

    total_qty = first_qty + second_qty
    for _ in range(8):
        total_qty += 1
        price = round_down(budget / total_qty, 2)
        rows.append(order("\ub9e4\uc218", "LOC", price, 1))
    return rows


def order(side: str, order_type: str, price: float | None, quantity: int) -> dict:
    return {
        "side": side,
        "order_type": order_type,
        "price": None if price is None else round(float(price), 2),
        "quantity": int(quantity),
    }


def close_on_or_before(
    con: duckdb.DuckDBPyConnection, symbol: str, trade_date: date
) -> float | None:
    try:
        return find_close_price(con, symbol, trade_date)
    except Exception:
        return None


def per_buy_amount(setting: InfiniteSetting, con: duckdb.DuckDBPyConnection) -> float:
    return per_buy_amount_from_principal(setting, adjusted_principal(setting, con))


def adjusted_principal(setting: InfiniteSetting, con: duckdb.DuckDBPyConnection) -> float:
    latest = latest_principal_row(con, setting.name)
    if latest and latest.get("principal_after_withdrawal") is not None:
        return max(0.0, float(latest["principal_after_withdrawal"]))

    profit = principal_profit_effect_sum(con, setting.name)
    cash_flow = cash_flow_sum(con, setting.name)
    return principal_amount(setting, profit, cash_flow)


def per_buy_amount_from_principal(
    setting: InfiniteSetting, principal: float | None
) -> float:
    if setting.split_count <= 0:
        return 0.0
    basis = setting.initial_principal if principal is None else max(0.0, float(principal))
    return basis / setting.split_count


def principal_amount(
    setting: InfiniteSetting, cumulative_principal_effect: float, cumulative_cash_flow: float
) -> float:
    profit_part = 0.0
    if setting.mode != "기본":
        profit_part = round(float(cumulative_principal_effect or 0.0), 2)
    return max(0.0, round(setting.initial_principal + profit_part + cumulative_cash_flow, 2))


def principal_profit_effect(stop_loss: float, fee: float) -> float:
    realized = float(stop_loss or 0.0)
    fee_amount = abs(float(fee or 0.0))
    if realized > 0:
        return round(realized / 2 - fee_amount, 2)
    return round(realized - fee_amount, 2)


def principal_profit_effect_sum(
    con: duckdb.DuckDBPyConnection, setting_name: str
) -> float:
    rows = con.execute(
        """
        SELECT stop_loss, fee
        FROM infinite_rows
        WHERE setting_name = ?
        ORDER BY trade_date
        """,
        [setting_name],
    ).fetchall()
    return round(sum(principal_profit_effect(row[0], row[1]) for row in rows), 2)


def latest_principal_row(
    con: duckdb.DuckDBPyConnection, setting_name: str
) -> dict | None:
    cursor = con.execute(
        """
        SELECT principal_after_withdrawal
        FROM infinite_rows
        WHERE setting_name = ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        [setting_name],
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [item[0] for item in cursor.description]
    return dict(zip(columns, row))


def realized_profit(con: duckdb.DuckDBPyConnection, setting_name: str) -> float:
    row = con.execute(
        """
        SELECT coalesce(sum(stop_loss), 0) - coalesce(sum(fee), 0)
        FROM infinite_rows
        WHERE setting_name = ?
        """,
        [setting_name],
    ).fetchone()
    return round(float(row[0] or 0), 2)


def cash_flow_sum(con: duckdb.DuckDBPyConnection, setting_name: str) -> float:
    row = con.execute(
        """
        SELECT coalesce(sum(cash_flow_amount), 0)
        FROM infinite_rows
        WHERE setting_name = ?
        """,
        [setting_name],
    ).fetchone()
    return float(row[0] or 0)


def trade_cash(
    close_price: float | None,
    previous_avg: float | None,
    avg_price: float | None,
    buy_qty: int,
    sell_qty: int,
) -> float:
    buy_qty = int(buy_qty or 0)
    sell_qty = int(sell_qty or 0)
    if buy_qty == 0 and sell_qty == 0:
        return 0.0
    buy_amount = (close_price or avg_price or previous_avg or 0) * buy_qty
    sell_basis = (previous_avg or avg_price or close_price or 0) * sell_qty
    return round(buy_amount - sell_basis, 2)


def trade_fee(
    close_price: float | None,
    previous_avg: float | None,
    avg_price: float | None,
    buy_qty: int,
    sell_qty: int,
    fee_rate: float,
) -> float:
    price = close_price or avg_price or previous_avg or 0
    gross_amount = abs(price * int(buy_qty or 0)) + abs(price * int(sell_qty or 0))
    return abs(round_down(gross_amount * fee_rate, 2))


def calc_star_price(
    basis_avg: float | None, t_value: float, setting: InfiniteSetting
) -> float | None:
    if basis_avg is None:
        return None
    factor = (
        setting.target_rate * 100
        - (t_value * setting.target_rate * 5) * (40 / setting.split_count)
        + 100
    ) / 100
    return round(float(basis_avg) * factor, 2)


def round_down(value: float, digits: int = 0) -> float:
    factor = 10**digits
    return floor(value * factor) / factor


def round_up(value: float, digits: int = 0) -> float:
    factor = 10**digits
    return ceil(value * factor) / factor


def roundup(value: float, digits: int = 0) -> float:
    return round_up(value, digits)


def weekday_name(day: date) -> str:
    return ("월", "화", "수", "목", "금", "토", "일")[day.weekday()]
