from __future__ import annotations

from datetime import date, timedelta

import duckdb

from .core import (
    CycleInput,
    SnapshotInput,
    cycle_input_available_date,
    cycle_dates,
    cycle_result_values,
    normalize_buy_limit_config,
    normalize_g_config,
    normalize_g_start_cycle_no,
    normalize_start_week_no,
    order_basis_values,
    order_level_values,
    profile_g_config,
    rebalance_snapshot_values,
    seed_snapshot_values,
    week_monday,
)
from .db import next_id
from .price_api import PriceBar, fetch_yahoo_daily
from .profiles import Profile


AUTO_PRICE_SYMBOLS = ("TQQQ", "SOXL", "KRW=X")
AUTO_PRICE_LOOKBACK_DAYS = 90


def find_close_price(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    end_date: date,
    start_date: date | None = None,
) -> float:
    params: list[object] = [symbol.upper(), end_date]
    lower_bound = ""
    if start_date is not None:
        lower_bound = "AND price_date >= ?"
        params.append(start_date)

    row = con.execute(
        f"""
        SELECT close
        FROM prices
        WHERE symbol = ? AND price_date <= ?
        {lower_bound}
        ORDER BY price_date DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if row is None:
        raise ValueError(f"No close price for {symbol} on or before {end_date}")
    return float(row[0])


def latest_price_date(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
) -> date | None:
    row = con.execute(
        "SELECT max(price_date) FROM prices WHERE symbol = ?",
        [symbol.upper()],
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def price_count(con: duckdb.DuckDBPyConnection, symbol: str) -> int:
    row = con.execute(
        "SELECT count(*) FROM prices WHERE symbol = ?",
        [symbol.upper()],
    ).fetchone()
    return int(row[0] or 0)


def update_market_prices(
    con: duckdb.DuckDBPyConnection,
    symbols: tuple[str, ...] = AUTO_PRICE_SYMBOLS,
    today: date | None = None,
) -> dict[str, dict]:
    today = today or date.today()
    summary: dict[str, dict] = {}
    for symbol in symbols:
        symbol = symbol.upper()
        start = today - timedelta(days=AUTO_PRICE_LOOKBACK_DAYS)

        bars = [
            bar
            for bar in fetch_yahoo_daily(symbol, start, today)
            if start <= bar.price_date <= today
        ]
        for bar in bars:
            upsert_price_bar(con, bar)
        summary[symbol] = {
            "start": start,
            "end": today,
            "fetched": len(bars),
            "latest": latest_price_date(con, symbol),
            "total": price_count(con, symbol),
        }
    return summary


def latest_snapshot(
    con: duckdb.DuckDBPyConnection, profile_name: str = "default"
) -> dict | None:
    cursor = con.execute(
        """
        SELECT *
        FROM rebalance_snapshots
        WHERE profile_name = ?
        ORDER BY end_date DESC, id DESC
        LIMIT 1
        """,
        [profile_name],
    )
    row = cursor.fetchone()
    return _row_to_dict(cursor, row) if row is not None else None


def latest_cycle_snapshot(
    con: duckdb.DuckDBPyConnection, profile_name: str = "default"
) -> dict | None:
    cursor = con.execute(
        """
        SELECT *
        FROM rebalance_snapshots
        WHERE profile_name = ? AND cycle_no IS NOT NULL
        ORDER BY cycle_no DESC, id DESC
        LIMIT 1
        """,
        [profile_name],
    )
    row = cursor.fetchone()
    return _row_to_dict(cursor, row) if row is not None else None


def previous_cycle_snapshot(
    con: duckdb.DuckDBPyConnection, profile_name: str, cycle_no: int
) -> dict | None:
    cursor = con.execute(
        """
        SELECT *
        FROM rebalance_snapshots
        WHERE profile_name = ? AND cycle_no < ?
        ORDER BY cycle_no DESC, id DESC
        LIMIT 1
        """,
        [profile_name, cycle_no],
    )
    row = cursor.fetchone()
    return _row_to_dict(cursor, row) if row is not None else None


def snapshot_for_cycle(
    con: duckdb.DuckDBPyConnection, profile_name: str, cycle_no: int
) -> dict | None:
    cursor = con.execute(
        """
        SELECT *
        FROM rebalance_snapshots
        WHERE profile_name = ? AND cycle_no = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        [profile_name, cycle_no],
    )
    row = cursor.fetchone()
    return _row_to_dict(cursor, row) if row is not None else None


def cycle_numbers(con: duckdb.DuckDBPyConnection, profile_name: str) -> list[int]:
    rows = con.execute(
        """
        SELECT DISTINCT cycle_no
        FROM rebalance_snapshots
        WHERE profile_name = ? AND cycle_no IS NOT NULL
        ORDER BY cycle_no
        """,
        [profile_name],
    ).fetchall()
    return [int(row[0]) for row in rows]


def profile_cycle_status(
    con: duckdb.DuckDBPyConnection,
    profile: Profile,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    start_day = date.fromisoformat(profile.start_date)
    start_monday = week_monday(start_day)
    current_cycle = max(0, (today - start_monday).days // 14)
    saved = set(cycle_numbers(con, profile.name))

    last_available = -1
    cycle_no = 0
    while cycle_input_available_date(start_day, cycle_no) <= today:
        last_available = cycle_no
        cycle_no += 1

    missing = [cycle for cycle in range(last_available + 1) if cycle not in saved]
    return {
        "today": today,
        "current_cycle": current_cycle,
        "last_available_input_cycle": last_available,
        "last_done_cycle": max(saved) if saved else None,
        "next_input_cycle": next_input_cycle(con, profile.name),
        "missing_count": len(missing),
        "missing_cycles": missing,
    }


def cycle_snapshots(con: duckdb.DuckDBPyConnection, profile_name: str) -> list[dict]:
    cursor = con.execute(
        """
        SELECT *
        FROM rebalance_snapshots
        WHERE profile_name = ? AND cycle_no IS NOT NULL
        ORDER BY cycle_no, id
        """,
        [profile_name],
    )
    latest_by_cycle: dict[int, dict] = {}
    for row in cursor.fetchall():
        item = _row_to_dict(cursor, row)
        latest_by_cycle[int(item["cycle_no"])] = item
    return [latest_by_cycle[key] for key in sorted(latest_by_cycle)]


def display_cycle_rows(con: duckdb.DuckDBPyConnection, profile: Profile) -> list[dict]:
    rows = cycle_snapshots(con, profile.name)
    if rows:
        rows.append(_with_cycle_dates(profile, order_basis_values(profile, rows[-1])))
    return rows


def order_basis_for_next_cycle(
    con: duckdb.DuckDBPyConnection, profile: Profile
) -> dict | None:
    latest = latest_cycle_snapshot(con, profile.name)
    if latest is None:
        return None
    return _with_cycle_dates(profile, order_basis_values(profile, latest))


def _with_cycle_dates(profile: Profile, values: dict) -> dict:
    dates = cycle_dates(date.fromisoformat(profile.start_date), int(values["cycle_no"]))
    values = dict(values)
    values["start_date"] = dates.result_start
    values["end_date"] = dates.result_end
    return values


def next_input_cycle(con: duckdb.DuckDBPyConnection, profile_name: str) -> int:
    saved = set(cycle_numbers(con, profile_name))
    cycle_no = 0
    while cycle_no in saved:
        cycle_no += 1
    return cycle_no


def latest_g_config(con: duckdb.DuckDBPyConnection, profile: Profile) -> str:
    latest = latest_cycle_snapshot(con, profile.name)
    if latest is not None and latest.get("g_config"):
        return normalize_g_config(str(latest["g_config"]), profile)
    return profile_g_config(profile)


def latest_g_start_cycle_no(con: duckdb.DuckDBPyConnection, profile: Profile) -> int:
    latest = latest_cycle_snapshot(con, profile.name)
    if latest is not None:
        return normalize_g_start_cycle_no(latest.get("g_start_cycle_no"))
    return normalize_start_week_no(profile.start_week_no, default=2)


def latest_buy_limit_config(con: duckdb.DuckDBPyConnection, profile: Profile) -> str:
    latest = latest_cycle_snapshot(con, profile.name)
    if latest is not None and latest.get("buy_limit_config"):
        return normalize_buy_limit_config(str(latest["buy_limit_config"]), profile)
    return "25%,26,0%"


def latest_buy_limit_start_week_no(
    con: duckdb.DuckDBPyConnection, profile: Profile
) -> int:
    latest = latest_cycle_snapshot(con, profile.name)
    if latest is not None:
        return normalize_start_week_no(latest.get("buy_limit_start_week_no"), default=2)
    return 2


def latest_contribution_amount(
    con: duckdb.DuckDBPyConnection, profile: Profile
) -> float:
    latest = latest_cycle_snapshot(con, profile.name)
    if latest is not None and latest.get("contribution") is not None:
        return float(latest["contribution"])
    return 0.0


def ensure_close_price(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    *,
    start_date: date,
    end_date: date,
) -> float:
    try:
        return find_close_price(con, symbol, end_date, start_date)
    except ValueError:
        for bar in fetch_yahoo_daily(symbol, start_date - timedelta(days=7), end_date):
            upsert_price_bar(con, bar)
        return find_close_price(con, symbol, end_date, start_date)


def save_cycle_result(
    con: duckdb.DuckDBPyConnection,
    *,
    profile: Profile,
    cycle_input: CycleInput,
) -> int:
    expected_cycle = next_input_cycle(con, profile.name)
    if cycle_input.cycle_no != expected_cycle:
        raise ValueError(f"Next input cycle is {expected_cycle}. Cannot save cycle {cycle_input.cycle_no}.")
    if cycle_input.shares <= 0:
        raise ValueError("Shares must be greater than 0.")

    start_day = date.fromisoformat(profile.start_date)
    dates = cycle_dates(start_day, cycle_input.cycle_no)
    close_price = cycle_input.close_price
    if close_price is None:
        close_price = ensure_close_price(
            con,
            profile.symbol,
            start_date=dates.result_start,
            end_date=dates.result_end,
        )
    if close_price <= 0:
        raise ValueError("Close price must be greater than 0.")

    previous = previous_cycle_snapshot(con, profile.name, cycle_input.cycle_no)
    g_config = cycle_input.g_config or latest_g_config(con, profile)
    g_start_cycle_no = (
        normalize_g_start_cycle_no(cycle_input.g_start_cycle_no)
        if cycle_input.g_start_cycle_no is not None
        else latest_g_start_cycle_no(con, profile)
    )
    contribution_amount = (
        cycle_input.contribution_amount
        if cycle_input.contribution_amount is not None
        else latest_contribution_amount(con, profile)
    )
    values = cycle_result_values(
        profile,
        previous,
        cycle_no=cycle_input.cycle_no,
        close_price=close_price,
        trade_amount=cycle_input.trade_amount,
        shares=cycle_input.shares,
        dividend=cycle_input.dividend,
        contribution_amount=contribution_amount,
        g_config=g_config,
        g_start_cycle_no=g_start_cycle_no,
        buy_limit_config=cycle_input.buy_limit_config
        or latest_buy_limit_config(con, profile),
        buy_limit_start_week_no=cycle_input.buy_limit_start_week_no
        if cycle_input.buy_limit_start_week_no is not None
        else latest_buy_limit_start_week_no(con, profile),
    )
    return insert_snapshot(
        con,
        profile_name=profile.name,
        start_date=dates.result_start,
        end_date=dates.result_end,
        status="done",
        values=values,
    )


def recalculate_cycle_results_from(
    con: duckdb.DuckDBPyConnection,
    *,
    profile: Profile,
    cycle_input: CycleInput,
) -> int:
    snapshots = cycle_snapshots(con, profile.name)
    saved_by_cycle = {int(item["cycle_no"]): item for item in snapshots}
    if cycle_input.cycle_no not in saved_by_cycle:
        raise ValueError(f"Saved cycle not found: {cycle_input.cycle_no}")
    if cycle_input.shares <= 0:
        raise ValueError("Shares must be greater than 0.")
    if cycle_input.close_price is None or cycle_input.close_price <= 0:
        raise ValueError("Close price must be greater than 0.")

    inputs: list[CycleInput] = [cycle_input]
    for cycle_no in sorted(key for key in saved_by_cycle if key > cycle_input.cycle_no):
        item = saved_by_cycle[cycle_no]
        inputs.append(
            CycleInput(
                cycle_no=cycle_no,
                close_price=float(item["close_price"]),
                trade_amount=float(item["trade_amount"]),
                shares=int(item["shares"]),
                dividend=float(item.get("dividend") or 0),
                contribution_amount=float(item.get("contribution") or 0),
                g_config=str(item.get("g_config") or latest_g_config(con, profile)),
                g_start_cycle_no=normalize_g_start_cycle_no(
                    item.get("g_start_cycle_no")
                ),
                buy_limit_config=str(
                    item.get("buy_limit_config") or latest_buy_limit_config(con, profile)
                ),
                buy_limit_start_week_no=normalize_start_week_no(
                    item.get("buy_limit_start_week_no"), default=2
                ),
            )
        )

    previous = previous_cycle_snapshot(con, profile.name, cycle_input.cycle_no)
    first_snapshot_id = 0
    for item in inputs:
        start_day = date.fromisoformat(profile.start_date)
        dates = cycle_dates(start_day, item.cycle_no)
        values = cycle_result_values(
            profile,
            previous,
            cycle_no=item.cycle_no,
            close_price=float(item.close_price),
            trade_amount=item.trade_amount,
            shares=item.shares,
            dividend=item.dividend,
            contribution_amount=item.contribution_amount,
            g_config=item.g_config,
            g_start_cycle_no=item.g_start_cycle_no,
            buy_limit_config=item.buy_limit_config,
            buy_limit_start_week_no=item.buy_limit_start_week_no,
        )
        snapshot_id = insert_snapshot(
            con,
            profile_name=profile.name,
            start_date=dates.result_start,
            end_date=dates.result_end,
            status="done",
            values=values,
        )
        if first_snapshot_id == 0:
            first_snapshot_id = snapshot_id
        previous = snapshot_by_id(con, snapshot_id, profile.name)
    return first_snapshot_id


def seed_snapshot(
    con: duckdb.DuckDBPyConnection,
    *,
    profile: Profile,
    start_date: date,
    end_date: date,
    week_no: int,
    close_price: float,
    v: float,
    pool: float,
    principal: float,
    shares: int,
    trade_amount: float,
    status: str,
) -> int:
    values = seed_snapshot_values(
        profile,
        close_price=close_price,
        week_no=week_no,
        v=v,
        pool=pool,
        principal=principal,
        shares=shares,
        trade_amount=trade_amount,
    )
    return insert_snapshot(
        con,
        profile_name=profile.name,
        start_date=start_date,
        end_date=end_date,
        status=status,
        values=values,
    )


def create_rebalance(
    con: duckdb.DuckDBPyConnection,
    *,
    profile: Profile,
    snapshot_input: SnapshotInput,
) -> int:
    previous = latest_snapshot(con, profile.name)
    if previous is None:
        raise ValueError(f"No previous snapshot for profile '{profile.name}'. Run seed-snapshot first.")

    week_no = snapshot_input.week_no or int(previous["week_no"]) + 2
    close_price = snapshot_input.close_price
    if close_price is None:
        close_price = find_close_price(con, profile.symbol, snapshot_input.end_date)

    values = rebalance_snapshot_values(
        profile,
        previous,
        close_price=close_price,
        week_no=week_no,
        trade_amount=snapshot_input.trade_amount,
        shares=snapshot_input.shares,
    )
    return insert_snapshot(
        con,
        profile_name=profile.name,
        start_date=snapshot_input.start_date,
        end_date=snapshot_input.end_date,
        status=snapshot_input.status,
        values=values,
    )


def generate_order_levels(
    con: duckdb.DuckDBPyConnection,
    *,
    profile: Profile,
    snapshot_id: int | None = None,
    quantity_step: int | None = None,
) -> None:
    snapshot = snapshot_by_id(con, snapshot_id, profile.name)
    sid = int(snapshot["id"])
    con.execute("DELETE FROM order_levels WHERE snapshot_id = ?", [sid])

    level_id = next_id(con, "order_levels")
    for row in order_level_values(profile, snapshot, quantity_step=quantity_step):
        con.execute(
            """
            INSERT INTO order_levels
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
            """,
            [
                level_id,
                sid,
                row["side"],
                row["level_no"],
                row["quantity_step"],
                row["before_shares"],
                row["after_shares"],
                row["price"],
                row["pool_before"],
                row["pool_after"],
            ],
        )
        level_id += 1
    commit_if_possible(con)


def order_levels(con: duckdb.DuckDBPyConnection, snapshot_id: int) -> list[dict]:
    cursor = con.execute(
        """
        SELECT side, level_no, quantity_step, before_shares, after_shares,
               price, pool_before, pool_after
        FROM order_levels
        WHERE snapshot_id = ?
        ORDER BY side, level_no
        """,
        [snapshot_id],
    )
    return [_row_to_dict(cursor, row) for row in cursor.fetchall()]


def rename_profile_snapshots(
    con: duckdb.DuckDBPyConnection, old_name: str, new_name: str
) -> None:
    con.execute(
        "UPDATE rebalance_snapshots SET profile_name = ? WHERE profile_name = ?",
        [new_name, old_name],
    )
    commit_if_possible(con)


def delete_profile_records(con: duckdb.DuckDBPyConnection, profile_name: str) -> None:
    con.execute(
        """
        DELETE FROM order_levels
        WHERE snapshot_id IN (
            SELECT id FROM rebalance_snapshots WHERE profile_name = ?
        )
        """,
        [profile_name],
    )
    con.execute("DELETE FROM rebalance_snapshots WHERE profile_name = ?", [profile_name])
    commit_if_possible(con)


def upsert_price_bar(con: duckdb.DuckDBPyConnection, bar: PriceBar) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO prices
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
        """,
        [
            bar.symbol,
            bar.price_date,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.source,
        ],
    )
    commit_if_possible(con)


def commit_if_possible(con: duckdb.DuckDBPyConnection) -> None:
    try:
        con.commit()
    except Exception:
        pass


def upsert_manual_price(
    con: duckdb.DuckDBPyConnection,
    *,
    symbol: str,
    price_date: date,
    close: float,
    open_price: float | None,
    high: float | None,
    low: float | None,
    volume: int | None,
    source: str,
) -> None:
    upsert_price_bar(
        con,
        PriceBar(
            symbol=symbol.upper(),
            price_date=price_date,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source=source,
        ),
    )


def insert_snapshot(
    con: duckdb.DuckDBPyConnection,
    *,
    profile_name: str,
    start_date: date,
    end_date: date,
    status: str,
    values: dict,
) -> int:
    snapshot_id = next_id(con, "rebalance_snapshots")
    columns = [
        "id",
        "setting_id",
        "start_date",
        "end_date",
        "close_price",
        "g",
        "week_no",
        "status",
        "valuation",
        "v",
        "min_value",
        "max_value",
        "trade_amount",
        "prior_pool",
        "pool",
        "principal",
        "account_total",
        "return_rate",
        "profit",
        "shares",
        "buy_principal",
        "avg_cost",
        "buy_limit_ratio",
        "profile_name",
        "cycle_no",
        "contribution",
        "dividend",
        "g_config",
        "g_start_cycle_no",
        "buy_limit_config",
        "buy_limit_start_week_no",
        "created_at",
    ]
    params = [
        snapshot_id,
        1,
        start_date,
        end_date,
        values["close_price"],
        values["g"],
        values["week_no"],
        status,
        values["valuation"],
        values["v"],
        values["min_value"],
        values["max_value"],
        values["trade_amount"],
        values["prior_pool"],
        values["pool"],
        values["principal"],
        values["account_total"],
        values["return_rate"],
        values["profit"],
        values["shares"],
        values["buy_principal"],
        values["avg_cost"],
        values["buy_limit_ratio"],
        profile_name,
        values.get("cycle_no"),
        values.get("contribution", 0.0),
        values.get("dividend", 0.0),
        values.get("g_config"),
        normalize_g_start_cycle_no(values.get("g_start_cycle_no")),
        values.get("buy_limit_config"),
        normalize_start_week_no(values.get("buy_limit_start_week_no"), default=2),
    ]
    placeholders = ", ".join(["?"] * len(params)) + ", current_timestamp"
    con.execute(
        f"""
        INSERT INTO rebalance_snapshots ({", ".join(columns)})
        VALUES ({placeholders})
        """,
        params,
    )
    commit_if_possible(con)
    return snapshot_id


def snapshot_by_id(
    con: duckdb.DuckDBPyConnection, snapshot_id: int | None, profile_name: str
) -> dict:
    if snapshot_id is None:
        snapshot = latest_snapshot(con, profile_name)
        if snapshot is None:
            raise ValueError(f"No snapshot found for profile '{profile_name}'")
        return snapshot

    cursor = con.execute(
        "SELECT * FROM rebalance_snapshots WHERE id = ? AND profile_name = ?",
        [snapshot_id, profile_name],
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"snapshot id={snapshot_id} not found for profile '{profile_name}'")
    return _row_to_dict(cursor, row)


def _row_to_dict(cursor: duckdb.DuckDBPyConnection, row: tuple) -> dict:
    names = [column[0] for column in cursor.description]
    return dict(zip(names, row))
