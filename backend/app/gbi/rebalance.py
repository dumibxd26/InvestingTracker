from __future__ import annotations

from datetime import datetime

from app.gbi.constants import (
    MACRO_BUCKETS,
    CatalogSecurity,
)
from app.gbi.domain import (
    AllocatedHolding,
    ContributionRouteItem,
    GoalEvaluation,
    GoalSpec,
    LotDisposal,
    ProjectedImpact,
    RebalancePlan,
    TaxTrimProposal,
    TickerProposal,
)
from app.gbi.drift import target_mix_statistics

TRIM_REASONS = frozenset({"SINGLE_STOCK_CAP", "HORIZON_MISMATCH", "SAFE_ASSET_FX_MISMATCH"})
MIN_REBALANCE_BUY = 50.0


def _base_symbol(ticker: str) -> str:
    return ticker.split(".")[0].upper()


def select_optimal_tax_lots(
    allocated: AllocatedHolding,
    target_gross_in_goal: float,
    spot_rate_to_goal: float,
    long_term_rate: float,
    short_term_rate: float,
    now: datetime,
) -> list[LotDisposal]:
    """Pick lots with the lowest tax per dollar of proceeds first (MinTax / specific ID)."""
    holding = allocated.holding
    ratio = min(100.0, max(0.0, allocated.allocated_percentage)) / 100.0
    price_in_goal = holding.current_price * spot_rate_to_goal
    if price_in_goal <= 0 or target_gross_in_goal <= 0:
        return []

    candidates = []
    for lot in holding.tax_lots:
        is_long_term = (now.date() - lot.purchase_date).days >= 365
        if holding.is_tax_advantaged:
            rate = 0.0
        elif holding.capital_gains_rate is not None:
            rate = holding.capital_gains_rate
        else:
            rate = long_term_rate if is_long_term else short_term_rate
        cost_per_unit = lot.cost_basis_per_unit * lot.purchase_fx_rate_to_goal
        tax_per_dollar = (price_in_goal - cost_per_unit) * rate / price_in_goal
        candidates.append(
            (tax_per_dollar, lot, is_long_term, rate, cost_per_unit, lot.units * ratio)
        )
    candidates.sort(key=lambda item: item[0])

    disposals: list[LotDisposal] = []
    remaining = target_gross_in_goal
    for _, lot, is_long_term, rate, cost_per_unit, available_units in candidates:
        if remaining <= 0.01 or available_units <= 0:
            break
        proceeds = min(remaining, available_units * price_in_goal)
        units = proceeds / price_in_goal
        cost = units * cost_per_unit
        realized = proceeds - cost
        disposals.append(
            LotDisposal(
                lot_id=lot.lot_id,
                units_to_sell=round(units, 6),
                proceeds_in_goal_currency=round(proceeds, 2),
                cost_basis_in_goal_currency=round(cost, 2),
                realized_gain_or_loss=round(realized, 2),
                is_long_term=is_long_term,
                applicable_tax_rate=rate,
                estimated_tax_due=round(realized * rate, 2),
            )
        )
        remaining -= proceeds
    return disposals


def rank_candidates_for_bucket(
    bucket: str,
    dollar_amount: float,
    action: str,
    evaluation: GoalEvaluation,
    catalog: tuple[CatalogSecurity, ...],
) -> list[TickerProposal]:
    """Score catalog securities on horizon fit, currency match, continuity and cost."""
    existing = {_base_symbol(item.ticker) for item in evaluation.slices}
    has_tech_overlap = any(
        warning.reason == "SECTOR_OVERLAP" and warning.ticker == "TECHNOLOGY"
        for warning in evaluation.warnings
    )
    remaining = evaluation.remaining_years
    base = evaluation.base_currency

    scored: list[TickerProposal] = []
    for candidate in catalog:
        if candidate.macro_bucket != bucket:
            continue
        score = 50.0
        score += 20.0 if remaining >= candidate.min_horizon_years else -35.0

        matched = candidate.underlying_currency == base or (
            candidate.is_currency_hedged and candidate.trading_currency == base
        )
        if bucket in ("CASH", "BONDS"):
            score += 35.0 if matched else -100.0
        elif remaining <= 3 and matched:
            score += 20.0

        if _base_symbol(candidate.ticker) in existing and candidate.sector == "BROAD_MARKET":
            score += 18.0
        if has_tech_overlap and candidate.asset_class == "DIVIDEND_VALUE_ETF":
            score += 22.0
        score += max(0.0, (0.005 - candidate.expense_ratio) * 2000.0)

        scored.append(
            TickerProposal(
                ticker=candidate.ticker,
                name=candidate.name,
                asset_class=candidate.asset_class,
                action=action,
                recommended_amount=round(dollar_amount, 2),
                score=round(score, 1),
                rationale=candidate.rationale_tag,
            )
        )
    scored.sort(key=lambda proposal: proposal.score, reverse=True)
    return scored[:2]


def generate_rebalance_plan(
    goal: GoalSpec,
    evaluation: GoalEvaluation,
    allocations: list[AllocatedHolding],
    catalog: tuple[CatalogSecurity, ...],
    now: datetime,
) -> RebalancePlan:
    contribution = goal.monthly_contribution
    new_total = evaluation.total_current_value + contribution
    buckets = MACRO_BUCKETS
    targets = evaluation.target_weights

    deficits = {
        bucket: max(
            0.0, targets[bucket] * new_total - evaluation.bucket_drifts[bucket].current_value
        )
        for bucket in buckets
    }
    total_deficit = sum(deficits.values())

    routing: list[ContributionRouteItem] = []
    for bucket in buckets:
        if contribution > 0 and total_deficit > 0:
            allocated = contribution * deficits[bucket] / total_deficit
        elif contribution > 0:
            allocated = contribution * targets[bucket]
        else:
            allocated = 0.0
        new_bucket_value = evaluation.bucket_drifts[bucket].current_value + allocated
        post_weight = new_bucket_value / new_total if new_total > 0 else 0.0
        routing.append(
            ContributionRouteItem(
                bucket=bucket,
                allocated_contribution=round(allocated, 2),
                share_of_contribution=round(allocated / contribution, 4)
                if contribution > 0
                else 0.0,
                post_contribution_weight=round(post_weight, 4),
                target_weight=targets[bucket],
                suggested_tickers=rank_candidates_for_bucket(
                    bucket, allocated, "BUY_WITH_CONTRIBUTION", evaluation, catalog
                )
                if allocated >= 1
                else [],
            )
        )

    allocation_by_id = {item.holding.holding_id: item for item in allocations}
    slice_by_id = {item.holding_id: item for item in evaluation.slices}
    trims: list[TaxTrimProposal] = []
    net_reinvestable = 0.0
    for warning in evaluation.warnings:
        if warning.reason not in TRIM_REASONS:
            continue
        allocated = allocation_by_id.get(warning.holding_id)
        slice_ = slice_by_id.get(warning.holding_id)
        if allocated is None or slice_ is None or slice_.value_in_trading_currency <= 0:
            continue
        spot = slice_.market_value_in_goal / slice_.value_in_trading_currency
        disposals = select_optimal_tax_lots(
            allocated,
            warning.excess_dollar_amount,
            spot,
            goal.tax_profile.long_term_cap_gains_rate,
            goal.tax_profile.short_term_cap_gains_rate,
            now,
        )
        gross_sell = sum(item.proceeds_in_goal_currency for item in disposals)
        realized_gain = sum(item.realized_gain_or_loss for item in disposals)
        raw_tax = sum(item.estimated_tax_due for item in disposals)
        allowance = goal.tax_profile.annual_tax_free_allowance
        taxable_gain = max(0.0, realized_gain - allowance)
        estimated_tax = raw_tax * taxable_gain / realized_gain if realized_gain > 0 else raw_tax
        net_proceeds = gross_sell - max(0.0, estimated_tax)
        tax_drag = max(0.0, estimated_tax) / gross_sell if gross_sell > 0 else 0.0
        months_to_cure = (
            warning.excess_dollar_amount / contribution if contribution > 0 else float("inf")
        )

        recommendation = "EXECUTE_LOW_TAX_DRAG"
        rationale = (
            f"Selling highest-basis lots of {slice_.ticker} incurs {estimated_tax:.0f} "
            f"{goal.base_currency} tax, freeing {net_proceeds:.0f} {goal.base_currency} to "
            "rebalance."
        )
        if estimated_tax <= 0:
            recommendation = "EXECUTE_TAX_FREE_OR_TLH"
            rationale = (
                f"Using specific lot identification, trimming {gross_sell:.0f} "
                f"{goal.base_currency} of {slice_.ticker} incurs no tax"
                + (" and harvests a loss." if realized_gain < 0 else ".")
            )
            net_reinvestable += net_proceeds
        elif months_to_cure <= 6 and evaluation.remaining_years > 2:
            recommendation = "DEFER_USE_INFLOWS_INSTEAD"
            rationale = (
                f"Selling triggers {estimated_tax:.0f} {goal.base_currency} tax "
                f"({tax_drag * 100:.1f}% drag). Your monthly deposit cures this drift in "
                f"{months_to_cure:.1f} months without selling."
            )
        else:
            net_reinvestable += net_proceeds

        trims.append(
            TaxTrimProposal(
                holding_id=slice_.holding_id,
                ticker=slice_.ticker,
                gross_sell_amount=round(gross_sell, 2),
                total_realized_gain=round(realized_gain, 2),
                total_estimated_tax=round(estimated_tax, 2),
                net_reinvestable_proceeds=round(net_proceeds, 2),
                effective_tax_drag_pct=round(tax_drag, 4),
                recommendation_type=recommendation,
                rationale=rationale,
                lot_disposals=disposals,
            )
        )

    buys: list[TickerProposal] = []
    for bucket in buckets:
        delta = evaluation.bucket_drifts[bucket].dollar_delta_to_target
        if delta <= MIN_REBALANCE_BUY or not evaluation.requires_rebalancing:
            continue
        amount = min(delta, net_reinvestable) if net_reinvestable > 0 else delta
        ranked = rank_candidates_for_bucket(bucket, amount, "REBALANCE_INTO", evaluation, catalog)
        if ranked:
            buys.append(ranked[0])

    previous_sigma = evaluation.portfolio_volatility_sigma
    target_return, _, target_sigma = target_mix_statistics(targets)
    new_median = target_return - 0.5 * target_sigma**2
    if target_sigma < previous_sigma:
        summary = (
            f"Aligning with your {evaluation.remaining_years:.1f}-year glide path cuts volatility "
            f"from {previous_sigma * 100:.1f}% to {target_sigma * 100:.1f}%."
        )
    else:
        summary = (
            "Reducing cash drag raises expected median compounding from "
            f"{evaluation.median_compounding_rate * 100:.1f}% to {new_median * 100:.1f}%."
        )

    return RebalancePlan(
        goal_id=goal.goal_id,
        monthly_contribution_routing=routing,
        tax_aware_trim_proposals=trims,
        rebalance_buy_proposals=buys,
        projected_impact=ProjectedImpact(
            previous_volatility=previous_sigma,
            new_volatility=target_sigma,
            previous_median_return=evaluation.median_compounding_rate,
            new_median_return=new_median,
            summary_text=summary,
        ),
    )
