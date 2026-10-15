from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations import fixed_deposit_value
from app.gbi.constants import (
    CMA_CONFIG,
    CURRENCY_INFLATION_PARITY,
    DEFAULT_BENCHMARK_CATALOG,
    CatalogSecurity,
)
from app.gbi.domain import AllocatedHolding, GoalSpec, Holding, TaxInflationProfile, TaxLot
from app.gbi.drift import SpotRate
from app.models import (
    BrokerAccount,
    FixedDeposit,
    Goal,
    GoalDepositAllocation,
    GoalHoldingAllocation,
    Instrument,
    MarketPriceCache,
    TaxReportingMethod,
    User,
)
from app.models import Holding as HoldingModel
from app.taxes.engine import TaxEstimate, estimate_capital_gain_tax, estimate_income_tax
from app.taxes.rules import get_country_tax_rules

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


def _estimate_capital_gain(
    *,
    holding: HoldingModel,
    quote: MarketPriceCache,
    user: User,
    account: BrokerAccount,
    acquired_on: date,
    sold_on: date,
    legacy_rate: Decimal,
    tax_exempt: bool,
) -> TaxEstimate:
    return estimate_capital_gain_tax(
        gross_proceeds=holding.quantity * quote.price,
        cost_basis=holding.quantity * holding.average_cost,
        acquired_on=acquired_on,
        sold_on=sold_on,
        country_code=user.tax_residence_country_code,
        tax_year=user.tax_year,
        intermediary_country_code=account.broker_country_code,
        reporting_method=str(account.tax_reporting_method),
        manual_rate=holding.sale_tax_rate,
        legacy_rate=legacy_rate,
        tax_exempt=tax_exempt,
    )


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
        select(
            GoalHoldingAllocation.allocated_percentage,
            HoldingModel,
            Instrument,
            BrokerAccount,
        )
        .join(HoldingModel, HoldingModel.id == GoalHoldingAllocation.holding_id)
        .join(Instrument, Instrument.id == HoldingModel.instrument_id)
        .join(BrokerAccount, BrokerAccount.id == HoldingModel.account_id)
        .where(GoalHoldingAllocation.goal_id == goal.id)
        .order_by(Instrument.symbol)
    ).all()
    quotes = _latest_quotes(
        session, {instrument.id for _, _, instrument, _ in holding_rows}
    )
    user = session.get(User, goal.user_id)
    if user is None:
        raise ValueError("Goal owner was not found while building tax assumptions")
    for percentage, holding, instrument, account in holding_rows:
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
        account_tax_exempt = (
            account.tax_reporting_method == TaxReportingMethod.TAX_EXEMPT
        )
        default_gain_rate = Decimal(str(default_capital_gains_rate))
        rule_pack = get_country_tax_rules(user.tax_residence_country_code, user.tax_year)
        long_term_days = rule_pack.local_long_term_days if rule_pack else 365
        capital_gains = _estimate_capital_gain(
            holding=holding,
            quote=quote,
            user=user,
            account=account,
            acquired_on=holding.purchase_date,
            sold_on=today,
            legacy_rate=default_gain_rate,
            tax_exempt=account_tax_exempt,
        )
        short_term_capital_gains = _estimate_capital_gain(
            holding=holding,
            quote=quote,
            user=user,
            account=account,
            acquired_on=today - timedelta(days=max(0, long_term_days - 1)),
            sold_on=today,
            legacy_rate=default_gain_rate,
            tax_exempt=account_tax_exempt,
        )
        long_term_capital_gains = _estimate_capital_gain(
            holding=holding,
            quote=quote,
            user=user,
            account=account,
            acquired_on=today - timedelta(days=long_term_days),
            sold_on=today,
            legacy_rate=default_gain_rate,
            tax_exempt=account_tax_exempt,
        )
        distribution = estimate_income_tax(
            event_type="dividend",
            gross_amount=Decimal("1"),
            country_code=user.tax_residence_country_code,
            tax_year=user.tax_year,
            source_country_code=holding.tax_domicile_country_code,
            reporting_method=str(account.tax_reporting_method),
            legacy_rate=Decimal(str(DIVIDEND_AND_INTEREST_TAX_RATE)),
            tax_exempt=account_tax_exempt,
        )
        notes.extend(capital_gains.warnings)
        notes.extend(distribution.warnings)
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
                    distribution_tax_rate=float(
                        distribution.rate
                        if distribution.rate is not None
                        else Decimal(str(DIVIDEND_AND_INTEREST_TAX_RATE))
                    ),
                    is_tax_advantaged=account_tax_exempt,
                    capital_gains_rate=float(
                        capital_gains.rate
                        if capital_gains.rate is not None
                        else default_gain_rate
                    ),
                    short_term_capital_gains_rate=float(
                        short_term_capital_gains.rate
                        if short_term_capital_gains.rate is not None
                        else default_gain_rate
                    ),
                    long_term_capital_gains_rate=float(
                        long_term_capital_gains.rate
                        if long_term_capital_gains.rate is not None
                        else default_gain_rate
                    ),
                    long_term_holding_period_days=long_term_days,
                ),
                allocated_percentage=float(percentage),
            )
        )

    deposit_rows = session.execute(
        select(
            GoalDepositAllocation.allocated_percentage,
            FixedDeposit,
            BrokerAccount,
        )
        .join(FixedDeposit, FixedDeposit.id == GoalDepositAllocation.fixed_deposit_id)
        .join(BrokerAccount, BrokerAccount.id == FixedDeposit.account_id)
        .where(GoalDepositAllocation.goal_id == goal.id)
        .order_by(FixedDeposit.name)
    ).all()
    for percentage, deposit, account in deposit_rows:
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
        account_tax_exempt = (
            account.tax_reporting_method == TaxReportingMethod.TAX_EXEMPT
        )
        interest_tax = estimate_income_tax(
            event_type="interest",
            gross_amount=Decimal("1"),
            country_code=user.tax_residence_country_code,
            tax_year=user.tax_year,
            source_country_code=account.broker_country_code,
            reporting_method=str(account.tax_reporting_method),
            legacy_rate=Decimal(str(DIVIDEND_AND_INTEREST_TAX_RATE)),
            tax_exempt=account_tax_exempt,
        )
        notes.extend(interest_tax.warnings)
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
                    distribution_tax_rate=float(
                        interest_tax.rate
                        if interest_tax.rate is not None
                        else Decimal(str(DIVIDEND_AND_INTEREST_TAX_RATE))
                    ),
                    is_tax_advantaged=account_tax_exempt,
                    capital_gains_rate=0.0,
                ),
                allocated_percentage=float(percentage),
            )
        )

    manual_cash = float(getattr(goal, "current_amount", 0.0) or 0.0)
    if manual_cash > 0:
        allocations.append(
            AllocatedHolding(
                holding=Holding(
                    holding_id=f"goal-cash-{goal.id}",
                    ticker="CASH",
                    name="Manual goal savings",
                    asset_class="CASH_BALANCE",
                    total_units=1.0,
                    current_price=manual_cash,
                    trading_currency=goal_currency,
                    underlying_currency=goal_currency,
                    is_currency_hedged=False,
                    tax_lots=[
                        TaxLot(f"goal-cash-{goal.id}", today, 1.0, manual_cash, 1.0)
                    ],
                    capital_gains_rate=0.0,
                    short_term_capital_gains_rate=0.0,
                    long_term_capital_gains_rate=0.0,
                    distribution_tax_rate=0.0,
                ),
                allocated_percentage=100.0,
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
    weighted_short_term_rate = 0.0
    weighted_long_term_rate = 0.0
    distribution_yield_value = 0.0
    distribution_tax_weighted = 0.0
    for item in allocations:
        holding = item.holding
        value = (
            holding.total_units
            * holding.current_price
            * item.allocated_percentage
            / 100.0
            * spot_rate(holding.trading_currency, goal_currency)
        )
        short_term_rate = (
            holding.short_term_capital_gains_rate
            if holding.short_term_capital_gains_rate is not None
            else holding.capital_gains_rate
            if holding.capital_gains_rate is not None
            else default_capital_gains_rate
        )
        long_term_rate = (
            holding.long_term_capital_gains_rate
            if holding.long_term_capital_gains_rate is not None
            else holding.capital_gains_rate
            if holding.capital_gains_rate is not None
            else default_capital_gains_rate
        )
        if holding.asset_class != "CASH_BALANCE":
            total_value += value
            weighted_short_term_rate += value * short_term_rate
            weighted_long_term_rate += value * long_term_rate
        assumption = CMA_CONFIG[holding.asset_class]
        distribution_yield = (
            holding.dividend_yield
            if holding.dividend_yield is not None
            else assumption.dividend_yield
        )
        distribution_exposure = value * distribution_yield
        distribution_rate = (
            holding.distribution_tax_rate
            if holding.distribution_tax_rate is not None
            else DIVIDEND_AND_INTEREST_TAX_RATE
        )
        distribution_yield_value += distribution_exposure
        distribution_tax_weighted += distribution_exposure * distribution_rate
    short_term_capital_gains_rate = (
        weighted_short_term_rate / total_value if total_value > 0 else default_capital_gains_rate
    )
    long_term_capital_gains_rate = (
        weighted_long_term_rate / total_value if total_value > 0 else default_capital_gains_rate
    )
    distribution_tax_rate = (
        distribution_tax_weighted / distribution_yield_value
        if distribution_yield_value > 0
        else DIVIDEND_AND_INTEREST_TAX_RATE
    )

    inflation_override = getattr(goal, "annual_inflation_rate", None)
    profile = TaxInflationProfile(
        annual_inflation_rate=(
            float(inflation_override)
            if inflation_override is not None
            else CURRENCY_INFLATION_PARITY[goal_currency]
        ),
        is_target_in_todays_dollars=getattr(goal, "target_money_basis", "real") != "nominal",
        index_contributions_to_inflation=False,
        short_term_cap_gains_rate=short_term_capital_gains_rate,
        long_term_cap_gains_rate=long_term_capital_gains_rate,
        dividend_and_interest_tax_rate=distribution_tax_rate,
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
