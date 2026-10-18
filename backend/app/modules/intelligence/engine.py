"""
modules/intelligence/engine.py

Responsibility
--------------
Composes the pure building blocks (forecast -> projection -> risk ->
reorder) into one `PositionAnalysis` for a single product x warehouse
stock position. This is the single place the pipeline order is defined.
It performs no I/O, so the service can run it for what-if scenarios by
just changing `demand_multiplier`.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from app.modules.intelligence.forecasting import (
    BacktestPoint,
    ForecastResult,
    forecast_demand,
    rolling_backtest,
    wape,
)
from app.modules.intelligence.projection import (
    ProjectionPoint,
    project_inventory,
    stockout_date,
    stocks_out_within,
    unserved_demand,
)
from app.modules.intelligence.reorder import ReorderRecommendation, recommend_reorder
from app.modules.intelligence.risk import RiskAssessment, assess_risk
from app.modules.intelligence.constants import ForecastConfidence


@dataclass(frozen=True)
class PositionInput:
    """Everything the engine needs about one stock position."""

    product_id: object
    product_name: str
    product_sku: str
    warehouse_id: object
    warehouse_name: str
    warehouse_code: str
    quantity: int
    reserved_quantity: int
    reorder_level: int
    max_stock: int
    # Zero-filled daily units, oldest -> newest, ending yesterday and
    # starting at the position's history start.
    history: Sequence[int]
    series_end: date


@dataclass(frozen=True)
class PositionAnalysis:
    position: PositionInput
    available: int
    forecast: ForecastResult
    forecast_demand_horizon: float
    projection: list[ProjectionPoint]
    stockout_date: date | None
    stocks_out_in_horizon: bool
    unserved_demand: float
    risk: RiskAssessment
    reorder: ReorderRecommendation
    backtest: list[BacktestPoint] = field(default_factory=list)
    wape: float | None = None
    reasoning: list[str] = field(default_factory=list)


def analyze_position(
    pos: PositionInput,
    *,
    as_of: date,
    horizon_days: int,
    lead_time_days: int,
    demand_multiplier: float = 1.0,
    include_backtest: bool = False,
) -> PositionAnalysis:
    available = pos.quantity - pos.reserved_quantity

    base_forecast = forecast_demand(pos.history)
    forecast = (
        base_forecast
        if demand_multiplier == 1.0
        else base_forecast.scaled(demand_multiplier)
    )
    rate = forecast.daily_rate

    projection = project_inventory(as_of, available, rate, horizon_days)
    s_date = stockout_date(as_of, available, rate)
    out_in_horizon = stocks_out_within(as_of, available, rate, horizon_days)
    shortfall = unserved_demand(available, rate, horizon_days)

    risk = assess_risk(
        available=available,
        daily_rate=rate,
        lead_time_days=lead_time_days,
        reorder_level=pos.reorder_level,
    )
    reorder = recommend_reorder(
        available=available,
        daily_rate=rate,
        sigma_daily=forecast.sigma_daily,
        lead_time_days=lead_time_days,
        horizon_days=horizon_days,
        reorder_level=pos.reorder_level,
        max_stock=pos.max_stock,
    )

    backtest: list[BacktestPoint] = []
    accuracy: float | None = None
    if include_backtest:
        backtest = rolling_backtest(list(pos.history), pos.series_end)
        accuracy = wape(backtest)

    reasoning = _build_reasoning(
        pos, available, forecast, risk, s_date, out_in_horizon, horizon_days,
        demand_multiplier,
    )

    return PositionAnalysis(
        position=pos,
        available=available,
        forecast=forecast,
        forecast_demand_horizon=rate * horizon_days,
        projection=projection,
        stockout_date=s_date,
        stocks_out_in_horizon=out_in_horizon,
        unserved_demand=shortfall,
        risk=risk,
        reorder=reorder,
        backtest=backtest,
        wape=accuracy,
        reasoning=reasoning,
    )


def _build_reasoning(
    pos: PositionInput,
    available: int,
    forecast: ForecastResult,
    risk: RiskAssessment,
    s_date: date | None,
    out_in_horizon: bool,
    horizon_days: int,
    demand_multiplier: float,
) -> list[str]:
    lines: list[str] = []
    if forecast.confidence == ForecastConfidence.NONE:
        lines.append(
            "No confirmed/shipped/delivered orders were found in the history "
            "window, so demand is forecast at 0 units/day."
        )
    else:
        lines.append(
            f"Forecast {forecast.daily_rate:.2f} units/day = 0.5 x MA7 "
            f"({forecast.ma_7:.2f}) + 0.3 x MA14 ({forecast.ma_14:.2f}) + "
            f"0.2 x MA30 ({forecast.ma_30:.2f}), from {forecast.history_days} "
            f"days of history ({forecast.confidence.value} confidence)."
        )
        if demand_multiplier != 1.0:
            lines.append(
                f"Scenario: demand scaled by x{demand_multiplier:.2f} versus baseline."
            )
    lines.append(
        f"Available stock is {available} units "
        f"({pos.quantity} on hand - {pos.reserved_quantity} reserved)."
    )
    if s_date is not None:
        within = "inside" if out_in_horizon else "outside"
        lines.append(
            f"Projected stockout on {s_date.isoformat()}, {within} the "
            f"{horizon_days}-day horizon."
        )
    lines.extend(risk.reasons)
    return lines
