from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .calculator import (
    SnapshotInput,
    create_rebalance,
    generate_order_levels,
    latest_snapshot,
    order_levels,
    rename_profile_snapshots,
    seed_snapshot,
)
from .db import DEFAULT_DB_PATH, connect, init_db
from .price_api import fetch_yahoo_daily
from .storage import upsert_manual_price, upsert_price_bar
from .profiles import (
    DEFAULT_PROFILE_NAME,
    Profile,
    create_profile,
    default_profiles_dir,
    ensure_default_profile,
    list_profiles,
    load_profile,
    rename_profile,
    save_profile,
    update_profile,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="TQQQ rebalance helper")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="DuckDB file path")
    parser.add_argument(
        "--profiles-dir",
        default=str(default_profiles_dir()),
        help="Profile JSON directory",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create DuckDB schema and default profile")

    profile_list = subparsers.add_parser("profile-list", help="List profiles")
    profile_list.set_defaults(needs_profile=False)

    profile_create = subparsers.add_parser("profile-create", help="Create a profile")
    profile_create.add_argument("--profile", required=True)

    profile_rename = subparsers.add_parser("profile-rename", help="Rename a profile")
    profile_rename.add_argument("--profile", required=True)
    profile_rename.add_argument("--new-name", required=True)

    profile_show = subparsers.add_parser("profile-show", help="Show profile settings")
    profile_show.add_argument("--profile", default=DEFAULT_PROFILE_NAME)

    profile_set = subparsers.add_parser("profile-set", help="Update profile settings")
    _add_profile_arg(profile_set)
    _add_profile_setting_args(profile_set)

    # Backward-compatible aliases for the original single-setting commands.
    settings = subparsers.add_parser("settings", help="Show default profile settings")
    _add_profile_arg(settings)

    set_settings = subparsers.add_parser("set-settings", help="Update profile settings")
    _add_profile_arg(set_settings)
    _add_profile_setting_args(set_settings)

    update_prices = subparsers.add_parser("update-prices", help="Fetch daily prices")
    update_prices.add_argument("--symbol", default="TQQQ")
    update_prices.add_argument("--start", required=True, type=_date)
    update_prices.add_argument("--end", required=True, type=_date)

    add_price = subparsers.add_parser("add-price", help="Manually upsert one close price")
    add_price.add_argument("--symbol", default="TQQQ")
    add_price.add_argument("--date", required=True, type=_date)
    add_price.add_argument("--close", required=True, type=float)
    add_price.add_argument("--open", type=float)
    add_price.add_argument("--high", type=float)
    add_price.add_argument("--low", type=float)
    add_price.add_argument("--volume", type=int)
    add_price.add_argument("--source", default="manual")

    seed = subparsers.add_parser("seed-snapshot", help="Insert the first baseline snapshot")
    _add_profile_arg(seed)
    seed.add_argument("--start-date", required=True, type=_date)
    seed.add_argument("--end-date", required=True, type=_date)
    seed.add_argument("--week-no", required=True, type=int)
    seed.add_argument("--close-price", required=True, type=float)
    seed.add_argument("--v", required=True, type=float)
    seed.add_argument("--pool", required=True, type=float)
    seed.add_argument("--principal", required=True, type=float)
    seed.add_argument("--shares", required=True, type=int)
    seed.add_argument("--trade-amount", default=0.0, type=float)
    seed.add_argument("--status", default="done")

    rebalance = subparsers.add_parser("rebalance", help="Create the next 2-week snapshot")
    _add_profile_arg(rebalance)
    rebalance.add_argument("--start-date", required=True, type=_date)
    rebalance.add_argument("--end-date", required=True, type=_date)
    rebalance.add_argument("--trade-amount", required=True, type=float)
    rebalance.add_argument("--shares", required=True, type=int)
    rebalance.add_argument("--close-price", type=float)
    rebalance.add_argument("--week-no", type=int)
    rebalance.add_argument("--status", default="running")

    orders = subparsers.add_parser("generate-orders", help="Generate BUY/SELL levels")
    _add_profile_arg(orders)
    orders.add_argument("--snapshot-id", type=int)

    latest = subparsers.add_parser("show-latest", help="Show latest snapshot and order levels")
    _add_profile_arg(latest)

    args = parser.parse_args()
    con = connect(Path(args.db))
    init_db(con, Path(args.db), args.profiles_dir)
    ensure_default_profile(args.profiles_dir)

    if args.command == "init":
        print(f"Initialized DB: {args.db}")
        print(f"Profiles directory: {args.profiles_dir}")
    elif args.command == "profile-list":
        _profile_list(args.profiles_dir)
    elif args.command == "profile-create":
        profile = create_profile(args.profile, args.profiles_dir)
        print(f"Created profile: {profile.name}")
    elif args.command == "profile-rename":
        profile = rename_profile(args.profile, args.new_name, args.profiles_dir)
        rename_profile_snapshots(con, args.profile, args.new_name)
        print(f"Renamed profile: {args.profile} -> {profile.name}")
    elif args.command == "profile-show" or args.command == "settings":
        print(_profile_text(load_profile(args.profile, args.profiles_dir)))
    elif args.command == "profile-set" or args.command == "set-settings":
        profile = _update_profile_from_args(args)
        print(_profile_text(profile))
    elif args.command == "update-prices":
        _update_prices(con, args.symbol, args.start, args.end)
    elif args.command == "add-price":
        _add_price(
            con,
            symbol=args.symbol,
            price_date=args.date,
            close=args.close,
            open_price=args.open,
            high=args.high,
            low=args.low,
            volume=args.volume,
            source=args.source,
        )
    elif args.command == "seed-snapshot":
        profile = load_profile(args.profile, args.profiles_dir)
        snapshot_id = seed_snapshot(
            con,
            profile=profile,
            start_date=args.start_date,
            end_date=args.end_date,
            week_no=args.week_no,
            close_price=args.close_price,
            v=args.v,
            pool=args.pool,
            principal=args.principal,
            shares=args.shares,
            trade_amount=args.trade_amount,
            status=args.status,
        )
        print(f"Seeded snapshot id={snapshot_id} profile={profile.name}")
    elif args.command == "rebalance":
        profile = load_profile(args.profile, args.profiles_dir)
        snapshot_id = create_rebalance(
            con,
            profile=profile,
            snapshot_input=SnapshotInput(
                start_date=args.start_date,
                end_date=args.end_date,
                trade_amount=args.trade_amount,
                shares=args.shares,
                status=args.status,
                close_price=args.close_price,
                week_no=args.week_no,
            ),
        )
        print(f"Created rebalance snapshot id={snapshot_id} profile={profile.name}")
    elif args.command == "generate-orders":
        profile = load_profile(args.profile, args.profiles_dir)
        generate_order_levels(con, profile=profile, snapshot_id=args.snapshot_id)
        print(f"Generated order levels profile={profile.name}")
    elif args.command == "show-latest":
        profile = load_profile(args.profile, args.profiles_dir)
        _show_latest(con, profile)


def _add_profile_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", default=DEFAULT_PROFILE_NAME)


def _add_profile_setting_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--symbol")
    parser.add_argument("--start-date")
    parser.add_argument("--g-initial", type=float)
    parser.add_argument("--g-base-week", type=int)
    parser.add_argument("--g-step-weeks", type=int)
    parser.add_argument("--g-step-value", type=float)
    parser.add_argument("--min-ratio", type=float)
    parser.add_argument("--max-ratio", type=float)
    parser.add_argument("--buy-limit-ratio", type=float)
    parser.add_argument("--quantity-step", type=int)


def _profile_list(profiles_dir: str) -> None:
    profiles = list_profiles(profiles_dir)
    if not profiles:
        print("No profiles")
        return
    for profile in profiles:
        print(profile.name)


def _update_profile_from_args(args) -> Profile:
    profile = load_profile(args.profile, args.profiles_dir)
    updated = update_profile(
        profile,
        symbol=args.symbol,
        start_date=args.start_date,
        g_initial=args.g_initial,
        g_base_week=args.g_base_week,
        g_step_weeks=args.g_step_weeks,
        g_step_value=args.g_step_value,
        min_ratio=args.min_ratio,
        max_ratio=args.max_ratio,
        buy_limit_ratio=args.buy_limit_ratio,
        quantity_step=args.quantity_step,
    )
    save_profile(updated, args.profiles_dir)
    return updated


def _update_prices(con, symbol: str, start: date, end: date) -> None:
    bars = fetch_yahoo_daily(symbol, start, end)
    for bar in bars:
        upsert_price_bar(con, bar)
    print(f"Upserted {len(bars)} price rows for {symbol.upper()}")


def _add_price(
    con,
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
    upsert_manual_price(
        con,
        symbol=symbol,
        price_date=price_date,
        close=close,
        open_price=open_price,
        high=high,
        low=low,
        volume=volume,
        source=source,
    )
    print(f"Upserted {symbol.upper()} close={close} on {price_date}")


def _show_latest(con, profile: Profile) -> None:
    snapshot = latest_snapshot(con, profile.name)
    if snapshot is None:
        print(f"No snapshots for profile={profile.name}")
        return

    print(f"Latest snapshot profile={profile.name}")
    for key in [
        "id",
        "profile_name",
        "start_date",
        "end_date",
        "close_price",
        "g",
        "week_no",
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
    ]:
        print(f"  {key}: {snapshot[key]}")

    rows = order_levels(con, int(snapshot["id"]))
    if not rows:
        print("\nNo order levels")
        return

    print("\nOrder levels")
    print("side  no  qty  before  after  price   pool_before  pool_after")
    for row in rows:
        print(
            f"{row['side']:<5} {row['level_no']:>2} {row['quantity_step']:>4} "
            f"{row['before_shares']:>7} {row['after_shares']:>6} "
            f"{row['price']:>7.2f} {row['pool_before']:>12.2f} "
            f"{row['pool_after']:>11.2f}"
        )


def _profile_text(profile: Profile) -> str:
    return (
        "Profile\n"
        f"  name: {profile.name}\n"
        f"  start date: {profile.start_date}\n"
        f"  symbol: {profile.symbol}\n"
        f"  G: initial={profile.g_initial}, base_week={profile.g_base_week}, "
        f"step={profile.g_step_weeks},{profile.g_step_value}\n"
        f"  min/max ratio: {profile.min_ratio}/{profile.max_ratio}\n"
        f"  buy limit ratio: {profile.buy_limit_ratio}\n"
        f"  quantity step: {profile.quantity_step}\n"
        f"  order quantity step: {profile.quantity_step}"
    )


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    main()
