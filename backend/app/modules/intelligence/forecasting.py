"""
modules/intelligence/forecasting.py

Responsibility
--------------
Pure, deterministic demand-forecasting functions. No database, no clock,
no randomness: the same inputs always give the same outputs.

Method (deliberately simple and explainable)
--------------------------------------------
Given a zero-filled series of daily units sold (oldest -> newest):

    MA_w      = mean of the last min(w, n) days            for w in 7, 14, 30
    rate      = 0.5 * MA_7 + 0.3 * MA_14 + 0.2 * MA_30     (units / day)
    sigma     = sample standard deviation of the last 30 days

The forecast is a flat daily rate over the horizon:
    forecast_demand(H) = rate * H

A short-window average reacts quickly to trend changes; longer windows
damp noise. When history is shorter than a window, that window simply
uses all available days (so a brand-new position is not diluted by days
it could not have sold).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from math import sqrt
from typing import Mapping, Sequence

from app.modules.intelligence.constants import (
    BACKTEST_DAYS,
    FORECAST_WEIGHTS,
    FORECAST_WINDOWS,
    FULL_HISTORY_DAYS,
    LOW_CONFIDENCE_MAX_DAYS,
    SIGMA_WINDOW_DAYS,
    ForecastConfidence,
)


@dataclass(frozen=True)
class ForecastResult:
    """Output of the baseline forecaster for one product x warehouse."""

    daily_rate: float
    ma_7: float
    ma_14: float
    ma_30: float
    sigma_daily: float
    history_days: int
    total_units_in_history: int
    confidence: ForecastConfidence

    def scaled(self, factor: float) -> "ForecastResult":
        """Returns a copy with demand scaled by `factor` (what-if analysis).
        Mean and standard deviation both scale linearly with demand."""
        return ForecastResult(
            daily_rate=self.daily_rate * factor,
            ma_7=self.ma_7 * factor,
            ma_14=self.ma_14 * factor,
            ma_30=self.ma_30 * factor,
            sigma_daily=self.sigma_daily * factor,
            history_days=self.history_days,
            total_units_in_history=self.total_units_in_history,
            confidence=self.confidence,
        )


@dataclass(frozen=True)
class BacktestPoint:
    """One day of 'what we predicted' versus 'what actually sold'."""

    day: date
    actual: int
    forecast: float


def build_daily_series(
    demand_by_day: Mapping[date, int], start: date, end: date
) -> list[int]:
    """Zero-filled daily series for every calendar day in [start, end]
    inclusive. Missing days mean zero units sold. Empty if end < start."""
    if end < start:
        return []
    days = (end - start).days + 1
    return [int(demand_by_day.get(start + timedelta(days=i), 0)) for i in range(days)]


def resolve_history_start(
    *,
    window_start: date,
    as_of: date,
    inventory_created: date | None,
    first_demand: date | None,
) -> date:
    """First day this position could have sold, clipped to the loaded window.

    Days before a position existed are NOT zero-demand days; counting them
    would drag the average down. The start is the earlier of the inventory
    row's creation date and the first observed sale (the latter protects
    against back-dated/imported data), clipped into [window_start, as_of].
    """
    candidates = [d for d in (inventory_created, first_demand) if d is not None]
    start = min(candidates) if candidates else as_of
    return max(window_start, min(start, as_of))


def moving_average(values: Sequence[float], window: int) -> float:
    """Mean of the last min(window, len(values)) values; 0.0 if empty."""
    n = min(window, len(values))
    if n <= 0:
        return 0.0
    return sum(values[-n:]) / n


def weighted_daily_rate(values: Sequence[float]) -> float:
    """Weighted blend of the 7/14/30-day moving averages (units per day)."""
    return sum(
        weight * moving_average(values, window)
        for window, weight in zip(FORECAST_WINDOWS, FORECAST_WEIGHTS)
    )


def demand_std(values: Sequence[float], window: int = SIGMA_WINDOW_DAYS) -> float:
    """Sample standard deviation (n-1) over the last `window` days.
    Returns 0.0 when fewer than 2 observations exist."""
    recent = list(values[-window:])
    n = len(recent)
    if n < 2:
        return 0.0
    mean = sum(recent) / n
    variance = sum((v - mean) ** 2 for v in recent) / (n - 1)
    return sqrt(variance)


def classify_confidence(history_days: int, total_units: int) -> ForecastConfidence:
    """Confidence label from the amount of observed history."""
    if total_units <= 0 or history_days <= 0:
        return ForecastConfidence.NONE
    if history_days < LOW_CONFIDENCE_MAX_DAYS:
        return ForecastConfidence.LOW
    if history_days < FULL_HISTORY_DAYS:
        return ForecastConfidence.MEDIUM
    return ForecastConfidence.HIGH


def forecast_demand(values: Sequence[int]) -> ForecastResult:
    """Runs the baseline forecaster over a history-trimmed daily series."""
    history_days = len(values)
    total_units = int(sum(values))
    return ForecastResult(
        daily_rate=weighted_daily_rate(values),
        ma_7=moving_average(values, 7),
        ma_14=moving_average(values, 14),
        ma_30=moving_average(values, 30),
        sigma_daily=demand_std(values),
        history_days=history_days,
        total_units_in_history=total_units,
        confidence=classify_confidence(history_days, total_units),
    )


def rolling_backtest(
    values: Sequence[int], series_end: date, days: int = BACKTEST_DAYS
) -> list[BacktestPoint]:
    """One-step-ahead backtest over the most recent `days` days.

    For each day t in the window, the forecast is computed using ONLY data
    strictly before t (no look-ahead), then compared with what actually
    sold on t. `values` must end on `series_end`.
    """
    n = len(values)
    points: list[BacktestPoint] = []
    first = max(0, n - days)
    for t in range(first, n):
        day = series_end - timedelta(days=(n - 1 - t))
        points.append(
            BacktestPoint(
                day=day,
                actual=int(values[t]),
                forecast=weighted_daily_rate(values[:t]),
            )
        )
    return points


def wape(points: Sequence[BacktestPoint]) -> float | None:
    """Weighted absolute percentage error = sum|actual-forecast| / sum(actual).
    Robust to zero-demand days (unlike MAPE). None when nothing sold."""
    total_actual = sum(p.actual for p in points)
    if total_actual <= 0:
        return None
    return sum(abs(p.actual - p.forecast) for p in points) / total_actual
