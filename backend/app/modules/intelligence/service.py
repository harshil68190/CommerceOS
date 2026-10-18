"""
modules/intelligence/service.py

Responsibility
--------------
Orchestrates the intelligence use-cases: loads real stock + order data
through the repository, runs the pure engine for each stock position, and
shapes the results (dashboard KPIs, product drill-down, what-if
simulation). All business *decisions* live in the pure modules
(forecasting / projection / risk / reorder); this layer only wires data
in and aggregates results out.

Everything is read-only: the simulation never writes anything.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from app.core.exceptions import NotFoundError
from app.modules.intelligence.constants import (
    BACKTEST_DAYS,
    DEFAULT_LEAD_TIME_DAYS,
    FORECAST_WEIGHTS,
    FORECAST_WINDOWS,
    LOOKBACK_DAYS,
    RISK_RANK,
    SERVICE_LEVEL_Z,
    VALID_DEMAND_STATUSES,
    RiskLevel,
)
from app.modules.intelligence.engine import (
    PositionAnalysis,
    PositionInput,
    analyze_position,
)
from app.modules.intelligence.forecasting import (
    BacktestPoint,
    build_daily_series,
    resolve_history_start,
    wape,
)
from app.modules.intelligence.repository import (
    IntelligenceRepository,
    StockPositionRow,
)
from app.modules.intelligence.risk import risk_thresholds
from app.modules.intelligence.schemas import (
    Assumptions,
    DashboardResponse,
    DemandPointOut,
    ForecastOut,
    Kpis,
    PositionOut,
    PositionSummary,
    ProductAggregate,
    ProductIntelligenceResponse,
    ProjectionPointOut,
    ReorderOut,
    RiskCounts,
    RiskOut,
    ScenarioSummary,
    SimulationDelta,
    SimulationRequest,
    SimulationResponse,
)

MAX_CHANGED_POSITIONS = 100


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


@dataclass(frozen=True)
class _Context:
    as_of: date
    positions: list[PositionInput]


def _sort_key(a: PositionAnalysis) -> tuple:
    cover = a.risk.days_of_cover
    return (
        -RISK_RANK[a.risk.level],
        cover if cover is not None else float("inf"),
        a.position.product_name,
        a.position.warehouse_code,
    )


class IntelligenceService:
    def __init__(
        self,
        repository: IntelligenceRepository,
        today_provider: Callable[[], date] = utc_today,
    ) -> None:
        self.repo = repository
        self._today = today_provider

    # ------------------------------------------------------------------
    # Public use-cases
    # ------------------------------------------------------------------

    def get_dashboard(
        self,
        *,
        horizon_days: int,
        lead_time_days: int = DEFAULT_LEAD_TIME_DAYS,
        limit: int = 20,
    ) -> DashboardResponse:
        horizon_days = int(horizon_days)
        ctx = self._load_context()
        analyses = [
            analyze_position(
                p,
                as_of=ctx.as_of,
                horizon_days=horizon_days,
                lead_time_days=lead_time_days,
                include_backtest=True,
            )
            for p in ctx.positions
        ]

        high = sorted(
            (a for a in analyses if a.risk.level == RiskLevel.HIGH), key=_sort_key
        )
        to_order = sorted(
            (
                a
                for a in analyses
                if a.reorder.reorder_needed and a.reorder.recommended_quantity > 0
            ),
            key=lambda a: (_sort_key(a), -a.reorder.recommended_quantity),
        )

        trend = self._network_trend(analyses, ctx.as_of, horizon_days)
        trend_backtest = [
            BacktestPoint(day=t.day, actual=int(t.actual), forecast=t.forecast or 0.0)
            for t in trend
            if t.actual is not None
        ]

        return DashboardResponse(
            generated_at=datetime.now(timezone.utc),
            as_of_date=ctx.as_of,
            assumptions=self._assumptions(horizon_days, lead_time_days),
            kpis=self._kpis(analyses),
            high_risk=[self._summary(a) for a in high[:limit]],
            reorder_recommendations=[self._summary(a) for a in to_order[:limit]],
            demand_trend=trend,
            network_wape=_round_or_none(wape(trend_backtest), 4),
            has_demand_history=any(
                a.forecast.total_units_in_history > 0 for a in analyses
            ),
        )

    def get_product(
        self,
        product_id: uuid.UUID,
        *,
        horizon_days: int,
        lead_time_days: int = DEFAULT_LEAD_TIME_DAYS,
    ) -> ProductIntelligenceResponse:
        horizon_days = int(horizon_days)
        product = self.repo.get_product(product_id)
        if product is None:
            raise NotFoundError("Product not found.")

        ctx = self._load_context(product_id=product_id)
        analyses = sorted(
            (
                analyze_position(
                    p,
                    as_of=ctx.as_of,
                    horizon_days=horizon_days,
                    lead_time_days=lead_time_days,
                    include_backtest=True,
                )
                for p in ctx.positions
            ),
            key=_sort_key,
        )

        stockout_dates = [a.stockout_date for a in analyses if a.stockout_date]
        worst = (
            max((a.risk.level for a in analyses), key=lambda r: RISK_RANK[r])
            if analyses
            else RiskLevel.HEALTHY
        )
        aggregate = ProductAggregate(
            total_available=sum(a.available for a in analyses),
            total_daily_rate=round(sum(a.forecast.daily_rate for a in analyses), 4),
            total_recommended_quantity=sum(
                a.reorder.recommended_quantity for a in analyses
            ),
            worst_risk=worst,
            earliest_stockout_date=min(stockout_dates) if stockout_dates else None,
            projected_stockouts=sum(1 for a in analyses if a.stocks_out_in_horizon),
        )

        return ProductIntelligenceResponse(
            generated_at=datetime.now(timezone.utc),
            as_of_date=ctx.as_of,
            product_id=product.id,
            product_name=product.name,
            product_sku=product.sku,
            assumptions=self._assumptions(horizon_days, lead_time_days),
            aggregate=aggregate,
            positions=[self._position_out(a, ctx.as_of, horizon_days) for a in analyses],
            demand_trend=self._network_trend(analyses, ctx.as_of, horizon_days),
        )

    def simulate(
        self,
        request: SimulationRequest,
        *,
        lead_time_days: int | None = None,
    ) -> SimulationResponse:
        lead = (
            request.lead_time_days
            if request.lead_time_days is not None
            else (lead_time_days or DEFAULT_LEAD_TIME_DAYS)
        )
        if request.product_id is not None and self.repo.get_product(request.product_id) is None:
            raise NotFoundError("Product not found.")

        ctx = self._load_context(
            product_id=request.product_id, warehouse_id=request.warehouse_id
        )
        multiplier = 1.0 + request.demand_change_percent / 100.0
        horizon = int(request.horizon_days)

        deltas: list[tuple[PositionAnalysis, PositionAnalysis]] = []
        for p in ctx.positions:
            base = analyze_position(
                p, as_of=ctx.as_of, horizon_days=horizon,
                lead_time_days=lead,
            )
            scen = analyze_position(
                p, as_of=ctx.as_of, horizon_days=horizon,
                lead_time_days=lead, demand_multiplier=multiplier,
            )
            deltas.append((base, scen))

        base_summary = self._scenario_summary([b for b, _ in deltas])
        scen_summary = self._scenario_summary([s for _, s in deltas])

        changed: list[SimulationDelta] = []
        risk_changes = 0
        stockout_date_changes = 0
        newly_projected_stockouts = 0
        for base, scen in deltas:
            risk_changed = base.risk.level != scen.risk.level
            if risk_changed:
                risk_changes += 1
            stockout_date_changed = base.stockout_date != scen.stockout_date
            if stockout_date_changed:
                stockout_date_changes += 1
            extra = scen.reorder.recommended_quantity - base.reorder.recommended_quantity
            newly = scen.stocks_out_in_horizon and not base.stocks_out_in_horizon
            if newly:
                newly_projected_stockouts += 1
            if (
                risk_changed
                or newly
                or extra != 0
                or base.stocks_out_in_horizon != scen.stocks_out_in_horizon
                or base.stockout_date != scen.stockout_date
            ):
                changed.append(self._delta(base, scen, risk_changed, newly, extra))

        changed.sort(
            key=lambda d: (
                -RISK_RANK[d.scenario_risk],
                -d.additional_reorder_quantity,
                d.product_name,
            )
        )

        return SimulationResponse(
            generated_at=datetime.now(timezone.utc),
            as_of_date=ctx.as_of,
            demand_change_percent=request.demand_change_percent,
            assumptions=self._assumptions(horizon, lead),
            positions_analyzed=len(deltas),
            changed_positions_count=len(changed),
            baseline=base_summary,
            scenario=scen_summary,
            additional_projected_stockouts=(
                scen_summary.projected_stockouts - base_summary.projected_stockouts
            ),
            additional_reorder_units=(
                scen_summary.total_recommended_units - base_summary.total_recommended_units
            ),
            positions_with_risk_change=risk_changes,
            positions_with_stockout_date_change=stockout_date_changes,
            newly_projected_stockouts=newly_projected_stockouts,
            changed_positions=changed[:MAX_CHANGED_POSITIONS],
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_context(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
    ) -> _Context:
        as_of = self._today()
        series_end = as_of - timedelta(days=1)          # last completed day
        window_start = as_of - timedelta(days=LOOKBACK_DAYS)

        rows = self.repo.list_stock_positions(
            product_id=product_id, warehouse_id=warehouse_id
        )
        demand_rows = self.repo.get_daily_demand(
            start=window_start, end=series_end,
            product_id=product_id, warehouse_id=warehouse_id,
        )
        by_key: dict[tuple, dict[date, int]] = defaultdict(dict)
        for d in demand_rows:
            by_key[(d.product_id, d.warehouse_id)][d.day] = d.quantity

        return _Context(
            as_of=as_of,
            positions=[
                self._to_input(r, by_key.get((r.product_id, r.warehouse_id), {}),
                               as_of, series_end, window_start)
                for r in rows
            ],
        )

    @staticmethod
    def _to_input(
        row: StockPositionRow,
        demand_by_day: dict[date, int],
        as_of: date,
        series_end: date,
        window_start: date,
    ) -> PositionInput:
        history_start = resolve_history_start(
            window_start=window_start,
            as_of=as_of,
            inventory_created=row.inventory_created,
            first_demand=min(demand_by_day) if demand_by_day else None,
        )
        return PositionInput(
            product_id=row.product_id,
            product_name=row.product_name,
            product_sku=row.product_sku,
            warehouse_id=row.warehouse_id,
            warehouse_name=row.warehouse_name,
            warehouse_code=row.warehouse_code,
            quantity=row.quantity,
            reserved_quantity=row.reserved_quantity,
            reorder_level=row.reorder_level,
            max_stock=row.max_stock,
            history=build_daily_series(demand_by_day, history_start, series_end),
            series_end=series_end,
        )

    # ------------------------------------------------------------------
    # Shaping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assumptions(horizon_days: int, lead_time_days: int) -> Assumptions:
        t = risk_thresholds(lead_time_days)
        return Assumptions(
            horizon_days=horizon_days,
            lead_time_days=lead_time_days,
            service_level_z=SERVICE_LEVEL_Z,
            forecast_weights={
                f"ma_{w}": wt for w, wt in zip(FORECAST_WINDOWS, FORECAST_WEIGHTS)
            },
            risk_thresholds_days={
                "high": t.high_days, "medium": t.medium_days, "low": t.low_days,
            },
            demand_statuses=sorted(s.value for s in VALID_DEMAND_STATUSES),
            history_window_days=LOOKBACK_DAYS,
            notes=[
                "Demand counts confirmed, shipped and delivered orders only.",
                "Lead time is an assumption: the schema stores no supplier lead times.",
                "Stock already on order is not netted off: no purchase-order data exists.",
                "Demand during past stockouts is under-observed, so forecasts can run low.",
            ],
        )

    @staticmethod
    def _counts(analyses: list[PositionAnalysis]) -> RiskCounts:
        counts = RiskCounts()
        for a in analyses:
            setattr(counts, a.risk.level.value, getattr(counts, a.risk.level.value) + 1)
        return counts

    def _kpis(self, analyses: list[PositionAnalysis]) -> Kpis:
        return Kpis(
            total_positions=len(analyses),
            positions_with_demand=sum(1 for a in analyses if a.forecast.daily_rate > 0),
            risk_counts=self._counts(analyses),
            projected_stockouts=sum(1 for a in analyses if a.stocks_out_in_horizon),
            positions_needing_reorder=sum(
                1 for a in analyses
                if a.reorder.reorder_needed and a.reorder.recommended_quantity > 0
            ),
            total_recommended_units=sum(a.reorder.recommended_quantity for a in analyses),
            total_unserved_demand=round(sum(a.unserved_demand for a in analyses), 2),
        )

    def _scenario_summary(self, analyses: list[PositionAnalysis]) -> ScenarioSummary:
        k = self._kpis(analyses)
        return ScenarioSummary(
            risk_counts=k.risk_counts,
            projected_stockouts=k.projected_stockouts,
            positions_needing_reorder=k.positions_needing_reorder,
            total_recommended_units=k.total_recommended_units,
            total_unserved_demand=k.total_unserved_demand,
        )

    @staticmethod
    def _summary(a: PositionAnalysis) -> PositionSummary:
        p = a.position
        return PositionSummary(
            product_id=p.product_id,
            product_name=p.product_name,
            product_sku=p.product_sku,
            warehouse_id=p.warehouse_id,
            warehouse_name=p.warehouse_name,
            warehouse_code=p.warehouse_code,
            available=a.available,
            daily_rate=round(a.forecast.daily_rate, 2),
            days_of_cover=_round_or_none(a.risk.days_of_cover, 1),
            risk_level=a.risk.level,
            stockout_date=a.stockout_date,
            stocks_out_in_horizon=a.stocks_out_in_horizon,
            confidence=a.forecast.confidence,
            recommended_quantity=a.reorder.recommended_quantity,
            reorder_needed=a.reorder.reorder_needed,
        )

    @staticmethod
    def _delta(
        base: PositionAnalysis,
        scen: PositionAnalysis,
        risk_changed: bool,
        newly: bool,
        extra: int,
    ) -> SimulationDelta:
        p = base.position
        return SimulationDelta(
            product_id=p.product_id,
            product_name=p.product_name,
            product_sku=p.product_sku,
            warehouse_id=p.warehouse_id,
            warehouse_name=p.warehouse_name,
            warehouse_code=p.warehouse_code,
            available=base.available,
            baseline_daily_rate=round(base.forecast.daily_rate, 4),
            scenario_daily_rate=round(scen.forecast.daily_rate, 4),
            baseline_risk=base.risk.level,
            scenario_risk=scen.risk.level,
            risk_changed=risk_changed,
            baseline_stockout_date=base.stockout_date,
            scenario_stockout_date=scen.stockout_date,
            baseline_stocks_out_in_horizon=base.stocks_out_in_horizon,
            scenario_stocks_out_in_horizon=scen.stocks_out_in_horizon,
            newly_stocking_out=newly,
            baseline_recommended_quantity=base.reorder.recommended_quantity,
            scenario_recommended_quantity=scen.reorder.recommended_quantity,
            additional_reorder_quantity=extra,
        )

    @staticmethod
    def _position_out(a: PositionAnalysis, as_of: date, horizon_days: int) -> PositionOut:
        p = a.position
        f = a.forecast
        r = a.reorder
        history = [
            DemandPointOut(day=b.day, actual=b.actual, forecast=round(b.forecast, 3))
            for b in a.backtest
        ]
        history.extend(
            DemandPointOut(day=pt.day, forecast=round(f.daily_rate, 3))
            for pt in a.projection
        )
        return PositionOut(
            product_id=p.product_id,
            product_name=p.product_name,
            product_sku=p.product_sku,
            warehouse_id=p.warehouse_id,
            warehouse_name=p.warehouse_name,
            warehouse_code=p.warehouse_code,
            quantity=p.quantity,
            reserved_quantity=p.reserved_quantity,
            available=a.available,
            reorder_level=p.reorder_level,
            max_stock=p.max_stock,
            forecast=ForecastOut(
                daily_rate=round(f.daily_rate, 4),
                ma_7=round(f.ma_7, 4),
                ma_14=round(f.ma_14, 4),
                ma_30=round(f.ma_30, 4),
                sigma_daily=round(f.sigma_daily, 4),
                history_days=f.history_days,
                total_units_in_history=f.total_units_in_history,
                confidence=f.confidence,
                forecast_demand_horizon=round(a.forecast_demand_horizon, 2),
            ),
            risk=RiskOut(
                level=a.risk.level,
                days_of_cover=_round_or_none(a.risk.days_of_cover, 2),
                reasons=a.risk.reasons,
            ),
            stockout_date=a.stockout_date,
            stocks_out_in_horizon=a.stocks_out_in_horizon,
            unserved_demand=round(a.unserved_demand, 2),
            reorder=ReorderOut(
                available=r.available,
                lead_time_demand=round(r.lead_time_demand, 2),
                safety_stock=round(r.safety_stock, 2),
                computed_reorder_point=round(r.computed_reorder_point, 2),
                configured_reorder_level=r.configured_reorder_level,
                effective_reorder_point=r.effective_reorder_point,
                target_stock=r.target_stock,
                max_stock=r.max_stock,
                capped_by_max_stock=r.capped_by_max_stock,
                reorder_needed=r.reorder_needed,
                recommended_quantity=r.recommended_quantity,
                reasons=r.reasons,
            ),
            reasoning=a.reasoning,
            wape=_round_or_none(a.wape, 4),
            projection=[
                ProjectionPointOut(
                    day=pt.day,
                    projected_stock=round(pt.projected_stock, 2),
                    cumulative_demand=round(pt.cumulative_demand, 2),
                )
                for pt in a.projection
            ],
            demand_history=history,
        )

    @staticmethod
    def _network_trend(
        analyses: list[PositionAnalysis], as_of: date, horizon_days: int
    ) -> list[DemandPointOut]:
        """Sums per-position backtests (actual vs one-step-ahead forecast)
        for the last BACKTEST_DAYS, then appends the forward forecast."""
        actual: dict[date, float] = defaultdict(float)
        fcst: dict[date, float] = defaultdict(float)
        for a in analyses:
            for b in a.backtest:
                actual[b.day] += b.actual
                fcst[b.day] += b.forecast

        series_end = as_of - timedelta(days=1)
        points: list[DemandPointOut] = []
        for i in range(BACKTEST_DAYS - 1, -1, -1):
            day = series_end - timedelta(days=i)
            points.append(
                DemandPointOut(
                    day=day,
                    actual=round(actual.get(day, 0.0), 2),
                    forecast=round(fcst.get(day, 0.0), 2),
                )
            )
        forward = sum(a.forecast.daily_rate for a in analyses)
        for d in range(horizon_days):
            points.append(
                DemandPointOut(day=as_of + timedelta(days=d), forecast=round(forward, 2))
            )
        return points


def _round_or_none(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)
