from __future__ import annotations

import math
from datetime import UTC, date, datetime
from uuid import uuid4

import numpy as np
import pytest

from app.gbi import simulation as sim
from app.gbi.adapter import build_goal_spec
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
                dividend = balance * yield_step
                balance = balance * math.exp(drift + sign * combined) + dividend + deposit
                basis += dividend + deposit
            net = balance
            if balance > basis:
                net = balance - (balance - basis) * params.tax_profile.long_term_cap_gains_rate
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
