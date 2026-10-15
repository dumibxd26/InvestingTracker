from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import numpy as np
import pytest

from app.gbi import simulation as sim
from app.gbi.adapter import build_goal_spec, load_allocated_holdings
from app.gbi.constants import DEFAULT_SEED
from app.gbi.controller import analytical_bands, build_goal_insights
from app.gbi.domain import (
    AllocatedHolding,
    GoalSpec,
    Holding,
    TaxInflationProfile,
    TaxLot,
    to_plain,
)
from app.gbi.drift import evaluate_goal_portfolio, glide_path_targets, portfolio_volatility
from app.gbi.rebalance import select_optimal_tax_lots
from app.gbi.schemas import GoalPayload, YearlyPointPayload
from app.models import Currency, Goal, GoalType, RiskLevel

NOW = datetime(2026, 10, 14, tzinfo=UTC)
RATES = {("EUR", "USD"): 1.08, ("USD", "EUR"): 1 / 1.08, ("RON", "EUR"): 0.2, ("EUR", "RON"): 5.0}


def spot(source: str, target: str) -> float:
    return 1.0 if source == target else RATES[(source, target)]


def _profile(**overrides) -> TaxInflationProfile:
    values = {
        "annual_inflation_rate": 0.022,
        "long_term_cap_gains_rate": 0.03,
        "short_term_cap_gains_rate": 0.03,
        "dividend_and_interest_tax_rate": 0.10,
    }
    values.update(overrides)
    return TaxInflationProfile(**values)


def _goal(years: float = 10.0, **overrides) -> GoalSpec:
    values = {
        "goal_id": "goal-1",
        "name": "House",
        "base_currency": "EUR",
        "target_amount": 200000.0,
        "target_date": date(2026 + int(years), 10, 14),
        "monthly_contribution": 1000.0,
        "risk_profile": "MODERATE",
        "tax_profile": _profile(),
    }
    values.update(overrides)
    return GoalSpec(**values)


def _vwce(units: float = 250.0, price: float = 120.0) -> Holding:
    return Holding(
        holding_id="vwce",
        ticker="VWCE",
        name="Vanguard All-World",
        asset_class="BROAD_EQUITY_ETF",
        total_units=units,
        current_price=price,
        trading_currency="EUR",
        underlying_currency="USD",
        is_currency_hedged=False,
        tax_lots=[TaxLot("vwce-lot", date(2023, 1, 5), units, 95.0, 1.0)],
        capital_gains_rate=0.03,
    )


def _nvda() -> Holding:
    return Holding(
        holding_id="nvda",
        ticker="NVDA",
        name="NVIDIA",
        asset_class="BLUE_CHIP_STOCK",
        total_units=40.0,
        current_price=180.0,
        trading_currency="USD",
        underlying_currency="USD",
        is_currency_hedged=False,
        tax_lots=[TaxLot("nvda-lot", date(2025, 3, 1), 40.0, 90.0, 0.92)],
        beta=1.7,
        capital_gains_rate=0.03,
    )


def _deposit() -> Holding:
    return Holding(
        holding_id="deposit",
        ticker="Term",
        name="Term deposit",
        asset_class="CASH_DEPOSIT",
        total_units=1.0,
        current_price=8000.0,
        trading_currency="RON",
        underlying_currency="RON",
        is_currency_hedged=False,
        tax_lots=[TaxLot("deposit-lot", date(2025, 6, 1), 1.0, 7000.0, 0.2)],
        custom_yield=0.06,
        dividend_yield=0.06,
        capital_gains_rate=0.0,
    )


def test_goal_tax_profile_preserves_short_and_long_term_rates() -> None:
    holding = _vwce()
    holding.capital_gains_rate = 0.06
    holding.short_term_capital_gains_rate = 0.06
    holding.long_term_capital_gains_rate = 0.03
    allocations = [AllocatedHolding(holding, 100.0)]

    goal = Goal(
        id=uuid4(),
        user_id=uuid4(),
        name="Long term",
        goal_type=GoalType.WEALTH,
        target_amount=200000,
        target_currency=Currency.EUR,
        target_date=date(2036, 10, 14),
        risk_level=RiskLevel.MODERATE,
        monthly_contribution=1000,
    )
    goal_spec = build_goal_spec(goal, allocations, spot, default_capital_gains_rate=0.10)

    assert goal_spec.tax_profile.short_term_cap_gains_rate == pytest.approx(0.06)
    assert goal_spec.tax_profile.long_term_cap_gains_rate == pytest.approx(0.03)


def test_tax_lot_selection_uses_the_country_rate_for_each_holding_period() -> None:
    holding = _vwce(units=20.0)
    holding.capital_gains_rate = 0.06
    holding.short_term_capital_gains_rate = 0.06
    holding.long_term_capital_gains_rate = 0.03
    holding.long_term_holding_period_days = 365
    holding.tax_lots = [
        TaxLot("long", date(2024, 1, 1), 10.0, 95.0, 1.0),
        TaxLot("short", date(2026, 6, 1), 10.0, 95.0, 1.0),
    ]

    disposals = select_optimal_tax_lots(
        AllocatedHolding(holding, 100.0),
        target_gross_in_goal=2400.0,
        spot_rate_to_goal=1.0,
        long_term_rate=0.03,
        short_term_rate=0.06,
        now=NOW,
    )

    rates_by_lot = {item.lot_id: item.applicable_tax_rate for item in disposals}
    assert rates_by_lot == {"long": 0.03, "short": 0.06}


def test_mulberry32_matches_reference_sequence() -> None:
    uniforms = sim.mulberry32_uniforms(1, 3)
    assert uniforms[0] == pytest.approx(0.6270739405881613, abs=1e-15)
    assert uniforms[1] == pytest.approx(0.002735721180215478, abs=1e-15)
    assert uniforms[2] == pytest.approx(0.5274470399599522, abs=1e-15)


def test_mulberry32_is_deterministic_and_uniform() -> None:
    first = sim.mulberry32_uniforms(DEFAULT_SEED, 200_000)
    second = sim.mulberry32_uniforms(DEFAULT_SEED, 200_000)
    assert np.array_equal(first, second)
    assert first.min() >= 0.0 and first.max() < 1.0
    assert first.mean() == pytest.approx(0.5, abs=0.01)


def test_box_muller_shocks_are_standard_normal() -> None:
    shocks = sim.build_shocks(DEFAULT_SEED, 1000, 240)
    values = np.concatenate([shocks.z1.ravel(), shocks.z2.ravel()])
    assert values.mean() == pytest.approx(0.0, abs=0.02)
    assert values.std() == pytest.approx(1.0, abs=0.02)


def _loop_reference(params: sim.SimulationParams, paths: int, months: int) -> np.ndarray:
    """Month-by-month recursion matching the TypeScript reference, used to validate the prefix."""
    shocks = sim.build_shocks(DEFAULT_SEED, paths, months)
    key = sim._growth_key(params)
    drift, asset_step, fx_step, rho, yield_step, inflation, index_flag = key
    rho_complement = math.sqrt(1 - rho * rho)
    terminal = []
    for path in range(paths):
        for sign in (1.0, -1.0):
            balance = params.initial_balance
            basis = min(params.initial_balance, params.initial_cost_basis)
            for month in range(1, months + 1):
                z1 = shocks.z1[path, month - 1]
                z2 = shocks.z2[path, month - 1]
                combined = asset_step * z1 + fx_step * (rho * z1 + rho_complement * z2)
                deposit = params.monthly_contribution
                if index_flag:
                    deposit *= (1 + inflation) ** ((month - 1) // 12)
                if params.monthly_contributions is not None:
                    deposit = params.monthly_contributions[month - 1]
                dividend = balance * yield_step
                balance = balance * math.exp(drift + sign * combined) + dividend + deposit
                basis += dividend + deposit
            net = balance
            if balance > basis and not params.is_tax_advantaged:
                taxable = max(0, balance - basis - params.tax_profile.annual_tax_free_allowance)
                net = balance - taxable * params.tax_profile.long_term_cap_gains_rate
            terminal.append(net)
    return np.array(terminal)


def test_prefix_simulation_matches_month_by_month_recursion() -> None:
    params = sim.SimulationParams(
        initial_balance=37466.0,
        initial_cost_basis=27762.0,
        monthly_contribution=1000.0,
        weighted_local_return_mu=0.0858,
        weighted_dividend_yield=0.02,
        weighted_local_volatility_sigma=0.19,
        unhedged_foreign_weight=0.6,
        expected_fx_drift_annual=0.003,
        horizon_months=36,
        target_amount=60000.0,
        tax_profile=_profile(index_contributions_to_inflation=True),
    )
    reference = _loop_reference(params, paths=20, months=36)
    prefix = sim._growth_prefix(sim._growth_key(params), DEFAULT_SEED, 20, 36)
    columns = np.array([36])
    gross_pos, basis_pos = sim._gross_and_basis(
        prefix.positive, columns, params, prefix.deposit_units
    )
    gross_neg, basis_neg = sim._gross_and_basis(
        prefix.negative, columns, params, prefix.deposit_units
    )
    vectorized = np.concatenate(
        [
            sim._after_tax(gross_pos, basis_pos, params)[:, -1],
            sim._after_tax(gross_neg, basis_neg, params)[:, -1],
        ]
    )
    assert np.allclose(np.sort(vectorized), np.sort(reference), rtol=1e-9)


def test_monte_carlo_is_reproducible_and_terminal_success_matches_full_run() -> None:
    goal = _goal()
    evaluation = evaluate_goal_portfolio(goal, [AllocatedHolding(_vwce(), 100.0)], spot, NOW)
    horizon = round(evaluation.remaining_years * 12)
    params = sim._base_params(goal, evaluation, horizon)
    first = sim.run_monte_carlo(params)
    second = sim.run_monte_carlo(params)
    assert first.success_probability == second.success_probability
    assert len(first.yearly_schedule) == math.ceil(horizon / 12) + 1
    prefix = sim._growth_prefix(sim._growth_key(params), DEFAULT_SEED, sim.HALF_PATHS, horizon)
    assert sim._terminal_success(params, prefix, horizon) == first.success_probability
    start_gain = evaluation.total_current_value - evaluation.total_cost_basis
    expected_year_zero = evaluation.total_current_value - start_gain * 0.03
    assert first.yearly_schedule[0].nominal_after_tax["p50"] == pytest.approx(
        expected_year_zero, abs=0.01
    )


def test_glide_path_shifts_from_equities_to_cash_and_bonds() -> None:
    long_horizon = glide_path_targets(15.0, "MODERATE")
    short_horizon = glide_path_targets(1.0, "MODERATE")
    assert sum(long_horizon.weights.values()) == pytest.approx(1.0, abs=1e-6)
    assert (
        long_horizon.weights["EQUITIES"] > glide_path_targets(6.0, "MODERATE").weights["EQUITIES"]
    )
    assert short_horizon.weights == {"CASH": 0.8, "BONDS": 0.2, "EQUITIES": 0.0}
    assert (
        glide_path_targets(10.0, "AGGRESSIVE").weights["EQUITIES"]
        > glide_path_targets(10.0, "CONSERVATIVE").weights["EQUITIES"]
    )


def test_portfolio_volatility_uses_bucket_covariance_and_concentration() -> None:
    single_bucket = portfolio_volatility({"CASH": 0.0, "BONDS": 0.0, "EQUITIES": 0.16}, [])
    assert single_bucket == pytest.approx(0.16)
    with_concentration = portfolio_volatility({"CASH": 0.0, "BONDS": 0.0, "EQUITIES": 0.16}, [0.5])
    assert with_concentration > single_bucket


def test_tax_lot_selection_prefers_lowest_tax_per_dollar() -> None:
    holding = Holding(
        holding_id="h",
        ticker="H",
        name="H",
        asset_class="BROAD_EQUITY_ETF",
        total_units=20.0,
        current_price=100.0,
        trading_currency="EUR",
        underlying_currency="EUR",
        is_currency_hedged=False,
        tax_lots=[
            TaxLot("high-basis", date(2020, 1, 1), 10.0, 95.0, 1.0),
            TaxLot("low-basis", date(2020, 1, 1), 10.0, 40.0, 1.0),
        ],
    )
    disposals = select_optimal_tax_lots(
        AllocatedHolding(holding, 100.0), 1500.0, 1.0, 0.1, 0.1, NOW
    )
    assert [item.lot_id for item in disposals] == ["high-basis", "low-basis"]
    assert disposals[0].realized_gain_or_loss == pytest.approx(50.0, abs=0.01)
    assert sum(item.proceeds_in_goal_currency for item in disposals) == pytest.approx(1500.0)


def test_evaluation_flags_single_stock_cap_and_unhedged_safe_asset() -> None:
    goal = _goal(years=10.0)
    bond = Holding(
        holding_id="bond",
        ticker="BND",
        name="Core bond",
        asset_class="INVESTMENT_BOND",
        total_units=10.0,
        current_price=100.0,
        trading_currency="USD",
        underlying_currency="USD",
        is_currency_hedged=False,
        tax_lots=[TaxLot("bond-lot", date(2024, 1, 1), 10.0, 95.0, 0.92)],
    )
    allocations = [
        AllocatedHolding(_nvda(), 100.0),
        AllocatedHolding(_vwce(), 100.0),
        AllocatedHolding(bond, 100.0),
    ]
    evaluation = evaluate_goal_portfolio(goal, allocations, spot, NOW)
    reasons = {warning.reason for warning in evaluation.warnings}
    assert "SINGLE_STOCK_CAP" in reasons
    assert "SAFE_ASSET_FX_MISMATCH" in reasons
    assert evaluation.requires_rebalancing
    assert sum(item.weight_in_goal for item in evaluation.slices) == pytest.approx(1.0)


def test_contribution_routing_sums_to_monthly_amount_and_fills_underweight_buckets() -> None:
    goal = _goal(years=10.0)
    allocations = [AllocatedHolding(_vwce(), 100.0), AllocatedHolding(_deposit(), 100.0)]
    insights = build_goal_insights(goal, allocations, spot, NOW, half_paths=200)
    routing = insights.rebalance_plan.monthly_contribution_routing
    assert sum(item.allocated_contribution for item in routing) == pytest.approx(1000.0, abs=0.05)
    by_bucket = {item.bucket: item.allocated_contribution for item in routing}
    assert by_bucket["EQUITIES"] == pytest.approx(0.0)


def test_after_tax_value_deducts_sale_tax_on_gains_only() -> None:
    goal = _goal()
    evaluation = evaluate_goal_portfolio(goal, [AllocatedHolding(_vwce(), 100.0)], spot, NOW)
    gain = evaluation.total_current_value - evaluation.total_cost_basis
    assert gain > 0
    assert evaluation.after_tax_value == pytest.approx(evaluation.total_current_value - gain * 0.03)
    deposit_only = evaluate_goal_portfolio(goal, [AllocatedHolding(_deposit(), 100.0)], spot, NOW)
    assert deposit_only.after_tax_value == pytest.approx(deposit_only.total_current_value)


def test_partial_allocation_scales_value_and_cost() -> None:
    goal = _goal()
    full = evaluate_goal_portfolio(goal, [AllocatedHolding(_vwce(), 100.0)], spot, NOW)
    half = evaluate_goal_portfolio(goal, [AllocatedHolding(_vwce(), 50.0)], spot, NOW)
    assert half.total_current_value == pytest.approx(full.total_current_value / 2)
    assert half.total_cost_basis == pytest.approx(full.total_cost_basis / 2)


def test_on_track_goal_returns_no_recovery_levers() -> None:
    goal = _goal(years=20.0, target_amount=1000.0, monthly_contribution=500.0)
    insights = build_goal_insights(
        goal, [AllocatedHolding(_vwce(), 100.0)], spot, NOW, half_paths=300
    )
    assert insights.recovery.is_goal_on_track
    assert insights.recovery.plans.increase_contribution_plan is None
    assert insights.recovery.plans.extend_timeline_plan is None
    assert insights.recovery.plans.optimize_portfolio_plan is None


def test_off_track_goal_solves_contribution_and_timeline_levers() -> None:
    goal = _goal(years=5.0, target_amount=400000.0, monthly_contribution=500.0)
    insights = build_goal_insights(
        goal, [AllocatedHolding(_vwce(units=50.0), 100.0)], spot, NOW, half_paths=300
    )
    recovery = insights.recovery
    assert not recovery.is_goal_on_track
    plan = recovery.plans.increase_contribution_plan
    assert plan is not None
    assert plan.required_monthly_contribution >= goal.monthly_contribution
    assert plan.resulting_success_probability >= goal.target_success_probability
    timeline = recovery.plans.extend_timeline_plan
    assert (timeline is not None) != ("EXTEND_TIMELINE" in recovery.plans.unreachable_levers)
    if timeline is not None:
        assert timeline.resulting_success_probability >= goal.target_success_probability
    assert recovery.plans.optimize_portfolio_plan is not None


def test_analytical_bands_are_ordered_and_grow_with_return() -> None:
    goal = _goal()
    bands = analytical_bands(goal, 0.08, 0.15, 10000.0, 120)
    assert bands.optimistic_rate > bands.expected_rate > bands.conservative_rate
    assert bands.projected_value_optimistic > bands.projected_value_expected
    assert bands.projected_value_expected > bands.projected_value_conservative


def test_insights_are_deterministic_and_serializable() -> None:
    goal = _goal()
    allocations = [AllocatedHolding(_vwce(), 100.0), AllocatedHolding(_nvda(), 100.0)]
    first = build_goal_insights(goal, allocations, spot, NOW, half_paths=200)
    second = build_goal_insights(goal, allocations, spot, NOW, half_paths=200)
    assert first.simulation.success_probability == second.simulation.success_probability
    payload = to_plain(first)
    assert payload["goal"]["target_date"] == goal.target_date.isoformat()
    assert set(payload) >= {"evaluation", "rebalance_plan", "simulation", "recovery"}


def _simulation_params(**overrides) -> sim.SimulationParams:
    values = {
        "initial_balance": 1000.0,
        "initial_cost_basis": 800.0,
        "monthly_contribution": 100.0,
        "weighted_local_return_mu": 0.0,
        "weighted_dividend_yield": 0.0,
        "weighted_local_volatility_sigma": 0.0,
        "unhedged_foreign_weight": 0.0,
        "expected_fx_drift_annual": 0.0,
        "horizon_months": 18,
        "target_amount": 10000.0,
        "tax_profile": _profile(annual_inflation_rate=0.0),
    }
    values.update(overrides)
    return sim.SimulationParams(**values)


@pytest.mark.parametrize("tax_advantaged", [False, True])
def test_variable_lump_sums_match_recursion_including_dividend_basis(tax_advantaged) -> None:
    params = _simulation_params(
        monthly_contributions=(5000.0, 0.0, 20.0, 0.0, 800.0, 2000.0) * 6,
        horizon_months=36,
        weighted_local_return_mu=0.08,
        weighted_dividend_yield=0.03,
        weighted_local_volatility_sigma=0.15,
        unhedged_foreign_weight=0.4,
        expected_fx_drift_annual=0.01,
        is_tax_advantaged=tax_advantaged,
        tax_profile=_profile(index_contributions_to_inflation=True, annual_tax_free_allowance=50.0),
    )
    if tax_advantaged:
        params = replace(
            params,
            tax_profile=replace(params.tax_profile, dividend_and_interest_tax_rate=0.0),
        )
    reference = _loop_reference(params, paths=20, months=36)
    prefix = sim._growth_prefix(
        sim._growth_key(params), DEFAULT_SEED, 20, 36, params.monthly_contributions
    )
    values = []
    for path in (prefix.positive, prefix.negative):
        gross, basis = sim._gross_and_basis(path, np.array([36]), params, prefix.deposit_units)
        values.append(sim._after_tax(gross, basis, params).ravel())
    assert np.sort(np.concatenate(values)) == pytest.approx(np.sort(reference), abs=1e-7)
    result = sim.run_monte_carlo(params, half_paths=20)
    assert result.terminal_nominal_after_tax_p50 == sim._quantile(np.sort(reference), 0.5)


@pytest.mark.parametrize("indexed", [False, True])
def test_explicit_schedule_equivalent_to_legacy_scalar(indexed) -> None:
    scalar = _simulation_params(
        horizon_months=36,
        weighted_local_return_mu=0.08,
        weighted_dividend_yield=0.02,
        weighted_local_volatility_sigma=0.15,
        tax_profile=_profile(index_contributions_to_inflation=indexed),
    )
    schedule = tuple(
        scalar.monthly_contribution
        * ((1 + scalar.tax_profile.annual_inflation_rate) ** (month // 12) if indexed else 1)
        for month in range(36)
    )
    explicit = replace(scalar, monthly_contributions=schedule)
    assert to_plain(sim.run_monte_carlo(explicit, half_paths=30)) == to_plain(
        sim.run_monte_carlo(scalar, half_paths=30)
    )


@pytest.mark.parametrize("real_target", [False, True])
def test_inflation_factors_use_actual_partial_year_month(real_target) -> None:
    factors = (1.0,) + (1.1,) * 11 + (1.2,) * 6 + (1.8,)
    params = _simulation_params(
        inflation_factors=factors,
        tax_profile=_profile(
            annual_inflation_rate=0.99,
            is_target_in_todays_dollars=real_target,
            long_term_cap_gains_rate=0.0,
        ),
    )
    result = sim.run_monte_carlo(params, half_paths=2)
    assert [point.month_offset for point in result.yearly_schedule] == [0, 12, 18]
    assert result.yearly_schedule[-1].real_todays_dollars["p50"] == round(2800 / 1.8, 2)
    assert result.yearly_schedule[-1].inflated_target_at_year == (
        18000.0 if real_target else 10000.0
    )
    assert result.nominal_target_at_maturity == (18000.0 if real_target else 10000.0)
    assert result.real_target_in_todays_dollars == (
        10000.0 if real_target else round(10000 / 1.8, 2)
    )
    assert result.terminal_real_todays_dollars_p50 == round(2800 / 1.8, 2)


def test_scalar_inflation_partial_year_deflates_at_maturity_not_rounded_year() -> None:
    params = _simulation_params(
        tax_profile=_profile(annual_inflation_rate=0.1, long_term_cap_gains_rate=0.0)
    )
    result = sim.run_monte_carlo(params, half_paths=2)
    assert result.yearly_schedule[-1].inflated_target_at_year == round(10000 * 1.1**1.5, 2)
    assert result.yearly_schedule[-1].real_todays_dollars["p50"] == (
        result.terminal_real_todays_dollars_p50
    )


def test_analytical_bands_use_month_end_schedule_and_ignore_scalar() -> None:
    schedule = (1000.0, 0.0, 50.0, 250.0)
    goal = _goal(monthly_contribution=99999, monthly_contributions=schedule)
    bands = analytical_bands(goal, 0.08, 0.1, 100.0, 4)
    for rate, value in (
        (bands.expected_rate, bands.projected_value_expected),
        (bands.optimistic_rate, bands.projected_value_optimistic),
        (bands.conservative_rate, bands.projected_value_conservative),
    ):
        expected = 100.0
        for contribution in schedule:
            expected = expected * math.exp(rate / 12) + contribution
        assert value == pytest.approx(expected)
    assert analytical_bands(goal, 0, 0, 100, 4).projected_value_expected == sum(schedule) + 100


def _deterministic_evaluation(goal):
    evaluation = evaluate_goal_portfolio(goal, [AllocatedHolding(_vwce(), 100)], spot, NOW)
    return replace(
        evaluation,
        remaining_years=1.0,
        total_current_value=0.0,
        total_cost_basis=0.0,
        weighted_local_return_mu=0.0,
        weighted_dividend_yield=0.0,
        weighted_local_volatility_sigma=0.0,
        unhedged_foreign_weight=0.0,
        unhedged_fx_drift=0.0,
    )


def test_recovery_adds_constant_nominal_amount_preserving_lump_sums() -> None:
    schedule = (100.0,) + (0.0,) * 4 + (2000.0,) + (0.0,) * 6
    goal = _goal(
        monthly_contribution=100.0,
        monthly_contributions=schedule,
        target_amount=10000.0,
        tax_profile=_profile(annual_inflation_rate=0, index_contributions_to_inflation=True),
    )
    evaluation = _deterministic_evaluation(goal)
    current, recovery = sim.solve_recovery(goal, evaluation, half_paths=4)
    plan = recovery.plans.increase_contribution_plan
    assert current.terminal_nominal_after_tax_p50 == 2100
    assert plan is not None
    assert plan.additional_monthly_needed == 659
    assert plan.required_monthly_contribution == 759
    assert "extra nominal" in plan.description and "atop scheduled savings" in plan.description
    assert goal.monthly_contributions == schedule
    params = sim._base_params(goal, evaluation, 12)
    improved = replace(
        params,
        monthly_contributions=tuple(value + plan.additional_monthly_needed for value in schedule),
    )
    assert (
        sim.run_monte_carlo(improved, half_paths=4).success_probability
        == (plan.resulting_success_probability)
        == 1.0
    )
    assert recovery.plans.extend_timeline_plan is None
    assert "EXTEND_TIMELINE" in recovery.plans.unreachable_levers


def test_recovery_preserves_indexed_scalar_savings_and_adds_only_nominal_extra() -> None:
    goal = _goal(
        monthly_contribution=100,
        target_amount=10000,
        tax_profile=_profile(
            annual_inflation_rate=0.5,
            is_target_in_todays_dollars=False,
            index_contributions_to_inflation=True,
        ),
    )
    evaluation = replace(_deterministic_evaluation(goal), remaining_years=2.0)
    current, recovery = sim.solve_recovery(goal, evaluation, half_paths=2)
    assert current.terminal_nominal_after_tax_p50 == 3000
    plan = recovery.plans.increase_contribution_plan
    assert plan is not None
    assert plan.additional_monthly_needed == 292
    assert plan.required_monthly_contribution == 392
    assert plan.resulting_success_probability == 1


def test_nominal_addition_preserves_dividend_basis_on_identical_shocks() -> None:
    params = _simulation_params(
        monthly_contributions=(500.0, 0.0, 20.0) * 6,
        weighted_local_return_mu=0.1,
        weighted_dividend_yield=0.04,
        weighted_local_volatility_sigma=0.2,
    )
    extra = 250.0
    improved = replace(
        params, monthly_contributions=tuple(value + extra for value in params.monthly_contributions)
    )
    prefixes = [
        sim._growth_prefix(sim._growth_key(p), DEFAULT_SEED, 10, 18, p.monthly_contributions)
        for p in (params, improved)
    ]
    for sign in ("positive", "negative"):
        gross, basis = sim._gross_and_basis(
            getattr(prefixes[0], sign),
            np.array([12, 18]),
            params,
            prefixes[0].deposit_units,
            additional_monthly=extra,
        )
        expected_gross, expected_basis = sim._gross_and_basis(
            getattr(prefixes[1], sign), np.array([12, 18]), improved, prefixes[1].deposit_units
        )
        assert gross == pytest.approx(expected_gross)
        assert basis == pytest.approx(expected_basis)


def test_extension_uses_future_lump_sum_and_first_success_despite_later_inflation() -> None:
    width = 12 + sim.MAX_EXTENSION_MONTHS
    schedule = (0.0,) * 13 + (20000.0,) + (0.0,) * (width - 14)
    factors = (1.0,) * 15 + (3.0,) * (width - 14)
    goal = _goal(
        monthly_contribution=0,
        monthly_contributions=schedule,
        inflation_factors=factors,
        target_amount=10000,
    )
    _, recovery = sim.solve_recovery(goal, _deterministic_evaluation(goal), half_paths=4)
    plan = recovery.plans.extend_timeline_plan
    assert plan is not None
    assert plan.additional_months_needed == 2
    assert plan.resulting_success_probability == 1.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"monthly_contributions": (-1.0,)},
        {"monthly_contributions": (float("nan"),)},
        {"monthly_contributions": (float("inf"),)},
        {"inflation_factors": ()},
        {"inflation_factors": (2.0,)},
        {"inflation_factors": (1.0, 0.0)},
        {"inflation_factors": (1.0, -1.0)},
        {"inflation_factors": (1.0, float("nan"))},
        {"inflation_factors": (1.0, float("inf"))},
    ],
)
def test_invalid_schedule_values_are_rejected(overrides) -> None:
    with pytest.raises(ValueError):
        _goal(**overrides)
    with pytest.raises(ValueError):
        _simulation_params(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [{"monthly_contributions": (100.0,) * 17}, {"inflation_factors": (1.0,) * 18}],
)
def test_short_schedules_are_not_extrapolated(overrides) -> None:
    with pytest.raises(ValueError, match="does not cover"):
        sim.run_monte_carlo(_simulation_params(**overrides), half_paths=2)
    goal = _goal(**overrides)
    evaluation = replace(_deterministic_evaluation(goal), remaining_years=1.5)
    with pytest.raises(ValueError, match="does not cover"):
        sim.solve_recovery(goal, evaluation, half_paths=2)


def test_analytical_bands_reject_short_contribution_schedule() -> None:
    with pytest.raises(ValueError, match="does not cover"):
        analytical_bands(_goal(monthly_contributions=(100.0,)), 0, 0, 0, 2)


@pytest.mark.parametrize("inflation", [0.0, 0.073])
@pytest.mark.parametrize("basis", ["real", "nominal"])
def test_adapter_honors_explicit_goal_inflation_and_money_basis(inflation, basis) -> None:
    goal = SimpleNamespace(
        id=uuid4(),
        name="Goal",
        target_currency=Currency.EUR,
        target_amount=10000,
        target_date=date(2036, 1, 1),
        monthly_contribution=100,
        risk_level=RiskLevel.MODERATE,
        annual_inflation_rate=inflation,
        target_money_basis=basis,
    )
    spec = build_goal_spec(goal, [], spot, default_capital_gains_rate=0.03)
    assert spec.tax_profile.annual_inflation_rate == inflation
    assert spec.tax_profile.is_target_in_todays_dollars == (basis == "real")


@pytest.mark.parametrize("manual_cash", [0.0, 2500.0])
def test_adapter_includes_manual_cash_once_without_changing_linked_assets(manual_cash) -> None:
    goal = SimpleNamespace(
        id=uuid4(), user_id=uuid4(), target_currency=Currency.EUR, current_amount=manual_cash
    )
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    loaded, notes = load_allocated_holdings(session, goal, spot, NOW.date(), 0.03)
    loaded_again, _ = load_allocated_holdings(session, goal, spot, NOW.date(), 0.03)
    assert len(loaded) == len(loaded_again) == (1 if manual_cash else 0)
    assert notes == []
    spec = _goal()
    linked = AllocatedHolding(_vwce(), 100)
    legacy = evaluate_goal_portfolio(spec, [linked], spot, NOW)
    combined = evaluate_goal_portfolio(spec, [linked, *loaded], spot, NOW)
    assert combined.total_current_value == legacy.total_current_value + manual_cash
    assert combined.total_cost_basis == legacy.total_cost_basis + manual_cash
    assert combined.after_tax_value == legacy.after_tax_value + manual_cash
    if manual_cash:
        cash = next(item for item in combined.slices if item.ticker == "CASH")
        assert cash.local_expected_return == cash.local_volatility == 0
        assert cash.effective_dividend_yield == cash.unhedged_fx_drift == 0
        assert cash.after_tax_market_value == manual_cash
        cash_only = evaluate_goal_portfolio(spec, loaded, spot, NOW)
        params = replace(
            sim._base_params(spec, cash_only, 12),
            monthly_contribution=0.0,
        )
        result = sim.run_monte_carlo(params, half_paths=2)
        assert result.terminal_nominal_after_tax_p50 == manual_cash
        assert result.estimated_median_tax_paid_at_liquidation == 0
        model = SimpleNamespace(
            id=goal.id,
            name="Manual and linked",
            target_currency=Currency.EUR,
            target_amount=100000,
            target_date=date(2036, 1, 1),
            monthly_contribution=100,
            risk_level=RiskLevel.MODERATE,
        )
        legacy_profile = build_goal_spec(model, [linked], spot, 0.03).tax_profile
        combined_profile = build_goal_spec(model, [linked, *loaded], spot, 0.03).tax_profile
        assert combined_profile.long_term_cap_gains_rate == legacy_profile.long_term_cap_gains_rate


def test_configured_inflation_changes_foreign_parity_not_same_currency_returns() -> None:
    spec = _goal(tax_profile=_profile(annual_inflation_rate=0.1))
    foreign = evaluate_goal_portfolio(spec, [AllocatedHolding(_vwce(), 100)], spot, NOW)
    assert foreign.slices[0].unhedged_fx_drift == pytest.approx(0.1 - 0.025)
    domestic_holding = replace(_vwce(), underlying_currency="EUR")
    domestic = evaluate_goal_portfolio(spec, [AllocatedHolding(domestic_holding, 100)], spot, NOW)
    assert domestic.slices[0].unhedged_fx_drift == 0
    assert domestic.slices[0].effective_return_in_goal == domestic.slices[0].local_expected_return


def test_schedule_payloads_preserve_vectors_and_actual_month_offsets() -> None:
    goal = _goal(
        monthly_contributions=(0.0, 5000.0, 100.0),
        inflation_factors=(1.0, 1.01, 1.03, 1.04),
    )
    payload = GoalPayload.model_validate(to_plain(goal))
    assert payload.monthly_contributions == goal.monthly_contributions
    assert payload.inflation_factors == goal.inflation_factors
    params = _simulation_params(
        horizon_months=3,
        monthly_contributions=goal.monthly_contributions,
        inflation_factors=goal.inflation_factors,
    )
    result = sim.run_monte_carlo(params, half_paths=2)
    point = YearlyPointPayload.model_validate(to_plain(result.yearly_schedule[-1]))
    assert point.month_offset == 3
