from __future__ import annotations

import math
from datetime import datetime

from app.gbi.constants import (
    CURRENCY_INFLATION_PARITY,
    DEFAULT_BENCHMARK_CATALOG,
    DEFAULT_SEED,
    EQUITY_FX_CORRELATION,
    FX_VOLATILITY,
    HALF_PATHS,
)
from app.gbi.domain import AllocatedHolding, AnalyticalBands, GoalInsights, GoalSpec
from app.gbi.drift import SpotRate, evaluate_goal_portfolio
from app.gbi.rebalance import generate_rebalance_plan
from app.gbi.simulation import solve_recovery


def analytical_bands(
    goal: GoalSpec, evaluation_mu: float, evaluation_sigma: float, start_value: float, months: int
) -> AnalyticalBands:
    """Closed-form median and +/-0.5 sigma rate bands for instant slider feedback."""
    expected = evaluation_mu - 0.5 * evaluation_sigma**2
    optimistic = expected + 0.5 * evaluation_sigma
    conservative = expected - 0.5 * evaluation_sigma
    contribution = goal.monthly_contribution

    def projected(rate: float) -> float:
        monthly_growth = math.exp(rate / 12.0)
        if abs(monthly_growth - 1.0) < 1e-12:
            annuity = float(months)
        else:
            annuity = (monthly_growth**months - 1.0) / (monthly_growth - 1.0)
        return start_value * monthly_growth**months + contribution * annuity

    return AnalyticalBands(
        expected_rate=expected,
        optimistic_rate=optimistic,
        conservative_rate=conservative,
        projected_value_expected=projected(expected),
        projected_value_optimistic=projected(optimistic),
        projected_value_conservative=projected(conservative),
        months_remaining=months,
    )


def build_goal_insights(
    goal: GoalSpec,
    allocations: list[AllocatedHolding],
    spot_rate: SpotRate,
    now: datetime,
    *,
    seed: int = DEFAULT_SEED,
    half_paths: int = HALF_PATHS,
    notes: list[str] | None = None,
) -> GoalInsights:
    evaluation = evaluate_goal_portfolio(goal, allocations, spot_rate, now)
    plan = generate_rebalance_plan(goal, evaluation, allocations, DEFAULT_BENCHMARK_CATALOG, now)
    simulation, recovery = solve_recovery(goal, evaluation, seed=seed, half_paths=half_paths)
    months = max(1, round(evaluation.remaining_years * 12))
    bands = analytical_bands(
        goal,
        evaluation.expected_return_mu,
        evaluation.portfolio_volatility_sigma,
        evaluation.total_current_value,
        months,
    )

    tax = goal.tax_profile
    inflation = CURRENCY_INFLATION_PARITY[goal.base_currency]
    assumptions = [
        "Capital-market assumptions are long-run baselines, not forecasts.",
        f"Inflation parity for {goal.base_currency}: {inflation * 100:.1f}% a year; the target "
        + (
            "is in today's money and is inflated each year."
            if tax.is_target_in_todays_dollars
            else "is a fixed nominal amount."
        ),
        f"Capital gains are taxed at {tax.long_term_cap_gains_rate * 100:.1f}% when liquidated; "
        f"dividends and interest are taxed at {tax.dividend_and_interest_tax_rate * 100:.1f}% "
        "each year.",
        "Each holding is modelled as one tax lot with cost converted at today's FX rate, "
        "because historical FX rates are not stored.",
        "Deposits are valued at accrued value and modelled with their stated annual rate.",
        "The value today is after estimated sale tax, as on the dashboard. Allocation weights "
        "and the projection start from market value and tax gains at liquidation.",
        f"Unhedged FX volatility is {FX_VOLATILITY * 100:.1f}% with a "
        f"{EQUITY_FX_CORRELATION:.2f} equity-FX correlation.",
        f"Simulation uses {2 * half_paths:,} antithetic paths with seed {seed}; "
        "results are deterministic for the same inputs.",
        "Only the stocks, ETFs and deposits linked to this goal are modelled; manual progress "
        "entered on the goal is excluded.",
    ]
    assumptions.extend(notes or [])

    return GoalInsights(
        goal=goal,
        remaining_years=evaluation.remaining_years,
        evaluation=evaluation,
        rebalance_plan=plan,
        simulation=simulation,
        recovery=recovery,
        analytical_bands=bands,
        assumptions=assumptions,
    )
