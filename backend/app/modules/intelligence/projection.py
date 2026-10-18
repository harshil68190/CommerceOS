"""
modules/intelligence/projection.py

Responsibility
--------------
Projected-inventory and stockout-date maths. Pure functions.

Conventions
-----------
* Day 1 of the forecast is `as_of` (today); history ends yesterday.
* Stock at the END of forecast day d is   available - rate * d.
* The position "stocks out" on the first day d where that is <= 0:

      d* = ceil(available / rate)            (available > 0, rate > 0)
      stockout_date = as_of + (d* - 1) days  (the day the last unit goes)

* If available <= 0 and demand is expected, the position is already out:
  stockout_date = as_of, days_of_cover = 0.
* If rate == 0 there is no stockout (cover is infinite -> None).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil, isfinite


@dataclass(frozen=True)
class ProjectionPoint:
    day: date
    projected_stock: float      # end-of-day stock, floored at 0
    cumulative_demand: float    # forecast units consumed through this day


def days_of_cover(available: int, daily_rate: float) -> float | None:
    """Days the available stock lasts at the forecast rate.
    None = infinite (no expected demand)."""
    if not isfinite(daily_rate) or daily_rate <= 0:
        return None
    cover = max(0, available) / daily_rate
    return cover if isfinite(cover) else None


def stockout_day_number(available: int, daily_rate: float) -> int | None:
    """1-based forecast day on which stock first reaches zero.
    0 means already out of stock; None means it never runs out."""
    if not isfinite(daily_rate) or daily_rate <= 0:
        return None
    if available <= 0:
        return 0
    # round() guards against float noise such as 2.0000000000000004
    days = available / daily_rate
    if not isfinite(days):
        return None
    return ceil(round(days, 9))


def stockout_date(as_of: date, available: int, daily_rate: float) -> date | None:
    """Calendar date on which the position runs out (None if it won't)."""
    d_star = stockout_day_number(available, daily_rate)
    if d_star is None:
        return None
    try:
        return as_of + timedelta(days=max(d_star - 1, 0))
    except (OverflowError, ValueError):
        # Dates outside datetime.date's supported range have no representable
        # stockout date. Keep the position analyzable and expose no date.
        return None


def stocks_out_within(
    as_of: date, available: int, daily_rate: float, horizon_days: int
) -> bool:
    """True if stock reaches zero on or before day `horizon_days`."""
    d_star = stockout_day_number(available, daily_rate)
    return d_star is not None and d_star <= horizon_days


def project_inventory(
    as_of: date, available: int, daily_rate: float, horizon_days: int
) -> list[ProjectionPoint]:
    """End-of-day projected stock for each day of the horizon."""
    start_stock = max(0, available)
    points: list[ProjectionPoint] = []
    for d in range(1, horizon_days + 1):
        consumed = daily_rate * d
        points.append(
            ProjectionPoint(
                day=as_of + timedelta(days=d - 1),
                projected_stock=max(0.0, start_stock - consumed),
                cumulative_demand=consumed,
            )
        )
    return points


def unserved_demand(available: int, daily_rate: float, horizon_days: int) -> float:
    """Forecast units that cannot be fulfilled from current stock by the
    end of the horizon (the size of the projected shortfall)."""
    return max(0.0, daily_rate * horizon_days - max(0, available))
