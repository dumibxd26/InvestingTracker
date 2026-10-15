from __future__ import annotations

import math
from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache

import numpy as np

from app.gbi.constants import (
    DEFAULT_SEED,
    EQUITY_FX_CORRELATION,
    FX_VOLATILITY,
    GLIDE_UNHEDGED_SHARE_OF_EQUITIES,
    HALF_PATHS,
    MAX_EXTENSION_MONTHS,
)
from app.gbi.domain import (
    ContributionLeverPlan,
    GoalEvaluation,
    GoalRecovery,
    GoalSpec,
    MonteCarloResult,
    PortfolioLeverPlan,
    RecoveryPlans,
    TaxInflationProfile,
    TimelineLeverPlan,
    YearlyPercentileSchedulePoint,
    validate_schedules,
)
from app.gbi.drift import glide_path_targets, target_mix_statistics

_INCREMENT = np.uint32(0x6D2B79F5)
_ONE = np.uint32(1)
_SIXTY_ONE = np.uint32(61)
_SHIFT_7 = np.uint32(7)
_SHIFT_14 = np.uint32(14)
_SHIFT_15 = np.uint32(15)
_TWO_POW_32 = 4294967296.0
_MONTH = 1.0 / 12.0
_QUANTILES = (("p10", 0.10), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p90", 0.90))
_BISECTION_STEPS = 14


def mulberry32_uniforms(seed: int, count: int) -> np.ndarray:
    """Vectorized Mulberry32: the state advances by a constant, so every output is independent.

    uint32 arithmetic wraps modulo 2**32, which matches the 32-bit integer operations of the
    reference algorithm.
    """
    index = np.arange(1, count + 1, dtype=np.uint32)
    state = np.uint32(seed & 0xFFFFFFFF) + index * _INCREMENT
    value = (state ^ (state >> _SHIFT_15)) * (state | _ONE)
    value = value + (value ^ (value >> _SHIFT_7)) * (value | _SIXTY_ONE) ^ value
    value = value ^ (value >> _SHIFT_14)
    return value.astype(np.float64) / _TWO_POW_32


@dataclass(frozen=True)
class ShockMatrix:
    z1: np.ndarray
    z2: np.ndarray


@lru_cache(maxsize=4)
def build_shocks(seed: int, half_paths: int, width: int) -> ShockMatrix:
    """Standard normal shocks via Box-Muller; row = antithetic path pair, column = month."""
    uniforms = mulberry32_uniforms(seed, half_paths * width * 2).reshape(half_paths, width, 2)
    u1 = np.maximum(uniforms[..., 0], 1e-12)
    u2 = uniforms[..., 1]
    radius = np.sqrt(-2.0 * np.log(u1))
    theta = 2.0 * np.pi * u2
    return ShockMatrix(z1=radius * np.cos(theta), z2=radius * np.sin(theta))


@dataclass(frozen=True)
class SimulationParams:
    """Explicit deposit and inflation vectors override their legacy scalar assumptions."""

    initial_balance: float
    initial_cost_basis: float
    monthly_contribution: float
    weighted_local_return_mu: float
    weighted_dividend_yield: float
    weighted_local_volatility_sigma: float
    unhedged_foreign_weight: float
    expected_fx_drift_annual: float
    horizon_months: int
    target_amount: float
    tax_profile: TaxInflationProfile
    is_tax_advantaged: bool = False
    fx_volatility_annual: float = FX_VOLATILITY
    asset_fx_correlation: float = EQUITY_FX_CORRELATION
    monthly_contributions: tuple[float, ...] | None = None
    inflation_factors: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        validate_schedules(self.monthly_contributions, self.inflation_factors)


def contribution_schedule(
    monthly_contribution: float,
    monthly_contributions: tuple[float, ...] | None,
    tax_profile: TaxInflationProfile,
    months: int,
) -> np.ndarray:
    """Return nominal month-end deposits, never extrapolating an explicit schedule."""
    if monthly_contributions is not None:
        if len(monthly_contributions) < months:
            raise ValueError("monthly_contributions does not cover the requested horizon")
        return np.asarray(monthly_contributions[:months], dtype=float)
    offsets = np.arange(months)
    weights = (
        (1.0 + tax_profile.annual_inflation_rate) ** (offsets // 12)
        if tax_profile.index_contributions_to_inflation
        else np.ones(months)
    )
    return monthly_contribution * weights


def _validate_horizon(params: SimulationParams, months: int) -> None:
    if params.monthly_contributions is not None and len(params.monthly_contributions) < months:
        raise ValueError("monthly_contributions does not cover the requested horizon")
    if params.inflation_factors is not None and len(params.inflation_factors) <= months:
        raise ValueError("inflation_factors does not cover the requested horizon")


def _inflation_factor(params: SimulationParams, months: int) -> float:
    if params.inflation_factors is not None:
        if len(params.inflation_factors) <= months:
            raise ValueError("inflation_factors does not cover the requested horizon")
        return params.inflation_factors[months]
    return (1.0 + params.tax_profile.annual_inflation_rate) ** (months / 12.0)


@dataclass(frozen=True)
class _PathPrefix:
    """Cumulative terms that let any (contribution, horizon) be evaluated without re-simulating.

    Column k describes the state after k months: ``cumulative`` is the growth product P_k,
    ``growth_index`` is sum(g_j / P_j), ``balance_weight`` is sum(P_{j-1}) and
    ``contribution_weight`` is sum(P_{j-1} * growth_index_{j-1}).
    """

    cumulative: np.ndarray
    growth_index: np.ndarray
    balance_weight: np.ndarray
    contribution_weight: np.ndarray
    nominal_growth_index: np.ndarray | None = None
    nominal_contribution_weight: np.ndarray | None = None


@dataclass(frozen=True)
class _GrowthPrefix:
    positive: _PathPrefix
    negative: _PathPrefix
    deposit_units: np.ndarray


def _path_prefix(
    growth: np.ndarray, deposit_weights: np.ndarray, *, scheduled: bool = False
) -> _PathPrefix:
    paths = growth.shape[0]
    zeros = np.zeros((paths, 1))
    cumulative = np.concatenate([np.ones((paths, 1)), np.cumprod(growth, axis=1)], axis=1)
    growth_index = np.concatenate(
        [zeros, np.cumsum(deposit_weights / cumulative[:, 1:], axis=1)], axis=1
    )
    balance_weight = np.concatenate([zeros, np.cumsum(cumulative[:, :-1], axis=1)], axis=1)
    contribution_weight = np.concatenate(
        [zeros, np.cumsum(cumulative[:, :-1] * growth_index[:, :-1], axis=1)], axis=1
    )
    nominal_index = None
    nominal_weight = None
    if scheduled:
        nominal_index = np.concatenate([zeros, np.cumsum(1.0 / cumulative[:, 1:], axis=1)], axis=1)
        nominal_weight = np.concatenate(
            [zeros, np.cumsum(cumulative[:, :-1] * nominal_index[:, :-1], axis=1)], axis=1
        )
    return _PathPrefix(
        cumulative, growth_index, balance_weight, contribution_weight, nominal_index, nominal_weight
    )


def _dividend_tax_rate(params: SimulationParams) -> float:
    if params.is_tax_advantaged:
        return 0.0
    return params.tax_profile.dividend_and_interest_tax_rate


def _yield_step(params: SimulationParams) -> float:
    return params.weighted_dividend_yield * (1.0 - _dividend_tax_rate(params)) * _MONTH


def _growth_key(params: SimulationParams) -> tuple[float, float, float, float, float, float, bool]:
    sigma = params.weighted_local_volatility_sigma
    fx_vol = params.unhedged_foreign_weight * params.fx_volatility_annual
    fx_drift = params.unhedged_foreign_weight * params.expected_fx_drift_annual
    rho = params.asset_fx_correlation
    combined_variance = sigma**2 + fx_vol**2 + 2.0 * rho * sigma * fx_vol
    price_return = params.weighted_local_return_mu - params.weighted_dividend_yield
    drift_step = (price_return + fx_drift + rho * sigma * fx_vol - 0.5 * combined_variance) * _MONTH
    return (
        drift_step,
        sigma * math.sqrt(_MONTH),
        fx_vol * math.sqrt(_MONTH),
        rho,
        _yield_step(params),
        params.tax_profile.annual_inflation_rate,
        params.tax_profile.index_contributions_to_inflation,
    )


@lru_cache(maxsize=4)
def _growth_prefix(
    key: tuple[float, float, float, float, float, float, bool],
    seed: int,
    half_paths: int,
    width: int,
    monthly_contributions: tuple[float, ...] | None = None,
) -> _GrowthPrefix:
    drift_step, asset_step, fx_step, rho, yield_step, inflation, index_flag = key
    shocks = build_shocks(seed, half_paths, width)
    rho_complement = math.sqrt(max(0.0, 1.0 - rho * rho))
    shock = asset_step * shocks.z1 + fx_step * (rho * shocks.z1 + rho_complement * shocks.z2)
    month_offsets = np.arange(width)
    if monthly_contributions is not None:
        # Width fixes common random numbers. Unavailable months are never evaluated.
        deposit_weights = np.zeros(width)
        count = min(width, len(monthly_contributions))
        deposit_weights[:count] = monthly_contributions[:count]
    elif index_flag:
        deposit_weights = (1.0 + inflation) ** (month_offsets // 12)
    else:
        deposit_weights = np.ones(width)
    deposit_units = np.concatenate([[0.0], np.cumsum(deposit_weights)])
    return _GrowthPrefix(
        positive=_path_prefix(
            np.exp(drift_step + shock) + yield_step,
            deposit_weights,
            scheduled=monthly_contributions is not None or index_flag,
        ),
        negative=_path_prefix(
            np.exp(drift_step - shock) + yield_step,
            deposit_weights,
            scheduled=monthly_contributions is not None or index_flag,
        ),
        deposit_units=deposit_units,
    )


def _gross_and_basis(
    path: _PathPrefix,
    columns: np.ndarray,
    params: SimulationParams,
    deposit_units: np.ndarray,
    additional_monthly: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    _validate_horizon(params, int(np.max(columns)))
    start = params.initial_balance
    contribution = 1.0 if params.monthly_contributions is not None else params.monthly_contribution
    floor = min(start, params.initial_cost_basis)
    gross = path.cumulative[:, columns] * (start + contribution * path.growth_index[:, columns])
    reinvested = start * path.balance_weight[:, columns]
    reinvested += contribution * path.contribution_weight[:, columns]
    basis = floor + _yield_step(params) * reinvested + contribution * deposit_units[columns]
    if additional_monthly:
        nominal_index = (
            path.nominal_growth_index
            if path.nominal_growth_index is not None
            else path.growth_index
        )
        nominal_weight = (
            path.nominal_contribution_weight
            if path.nominal_contribution_weight is not None
            else path.contribution_weight
        )
        gross += additional_monthly * path.cumulative[:, columns] * nominal_index[:, columns]
        basis += additional_monthly * (columns + _yield_step(params) * nominal_weight[:, columns])
    return gross, basis


def _after_tax(gross: np.ndarray, basis: np.ndarray, params: SimulationParams) -> np.ndarray:
    cap_gains_rate = (
        0.0 if params.is_tax_advantaged else params.tax_profile.long_term_cap_gains_rate
    )
    if cap_gains_rate <= 0:
        return gross
    allowance = params.tax_profile.annual_tax_free_allowance
    taxable = np.maximum(0.0, gross - basis - allowance)
    return np.where(gross <= basis, gross, gross - taxable * cap_gains_rate)


def _nominal_target(params: SimulationParams, months: int) -> float:
    tax = params.tax_profile
    if tax.is_target_in_todays_dollars:
        return params.target_amount * _inflation_factor(params, months)
    return params.target_amount


def _terminal_success(
    params: SimulationParams,
    prefix: _GrowthPrefix,
    months: int,
    additional_monthly: float = 0.0,
) -> float:
    columns = np.array([months])
    gross_pos, basis_pos = _gross_and_basis(
        prefix.positive, columns, params, prefix.deposit_units, additional_monthly
    )
    gross_neg, basis_neg = _gross_and_basis(
        prefix.negative, columns, params, prefix.deposit_units, additional_monthly
    )
    net = np.concatenate(
        [
            _after_tax(gross_pos, basis_pos, params)[:, -1],
            _after_tax(gross_neg, basis_neg, params)[:, -1],
        ]
    )
    return float(np.mean(net >= _nominal_target(params, months)))


def _quantile(ordered: np.ndarray, q: float) -> float:
    index = min(len(ordered) - 1, max(0, math.floor(q * len(ordered))))
    return round(float(ordered[index]), 2)


def _evaluate(params: SimulationParams, prefix: _GrowthPrefix, months: int) -> MonteCarloResult:
    tax = params.tax_profile
    years_count = math.ceil(months / 12)
    columns = np.array([0] + [min(12 * year, months) for year in range(1, years_count + 1)])

    gross_pos, basis_pos = _gross_and_basis(prefix.positive, columns, params, prefix.deposit_units)
    gross_neg, basis_neg = _gross_and_basis(prefix.negative, columns, params, prefix.deposit_units)
    net_pos = _after_tax(gross_pos, basis_pos, params)
    net_neg = _after_tax(gross_neg, basis_neg, params)

    nominal_target = _nominal_target(params, months)
    real_target = (
        params.target_amount
        if tax.is_target_in_todays_dollars
        else params.target_amount / _inflation_factor(params, months)
    )
    terminal_net = np.concatenate([net_pos[:, -1], net_neg[:, -1]])
    terminal_tax = np.concatenate(
        [gross_pos[:, -1] - net_pos[:, -1], gross_neg[:, -1] - net_neg[:, -1]]
    )
    success_probability = float(np.mean(terminal_net >= nominal_target))

    schedule: list[YearlyPercentileSchedulePoint] = []
    for year in range(columns.size):
        ordered = np.sort(np.concatenate([net_pos[:, year], net_neg[:, year]]))
        month_offset = int(columns[year])
        deflator = _inflation_factor(params, month_offset)
        nominal = {name: _quantile(ordered, q) for name, q in _QUANTILES}
        schedule.append(
            YearlyPercentileSchedulePoint(
                year=year,
                month_offset=month_offset,
                nominal_after_tax=nominal,
                real_todays_dollars={
                    name: round(value / deflator, 2) for name, value in nominal.items()
                },
                inflated_target_at_year=round(
                    params.target_amount * deflator
                    if tax.is_target_in_todays_dollars
                    else params.target_amount,
                    2,
                ),
            )
        )

    ordered_terminal = np.sort(terminal_net)
    terminal_deflator = _inflation_factor(params, months)
    terminal_p10 = _quantile(ordered_terminal, 0.10)
    terminal_p50 = _quantile(ordered_terminal, 0.50)
    terminal_p90 = _quantile(ordered_terminal, 0.90)

    return MonteCarloResult(
        success_probability=success_probability,
        nominal_target_at_maturity=round(nominal_target, 2),
        real_target_in_todays_dollars=round(real_target, 2),
        terminal_nominal_after_tax_p50=terminal_p50,
        terminal_real_todays_dollars_p10=round(terminal_p10 / terminal_deflator, 2),
        terminal_real_todays_dollars_p50=round(terminal_p50 / terminal_deflator, 2),
        terminal_real_todays_dollars_p90=round(terminal_p90 / terminal_deflator, 2),
        estimated_median_tax_paid_at_liquidation=_quantile(np.sort(terminal_tax), 0.50),
        yearly_schedule=schedule,
    )


def run_monte_carlo(
    params: SimulationParams,
    seed: int = DEFAULT_SEED,
    half_paths: int = HALF_PATHS,
) -> MonteCarloResult:
    """Antithetic two-factor simulation with dividend tax drag, cost-basis step-up and deflation.

    Balances obey ``B_k = B_{k-1} * (exp(x_k) + y) + d_k``. That recurrence is linear in the
    starting balance and the contribution, so it is solved from cumulative products rather than
    a per-month loop.
    """
    months = max(1, round(params.horizon_months))
    _validate_horizon(params, months)
    prefix = _growth_prefix(
        _growth_key(params), seed, half_paths, months, params.monthly_contributions
    )
    return _evaluate(params, prefix, months)


def _add_months(value: date, months: int) -> date:
    year_shift, month_index = divmod(value.month - 1 + months, 12)
    year = value.year + year_shift
    day = min(value.day, monthrange(year, month_index + 1)[1])
    return date(year, month_index + 1, day)


def _base_params(goal: GoalSpec, evaluation: GoalEvaluation, horizon: int) -> SimulationParams:
    return SimulationParams(
        initial_balance=evaluation.total_current_value,
        initial_cost_basis=evaluation.total_cost_basis,
        monthly_contribution=goal.monthly_contribution,
        weighted_local_return_mu=evaluation.weighted_local_return_mu,
        weighted_dividend_yield=evaluation.weighted_dividend_yield,
        weighted_local_volatility_sigma=evaluation.weighted_local_volatility_sigma,
        unhedged_foreign_weight=evaluation.unhedged_foreign_weight,
        expected_fx_drift_annual=evaluation.unhedged_fx_drift,
        horizon_months=horizon,
        target_amount=goal.target_amount,
        tax_profile=goal.tax_profile,
        monthly_contributions=goal.monthly_contributions,
        inflation_factors=goal.inflation_factors,
    )


def solve_recovery(
    goal: GoalSpec,
    evaluation: GoalEvaluation,
    seed: int = DEFAULT_SEED,
    half_paths: int = HALF_PATHS,
) -> tuple[MonteCarloResult, GoalRecovery]:
    """Run the base simulation and, if the goal is off track, solve the three recovery levers.

    Every run in one solve shares one shock matrix (common random numbers), so the levers are
    comparable and repeated calls with the same inputs return identical numbers. Explicit vectors
    must cover the base horizon; timeline recovery only searches months covered by both vectors.
    The contribution lever adds a constant nominal amount to every month's scheduled savings.
    """
    target_confidence = goal.target_success_probability
    horizon = max(1, round(evaluation.remaining_years * 12))
    width = horizon + MAX_EXTENSION_MONTHS
    base = _base_params(goal, evaluation, horizon)
    _validate_horizon(base, horizon)
    base_prefix = _growth_prefix(
        _growth_key(base), seed, half_paths, width, base.monthly_contributions
    )
    current = _evaluate(base, base_prefix, horizon)

    if current.success_probability >= target_confidence:
        recovery = GoalRecovery(
            is_goal_on_track=True,
            current_success_probability=current.success_probability,
            target_success_probability=target_confidence,
            plans=RecoveryPlans(),
        )
        return current, recovery

    plans = RecoveryPlans()

    def success_with_contribution(amount: float) -> float:
        return _terminal_success(
            base, base_prefix, horizon, additional_monthly=amount - goal.monthly_contribution
        )

    low = goal.monthly_contribution
    nominal = current.nominal_target_at_maturity
    high = goal.monthly_contribution + nominal / horizon * 2.5
    ceiling = goal.monthly_contribution + nominal / horizon * 50.0
    while success_with_contribution(high) < target_confidence and high < ceiling:
        high = goal.monthly_contribution + (high - goal.monthly_contribution) * 2.0

    if success_with_contribution(high) >= target_confidence:
        for _ in range(_BISECTION_STEPS):
            middle = (low + high) / 2.0
            if success_with_contribution(middle) >= target_confidence:
                high = middle
            else:
                low = middle
        required = math.ceil(high)
        additional = max(0.0, required - goal.monthly_contribution)
        plans.increase_contribution_plan = ContributionLeverPlan(
            description=(
                f"Add an extra nominal {additional:,.0f} {goal.base_currency}/month atop "
                f"scheduled savings to reach a {target_confidence * 100:.0f}% "
                "after-tax success probability. The base savings schedule is unchanged."
            ),
            resulting_success_probability=success_with_contribution(required),
            required_monthly_contribution=float(required),
            additional_monthly_needed=float(additional),
        )
    else:
        plans.unreachable_levers.append("INCREASE_CONTRIBUTION")

    def success_with_extension(months: int) -> float:
        return _terminal_success(base, base_prefix, horizon + months)

    available_extension = MAX_EXTENSION_MONTHS
    if base.monthly_contributions is not None:
        available_extension = min(available_extension, len(base.monthly_contributions) - horizon)
    if base.inflation_factors is not None:
        available_extension = min(available_extension, len(base.inflation_factors) - 1 - horizon)
    extension = None
    if base.monthly_contributions is not None or base.inflation_factors is not None:
        # Lump sums and changing inflation can make success non-monotonic in time.
        extension = next(
            (
                month
                for month in range(1, available_extension + 1)
                if success_with_extension(month) >= target_confidence
            ),
            None,
        )
    elif success_with_extension(MAX_EXTENSION_MONTHS) >= target_confidence:
        lo, hi = 1, MAX_EXTENSION_MONTHS
        while lo < hi:
            middle = (lo + hi) // 2
            if success_with_extension(middle) >= target_confidence:
                hi = middle
            else:
                lo = middle + 1
        extension = lo
    if extension is not None:
        lo = extension
        new_target = _add_months(goal.target_date, lo)
        plans.extend_timeline_plan = TimelineLeverPlan(
            description=(
                f"Extend the target date by {lo} months (to {new_target:%Y-%m}) to reach a "
                f"{target_confidence * 100:.0f}% success rate with your scheduled savings."
            ),
            resulting_success_probability=success_with_extension(lo),
            additional_months_needed=lo,
            new_target_date=new_target.isoformat(),
        )
    else:
        plans.unreachable_levers.append("EXTEND_TIMELINE")

    weights = glide_path_targets(evaluation.remaining_years, goal.risk_profile).weights
    optimal_return, optimal_dividend, optimal_sigma = target_mix_statistics(weights)
    optimal = replace(
        base,
        weighted_local_return_mu=optimal_return,
        weighted_dividend_yield=optimal_dividend,
        weighted_local_volatility_sigma=optimal_sigma,
        unhedged_foreign_weight=weights["EQUITIES"] * GLIDE_UNHEDGED_SHARE_OF_EQUITIES,
    )
    optimal_prefix = _growth_prefix(
        _growth_key(optimal), seed, half_paths, width, optimal.monthly_contributions
    )
    optimal_success = _terminal_success(optimal, optimal_prefix, horizon)
    plans.optimize_portfolio_plan = PortfolioLeverPlan(
        description=(
            f"Rebalancing to the glide-path mix ({weights['EQUITIES'] * 100:.0f}% Equities / "
            f"{weights['BONDS'] * 100:.0f}% Bonds / {weights['CASH'] * 100:.0f}% Cash) moves your "
            f"success rate from {current.success_probability * 100:.1f}% to "
            f"{optimal_success * 100:.1f}% and sets volatility to {optimal_sigma * 100:.1f}%."
        ),
        resulting_success_probability=optimal_success,
        optimal_expected_return=round(optimal_return, 4),
        optimal_volatility=round(optimal_sigma, 4),
    )

    recovery = GoalRecovery(
        is_goal_on_track=False,
        current_success_probability=current.success_probability,
        target_success_probability=target_confidence,
        plans=plans,
    )
    return current, recovery
