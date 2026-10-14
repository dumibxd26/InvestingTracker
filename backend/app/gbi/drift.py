from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.gbi.constants import (
    BOND_FX_CORRELATION,
    BUCKET_CORRELATIONS,
    CMA_CONFIG,
    CONCENTRATION_VOLATILITY,
    CURRENCY_INFLATION_PARITY,
    DRIFT_THRESHOLD,
    EQUITY_FX_CORRELATION,
    FX_VOLATILITY,
    IDIOSYNCRATIC_VOLATILITY,
    MACRO_BUCKETS,
    MARKET_VOLATILITY,
    MAX_STOCK_VOLATILITY,
    SECTOR_CAP,
    SINGLE_STOCK_CLASSES,
)
from app.gbi.domain import (
    AllocatedHolding,
    BucketDrift,
    EvaluatedSlice,
    GoalEvaluation,
    GoalSpec,
    Holding,
    RiskWarning,
)

SpotRate = Callable[[str, str], float]


def _sale_tax_rate(holding: Holding, goal: GoalSpec) -> float:
    if holding.capital_gains_rate is not None:
        return holding.capital_gains_rate
    if holding.long_term_capital_gains_rate is not None:
        return holding.long_term_capital_gains_rate
    return goal.tax_profile.long_term_cap_gains_rate


@dataclass(frozen=True)
class GlidePath:
    weights: dict[str, float]
    max_single_stock_weight: float
    max_unhedged_fx_weight: float


def glide_path_targets(remaining_years: float, risk_profile: str) -> GlidePath:
    """Smoothly shift target weights from equities into bonds and cash as the horizon shortens."""
    risk_multiplier = {"AGGRESSIVE": 1.15, "CONSERVATIVE": 0.80}.get(risk_profile, 1.0)
    if remaining_years <= 1.5:
        return GlidePath(
            weights={"CASH": 0.80, "BONDS": 0.20, "EQUITIES": 0.0},
            max_single_stock_weight=0.0,
            max_unhedged_fx_weight=0.05,
        )

    horizon = min(1.0, max(0.0, (remaining_years - 1.5) / 10.5))
    raw_equity = (0.20 + 0.65 * horizon**0.75) * risk_multiplier
    equities = min(0.92, max(0.0, round(raw_equity, 4)))
    remainder = 1.0 - equities
    cash_share = max(0.10, 1.0 - horizon * 0.85)
    cash = round(remainder * cash_share, 4)
    bonds = round(1.0 - equities - cash, 4)

    if remaining_years < 3:
        max_single = 0.0
    elif remaining_years < 7:
        max_single = 0.05
    else:
        max_single = 0.15 if risk_profile == "AGGRESSIVE" else 0.10

    if remaining_years <= 4.0:
        max_fx = 0.35
    elif remaining_years <= 7.0:
        max_fx = 0.65
    else:
        max_fx = 0.85

    return GlidePath(
        weights={"CASH": cash, "BONDS": bonds, "EQUITIES": equities},
        max_single_stock_weight=max_single,
        max_unhedged_fx_weight=max_fx,
    )


def portfolio_volatility(
    bucket_volatilities: dict[str, float], single_stock_weights: list[float]
) -> float:
    """Cross-bucket covariance volatility plus a single-stock concentration penalty."""
    variance = 0.0
    for first in MACRO_BUCKETS:
        for second in MACRO_BUCKETS:
            variance += (
                bucket_volatilities[first]
                * bucket_volatilities[second]
                * BUCKET_CORRELATIONS[first][second]
            )
    concentration = sum(weight * weight for weight in single_stock_weights)
    variance += concentration * CONCENTRATION_VOLATILITY**2
    return math.sqrt(max(0.0, variance))


def _pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def target_mix_statistics(weights: dict[str, float]) -> tuple[float, float, float]:
    """Expected return, dividend yield and covariance-adjusted volatility of a macro-bucket mix."""
    cash = CMA_CONFIG["SHORT_TERM_BOND"]
    bonds = CMA_CONFIG["INVESTMENT_BOND"]
    equities = CMA_CONFIG["BROAD_EQUITY_ETF"]
    expected_return = (
        weights["CASH"] * cash.expected_return
        + weights["BONDS"] * bonds.expected_return
        + weights["EQUITIES"] * equities.expected_return
    )
    dividend_yield = (
        weights["CASH"] * cash.dividend_yield
        + weights["BONDS"] * bonds.dividend_yield
        + weights["EQUITIES"] * equities.dividend_yield
    )
    bucket_vols = {
        "CASH": weights["CASH"] * cash.volatility,
        "BONDS": weights["BONDS"] * bonds.volatility,
        "EQUITIES": weights["EQUITIES"] * equities.volatility,
    }
    return expected_return, dividend_yield, portfolio_volatility(bucket_vols, [])


def evaluate_goal_portfolio(
    goal: GoalSpec,
    allocations: list[AllocatedHolding],
    spot_rate: SpotRate,
    now: datetime,
) -> GoalEvaluation:
    remaining_years = max(0.1, (goal.target_date - now.date()).days / 365.25)
    glide = glide_path_targets(remaining_years, goal.risk_profile)
    target_weights = glide.weights
    goal_inflation = CURRENCY_INFLATION_PARITY[goal.base_currency]

    slices: list[EvaluatedSlice] = []
    for allocation in allocations:
        holding = allocation.holding
        pct = min(100.0, max(0.0, allocation.allocated_percentage))
        if pct <= 0:
            continue
        ratio = pct / 100.0
        value_trading = holding.total_units * holding.current_price * ratio
        if value_trading <= 0:
            continue

        spot = (
            1.0
            if holding.trading_currency == goal.base_currency
            else spot_rate(holding.trading_currency, goal.base_currency)
        )
        market_value = value_trading * spot
        if holding.tax_lots:
            cost_basis = sum(
                lot.units * ratio * lot.cost_basis_per_unit * lot.purchase_fx_rate_to_goal
                for lot in holding.tax_lots
            )
        else:
            cost_basis = market_value

        cma = CMA_CONFIG[holding.asset_class]
        local_return = (
            holding.custom_yield if holding.custom_yield is not None else cma.expected_return
        )
        local_vol = cma.volatility
        if holding.asset_class in SINGLE_STOCK_CLASSES and holding.beta is not None:
            local_vol = min(
                MAX_STOCK_VOLATILITY,
                math.sqrt((holding.beta * MARKET_VOLATILITY) ** 2 + IDIOSYNCRATIC_VOLATILITY**2),
            )
        dividend_yield = (
            holding.dividend_yield if holding.dividend_yield is not None else cma.dividend_yield
        )

        ppp_drift = goal_inflation - CURRENCY_INFLATION_PARITY[holding.underlying_currency]
        is_unhedged = (
            not holding.is_currency_hedged and holding.underlying_currency != goal.base_currency
        )
        if is_unhedged:
            correlation = (
                EQUITY_FX_CORRELATION if cma.macro_bucket == "EQUITIES" else BOND_FX_CORRELATION
            )
            covariance = correlation * local_vol * FX_VOLATILITY
            effective_vol = math.sqrt(local_vol**2 + FX_VOLATILITY**2 + 2 * covariance)
            effective_return = local_return + ppp_drift + covariance
            fx_vol_contribution = FX_VOLATILITY
        else:
            effective_vol = local_vol
            effective_return = local_return + ppp_drift
            fx_vol_contribution = 0.0

        slices.append(
            EvaluatedSlice(
                holding_id=holding.holding_id,
                ticker=holding.ticker,
                name=holding.name,
                asset_class=holding.asset_class,
                macro_bucket=cma.macro_bucket,
                allocated_percentage=pct,
                value_in_trading_currency=value_trading,
                market_value_in_goal=market_value,
                cost_basis_in_goal=cost_basis,
                after_tax_market_value=market_value
                - max(0.0, market_value - cost_basis) * _sale_tax_rate(holding, goal),
                local_expected_return=local_return,
                local_volatility=local_vol,
                effective_return_in_goal=effective_return,
                effective_volatility_in_goal=effective_vol,
                effective_dividend_yield=dividend_yield,
                fx_volatility_contribution=fx_vol_contribution,
                is_unhedged_foreign_exposure=is_unhedged,
                unhedged_fx_drift=ppp_drift,
                underlying_currency=holding.underlying_currency,
                sector=holding.sector,
            )
        )

    total_value = sum(s.market_value_in_goal for s in slices)
    total_cost = sum(s.cost_basis_in_goal for s in slices)
    after_tax_value = sum(s.after_tax_market_value for s in slices)
    bucket_values = {bucket: 0.0 for bucket in MACRO_BUCKETS}
    bucket_vols = {bucket: 0.0 for bucket in MACRO_BUCKETS}
    expected_return = 0.0
    weighted_local_return = 0.0
    weighted_dividend = 0.0
    weighted_local_vol = 0.0
    unhedged_weight = 0.0
    unhedged_drift_weighted = 0.0

    for item in slices:
        weight = item.market_value_in_goal / total_value if total_value > 0 else 0.0
        item.weight_in_goal = weight
        expected_return += weight * item.effective_return_in_goal
        weighted_local_return += weight * item.local_expected_return
        weighted_dividend += weight * item.effective_dividend_yield
        weighted_local_vol += weight * item.local_volatility
        if item.is_unhedged_foreign_exposure:
            unhedged_weight += weight
            unhedged_drift_weighted += weight * item.unhedged_fx_drift
        bucket_values[CMA_CONFIG[item.asset_class].macro_bucket] += item.market_value_in_goal
        bucket_vols[CMA_CONFIG[item.asset_class].macro_bucket] += (
            weight * item.effective_volatility_in_goal
        )

    if total_value == 0:
        expected_return = (
            target_weights["CASH"] * CMA_CONFIG["CASH_DEPOSIT"].expected_return
            + target_weights["BONDS"] * CMA_CONFIG["INVESTMENT_BOND"].expected_return
            + target_weights["EQUITIES"] * CMA_CONFIG["BROAD_EQUITY_ETF"].expected_return
        )
        weighted_local_return = expected_return
        weighted_dividend = (
            target_weights["CASH"] * CMA_CONFIG["CASH_DEPOSIT"].dividend_yield
            + target_weights["BONDS"] * CMA_CONFIG["INVESTMENT_BOND"].dividend_yield
            + target_weights["EQUITIES"] * CMA_CONFIG["BROAD_EQUITY_ETF"].dividend_yield
        )
        bucket_vols["CASH"] = target_weights["CASH"] * CMA_CONFIG["CASH_DEPOSIT"].volatility
        bucket_vols["BONDS"] = target_weights["BONDS"] * CMA_CONFIG["INVESTMENT_BOND"].volatility
        bucket_vols["EQUITIES"] = (
            target_weights["EQUITIES"] * CMA_CONFIG["BROAD_EQUITY_ETF"].volatility
        )
        weighted_local_vol = sum(bucket_vols.values())

    single_stock_weights = [
        item.weight_in_goal for item in slices if item.asset_class in SINGLE_STOCK_CLASSES
    ]
    portfolio_sigma = portfolio_volatility(bucket_vols, single_stock_weights)
    median_rate = expected_return - 0.5 * portfolio_sigma**2
    cash_return = CMA_CONFIG["CASH_DEPOSIT"].expected_return
    sharpe = (expected_return - cash_return) / portfolio_sigma if portfolio_sigma > 0.001 else 0.0

    bucket_drifts: dict[str, BucketDrift] = {}
    requires_rebalancing = False
    for bucket in MACRO_BUCKETS:
        current_value = bucket_values[bucket]
        target = target_weights[bucket]
        current_weight = current_value / total_value if total_value > 0 else target
        drift = current_weight - target
        is_breached = total_value > 0 and abs(drift) >= DRIFT_THRESHOLD
        requires_rebalancing = requires_rebalancing or is_breached
        bucket_drifts[bucket] = BucketDrift(
            bucket=bucket,
            current_value=current_value,
            current_weight=current_weight,
            target_weight=target,
            drift=drift,
            dollar_delta_to_target=total_value * target - current_value,
            is_breached=is_breached,
        )

    warnings: list[RiskWarning] = []
    sector_weights: dict[str, float] = {}
    max_single = glide.max_single_stock_weight
    for item in slices:
        if item.sector and item.sector not in ("BROAD_MARKET", "FIXED_INCOME"):
            sector_weights[item.sector] = sector_weights.get(item.sector, 0.0) + item.weight_in_goal

        if item.asset_class in SINGLE_STOCK_CLASSES and item.weight_in_goal > max_single:
            requires_rebalancing = True
            short_horizon = remaining_years < 3
            if short_horizon:
                message = (
                    f"{item.ticker} ({_pct(item.weight_in_goal)}) exposes a short-term goal "
                    f"({remaining_years:.1f} yrs left) to single-stock drawdown risk."
                )
            else:
                message = (
                    f"{item.ticker} is {_pct(item.weight_in_goal)} of this goal, exceeding the "
                    f"{_pct(max_single, 0)} single-stock cap."
                )
            warnings.append(
                RiskWarning(
                    holding_id=item.holding_id,
                    ticker=item.ticker,
                    current_weight=item.weight_in_goal,
                    max_allowed_weight=max_single,
                    excess_dollar_amount=(item.weight_in_goal - max_single) * total_value,
                    reason="HORIZON_MISMATCH" if short_horizon else "SINGLE_STOCK_CAP",
                    message=message,
                )
            )

        if item.is_unhedged_foreign_exposure and item.macro_bucket in ("CASH", "BONDS"):
            requires_rebalancing = True
            warnings.append(
                RiskWarning(
                    holding_id=item.holding_id,
                    ticker=item.ticker,
                    current_weight=item.weight_in_goal,
                    max_allowed_weight=0.0,
                    excess_dollar_amount=item.market_value_in_goal,
                    reason="SAFE_ASSET_FX_MISMATCH",
                    message=(
                        f"{item.ticker} has low {item.underlying_currency} volatility "
                        f"({_pct(item.local_volatility)}), but unhedged "
                        f"{item.underlying_currency}/{goal.base_currency} FX swings inflate its "
                        f"real volatility to {_pct(item.effective_volatility_in_goal)}."
                    ),
                    suggested_fix=(
                        f"Replace with a {goal.base_currency}-hedged bond ETF or local "
                        f"{goal.base_currency} term deposit."
                    ),
                )
            )

    for sector, weight in sector_weights.items():
        if weight > SECTOR_CAP:
            warnings.append(
                RiskWarning(
                    holding_id=f"SECTOR_{sector}",
                    ticker=sector,
                    current_weight=weight,
                    max_allowed_weight=SECTOR_CAP,
                    excess_dollar_amount=(weight - SECTOR_CAP) * total_value,
                    reason="SECTOR_OVERLAP",
                    message=f"{_pct(weight)} of this goal is concentrated in the {sector} sector.",
                )
            )

    max_fx = glide.max_unhedged_fx_weight
    if unhedged_weight > max_fx:
        warnings.append(
            RiskWarning(
                holding_id="PORTFOLIO_FX_EXPOSURE",
                ticker="UNHEDGED_FX",
                current_weight=unhedged_weight,
                max_allowed_weight=max_fx,
                excess_dollar_amount=(unhedged_weight - max_fx) * total_value,
                reason="GLIDE_PATH_FX_BREACH",
                message=(
                    f"{_pct(unhedged_weight, 0)} of your {goal.base_currency} goal is exposed to "
                    f"unhedged foreign currency with {remaining_years:.1f} years remaining "
                    f"(cap: {_pct(max_fx, 0)})."
                ),
            )
        )

    unhedged_fx_drift = unhedged_drift_weighted / unhedged_weight if unhedged_weight > 0 else 0.0

    return GoalEvaluation(
        goal_id=goal.goal_id,
        base_currency=goal.base_currency,
        remaining_years=remaining_years,
        total_current_value=total_value,
        total_cost_basis=total_cost,
        after_tax_value=after_tax_value,
        expected_return_mu=expected_return,
        weighted_local_return_mu=weighted_local_return,
        weighted_dividend_yield=weighted_dividend,
        weighted_local_volatility_sigma=weighted_local_vol,
        portfolio_volatility_sigma=portfolio_sigma,
        unhedged_foreign_weight=unhedged_weight,
        unhedged_fx_drift=unhedged_fx_drift,
        median_compounding_rate=median_rate,
        sharpe_ratio=sharpe,
        max_single_stock_weight=max_single,
        max_unhedged_fx_weight=max_fx,
        target_weights=target_weights,
        bucket_drifts=bucket_drifts,
        requires_rebalancing=requires_rebalancing,
        warnings=warnings,
        slices=slices,
    )
