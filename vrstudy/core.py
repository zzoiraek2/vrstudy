from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import floor, sqrt

from .profiles import Profile


@dataclass(frozen=True)
class SnapshotInput:
    start_date: date
    end_date: date
    trade_amount: float
    shares: int
    status: str = "done"
    close_price: float | None = None
    week_no: int | None = None


@dataclass(frozen=True)
class CycleInput:
    cycle_no: int
    trade_amount: float
    shares: int
    dividend: float = 0.0
    close_price: float | None = None
    contribution_amount: float | None = None
    g_config: str = ""
    g_start_cycle_no: int | None = None
    buy_limit_config: str = ""
    buy_limit_start_week_no: int | None = None


@dataclass(frozen=True)
class CycleDates:
    result_start: date
    result_end: date
    order_start: date
    order_end: date


def week_monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def cycle_dates(start_day: date, cycle_index: int = 0) -> CycleDates:
    result_start = week_monday(start_day) + timedelta(days=cycle_index * 14)
    result_end = result_start + timedelta(days=11)
    order_start = result_start + timedelta(days=14)
    order_end = order_start + timedelta(days=11)
    return CycleDates(
        result_start=result_start,
        result_end=result_end,
        order_start=order_start,
        order_end=order_end,
    )


def cycle_input_available_date(start_day: date, cycle_index: int = 0) -> date:
    return cycle_dates(start_day, cycle_index).result_end + timedelta(days=1)


def calculate_g(profile: Profile, week_no: int) -> float:
    steps = floor(week_no / profile.g_step_weeks)
    return profile.g_initial + steps * profile.g_step_value


def profile_g_config(profile: Profile) -> str:
    return f"{profile.g_initial:g},{profile.g_step_weeks},{profile.g_step_value:g}"


def normalize_g_config(g_config: str | None, profile: Profile) -> str:
    text = (g_config or "").strip()
    if not text:
        text = profile_g_config(profile)
    initial, period_weeks, step_value = parse_g_config(text)
    return f"{initial:g},{period_weeks},{step_value:g}"


def parse_g_config(g_config: str) -> tuple[float, int, float]:
    parts = [part.strip() for part in g_config.split(",")]
    if len(parts) != 3:
        raise ValueError("G condition must be like 15,26,1.")
    initial = float(parts[0])
    period_weeks = int(float(parts[1]))
    step_value = float(parts[2])
    if period_weeks <= 0:
        raise ValueError("G period weeks must be greater than 0.")
    return initial, period_weeks, step_value


def parse_percent_value(value: str | float | int) -> float:
    if isinstance(value, str):
        text = value.strip()
        has_percent = text.endswith("%")
        if has_percent:
            text = text[:-1].strip()
        number = float(text)
        if has_percent or abs(number) > 1:
            return number / 100
        return number
    number = float(value)
    if abs(number) > 1:
        return number / 100
    return number


def normalize_start_week_no(start_week_no: int | None, default: int = 2) -> int:
    if start_week_no is None:
        return default
    value = int(start_week_no)
    if value <= 0:
        raise ValueError("Start week must be 1 or greater.")
    return value


def normalize_g_start_cycle_no(g_start_cycle_no: int | None) -> int:
    return normalize_start_week_no(g_start_cycle_no, default=2)


def calculate_week_g(
    week_no: int, g_config: str, g_start_week_no: int | None = None
) -> float:
    initial, period_weeks, step_value = parse_g_config(g_config)
    elapsed_weeks = max(0, week_no - normalize_g_start_cycle_no(g_start_week_no))
    steps = floor(elapsed_weeks / period_weeks)
    return initial + steps * step_value


def calculate_cycle_g(
    cycle_no: int,
    g_config: str,
    g_start_cycle_no: int | None = None,
    profile: Profile | None = None,
) -> float | None:
    if cycle_no <= 0:
        return None
    if profile is None:
        week_no = cycle_no * 2
    else:
        week_no = cycle_week_no(profile, cycle_no)
    return calculate_week_g(week_no, g_config, g_start_cycle_no)


def profile_buy_limit_config(profile: Profile) -> str:
    text = (profile.buy_limit_config or "").strip()
    if text:
        return normalize_buy_limit_config(text, profile)
    return f"{float(profile.buy_limit_ratio) * 100:g}%,26,0%"


def normalize_buy_limit_config(buy_limit_config: str | None, profile: Profile) -> str:
    text = (buy_limit_config or "").strip()
    if not text:
        text = profile_buy_limit_config(profile)
    initial, period_weeks, step_value = parse_buy_limit_config(text)
    return f"{initial * 100:g}%,{period_weeks},{step_value * 100:g}%"


def parse_buy_limit_config(buy_limit_config: str) -> tuple[float, int, float]:
    parts = [part.strip() for part in buy_limit_config.split(",")]
    if len(parts) != 3:
        raise ValueError("Buy limit condition must be like 75%,26,-5%.")
    initial = parse_percent_value(parts[0])
    period_weeks = int(float(parts[1]))
    step_value = parse_percent_value(parts[2])
    if period_weeks <= 0:
        raise ValueError("Buy limit period weeks must be greater than 0.")
    return initial, period_weeks, step_value


def calculate_buy_limit_ratio(
    week_no: int, buy_limit_config: str, buy_limit_start_week_no: int | None = None
) -> float:
    initial, period_weeks, step_value = parse_buy_limit_config(buy_limit_config)
    start_week = normalize_start_week_no(buy_limit_start_week_no, default=2)
    elapsed_weeks = max(0, week_no - start_week - 1)
    steps = floor(elapsed_weeks / period_weeks)
    return max(0.0, min(1.0, initial + steps * step_value))


def cycle_week_no(profile: Profile, cycle_no: int) -> int:
    if cycle_no <= 0:
        return 0
    return int(profile.start_week_no) + (cycle_no - 1) * 2


def cycle_no_from_week(profile: Profile, week_no: int) -> int:
    week_no = int(week_no)
    if week_no == 0:
        return 0
    start_week = int(profile.start_week_no)
    if week_no < start_week or (week_no - start_week) % 2 != 0:
        raise ValueError(
            f"{profile.name} 프로필은 {start_week}주차부터 2주 간격으로 입력합니다."
        )
    return ((week_no - start_week) // 2) + 1


def contribution_for_cycle(
    profile: Profile, contribution_amount: float | None = None
) -> float:
    if contribution_amount is not None:
        return float(contribution_amount)
    return 0.0


def cycle_result_values(
    profile: Profile,
    previous: dict | None,
    *,
    cycle_no: int,
    close_price: float,
    trade_amount: float,
    shares: int,
    dividend: float,
    contribution_amount: float | None = None,
    g_config: str | None = None,
    g_start_cycle_no: int | None = None,
    buy_limit_config: str | None = None,
    buy_limit_start_week_no: int | None = None,
) -> dict:
    week_no = cycle_week_no(profile, cycle_no)
    normalized_g_config = normalize_g_config(g_config, profile)
    normalized_g_start_cycle_no = normalize_g_start_cycle_no(g_start_cycle_no)
    g = None if cycle_no <= 0 else calculate_week_g(
        week_no, normalized_g_config, normalized_g_start_cycle_no
    )
    normalized_buy_limit_config = normalize_buy_limit_config(buy_limit_config, profile)
    normalized_buy_limit_start_week_no = normalize_start_week_no(
        buy_limit_start_week_no, default=2
    )
    buy_limit_ratio = calculate_buy_limit_ratio(
        week_no, normalized_buy_limit_config, normalized_buy_limit_start_week_no
    )
    contribution = contribution_for_cycle(profile, contribution_amount)
    valuation = round(shares * close_price, 2)

    if previous is None:
        base_v = float(profile.initial_v)
        base_pool = float(profile.initial_pool)
        base_principal = float(profile.initial_principal)
        previous_valuation = valuation
        v = round(base_v + contribution, 2)
    else:
        base_v = float(previous["v"])
        base_pool = float(previous["pool"])
        base_principal = float(previous["principal"])
        previous_valuation = float(previous["valuation"])
        if g is None:
            raise ValueError("G is required from cycle 1.")
        v = round(
            base_v + base_pool / g + (previous_valuation - base_v) / (2 * sqrt(g)),
            2,
        ) + contribution

    prior_pool = round(base_pool + contribution, 2)
    pool = round(prior_pool + trade_amount + dividend, 2)
    principal = round(base_principal + contribution, 2)
    account_total = round(prior_pool + previous_valuation, 2)

    values = _snapshot_values(
        profile,
        close_price=close_price,
        g=g or 0.0,
        week_no=week_no,
        valuation=valuation,
        v=v,
        trade_amount=trade_amount,
        prior_pool=prior_pool,
        pool=pool,
        principal=principal,
        account_total=account_total,
        shares=shares,
        buy_limit_ratio=buy_limit_ratio,
    )
    values["cycle_no"] = cycle_no
    values["contribution"] = contribution
    values["dividend"] = dividend
    values["g_config"] = normalized_g_config
    values["g_start_cycle_no"] = normalized_g_start_cycle_no
    values["buy_limit_config"] = normalized_buy_limit_config
    values["buy_limit_start_week_no"] = normalized_buy_limit_start_week_no
    return values


def order_basis_values(profile: Profile, previous: dict) -> dict:
    cycle_no = int(previous["cycle_no"]) + 1
    week_no = cycle_week_no(profile, cycle_no)
    g_config = normalize_g_config(previous.get("g_config"), profile)
    g_start_cycle_no = normalize_g_start_cycle_no(previous.get("g_start_cycle_no"))
    g = calculate_week_g(week_no, g_config, g_start_cycle_no)
    if g is None:
        raise ValueError("G is required for order basis.")
    buy_limit_config = normalize_buy_limit_config(
        previous.get("buy_limit_config"), profile
    )
    buy_limit_start_week_no = normalize_start_week_no(
        previous.get("buy_limit_start_week_no"), default=2
    )
    buy_limit_ratio = calculate_buy_limit_ratio(
        week_no, buy_limit_config, buy_limit_start_week_no
    )
    contribution = contribution_for_cycle(
        profile,
        float(previous["contribution"])
        if previous.get("contribution") is not None
        else None,
    )
    base_v = float(previous["v"])
    base_pool = float(previous["pool"])
    base_principal = float(previous["principal"])
    previous_valuation = float(previous["valuation"])
    shares = int(previous["shares"])
    v = round(
        base_v + base_pool / g + (previous_valuation - base_v) / (2 * sqrt(g)),
        2,
    ) + contribution
    pool = round(base_pool + contribution, 2)
    principal = round(base_principal + contribution, 2)
    account_total = round(pool + previous_valuation, 2)

    values = _snapshot_values(
        profile,
        close_price=None,
        g=g,
        week_no=week_no,
        valuation=previous_valuation,
        v=v,
        trade_amount=None,
        prior_pool=pool,
        pool=pool,
        principal=principal,
        account_total=account_total,
        shares=shares,
        buy_limit_ratio=buy_limit_ratio,
    )
    values["cycle_no"] = cycle_no
    values["status"] = "주문생성"
    values["contribution"] = contribution
    values["dividend"] = None
    values["g_config"] = g_config
    values["g_start_cycle_no"] = g_start_cycle_no
    values["buy_limit_config"] = buy_limit_config
    values["buy_limit_start_week_no"] = buy_limit_start_week_no
    values["is_order_basis"] = True
    values["source_cycle_no"] = int(previous["cycle_no"])
    return values


def seed_snapshot_values(
    profile: Profile,
    *,
    close_price: float,
    week_no: int,
    v: float,
    pool: float,
    principal: float,
    shares: int,
    trade_amount: float,
) -> dict:
    valuation = round(shares * close_price, 2)
    account_total = round(pool + valuation, 2)
    return _snapshot_values(
        profile,
        close_price=close_price,
        g=calculate_g(profile, week_no),
        week_no=week_no,
        valuation=valuation,
        v=v,
        trade_amount=trade_amount,
        prior_pool=pool,
        pool=pool,
        principal=principal,
        account_total=account_total,
        shares=shares,
        buy_limit_ratio=calculate_buy_limit_ratio(
            week_no,
            profile_buy_limit_config(profile),
            profile.buy_limit_start_week_no,
        ),
    )


def rebalance_snapshot_values(
    profile: Profile,
    previous: dict,
    *,
    close_price: float,
    week_no: int,
    trade_amount: float,
    shares: int,
) -> dict:
    g = calculate_g(profile, week_no)
    previous_pool = float(previous["pool"])
    previous_v = float(previous["v"])
    previous_valuation = float(previous["valuation"])
    principal = float(previous["principal"])

    valuation = round(shares * close_price, 2)
    v = round(
        previous_v
        + previous_pool / g
        + (previous_valuation - previous_v) / (2 * sqrt(g)),
        2,
    )
    pool = round(previous_pool + trade_amount, 2)
    account_total = round(previous_pool + previous_valuation, 2)

    return _snapshot_values(
        profile,
        close_price=close_price,
        g=g,
        week_no=week_no,
        valuation=valuation,
        v=v,
        trade_amount=trade_amount,
        prior_pool=previous_pool,
        pool=pool,
        principal=principal,
        account_total=account_total,
        shares=shares,
        buy_limit_ratio=calculate_buy_limit_ratio(
            week_no,
            profile_buy_limit_config(profile),
            profile.buy_limit_start_week_no,
        ),
    )


def order_level_values(
    profile: Profile, snapshot: dict, quantity_step: int | None = None
) -> list[dict]:
    quantity_step = int(quantity_step or profile.quantity_step)
    if quantity_step <= 0:
        raise ValueError("Quantity step must be greater than 0.")
    shares = int(snapshot["shares"])
    pool = float(snapshot["pool"])
    min_value = float(snapshot["min_value"])
    max_value = float(snapshot["max_value"])
    reserve_pool = round(pool * (1 - buy_limit_ratio(profile, snapshot)), 2)
    rows: list[dict] = []

    level_no = 1
    before_shares = shares
    pool_before = pool
    while before_shares > 0:
        price = round(min_value / before_shares, 2)
        pool_after = round(pool_before - price * quantity_step, 2)
        if pool_after < reserve_pool:
            break
        rows.append(
            _order_row(
                "BUY", level_no, quantity_step, before_shares, before_shares + quantity_step, price, pool_before, pool_after
            )
        )
        level_no += 1
        before_shares += quantity_step
        pool_before = pool_after

    level_no = 1
    before_shares = shares
    pool_before = pool
    while before_shares > quantity_step:
        price = round(max_value / before_shares, 2)
        pool_after = round(pool_before + price * quantity_step, 2)
        rows.append(
            _order_row(
                "SELL", level_no, quantity_step, before_shares, before_shares - quantity_step, price, pool_before, pool_after
            )
        )
        level_no += 1
        before_shares -= quantity_step
        pool_before = pool_after

    return rows


def _snapshot_values(
    profile: Profile,
    *,
    close_price: float | None,
    g: float,
    week_no: int,
    valuation: float,
    v: float,
    trade_amount: float | None,
    prior_pool: float,
    pool: float,
    principal: float,
    account_total: float,
    shares: int,
    buy_limit_ratio: float,
) -> dict:
    profit = round(account_total - principal, 2)
    buy_principal = round(principal - pool, 2)
    return {
        "close_price": close_price,
        "g": g,
        "week_no": week_no,
        "valuation": valuation,
        "v": v,
        "min_value": round(v * profile.min_ratio, 2),
        "max_value": round(v * profile.max_ratio, 2),
        "trade_amount": trade_amount,
        "prior_pool": prior_pool,
        "pool": pool,
        "principal": principal,
        "account_total": account_total,
        "return_rate": account_total / principal - 1 if principal else 0.0,
        "profit": profit,
        "shares": shares,
        "buy_principal": buy_principal,
        "avg_cost": round(buy_principal / shares, 2) if shares else None,
        "buy_limit_ratio": buy_limit_ratio,
    }


def buy_limit_ratio(profile: Profile, snapshot: dict) -> float:
    value = snapshot.get("buy_limit_ratio")
    if value is None:
        return calculate_buy_limit_ratio(
            int(snapshot["week_no"]),
            profile_buy_limit_config(profile),
            profile.buy_limit_start_week_no,
        )
    return max(0.0, min(1.0, float(value)))


def _order_row(
    side: str,
    level_no: int,
    quantity_step: int,
    before_shares: int,
    after_shares: int,
    price: float,
    pool_before: float,
    pool_after: float,
) -> dict:
    return {
        "side": side,
        "level_no": level_no,
        "quantity_step": quantity_step,
        "before_shares": before_shares,
        "after_shares": after_shares,
        "price": price,
        "pool_before": pool_before,
        "pool_after": pool_after,
    }
