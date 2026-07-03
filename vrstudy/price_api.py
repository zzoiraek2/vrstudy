from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class PriceBar:
    symbol: str
    price_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: int | None
    source: str = "yahoo-chart"


def _epoch_utc(day: date) -> int:
    return int(datetime.combine(day, time.min, timezone.utc).timestamp())


def fetch_yahoo_daily(symbol: str, start: date, end: date) -> list[PriceBar]:
    period1 = _epoch_utc(start)
    period2 = _epoch_utc(end) + 24 * 60 * 60
    query = urlencode(
        {
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"

    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    error = payload.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"Yahoo chart API error: {error}")

    results = payload.get("chart", {}).get("result") or []
    if not results:
        return []

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]

    bars: list[PriceBar] = []
    for index, timestamp in enumerate(timestamps):
        close = _value_at(quote.get("close"), index)
        if close is None:
            continue
        bars.append(
            PriceBar(
                symbol=symbol.upper(),
                price_date=datetime.fromtimestamp(timestamp, timezone.utc).date(),
                open=_value_at(quote.get("open"), index),
                high=_value_at(quote.get("high"), index),
                low=_value_at(quote.get("low"), index),
                close=close,
                volume=_int_at(quote.get("volume"), index),
            )
        )
    return bars


def _value_at(values: list[float | None] | None, index: int) -> float | None:
    if not values or index >= len(values) or values[index] is None:
        return None
    return float(values[index])


def _int_at(values: list[int | None] | None, index: int) -> int | None:
    if not values or index >= len(values) or values[index] is None:
        return None
    return int(values[index])
