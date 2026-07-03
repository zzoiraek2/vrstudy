from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from .accounts import user_data_dir, user_db_path


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _connect_readonly(db_path: Path) -> duckdb.DuckDBPyConnection | None:
    if not db_path.exists():
        return None
    return duckdb.connect(str(db_path), read_only=True)


def _tables(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in con.execute("SHOW TABLES").fetchall()}


def _count(con: duckdb.DuckDBPyConnection, table: str, tables: set[str]) -> int:
    if table not in tables:
        return 0
    return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _query_dicts(con: duckdb.DuckDBPyConnection, query: str) -> list[dict[str, Any]]:
    rows = con.execute(query).fetchall()
    columns = [desc[0] for desc in con.description]
    return [
        {column: _json_value(value) for column, value in zip(columns, row)}
        for row in rows
    ]


def _read_profile_files(base_dir: Path) -> list[dict[str, Any]]:
    profiles_dir = base_dir / "profiles" / "vr"
    if not profiles_dir.exists():
        return []
    profiles: list[dict[str, Any]] = []
    for path in sorted(profiles_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        profiles.append(
            {
                "name": str(raw.get("name") or path.stem),
                "symbol": str(raw.get("symbol") or raw.get("ticker") or ""),
                "account_number": str(raw.get("account_number") or ""),
                "file": path.name,
            }
        )
    return profiles


def user_dashboard(username: str) -> dict[str, Any]:
    base_dir = user_data_dir(username)
    db_path = user_db_path(username)
    result: dict[str, Any] = {
        "username": username,
        "has_database": db_path.exists(),
        "counts": {
            "vr_snapshots": 0,
            "infinite_profiles": 0,
            "infinite_rows": 0,
            "order_levels": 0,
        },
        "vr_profiles": _read_profile_files(base_dir),
        "infinite_profiles": [],
    }
    con = _connect_readonly(db_path)
    if con is None:
        return result
    try:
        tables = _tables(con)
        result["counts"] = {
            "vr_snapshots": _count(con, "rebalance_snapshots", tables),
            "infinite_profiles": _count(con, "infinite_settings", tables),
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
                ORDER BY COALESCE(profile_no, 9999), name
                """,
            )
    finally:
        con.close()
    return result

