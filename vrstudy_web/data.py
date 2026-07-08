from __future__ import annotations

import json
from dataclasses import asdict, fields, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

from .accounts import user_data_dir, user_db_path
from vrstudy.db import init_db, next_id
from vrstudy.core import CycleInput, cycle_dates, cycle_input_available_date, order_level_values
from vrstudy.infinite import (
    INFINITE_SYMBOLS,
    InfiniteSetting,
    generate_infinite_rows,
    infinite_rows,
    infinite_order_plan,
    infinite_status_view,
    latest_fx_rate,
    order_basis_row,
    next_us_trading_day,
    previous_us_trading_day,
    save_infinite_execution,
)
from vrstudy.kiwoom_api import (
    KiwoomApiError,
    default_us_stock_exchange_code,
    is_token_valid_for_credentials,
    issue_access_token,
    load_profile_token,
    delete_profile_token,
    rename_profile_token,
    request_us_buy_order,
    request_us_ledger_balance,
    request_us_period_order_history,
    request_us_sell_order,
    resolve_us_stock_exchange_code,
    save_profile_token,
)
from vrstudy.kiwoom_credentials import (
    KiwoomCredentials,
    delete_kiwoom_credentials,
    load_kiwoom_credentials,
    load_kiwoom_credentials_store,
    rename_kiwoom_credentials,
    save_kiwoom_credentials,
)
from vrstudy.profiles import (
    Profile,
    create_profile,
    delete_profile,
    rename_profile,
    save_profile,
    update_profile,
)
from vrstudy.storage import (
    find_close_price,
    latest_buy_limit_config,
    latest_buy_limit_start_week_no,
    latest_contribution_amount,
    latest_cycle_snapshot,
    latest_g_config,
    latest_g_start_cycle_no,
    next_input_cycle,
    order_basis_for_next_cycle,
    profile_cycle_status,
    recalculate_cycle_results_from,
    rename_profile_snapshots,
    save_cycle_result,
    snapshot_for_cycle,
)
from vrstudy.telegram import (
    TelegramSettings,
    load_telegram_settings,
    save_telegram_settings,
    send_telegram_message,
)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _json_value(str(key)): _json_value(item)
            for key, item in value.items()
        }
    return value


def _connect_readonly(db_path: Path) -> duckdb.DuckDBPyConnection | None:
    if not db_path.exists():
        return None
    try:
        return duckdb.connect(str(db_path), read_only=True)
    except duckdb.ConnectionException:
        return duckdb.connect(str(db_path))


def _connect_writable(db_path: Path) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    init_db(con, db_path=db_path, profiles_dir=db_path.parent / "profiles")
    return con


def _tables(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in con.execute("SHOW TABLES").fetchall()}


def _count(con: duckdb.DuckDBPyConnection, table: str, tables: set[str]) -> int:
    if table not in tables:
        return 0
    return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _infinite_profile_count(con: duckdb.DuckDBPyConnection, tables: set[str]) -> int:
    if "infinite_settings" not in tables:
        return 0
    return int(
        con.execute("SELECT COUNT(*) FROM infinite_settings WHERE name <> 'default'").fetchone()[0]
    )


def _vr_snapshot_count(con: duckdb.DuckDBPyConnection, tables: set[str]) -> int:
    if "rebalance_snapshots" not in tables:
        return 0
    return int(
        con.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT profile_name, cycle_no
                FROM rebalance_snapshots
                WHERE profile_name <> 'default' AND cycle_no IS NOT NULL
                GROUP BY profile_name, cycle_no
            )
            """
        ).fetchone()[0]
    )


def _query_dicts(
    con: duckdb.DuckDBPyConnection, query: str, params: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    rows = con.execute(query, params).fetchall()
    columns = [desc[0] for desc in con.description]
    return [
        {column: _json_value(value) for column, value in zip(columns, row)}
        for row in rows
    ]


def _ensure_order_execution_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS web_order_executions (
            id BIGINT PRIMARY KEY,
            created_at TIMESTAMP NOT NULL,
            strategy TEXT NOT NULL,
            profile_name TEXT NOT NULL,
            symbol TEXT,
            order_date DATE NOT NULL,
            order_key TEXT NOT NULL,
            side TEXT,
            side_label TEXT,
            order_type TEXT,
            price DOUBLE,
            quantity BIGINT,
            stex_tp TEXT,
            trde_tp TEXT,
            status TEXT NOT NULL,
            order_no TEXT,
            message TEXT,
            response_json TEXT
        )
        """
    )


def _order_execution_table_exists(con: duckdb.DuckDBPyConnection) -> bool:
    return "web_order_executions" in _tables(con)


def _order_execution_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _order_row_key(strategy: str, profile_name: str, order_date: date, row: dict[str, Any]) -> str:
    price = "" if row.get("price") is None else _clean_number_text(row.get("price"))
    return "|".join(
        [
            strategy,
            profile_name,
            order_date.isoformat(),
            str(row.get("symbol") or "").upper(),
            str(row.get("side") or ""),
            str(row.get("order_type") or ""),
            price,
            str(int(row.get("quantity") or 0)),
        ]
    )


def _successful_order_execution_count(
    con: duckdb.DuckDBPyConnection,
    strategy: str,
    profile_name: str,
    order_date: date | str,
) -> int:
    if not _order_execution_table_exists(con):
        return 0
    return int(
        con.execute(
            """
            SELECT COUNT(*)
            FROM web_order_executions
            WHERE strategy = ?
              AND profile_name = ?
              AND order_date = ?
              AND status = 'sent'
            """,
            (strategy, profile_name, _order_execution_date(order_date)),
        ).fetchone()[0]
    )


def _recent_order_execution_rows(
    con: duckdb.DuckDBPyConnection,
    strategy: str,
    profile_name: str,
    order_date: date | str,
) -> list[dict[str, Any]]:
    if not _order_execution_table_exists(con):
        return []
    return _query_dicts(
        con,
        """
        SELECT
            created_at,
            order_date,
            symbol,
            side_label,
            order_type,
            price,
            quantity,
            stex_tp,
            trde_tp,
            status,
            order_no,
            message
        FROM web_order_executions
        WHERE strategy = ?
          AND profile_name = ?
          AND order_date = ?
          AND status IN ('sent', 'failed')
        ORDER BY id DESC
        """,
        (strategy, profile_name, _order_execution_date(order_date)),
    )


def _record_order_execution(
    con: duckdb.DuckDBPyConnection,
    strategy: str,
    profile_name: str,
    order_date: date,
    row: dict[str, Any],
    status: str,
    result: dict[str, Any] | None = None,
    message: str = "",
) -> None:
    _ensure_order_execution_table(con)
    response_json = json.dumps(result or {}, ensure_ascii=False, default=str)
    order_no = ""
    if result:
        order_no = str(result.get("ord_no") or result.get("odno") or "")
    con.execute(
        """
        INSERT INTO web_order_executions (
            id,
            created_at,
            strategy,
            profile_name,
            symbol,
            order_date,
            order_key,
            side,
            side_label,
            order_type,
            price,
            quantity,
            stex_tp,
            trde_tp,
            status,
            order_no,
            message,
            response_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            next_id(con, "web_order_executions"),
            datetime.now(),
            strategy,
            profile_name,
            str(row.get("symbol") or "").upper(),
            order_date,
            _order_row_key(strategy, profile_name, order_date, row),
            row.get("side"),
            row.get("side_label"),
            row.get("order_type"),
            row.get("price"),
            int(row.get("quantity") or 0),
            row.get("stex_tp"),
            row.get("trde_tp"),
            status,
            order_no,
            message,
            response_json,
        ),
    )


def _kiwoom_error_hint(exc: KiwoomApiError) -> str:
    code = str(exc.return_code or "").strip()
    message = str(exc.return_msg or exc or "")
    if code == "505531" or "주간거래" in message:
        return "키움이 현재 시간대/주문유형을 지원하지 않아 거절했습니다. 정규장 주문 가능 시간에 다시 실행하거나 주문유형을 확인하세요."
    return ""


def _order_failure_message(exc: Exception) -> str:
    if isinstance(exc, KiwoomApiError):
        details = []
        if exc.return_code is not None:
            details.append(f"return_code {exc.return_code}")
        if exc.return_msg:
            details.append(exc.return_msg)
        hint = _kiwoom_error_hint(exc)
        if hint:
            details.append(hint)
        if details:
            return " / ".join(str(item) for item in details)
    return str(exc)


def _order_executions_for_response(
    username: str, strategy: str, profile_name: str, order_date: date | str
) -> list[dict[str, Any]]:
    con = _connect_readonly(user_db_path(username))
    if con is None:
        return []
    try:
        return _recent_order_execution_rows(con, strategy, profile_name, order_date)
    finally:
        con.close()


def _verify_order_execution_rows(
    execution_rows: list[dict[str, Any]],
    credentials: KiwoomCredentials,
    token: Any,
    *,
    order_date: date,
    stex_tp: str,
    symbol: str,
) -> list[dict[str, Any]]:
    if not execution_rows:
        return execution_rows
    history_rows = _order_history_rows_for_date(
        credentials,
        token,
        order_date=order_date,
        stex_tp=stex_tp,
        symbol=symbol,
    )
    return _apply_order_history_verification(execution_rows, history_rows)


def _read_profile_files(
    base_dir: Path, kind: str = "vr", include_default: bool = False
) -> list[dict[str, Any]]:
    profiles_dir = base_dir / "profiles" / kind
    if not profiles_dir.exists():
        return []
    profiles: list[dict[str, Any]] = []
    for path in sorted(profiles_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        profile_name = str(raw.get("name") or path.stem)
        if not include_default and profile_name == "default":
            continue
        item = dict(raw)
        item["name"] = profile_name
        item["symbol"] = str(raw.get("symbol") or raw.get("ticker") or "")
        item["account_number"] = str(raw.get("account_number") or "")
        item["profile_no"] = raw.get("profile_no")
        item["calculation_paused"] = bool(raw.get("calculation_paused", False))
        item["file"] = path.name
        profiles.append(_json_value(item))
    return profiles


def _read_profile_file(base_dir: Path, kind: str, profile_name: str) -> dict[str, Any]:
    profiles_dir = base_dir / "profiles" / kind
    if not profiles_dir.exists():
        return {}
    for path in profiles_dir.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(raw.get("name") or path.stem) == profile_name:
            raw["file"] = path.name
            return _json_value(raw)
    return {}


def _profile_from_data(data: dict[str, Any]) -> Profile:
    payload = dict(data)
    payload.setdefault("name", "")
    allowed = {field.name for field in fields(Profile)}
    return Profile(**{key: value for key, value in payload.items() if key in allowed})


def _infinite_setting_from_data(data: dict[str, Any]) -> InfiniteSetting:
    payload = dict(data)
    payload.setdefault("name", "")
    if isinstance(payload.get("start_date"), str) and payload["start_date"]:
        payload["start_date"] = date.fromisoformat(payload["start_date"])
    allowed = {field.name for field in fields(InfiniteSetting)}
    return InfiniteSetting(**{key: value for key, value in payload.items() if key in allowed})


def _payload_value(payload: dict[str, Any], key: str, default: Any) -> Any:
    value = payload.get(key, default)
    if value == "":
        return default
    return value


def kiwoom_credentials_path(username: str) -> Path:
    return user_data_dir(username) / "secrets" / "kiwoom_api_credentials.json"


def kiwoom_token_cache_path(username: str) -> Path:
    return user_data_dir(username) / "secrets" / "kiwoom_token_cache.json"


def telegram_settings_path(username: str) -> Path:
    return user_data_dir(username) / "telegram_settings.json"


DEFAULT_INFINITE_SCHEDULE = {
    "enabled": False,
    "time": "15:55",
    "weekdays": [0, 1, 2, 3, 4],
    "last_attempt_date": "",
    "last_run_at": "",
    "last_status": "",
    "last_message": "",
}


def _infinite_schedule_path(username: str, profile_name: str) -> Path:
    return (
        user_data_dir(username)
        / "schedules"
        / "infinite"
        / f"{_safe_profile_filename(profile_name)}.json"
    )


def _validate_schedule_time(value: Any) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%H:%M")
    except ValueError as exc:
        raise ValueError("스케줄 시간은 HH:MM 형식이어야 합니다.") from exc
    return parsed.strftime("%H:%M")


def _validate_schedule_weekdays(value: Any) -> list[int]:
    raw_days = value if isinstance(value, list) else []
    days = sorted({int(day) for day in raw_days if 0 <= int(day) <= 6})
    if not days:
        raise ValueError("스케줄 요일을 1개 이상 선택해야 합니다.")
    return days


def _read_infinite_schedule(username: str, profile_name: str) -> dict[str, Any]:
    path = _infinite_schedule_path(username, profile_name)
    data = dict(DEFAULT_INFINITE_SCHEDULE)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                data.update(raw)
        except json.JSONDecodeError:
            pass
    data["enabled"] = bool(data.get("enabled"))
    data["time"] = _validate_schedule_time(data.get("time") or DEFAULT_INFINITE_SCHEDULE["time"])
    data["weekdays"] = _validate_schedule_weekdays(data.get("weekdays") or DEFAULT_INFINITE_SCHEDULE["weekdays"])
    return data


def _write_infinite_schedule(username: str, profile_name: str, data: dict[str, Any]) -> dict[str, Any]:
    path = _infinite_schedule_path(username, profile_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def get_infinite_schedule(username: str, profile_name: str) -> dict[str, Any]:
    infinite_profile_detail(username, profile_name)
    return _read_infinite_schedule(username, profile_name)


def put_infinite_schedule(username: str, profile_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    infinite_profile_detail(username, profile_name)
    current = _read_infinite_schedule(username, profile_name)
    current.update(
        {
            "enabled": bool(payload.get("enabled", current["enabled"])),
            "time": _validate_schedule_time(payload.get("time", current["time"])),
            "weekdays": _validate_schedule_weekdays(payload.get("weekdays", current["weekdays"])),
        }
    )
    return _write_infinite_schedule(username, profile_name, current)


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def _result_rows(body: dict) -> list[dict]:
    rows = body.get("result_list") or body.get("result_lsit") or []
    return rows if isinstance(rows, list) else []


def _first_row_value(row: dict, *keys: str):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return ""


def _clean_int(value) -> int:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _clean_float(value) -> float:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _clean_number_text(value) -> str:
    number = _clean_float(value)
    if number == 0:
        return "0"
    text = f"{number:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _price_key(value) -> str:
    price = _clean_float(value)
    return f"{round(price, 2):.2f}" if price else ""


def _format_api_date(value: str) -> str:
    value = str(value or "").strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    return value


def _find_symbol_row(rows: list[dict], symbol: str) -> dict:
    symbol = symbol.upper()
    for row in rows:
        if str(row.get("stk_cd") or "").upper() == symbol:
            return row
    if len(rows) == 1 and isinstance(rows[0], dict):
        return rows[0]
    return {}


def _order_side(row: dict) -> str:
    slby_tp = str(row.get("slby_tp") or "").strip()
    if slby_tp == "2":
        return "buy"
    if slby_tp == "1":
        return "sell"
    label = " ".join(
        str(row.get(key) or "")
        for key in ("slby_tp_nm", "trde_tp", "frgn_trde_tp")
    ).lower()
    if "매수" in label or "buy" in label:
        return "buy"
    if "매도" in label or "sell" in label:
        return "sell"
    return ""


def _order_filled_quantity(row: dict) -> int:
    cntr_qty = str(row.get("cntr_qty") or "").strip()
    if cntr_qty:
        return _clean_int(cntr_qty)
    return _clean_int(row.get("ord_qty"))


def _order_contract_quantity(row: dict) -> int:
    return _clean_int(_first_row_value(row, "cntr_qty", "exec_qty", "cntr_qy"))


def _order_filled_amount(row: dict) -> float:
    amount_text = str(row.get("cntr_amt") or "").strip()
    amount = _clean_float(amount_text)
    if amount_text and amount != 0:
        return abs(amount)
    qty = _order_filled_quantity(row)
    price = _clean_float(row.get("cntr_uv"))
    return abs(qty * price)


def _order_history_no(row: dict) -> str:
    return str(_first_row_value(row, "ord_no", "odno", "orgn_ord_no") or "").strip()


def _verified_order_status(history_row: dict | None) -> tuple[str, str, dict[str, int]]:
    if not history_row:
        return "not_found", "키움 주문내역에서 주문번호를 찾지 못했습니다.", {
            "filled_quantity": 0,
            "remaining_quantity": 0,
            "canceled_quantity": 0,
        }
    filled = _clean_int(history_row.get("cntr_qty"))
    remaining = _clean_int(history_row.get("ord_remnq"))
    canceled = _clean_int(history_row.get("cncl_qty"))
    quantities = {
        "filled_quantity": filled,
        "remaining_quantity": remaining,
        "canceled_quantity": canceled,
    }
    if filled > 0 and remaining > 0:
        return "partial", f"부분체결 {filled}주 / 미체결 {remaining}주", quantities
    if filled > 0:
        return "filled", f"체결 {filled}주", quantities
    if remaining > 0:
        return "accepted", f"미체결 잔량 {remaining}주", quantities
    if canceled > 0:
        return "canceled", f"취소 {canceled}주", quantities
    return "unfilled_closed", "체결 0주 / 잔량 0주 - 유효 주문으로 남아있지 않습니다.", quantities


def _apply_order_history_verification(
    execution_rows: list[dict[str, Any]], history_rows: list[dict]
) -> list[dict[str, Any]]:
    history_by_no = {
        order_no: row
        for row in history_rows
        if (order_no := _order_history_no(row))
    }
    verified_rows: list[dict[str, Any]] = []
    for row in execution_rows:
        item = dict(row)
        history_row = history_by_no.get(str(item.get("order_no") or "").strip())
        verified_status, verified_message, quantities = _verified_order_status(history_row)
        item["api_status"] = item.get("status")
        item["status"] = verified_status
        item["verified_message"] = verified_message
        item.update(quantities)
        item["message"] = verified_message
        verified_rows.append(item)
    return verified_rows


def _order_history_rows_for_date(
    credentials: KiwoomCredentials,
    token: Any,
    *,
    order_date: date,
    stex_tp: str,
    symbol: str,
) -> list[dict]:
    history = request_us_period_order_history(
        credentials,
        token,
        start_date=order_date.strftime("%Y%m%d"),
        end_date=order_date.strftime("%Y%m%d"),
        slby_tp="0",
        stex_tp=stex_tp,
        stk_cd=symbol.upper(),
        oppo_trde_tp="%",
    )
    return _result_rows(history)


def _summarize_last_order_day(rows: list[dict], symbol: str) -> dict[str, Any]:
    symbol = symbol.upper()
    symbol_rows = [
        row
        for row in rows
        if str(row.get("stk_cd") or "").upper() == symbol
        and str(row.get("ord_dt") or "").strip()
    ]
    if not symbol_rows:
        return {"last_trade_date": "", "buy_qty": 0, "sell_qty": 0}
    last_trade_date = max(str(row.get("ord_dt") or "") for row in symbol_rows)
    buy_qty = 0
    sell_qty = 0
    for row in symbol_rows:
        if str(row.get("ord_dt") or "") != last_trade_date:
            continue
        qty = _order_filled_quantity(row)
        side = _order_side(row)
        if side == "buy":
            buy_qty += qty
        elif side == "sell":
            sell_qty += qty
    return {
        "last_trade_date": last_trade_date,
        "buy_qty": buy_qty,
        "sell_qty": sell_qty,
    }


def _summarize_order_period(rows: list[dict], symbol: str) -> dict[str, Any]:
    symbol = symbol.upper()
    buy_qty = 0
    sell_qty = 0
    buy_amount = 0.0
    sell_amount = 0.0
    for row in rows:
        row_symbol = str(row.get("stk_cd") or "").upper()
        if row_symbol and row_symbol != symbol:
            continue
        qty = _order_filled_quantity(row)
        amount = _order_filled_amount(row)
        side = _order_side(row)
        if side == "buy":
            buy_qty += qty
            buy_amount += amount
        elif side == "sell":
            sell_qty += qty
            sell_amount += amount
    return {
        "buy_qty": buy_qty,
        "buy_amount": buy_amount,
        "sell_qty": sell_qty,
        "sell_amount": sell_amount,
    }


def _latest_completed_vr_result_period(profile: Profile, query_day: date) -> tuple[int, Any]:
    start_day = date.fromisoformat(profile.start_date)
    latest: tuple[int, Any] | None = None
    cycle_no = 0
    while cycle_no < 10000:
        dates = cycle_dates(start_day, cycle_no)
        if dates.result_end >= query_day:
            break
        latest = (cycle_no, dates)
        cycle_no += 1
    if latest is None:
        raise ValueError("조회일 기준으로 완료된 VR 결과구간이 아직 없습니다.")
    return latest


def _vr_fill_history_rows(rows: list[dict], symbol: str) -> list[dict]:
    symbol = symbol.upper()
    fill_rows: list[dict] = []
    for row in rows:
        row_symbol = str(row.get("stk_cd") or "").upper()
        if row_symbol and row_symbol != symbol:
            continue
        quantity = _order_contract_quantity(row)
        if quantity <= 0:
            continue
        side = _order_side(row)
        if side not in {"buy", "sell"}:
            continue
        price = _clean_float(
            _first_row_value(row, "cntr_uv", "cntr_pric", "avg_pric", "ord_uv")
        )
        amount = _clean_float(_first_row_value(row, "cntr_amt", "exec_amt", "trde_amt"))
        if amount == 0 and price:
            amount = quantity * price
        trade_date = str(_first_row_value(row, "cntr_dt", "ord_dt", "trde_dt") or "").strip()
        order_no = str(_first_row_value(row, "ord_no", "odno", "orgn_ord_no") or "").strip()
        order_quantity = _clean_int(row.get("ord_qty"))
        status = str(
            _first_row_value(
                row,
                "ord_stt_nm",
                "ord_stat_nm",
                "cntr_tp_nm",
                "trde_tp_nm",
                "ord_stt",
            )
            or ""
        ).strip()
        fill_rows.append(
            {
                "date": trade_date,
                "display_date": _format_api_date(trade_date),
                "side": side,
                "side_label": "매수" if side == "buy" else "매도",
                "price": price,
                "price_key": f"{round(price, 2):.2f}" if price else "",
                "quantity": quantity,
                "amount": abs(amount),
                "order_no": order_no,
                "order_quantity": order_quantity,
                "status": status,
            }
        )
    return sorted(
        fill_rows,
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("side") or ""),
            float(item.get("price") or 0),
            str(item.get("order_no") or ""),
        ),
    )


def _vr_fill_price_summary(fill_rows: list[dict]) -> list[dict]:
    summary: dict[tuple[str, str], dict] = {}
    for row in fill_rows:
        key = (str(row.get("side") or ""), str(row.get("price_key") or ""))
        if not key[0] or not key[1]:
            continue
        item = summary.setdefault(
            key,
            {
                "side": key[0],
                "side_label": row.get("side_label") or "",
                "price": row.get("price") or 0,
                "quantity": 0,
                "amount": 0.0,
            },
        )
        item["quantity"] += int(row.get("quantity") or 0)
        item["amount"] += float(row.get("amount") or 0)
    return sorted(
        summary.values(),
        key=lambda item: (
            0 if item.get("side") == "buy" else 1,
            float(item.get("price") or 0),
        ),
    )


def _current_vr_order_period(profile: Profile, query_day: date) -> tuple[int, Any]:
    start_day = date.fromisoformat(profile.start_date)
    latest: tuple[int, Any] | None = None
    cycle_no = 0
    while cycle_no < 10000:
        dates = cycle_dates(start_day, cycle_no)
        if dates.result_start > query_day:
            break
        latest = (cycle_no, dates)
        cycle_no += 1
    if latest is None:
        raise ValueError("조회일 기준으로 시작된 VR 주문표 기간이 아직 없습니다.")
    return latest


def _vr_fill_lookup_period(profile: Profile, query_day: date, period_kind: str) -> tuple[int, Any]:
    cycle_no, dates = _current_vr_order_period(profile, query_day)
    if period_kind == "current":
        return cycle_no, dates
    if period_kind != "previous":
        raise ValueError(f"지원하지 않는 체결내역 조회 구분입니다: {period_kind}")
    previous_cycle_no = cycle_no - 1
    if previous_cycle_no < 0:
        raise ValueError("조회 가능한 지난차수 VR 주문표 기간이 아직 없습니다.")
    start_day = date.fromisoformat(profile.start_date)
    return previous_cycle_no, cycle_dates(start_day, previous_cycle_no)


def _format_kiwoom_error(prefix: str, exc: KiwoomApiError) -> str:
    details = []
    if exc.status_code is not None:
        details.append(f"HTTP {exc.status_code}")
    if exc.return_code is not None:
        details.append(f"return_code {exc.return_code}")
    if exc.return_msg:
        details.append(exc.return_msg)
    hint = _kiwoom_error_hint(exc)
    if hint:
        details.append(hint)
    if exc.response_preview:
        details.append(f"response {exc.response_preview}")
    error_text = str(exc)
    if error_text and error_text not in details:
        details.append(error_text)
    return prefix + (": " + " / ".join(str(item) for item in details) if details else "")


def _profile_label(profile: dict[str, Any]) -> str:
    profile_no = profile.get("profile_no")
    name = str(profile.get("name") or "")
    if profile_no in (None, ""):
        return name
    return f"#{profile_no} {name}"


def _format_missing_issue(count: int, first_day: Any = None, last_day: Any = None) -> str:
    if count <= 0:
        return ""
    if first_day and last_day and first_day != last_day:
        return f"평단 미입력 {count}개 / {first_day} ~ {last_day}"
    if first_day:
        return f"평단 미입력 {count}개 / {first_day}"
    return f"미작성 {count}개"


def _infinite_missing_summary(
    con: duckdb.DuckDBPyConnection, setting: InfiniteSetting
) -> dict[str, Any]:
    if setting.calculation_paused:
        return {"count": 0, "issue": "산출 중단", "first_day": "", "last_day": ""}
    required_day = previous_us_trading_day(date.today() - timedelta(days=1))
    if required_day < setting.start_date:
        return {"count": 0, "issue": "", "first_day": "", "last_day": ""}
    try:
        row = con.execute(
            """
            SELECT count(*), min(trade_date), max(trade_date)
            FROM infinite_rows
            WHERE setting_name = ?
              AND trade_date <= ?
              AND avg_price IS NULL
            """,
            [setting.name, required_day],
        ).fetchone()
    except duckdb.Error:
        return {"count": 0, "issue": "", "first_day": "", "last_day": ""}
    count = int(row[0] or 0)
    first_day = _json_value(row[1]) if row and row[1] else ""
    last_day = _json_value(row[2]) if row and row[2] else ""
    return {
        "count": count,
        "issue": _format_missing_issue(count, first_day, last_day),
        "first_day": first_day,
        "last_day": last_day,
    }


def _dashboard_vr_rows(
    con: duckdb.DuckDBPyConnection, profiles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile_data in profiles:
        profile = _profile_from_data(profile_data)
        snapshot = latest_cycle_snapshot(con, profile.name)
        try:
            status = profile_cycle_status(con, profile)
        except Exception:
            status = {"missing_cycles": [], "missing_count": 0, "last_done_cycle": None}
        missing = status.get("missing_cycles") or []
        target_cycle_no = int(missing[0]) if missing else None
        missing_count = 0 if profile.calculation_paused else int(status.get("missing_count") or 0)
        missing_list = ", ".join(str(item) for item in missing[:8])
        if len(missing) > 8:
            missing_list += "..."
        issue = "산출 중단" if profile.calculation_paused else (
            f"{missing_count}개 차수 미작성 {missing_list}".strip() if missing_count else ""
        )
        rows.append(
            {
                "name": profile.name,
                "label": _profile_label(profile_data),
                "symbol": profile.symbol,
                "account_number": profile.account_number,
                "principal": float(snapshot["principal"]) if snapshot else 0.0,
                "account_total": float(snapshot["account_total"]) if snapshot else 0.0,
                "profit": float(snapshot["profit"]) if snapshot else 0.0,
                "return_rate": float(snapshot["return_rate"])
                if snapshot and snapshot["return_rate"] is not None
                else None,
                "buy_principal": float(snapshot["buy_principal"]) if snapshot else 0.0,
                "cash_amount": float(snapshot["pool"]) if snapshot else 0.0,
                "shares": int(snapshot["shares"]) if snapshot and snapshot["shares"] is not None else 0,
                "last_done_cycle": status.get("last_done_cycle"),
                "target_cycle_no": target_cycle_no,
                "last_done_text": "-"
                if status.get("last_done_cycle") is None
                else str(status.get("last_done_cycle")),
                "missing_count": missing_count,
                "missing_text": "산출 중단"
                if profile.calculation_paused
                else (f"{missing_count}개" if missing_count else ""),
                "issue": issue,
                "calculation_paused": profile.calculation_paused,
            }
        )
    return rows


def _dashboard_infinite_rows(
    con: duckdb.DuckDBPyConnection, settings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for setting_data in settings:
        setting = _infinite_setting_from_data(setting_data)
        try:
            status = infinite_status_view(con, setting)
            daily_rows = infinite_rows(con, setting.name)
        except Exception:
            status = {}
            daily_rows = []
        latest = daily_rows[-1] if daily_rows else None
        missing = _infinite_missing_summary(con, setting)
        market_price = status.get("current_price") or status.get("avg_price") or 0.0
        fx_rate = status.get("fx_rate") or 1.0
        market_value = float(status.get("cumulative_qty") or 0) * float(fx_rate) * float(market_price or 0)
        principal = float(status.get("repeat_principal") or setting.initial_principal)
        cumulative_amount = float(latest["cumulative_amount"]) if latest else 0.0
        cash_basis_principal = (
            float(latest.get("principal_after_withdrawal") or principal)
            if latest
            else principal
        )
        cash_amount = max(0.0, cash_basis_principal - cumulative_amount)
        progress = status.get("progress")
        t_value = status.get("t_value")
        progress_text = ""
        if t_value is not None and setting.split_count:
            progress_text = f"{float(t_value):.1f}T / {int(setting.split_count)}T"
        if progress is not None:
            progress_text = f"{progress_text} / {float(progress) * 100:.1f}%".strip(" /")
        if status.get("phase"):
            progress_text = f"{progress_text} / {status.get('phase')}".strip(" /")
        rows.append(
            {
                "name": setting.name,
                "label": _profile_label(setting_data),
                "profile_no": setting.profile_no,
                "symbol": setting.symbol,
                "account_number": setting.account_number,
                "mode": setting.mode,
                "start_date": setting.start_date.isoformat(),
                "principal": principal,
                "cumulative_amount": cumulative_amount,
                "cumulative_value": market_value,
                "cash_amount": cash_amount,
                "return_rate": status.get("return_rate"),
                "avg_price": status.get("avg_price"),
                "current_price": status.get("current_price"),
                "cumulative_qty": int(status.get("cumulative_qty") or 0),
                "t_value": t_value,
                "split_count": setting.split_count,
                "progress": progress,
                "phase": status.get("phase") or "",
                "progress_text": progress_text,
                "missing_count": int(missing["count"]),
                "target_trade_date": missing.get("first_day") or "",
                "missing_text": "산출 중단"
                if setting.calculation_paused
                else (f"{missing['count']}개" if missing["count"] else ""),
                "issue": missing["issue"],
                "calculation_paused": setting.calculation_paused,
            }
        )
    return rows


def _dashboard_summary(
    con: duckdb.DuckDBPyConnection,
    vr_rows: list[dict[str, Any]],
    infinite_rows_data: list[dict[str, Any]],
) -> dict[str, Any]:
    fx_rate = latest_fx_rate(con, date.today())
    vr_principal_usd = sum(float(row["principal"] or 0) for row in vr_rows)
    vr_value_usd = sum(float(row["account_total"] or 0) for row in vr_rows)
    vr_bought_usd = sum(float(row["buy_principal"] or 0) for row in vr_rows)
    vr_cash_usd = sum(float(row["cash_amount"] or 0) for row in vr_rows)
    infinite_principal_usd = sum(float(row["principal"] or 0) for row in infinite_rows_data)
    infinite_value_krw = sum(float(row["cumulative_value"] or 0) for row in infinite_rows_data)
    infinite_bought_usd = sum(float(row["cumulative_amount"] or 0) for row in infinite_rows_data)
    infinite_cash_usd = sum(float(row["cash_amount"] or 0) for row in infinite_rows_data)
    total_principal_krw = (vr_principal_usd + infinite_principal_usd) * fx_rate
    total_value_krw = (vr_value_usd * fx_rate) + infinite_value_krw + (infinite_cash_usd * fx_rate)
    total_profit_krw = total_value_krw - total_principal_krw
    total_bought_krw = (vr_bought_usd + infinite_bought_usd) * fx_rate
    total_cash_krw = (vr_cash_usd + infinite_cash_usd) * fx_rate
    cash_basis = total_bought_krw + total_cash_krw
    return {
        "fx_rate": fx_rate,
        "total_value_krw": total_value_krw,
        "total_principal_krw": total_principal_krw,
        "total_profit_krw": total_profit_krw,
        "total_return_rate": total_profit_krw / total_principal_krw if total_principal_krw else None,
        "total_bought_krw": total_bought_krw,
        "total_cash_krw": total_cash_krw,
        "total_cash_ratio": total_cash_krw / cash_basis if cash_basis else None,
        "vr_due_count": sum(1 for row in vr_rows if row["missing_count"] > 0),
        "infinite_due_count": sum(1 for row in infinite_rows_data if row["missing_count"] > 0),
    }


def _week_no_for_cycle(profile: Profile, cycle_no: int) -> int:
    if cycle_no <= 0:
        return 0
    return int(profile.start_week_no) + (cycle_no - 1) * 2


def _vr_cycle_input_defaults(
    con: duckdb.DuckDBPyConnection, profile: Profile
) -> dict[str, Any]:
    cycle_no = next_input_cycle(con, profile.name)
    start_day = date.fromisoformat(profile.start_date)
    dates = cycle_dates(start_day, cycle_no)
    available_date = cycle_input_available_date(start_day, cycle_no)
    close_price: float | str = ""
    try:
        close_price = round(float(find_close_price(con, profile.symbol, dates.result_end)), 2)
    except Exception:
        close_price = ""
    return {
        "cycle_no": cycle_no,
        "week_no": _week_no_for_cycle(profile, cycle_no),
        "result_period": f"{dates.result_start} ~ {dates.result_end}",
        "next_period": f"{cycle_dates(start_day, cycle_no + 1).result_start} ~ {cycle_dates(start_day, cycle_no + 1).result_end}",
        "available_date": available_date.isoformat(),
        "allowed": bool(date.today() >= available_date and not profile.calculation_paused),
        "close_price": close_price,
        "trade_amount": 0,
        "shares": "",
        "dividend": 0,
        "contribution_amount": latest_contribution_amount(con, profile),
        "g_config": latest_g_config(con, profile),
        "g_start_cycle_no": latest_g_start_cycle_no(con, profile),
        "buy_limit_config": latest_buy_limit_config(con, profile),
        "buy_limit_start_week_no": latest_buy_limit_start_week_no(con, profile),
        "mode": "save",
    }


def user_dashboard(username: str) -> dict[str, Any]:
    base_dir = user_data_dir(username)
    db_path = user_db_path(username)
    result: dict[str, Any] = {
        "username": username,
        "today": date.today().isoformat(),
        "has_database": db_path.exists(),
        "counts": {
            "vr_snapshots": 0,
            "infinite_profiles": 0,
            "infinite_rows": 0,
            "order_levels": 0,
        },
        "vr_profiles": _read_profile_files(base_dir, "vr"),
        "infinite_profiles": [],
        "summary": {},
        "due_items": [],
        "vr_profile_rows": [],
        "infinite_profile_rows": [],
    }
    con = _connect_readonly(db_path)
    if con is None:
        return result
    try:
        tables = _tables(con)
        result["counts"] = {
            "vr_snapshots": _vr_snapshot_count(con, tables),
            "infinite_profiles": _infinite_profile_count(con, tables),
            "infinite_rows": _count(con, "infinite_rows", tables),
            "order_levels": _count(con, "order_levels", tables),
        }
        if "infinite_settings" in tables:
            result["infinite_profiles"] = _query_dicts(
                con,
                """
                SELECT
                    profile_no,
                    name,
                    symbol,
                    start_date,
                    account_number,
                    mode,
                    calculation_paused
                FROM infinite_settings
                WHERE name <> 'default'
                ORDER BY COALESCE(profile_no, 9999), name
                """,
            )
        result["vr_profile_rows"] = _dashboard_vr_rows(con, result["vr_profiles"])
        result["infinite_profile_rows"] = _dashboard_infinite_rows(
            con, result["infinite_profiles"]
        )
        result["summary"] = _dashboard_summary(
            con, result["vr_profile_rows"], result["infinite_profile_rows"]
        )
        due_items: list[dict[str, Any]] = []
        for row in result["vr_profile_rows"]:
            if row["missing_count"] > 0:
                due_items.append(
                    {
                        "kind": "VR",
                        "strategy": "vr",
                        "profile_name": row["name"],
                        "profile": row["label"],
                        "issue": row["issue"],
                        "target_cycle_no": row.get("target_cycle_no"),
                    }
                )
        for row in result["infinite_profile_rows"]:
            if row["missing_count"] > 0:
                due_items.append(
                    {
                        "kind": "무한매수법",
                        "strategy": "infinite",
                        "profile_name": row["name"],
                        "profile": row["label"],
                        "issue": row["issue"],
                        "target_trade_date": row.get("target_trade_date") or "",
                    }
                )
        result["due_items"] = due_items
    finally:
        con.close()
    return result


def dashboard_vr_chart(username: str, profile_name: str) -> dict[str, Any]:
    base_dir = user_data_dir(username)
    db_path = user_db_path(username)
    profile = _read_profile_file(base_dir, "vr", profile_name)
    result: dict[str, Any] = {
        "name": profile_name,
        "label": _profile_label(profile),
        "rows": [],
    }
    con = _connect_readonly(db_path)
    if con is None:
        return result
    try:
        if "rebalance_snapshots" not in _tables(con):
            return result
        rows = _query_dicts(
            con,
            """
            SELECT
                cycle_no,
                end_date,
                min_value,
                max_value,
                account_total,
                valuation,
                principal,
                profit
            FROM (
                SELECT
                    *,
                    row_number() OVER (
                        PARTITION BY cycle_no
                        ORDER BY id DESC
                    ) AS rn
                FROM rebalance_snapshots
                WHERE profile_name = ? AND cycle_no IS NOT NULL
            )
            WHERE rn = 1
            ORDER BY cycle_no
            """,
            (profile_name,),
        )
        result["rows"] = rows
        return result
    finally:
        con.close()


def dashboard_infinite_chart(username: str, profile_name: str) -> dict[str, Any]:
    db_path = user_db_path(username)
    result: dict[str, Any] = {
        "name": profile_name,
        "label": profile_name,
        "rows": [],
    }
    con = _connect_readonly(db_path)
    if con is None:
        return result
    try:
        if "infinite_settings" not in _tables(con):
            return result
        setting_row = con.execute(
            """
            SELECT
                profile_no,
                name,
                symbol,
                start_date,
                account_number,
                mode,
                calculation_paused,
                initial_principal,
                initial_cumulative_amount,
                initial_cumulative_qty,
                target_rate,
                split_count,
                fee_rate
            FROM infinite_settings
            WHERE name = ?
            """,
            [profile_name],
        ).fetchone()
        if setting_row is None:
            return result
        columns = [item[0] for item in con.description]
        setting_data = {key: _json_value(value) for key, value in zip(columns, setting_row)}
        setting = _infinite_setting_from_data(setting_data)
        result["label"] = _profile_label(setting_data)
        result["rows"] = list(reversed(infinite_rows(con, setting.name)))
        return result
    finally:
        con.close()


def vr_profiles(username: str) -> list[dict[str, Any]]:
    return _read_profile_files(user_data_dir(username), "vr")


def infinite_profiles(username: str) -> list[dict[str, Any]]:
    base_dir = user_data_dir(username)
    db_path = user_db_path(username)
    con = _connect_readonly(db_path)
    if con is None:
        return _read_profile_files(base_dir, "infinite")
    try:
        tables = _tables(con)
        if "infinite_settings" not in tables:
            return _read_profile_files(base_dir, "infinite")
        return _query_dicts(
            con,
            """
            SELECT
                profile_no,
                name,
                symbol,
                start_date,
                account_number,
                mode,
                calculation_paused
            FROM infinite_settings
            WHERE name <> 'default'
            ORDER BY COALESCE(profile_no, 9999), name
            """,
        )
    finally:
        con.close()


def vr_profile_detail(username: str, profile_name: str) -> dict[str, Any]:
    base_dir = user_data_dir(username)
    db_path = user_db_path(username)
    profile = _read_profile_file(base_dir, "vr", profile_name)
    detail: dict[str, Any] = {
        "profile": profile,
        "snapshots": [],
        "order_levels": [],
        "order_basis": None,
        "order_executable": False,
        "order_reorderable": False,
        "order_date": "",
        "order_expected_count": 0,
        "order_history_warning": "",
        "order_message": "",
        "order_executions": [],
        "cycle_input": None,
    }
    con = _connect_readonly(db_path)
    if con is None:
        if not profile:
            return detail
        con = _connect_writable(db_path)
    try:
        tables = _tables(con)
        if "rebalance_snapshots" in tables:
            detail["snapshots"] = _query_dicts(
                con,
                """
                SELECT
                    id,
                    cycle_no,
                    start_date,
                    end_date,
                    week_no,
                    status,
                    close_price,
                    g,
                    v,
                    min_value,
                    max_value,
                    trade_amount,
                    prior_pool,
                    pool,
                    principal,
                    account_total,
                    return_rate,
                    profit,
                    shares,
                    avg_cost,
                    valuation,
                    contribution,
                    dividend,
                    g_config,
                    g_start_cycle_no,
                    buy_limit_config,
                    buy_limit_start_week_no
                FROM (
                    SELECT
                        *,
                        row_number() OVER (
                            PARTITION BY cycle_no
                            ORDER BY id DESC
                        ) AS rn
                    FROM rebalance_snapshots
                    WHERE profile_name = ? AND cycle_no IS NOT NULL
                )
                WHERE rn = 1
                ORDER BY cycle_no DESC
                LIMIT 120
                """,
                (profile_name,),
            )
        latest_id = None
        if detail["snapshots"]:
            latest_id = detail["snapshots"][0].get("id")
        if latest_id and "order_levels" in tables:
            detail["order_levels"] = _query_dicts(
                con,
                """
                SELECT
                    side,
                    level_no,
                    quantity_step,
                    before_shares,
                    after_shares,
                    price,
                    pool_before,
                    pool_after
                FROM order_levels
                WHERE snapshot_id = ?
                ORDER BY side, level_no
                """,
                (latest_id,),
            )
        if not detail["order_levels"] and detail["snapshots"] and profile:
            try:
                rows = order_level_values(_profile_from_data(profile), detail["snapshots"][0])
                detail["order_levels"] = [
                    {key: _json_value(value) for key, value in row.items()}
                    for row in rows
                ]
            except Exception as exc:
                detail["order_error"] = str(exc)
        if profile:
            try:
                profile_obj = _profile_from_data(profile)
                detail["cycle_input"] = _vr_cycle_input_defaults(con, profile_obj)
                basis = order_basis_for_next_cycle(con, profile_obj)
                if basis is not None:
                    detail["order_basis"] = {key: _json_value(value) for key, value in basis.items()}
                    basis_rows = order_level_values(
                        profile_obj, basis, quantity_step=int(profile_obj.quantity_step or 1)
                    )
                    detail["order_levels"] = [
                        {key: _json_value(value) for key, value in row.items()}
                        for row in basis_rows
                    ]
                    start_day = date.fromisoformat(str(basis["start_date"]))
                    end_day = date.fromisoformat(str(basis["end_date"]))
                    has_orders = bool(detail["order_levels"])
                    expected_count = _vr_match_buy_order_count(detail["order_levels"])
                    query_day = date.today()
                    sent_count = _successful_order_execution_count(
                        con, "vr", profile_name, query_day
                    )
                    detail["order_executions"] = _recent_order_execution_rows(
                        con, "vr", profile_name, query_day
                    )
                    if detail["order_executions"]:
                        try:
                            verify_credentials = load_kiwoom_credentials(
                                "vr", profile_name, kiwoom_credentials_path(username)
                            )
                            verify_token, _ = _ensure_user_kiwoom_token(
                                username, "vr", profile_name, verify_credentials
                            )
                            verify_stex_tp = _resolve_user_exchange_code(
                                verify_credentials, verify_token, profile_obj.symbol
                            )
                            detail["order_executions"] = _verify_order_execution_rows(
                                detail["order_executions"],
                                verify_credentials,
                                verify_token,
                                order_date=query_day,
                                stex_tp=verify_stex_tp,
                                symbol=profile_obj.symbol,
                            )
                        except Exception as exc:
                            detail["order_history_warning"] = f"키움 주문내역 검증 실패: {exc}"
                    detail["order_date"] = query_day.isoformat()
                    detail["order_expected_count"] = expected_count
                    detail["order_executable"] = bool(
                        start_day <= query_day <= end_day and has_orders and sent_count == 0
                    )
                    detail["order_reorderable"] = bool(
                        start_day <= query_day <= end_day and has_orders and sent_count > 0
                    )
                    detail["order_message"] = (
                        f"주문표 기간: {start_day} ~ {end_day} / "
                        f"주문 실행일: {query_day}"
                    )
                    if sent_count:
                        detail["order_message"] = (
                            f"주문표 기간: {start_day} ~ {end_day} / "
                            f"{query_day} 주문실행 이력 {sent_count}건"
                        )
                        if expected_count and sent_count != expected_count:
                            detail["order_history_warning"] = (
                                f"현재 기본 주문옵션 예상 {expected_count}건과 "
                                f"저장된 이력 {sent_count}건이 다릅니다."
                            )
                            detail["order_message"] = (
                                f"{detail['order_message']} / "
                                f"{detail['order_history_warning']}"
                            )
            except Exception as exc:
                detail["order_error"] = str(exc)
    finally:
        con.close()
    return detail


def create_vr_web_profile(username: str, name: str) -> dict[str, Any]:
    profile_name = name.strip()
    if not profile_name or profile_name == "default":
        raise ValueError("사용할 수 없는 프로필 이름입니다.")
    profile = create_profile(profile_name, user_data_dir(username) / "profiles" / "vr")
    return asdict(profile)


def update_vr_web_profile(
    username: str, profile_name: str, payload: dict[str, Any]
) -> dict[str, Any]:
    profiles_dir = user_data_dir(username) / "profiles" / "vr"
    current = _profile_from_data(_read_profile_file(user_data_dir(username), "vr", profile_name))
    quantity_step_value = _payload_value(payload, "quantity_step", current.quantity_step)
    if quantity_step_value is None:
        quantity_step_value = current.quantity_step
    start_week_no_value = int(_payload_value(payload, "start_week_no", current.start_week_no))
    buy_limit_start_week_no_value = _payload_value(
        payload, "buy_limit_start_week_no", start_week_no_value
    )
    if buy_limit_start_week_no_value is None:
        buy_limit_start_week_no_value = start_week_no_value
    updated = update_profile(
        current,
        start_date=str(_payload_value(payload, "start_date", current.start_date)).strip(),
        start_week_no=start_week_no_value,
        symbol=str(_payload_value(payload, "symbol", current.symbol)).strip(),
        account_number=str(
            _payload_value(payload, "account_number", current.account_number)
        ).strip(),
        min_ratio=float(_payload_value(payload, "min_ratio", current.min_ratio)),
        max_ratio=float(_payload_value(payload, "max_ratio", current.max_ratio)),
        initial_v=float(_payload_value(payload, "initial_v", current.initial_v)),
        initial_pool=float(_payload_value(payload, "initial_pool", current.initial_pool)),
        initial_principal=float(
            _payload_value(payload, "initial_principal", current.initial_principal)
        ),
        initial_shares=int(_payload_value(payload, "initial_shares", current.initial_shares)),
        quantity_step=int(quantity_step_value),
        buy_limit_start_week_no=int(buy_limit_start_week_no_value),
    )
    if updated.min_ratio <= 0 or updated.max_ratio <= 0:
        raise ValueError("최소/최대 비율은 0보다 커야 합니다.")
    if updated.min_ratio >= updated.max_ratio:
        raise ValueError("최소 비율은 최대 비율보다 작아야 합니다.")
    if updated.initial_shares < 0:
        raise ValueError("초기 개수는 0 이상이어야 합니다.")
    if updated.quantity_step <= 0:
        raise ValueError("수량간격은 1 이상이어야 합니다.")
    save_profile(updated, profiles_dir)
    return asdict(updated)


def rename_vr_web_profile(username: str, profile_name: str, new_name: str) -> dict[str, Any]:
    target_name = new_name.strip()
    if not target_name or target_name == "default":
        raise ValueError("사용할 수 없는 프로필 이름입니다.")
    profiles_dir = user_data_dir(username) / "profiles" / "vr"
    db_path = user_db_path(username)
    updated = rename_profile(profile_name, target_name, profiles_dir)
    con = _connect_writable(db_path)
    try:
        tables = _tables(con)
        if "rebalance_snapshots" in tables:
            rename_profile_snapshots(con, profile_name, target_name)
        if "web_order_executions" in tables:
            con.execute(
                """
                UPDATE web_order_executions
                SET profile_name = ?
                WHERE strategy = 'vr' AND profile_name = ?
                """,
                (target_name, profile_name),
            )
    finally:
        con.close()
    rename_kiwoom_credentials(
        "vr", profile_name, target_name, kiwoom_credentials_path(username)
    )
    rename_profile_token("vr", profile_name, target_name, kiwoom_token_cache_path(username))
    return asdict(updated)


def delete_vr_web_profile(username: str, profile_name: str) -> dict[str, Any]:
    if profile_name == "default":
        raise ValueError("default 프로필은 삭제할 수 없습니다.")
    profiles_dir = user_data_dir(username) / "profiles" / "vr"
    con = _connect_writable(user_db_path(username))
    try:
        tables = _tables(con)
        if "rebalance_snapshots" in tables:
            if "order_levels" in tables:
                con.execute(
                    """
                    DELETE FROM order_levels
                    WHERE snapshot_id IN (
                        SELECT id FROM rebalance_snapshots WHERE profile_name = ?
                    )
                    """,
                    (profile_name,),
                )
            con.execute(
                "DELETE FROM rebalance_snapshots WHERE profile_name = ?", (profile_name,)
            )
        if "web_order_executions" in tables:
            con.execute(
                "DELETE FROM web_order_executions WHERE strategy = 'vr' AND profile_name = ?",
                (profile_name,),
            )
    finally:
        con.close()
    delete_profile(profile_name, profiles_dir)
    delete_kiwoom_credentials("vr", profile_name, kiwoom_credentials_path(username))
    delete_profile_token("vr", profile_name, kiwoom_token_cache_path(username))
    return {"ok": True, "deleted": profile_name}


def toggle_vr_web_profile_pause(username: str, profile_name: str) -> dict[str, Any]:
    if profile_name == "default":
        raise ValueError("default 프로필은 산출 중단 대상에서 제외됩니다.")
    profiles_dir = user_data_dir(username) / "profiles" / "vr"
    current = _profile_from_data(_read_profile_file(user_data_dir(username), "vr", profile_name))
    updated = update_profile(current, calculation_paused=not current.calculation_paused)
    save_profile(updated, profiles_dir)
    return asdict(updated)


def save_vr_web_cycle_input(
    username: str, profile_name: str, payload: dict[str, Any]
) -> dict[str, Any]:
    profile = _profile_from_data(_read_profile_file(user_data_dir(username), "vr", profile_name))
    cycle_no = int(_payload_value(payload, "cycle_no", 0))
    close_raw = str(payload.get("close_price") or "").replace(",", "").strip()
    close_price = float(close_raw) if close_raw else None
    cycle_input = CycleInput(
        cycle_no=cycle_no,
        close_price=close_price,
        trade_amount=float(_payload_value(payload, "trade_amount", 0)),
        shares=int(_payload_value(payload, "shares", 0)),
        dividend=float(_payload_value(payload, "dividend", 0)),
        contribution_amount=float(_payload_value(payload, "contribution_amount", 0)),
        g_config=str(_payload_value(payload, "g_config", "")).strip(),
        g_start_cycle_no=int(_payload_value(payload, "g_start_cycle_no", profile.start_week_no)),
        buy_limit_config=str(_payload_value(payload, "buy_limit_config", "")).strip(),
        buy_limit_start_week_no=int(_payload_value(payload, "buy_limit_start_week_no", 2)),
    )
    con = _connect_writable(user_db_path(username))
    try:
        existing = snapshot_for_cycle(con, profile.name, cycle_no)
        if existing is not None:
            if cycle_input.close_price is None:
                raise ValueError("저장된 차수 수정은 종가가 필요합니다.")
            snapshot_id = recalculate_cycle_results_from(
                con, profile=profile, cycle_input=cycle_input
            )
            mode = "recalculate"
        else:
            expected = next_input_cycle(con, profile.name)
            if cycle_no != expected:
                raise ValueError(f"다음 입력 차수는 {expected}차입니다.")
            available_date = cycle_input_available_date(
                date.fromisoformat(profile.start_date), cycle_no
            )
            if date.today() < available_date:
                raise ValueError(
                    f"{_week_no_for_cycle(profile, cycle_no)}주차는 {available_date}부터 입력 가능합니다."
                )
            snapshot_id = save_cycle_result(con, profile=profile, cycle_input=cycle_input)
            mode = "save"
        try:
            con.execute("CHECKPOINT")
        except Exception:
            pass
    finally:
        con.close()
    detail = vr_profile_detail(username, profile_name)
    detail["cycle_save"] = {
        "ok": True,
        "snapshot_id": snapshot_id,
        "mode": mode,
        "message": "수정값 재계산 저장 완료" if mode == "recalculate" else "저장하고 다음 주차 매수/매도점 보기 완료",
    }
    return detail


def _safe_profile_filename(name: str) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if char in invalid else char for char in name).strip()
    cleaned = cleaned.strip(". ")
    if not cleaned:
        raise ValueError("Profile name cannot be empty")
    return cleaned


def _next_infinite_profile_no_for_user(username: str) -> int:
    used: set[int] = set()
    con = _connect_readonly(user_db_path(username))
    if con is not None:
        try:
            if "infinite_settings" in _tables(con):
                used.update(
                    int(row[0])
                    for row in con.execute(
                        "SELECT profile_no FROM infinite_settings WHERE name <> 'default'"
                    ).fetchall()
                    if row[0] is not None and int(row[0]) > 0
                )
        finally:
            con.close()
    for profile in _read_profile_files(user_data_dir(username), "infinite"):
        value = profile.get("profile_no")
        if value:
            used.add(int(value))
    profile_no = 1
    while profile_no in used:
        profile_no += 1
    return profile_no


def create_infinite_web_profile(username: str, name: str) -> dict[str, Any]:
    profile_name = name.strip()
    if not profile_name or profile_name == "default":
        raise ValueError("사용할 수 없는 프로필 이름입니다.")
    profiles_dir = user_data_dir(username) / "profiles" / "infinite"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    path = profiles_dir / f"{_safe_profile_filename(profile_name)}.json"
    if path.exists():
        raise ValueError(f"이미 존재하는 프로필입니다: {profile_name}")
    setting = InfiniteSetting(
        name=profile_name,
        profile_no=_next_infinite_profile_no_for_user(username),
    )
    data = asdict(setting)
    data["start_date"] = setting.start_date.isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    con = _connect_writable(user_db_path(username))
    try:
        if "infinite_settings" in _tables(con):
            existing = con.execute(
                "SELECT id FROM infinite_settings WHERE name = ?", [setting.name]
            ).fetchone()
            if not existing:
                con.execute(
                    """
                    INSERT INTO infinite_settings (
                        id,
                        profile_no,
                        account_number,
                        name,
                        symbol,
                        start_date,
                        initial_principal,
                        initial_cumulative_amount,
                        initial_cumulative_qty,
                        target_rate,
                        split_count,
                        fee_rate,
                        mode,
                        calculation_paused
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        next_id(con, "infinite_settings"),
                        setting.profile_no,
                        setting.account_number,
                        setting.name,
                        setting.symbol,
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
    finally:
        con.close()
    return data


def _write_infinite_profile_json(username: str, setting: InfiniteSetting) -> None:
    profiles_dir = user_data_dir(username) / "profiles" / "infinite"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    data = asdict(setting)
    data["start_date"] = setting.start_date.isoformat()
    path = profiles_dir / f"{_safe_profile_filename(setting.name)}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _save_infinite_setting_to_user_db(
    con: duckdb.DuckDBPyConnection, setting: InfiniteSetting
) -> None:
    if "infinite_settings" not in _tables(con):
        return
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
                setting.profile_no,
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
                setting.profile_no,
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


def update_infinite_web_profile(
    username: str, profile_name: str, payload: dict[str, Any]
) -> dict[str, Any]:
    current = _infinite_setting_from_data(
        infinite_profile_detail(username, profile_name).get("profile") or {"name": profile_name}
    )
    start_date_value = _payload_value(payload, "start_date", current.start_date)
    if isinstance(start_date_value, str):
        start_date_value = date.fromisoformat(start_date_value.strip())
    setting = InfiniteSetting(
        name=current.name,
        profile_no=int(_payload_value(payload, "profile_no", current.profile_no)),
        account_number=str(
            _payload_value(payload, "account_number", current.account_number)
        ).strip(),
        symbol=str(_payload_value(payload, "symbol", current.symbol)).strip().upper(),
        start_date=start_date_value,
        initial_principal=float(
            _payload_value(payload, "initial_principal", current.initial_principal)
        ),
        initial_cumulative_amount=float(
            _payload_value(
                payload,
                "initial_cumulative_amount",
                current.initial_cumulative_amount,
            )
        ),
        initial_cumulative_qty=int(
            _payload_value(
                payload,
                "initial_cumulative_qty",
                current.initial_cumulative_qty,
            )
        ),
        target_rate=float(_payload_value(payload, "target_rate", current.target_rate)),
        split_count=int(_payload_value(payload, "split_count", current.split_count)),
        fee_rate=float(_payload_value(payload, "fee_rate", current.fee_rate)),
        mode=str(_payload_value(payload, "mode", current.mode)).strip() or "기본",
        calculation_paused=bool(payload.get("calculation_paused", current.calculation_paused)),
    )
    if setting.symbol not in INFINITE_SYMBOLS:
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
    _write_infinite_profile_json(username, setting)
    con = _connect_writable(user_db_path(username))
    try:
        _save_infinite_setting_to_user_db(con, setting)
        generate_infinite_rows(con, setting, through=max(setting.start_date, date.today()))
    finally:
        con.close()
    data = asdict(setting)
    data["start_date"] = setting.start_date.isoformat()
    return data


def _infinite_profile_json_path(username: str, profile_name: str) -> Path:
    return user_data_dir(username) / "profiles" / "infinite" / f"{_safe_profile_filename(profile_name)}.json"


def rename_infinite_web_profile(
    username: str, profile_name: str, new_name: str
) -> dict[str, Any]:
    target_name = new_name.strip()
    if not target_name or target_name == "default":
        raise ValueError("사용할 수 없는 프로필 이름입니다.")
    current = _infinite_setting_from_data(
        infinite_profile_detail(username, profile_name).get("profile") or {"name": profile_name}
    )
    setting = replace(current, name=target_name)
    old_path = _infinite_profile_json_path(username, profile_name)
    new_path = _infinite_profile_json_path(username, target_name)
    if new_path.exists():
        raise ValueError(f"이미 존재하는 프로필입니다: {target_name}")
    if old_path.exists():
        old_path.unlink()
    _write_infinite_profile_json(username, setting)
    con = _connect_writable(user_db_path(username))
    try:
        tables = _tables(con)
        if "infinite_settings" in tables:
            con.execute(
                "UPDATE infinite_settings SET name = ?, updated_at = current_timestamp WHERE name = ?",
                (target_name, profile_name),
            )
        if "infinite_rows" in tables:
            con.execute(
                "UPDATE infinite_rows SET setting_name = ? WHERE setting_name = ?",
                (target_name, profile_name),
            )
        if "web_order_executions" in tables:
            con.execute(
                """
                UPDATE web_order_executions
                SET profile_name = ?
                WHERE strategy = 'infinite' AND profile_name = ?
                """,
                (target_name, profile_name),
            )
    finally:
        con.close()
    rename_kiwoom_credentials(
        "infinite", profile_name, target_name, kiwoom_credentials_path(username)
    )
    rename_profile_token(
        "infinite", profile_name, target_name, kiwoom_token_cache_path(username)
    )
    data = asdict(setting)
    data["start_date"] = setting.start_date.isoformat()
    return data


def delete_infinite_web_profile(username: str, profile_name: str) -> dict[str, Any]:
    if profile_name == "default":
        raise ValueError("default 프로필은 삭제할 수 없습니다.")
    path = _infinite_profile_json_path(username, profile_name)
    if path.exists():
        path.unlink()
    con = _connect_writable(user_db_path(username))
    try:
        tables = _tables(con)
        if "infinite_rows" in tables:
            con.execute("DELETE FROM infinite_rows WHERE setting_name = ?", (profile_name,))
        if "infinite_settings" in tables:
            con.execute("DELETE FROM infinite_settings WHERE name = ?", (profile_name,))
        if "web_order_executions" in tables:
            con.execute(
                "DELETE FROM web_order_executions WHERE strategy = 'infinite' AND profile_name = ?",
                (profile_name,),
            )
    finally:
        con.close()
    delete_kiwoom_credentials("infinite", profile_name, kiwoom_credentials_path(username))
    delete_profile_token("infinite", profile_name, kiwoom_token_cache_path(username))
    return {"ok": True, "deleted": profile_name}


def toggle_infinite_web_profile_pause(username: str, profile_name: str) -> dict[str, Any]:
    if profile_name == "default":
        raise ValueError("default 프로필은 산출 중단 대상에서 제외됩니다.")
    current = _infinite_setting_from_data(
        infinite_profile_detail(username, profile_name).get("profile") or {"name": profile_name}
    )
    setting = replace(current, calculation_paused=not current.calculation_paused)
    _write_infinite_profile_json(username, setting)
    con = _connect_writable(user_db_path(username))
    try:
        _save_infinite_setting_to_user_db(con, setting)
    finally:
        con.close()
    data = asdict(setting)
    data["start_date"] = setting.start_date.isoformat()
    return data


def _next_infinite_execution_input(
    con: duckdb.DuckDBPyConnection, setting: InfiniteSetting
) -> dict[str, Any]:
    today = date.today()
    required_day = previous_us_trading_day(today - timedelta(days=1))
    row = con.execute(
        """
        SELECT max(trade_date)
        FROM infinite_rows
        WHERE setting_name = ? AND avg_price IS NOT NULL
        """,
        [setting.name],
    ).fetchone()
    latest = row[0] if row and row[0] is not None else None
    if latest is not None and latest >= required_day:
        saved = con.execute(
            """
            SELECT trade_date, avg_price, buy_qty, sell_qty, cash_flow_amount
            FROM infinite_rows
            WHERE setting_name = ? AND trade_date = ?
            """,
            [setting.name, latest],
        ).fetchone()
        if saved:
            return {
                "trade_date": _json_value(saved[0]),
                "avg_price": _json_value(saved[1]),
                "buy_qty": int(saved[2] or 0),
                "sell_qty": int(saved[3] or 0),
                "cash_flow_amount": float(saved[4] or 0.0),
                "allowed": False,
            }
    trade_date = required_day
    if latest is not None:
        trade_date = min(required_day, next_us_trading_day(latest + timedelta(days=1)))
    if trade_date < setting.start_date:
        trade_date = next_us_trading_day(setting.start_date)
    return {
        "trade_date": trade_date.isoformat(),
        "avg_price": "",
        "buy_qty": 0,
        "sell_qty": 0,
        "cash_flow_amount": 0,
        "allowed": bool(not setting.calculation_paused and setting.start_date <= trade_date < today),
    }


def save_infinite_web_execution(
    username: str, profile_name: str, payload: dict[str, Any]
) -> dict[str, Any]:
    setting = _infinite_setting_from_data(
        infinite_profile_detail(username, profile_name).get("profile") or {"name": profile_name}
    )
    trade_date = date.fromisoformat(str(payload.get("trade_date") or "").strip())
    con = _connect_writable(user_db_path(username))
    try:
        _save_infinite_setting_to_user_db(con, setting)
        save_infinite_execution(
            con,
            setting,
            trade_date,
            float(_payload_value(payload, "avg_price", 0)),
            int(_payload_value(payload, "buy_qty", 0)),
            int(_payload_value(payload, "sell_qty", 0)),
            float(_payload_value(payload, "cash_flow_amount", 0)),
        )
        generate_infinite_rows(con, setting, through=max(setting.start_date, date.today()))
    finally:
        con.close()
    auto_result = _auto_send_infinite_telegram_order(username, setting)
    detail = infinite_profile_detail(username, profile_name)
    detail["telegram_auto"] = auto_result
    return detail


def infinite_profile_detail(username: str, profile_name: str) -> dict[str, Any]:
    base_dir = user_data_dir(username)
    db_path = user_db_path(username)
    profile = _read_profile_file(base_dir, "infinite", profile_name)
    detail: dict[str, Any] = {
        "profile": profile,
        "rows": [],
        "order_plan": None,
        "execution_input": None,
        "order_executable": False,
        "order_reorderable": False,
        "order_date": "",
        "order_message": "",
        "order_executions": [],
    }
    con = _connect_readonly(db_path)
    if con is None:
        return detail
    try:
        tables = _tables(con)
        if "infinite_settings" in tables:
            rows = _query_dicts(
                con,
                """
                SELECT
                    profile_no,
                    name,
                    symbol,
                    start_date,
                    initial_principal,
                    initial_cumulative_amount,
                    initial_cumulative_qty,
                    target_rate,
                    split_count,
                    fee_rate,
                    mode,
                    account_number,
                    calculation_paused
                FROM infinite_settings
                WHERE name = ?
                LIMIT 1
                """,
                (profile_name,),
            )
            if rows:
                detail["profile"] = {**profile, **rows[0]}
        if "infinite_rows" in tables:
            detail["rows"] = _query_dicts(
                con,
                """
                SELECT
                    trade_date,
                    weekday,
                    close_price,
                    avg_price,
                    buy_qty,
                    sell_qty,
                    trade_qty,
                    cumulative_qty,
                    t_value,
                    star_price,
                    return_rate,
                    trade_amount,
                    cumulative_amount,
                    withdrawal_amount,
                    principal_after_withdrawal
                FROM infinite_rows
                WHERE setting_name = ?
                ORDER BY trade_date DESC
                LIMIT 160
                """,
                (profile_name,),
            )
        if detail["profile"]:
            try:
                setting = _infinite_setting_from_data(detail["profile"])
                detail["execution_input"] = _next_infinite_execution_input(con, setting)
                plan = infinite_order_plan(con, setting)
                basis = order_basis_row(con, setting)
                detail["order_plan"] = {
                    "title": plan.get("title") or "",
                    "per_buy_amount": _json_value(plan.get("per_buy_amount")),
                    "buy": [
                        {key: _json_value(value) for key, value in row.items()}
                        for row in plan.get("buy", [])
                    ],
                    "sell": [
                        {key: _json_value(value) for key, value in row.items()}
                        for row in plan.get("sell", [])
                    ],
                }
                if basis is not None:
                    basis_date = basis["trade_date"]
                    if isinstance(basis_date, str):
                        basis_date = date.fromisoformat(basis_date)
                    has_orders = bool(plan.get("buy") or plan.get("sell"))
                    sent_count = _successful_order_execution_count(
                        con, "infinite", profile_name, basis_date
                    )
                    detail["order_executions"] = _recent_order_execution_rows(
                        con, "infinite", profile_name, basis_date
                    )
                    if detail["order_executions"]:
                        try:
                            verify_credentials = load_kiwoom_credentials(
                                "infinite", profile_name, kiwoom_credentials_path(username)
                            )
                            verify_token, _ = _ensure_user_kiwoom_token(
                                username, "infinite", profile_name, verify_credentials
                            )
                            verify_stex_tp = _resolve_user_exchange_code(
                                verify_credentials, verify_token, setting.symbol
                            )
                            detail["order_executions"] = _verify_order_execution_rows(
                                detail["order_executions"],
                                verify_credentials,
                                verify_token,
                                order_date=basis_date,
                                stex_tp=verify_stex_tp,
                                symbol=setting.symbol,
                            )
                        except Exception as exc:
                            detail["order_history_warning"] = f"키움 주문내역 검증 실패: {exc}"
                    detail["order_date"] = basis_date.isoformat()
                    detail["order_executable"] = bool(
                        basis_date == date.today() and has_orders and sent_count == 0
                    )
                    detail["order_reorderable"] = bool(
                        basis_date == date.today() and has_orders and sent_count > 0
                    )
                    detail["order_message"] = f"주문표 날짜: {basis_date}"
                    if sent_count:
                        detail["order_message"] = (
                            f"{basis_date} 주문실행 이력 {sent_count}건"
                        )
            except Exception as exc:
                detail["order_error"] = str(exc)
    finally:
        con.close()
    return detail


def list_kiwoom_credentials(username: str) -> dict[str, Any]:
    path = kiwoom_credentials_path(username)
    store = load_kiwoom_credentials_store(path)
    result: dict[str, Any] = {"vr": {}, "infinite": {}}
    for kind, profiles in store.items():
        result.setdefault(kind, {})
        for profile_name, raw in profiles.items():
            app_secret = str(raw.get("app_secret") or "")
            result[kind][profile_name] = {
                "investment_type": raw.get("investment_type", "실전투자"),
                "account_number": raw.get("account_number", ""),
                "app_key": raw.get("app_key", ""),
                "app_secret": "",
                "app_secret_masked": _mask_secret(app_secret),
                "has_app_secret": bool(app_secret),
                "expires_at": raw.get("expires_at", ""),
                "memo": raw.get("memo", ""),
            }
    return result


def get_kiwoom_credentials(username: str, kind: str, profile_name: str) -> dict[str, Any]:
    credentials = load_kiwoom_credentials(kind, profile_name, kiwoom_credentials_path(username))
    data = asdict(credentials)
    app_secret = data.pop("app_secret", "")
    data["app_secret"] = ""
    data["app_secret_masked"] = _mask_secret(app_secret)
    data["has_app_secret"] = bool(app_secret)
    return data


def put_kiwoom_credentials(
    username: str, kind: str, profile_name: str, payload: dict[str, Any]
) -> dict[str, Any]:
    path = kiwoom_credentials_path(username)
    existing = load_kiwoom_credentials(kind, profile_name, path)
    app_secret = str(payload.get("app_secret") or "").strip() or existing.app_secret
    credentials = KiwoomCredentials(
        investment_type=str(payload.get("investment_type") or "실전투자"),
        account_number=str(payload.get("account_number") or ""),
        app_key=str(payload.get("app_key") or ""),
        app_secret=app_secret,
        expires_at=str(payload.get("expires_at") or ""),
        memo=str(payload.get("memo") or ""),
    )
    save_kiwoom_credentials(kind, profile_name, credentials, path)
    return get_kiwoom_credentials(username, kind, profile_name)


def test_kiwoom_token(username: str, kind: str, profile_name: str) -> dict[str, Any]:
    credentials = load_kiwoom_credentials(kind, profile_name, kiwoom_credentials_path(username))
    try:
        token = issue_access_token(credentials)
        save_profile_token(kind, profile_name, token, kiwoom_token_cache_path(username))
        return {
            "ok": True,
            "message": f"토큰 발급 성공: 만료 {token.expires_dt or '-'} / {token.return_msg or '정상'}",
            "expires_dt": token.expires_dt,
            "return_code": token.return_code,
            "return_msg": token.return_msg or "정상",
        }
    except KiwoomApiError as exc:
        details = []
        if exc.status_code is not None:
            details.append(f"HTTP {exc.status_code}")
        if exc.return_code is not None:
            details.append(f"return_code {exc.return_code}")
        if exc.return_msg:
            details.append(exc.return_msg)
        if exc.response_preview:
            details.append(f"response {exc.response_preview}")
        error_text = str(exc)
        if error_text and error_text not in details:
            details.append(error_text)
        return {
            "ok": False,
            "message": "토큰 발급 실패" + (": " + " / ".join(details) if details else ""),
            "return_code": exc.return_code,
            "return_msg": exc.return_msg,
        }


def lookup_infinite_balance(username: str, profile_name: str) -> dict[str, Any]:
    credentials = load_kiwoom_credentials(
        "infinite", profile_name, kiwoom_credentials_path(username)
    )
    try:
        token, renewed = _ensure_user_kiwoom_token(
            username, "infinite", profile_name, credentials
        )
        result = request_us_ledger_balance(credentials, token)
        rows = result.get("result_list")
        row_count = len(rows) if isinstance(rows, list) else 0
        token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
        summary = {
            "profile": profile_name,
            "account_number": credentials.account_number,
            "token": {
                "state": token_state,
                "expires_dt": token.expires_dt,
            },
            "balance": {
                "row_count": row_count,
                "return_code": result.get("return_code"),
                "return_msg": result.get("return_msg"),
            },
            "response": result,
        }
        return {
            "ok": True,
            "profile": profile_name,
            "row_count": row_count,
            "token_renewed": renewed,
            "summary": summary,
            "message": f"조회 성공: {row_count}건 / {token_state}",
        }
    except KiwoomApiError as exc:
        return {
            "ok": False,
            "message": _format_kiwoom_error("잔고조회 실패", exc),
            "return_code": exc.return_code,
            "return_msg": exc.return_msg,
        }


def _ensure_user_kiwoom_token(
    username: str, kind: str, profile_name: str, credentials: KiwoomCredentials
) -> tuple[Any, bool]:
    path = kiwoom_token_cache_path(username)
    token = load_profile_token(kind, profile_name, path)
    if token and is_token_valid_for_credentials(token, credentials):
        return token, False
    token = issue_access_token(credentials)
    save_profile_token(kind, profile_name, token, path)
    return token, True


def _resolve_user_exchange_code(credentials: KiwoomCredentials, token: Any, symbol: str) -> str:
    try:
        return resolve_us_stock_exchange_code(credentials, token, symbol)
    except Exception:
        return default_us_stock_exchange_code(symbol)


def _kiwoom_order_type_code(side: str, order_type: str) -> str:
    normalized = str(order_type or "").strip().upper()
    if normalized == "LOC":
        return "30"
    if normalized == "MOC" and side == "sell":
        return "33"
    if str(order_type or "").strip() == "지정가" or normalized in ("LIMIT", "00"):
        return "00"
    raise ValueError(f"지원하지 않는 주문 종류입니다: {order_type}")


def _vr_api_order_rows(profile: Profile, basis: dict, stex_tp: str) -> list[dict[str, Any]]:
    quantity_step = int(profile.quantity_step or 1)
    rows = order_level_values(profile, basis, quantity_step=quantity_step)
    order_rows: list[dict[str, Any]] = []
    for source in rows:
        side = "buy" if source.get("side") == "BUY" else "sell"
        quantity = int(source.get("quantity_step") or quantity_step)
        if quantity <= 0:
            continue
        price = round(float(source["price"]), 2)
        order_rows.append(
            {
                "side": side,
                "side_label": "매수" if side == "buy" else "매도",
                "symbol": profile.symbol.upper(),
                "stex_tp": stex_tp,
                "order_type": "지정가",
                "trde_tp": "00",
                "price": price,
                "price_key": _price_key(price),
                "quantity": quantity,
                "level_no": int(source.get("level_no") or 0),
            }
        )
    return order_rows


def _infinite_api_order_rows(
    setting: InfiniteSetting, plan: dict[str, Any], stex_tp: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group, side in (("buy", "buy"), ("sell", "sell")):
        for item in plan.get(group, []):
            quantity = int(item.get("quantity") or 0)
            if quantity <= 0:
                continue
            order_type = str(item.get("order_type") or "").strip()
            trde_tp = _kiwoom_order_type_code(side, order_type)
            price = item.get("price")
            if trde_tp in ("00", "30") and price is None:
                raise ValueError(f"{order_type} 주문은 가격이 필요합니다.")
            rows.append(
                {
                    "side": side,
                    "side_label": "매수" if side == "buy" else "매도",
                    "symbol": setting.symbol.upper(),
                    "stex_tp": stex_tp,
                    "order_type": order_type,
                    "trde_tp": trde_tp,
                    "price": None if trde_tp == "33" else price,
                    "quantity": quantity,
                }
            )
    return rows


def _apply_vr_fill_exclusions(
    order_rows: list[dict[str, Any]], fill_summary: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    fill_remaining: dict[tuple[str, str], int] = {}
    fill_amounts: dict[tuple[str, str], float] = {}
    for fill in fill_summary:
        side = str(fill.get("side") or "")
        price = _price_key(fill.get("price"))
        if not side or not price:
            continue
        key = (side, price)
        fill_remaining[key] = fill_remaining.get(key, 0) + int(fill.get("quantity") or 0)
        fill_amounts[key] = fill_amounts.get(key, 0.0) + float(fill.get("amount") or 0)

    remaining_rows: list[dict[str, Any]] = []
    deducted_rows: list[dict[str, Any]] = []
    for row in order_rows:
        key = (row["side"], row["price_key"])
        quantity = int(row["quantity"])
        deducted = min(quantity, fill_remaining.get(key, 0))
        if deducted:
            fill_remaining[key] -= deducted
            deducted_rows.append({**row, "deducted_quantity": deducted})
        remaining = quantity - deducted
        if remaining > 0:
            remaining_rows.append({**row, "quantity": remaining, "deducted_quantity": deducted})

    unmatched_fills: list[dict[str, Any]] = []
    for (side, price), quantity in fill_remaining.items():
        if quantity <= 0:
            continue
        unmatched_fills.append(
            {
                "side": side,
                "side_label": "매수" if side == "buy" else "매도",
                "price": price,
                "quantity": quantity,
                "amount": fill_amounts.get((side, price), 0.0),
            }
        )
    return remaining_rows, deducted_rows, unmatched_fills


def _normalize_vr_sell_order_mode(
    sell_mode: str = "match_buy", sell_row_count: int | None = None
) -> tuple[str, int | None]:
    mode = str(sell_mode or "match_buy").strip()
    if mode != "manual":
        return "match_buy", None
    try:
        count = int(sell_row_count or 0)
    except (TypeError, ValueError):
        count = 0
    return "manual", max(0, count)


def _filter_vr_sell_order_rows(
    order_rows: list[dict[str, Any]],
    sell_mode: str = "match_buy",
    sell_row_count: int | None = None,
) -> list[dict[str, Any]]:
    mode, manual_count = _normalize_vr_sell_order_mode(sell_mode, sell_row_count)
    buy_rows = [row for row in order_rows if str(row.get("side") or "") == "buy"]
    sell_rows = [row for row in order_rows if str(row.get("side") or "") == "sell"]
    sell_limit = manual_count if mode == "manual" else len(buy_rows)
    return buy_rows + sell_rows[: max(0, min(len(sell_rows), int(sell_limit or 0)))]


def _order_rows_side_summary(rows: list[dict[str, Any]], quantity_key: str = "quantity") -> dict[str, int]:
    summary = {"buy_count": 0, "buy_qty": 0, "sell_count": 0, "sell_qty": 0}
    for row in rows:
        side = str(row.get("side") or "")
        quantity = int(row.get(quantity_key) or 0)
        if quantity <= 0:
            continue
        if side == "buy":
            summary["buy_count"] += 1
            summary["buy_qty"] += quantity
        elif side == "sell":
            summary["sell_count"] += 1
            summary["sell_qty"] += quantity
    return summary


def _vr_match_buy_order_count(order_rows: list[dict[str, Any]]) -> int:
    buy_count = 0
    sell_count = 0
    for row in order_rows:
        side = str(row.get("side") or "").strip().lower()
        if side == "buy":
            buy_count += 1
        elif side == "sell":
            sell_count += 1
    return buy_count + min(buy_count, sell_count)


def _execute_us_order_rows(
    credentials: KiwoomCredentials,
    token: Any,
    order_rows: list[dict[str, Any]],
    log_con: duckdb.DuckDBPyConnection | None = None,
    strategy: str = "",
    profile_name: str = "",
    order_date: date | None = None,
) -> list[str]:
    successes: list[str] = []
    for index, row in enumerate(order_rows, start=1):
        kwargs = {
            "stex_tp": row["stex_tp"],
            "stk_cd": row["symbol"],
            "ord_qty": row["quantity"],
            "ord_uv": row["price"],
            "trde_tp": row["trde_tp"],
        }
        try:
            if row["side"] == "buy":
                result = request_us_buy_order(credentials, token, **kwargs)
            else:
                result = request_us_sell_order(credentials, token, stop_pric=None, **kwargs)
        except Exception as exc:
            if log_con is not None and order_date is not None and strategy and profile_name:
                _record_order_execution(
                    log_con,
                    strategy,
                    profile_name,
                    order_date,
                    row,
                    "failed",
                    None,
                    _order_failure_message(exc),
                )
            raise
        ord_no = str(result.get("ord_no") or result.get("odno") or "").strip()
        price = "시장가" if row.get("price") is None else _clean_number_text(row.get("price"))
        if not ord_no:
            message = str(result.get("return_msg") or "").strip()
            if not message:
                message = "키움 주문 응답에 주문번호가 없어 접수 실패로 처리했습니다."
            if log_con is not None and order_date is not None and strategy and profile_name:
                _record_order_execution(
                    log_con,
                    strategy,
                    profile_name,
                    order_date,
                    row,
                    "failed",
                    result,
                    message,
                )
            continue
        message = (
            f"{index}. {row['side_label']} {row['quantity']}주 "
            f"{price} {row.get('order_type') or ''} 주문번호 {ord_no}"
        )
        if log_con is not None and order_date is not None and strategy and profile_name:
            _record_order_execution(
                log_con,
                strategy,
                profile_name,
                order_date,
                row,
                "sent",
                result,
                message,
            )
        successes.append(message)
    return successes


def lookup_infinite_execution_preview(username: str, profile_name: str) -> dict[str, Any]:
    credentials = load_kiwoom_credentials(
        "infinite", profile_name, kiwoom_credentials_path(username)
    )
    setting = _infinite_setting_from_data(
        infinite_profile_detail(username, profile_name).get("profile") or {"name": profile_name}
    )
    symbol = setting.symbol.upper()
    try:
        token, renewed = _ensure_user_kiwoom_token(
            username, "infinite", profile_name, credentials
        )
        stex_tp = _resolve_user_exchange_code(credentials, token, symbol)
        end_day = date.today()
        start_day = end_day - timedelta(days=30)
        balance = request_us_ledger_balance(credentials, token, stex_tp=stex_tp, stk_cd=symbol)
        orders = request_us_period_order_history(
            credentials,
            token,
            start_date=start_day.strftime("%Y%m%d"),
            end_date=end_day.strftime("%Y%m%d"),
            slby_tp="0",
            stex_tp=stex_tp,
            stk_cd=symbol,
            oppo_trde_tp="%",
        )
        balance_row = _find_symbol_row(_result_rows(balance), symbol)
        order_summary = _summarize_last_order_day(_result_rows(orders), symbol)
        avg_price = _first_row_value(balance_row, "frgn_stk_book_uv", "prch_uv", "avg_pric")
        preview = {
            "trade_date": _format_api_date(order_summary["last_trade_date"]),
            "avg_price": _clean_number_text(avg_price) if avg_price else "",
            "buy_qty": order_summary["buy_qty"],
            "sell_qty": order_summary["sell_qty"],
        }
        token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
        no_fills = bool(orders.get("_meta", {}).get("empty_result"))
        return {
            "ok": True,
            "profile": profile_name,
            "symbol": symbol,
            "stex_tp": stex_tp,
            "query_range": {
                "start_date": start_day.strftime("%Y%m%d"),
                "end_date": end_day.strftime("%Y%m%d"),
            },
            "token_renewed": renewed,
            "preview": preview,
            "message": (
                f"조회 성공: {symbol} / 마지막 체결일 {preview['trade_date'] or '-'}"
                f" / {token_state}"
                + (" / no fills" if no_fills else "")
            ),
        }
    except KiwoomApiError as exc:
        return {
            "ok": False,
            "message": _format_kiwoom_error("체결입력정보 조회 실패", exc),
            "return_code": exc.return_code,
            "return_msg": exc.return_msg,
        }


def lookup_vr_fill_history(
    username: str, profile_name: str, period_kind: str = "current"
) -> dict[str, Any]:
    credentials = load_kiwoom_credentials("vr", profile_name, kiwoom_credentials_path(username))
    profile_data = _read_profile_file(user_data_dir(username), "vr", profile_name)
    profile = _profile_from_data(profile_data)
    symbol = profile.symbol.upper()
    try:
        query_day = date.today()
        cycle_no, dates = _vr_fill_lookup_period(profile, query_day, period_kind)
        start_day = dates.result_start
        end_day = min(query_day, dates.result_end) if period_kind == "current" else dates.result_end
        if end_day < start_day:
            raise ValueError("조회 가능한 VR 주문구간이 아직 시작되지 않았습니다.")
        token, renewed = _ensure_user_kiwoom_token(username, "vr", profile_name, credentials)
        stex_tp = _resolve_user_exchange_code(credentials, token, symbol)
        orders = request_us_period_order_history(
            credentials,
            token,
            start_date=start_day.strftime("%Y%m%d"),
            end_date=end_day.strftime("%Y%m%d"),
            slby_tp="0",
            stex_tp=stex_tp,
            stk_cd=symbol,
            oppo_trde_tp="%",
        )
        fills = _vr_fill_history_rows(_result_rows(orders), symbol)
        summary = _vr_fill_price_summary(fills)
        period_label = "현재차수" if period_kind == "current" else "지난차수"
        token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
        return {
            "ok": True,
            "profile": profile_name,
            "symbol": symbol,
            "stex_tp": stex_tp,
            "cycle_no": cycle_no,
            "period_kind": period_kind,
            "period_label": period_label,
            "order_period": {
                "start_date": start_day.isoformat(),
                "end_date": dates.result_end.isoformat(),
                "query_end_date": end_day.isoformat(),
            },
            "fills": fills,
            "summary": summary,
            "message": f"{period_label} 조회 성공: {symbol} / 체결 {len(fills)}건 / {token_state}",
        }
    except KiwoomApiError as exc:
        return {
            "ok": False,
            "message": _format_kiwoom_error("VR 체결내역 조회 실패", exc),
            "return_code": exc.return_code,
            "return_msg": exc.return_msg,
        }


def _build_vr_period_preview(
    symbol: str, orders: dict, balance: dict, after_orders: dict
) -> dict[str, Any]:
    order_summary = _summarize_order_period(_result_rows(orders), symbol)
    after_order_summary = _summarize_order_period(_result_rows(after_orders), symbol)
    balance_row = _find_symbol_row(_result_rows(balance), symbol)
    holding_qty = _clean_int(
        _first_row_value(balance_row, "poss_qty", "qty", "evlt_qty")
    )
    period_end_holding_qty = (
        holding_qty
        - int(after_order_summary["buy_qty"])
        + int(after_order_summary["sell_qty"])
    )
    return {
        "sell_qty": order_summary["sell_qty"],
        "sell_amount": _clean_number_text(round(float(order_summary["sell_amount"]), 4)),
        "buy_qty": order_summary["buy_qty"],
        "buy_amount": _clean_number_text(round(float(order_summary["buy_amount"]), 4)),
        "holding_qty": holding_qty,
        "period_end_holding_qty": period_end_holding_qty,
    }


def lookup_vr_period_preview(username: str, profile_name: str) -> dict[str, Any]:
    credentials = load_kiwoom_credentials("vr", profile_name, kiwoom_credentials_path(username))
    profile_data = _read_profile_file(user_data_dir(username), "vr", profile_name)
    profile = _profile_from_data(profile_data)
    symbol = profile.symbol.upper()
    query_day = date.today()
    try:
        cycle_no, dates = _latest_completed_vr_result_period(profile, query_day)
        token, renewed = _ensure_user_kiwoom_token(username, "vr", profile_name, credentials)
        stex_tp = _resolve_user_exchange_code(credentials, token, symbol)
        orders = request_us_period_order_history(
            credentials,
            token,
            start_date=dates.result_start.strftime("%Y%m%d"),
            end_date=dates.result_end.strftime("%Y%m%d"),
            slby_tp="0",
            stex_tp=stex_tp,
            stk_cd=symbol,
            oppo_trde_tp="%",
        )
        balance = request_us_ledger_balance(
            credentials, token, stex_tp=stex_tp, stk_cd=symbol
        )
        after_start_day = dates.result_end + timedelta(days=1)
        after_orders = request_us_period_order_history(
            credentials,
            token,
            start_date=after_start_day.strftime("%Y%m%d"),
            end_date=query_day.strftime("%Y%m%d"),
            slby_tp="0",
            stex_tp=stex_tp,
            stk_cd=symbol,
            oppo_trde_tp="%",
        )
        preview = _build_vr_period_preview(symbol, orders, balance, after_orders)
        token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
        return {
            "ok": True,
            "profile": profile_name,
            "symbol": symbol,
            "stex_tp": stex_tp,
            "cycle_no": cycle_no,
            "result_period": {
                "start_date": dates.result_start.isoformat(),
                "end_date": dates.result_end.isoformat(),
            },
            "after_period": {
                "start_date": after_start_day.isoformat(),
                "end_date": query_day.isoformat(),
            },
            "token_renewed": renewed,
            "preview": preview,
            "message": (
                f"조회 성공: {symbol} / 기준일 {query_day} / "
                f"대상 {dates.result_start}~{dates.result_end} / {token_state}"
            ),
        }
    except KiwoomApiError as exc:
        return {
            "ok": False,
            "message": _format_kiwoom_error("VR 결과구간 조회 실패", exc),
            "return_code": exc.return_code,
            "return_msg": exc.return_msg,
        }


def preview_vr_web_orders(
    username: str,
    profile_name: str,
    sell_mode: str = "match_buy",
    sell_row_count: int | None = None,
) -> dict[str, Any]:
    credentials = load_kiwoom_credentials("vr", profile_name, kiwoom_credentials_path(username))
    profile_data = _read_profile_file(user_data_dir(username), "vr", profile_name)
    profile = _profile_from_data(profile_data)
    query_day = date.today()
    mode, manual_count = _normalize_vr_sell_order_mode(sell_mode, sell_row_count)
    con = _connect_readonly(user_db_path(username))
    if con is None:
        return {"ok": False, "message": "VR 주문표 미리보기 실패: 데이터베이스가 없습니다."}
    try:
        basis = order_basis_for_next_cycle(con, profile)
    finally:
        con.close()
    if basis is None:
        return {"ok": False, "message": "VR 주문표 미리보기 실패: 주문 기준 행이 없습니다."}
    start_day = date.fromisoformat(str(basis["start_date"]))
    end_day = date.fromisoformat(str(basis["end_date"]))
    if not (start_day <= query_day <= end_day):
        return {
            "ok": False,
            "message": f"VR 주문표 미리보기 실패: 주문 실행일 {query_day}가 주문표 기간에 포함되지 않습니다. 주문표 기간: {start_day}~{end_day}",
        }
    try:
        token, renewed = _ensure_user_kiwoom_token(username, "vr", profile_name, credentials)
        stex_tp = _resolve_user_exchange_code(credentials, token, profile.symbol)
        order_rows = _vr_api_order_rows(profile, basis, stex_tp)
        orders = request_us_period_order_history(
            credentials,
            token,
            start_date=start_day.strftime("%Y%m%d"),
            end_date=query_day.strftime("%Y%m%d"),
            slby_tp="0",
            stex_tp=stex_tp,
            stk_cd=profile.symbol.upper(),
            oppo_trde_tp="%",
        )
        fill_rows = _vr_fill_history_rows(_result_rows(orders), profile.symbol)
        fill_summary = _vr_fill_price_summary(fill_rows)
        remaining_rows, deducted_rows, unmatched_fills = _apply_vr_fill_exclusions(
            order_rows, fill_summary
        )
        execution_rows = _filter_vr_sell_order_rows(remaining_rows, mode, manual_count)
        original_summary = _order_rows_side_summary(order_rows)
        deducted_summary = _order_rows_side_summary(deducted_rows, "deducted_quantity")
        remaining_summary = _order_rows_side_summary(remaining_rows)
        execution_summary = _order_rows_side_summary(execution_rows)
        token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
        option_text = (
            f"매도행 직접설정 {manual_count}행"
            if mode == "manual"
            else "매수 행에 맞춰 주문"
        )
        return {
            "ok": True,
            "profile": profile_name,
            "symbol": profile.symbol.upper(),
            "order_date": query_day.isoformat(),
            "order_period": {
                "start_date": start_day.isoformat(),
                "end_date": end_day.isoformat(),
            },
            "option": {
                "sell_mode": mode,
                "sell_row_count": manual_count,
                "label": option_text,
            },
            "summary": {
                "original": original_summary,
                "deducted": deducted_summary,
                "remaining": remaining_summary,
                "execution": execution_summary,
            },
            "order_rows": execution_rows,
            "deducted": deducted_rows,
            "unmatched_fills": unmatched_fills,
            "fills": fill_rows,
            "token_renewed": renewed,
            "message": (
                f"VR 주문표 미리보기 완료: {profile.symbol.upper()} / {option_text} / "
                f"주문 {len(execution_rows)}건 / {token_state}"
            ),
        }
    except KiwoomApiError as exc:
        return {
            "ok": False,
            "message": _format_kiwoom_error("VR 주문표 미리보기 실패", exc),
            "return_code": exc.return_code,
            "return_msg": exc.return_msg,
        }
    except Exception as exc:
        return {"ok": False, "message": f"VR 주문표 미리보기 실패: {exc}"}


def execute_vr_web_orders(
    username: str,
    profile_name: str,
    sell_mode: str = "match_buy",
    sell_row_count: int | None = None,
    force_reorder: bool = False,
) -> dict[str, Any]:
    credentials = load_kiwoom_credentials("vr", profile_name, kiwoom_credentials_path(username))
    profile_data = _read_profile_file(user_data_dir(username), "vr", profile_name)
    profile = _profile_from_data(profile_data)
    query_day = date.today()
    mode, manual_count = _normalize_vr_sell_order_mode(sell_mode, sell_row_count)
    con = _connect_readonly(user_db_path(username))
    if con is None:
        return {"ok": False, "message": "VR 주문실행 실패: 데이터베이스가 없습니다."}
    try:
        basis = order_basis_for_next_cycle(con, profile)
    finally:
        con.close()
    if basis is None:
        return {"ok": False, "message": "VR 주문실행 실패: 주문 기준 행이 없습니다."}
    start_day = date.fromisoformat(str(basis["start_date"]))
    end_day = date.fromisoformat(str(basis["end_date"]))
    if not (start_day <= query_day <= end_day):
        return {
            "ok": False,
            "message": f"VR 주문실행 실패: 주문 실행일 {query_day}가 주문표 기간에 포함되지 않습니다. 주문표 기간: {start_day}~{end_day}",
        }
    duplicate_con = _connect_writable(user_db_path(username))
    try:
        _ensure_order_execution_table(duplicate_con)
        sent_count = _successful_order_execution_count(
            duplicate_con, "vr", profile_name, query_day
        )
        if sent_count and not force_reorder:
            sent_rows = _recent_order_execution_rows(
                duplicate_con, "vr", profile_name, query_day
            )
            return {
                "ok": False,
                "message": f"VR 주문실행 중단: {query_day} 주문실행 이력 {sent_count}건이 있습니다.",
                "order_executions": sent_rows,
            }
    finally:
        duplicate_con.close()
    try:
        token, renewed = _ensure_user_kiwoom_token(username, "vr", profile_name, credentials)
        stex_tp = _resolve_user_exchange_code(credentials, token, profile.symbol)
        order_rows = _vr_api_order_rows(profile, basis, stex_tp)
        if not order_rows:
            return {"ok": False, "message": "VR 주문실행 실패: 실행할 주문이 없습니다."}
        orders = request_us_period_order_history(
            credentials,
            token,
            start_date=start_day.strftime("%Y%m%d"),
            end_date=query_day.strftime("%Y%m%d"),
            slby_tp="0",
            stex_tp=stex_tp,
            stk_cd=profile.symbol.upper(),
            oppo_trde_tp="%",
        )
        fill_rows = _vr_fill_history_rows(_result_rows(orders), profile.symbol)
        fill_summary = _vr_fill_price_summary(fill_rows)
        remaining_rows, deducted_rows, unmatched_fills = _apply_vr_fill_exclusions(
            order_rows, fill_summary
        )
        execution_rows = _filter_vr_sell_order_rows(remaining_rows, mode, manual_count)
        if not execution_rows:
            return {
                "ok": True,
                "message": "현재차수 체결 차감 후 전송할 주문이 없습니다.",
                "successes": [],
                "deducted": deducted_rows,
                "unmatched_fills": unmatched_fills,
                "fills": fill_rows,
            }
        log_con = _connect_writable(user_db_path(username))
        try:
            _ensure_order_execution_table(log_con)
            sent_count = _successful_order_execution_count(
                log_con, "vr", profile_name, query_day
            )
            if sent_count and not force_reorder:
                return {
                    "ok": False,
                    "message": f"VR 주문실행 중단: {query_day} 주문실행 이력 {sent_count}건이 있습니다.",
                    "order_executions": _recent_order_execution_rows(
                        log_con, "vr", profile_name, query_day
                    ),
                }
            successes = _execute_us_order_rows(
                credentials,
                token,
                execution_rows,
                log_con=log_con,
                strategy="vr",
                profile_name=profile_name,
                order_date=query_day,
            )
        finally:
            log_con.close()
        original_summary = _order_rows_side_summary(order_rows)
        deducted_summary = _order_rows_side_summary(deducted_rows, "deducted_quantity")
        remaining_summary = _order_rows_side_summary(remaining_rows)
        execution_summary = _order_rows_side_summary(execution_rows)
        token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
        action_label = "VR 재주문" if force_reorder else "VR 주문실행"
        order_executions = _order_executions_for_response(
            username, "vr", profile_name, query_day
        )
        try:
            order_executions = _verify_order_execution_rows(
                order_executions,
                credentials,
                token,
                order_date=query_day,
                stex_tp=stex_tp,
                symbol=profile.symbol,
            )
        except Exception:
            pass
        failed_count = sum(
            1
            for row in order_executions
            if str(row.get("status") or "") == "failed"
        )
        ok = bool(successes)
        result_label = "완료" if ok else "실패"
        return {
            "ok": ok,
            "message": (
                f"{action_label} {result_label}: 성공 {len(successes)}건 / 실패 {failed_count}건 "
                f"/ 주문 실행일 {query_day} / {token_state}"
            ),
            "successes": successes,
            "order_executions": order_executions,
            "order_date": query_day.isoformat(),
            "summary": {
                "original": original_summary,
                "deducted": deducted_summary,
                "remaining": remaining_summary,
                "execution": execution_summary,
            },
            "order_rows": execution_rows,
            "deducted": deducted_rows,
            "unmatched_fills": unmatched_fills,
            "fills": fill_rows,
        }
    except KiwoomApiError as exc:
        return {
            "ok": False,
            "message": _format_kiwoom_error("VR 주문실행 실패", exc),
            "return_code": exc.return_code,
            "return_msg": exc.return_msg,
            "order_executions": _order_executions_for_response(
                username, "vr", profile_name, query_day
            ),
        }
    except Exception as exc:
        return {"ok": False, "message": f"VR 주문실행 실패: {exc}"}


def execute_infinite_web_orders(
    username: str, profile_name: str, force_reorder: bool = False
) -> dict[str, Any]:
    credentials = load_kiwoom_credentials(
        "infinite", profile_name, kiwoom_credentials_path(username)
    )
    setting = _infinite_setting_from_data(
        infinite_profile_detail(username, profile_name).get("profile") or {"name": profile_name}
    )
    con = _connect_readonly(user_db_path(username))
    if con is None:
        return {"ok": False, "message": "무한매수법 주문실행 실패: 데이터베이스가 없습니다."}
    try:
        basis = order_basis_row(con, setting)
        if basis is None:
            return {"ok": False, "message": "무한매수법 주문실행 실패: 주문 기준 행이 없습니다."}
        basis_date = basis["trade_date"]
        if isinstance(basis_date, str):
            basis_date = date.fromisoformat(basis_date)
        if basis_date != date.today():
            return {
                "ok": False,
                "message": f"무한매수법 주문실행 실패: 주문 실행일 {date.today()}에는 주문표 날짜 {basis_date}를 실행할 수 없습니다.",
            }
        plan = infinite_order_plan(con, setting)
    finally:
        con.close()
    duplicate_con = _connect_writable(user_db_path(username))
    try:
        _ensure_order_execution_table(duplicate_con)
        sent_count = _successful_order_execution_count(
            duplicate_con, "infinite", profile_name, basis_date
        )
        if sent_count and not force_reorder:
            sent_rows = _recent_order_execution_rows(
                duplicate_con, "infinite", profile_name, basis_date
            )
            return {
                "ok": False,
                "message": f"무한매수법 주문실행 중단: {basis_date} 주문실행 이력 {sent_count}건이 있습니다.",
                "order_executions": sent_rows,
            }
    finally:
        duplicate_con.close()
    try:
        token, renewed = _ensure_user_kiwoom_token(
            username, "infinite", profile_name, credentials
        )
        stex_tp = _resolve_user_exchange_code(credentials, token, setting.symbol)
        order_rows = _infinite_api_order_rows(setting, plan, stex_tp)
        if not order_rows:
            return {"ok": False, "message": "무한매수법 주문실행 실패: 실행할 주문이 없습니다."}
        log_con = _connect_writable(user_db_path(username))
        try:
            _ensure_order_execution_table(log_con)
            sent_count = _successful_order_execution_count(
                log_con, "infinite", profile_name, basis_date
            )
            if sent_count and not force_reorder:
                return {
                    "ok": False,
                    "message": f"무한매수법 주문실행 중단: {basis_date} 주문실행 이력 {sent_count}건이 있습니다.",
                    "order_executions": _recent_order_execution_rows(
                        log_con, "infinite", profile_name, basis_date
                    ),
                }
            successes = _execute_us_order_rows(
                credentials,
                token,
                order_rows,
                log_con=log_con,
                strategy="infinite",
                profile_name=profile_name,
                order_date=basis_date,
            )
        finally:
            log_con.close()
        token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
        action_label = "무한매수법 재주문" if force_reorder else "무한매수법 주문실행"
        order_executions = _order_executions_for_response(
            username, "infinite", profile_name, basis_date
        )
        try:
            order_executions = _verify_order_execution_rows(
                order_executions,
                credentials,
                token,
                order_date=basis_date,
                stex_tp=stex_tp,
                symbol=setting.symbol,
            )
        except Exception:
            pass
        failed_count = sum(
            1
            for row in order_executions
            if str(row.get("status") or "") == "failed"
        )
        ok = bool(successes)
        result_label = "완료" if ok else "실패"
        return {
            "ok": ok,
            "message": (
                f"{action_label} {result_label}: 성공 {len(successes)}건 / 실패 {failed_count}건 "
                f"/ 주문 실행일 {basis_date} / {token_state}"
            ),
            "successes": successes,
            "order_executions": order_executions,
            "order_date": basis_date.isoformat(),
        }
    except KiwoomApiError as exc:
        return {
            "ok": False,
            "message": _format_kiwoom_error("무한매수법 주문실행 실패", exc),
            "return_code": exc.return_code,
            "return_msg": exc.return_msg,
            "order_executions": _order_executions_for_response(
                username, "infinite", profile_name, basis_date
            ),
        }
    except Exception as exc:
        return {"ok": False, "message": f"무한매수법 주문실행 실패: {exc}"}


def execute_infinite_after_input_workflow(
    username: str, profile_name: str, *, source: str = "manual"
) -> dict[str, Any]:
    detail = infinite_profile_detail(username, profile_name)
    if detail.get("order_executable"):
        return {
            "ok": False,
            "skipped": True,
            "message": "이미 해당 주문표가 있어 체결입력 후 주문실행을 건너뜁니다.",
        }
    execution_input = detail.get("execution_input") or {}
    if not execution_input.get("allowed"):
        return {
            "ok": False,
            "skipped": True,
            "message": "체결입력 가능한 상태가 아닙니다.",
        }
    preview = lookup_infinite_execution_preview(username, profile_name)
    if not preview.get("ok") or not preview.get("preview"):
        return {
            "ok": False,
            "message": preview.get("message") or "체결 결과 조회에 실패했습니다.",
            "preview": preview,
        }
    preview_row = preview["preview"]
    trade_date = str(preview_row.get("trade_date") or "").strip()
    allowed_date = str(execution_input.get("trade_date") or "").strip()
    if not trade_date or trade_date == "-":
        return {"ok": False, "message": "조회 결과에 체결 입력일이 없습니다.", "preview": preview}
    if allowed_date and trade_date != allowed_date:
        return {
            "ok": False,
            "message": f"조회 입력일({trade_date})과 저장 가능한 입력일({allowed_date})이 다릅니다.",
            "preview": preview,
        }
    avg_price = float(preview_row.get("avg_price") or 0)
    if avg_price <= 0:
        return {"ok": False, "message": "조회 결과에 평균단가가 없습니다.", "preview": preview}
    save_infinite_web_execution(
        username,
        profile_name,
        {
            "trade_date": trade_date,
            "avg_price": avg_price,
            "buy_qty": int(preview_row.get("buy_qty") or 0),
            "sell_qty": int(preview_row.get("sell_qty") or 0),
            "cash_flow_amount": 0.0,
        },
    )
    order_result = execute_infinite_web_orders(username, profile_name)
    return {
        **order_result,
        "source": source,
        "preview": preview,
        "message": f"자동 체결입력 후 주문실행: {order_result.get('message') or '-'}",
    }


def _mark_infinite_schedule_attempt(
    username: str,
    profile_name: str,
    schedule: dict[str, Any],
    now: datetime,
    result: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(schedule)
    updated["last_attempt_date"] = now.date().isoformat()
    updated["last_run_at"] = now.isoformat(timespec="seconds")
    updated["last_status"] = "ok" if result.get("ok") else "failed"
    if result.get("skipped"):
        updated["last_status"] = "skipped"
    updated["last_message"] = str(result.get("message") or "")[:1000]
    return _write_infinite_schedule(username, profile_name, updated)


def run_due_infinite_schedules(
    usernames: list[str], now: datetime | None = None
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone(timedelta(hours=9)))
    today = now.date().isoformat()
    current_time = now.strftime("%H:%M")
    results: list[dict[str, Any]] = []
    for username in usernames:
        try:
            profiles = infinite_profiles(username)
        except Exception as exc:
            results.append({"ok": False, "username": username, "message": str(exc)})
            continue
        for profile in profiles:
            profile_name = str(profile.get("name") or "").strip()
            if not profile_name:
                continue
            try:
                schedule = _read_infinite_schedule(username, profile_name)
            except Exception as exc:
                results.append(
                    {
                        "ok": False,
                        "username": username,
                        "profile": profile_name,
                        "message": f"스케줄 읽기 실패: {exc}",
                    }
                )
                continue
            if not schedule.get("enabled"):
                continue
            if now.weekday() not in schedule.get("weekdays", []):
                continue
            if current_time < str(schedule.get("time") or "00:00"):
                continue
            if schedule.get("last_attempt_date") == today:
                continue
            running = {
                **schedule,
                "last_attempt_date": today,
                "last_run_at": now.isoformat(timespec="seconds"),
                "last_status": "running",
                "last_message": "자동 실행 중...",
            }
            _write_infinite_schedule(username, profile_name, running)
            try:
                result = execute_infinite_after_input_workflow(
                    username, profile_name, source="schedule"
                )
            except Exception as exc:
                result = {"ok": False, "message": f"자동 실행 실패: {exc}"}
            _mark_infinite_schedule_attempt(username, profile_name, running, now, result)
            results.append({"username": username, "profile": profile_name, **result})
    return results


def get_telegram_settings(username: str) -> dict[str, Any]:
    settings = load_telegram_settings(telegram_settings_path(username))
    data = asdict(settings)
    bot_token = data.pop("bot_token", "")
    data["bot_token"] = ""
    data["bot_token_masked"] = _mask_secret(bot_token)
    data["has_bot_token"] = bool(bot_token)
    return data


def put_telegram_settings(username: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = load_telegram_settings(telegram_settings_path(username))
    raw = asdict(current)
    for key in raw:
        if key in payload:
            raw[key] = payload[key]
    if not str(raw.get("bot_token") or "").strip():
        raw["bot_token"] = current.bot_token
    settings = TelegramSettings(
        bot_token=str(raw.get("bot_token") or ""),
        chat_id=str(raw.get("chat_id") or ""),
        auto_send_on_calculation=bool(raw.get("auto_send_on_calculation")),
        auto_send_vr_orders=bool(raw.get("auto_send_vr_orders")),
        auto_send_infinite_orders=bool(raw.get("auto_send_infinite_orders")),
        send_order_table=bool(raw.get("send_order_table")),
        order_row_limit=int(raw.get("order_row_limit") or 10),
        send_due=bool(raw.get("send_due")),
        send_dashboard=bool(raw.get("send_dashboard")),
        send_vr_summary=bool(raw.get("send_vr_summary")),
        send_infinite_summary=bool(raw.get("send_infinite_summary")),
        send_order_status=bool(raw.get("send_order_status")),
        include_paused=bool(raw.get("include_paused")),
    )
    save_telegram_settings(settings, telegram_settings_path(username))
    return get_telegram_settings(username)


def send_telegram_test_message(username: str) -> dict[str, Any]:
    settings = load_telegram_settings(telegram_settings_path(username))
    send_telegram_message(
        settings,
        f"VR Study 웹 테스트 메시지\n{datetime.now():%Y-%m-%d %H:%M:%S}",
    )
    return {"ok": True, "message": "테스트 메시지 전송 완료"}


def _telegram_money(value: Any, digits: int = 0) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):,.{digits}f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _telegram_percent(value: Any, digits: int = 2) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value) * 100:,.{digits}f}%"
    except (TypeError, ValueError):
        return str(value)


def _telegram_auto_enabled(settings: TelegramSettings, strategy: str) -> bool:
    if not settings.bot_token.strip() or not settings.chat_id.strip():
        return False
    if not settings.auto_send_on_calculation:
        return False
    if strategy == "infinite":
        return bool(settings.auto_send_infinite_orders)
    if strategy == "vr":
        return bool(settings.auto_send_vr_orders)
    return False


def _order_row_limit(settings: TelegramSettings) -> int:
    return max(1, min(50, int(settings.order_row_limit or 10)))


def _split_order_limit(buy_count: int, sell_count: int, limit: int) -> tuple[int, int]:
    if buy_count + sell_count <= limit:
        return buy_count, sell_count
    buy_limit = min(buy_count, max(1, limit // 2))
    sell_limit = min(sell_count, max(1, limit - buy_limit))
    remaining = limit - buy_limit - sell_limit
    if remaining > 0 and buy_limit < buy_count:
        extra = min(remaining, buy_count - buy_limit)
        buy_limit += extra
        remaining -= extra
    if remaining > 0 and sell_limit < sell_count:
        sell_limit += min(remaining, sell_count - sell_limit)
    return buy_limit, sell_limit


def _format_infinite_order_lines(plan: dict[str, Any], limit: int) -> list[str]:
    buy_rows = list(plan.get("buy") or [])
    sell_rows = list(plan.get("sell") or [])
    buy_limit, sell_limit = _split_order_limit(len(buy_rows), len(sell_rows), limit)
    lines: list[str] = []
    if buy_rows:
        lines.extend(["", "매수"])
        for row in buy_rows[:buy_limit]:
            price = "시장가" if row.get("price") is None else _telegram_money(row.get("price"), 2)
            lines.append(f"- {row.get('order_type')} {price} / {row.get('quantity')}주")
    if sell_rows:
        lines.extend(["", "매도"])
        for row in sell_rows[:sell_limit]:
            price = "시장가" if row.get("price") is None else _telegram_money(row.get("price"), 2)
            lines.append(f"- {row.get('order_type')} {price} / {row.get('quantity')}주")
    omitted = max(0, len(buy_rows) - buy_limit) + max(0, len(sell_rows) - sell_limit)
    if omitted:
        lines.append(f"- 외 {omitted}건")
    return lines


def build_infinite_order_telegram_message(
    username: str, setting: InfiniteSetting, settings: TelegramSettings
) -> str:
    con = _connect_readonly(user_db_path(username))
    if con is None:
        return f"[무한매수법 주문표] {_profile_label(asdict(setting))}\n주문 기준 로우가 없습니다."
    try:
        basis = order_basis_row(con, setting)
        plan = infinite_order_plan(con, setting)
    finally:
        con.close()
    lines = [f"[무한매수법 주문표] {_profile_label(asdict(setting))}"]
    if basis is not None:
        lines.extend(
            [
                f"주문일: {basis.get('trade_date')}",
                f"종목: {setting.symbol}",
                f"상태: {plan.get('title') or '-'}",
                f"T: {_telegram_money(basis.get('t_value'), 2)}",
                f"보유수량: {basis.get('cumulative_qty')}",
                f"1회매수금: {_telegram_money(plan.get('per_buy_amount'), 2)}",
            ]
        )
    else:
        lines.append("주문 기준 로우가 없습니다.")
    if str(plan.get("title") or "").startswith("주문불가"):
        lines.append(f"사유: {plan.get('title')}")
    elif settings.send_order_table:
        lines.extend(_format_infinite_order_lines(plan, _order_row_limit(settings)))
    return "\n".join(lines)[:3900]


def _auto_send_infinite_telegram_order(
    username: str, setting: InfiniteSetting
) -> dict[str, Any]:
    settings = load_telegram_settings(telegram_settings_path(username))
    if not _telegram_auto_enabled(settings, "infinite"):
        return {"sent": False, "message": "텔레그램 자동발송 꺼짐"}
    try:
        message = build_infinite_order_telegram_message(username, setting, settings)
        send_telegram_message(settings, message)
        return {"sent": True, "message": "텔레그램 주문표 자동발송 완료"}
    except Exception as exc:
        return {"sent": False, "message": f"텔레그램 주문표 자동발송 실패: {exc}"}


def build_telegram_summary_message(username: str, settings: TelegramSettings) -> str:
    dashboard = user_dashboard(username)
    vr_rows = dashboard.get("vr_profile_rows") or []
    infinite_rows_data = dashboard.get("infinite_profile_rows") or []
    if not settings.include_paused:
        vr_rows = [row for row in vr_rows if not row.get("calculation_paused")]
        infinite_rows_data = [
            row for row in infinite_rows_data if not row.get("calculation_paused")
        ]

    sections: list[str] = [f"VR Study 알림 ({date.today().isoformat()})"]
    if settings.send_due:
        due = [
            f"- VR {row['label']}: {row['issue']}"
            for row in vr_rows
            if int(row.get("missing_count") or 0) > 0
        ]
        due.extend(
            f"- 무매 {row['label']}: {row['issue']}"
            for row in infinite_rows_data
            if int(row.get("missing_count") or 0) > 0
        )
        sections.extend(["", "[입력 필요]"])
        sections.extend(due[:12] if due else ["- 없음"])
        if len(due) > 12:
            sections.append(f"- 외 {len(due) - 12}건")

    if settings.send_dashboard:
        summary = dashboard.get("summary") or {}
        sections.extend(
            [
                "",
                "[총괄]",
                f"- 운용 프로필: VR {len(vr_rows)}개 / 무매 {len(infinite_rows_data)}개",
                f"- 현재자산(원화): {_telegram_money(summary.get('total_value_krw'))}",
                f"- 원금(원화): {_telegram_money(summary.get('total_principal_krw'))}",
                f"- 손익/수익률: {_telegram_money(summary.get('total_profit_krw'))} / {_telegram_percent(summary.get('total_return_rate'))}",
                f"- 총 매수금: {_telegram_money(summary.get('total_bought_krw'))}",
                f"- 예수금/비율: {_telegram_money(summary.get('total_cash_krw'))} / {_telegram_percent(summary.get('total_cash_ratio'))}",
            ]
        )

    if settings.send_vr_summary:
        sections.extend(["", "[VR 요약]"])
        if vr_rows:
            for row in vr_rows[:8]:
                sections.append(
                    f"- {row['label']}: 계좌 {_telegram_money(row.get('account_total'), 2)}, "
                    f"손익 {_telegram_money(row.get('profit'), 2)} / {_telegram_percent(row.get('return_rate'))}, "
                    f"미작성 {row.get('missing_text') or '없음'}"
                )
            if len(vr_rows) > 8:
                sections.append(f"- 외 {len(vr_rows) - 8}개")
        else:
            sections.append("- 없음")

    if settings.send_infinite_summary:
        sections.extend(["", "[무한매수법 요약]"])
        if infinite_rows_data:
            for row in infinite_rows_data[:8]:
                sections.append(
                    f"- {row['label']}: 평가 {_telegram_money(row.get('cumulative_value'))}, "
                    f"평단 {_telegram_money(row.get('avg_price'), 4)}, "
                    f"{row.get('progress_text') or '-'}, 미작성 {row.get('missing_text') or '없음'}"
                )
            if len(infinite_rows_data) > 8:
                sections.append(f"- 외 {len(infinite_rows_data) - 8}개")
        else:
            sections.append("- 없음")

    if settings.send_order_status:
        sections.extend(["", "[주문표 상태]"])
        if not vr_rows and not infinite_rows_data:
            sections.append("- 없음")
        for row in vr_rows[:6]:
            sections.append(
                f"- VR {row['label']}: 마지막 {row.get('last_done_text') or '-'} / 미작성 {row.get('missing_text') or '없음'}"
            )
        for row in infinite_rows_data[:6]:
            sections.append(
                f"- 무매 {row['label']}: {row.get('progress_text') or '-'} / 미작성 {row.get('missing_text') or '없음'}"
            )

    if len(sections) == 1:
        sections.append("선택된 발송 항목이 없습니다.")
    return "\n".join(sections)[:3900]


def send_telegram_selected_message(username: str) -> dict[str, Any]:
    settings = load_telegram_settings(telegram_settings_path(username))
    message = build_telegram_summary_message(username, settings)
    send_telegram_message(settings, message)
    return {"ok": True, "message": "선택 항목 전송 완료", "preview": message[:500]}
