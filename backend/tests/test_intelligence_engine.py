"""
tests/test_intelligence_engine.py

Unit tests for the pure CommerceOS Intelligence calculation modules:
forecasting, projection (stockout), risk, reorder and the composing
engine. None of these touch the database; every expected value below can
be re-derived by hand from the formulas documented in each module.
"""

from datetime import date, timedelta
from math import inf, nan, sqrt
from uuid import uuid4

import pytest

from app.modules.intelligence.constants import ForecastConfidence, RiskLevel
from app.modules.intelligence.engine import PositionInput, analyze_position
from app.modules.intelligence.forecasting import (
    BacktestPoint,
    build_daily_series,
    classify_confidence,
    demand_std,
    forecast_demand,
    moving_average,
    resolve_history_start,
    rolling_backtest,
    wape,
    weighted_daily_rate,
)
from app.modules.intelligence.projection import (
    days_of_cover,
    project_inventory,
    stockout_date,
    stockout_day_number,
    stocks_out_within,
    unserved_demand,
)
from app.modules.intelligence.reorder import recommend_reorder
from app.modules.intelligence.risk import assess_risk, max_risk, risk_thresholds

AS_OF = date(2026, 3, 10)


# =========================================================================
# Forecasting
# =========================================================================


class TestDailySeries:
    def test_zero_fills_missing_days(self):
        series = build_daily_series(
            {date(2026, 3, 2): 3, date(2026, 3, 5): 1},
            date(2026, 3, 1),
            date(2026, 3, 5),
        )
        assert series == [0, 3, 0, 0, 1]

    def test_end_before_start_is_empty(self):
        assert build_daily_series({}, date(2026, 3, 5), date(2026, 3, 4)) == []

    def test_single_day_window(self):
        assert build_daily_series({date(2026, 3, 1): 7}, date(2026, 3, 1), date(2026, 3, 1)) == [7]

    def test_days_outside_window_are_ignored(self):
        series = build_daily_series(
            {date(2026, 2, 1): 99, date(2026, 3, 1): 2}, date(2026, 3, 1), date(2026, 3, 2)
        )
        assert series == [2, 0]


class TestHistoryStart:
    WINDOW = date(2026, 1, 10)

    def test_uses_inventory_creation_when_earlier_than_first_sale(self):
        start = resolve_history_start(
            window_start=self.WINDOW, as_of=AS_OF,
            inventory_created=date(2026, 2, 10), first_demand=date(2026, 2, 15),
        )
        assert start == date(2026, 2, 10)

    def test_uses_first_sale_when_earlier_than_inventory_creation(self):
        start = resolve_history_start(
            window_start=self.WINDOW, as_of=AS_OF,
            inventory_created=date(2026, 3, 1), first_demand=date(2026, 2, 5),
        )
        assert start == date(2026, 2, 5)

    def test_clipped_to_window_start(self):
        start = resolve_history_start(
            window_start=self.WINDOW, as_of=AS_OF,
            inventory_created=date(2025, 1, 1), first_demand=None,
        )
        assert start == self.WINDOW

    def test_clipped_to_as_of_when_everything_is_in_the_future(self):
        start = resolve_history_start(
            window_start=self.WINDOW, as_of=AS_OF,
            inventory_created=date(2026, 6, 1), first_demand=None,
        )
        assert start == AS_OF

    def test_no_information_defaults_to_as_of(self):
        start = resolve_history_start(
            window_start=self.WINDOW, as_of=AS_OF, inventory_created=None, first_demand=None
        )
        assert start == AS_OF


class TestMovingAverageAndRate:
    def test_moving_average_uses_last_n_values(self):
        assert moving_average([1, 2, 3, 4], 2) == 3.5

    def test_window_larger_than_history_uses_all_values(self):
        assert moving_average([1, 2, 3, 4], 10) == 2.5

    def test_empty_history_is_zero(self):
        assert moving_average([], 7) == 0.0
        assert weighted_daily_rate([]) == 0.0

    def test_constant_demand_forecasts_the_constant(self):
        assert weighted_daily_rate([10] * 30) == pytest.approx(10.0)

    def test_short_history_is_not_diluted(self):
        # Only 3 days exist: every window collapses to those 3 days.
        assert weighted_daily_rate([4, 4, 4]) == pytest.approx(4.0)

    def test_weighted_blend_matches_hand_calculation(self):
        series = [0] * 23 + [7] * 7   # 30 days, last 7 days sell 7/day
        ma7, ma14, ma30 = 7.0, 49 / 14, 49 / 30
        expected = 0.5 * ma7 + 0.3 * ma14 + 0.2 * ma30
        assert weighted_daily_rate(series) == pytest.approx(expected)
        assert expected == pytest.approx(4.87666667, rel=1e-6)

    def test_recent_surge_raises_forecast_above_long_average(self):
        flat = weighted_daily_rate([5] * 30)
        surge = weighted_daily_rate([5] * 23 + [15] * 7)
        assert surge > flat

    def test_only_last_30_days_matter(self):
        old_spike = [1000] + [5] * 30
        assert weighted_daily_rate(old_spike) == pytest.approx(5.0)


class TestDemandStd:
    def test_known_sample_standard_deviation(self):
        values = [2, 4, 4, 4, 5, 5, 7, 9]   # mean 5, SS 32, n-1 = 7
        assert demand_std(values) == pytest.approx(sqrt(32 / 7))

    def test_constant_series_has_zero_deviation(self):
        assert demand_std([6] * 20) == 0.0

    def test_fewer_than_two_points_is_zero(self):
        assert demand_std([]) == 0.0
        assert demand_std([5]) == 0.0

    def test_window_limits_observations(self):
        assert demand_std([100] + [3] * 30) == 0.0


class TestConfidence:
    @pytest.mark.parametrize(
        "history_days,units,expected",
        [
            (0, 0, ForecastConfidence.NONE),
            (40, 0, ForecastConfidence.NONE),     # long history but never sold
            (10, 5, ForecastConfidence.LOW),
            (13, 5, ForecastConfidence.LOW),
            (14, 5, ForecastConfidence.MEDIUM),
            (29, 5, ForecastConfidence.MEDIUM),
            (30, 5, ForecastConfidence.HIGH),
            (60, 5, ForecastConfidence.HIGH),
        ],
    )
    def test_boundaries(self, history_days, units, expected):
        assert classify_confidence(history_days, units) == expected

    def test_forecast_demand_bundles_everything(self):
        result = forecast_demand([2, 2, 2, 2])
        assert result.history_days == 4
        assert result.total_units_in_history == 8
        assert result.daily_rate == pytest.approx(2.0)
        assert result.confidence == ForecastConfidence.LOW

    def test_scaled_scales_rate_and_sigma_but_not_history(self):
        base = forecast_demand([1, 3, 1, 3, 1, 3])
        scaled = base.scaled(1.5)
        assert scaled.daily_rate == pytest.approx(base.daily_rate * 1.5)
        assert scaled.sigma_daily == pytest.approx(base.sigma_daily * 1.5)
        assert scaled.history_days == base.history_days
        assert scaled.confidence == base.confidence


class TestBacktest:
    def test_forecast_uses_only_prior_days(self):
        values = [0, 0, 0, 10, 10]
        points = rolling_backtest(values, date(2026, 3, 5), days=3)
        assert [p.day for p in points] == [date(2026, 3, 3), date(2026, 3, 4), date(2026, 3, 5)]
        assert [p.actual for p in points] == [0, 10, 10]
        # Day 4 actual is 10 but the forecast must not know that yet.
        assert points[0].forecast == 0.0
        assert points[1].forecast == 0.0
        assert points[2].forecast == pytest.approx(2.5)

    def test_window_longer_than_history_returns_all_days(self):
        points = rolling_backtest([1, 2], date(2026, 3, 2), days=14)
        assert len(points) == 2

    def test_empty_history(self):
        assert rolling_backtest([], AS_OF) == []

    def test_wape_hand_calculation(self):
        points = rolling_backtest([0, 0, 0, 10, 10], date(2026, 3, 5), days=3)
        # (|0-0| + |10-0| + |10-2.5|) / 20
        assert wape(points) == pytest.approx(0.875)

    def test_wape_is_none_when_nothing_sold(self):
        pts = [BacktestPoint(day=AS_OF, actual=0, forecast=1.0)]
        assert wape(pts) is None

    def test_perfect_forecast_has_zero_wape(self):
        pts = [BacktestPoint(day=AS_OF, actual=5, forecast=5.0)]
        assert wape(pts) == 0.0


# =========================================================================
# Projection / stockout
# =========================================================================


class TestDaysOfCover:
    def test_basic(self):
        assert days_of_cover(100, 10) == 10

    def test_no_demand_is_infinite(self):
        assert days_of_cover(100, 0) is None

    def test_negative_available_is_zero(self):
        assert days_of_cover(-5, 10) == 0


class TestStockoutDay:
    @pytest.mark.parametrize(
        "available,rate,expected",
        [
            (100, 10, 10),     # exactly divisible
            (101, 10, 11),     # one unit over -> next day
            (95, 10, 10),
            (1, 10, 1),
            (0, 5, 0),         # already out
            (-3, 5, 0),
            (100, 0, None),    # no demand
            (3, 1.5, 2),
            (7, 0.7, 10),      # 7/0.7 = 10.000000000000002 in floats
        ],
    )
    def test_day_number(self, available, rate, expected):
        assert stockout_day_number(available, rate) == expected

    def test_stockout_date_is_the_day_the_last_unit_goes(self):
        assert stockout_date(AS_OF, 100, 10) == AS_OF + timedelta(days=9)

    def test_stockout_today_when_stock_below_one_day_of_demand(self):
        assert stockout_date(AS_OF, 5, 10) == AS_OF

    def test_already_out_stocks_out_today(self):
        assert stockout_date(AS_OF, 0, 4) == AS_OF

    def test_no_demand_means_no_stockout_date(self):
        assert stockout_date(AS_OF, 50, 0) is None

    @pytest.mark.parametrize("rate", [0.0, -1.0, inf, -inf, nan])
    def test_invalid_or_nonpositive_rate_has_no_stockout_date(self, rate):
        assert stockout_date(AS_OF, 50, rate) is None

    def test_extremely_small_rate_has_no_representable_stockout_date(self):
        assert stockout_date(AS_OF, 50, 1e-300) is None

    def test_stockout_date_beyond_supported_date_range_is_none(self):
        assert stockout_date(date.max, 2, 1) is None

    def test_normal_future_stockout_date_is_preserved(self):
        assert stockout_date(AS_OF, 11, 1) == AS_OF + timedelta(days=10)

    def test_within_horizon_boundaries(self):
        assert stocks_out_within(AS_OF, 100, 10, 10) is True    # d* == horizon
        assert stocks_out_within(AS_OF, 100, 10, 9) is False
        assert stocks_out_within(AS_OF, 100, 0, 30) is False


class TestProjection:
    def test_projected_stock_and_cumulative_demand(self):
        pts = project_inventory(AS_OF, 25, 10, 3)
        assert [p.projected_stock for p in pts] == [15, 5, 0]
        assert [p.cumulative_demand for p in pts] == [10, 20, 30]
        assert [p.day for p in pts] == [AS_OF, AS_OF + timedelta(1), AS_OF + timedelta(2)]

    def test_projection_never_goes_negative(self):
        assert min(p.projected_stock for p in project_inventory(AS_OF, 5, 100, 5)) == 0

    def test_zero_demand_is_flat(self):
        assert {p.projected_stock for p in project_inventory(AS_OF, 40, 0, 7)} == {40}

    def test_length_matches_horizon(self):
        for h in (7, 14, 30):
            assert len(project_inventory(AS_OF, 10, 1, h)) == h

    def test_unserved_demand(self):
        assert unserved_demand(25, 10, 3) == 5
        assert unserved_demand(100, 10, 3) == 0
        assert unserved_demand(-4, 10, 3) == 30


# =========================================================================
# Risk
# =========================================================================


def _risk(available, rate=1.0, lead=7, reorder_level=0):
    return assess_risk(
        available=available, daily_rate=rate, lead_time_days=lead, reorder_level=reorder_level
    )


class TestRiskBoundaries:
    """rate = 1 unit/day so days-of-cover == available. L = 7."""

    @pytest.mark.parametrize(
        "available,expected",
        [
            (0, RiskLevel.HIGH),
            (1, RiskLevel.HIGH),
            (7, RiskLevel.HIGH),       # cover == 1 x L is inclusive-high
            (8, RiskLevel.MEDIUM),
            (14, RiskLevel.MEDIUM),    # cover == 2 x L is inclusive-medium
            (15, RiskLevel.LOW),
            (28, RiskLevel.LOW),       # cover == 4 x L is inclusive-low
            (29, RiskLevel.HEALTHY),
            (1000, RiskLevel.HEALTHY),
        ],
    )
    def test_default_lead_time(self, available, expected):
        assert _risk(available).level == expected

    @pytest.mark.parametrize(
        "available,expected",
        [(3, RiskLevel.HIGH), (4, RiskLevel.MEDIUM), (6, RiskLevel.MEDIUM),
         (7, RiskLevel.LOW), (12, RiskLevel.LOW), (13, RiskLevel.HEALTHY)],
    )
    def test_thresholds_scale_with_lead_time(self, available, expected):
        assert _risk(available, lead=3).level == expected

    def test_exact_fractional_boundary(self):
        # 21 units at 3/day is exactly 7.0 days of cover.
        assert _risk(21, rate=3.0).level == RiskLevel.HIGH

    def test_thresholds_object(self):
        t = risk_thresholds(5)
        assert (t.high_days, t.medium_days, t.low_days) == (5, 10, 20)

    def test_days_of_cover_is_reported(self):
        assert _risk(50, rate=5.0).days_of_cover == pytest.approx(10.0)


class TestRiskSpecialCases:
    def test_no_demand_is_healthy_regardless_of_stock(self):
        for stock in (0, 5, 500):
            r = _risk(stock, rate=0.0)
            assert r.level == RiskLevel.HEALTHY
            assert r.days_of_cover is None

    def test_zero_stock_with_no_demand_explains_itself(self):
        r = _risk(0, rate=0.0)
        assert any("no recent demand" in s.lower() for s in r.reasons)

    def test_zero_stock_with_demand_is_high_and_cover_zero(self):
        r = _risk(0, rate=2.0)
        assert r.level == RiskLevel.HIGH
        assert r.days_of_cover == 0

    def test_negative_available_is_high(self):
        assert _risk(-3, rate=2.0).level == RiskLevel.HIGH

    def test_reorder_level_floor_raises_low_to_medium(self):
        assert _risk(20).level == RiskLevel.LOW
        raised = _risk(20, reorder_level=20)
        assert raised.level == RiskLevel.MEDIUM
        assert any("reorder level" in s for s in raised.reasons)

    def test_reorder_level_never_lowers_risk(self):
        assert _risk(3, reorder_level=50).level == RiskLevel.HIGH

    def test_reorder_level_ignored_without_demand(self):
        assert _risk(2, rate=0.0, reorder_level=10).level == RiskLevel.HEALTHY

    def test_zero_reorder_level_does_not_trigger_floor(self):
        assert _risk(20, reorder_level=0).level == RiskLevel.LOW

    def test_every_assessment_has_reasons(self):
        for stock in (0, 5, 10, 20, 100):
            assert _risk(stock).reasons

    def test_max_risk_ordering(self):
        assert max_risk(RiskLevel.LOW, RiskLevel.HIGH) == RiskLevel.HIGH
        assert max_risk(RiskLevel.MEDIUM, RiskLevel.HEALTHY) == RiskLevel.MEDIUM
        assert max_risk(RiskLevel.HEALTHY, RiskLevel.HEALTHY) == RiskLevel.HEALTHY


# =========================================================================
# Reorder
# =========================================================================


def _reorder(**kw):
    params = dict(
        available=50, daily_rate=10.0, sigma_daily=0.0, lead_time_days=7,
        horizon_days=30, reorder_level=0, max_stock=0,
    )
    params.update(kw)
    return recommend_reorder(**params)


class TestReorderCalculation:
    def test_hand_calculated_baseline(self):
        r = _reorder()
        assert r.lead_time_demand == pytest.approx(70)
        assert r.safety_stock == 0
        assert r.effective_reorder_point == 70
        assert r.target_stock == 370          # 10 x (7 + 30)
        assert r.reorder_needed is True
        assert r.recommended_quantity == 320  # 370 - 50

    def test_reorder_triggers_at_reorder_point_inclusive(self):
        assert _reorder(available=70).reorder_needed is True
        assert _reorder(available=70).recommended_quantity == 300
        assert _reorder(available=71).reorder_needed is False
        assert _reorder(available=71).recommended_quantity == 0

    def test_safety_stock_formula(self):
        r = _reorder(daily_rate=5.0, sigma_daily=2.0, lead_time_days=4,
                     horizon_days=10, available=10)
        assert r.safety_stock == pytest.approx(1.65 * 2.0 * sqrt(4))   # 6.6
        assert r.effective_reorder_point == 27                          # ceil(20 + 6.6)
        assert r.target_stock == 77                                     # ceil(70 + 6.6)
        assert r.recommended_quantity == 67

    def test_higher_variability_means_more_stock(self):
        calm = _reorder(sigma_daily=0.0, available=0)
        noisy = _reorder(sigma_daily=5.0, available=0)
        assert noisy.recommended_quantity > calm.recommended_quantity

    def test_configured_reorder_level_raises_reorder_point(self):
        r = _reorder(daily_rate=1.0, reorder_level=50, available=40)
        assert r.effective_reorder_point == 50
        assert r.target_stock == 50              # max(ceil(37), 50)
        assert r.recommended_quantity == 10

    def test_max_stock_caps_target(self):
        r = _reorder(max_stock=200)
        assert r.capped_by_max_stock is True
        assert r.target_stock == 200
        assert r.recommended_quantity == 150

    def test_max_stock_zero_means_uncapped(self):
        r = _reorder(max_stock=0)
        assert r.capped_by_max_stock is False
        assert r.target_stock == 370

    def test_max_stock_above_target_does_not_cap(self):
        r = _reorder(max_stock=5000)
        assert r.capped_by_max_stock is False
        assert r.target_stock == 370

    def test_max_stock_below_reorder_point_warns(self):
        r = _reorder(max_stock=60)
        assert r.target_stock == 60
        assert r.recommended_quantity == 10
        assert any(s.startswith("Warning") for s in r.reasons)

    def test_never_recommends_negative_quantity(self):
        assert _reorder(available=10_000).recommended_quantity == 0

    def test_negative_available_is_treated_as_zero(self):
        r = _reorder(available=-5)
        assert r.available == 0
        assert r.recommended_quantity == 370

    def test_zero_demand_and_zero_reorder_level_orders_nothing(self):
        r = _reorder(daily_rate=0.0, available=0)
        assert r.recommended_quantity == 0

    def test_zero_demand_still_respects_configured_reorder_level(self):
        r = _reorder(daily_rate=0.0, available=4, reorder_level=10)
        assert r.reorder_needed is True
        assert r.recommended_quantity == 6

    def test_float_noise_does_not_inflate_quantity(self):
        # 1.1 * 10 == 11.000000000000002 in binary floating point
        r = _reorder(daily_rate=1.1, lead_time_days=10, horizon_days=0, available=0)
        assert r.target_stock == 11
        assert r.recommended_quantity == 11

    def test_result_is_an_integer(self):
        assert isinstance(_reorder(daily_rate=3.3).recommended_quantity, int)

    def test_reasons_explain_each_step(self):
        text = " ".join(_reorder().reasons)
        for fragment in ("Lead-time demand", "Safety stock", "Reorder point", "Order-up-to"):
            assert fragment in text


# =========================================================================
# Engine composition
# =========================================================================


def _position(history, *, quantity=120, reserved=20, reorder_level=0, max_stock=0):
    return PositionInput(
        product_id=uuid4(), product_name="Widget", product_sku="W-1",
        warehouse_id=uuid4(), warehouse_name="Main", warehouse_code="MAIN",
        quantity=quantity, reserved_quantity=reserved,
        reorder_level=reorder_level, max_stock=max_stock,
        history=history, series_end=AS_OF - timedelta(days=1),
    )


def _analyze(pos, **kw):
    params = dict(as_of=AS_OF, horizon_days=30, lead_time_days=7)
    params.update(kw)
    return analyze_position(pos, **params)


class TestEngine:
    def test_available_is_quantity_minus_reserved(self):
        a = _analyze(_position([10] * 30))
        assert a.available == 100

    def test_flat_demand_end_to_end(self):
        a = _analyze(_position([10] * 30))        # 100 available, 10/day
        assert a.forecast.daily_rate == pytest.approx(10.0)
        assert a.risk.days_of_cover == pytest.approx(10.0)
        assert a.risk.level == RiskLevel.MEDIUM
        assert a.stockout_date == AS_OF + timedelta(days=9)
        assert a.stocks_out_in_horizon is True
        assert a.forecast_demand_horizon == pytest.approx(300)
        assert a.unserved_demand == pytest.approx(200)
        assert a.reorder.reorder_needed is False     # 100 > ROP of 70
        assert len(a.projection) == 30

    def test_october_18_reference_keeps_low_demand_stockout_in_the_future(self):
        reference_date = date(2026, 10, 18)
        # A single unit in the 30-day window produces a 0.0067/day blend.
        pos = _position([0] * 10 + [1] + [0] * 19, quantity=1000, reserved=0)
        baseline = analyze_position(
            pos, as_of=reference_date, horizon_days=30, lead_time_days=7,
        )
        scenario = analyze_position(
            pos, as_of=reference_date, horizon_days=30, lead_time_days=7,
            demand_multiplier=1.1,
        )

        assert baseline.stockout_date is not None
        assert scenario.stockout_date is not None
        assert baseline.stockout_date >= reference_date
        assert scenario.stockout_date >= reference_date
        assert baseline.forecast.daily_rate == pytest.approx(1 / 150)
        assert scenario.forecast.daily_rate == pytest.approx(1 / 150 * 1.1)
        assert baseline.risk.level == scenario.risk.level == RiskLevel.HEALTHY
        assert baseline.stocks_out_in_horizon is False
        assert scenario.stocks_out_in_horizon is False
        assert baseline.risk.thresholds == scenario.risk.thresholds

    def test_already_depleted_stock_is_high_and_stockout_is_today(self):
        reference_date = date(2026, 10, 18)
        result = analyze_position(
            _position([1] * 30, quantity=10, reserved=10),
            as_of=reference_date,
            horizon_days=30,
            lead_time_days=7,
        )
        assert result.stockout_date == reference_date
        assert result.risk.level == RiskLevel.HIGH

    def test_stockout_outside_short_horizon(self):
        a = _analyze(_position([10] * 30), horizon_days=7)
        assert a.stockout_date == AS_OF + timedelta(days=9)
        assert a.stocks_out_in_horizon is False
        assert a.unserved_demand == 0

    def test_demand_multiplier_changes_outcome(self):
        pos = _position([10] * 30)
        base = _analyze(pos)
        surge = _analyze(pos, demand_multiplier=1.5)
        assert surge.forecast.daily_rate == pytest.approx(15.0)
        assert surge.risk.level == RiskLevel.HIGH
        assert base.risk.level == RiskLevel.MEDIUM
        assert surge.reorder.recommended_quantity == 455    # 15 x 37 - 100
        assert base.reorder.recommended_quantity == 0

    def test_zero_multiplier_removes_all_risk(self):
        a = _analyze(_position([10] * 30), demand_multiplier=0.0)
        assert a.risk.level == RiskLevel.HEALTHY
        assert a.stockout_date is None
        assert a.stocks_out_in_horizon is False

    def test_no_history_is_healthy_with_no_forecast(self):
        a = _analyze(_position([]))
        assert a.forecast.daily_rate == 0
        assert a.forecast.confidence == ForecastConfidence.NONE
        assert a.risk.level == RiskLevel.HEALTHY
        assert a.stockout_date is None
        assert any("No confirmed" in line for line in a.reasoning)

    def test_all_zero_history_is_healthy(self):
        a = _analyze(_position([0] * 30))
        assert a.risk.level == RiskLevel.HEALTHY
        assert a.forecast.confidence == ForecastConfidence.NONE

    def test_out_of_stock_with_demand(self):
        a = _analyze(_position([5] * 30, quantity=10, reserved=10))
        assert a.available == 0
        assert a.risk.level == RiskLevel.HIGH
        assert a.stockout_date == AS_OF
        assert a.reorder.recommended_quantity > 0

    def test_backtest_only_when_requested(self):
        pos = _position([3] * 30)
        assert _analyze(pos).backtest == []
        with_bt = _analyze(pos, include_backtest=True)
        assert len(with_bt.backtest) == 14
        assert with_bt.wape == pytest.approx(0.0)    # perfectly flat demand

    def test_deterministic(self):
        pos = _position([1, 4, 2, 8, 3, 0, 5] * 5)
        first = _analyze(pos, include_backtest=True)
        second = _analyze(pos, include_backtest=True)
        assert first == second

    def test_reasoning_mentions_forecast_stock_and_risk(self):
        text = " ".join(_analyze(_position([10] * 30)).reasoning)
        assert "Forecast" in text
        assert "Available stock is 100" in text
        assert "covers" in text
