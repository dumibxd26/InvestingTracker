from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations import fixed_deposit_value
from app.gbi.constants import CURRENCY_INFLATION_PARITY, DEFAULT_BENCHMARK_CATALOG, CatalogSecurity
from app.gbi.domain import AllocatedHolding, GoalSpec, Holding, TaxInflationProfile, TaxLot
from app.gbi.drift import SpotRate
from app.models import (
    FixedDeposit,
    Goal,
    GoalDepositAllocation,
    GoalHoldingAllocation,
    Instrument,
    MarketPriceCache,
)
from app.models import Holding as HoldingModel

DIVIDEND_AND_INTEREST_TAX_RATE = 0.10
SHORT_TERM_BOND_ETFS = frozenset({"SGOV", "BIL", "XEON", "SHV", "TBIL", "ULST"})
DIVIDEND_ETFS = frozenset({"SCHD", "VIG", "VYM", "HDV", "DGRO", "VHYL", "SDY", "DVY"})
RISK_PROFILE_BY_LEVEL = {"low": "CONSERVATIVE", "moderate": "MODERATE", "high": "AGGRESSIVE"}


def base_symbol(symbol: str) -> str:
    return symbol.split(".")[0].upper()


def _catalog_entry(symbol: str) -> CatalogSecurity | None:
    base = base_symbol(symbol)
    return next(
        (item for item in DEFAULT_BENCHMARK_CATALOG if base_symbol(item.ticker) == base), None
    )


def classify_instrument(symbol: str, instrument_type: str, asset_class: str) -> str:
    """Map a tracked instrument onto the engine's capital-market asset classes."""
    catalog = _catalog_entry(symbol)
    if catalog is not None:
        return catalog.asset_class
    base = base_symbol(symbol)
    if asset_class == "fixed_income":
        if instrument_type == "ETF" and base in SHORT_TERM_BOND_ETFS:
            return "SHORT_TERM_BOND"
        return "INVESTMENT_BOND"
    if asset_class == "satellite":
        return "HIGH_BETA_SPEC"
    if instrument_type == "ETF":
        return "DIVIDEND_VALUE_ETF" if base in DIVIDEND_ETFS else "BROAD_EQUITY_ETF"
    return "BLUE_CHIP_STOCK"


def _latest_quotes(session: Session, instrument_ids: set) -> dict:
    if not instrument_ids:
        return {}
    latest: dict = {}
    rows = session.scalars(
        select(MarketPriceCache)
        .where(MarketPriceCache.instrument_id.in_(instrument_ids))
        .order_by(MarketPriceCache.received_at.desc(), MarketPriceCache.id.desc())
    )
    for quote in rows:
        latest.setdefault(quote.instrument_id, quote)
    return latest


def load_allocated_holdings(
    session: Session,
    goal: Goal,
    spot_rate: SpotRate,
    today: date,
    default_capital_gains_rate: float,
) -> tuple[list[AllocatedHolding], list[str]]:
    goal_currency = goal.target_currency.value
    notes: list[str] = []
    allocations: list[AllocatedHolding] = []

    holding_rows = session.execute(
        select(GoalHoldingAllocation.allocated_percentage, HoldingModel, Instrument)
        .join(HoldingModel, HoldingModel.id == GoalHoldingAllocation.holding_id)
        .join(Instrument, Instrument.id == HoldingModel.instrument_id)
        .where(GoalHoldingAllocation.goal_id == goal.id)
        .order_by(Instrument.symbol)
    ).all()
    quotes = _latest_quotes(session, {instrument.id for _, _, instrument in holding_rows})
    for percentage, holding, instrument in holding_rows:
        quote = quotes.get(instrument.id)
        if quote is None:
            notes.append(
                f"{instrument.symbol} has no cached quote and is excluded from this simulation."
            )
            continue
        trading_currency = quote.currency.value
        catalog = _catalog_entry(instrument.symbol)
        cost_currency = instrument.currency.value
        lot = TaxLot(
            lot_id=str(holding.id),
            purchase_date=holding.purchase_date,
            units=float(holding.quantity),
            cost_basis_per_unit=float(holding.average_cost),
            purchase_fx_rate_to_goal=spot_rate(cost_currency, goal_currency),
        )
        allocations.append(
            AllocatedHolding(
                holding=Holding(
                    holding_id=str(holding.id),
                    ticker=instrument.symbol,
                    name=instrument.name,
                    asset_class=classify_instrument(
                        instrument.symbol,
                        instrument.instrument_type,
                        instrument.asset_class.value,
                    ),
                    total_units=float(holding.quantity),
                    current_price=float(quote.price),
                    trading_currency=trading_currency,
                    underlying_currency=catalog.underlying_currency
                    if catalog
                    else trading_currency,
                    is_currency_hedged=catalog.is_currency_hedged if catalog else False,
                    tax_lots=[lot],
                    capital_gains_rate=float(holding.sale_tax_rate)
                    if holding.sale_tax_rate is not None
                    else default_capital_gains_rate,
                ),
                allocated_percentage=float(percentage),
            )
        )

    deposit_rows = session.execute(
        select(GoalDepositAllocation.allocated_percentage, FixedDeposit)
        .join(FixedDeposit, FixedDeposit.id == GoalDepositAllocation.fixed_deposit_id)
        .where(GoalDepositAllocation.goal_id == goal.id)
        .order_by(FixedDeposit.name)
    ).all()
    for percentage, deposit in deposit_rows:
        valuation_date = max(deposit.start_date, min(today, deposit.maturity_date))
        value = fixed_deposit_value(
            deposit.principal,
            deposit.annual_rate,
            deposit.start_date,
            valuation_date,
            deposit.compounding,
            deposit.rate_basis,
        )
        deposit_currency = deposit.currency.value
        rate = float(deposit.annual_rate)
        lot = TaxLot(
            lot_id=str(deposit.id),
            purchase_date=deposit.start_date,
            units=1.0,
            cost_basis_per_unit=float(deposit.principal),
            purchase_fx_rate_to_goal=spot_rate(deposit_currency, goal_currency),
        )
        allocations.append(
            AllocatedHolding(
                holding=Holding(
                    holding_id=str(deposit.id),
                    ticker=deposit.name,
                    name=deposit.name,
                    asset_class="CASH_DEPOSIT",
                    total_units=1.0,
                    current_price=float(value),
                    trading_currency=deposit_currency,
                    underlying_currency=deposit_currency,
                    is_currency_hedged=False,
                    tax_lots=[lot],
                    custom_yield=rate,
                    dividend_yield=rate,
                    capital_gains_rate=0.0,
                ),
                allocated_percentage=float(percentage),
            )
        )

    return allocations, notes


def build_goal_spec(
    goal: Goal,
    allocations: list[AllocatedHolding],
    spot_rate: SpotRate,
    default_capital_gains_rate: float,
) -> GoalSpec:
    """Build the engine goal, weighting the capital-gains rate by each holding's value."""
    goal_currency = goal.target_currency.value
    total_value = 0.0
    weighted_rate = 0.0
    for item in allocations:
        holding = item.holding
        value = (
            holding.total_units
            * holding.current_price
            * item.allocated_percentage
            / 100.0
            * spot_rate(holding.trading_currency, goal_currency)
        )
        rate = (
            holding.capital_gains_rate
            if holding.capital_gains_rate is not None
            else default_capital_gains_rate
        )
        total_value += value
        weighted_rate += value * rate
    capital_gains_rate = (
        weighted_rate / total_value if total_value > 0 else default_capital_gains_rate
    )

    profile = TaxInflationProfile(
        annual_inflation_rate=CURRENCY_INFLATION_PARITY[goal_currency],
        is_target_in_todays_dollars=True,
        index_contributions_to_inflation=False,
        short_term_cap_gains_rate=capital_gains_rate,
        long_term_cap_gains_rate=capital_gains_rate,
        dividend_and_interest_tax_rate=DIVIDEND_AND_INTEREST_TAX_RATE,
        annual_tax_free_allowance=0.0,
    )
    return GoalSpec(
        goal_id=str(goal.id),
        name=goal.name,
        base_currency=goal_currency,
        target_amount=float(goal.target_amount),
        target_date=goal.target_date,
        monthly_contribution=float(goal.monthly_contribution),
        risk_profile=RISK_PROFILE_BY_LEVEL[goal.risk_level.value],
        tax_profile=profile,
    )
