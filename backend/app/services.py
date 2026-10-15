from __future__ import annotations

import re
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.broker_imports import (
    BrokerImportError,
    ParsedBrokerReport,
    ParsedBrokerTransaction,
    parse_xtb_report,
)
from app.calculations import (
    compound_growth_factor,
    fixed_deposit_value,
    generate_vesting_schedule,
    goal_progress,
    rebalance_with_contribution,
    round_allocations,
    round_money,
    route_funding_to_goals,
)
from app.cash_flow_logic import add_months, occurrence_dates
from app.config import get_settings
from app.gbi.adapter import build_goal_spec, load_allocated_holdings
from app.gbi.constants import CMA_CONFIG, MAX_EXTENSION_MONTHS
from app.gbi.controller import build_goal_insights
from app.gbi.domain import to_plain
from app.gbi.schemas import GoalInsightsResponse
from app.market_data import (
    PROVIDER_NAME,
    ExchangeRateQuote,
    MarketDataProviderError,
    MarketQuote,
    TwelveDataClient,
)
from app.models import (
    AccountSubaccount,
    AccountType,
    AllocationPolicy,
    AssetClass,
    BrokerAccount,
    BrokerImportBatch,
    BrokerTransaction,
    CashFlow,
    CashFlowSchedule,
    CashSpend,
    CashTransfer,
    CompoundingFrequency,
    Currency,
    FinancialPlan,
    FixedDeposit,
    FlowDirection,
    FlowKind,
    FlowStatus,
    FundingRule,
    Goal,
    GoalAccountLink,
    GoalDepositAllocation,
    GoalHoldingAllocation,
    GoalType,
    GrantType,
    Holding,
    Instrument,
    LoginSession,
    MarketFXRate,
    MarketPriceCache,
    RateBasis,
    Recommendation,
    RiskLevel,
    StockPurchasePlan,
    StockSale,
    StockTransfer,
    TaxReportingMethod,
    TrancheStatus,
    User,
    ValuationSnapshot,
    VestingGrant,
    VestingTranche,
)
from app.planning import (
    ContributionRule,
    ContributionSchedule,
    Convert,
    FinancialPlanPayload,
    contribution_months,
    inflation_factor,
    matching_sources,
)
from app.schemas import (
    AccountCreate,
    AccountSubaccountCreate,
    AccountSubaccountSummary,
    AccountSummary,
    AccountTaxProfileUpdate,
    AccountWealthSummary,
    AllocationSummary,
    AuthResponse,
    BrokerImportPreviewResponse,
    BrokerImportResponse,
    BrokerTransactionListResponse,
    BrokerTransactionPreview,
    BrokerTransactionSummary,
    BucketAllocation,
    CashFlowScheduleCreate,
    CashFlowScheduleResponse,
    CashReceiptCreate,
    CashSpendCreate,
    CashSpendResponse,
    CashTransferCreate,
    CashTransferResponse,
    ChartPoint,
    DepositSummary,
    FixedDepositCreate,
    FixedDepositCreateResponse,
    FixedSharesUpdate,
    FlowResponse,
    GoalAllocation,
    GoalCreate,
    GoalResponse,
    GoalSummary,
    GoalUpdate,
    HoldingCreate,
    HoldingCreateResponse,
    HoldingSummary,
    HoldingUpdate,
    InitialPortfolioHolding,
    InitialPortfolioRequest,
    InitialPortfolioResponse,
    LoginRequest,
    MarketDataStatusResponse,
    MarketFXRateSummary,
    MarketRefreshResponse,
    MarketSymbolSearchResult,
    PolicyResponse,
    PolicyUpdate,
    PortfolioProjectionRangeRequest,
    PortfolioProjectionRangeResponse,
    PortfolioProjectionResponse,
    PortfolioProjectionScenarioRequest,
    PortfolioProjectionScenarioResponse,
    ProfileUpdate,
    ProjectionAccountValue,
    ProjectionPoint,
    ProjectionRangeInvestmentResult,
    ProjectionRangeLine,
    ProjectionRangeLinePoint,
    ProjectionScenarioInvestment,
    ProjectionScenarioRiskSummary,
    RecommendationRequest,
    RecommendationResponse,
    RegisterRequest,
    StockPurchasePlanCreate,
    StockPurchasePlanSummary,
    StockSaleCreate,
    StockSaleResponse,
    StockTransferCreate,
    StockTransferResponse,
    SubaccountInterestUpdate,
    TaxAnnualSummaryRequest,
    TaxAnnualSummaryResponse,
    TaxCassThreshold,
    TransferFeeInput,
    UserProfileResponse,
    VestingGrantCreate,
    VestingSummary,
    VestingTrancheSummary,
)
from app.security import create_access_token, digest_access_token, hash_password, verify_password
from app.taxes.engine import (
    estimate_capital_gain_tax,
    estimate_country_cass,
    estimate_income_tax,
)
from app.taxes.rules import country_rule_status, get_country_tax_rules

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")
SAVINGS_INTEREST_SOURCE = "SAVINGS_INTEREST"
MAX_INTEREST_CATCH_UP_MONTHS = 600
DEFAULT_SALE_TAX_RATE = Decimal("0.03")
DEFAULT_INTEREST_TAX_RATE = Decimal("0.10")


def _get_user(session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Application account is unavailable")
    return user


def _get_policy(session: Session, user_id: uuid.UUID) -> AllocationPolicy:
    policy = session.scalar(select(AllocationPolicy).where(AllocationPolicy.user_id == user_id))
    if policy is None:
        raise HTTPException(status_code=503, detail="Allocation policy is not configured")
    return policy


def _to_base(
    amount: Decimal,
    from_currency: Currency,
    to_currency: Currency,
    usd_per_eur: Decimal | None,
    fx_rates: dict[tuple[Currency, Currency], Decimal] | None = None,
) -> Decimal:
    if amount == ZERO:
        return ZERO
    if from_currency == to_currency:
        return amount
    rates = dict(fx_rates or {})
    if usd_per_eur is not None:
        rates.setdefault((Currency.EUR, Currency.USD), usd_per_eur)
        rates.setdefault((Currency.USD, Currency.EUR), ONE / usd_per_eur)
    if not rates:
        raise HTTPException(
            status_code=409,
            detail=(
                "Refresh market data or set a manual USD-per-EUR reference rate "
                "to value currencies."
            ),
        )
    frontier: list[tuple[Currency, Decimal]] = [(from_currency, ONE)]
    visited = {from_currency}
    while frontier:
        current, current_rate = frontier.pop(0)
        for (base, quote), rate in rates.items():
            if base != current or quote in visited:
                continue
            converted_rate = current_rate * rate
            if quote == to_currency:
                return amount * converted_rate
            visited.add(quote)
            frontier.append((quote, converted_rate))
    raise HTTPException(
        status_code=409,
        detail=(
            f"No cached FX path converts {from_currency.value} to {to_currency.value}. "
            "Refresh market data to retrieve current FX rates."
        ),
    )


def _market_fx_matrix(session: Session) -> dict[tuple[Currency, Currency], Decimal]:
    rates: dict[tuple[Currency, Currency], Decimal] = {}
    for quote in session.scalars(
        select(MarketFXRate).order_by(MarketFXRate.received_at.desc(), MarketFXRate.id.desc())
    ):
        pair = (quote.base_currency, quote.quote_currency)
        rates.setdefault(pair, quote.rate)
        rates.setdefault((quote.quote_currency, quote.base_currency), ONE / quote.rate)
    return rates


def _fx_matrix(session: Session, user: User) -> dict[tuple[Currency, Currency], Decimal]:
    rates = _market_fx_matrix(session)
    if user.usd_per_eur is not None:
        rates.setdefault((Currency.EUR, Currency.USD), user.usd_per_eur)
        rates.setdefault((Currency.USD, Currency.EUR), ONE / user.usd_per_eur)
    return rates


def _projection_volatility_assumption(
    instrument: Instrument, risk_tier: str
) -> Decimal:
    if instrument.asset_class == AssetClass.FIXED_INCOME:
        asset_class = "INVESTMENT_BOND"
    elif instrument.asset_class == AssetClass.SATELLITE or risk_tier == "Z":
        asset_class = "HIGH_BETA_SPEC"
    elif instrument.instrument_type == "ETF":
        asset_class = "BROAD_EQUITY_ETF"
    else:
        asset_class = "BLUE_CHIP_STOCK"
    return Decimal(str(CMA_CONFIG[asset_class].volatility))


def _interest_tax_rate_for_account(
    user: User, account: BrokerAccount | AccountSummary
) -> tuple[Decimal, list[str]]:
    estimate = estimate_income_tax(
        event_type="interest",
        gross_amount=ONE,
        country_code=user.tax_residence_country_code,
        tax_year=user.tax_year,
        source_country_code=account.broker_country_code,
        reporting_method=str(account.tax_reporting_method),
        legacy_rate=DEFAULT_INTEREST_TAX_RATE,
        tax_exempt=account.tax_reporting_method == TaxReportingMethod.TAX_EXEMPT,
    )
    return estimate.rate or ZERO, list(estimate.warnings)


def _market_fx_summaries(session: Session) -> list[MarketFXRateSummary]:
    latest_by_pair: dict[tuple[Currency, Currency], MarketFXRate] = {}
    for quote in session.scalars(
        select(MarketFXRate).order_by(MarketFXRate.received_at.desc(), MarketFXRate.id.desc())
    ):
        latest_by_pair.setdefault((quote.base_currency, quote.quote_currency), quote)
    return [
        MarketFXRateSummary(
            base_currency=quote.base_currency,
            quote_currency=quote.quote_currency,
            rate=quote.rate,
            provider=quote.provider,
            observed_at=quote.observed_at,
            change_percent=(
                (quote.rate - quote.previous_rate) * Decimal(100) / quote.previous_rate
                if quote.previous_rate
                else None
            ),
        )
        for quote in latest_by_pair.values()
    ]


def _market_client() -> TwelveDataClient:
    settings = get_settings()
    try:
        return TwelveDataClient(
            settings.twelve_data_api_key,
            timeout_seconds=settings.market_data_timeout_seconds,
        )
    except MarketDataProviderError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _raise_provider_error(error: MarketDataProviderError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


async def _ensure_fx_conversion(
    session: Session,
    client: TwelveDataClient,
    from_currency: Currency,
    to_currency: Currency,
    rates: dict[tuple[Currency, Currency], Decimal],
) -> None:
    if _can_convert(from_currency, to_currency, rates):
        return
    try:
        quote = await client.exchange_rate(f"{from_currency.value}/{to_currency.value}")
    except MarketDataProviderError as error:
        _raise_provider_error(error)
    _save_market_fx_quote(session, quote)
    rates[(quote.base_currency, quote.quote_currency)] = quote.rate
    rates[(quote.quote_currency, quote.base_currency)] = ONE / quote.rate
    if not _can_convert(from_currency, to_currency, rates):
        raise HTTPException(
            status_code=502,
            detail=(
                f"The provider did not return a usable FX rate from "
                f"{from_currency.value} to {to_currency.value}."
            ),
        )


def market_data_status() -> MarketDataStatusResponse:
    return MarketDataStatusResponse(
        provider=PROVIDER_NAME,
        provider_configured=bool(get_settings().twelve_data_api_key.strip()),
    )


async def search_market_symbols(query: str) -> list[MarketSymbolSearchResult]:
    client = _market_client()
    try:
        results = await client.search_symbols(query.strip())
    except MarketDataProviderError as error:
        _raise_provider_error(error)
    return [
        MarketSymbolSearchResult(
            symbol=result.symbol,
            name=result.name,
            exchange=result.exchange,
            mic_code=result.mic_code,
            currency=result.currency,
            instrument_type=result.instrument_type,
            country=result.country,
        )
        for result in results
    ]


async def create_vesting_grant(
    session: Session, user_id: uuid.UUID, payload: VestingGrantCreate
) -> uuid.UUID:
    user = _get_user(session, user_id)
    client = _market_client()
    try:
        quote = await client.quote(payload.symbol, payload.mic_code, payload.exchange)
    except MarketDataProviderError as error:
        _raise_provider_error(error)

    fx_rates = _fx_matrix(session, user)
    await _ensure_fx_conversion(session, client, quote.currency, user.base_currency, fx_rates)
    symbol = quote.symbol.upper()
    mic = (quote.mic_code or payload.mic_code or "UNKNOWN").upper()
    exchange = quote.exchange or payload.exchange or ""
    instrument = session.scalar(
        select(Instrument).where(Instrument.symbol == symbol, Instrument.mic == mic)
    )
    if instrument is None:
        instrument = Instrument(
            symbol=symbol,
            name=quote.name,
            asset_class=AssetClass.EQUITIES,
            currency=quote.currency,
            mic=mic,
            exchange=exchange,
            instrument_type="STOCK",
            estimated_annual_yield=ZERO,
            is_demo=False,
        )
        session.add(instrument)
        session.flush()
    elif (
        instrument.currency != quote.currency
        or (instrument.exchange and exchange and instrument.exchange != exchange)
        or instrument.instrument_type != "STOCK"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"{symbol} is already tracked using a different listing. "
                "Select its existing stock exchange listing."
            ),
        )
    else:
        instrument.name = quote.name
        instrument.exchange = exchange or instrument.exchange
        instrument.is_demo = False

    grant = VestingGrant(
        user_id=user.id,
        instrument_id=instrument.id,
        grant_type=payload.grant_type,
        grant_label=payload.grant_label,
        grant_date=payload.grant_date,
        total_units=payload.total_units,
        strike_price=payload.strike_price,
        strike_currency=quote.currency if payload.strike_price is not None else None,
        tax_rate_assumption=payload.tax_rate_assumption,
        short_term_sale_tax_rate=payload.short_term_sale_tax_rate,
        long_term_sale_tax_rate=payload.long_term_sale_tax_rate,
        long_term_holding_period_days=payload.long_term_holding_period_days,
    )
    session.add(grant)
    session.flush()
    grant_id = grant.id
    if payload.tranches is not None:
        vesting_schedule = sorted(
            ((tranche.vest_date, tranche.units) for tranche in payload.tranches),
            key=lambda tranche: tranche[0],
        )
    else:
        if (
            payload.grant_date is None
            or payload.duration_months is None
            or payload.cliff_months is None
            or payload.interval_months is None
        ):
            raise HTTPException(
                status_code=422,
                detail="Enter either custom vesting periods or a complete standard schedule.",
            )
        vesting_schedule = generate_vesting_schedule(
            payload.total_units,
            payload.grant_date,
            payload.duration_months,
            payload.cliff_months,
            payload.interval_months,
        )
    for vest_date, units in vesting_schedule:
        session.add(
            VestingTranche(
                grant_id=grant.id,
                vest_date=vest_date,
                available_date=vest_date,
                units=units,
                status=TrancheStatus.SCHEDULED,
            )
        )
    session.add(
        MarketPriceCache(
            instrument_id=instrument.id,
            price=quote.price,
            currency=quote.currency,
            source=PROVIDER_NAME,
            feed_type="QUOTE",
            observed_at=quote.observed_at,
            is_market_open=quote.is_market_open,
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="The equity grant could not be saved because its listing changed concurrently.",
        ) from error
    return grant_id


def delete_vesting_grant(session: Session, user_id: uuid.UUID, grant_id: uuid.UUID) -> None:
    grant = session.scalar(
        select(VestingGrant).where(
            VestingGrant.id == grant_id,
            VestingGrant.user_id == user_id,
        )
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="Equity grant was not found")
    session.execute(delete(VestingTranche).where(VestingTranche.grant_id == grant.id))
    session.delete(grant)
    session.commit()


async def create_holding(
    session: Session, user_id: uuid.UUID, payload: HoldingCreate
) -> HoldingCreateResponse:
    user = _get_user(session, user_id)
    account = session.scalar(
        select(BrokerAccount).where(
            BrokerAccount.id == payload.account_id,
            BrokerAccount.user_id == user.id,
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Selected investment account was not found")
    if account.account_type == AccountType.SAVINGS:
        raise HTTPException(
            status_code=422,
            detail="Stocks and ETFs cannot be added to a savings account",
        )

    client = _market_client()
    try:
        quote = await client.quote(payload.symbol, payload.mic_code, payload.exchange)
    except MarketDataProviderError as error:
        _raise_provider_error(error)

    fx_rates = _fx_matrix(session, user)
    average_cost_currency = payload.average_cost_currency or quote.currency
    await _ensure_fx_conversion(
        session, client, average_cost_currency, quote.currency, fx_rates
    )
    await _ensure_fx_conversion(
        session, client, quote.currency, user.base_currency, fx_rates
    )
    funding_subaccount = session.scalar(
        select(AccountSubaccount)
        .where(
            AccountSubaccount.id == payload.subaccount_id,
            AccountSubaccount.account_id == account.id,
        )
        .with_for_update()
    )
    if funding_subaccount is None:
        raise HTTPException(
            status_code=404, detail="The selected cash sub-account was not found"
        )
    await _ensure_fx_conversion(
        session, client, quote.currency, funding_subaccount.currency, fx_rates
    )
    average_cost_in_quote_currency = _to_base(
        payload.average_cost,
        average_cost_currency,
        quote.currency,
        user.usd_per_eur,
        fx_rates,
    )
    purchase_cost = round_money(payload.quantity * average_cost_in_quote_currency)
    funding_cost = round_money(
        _to_base(
            purchase_cost,
            quote.currency,
            funding_subaccount.currency,
            user.usd_per_eur,
            fx_rates,
        )
    )
    if funding_subaccount.cash_balance < funding_cost:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Insufficient {funding_subaccount.currency.value} cash: "
                f"the converted purchase cost is {funding_cost:.2f}, but the selected "
                f"sub-account has {funding_subaccount.cash_balance:.2f}."
            ),
        )

    symbol = quote.symbol.upper()
    mic = (quote.mic_code or payload.mic_code or "UNKNOWN").upper()
    exchange = quote.exchange or payload.exchange or ""
    instrument = session.scalar(
        select(Instrument).where(Instrument.symbol == symbol, Instrument.mic == mic)
    )
    if instrument is None:
        instrument = Instrument(
            symbol=symbol,
            name=quote.name,
            asset_class=AssetClass.EQUITIES,
            currency=quote.currency,
            mic=mic,
            exchange=exchange,
            instrument_type=payload.instrument_type,
            estimated_annual_yield=ZERO,
            is_demo=False,
        )
        session.add(instrument)
        session.flush()
    elif (
        instrument.currency != quote.currency
        or (instrument.exchange and exchange and instrument.exchange != exchange)
        or instrument.instrument_type != payload.instrument_type
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"{symbol} is already tracked using a different listing. "
                "Select its existing exchange listing or use a distinct ticker."
            ),
        )
    else:
        instrument.name = quote.name
        instrument.exchange = exchange or instrument.exchange
        instrument.is_demo = False

    holding = session.scalar(
        select(Holding).where(
            Holding.user_id == user.id,
            Holding.account_id == account.id,
            Holding.instrument_id == instrument.id,
        )
    )
    if holding is None:
        holding = Holding(
            user_id=user.id,
            account_id=account.id,
            funding_subaccount_id=funding_subaccount.id,
            instrument_id=instrument.id,
            quantity=payload.quantity,
            average_cost=average_cost_in_quote_currency,
            purchase_date=payload.purchase_date,
            risk_tier=payload.risk_tier or ("X" if instrument.instrument_type == "ETF" else "Y"),
            expected_annual_return=(
                payload.expected_annual_return
                if payload.expected_annual_return is not None
                else (
                    Decimal("0.06")
                    if instrument.instrument_type == "ETF"
                    else Decimal("0.05")
                )
            ),
            funding_cost=funding_cost,
        )
        session.add(holding)
        total_quantity = payload.quantity
    else:
        if (
            holding.funding_subaccount_id is not None
            and holding.funding_subaccount_id != funding_subaccount.id
        ):
            raise HTTPException(
                status_code=409,
                detail="This position is already funded from another currency sub-account.",
            )
        if holding.funding_subaccount_id is None:
            holding.funding_subaccount_id = funding_subaccount.id
        total_quantity = holding.quantity + payload.quantity
        weighted_purchase_ordinal = (
            Decimal(holding.purchase_date.toordinal()) * holding.quantity
            + Decimal(payload.purchase_date.toordinal()) * payload.quantity
        ) / total_quantity
        holding.average_cost = (
            holding.quantity * holding.average_cost
            + payload.quantity * average_cost_in_quote_currency
        ) / total_quantity
        holding.quantity = total_quantity
        holding.purchase_date = date.fromordinal(
            int(weighted_purchase_ordinal.to_integral_value(rounding=ROUND_HALF_UP))
        )
        holding.funding_cost += funding_cost
        if payload.risk_tier is not None:
            holding.risk_tier = payload.risk_tier
        if payload.expected_annual_return is not None:
            holding.expected_annual_return = payload.expected_annual_return

    if payload.tax_domicile_country_code is not None:
        holding.tax_domicile_country_code = payload.tax_domicile_country_code.upper()
    funding_subaccount.cash_balance -= funding_cost
    session.add(
        MarketPriceCache(
            instrument_id=instrument.id,
            price=quote.price,
            currency=quote.currency,
            source="TWELVE_DATA",
            feed_type="QUOTE",
            observed_at=quote.observed_at,
            is_market_open=quote.is_market_open,
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="The holding could not be saved because its listing already exists.",
        ) from error
    return HoldingCreateResponse(
        symbol=instrument.symbol,
        account_name=account.display_name,
        quantity=total_quantity,
        quote_price=quote.price,
        quote_currency=quote.currency,
        funding_currency=funding_subaccount.currency,
        funding_cost=funding_cost,
    )


async def initialize_portfolio(
    session: Session, user_id: uuid.UUID, request: InitialPortfolioRequest
) -> InitialPortfolioResponse:
    user = _get_user(session, user_id)
    normalized_names = [account.display_name.casefold() for account in request.accounts]
    existing_names = set(
        session.scalars(
            select(func.lower(BrokerAccount.display_name)).where(
                BrokerAccount.user_id == user.id,
                func.lower(BrokerAccount.display_name).in_(normalized_names),
            )
        )
    )
    if existing_names:
        duplicate_name = next(
            name for name in request.accounts if name.display_name.casefold() in existing_names
        )
        raise HTTPException(
            status_code=409,
            detail=f'An account named "{duplicate_name.display_name}" already exists.',
        )

    client = _market_client() if request.holdings else None
    quote_cache: dict[tuple[str, str, str], MarketQuote] = {}
    quoted_holdings: list[tuple[InitialPortfolioHolding, MarketQuote, int, Decimal]] = []
    seen_positions: set[tuple[int, str, str]] = set()
    fx_rates = _fx_matrix(session, user)
    fx_quotes: dict[tuple[Currency, Currency], ExchangeRateQuote] = {}

    async def ensure_currency_conversion(
        from_currency: Currency, to_currency: Currency
    ) -> None:
        nonlocal client
        if _can_convert(from_currency, to_currency, fx_rates, user.usd_per_eur):
            return
        pair = (from_currency, to_currency)
        if pair not in fx_quotes:
            if client is None:
                client = _market_client()
            try:
                fx_quote = await client.exchange_rate(
                    f"{from_currency.value}/{to_currency.value}"
                )
            except MarketDataProviderError as error:
                _raise_provider_error(error)
            fx_quotes[pair] = fx_quote
            fx_rates[(fx_quote.base_currency, fx_quote.quote_currency)] = fx_quote.rate
            fx_rates[(fx_quote.quote_currency, fx_quote.base_currency)] = ONE / fx_quote.rate
        if not _can_convert(from_currency, to_currency, fx_rates, user.usd_per_eur):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"No FX reference is available to convert {from_currency.value} "
                    f"to {to_currency.value}."
                ),
            )

    for holding_request in request.holdings:
        account_request = request.accounts[holding_request.account_index]
        listing_key = (
            holding_request.symbol.strip().upper(),
            (holding_request.mic_code or "").strip().upper(),
            (holding_request.exchange or "").strip().upper(),
        )
        cache_key = listing_key
        quote = quote_cache.get(cache_key)
        if quote is None:
            try:
                if client is None:
                    raise HTTPException(
                        status_code=503,
                        detail="Configure Twelve Data before adding owned stocks during setup.",
                    )
                quote = await client.quote(
                    holding_request.symbol.strip(),
                    holding_request.mic_code,
                    holding_request.exchange,
                )
            except MarketDataProviderError as error:
                _raise_provider_error(error)
            quote_cache[cache_key] = quote

        mic = (quote.mic_code or holding_request.mic_code or "UNKNOWN").upper()
        position_key = (holding_request.account_index, quote.symbol.upper(), mic)
        if position_key in seen_positions:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{quote.symbol} is listed more than once for "
                    f"{account_request.display_name}. Combine those shares into one position."
                ),
            )
        seen_positions.add(position_key)

        await ensure_currency_conversion(quote.currency, user.base_currency)
        average_cost_currency = holding_request.average_cost_currency or quote.currency
        await ensure_currency_conversion(average_cost_currency, quote.currency)

        instrument = session.scalar(
            select(Instrument).where(
                Instrument.symbol == quote.symbol.upper(),
                Instrument.mic == mic,
            )
        )
        exchange = quote.exchange or holding_request.exchange or ""
        if instrument is not None and (
            instrument.currency != quote.currency
            or (instrument.exchange and exchange and instrument.exchange != exchange)
            or instrument.instrument_type != holding_request.instrument_type
        ):
            raise HTTPException(
                status_code=409,
                detail=f"{quote.symbol} is already tracked with a different listing.",
            )

        average_cost_in_quote_currency = _to_base(
            holding_request.average_cost,
            average_cost_currency,
            quote.currency,
            user.usd_per_eur,
            fx_rates,
        )
        quoted_holdings.append(
            (
                holding_request,
                quote,
                holding_request.account_index,
                average_cost_in_quote_currency,
            )
        )

    for account_request in request.accounts:
        for wallet in account_request.subaccounts:
            if wallet.opening_balance:
                await ensure_currency_conversion(wallet.currency, user.base_currency)

    accounts: list[BrokerAccount] = []
    for account_request in request.accounts:
        account = BrokerAccount(
            id=uuid.uuid4(),
            user_id=user.id,
            provider_code=account_request.provider_code,
            display_name=account_request.display_name,
            account_type=account_request.account_type,
        )
        accounts.append(account)
        session.add(account)
        try:
            session.flush()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail=(
                    f'An account named "{account_request.display_name}" already exists '
                    "in this profile."
                ),
            ) from error
        for wallet_index, wallet_request in enumerate(account_request.subaccounts):
            session.add(
                AccountSubaccount(
                    id=uuid.uuid4(),
                    account_id=account.id,
                    currency=wallet_request.currency,
                    cash_balance=wallet_request.opening_balance,
                    is_primary=wallet_index == 0,
                )
            )

    session.flush()
    holding_responses: list[HoldingCreateResponse] = []
    for (
        holding_request,
        quote,
        account_index,
        average_cost_in_quote_currency,
    ) in quoted_holdings:
        account = accounts[account_index]
        symbol = quote.symbol.upper()
        mic = (quote.mic_code or holding_request.mic_code or "UNKNOWN").upper()
        exchange = quote.exchange or holding_request.exchange or ""
        instrument = session.scalar(
            select(Instrument).where(Instrument.symbol == symbol, Instrument.mic == mic)
        )
        if instrument is None:
            instrument = Instrument(
                symbol=symbol,
                name=quote.name,
                asset_class=AssetClass.EQUITIES,
                currency=quote.currency,
                mic=mic,
                exchange=exchange,
                instrument_type=holding_request.instrument_type,
                estimated_annual_yield=ZERO,
                is_demo=False,
            )
            session.add(instrument)
            session.flush()
        else:
            instrument.name = quote.name
            instrument.exchange = exchange or instrument.exchange
            instrument.is_demo = False

        session.add(
            Holding(
                user_id=user.id,
                account_id=account.id,
                funding_subaccount_id=None,
                instrument_id=instrument.id,
                quantity=holding_request.quantity,
                average_cost=average_cost_in_quote_currency,
                purchase_date=holding_request.purchase_date,
                risk_tier=holding_request.risk_tier
                or ("X" if holding_request.instrument_type == "ETF" else "Y"),
                expected_annual_return=(
                    holding_request.expected_annual_return
                    if holding_request.expected_annual_return is not None
                    else (
                        Decimal("0.06")
                        if holding_request.instrument_type == "ETF"
                        else Decimal("0.05")
                    )
                ),
                tax_domicile_country_code=(
                    holding_request.tax_domicile_country_code.upper()
                    if holding_request.tax_domicile_country_code
                    else None
                ),
                funding_cost=ZERO,
            )
        )
        session.add(
            MarketPriceCache(
                instrument_id=instrument.id,
                price=quote.price,
                currency=quote.currency,
                source="TWELVE_DATA",
                feed_type="QUOTE",
                observed_at=quote.observed_at,
                is_market_open=quote.is_market_open,
            )
        )
        holding_responses.append(
            HoldingCreateResponse(
                symbol=instrument.symbol,
                account_name=account.display_name,
                quantity=holding_request.quantity,
                quote_price=quote.price,
                quote_currency=quote.currency,
                funding_currency=None,
                funding_cost=ZERO,
            )
        )

    for fx_quote in fx_quotes.values():
        _save_market_fx_quote(session, fx_quote)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Initial portfolio setup could not be saved because an account or "
                "position conflicts with existing data."
            ),
        ) from error

    return InitialPortfolioResponse(
        accounts=list_accounts(session, user.id),
        holdings=holding_responses,
    )


def update_holding(
    session: Session, user_id: uuid.UUID, holding_id: uuid.UUID, payload: HoldingUpdate
) -> None:
    _get_user(session, user_id)
    holding = session.scalar(
        select(Holding)
        .where(Holding.id == holding_id, Holding.user_id == user_id)
    )
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding was not found")
    funding_subaccount_id = holding.funding_subaccount_id
    funding_subaccount = None
    if funding_subaccount_id is not None:
        funding_subaccount = session.scalar(
            select(AccountSubaccount)
            .where(AccountSubaccount.id == funding_subaccount_id)
            .with_for_update()
        )
        if funding_subaccount is None:
            raise HTTPException(
                status_code=409, detail="The position's funding sub-account is unavailable"
            )
    holding = session.scalar(
        select(Holding)
        .where(Holding.id == holding_id, Holding.user_id == user_id)
        .with_for_update()
    )
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding was not found")
    if holding.funding_subaccount_id != funding_subaccount_id:
        raise HTTPException(
            status_code=409, detail="The position's funding sub-account changed; reload it."
        )
    instrument = session.get(Instrument, holding.instrument_id)
    if instrument is None:
        raise HTTPException(status_code=409, detail="The position's instrument is unavailable")
    user = _get_user(session, user_id)
    average_cost_currency = payload.average_cost_currency or instrument.currency
    fx_rates = _fx_matrix(session, user)
    updated_native_average_cost = _to_base(
        payload.average_cost,
        average_cost_currency,
        instrument.currency,
        user.usd_per_eur,
        fx_rates,
    )
    if funding_subaccount is not None:
        updated_funding_cost = round_money(
            _to_base(
                round_money(payload.quantity * updated_native_average_cost),
                instrument.currency,
                funding_subaccount.currency,
                user.usd_per_eur,
                fx_rates,
            )
        )
        cost_change = updated_funding_cost - holding.funding_cost
        if cost_change > funding_subaccount.cash_balance:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Insufficient {funding_subaccount.currency.value} cash for this change. "
                    f"It would require an additional {cost_change:.2f}."
                ),
            )
        funding_subaccount.cash_balance -= cost_change
        holding.funding_cost = updated_funding_cost
    else:
        holding.funding_cost = ZERO
    holding.quantity = payload.quantity
    holding.average_cost = updated_native_average_cost
    if payload.purchase_date is not None:
        holding.purchase_date = payload.purchase_date
    if payload.risk_tier is not None:
        holding.risk_tier = payload.risk_tier
    if payload.expected_annual_return is not None:
        holding.expected_annual_return = payload.expected_annual_return
    if "tax_domicile_country_code" in payload.model_fields_set:
        holding.tax_domicile_country_code = (
            payload.tax_domicile_country_code.upper()
            if payload.tax_domicile_country_code is not None
            else None
        )
    session.commit()


def delete_holding(session: Session, user_id: uuid.UUID, holding_id: uuid.UUID) -> None:
    _get_user(session, user_id)
    holding = session.scalar(
        select(Holding)
        .where(Holding.id == holding_id, Holding.user_id == user_id)
    )
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding was not found")
    funding_subaccount_id = holding.funding_subaccount_id
    funding_subaccount = None
    if funding_subaccount_id is not None:
        funding_subaccount = session.scalar(
            select(AccountSubaccount)
            .where(AccountSubaccount.id == funding_subaccount_id)
            .with_for_update()
        )
        if funding_subaccount is None:
            raise HTTPException(
                status_code=409, detail="The position's funding sub-account is unavailable"
            )
    holding = session.scalar(
        select(Holding)
        .where(Holding.id == holding_id, Holding.user_id == user_id)
        .with_for_update()
    )
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding was not found")
    if holding.funding_subaccount_id != funding_subaccount_id:
        raise HTTPException(
            status_code=409, detail="The position's funding sub-account changed; reload it."
        )
    if funding_subaccount is not None:
        funding_subaccount.cash_balance += holding.funding_cost
    session.delete(holding)
    session.commit()


def _stock_sale_response(sale: StockSale, symbol: str) -> StockSaleResponse:
    return StockSaleResponse(
        id=sale.id,
        symbol=symbol,
        currency=sale.currency,
        quantity=sale.quantity,
        sell_price=sale.sell_price,
        proceeds=sale.proceeds,
        cost_basis=sale.cost_basis,
        realized_pnl=sale.realized_pnl,
        sell_date=sale.sell_date,
        credited_subaccount_id=sale.credited_subaccount_id,
    )


def sell_holding(
    session: Session, user_id: uuid.UUID, holding_id: uuid.UUID, payload: StockSaleCreate
) -> StockSaleResponse:
    user = _get_user(session, user_id)
    existing = session.scalar(
        select(StockSale).where(
            StockSale.user_id == user.id,
            StockSale.client_request_id == payload.idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.sell_date != payload.sell_date
            or existing.sell_price != payload.sell_price
            or (payload.quantity is not None and existing.quantity != payload.quantity)
        ):
            raise HTTPException(
                status_code=409,
                detail="This sale idempotency key was already used for different data",
            )
        instrument = session.get(Instrument, existing.instrument_id)
        return _stock_sale_response(existing, instrument.symbol if instrument else "")

    holding = session.scalar(
        select(Holding)
        .where(Holding.id == holding_id, Holding.user_id == user.id)
        .with_for_update()
    )
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding was not found")
    account = session.get(BrokerAccount, holding.account_id)
    if account is None:
        raise HTTPException(status_code=409, detail="The holding's account is unavailable")
    if account.account_type == AccountType.EMPLOYER_PLAN:
        raise HTTPException(
            status_code=422,
            detail="Employer-plan holdings cannot be sold; their proceeds have no cash account",
        )
    instrument = session.get(Instrument, holding.instrument_id)
    if instrument is None:
        raise HTTPException(status_code=409, detail="The position's instrument is unavailable")

    today = datetime.now(UTC).date()
    if payload.sell_date > today:
        raise HTTPException(status_code=422, detail="Sell date cannot be in the future")
    if payload.sell_date < holding.purchase_date:
        raise HTTPException(
            status_code=422,
            detail=(
                "Sell date cannot be before the purchase date "
                f"({holding.purchase_date.isoformat()})"
            ),
        )
    quantity = payload.quantity if payload.quantity is not None else holding.quantity
    if quantity > holding.quantity:
        raise HTTPException(
            status_code=422,
            detail=f"Only {holding.quantity:f} units are held; cannot sell {quantity:f}",
        )
    is_full_sale = quantity == holding.quantity

    wallet = session.scalar(
        select(AccountSubaccount)
        .where(
            AccountSubaccount.account_id == account.id,
            AccountSubaccount.currency == instrument.currency,
        )
        .with_for_update()
    )
    if wallet is None:
        wallet = AccountSubaccount(
            account_id=account.id,
            currency=instrument.currency,
            cash_balance=ZERO,
            is_primary=False,
        )
        session.add(wallet)
        session.flush()

    proceeds = round_money(quantity * payload.sell_price)
    cost_basis = round_money(quantity * holding.average_cost)
    sale = StockSale(
        user_id=user.id,
        client_request_id=payload.idempotency_key,
        account_id=account.id,
        credited_subaccount_id=wallet.id,
        instrument_id=instrument.id,
        holding_id=holding.id,
        quantity=quantity,
        sell_price=payload.sell_price,
        currency=instrument.currency,
        proceeds=proceeds,
        cost_basis=cost_basis,
        realized_pnl=proceeds - cost_basis,
        sell_date=payload.sell_date,
    )
    session.add(sale)
    session.flush()

    wallet.cash_balance += proceeds
    if is_full_sale:
        session.delete(holding)
    else:
        remaining_quantity = holding.quantity - quantity
        holding.funding_cost = round_money(
            holding.funding_cost * remaining_quantity / holding.quantity
        )
        holding.quantity = remaining_quantity
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This sale was already recorded; refresh the portfolio.",
        ) from error
    session.refresh(sale)
    return _stock_sale_response(sale, instrument.symbol)


def _cash_transfer_response(
    transfer: CashTransfer,
    source_account_name: str,
    destination_account_name: str,
) -> CashTransferResponse:
    return CashTransferResponse(
        id=transfer.id,
        source_subaccount_id=transfer.source_subaccount_id,
        destination_subaccount_id=transfer.destination_subaccount_id,
        source_account_name=source_account_name,
        destination_account_name=destination_account_name,
        source_currency=transfer.source_currency,
        destination_currency=transfer.destination_currency,
        source_amount=transfer.source_amount,
        destination_amount=transfer.destination_amount,
        transfer_date=transfer.transfer_date,
        fee_amount=transfer.fee_amount,
        fee_currency=transfer.fee_currency,
        fee_side=transfer.fee_side,
    )


def _transfer_fee_matches(record: CashTransfer | StockTransfer, payload: TransferFeeInput) -> bool:
    return (
        record.fee_amount == payload.fee_amount
        and record.fee_currency == payload.fee_currency
        and record.fee_side == payload.fee_side
    )


def transfer_cash(
    session: Session, user_id: uuid.UUID, payload: CashTransferCreate
) -> CashTransferResponse:
    user = _get_user(session, user_id)
    existing = session.scalar(
        select(CashTransfer).where(
            CashTransfer.user_id == user.id,
            CashTransfer.client_request_id == payload.idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.source_subaccount_id != payload.source_subaccount_id
            or existing.destination_subaccount_id != payload.destination_subaccount_id
            or existing.transfer_date != payload.transfer_date
            or existing.source_amount != payload.source_amount
            or not _transfer_fee_matches(existing, payload)
            or (
                payload.destination_amount is not None
                and existing.destination_amount != payload.destination_amount
            )
        ):
            raise HTTPException(
                status_code=409,
                detail="This transfer idempotency key was already used for different data",
            )
        source = session.get(AccountSubaccount, existing.source_subaccount_id)
        destination = session.get(AccountSubaccount, existing.destination_subaccount_id)
        if source is None or destination is None:
            raise HTTPException(status_code=409, detail="The transfer's wallets are unavailable")
        source_account = session.get(BrokerAccount, source.account_id)
        destination_account = session.get(BrokerAccount, destination.account_id)
        return _cash_transfer_response(
            existing,
            source_account.display_name if source_account else "",
            destination_account.display_name if destination_account else "",
        )

    if payload.source_subaccount_id == payload.destination_subaccount_id:
        raise HTTPException(status_code=422, detail="Choose two different wallets")

    today = datetime.now(UTC).date()
    if payload.transfer_date > today:
        raise HTTPException(status_code=422, detail="Transfer date cannot be in the future")

    wallet_ids = sorted([payload.source_subaccount_id, payload.destination_subaccount_id])
    locked = {
        wallet.id: wallet
        for wallet in session.scalars(
            select(AccountSubaccount)
            .where(AccountSubaccount.id.in_(wallet_ids))
            .order_by(AccountSubaccount.id)
            .with_for_update()
        )
    }
    source = locked.get(payload.source_subaccount_id)
    destination = locked.get(payload.destination_subaccount_id)
    if source is None or destination is None:
        raise HTTPException(status_code=404, detail="Wallet was not found")

    source_account = session.get(BrokerAccount, source.account_id)
    destination_account = session.get(BrokerAccount, destination.account_id)
    if source_account is None or destination_account is None:
        raise HTTPException(status_code=409, detail="A wallet's account is unavailable")
    if source_account.user_id != user.id or destination_account.user_id != user.id:
        raise HTTPException(status_code=404, detail="Wallet was not found")
    if AccountType.EMPLOYER_PLAN in (
        source_account.account_type,
        destination_account.account_type,
    ):
        raise HTTPException(
            status_code=422,
            detail="Employer-plan accounts cannot take part in cash transfers",
        )

    if source.currency == destination.currency:
        destination_amount = payload.destination_amount or payload.source_amount
        if destination_amount != payload.source_amount:
            raise HTTPException(
                status_code=422,
                detail="Both wallets use the same currency, so the amounts must match",
            )
    else:
        if payload.destination_amount is None:
            raise HTTPException(
                status_code=422,
                detail="Enter the amount received, because the wallets use different currencies",
            )
        destination_amount = payload.destination_amount

    fee_amount = payload.fee_amount
    source_debit = payload.source_amount
    destination_credit = destination_amount
    if fee_amount is not None:
        if payload.fee_side == "SOURCE":
            if payload.fee_currency != source.currency:
                raise HTTPException(
                    status_code=422,
                    detail="A fee charged to the source must use the source wallet's currency",
                )
            source_debit += fee_amount
        else:
            if payload.fee_currency != destination.currency:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "A fee charged to the destination must use the destination "
                        "wallet's currency"
                    ),
                )
            if destination_amount <= fee_amount:
                raise HTTPException(
                    status_code=422,
                    detail="The fee must be smaller than the amount received",
                )
            destination_credit -= fee_amount

    if source.cash_balance < source_debit:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Insufficient balance: {source.currency.value} "
                f"{source.cash_balance:.2f} available"
            ),
        )

    transfer = CashTransfer(
        user_id=user.id,
        client_request_id=payload.idempotency_key,
        source_subaccount_id=source.id,
        destination_subaccount_id=destination.id,
        source_amount=payload.source_amount,
        source_currency=source.currency,
        destination_amount=destination_amount,
        destination_currency=destination.currency,
        fee_amount=fee_amount,
        fee_currency=payload.fee_currency,
        fee_side=payload.fee_side,
        transfer_date=payload.transfer_date,
    )
    session.add(transfer)
    source.cash_balance -= source_debit
    destination.cash_balance += destination_credit
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This transfer was already recorded; refresh the portfolio.",
        ) from error
    session.refresh(transfer)
    return _cash_transfer_response(
        transfer, source_account.display_name, destination_account.display_name
    )


def spend_cash(
    session: Session, user_id: uuid.UUID, payload: CashSpendCreate
) -> CashSpendResponse:
    user = _get_user(session, user_id)
    existing = session.scalar(
        select(CashSpend).where(
            CashSpend.user_id == user.id,
            CashSpend.client_request_id == payload.idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.subaccount_id != payload.subaccount_id
            or existing.spend_date != payload.spend_date
            or existing.amount != payload.amount
        ):
            raise HTTPException(
                status_code=409,
                detail="This spend idempotency key was already used for different data",
            )
        subaccount = session.get(AccountSubaccount, existing.subaccount_id)
        account = session.get(BrokerAccount, subaccount.account_id) if subaccount else None
        if (
            subaccount is None
            or account is None
            or account.user_id != user.id
            or account.account_type != AccountType.BANK
        ):
            raise HTTPException(status_code=409, detail="The spend's wallet is unavailable")
        return CashSpendResponse(
            id=existing.id,
            subaccount_id=existing.subaccount_id,
            account_name=account.display_name,
            currency=existing.currency,
            amount=existing.amount,
            spend_date=existing.spend_date,
        )

    today = datetime.now(UTC).date()
    if payload.spend_date > today:
        raise HTTPException(status_code=422, detail="Spend date cannot be in the future")

    subaccount = session.scalar(
        select(AccountSubaccount)
        .where(AccountSubaccount.id == payload.subaccount_id)
        .with_for_update()
    )
    if subaccount is None:
        raise HTTPException(status_code=404, detail="Wallet was not found")
    account = session.get(BrokerAccount, subaccount.account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=404, detail="Wallet was not found")
    if account.account_type != AccountType.BANK:
        raise HTTPException(status_code=422, detail="Spending is available only for bank accounts")
    if account.provider_code == "SAMPLE":
        raise HTTPException(status_code=409, detail="Sample accounts cannot be changed")
    if subaccount.cash_balance < payload.amount:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Insufficient balance: {subaccount.currency.value} "
                f"{subaccount.cash_balance:.2f} available"
            ),
        )

    spend = CashSpend(
        user_id=user.id,
        client_request_id=payload.idempotency_key,
        subaccount_id=subaccount.id,
        amount=payload.amount,
        currency=subaccount.currency,
        spend_date=payload.spend_date,
    )
    session.add(spend)
    subaccount.cash_balance -= payload.amount
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This spend was already recorded; refresh the portfolio.",
        ) from error
    session.refresh(spend)
    return CashSpendResponse(
        id=spend.id,
        subaccount_id=spend.subaccount_id,
        account_name=account.display_name,
        currency=spend.currency,
        amount=spend.amount,
        spend_date=spend.spend_date,
    )


def _stock_transfer_response(
    transfer: StockTransfer,
    symbol: str,
    source_account_name: str,
    destination_account_name: str,
) -> StockTransferResponse:
    return StockTransferResponse(
        id=transfer.id,
        symbol=symbol,
        source_account_id=transfer.source_account_id,
        destination_account_id=transfer.destination_account_id,
        source_account_name=source_account_name,
        destination_account_name=destination_account_name,
        quantity=transfer.quantity,
        average_cost=transfer.average_cost,
        cost_basis=transfer.cost_basis,
        transfer_date=transfer.transfer_date,
        fee_amount=transfer.fee_amount,
        fee_currency=transfer.fee_currency,
        fee_side=transfer.fee_side,
    )


def transfer_stock(
    session: Session,
    user_id: uuid.UUID,
    holding_id: uuid.UUID,
    payload: StockTransferCreate,
) -> StockTransferResponse:
    user = _get_user(session, user_id)
    existing = session.scalar(
        select(StockTransfer).where(
            StockTransfer.user_id == user.id,
            StockTransfer.client_request_id == payload.idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.destination_account_id != payload.destination_account_id
            or existing.transfer_date != payload.transfer_date
            or (payload.quantity is not None and existing.quantity != payload.quantity)
            or not _transfer_fee_matches(existing, payload)
        ):
            raise HTTPException(
                status_code=409,
                detail="This transfer idempotency key was already used for different data",
            )
        instrument = session.get(Instrument, existing.instrument_id)
        source_account = session.get(BrokerAccount, existing.source_account_id)
        destination_account = session.get(BrokerAccount, existing.destination_account_id)
        return _stock_transfer_response(
            existing,
            instrument.symbol if instrument else "",
            source_account.display_name if source_account else "",
            destination_account.display_name if destination_account else "",
        )

    holding = session.scalar(
        select(Holding)
        .where(Holding.id == holding_id, Holding.user_id == user.id)
        .with_for_update()
    )
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding was not found")
    source_account = session.get(BrokerAccount, holding.account_id)
    if source_account is None:
        raise HTTPException(status_code=409, detail="The holding's account is unavailable")
    destination_account = session.scalar(
        select(BrokerAccount).where(
            BrokerAccount.id == payload.destination_account_id,
            BrokerAccount.user_id == user.id,
        )
    )
    if destination_account is None:
        raise HTTPException(status_code=404, detail="Destination account was not found")
    if destination_account.id == source_account.id:
        raise HTTPException(status_code=422, detail="Choose a different destination account")
    if AccountType.EMPLOYER_PLAN in (
        source_account.account_type,
        destination_account.account_type,
    ):
        raise HTTPException(
            status_code=422,
            detail="Employer-plan accounts cannot take part in stock transfers",
        )
    instrument = session.get(Instrument, holding.instrument_id)
    if instrument is None:
        raise HTTPException(status_code=409, detail="The position's instrument is unavailable")

    linked_goal = session.scalar(
        select(GoalHoldingAllocation.id).where(GoalHoldingAllocation.holding_id == holding.id)
    )
    if linked_goal is not None:
        raise HTTPException(
            status_code=409,
            detail="This position is assigned to a goal; unassign it before transferring it",
        )

    today = datetime.now(UTC).date()
    if payload.transfer_date > today:
        raise HTTPException(status_code=422, detail="Transfer date cannot be in the future")
    if payload.transfer_date < holding.purchase_date:
        raise HTTPException(
            status_code=422,
            detail=(
                "Transfer date cannot be before the purchase date "
                f"({holding.purchase_date.isoformat()})"
            ),
        )
    quantity = payload.quantity if payload.quantity is not None else holding.quantity
    if quantity > holding.quantity:
        raise HTTPException(
            status_code=422,
            detail=f"Only {holding.quantity:f} units are held; cannot transfer {quantity:f}",
        )
    is_full_transfer = quantity == holding.quantity

    fee_wallet: AccountSubaccount | None = None
    if payload.fee_amount is not None:
        fee_account = source_account if payload.fee_side == "SOURCE" else destination_account
        fee_wallet = session.scalar(
            select(AccountSubaccount)
            .where(
                AccountSubaccount.account_id == fee_account.id,
                AccountSubaccount.currency == payload.fee_currency,
            )
            .with_for_update()
        )
        if fee_wallet is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{fee_account.display_name} has no {payload.fee_currency.value} wallet "
                    "to pay the fee from"
                ),
            )
        if fee_wallet.cash_balance < payload.fee_amount:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Insufficient balance for the fee: {fee_wallet.currency.value} "
                    f"{fee_wallet.cash_balance:.2f} available"
                ),
            )

    average_cost = holding.average_cost
    cost_basis = round_money(quantity * average_cost)
    destination_holding = session.scalar(
        select(Holding)
        .where(
            Holding.user_id == user.id,
            Holding.account_id == destination_account.id,
            Holding.instrument_id == instrument.id,
        )
        .with_for_update()
    )
    if destination_holding is None:
        destination_holding = Holding(
            user_id=user.id,
            account_id=destination_account.id,
            funding_subaccount_id=None,
            instrument_id=instrument.id,
            quantity=quantity,
            average_cost=average_cost,
            purchase_date=holding.purchase_date,
            risk_tier=holding.risk_tier,
            expected_annual_return=holding.expected_annual_return,
            funding_cost=ZERO,
            sale_tax_rate=holding.sale_tax_rate,
            tax_domicile_country_code=holding.tax_domicile_country_code,
        )
        session.add(destination_holding)
    else:
        if destination_holding.tax_domicile_country_code is None:
            destination_holding.tax_domicile_country_code = (
                holding.tax_domicile_country_code
            )
        total_quantity = destination_holding.quantity + quantity
        destination_holding.average_cost = (
            destination_holding.quantity * destination_holding.average_cost
            + quantity * average_cost
        ) / total_quantity
        destination_holding.quantity = total_quantity
        destination_holding.purchase_date = min(
            destination_holding.purchase_date, holding.purchase_date
        )

    transfer = StockTransfer(
        user_id=user.id,
        client_request_id=payload.idempotency_key,
        instrument_id=instrument.id,
        source_account_id=source_account.id,
        destination_account_id=destination_account.id,
        quantity=quantity,
        average_cost=average_cost,
        cost_basis=cost_basis,
        fee_amount=payload.fee_amount,
        fee_currency=payload.fee_currency,
        fee_side=payload.fee_side,
        transfer_date=payload.transfer_date,
    )
    session.add(transfer)

    if is_full_transfer:
        session.delete(holding)
    else:
        remaining_quantity = holding.quantity - quantity
        holding.funding_cost = round_money(
            holding.funding_cost * remaining_quantity / holding.quantity
        )
        holding.quantity = remaining_quantity

    if fee_wallet is not None and payload.fee_amount is not None:
        fee_wallet.cash_balance -= payload.fee_amount
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This transfer was already recorded; refresh the portfolio.",
        ) from error
    session.refresh(transfer)
    return _stock_transfer_response(
        transfer, instrument.symbol, source_account.display_name, destination_account.display_name
    )


def _save_market_fx_quote(session: Session, quote: ExchangeRateQuote) -> None:
    canonical_pairs = {
        frozenset((Currency.EUR, Currency.USD)): (Currency.EUR, Currency.USD),
        frozenset((Currency.EUR, Currency.RON)): (Currency.EUR, Currency.RON),
        frozenset((Currency.USD, Currency.RON)): (Currency.USD, Currency.RON),
    }
    canonical_pair = canonical_pairs[frozenset((quote.base_currency, quote.quote_currency))]
    if (quote.base_currency, quote.quote_currency) != canonical_pair:
        quote = ExchangeRateQuote(
            base_currency=canonical_pair[0],
            quote_currency=canonical_pair[1],
            rate=ONE / quote.rate,
            observed_at=quote.observed_at,
        )
    existing = session.scalar(
        select(MarketFXRate).where(
            MarketFXRate.base_currency == quote.base_currency,
            MarketFXRate.quote_currency == quote.quote_currency,
            MarketFXRate.provider == PROVIDER_NAME,
            MarketFXRate.observed_at == quote.observed_at,
        )
    )
    if existing is not None:
        existing.rate = quote.rate
        return
    previous = session.scalar(
        select(MarketFXRate)
        .where(
            MarketFXRate.base_currency == quote.base_currency,
            MarketFXRate.quote_currency == quote.quote_currency,
            MarketFXRate.provider == PROVIDER_NAME,
        )
        .order_by(MarketFXRate.received_at.desc(), MarketFXRate.id.desc())
        .limit(1)
    )
    session.add(
        MarketFXRate(
            base_currency=quote.base_currency,
            quote_currency=quote.quote_currency,
            rate=quote.rate,
            provider=PROVIDER_NAME,
            observed_at=quote.observed_at,
            previous_rate=previous.rate if previous is not None else None,
        )
    )


async def refresh_market_data(
    session: Session, user_id: uuid.UUID
) -> MarketRefreshResponse:
    user = _get_user(session, user_id)
    settings = get_settings()
    client = _market_client()
    instrument_ids = set(
        session.scalars(select(Holding.instrument_id).where(Holding.user_id == user.id))
    )
    instrument_ids.update(
        session.scalars(select(VestingGrant.instrument_id).where(VestingGrant.user_id == user.id))
    )
    instruments = (
        list(
            session.scalars(
                select(Instrument)
                .where(Instrument.id.in_(instrument_ids))
                .order_by(Instrument.symbol)
            )
        )
        if instrument_ids
        else []
    )
    if len(instruments) > settings.market_data_max_symbols:
        raise HTTPException(
            status_code=413,
            detail=(
                f"This profile has {len(instruments)} different held or granted symbols; "
                f"the manual refresh limit is {settings.market_data_max_symbols}."
            ),
        )

    updated_symbols: list[str] = []
    updated_fx_pairs: list[str] = []
    errors: list[str] = []
    rate_limited = False
    for instrument in instruments:
        try:
            quote = await client.quote(
                instrument.symbol,
                instrument.mic if instrument.mic != "UNKNOWN" else None,
                instrument.exchange or None,
            )
        except MarketDataProviderError as error:
            errors.append(f"{instrument.symbol}: {error.detail}")
            if error.status_code == 429:
                rate_limited = True
                break
            continue
        if quote.currency != instrument.currency:
            errors.append(
                f"{instrument.symbol}: provider quote currency changed from "
                f"{instrument.currency.value} to {quote.currency.value}; mark not updated."
            )
            continue
        session.add(
            MarketPriceCache(
                instrument_id=instrument.id,
                price=quote.price,
                currency=quote.currency,
                source="TWELVE_DATA",
                feed_type="QUOTE",
                observed_at=quote.observed_at,
                is_market_open=quote.is_market_open,
            )
        )
        updated_symbols.append(instrument.symbol)

    if rate_limited:
        errors.append("Remaining quotes and FX pairs were skipped after the provider rate limit.")
    else:
        for pair in ("EUR/USD", "EUR/RON", "USD/RON"):
            try:
                quote = await client.exchange_rate(pair)
            except MarketDataProviderError as error:
                errors.append(f"{pair}: {error.detail}")
                if error.status_code == 429:
                    break
                continue
            _save_market_fx_quote(session, quote)
            updated_fx_pairs.append(pair)

    if not updated_symbols and not updated_fx_pairs:
        session.rollback()
        detail = (
            errors[0]
            if errors
            else "No held or granted symbols or supported FX pairs were refreshed."
        )
        raise HTTPException(status_code=502, detail=detail)
    session.commit()
    return MarketRefreshResponse(
        updated_symbols=updated_symbols,
        updated_fx_pairs=updated_fx_pairs,
        errors=errors,
    )


def _can_convert(
    from_currency: Currency,
    to_currency: Currency,
    rates: dict[tuple[Currency, Currency], Decimal],
    usd_per_eur: Decimal | None = None,
) -> bool:
    try:
        _to_base(ONE, from_currency, to_currency, usd_per_eur, rates)
    except HTTPException as error:
        if error.status_code != 409:
            raise
        return False
    return True


def _target_weights(policy: AllocationPolicy) -> dict[str, Decimal]:
    return {
        asset_class.value: Decimal(str(policy.target_weights.get(asset_class.value, "0")))
        for asset_class in AssetClass
    }


def _profile_response(user: User) -> UserProfileResponse:
    tax_rules = get_country_tax_rules(user.tax_residence_country_code, user.tax_year)
    return UserProfileResponse(
        id=user.id,
        username=user.username or "",
        display_name=user.display_name,
        base_currency=user.base_currency,
        usd_per_eur=user.usd_per_eur,
        tax_residence_country_code=user.tax_residence_country_code,
        tax_year=user.tax_year,
        tax_minimum_monthly_wage=user.tax_minimum_monthly_wage,
        tax_rules_status=country_rule_status(
            user.tax_residence_country_code, user.tax_year
        ),
        tax_rule_version=tax_rules.version if tax_rules is not None else None,
        tax_rule_sources=list(tax_rules.source_urls) if tax_rules is not None else [],
        tax_rule_limitations=list(tax_rules.limitations) if tax_rules is not None else [],
    )


def _tax_profile_warnings(user: User) -> list[str]:
    country_code = user.tax_residence_country_code
    tax_year = user.tax_year
    if country_code is None or tax_year is None:
        return [
            "Tax residence is not configured. Legacy/manual tax estimates remain in use and "
            "are not country-specific."
        ]
    rule_pack = get_country_tax_rules(country_code, tax_year)
    if rule_pack is None:
        return [
            f"No built-in tax rules are available for {country_code}/{tax_year}. "
            "Legacy/manual estimates are not a substitute for that country's tax rules."
        ]
    return [
        f"Tax rule pack {rule_pack.version} is {rule_pack.status} and is not tax advice.",
        *rule_pack.limitations,
    ]


def get_policy_response(session: Session, user_id: uuid.UUID) -> PolicyResponse:
    user = _get_user(session, user_id)
    policy = _get_policy(session, user.id)
    return PolicyResponse(
        funding_rule=policy.funding_rule,
        emergency_reserve=policy.emergency_reserve,
        target_weights=_target_weights(policy),
    )


def _subaccount_summary(subaccount: AccountSubaccount) -> AccountSubaccountSummary:
    return AccountSubaccountSummary(
        id=subaccount.id,
        currency=subaccount.currency,
        cash_balance=subaccount.cash_balance,
        is_primary=subaccount.is_primary,
        annual_interest_rate=subaccount.annual_interest_rate,
        interest_start_date=subaccount.interest_start_date,
    )


def _resolve_interest_settings(
    account_type: AccountType, rate: Decimal | None, start_date: date | None
) -> tuple[Decimal | None, date | None]:
    if rate is None:
        return None, None
    if account_type == AccountType.EMPLOYER_PLAN:
        raise HTTPException(
            status_code=422,
            detail="Employer-plan accounts cannot earn cash interest.",
        )
    return rate, start_date or date.today()


def list_accounts(session: Session, user_id: uuid.UUID) -> list[AccountSummary]:
    user = _get_user(session, user_id)
    _post_due_savings_interest(session, user.id)
    accounts = list(
        session.scalars(
            select(BrokerAccount)
            .where(BrokerAccount.user_id == user.id)
            .order_by(BrokerAccount.account_type, BrokerAccount.display_name)
        )
    )
    position_counts = dict(
        session.execute(
            select(Holding.account_id, func.count(Holding.id))
            .where(Holding.user_id == user.id)
            .group_by(Holding.account_id)
        ).all()
    )
    subaccounts_by_account: dict[uuid.UUID, list[AccountSubaccount]] = {}
    for subaccount in session.scalars(
        select(AccountSubaccount)
        .where(AccountSubaccount.account_id.in_([account.id for account in accounts]))
        .order_by(
            AccountSubaccount.account_id,
            AccountSubaccount.is_primary.desc(),
            AccountSubaccount.currency,
        )
    ):
        subaccounts_by_account.setdefault(subaccount.account_id, []).append(subaccount)
    return [
        AccountSummary(
            id=account.id,
            display_name=account.display_name,
            provider_code=account.provider_code,
            account_type=account.account_type,
            broker_country_code=account.broker_country_code,
            tax_reporting_method=account.tax_reporting_method,
            currency=(subaccounts_by_account[account.id][0].currency),
            cash_balance=(subaccounts_by_account[account.id][0].cash_balance),
            position_count=position_counts.get(account.id, 0),
            is_sample=account.provider_code == "SAMPLE",
            subaccounts=[
                _subaccount_summary(subaccount)
                for subaccount in subaccounts_by_account[account.id]
            ],
        )
        for account in accounts
    ]


def create_account(session: Session, user_id: uuid.UUID, payload: AccountCreate) -> AccountSummary:
    user = _get_user(session, user_id)
    interest_rate, interest_start = _resolve_interest_settings(
        payload.account_type, payload.annual_interest_rate, payload.interest_start_date
    )
    if payload.opening_cash and not _can_convert(
        payload.currency, user.base_currency, _fx_matrix(session, user), user.usd_per_eur
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Refresh market data or set a manual USD-per-EUR reference rate before "
                "adding an account in another currency."
            ),
        )
    account = BrokerAccount(
        user_id=user.id,
        provider_code=payload.provider_code,
        display_name=payload.display_name,
        account_type=payload.account_type,
        broker_country_code=payload.broker_country_code,
        tax_reporting_method=payload.tax_reporting_method,
    )
    session.add(account)
    try:
        session.flush()
        primary_subaccount = AccountSubaccount(
            account_id=account.id,
            currency=payload.currency,
            cash_balance=payload.opening_cash,
            is_primary=True,
            annual_interest_rate=interest_rate,
            interest_start_date=interest_start,
        )
        session.add(primary_subaccount)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account with that name already exists in this profile",
        ) from error
    session.refresh(account)
    session.refresh(primary_subaccount)
    return AccountSummary(
        id=account.id,
        display_name=account.display_name,
        provider_code=account.provider_code,
        account_type=account.account_type,
        broker_country_code=account.broker_country_code,
        tax_reporting_method=account.tax_reporting_method,
        currency=primary_subaccount.currency,
        cash_balance=primary_subaccount.cash_balance,
        position_count=0,
        is_sample=False,
        subaccounts=[_subaccount_summary(primary_subaccount)],
    )


def update_account_tax_profile(
    session: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    payload: AccountTaxProfileUpdate,
) -> AccountSummary:
    user = _get_user(session, user_id)
    account = session.scalar(
        select(BrokerAccount).where(
            BrokerAccount.id == account_id,
            BrokerAccount.user_id == user.id,
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Account was not found")
    if "broker_country_code" in payload.model_fields_set:
        account.broker_country_code = payload.broker_country_code
    account.tax_reporting_method = payload.tax_reporting_method
    session.commit()
    return next(
        item for item in list_accounts(session, user.id) if item.id == account.id
    )


def _broker_import_account(
    session: Session, user_id: uuid.UUID, account_id: uuid.UUID
) -> BrokerAccount:
    account = session.scalar(
        select(BrokerAccount).where(
            BrokerAccount.id == account_id,
            BrokerAccount.user_id == user_id,
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Account was not found")
    if account.provider_code.strip().upper() != "XTB":
        raise HTTPException(
            status_code=422,
            detail="File-history import currently supports XTB accounts only.",
        )
    if account.account_type != AccountType.BROKERAGE:
        raise HTTPException(
            status_code=422,
            detail="XTB history can only be imported into a brokerage account.",
        )
    return account


def _parse_broker_upload(
    session: Session,
    account: BrokerAccount,
    data: bytes,
    filename: str,
) -> ParsedBrokerReport:
    primary_currency = session.scalar(
        select(AccountSubaccount.currency)
        .where(
            AccountSubaccount.account_id == account.id,
            AccountSubaccount.is_primary.is_(True),
        )
        .limit(1)
    )
    if primary_currency is None:
        raise HTTPException(
            status_code=409,
            detail="Add a primary currency wallet to this account before importing history.",
        )
    try:
        return parse_xtb_report(data, filename, primary_currency.value)
    except BrokerImportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _existing_broker_event_ids(
    session: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    provider_code: str,
    event_ids: list[str],
) -> set[str]:
    if not event_ids:
        return set()
    existing: set[str] = set()
    for offset in range(0, len(event_ids), 5000):
        existing.update(
            session.scalars(
                select(BrokerTransaction.source_event_id).where(
                    BrokerTransaction.user_id == user_id,
                    BrokerTransaction.account_id == account_id,
                    BrokerTransaction.provider_code == provider_code,
                    BrokerTransaction.source_event_id.in_(event_ids[offset : offset + 5000]),
                )
            )
        )
    return existing


def _broker_transaction_preview(
    transaction: ParsedBrokerTransaction,
) -> BrokerTransactionPreview:
    return BrokerTransactionPreview(
        row_number=transaction.row_number,
        event_type=transaction.event_type,
        event_at=transaction.event_at,
        opened_at=transaction.opened_at,
        closed_at=transaction.closed_at,
        symbol=transaction.symbol,
        description=transaction.description,
        direction=transaction.direction,
        asset_type=transaction.asset_type,
        quantity=transaction.quantity,
        open_price=transaction.open_price,
        close_price=transaction.close_price,
        amount=transaction.amount,
        currency_code=transaction.currency_code,
        commission=transaction.commission,
        swap=transaction.swap,
        taxes=transaction.taxes,
        reported_profit=transaction.reported_profit,
    )


def preview_broker_import(
    session: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    filename: str,
    data: bytes,
    stocks_etfs_only: bool,
) -> BrokerImportPreviewResponse:
    _get_user(session, user_id)
    account = _broker_import_account(session, user_id, account_id)
    report = _parse_broker_upload(session, account, data, filename)
    event_ids = [transaction.source_event_id for transaction in report.transactions]
    existing_batch = session.scalar(
        select(BrokerImportBatch).where(
            BrokerImportBatch.user_id == user_id,
            BrokerImportBatch.account_id == account.id,
            BrokerImportBatch.provider_code == account.provider_code,
            BrokerImportBatch.content_sha256 == report.content_sha256,
        )
    )
    duplicates = (
        len(report.transactions)
        if existing_batch is not None
        else len(
            _existing_broker_event_ids(
                session, user_id, account.id, account.provider_code, event_ids
            )
        )
    )
    warnings = list(report.warnings)
    warnings.append(
        "Preview is read-only. Import saves history rows only; it does not change account "
        "balances or current holdings."
    )
    if stocks_etfs_only:
        warnings.append(
            "You marked this report as stocks/ETFs only. Estimated tax uses the broker-reported "
            "profit as a proxy and is not an annual tax calculation."
        )
    return BrokerImportPreviewResponse(
        content_sha256=report.content_sha256,
        source_format=report.source_format,
        transaction_count=len(report.transactions),
        closed_position_count=sum(
            transaction.event_type == "closed_position"
            for transaction in report.transactions
        ),
        cash_operation_count=sum(
            transaction.event_type == "cash_operation"
            for transaction in report.transactions
        ),
        duplicate_count=duplicates,
        stocks_etfs_only=stocks_etfs_only,
        warnings=warnings,
        sample=[
            _broker_transaction_preview(transaction)
            for transaction in report.transactions[:20]
        ],
    )


def import_broker_history(
    session: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    filename: str,
    data: bytes,
    expected_sha256: str,
    stocks_etfs_only: bool,
) -> BrokerImportResponse:
    user = _get_user(session, user_id)
    account = _broker_import_account(session, user.id, account_id)
    report = _parse_broker_upload(session, account, data, filename)
    if report.content_sha256 != expected_sha256:
        raise HTTPException(
            status_code=409,
            detail="The selected file changed after preview. Preview it again before importing.",
        )
    existing_batch = session.scalar(
        select(BrokerImportBatch).where(
            BrokerImportBatch.user_id == user.id,
            BrokerImportBatch.account_id == account.id,
            BrokerImportBatch.provider_code == account.provider_code,
            BrokerImportBatch.content_sha256 == report.content_sha256,
        )
    )
    if existing_batch is not None:
        if existing_batch.stocks_etfs_only != stocks_etfs_only:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This report was already imported with a different stocks/ETFs-only "
                    "setting. Remove that import before changing the setting."
                ),
            )
        return BrokerImportResponse(
            batch_id=existing_batch.id,
            imported_count=0,
            duplicate_count=len(report.transactions),
            stocks_etfs_only=existing_batch.stocks_etfs_only,
            warnings=["This exact report file has already been imported."],
        )

    event_ids = [transaction.source_event_id for transaction in report.transactions]
    existing_ids = _existing_broker_event_ids(
        session, user.id, account.id, account.provider_code, event_ids
    )
    new_transactions = [
        transaction
        for transaction in report.transactions
        if transaction.source_event_id not in existing_ids
    ]
    duplicate_count = len(report.transactions) - len(new_transactions)
    batch = BrokerImportBatch(
        user_id=user.id,
        account_id=account.id,
        provider_code=account.provider_code,
        content_sha256=report.content_sha256,
        source_format=report.source_format,
        stocks_etfs_only=stocks_etfs_only,
        record_count=len(new_transactions),
        duplicate_count=duplicate_count,
    )
    try:
        session.add(batch)
        session.flush()
        session.add_all(
            [
                BrokerTransaction(
                    user_id=user.id,
                    account_id=account.id,
                    import_batch_id=batch.id,
                    provider_code=account.provider_code,
                    source_event_id=transaction.source_event_id,
                    event_type=transaction.event_type,
                    source_sheet=transaction.source_sheet,
                    broker_reference=transaction.broker_reference,
                    event_at=transaction.event_at,
                    opened_at=transaction.opened_at,
                    closed_at=transaction.closed_at,
                    symbol=transaction.symbol,
                    description=transaction.description,
                    direction=transaction.direction,
                    asset_type=transaction.asset_type,
                    quantity=transaction.quantity,
                    open_price=transaction.open_price,
                    close_price=transaction.close_price,
                    amount=transaction.amount,
                    currency_code=transaction.currency_code,
                    commission=transaction.commission,
                    swap=transaction.swap,
                    taxes=transaction.taxes,
                    reported_profit=transaction.reported_profit,
                    balance_after=transaction.balance_after,
                )
                for transaction in new_transactions
            ]
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Some report transactions were imported by another request. "
                "Preview the file again."
            ),
        ) from error
    return BrokerImportResponse(
        batch_id=batch.id,
        imported_count=len(new_transactions),
        duplicate_count=duplicate_count,
        stocks_etfs_only=stocks_etfs_only,
        warnings=list(report.warnings),
    )


def _is_stock_or_etf_asset_type(asset_type: str | None) -> bool:
    if asset_type is None:
        return False
    normalized = re.sub(r"[^a-z]", "", asset_type.lower())
    return normalized in {
        "stock",
        "stocks",
        "share",
        "shares",
        "equity",
        "equities",
        "etf",
        "etfs",
    }


def _broker_transaction_summary(
    transaction: BrokerTransaction,
    batch: BrokerImportBatch,
    user: User,
    account: BrokerAccount,
) -> BrokerTransactionSummary:
    estimated_tax: Decimal | None = None
    estimated_tax_rate: Decimal | None = None
    estimated_tax_status = "not_estimated"
    tax_warnings: list[str] = []
    can_estimate_trade_tax = (
        transaction.event_type == "closed_position"
        and transaction.reported_profit is not None
        and transaction.opened_at is not None
        and transaction.closed_at is not None
        and transaction.direction == "BUY"
        and (
            _is_stock_or_etf_asset_type(transaction.asset_type)
            or (batch.stocks_etfs_only and transaction.asset_type is None)
        )
    )
    if can_estimate_trade_tax:
        tax_estimate = estimate_capital_gain_tax(
            gross_proceeds=transaction.reported_profit or ZERO,
            cost_basis=ZERO,
            acquired_on=transaction.opened_at.date(),
            sold_on=transaction.closed_at.date(),
            country_code=user.tax_residence_country_code,
            tax_year=transaction.closed_at.year,
            intermediary_country_code=account.broker_country_code,
            reporting_method=str(account.tax_reporting_method),
            manual_rate=None,
            legacy_rate=DEFAULT_SALE_TAX_RATE,
            tax_exempt=account.tax_reporting_method == TaxReportingMethod.TAX_EXEMPT,
        )
        estimated_tax = tax_estimate.tax_amount
        estimated_tax_rate = tax_estimate.rate
        estimated_tax_status = tax_estimate.status
        tax_warnings = [
            *tax_estimate.warnings,
            "This proxy applies the rate to XTB-reported profit; confirm how fees, taxes, "
            "short positions, losses, and annual offsets are treated before relying on it.",
            "The current tax residence and account reporting method are applied to historical "
            "rows; previous-year profile changes are not modeled.",
        ]
    elif transaction.event_type == "closed_position":
        if transaction.direction == "SELL":
            estimated_tax_status = "not_estimated_short_position"
            tax_warnings.append("Short positions are not included in this tax estimate.")
        elif not (
            _is_stock_or_etf_asset_type(transaction.asset_type) or batch.stocks_etfs_only
        ):
            estimated_tax_status = "not_estimated_asset_type_unknown"
            tax_warnings.append(
                "Confirm the report contains only stocks/ETFs or provides an instrument type "
                "before estimating tax."
            )
        elif transaction.reported_profit is None:
            estimated_tax_status = "not_estimated_profit_missing"
            tax_warnings.append("The broker report did not provide a profit value.")
    return BrokerTransactionSummary(
        id=transaction.id,
        import_batch_id=batch.id,
        event_type=transaction.event_type,
        source_sheet=transaction.source_sheet,
        broker_reference=transaction.broker_reference,
        event_at=transaction.event_at,
        opened_at=transaction.opened_at,
        closed_at=transaction.closed_at,
        symbol=transaction.symbol,
        description=transaction.description,
        direction=transaction.direction,
        asset_type=transaction.asset_type,
        quantity=transaction.quantity,
        open_price=transaction.open_price,
        close_price=transaction.close_price,
        amount=transaction.amount,
        currency_code=transaction.currency_code,
        commission=transaction.commission,
        swap=transaction.swap,
        taxes=transaction.taxes,
        reported_profit=transaction.reported_profit,
        balance_after=transaction.balance_after,
        estimated_tax=estimated_tax,
        estimated_tax_rate=estimated_tax_rate,
        estimated_tax_status=estimated_tax_status,
        tax_estimate_warnings=tax_warnings,
    )


def list_broker_transactions(
    session: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    offset: int,
    limit: int,
) -> BrokerTransactionListResponse:
    user = _get_user(session, user_id)
    account = _broker_import_account(session, user.id, account_id)
    filters = (
        BrokerTransaction.user_id == user.id,
        BrokerTransaction.account_id == account.id,
    )
    total = session.scalar(
        select(func.count(BrokerTransaction.id)).where(*filters)
    ) or 0
    rows = session.execute(
        select(BrokerTransaction, BrokerImportBatch)
        .join(BrokerImportBatch, BrokerImportBatch.id == BrokerTransaction.import_batch_id)
        .where(*filters)
        .order_by(BrokerTransaction.event_at.desc(), BrokerTransaction.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return BrokerTransactionListResponse(
        total=total,
        offset=offset,
        limit=limit,
        transactions=[
            _broker_transaction_summary(transaction, batch, user, account)
            for transaction, batch in rows
        ],
    )


def delete_broker_import(
    session: Session, user_id: uuid.UUID, account_id: uuid.UUID, batch_id: uuid.UUID
) -> None:
    user = _get_user(session, user_id)
    _broker_import_account(session, user.id, account_id)
    batch = session.scalar(
        select(BrokerImportBatch).where(
            BrokerImportBatch.id == batch_id,
            BrokerImportBatch.user_id == user.id,
            BrokerImportBatch.account_id == account_id,
        )
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Broker import was not found")
    session.delete(batch)
    session.commit()


def calculate_annual_tax_summary(
    session: Session,
    user_id: uuid.UUID,
    payload: TaxAnnualSummaryRequest,
) -> TaxAnnualSummaryResponse:
    user = _get_user(session, user_id)
    country_code = user.tax_residence_country_code
    tax_year = user.tax_year
    rule_status = country_rule_status(country_code, tax_year)
    base_response = {
        "country_code": country_code,
        "tax_year": tax_year,
        "rule_status": rule_status,
        "qualifying_income_ron": payload.annual_qualifying_income_ron,
        "complete_for_filing": False,
    }
    if country_code is None or tax_year is None:
        return TaxAnnualSummaryResponse(
            **base_response,
            cass_status="not_configured",
            warnings=["Configure tax residence and tax year before calculating CASS."],
        )
    rule_pack = get_country_tax_rules(country_code, tax_year)
    if rule_pack is None:
        return TaxAnnualSummaryResponse(
            **base_response,
            cass_status="unsupported",
            warnings=[
                f"No CASS calculator is available for {country_code}/{tax_year}.",
                "No rate or threshold from another country is substituted.",
            ],
        )

    minimum_monthly_wage = (
        user.tax_minimum_monthly_wage or rule_pack.minimum_monthly_wage_at_year_start
    )
    thresholds: list[TaxCassThreshold] = []
    if minimum_monthly_wage is not None and minimum_monthly_wage > ZERO:
        thresholds = [
            TaxCassThreshold(
                wage_multiple=multiple,
                threshold_ron=minimum_monthly_wage * multiple,
                cass_at_threshold_ron=round_money(
                    minimum_monthly_wage * multiple * rule_pack.cass_rate
                ),
            )
            for multiple in rule_pack.cass_threshold_wages
        ]
    estimate = estimate_country_cass(
        annual_qualifying_investment_income=payload.annual_qualifying_income_ron,
        minimum_monthly_wage=minimum_monthly_wage,
        country_code=country_code,
        tax_year=tax_year,
    )
    return TaxAnnualSummaryResponse(
        **base_response,
        rule_version=rule_pack.version,
        minimum_monthly_wage_ron=minimum_monthly_wage,
        cass_rate=rule_pack.cass_rate,
        threshold_bands=thresholds,
        cass_taxable_base_ron=estimate.taxable_amount,
        estimated_cass_ron=estimate.tax_amount,
        cass_status=estimate.status,
        warnings=[
            *estimate.warnings,
            "This calculator uses the annual qualifying income total you entered; it does not "
            "collect or validate every income source for the tax year.",
            "This is a CASS estimate only, not a calculation of dividend, interest, or "
            "capital-gains income tax and not a completed Form 212.",
            *rule_pack.limitations,
        ],
        source_urls=list(rule_pack.source_urls),
        limitations=list(rule_pack.limitations),
    )


def create_account_subaccount(
    session: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    payload: AccountSubaccountCreate,
) -> AccountSubaccountSummary:
    user = _get_user(session, user_id)
    account = session.scalar(
        select(BrokerAccount)
        .where(BrokerAccount.id == account_id, BrokerAccount.user_id == user.id)
        .with_for_update()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Account was not found")
    existing = session.scalar(
        select(AccountSubaccount).where(
            AccountSubaccount.account_id == account.id,
            AccountSubaccount.currency == payload.currency,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"This account already has a {payload.currency.value} sub-account.",
        )
    if account.account_type == AccountType.EMPLOYER_PLAN and payload.opening_balance > ZERO:
        raise HTTPException(
            status_code=422,
            detail="Employer-plan sub-accounts cannot hold available cash balances.",
        )
    if payload.opening_balance and not _can_convert(
        payload.currency, user.base_currency, _fx_matrix(session, user), user.usd_per_eur
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Refresh market data or configure an FX reference before entering a balance "
                "in this currency."
            ),
        )
    interest_rate, interest_start = _resolve_interest_settings(
        account.account_type, payload.annual_interest_rate, payload.interest_start_date
    )
    subaccount = AccountSubaccount(
        account_id=account.id,
        currency=payload.currency,
        cash_balance=payload.opening_balance,
        is_primary=False,
        annual_interest_rate=interest_rate,
        interest_start_date=interest_start,
    )
    session.add(subaccount)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"This account already has a {payload.currency.value} sub-account.",
        ) from error
    session.refresh(subaccount)
    return _subaccount_summary(subaccount)


def update_subaccount_interest(
    session: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    subaccount_id: uuid.UUID,
    payload: SubaccountInterestUpdate,
) -> AccountSubaccountSummary:
    _get_user(session, user_id)
    row = session.execute(
        select(AccountSubaccount, BrokerAccount)
        .join(BrokerAccount, BrokerAccount.id == AccountSubaccount.account_id)
        .where(
            AccountSubaccount.id == subaccount_id,
            BrokerAccount.id == account_id,
            BrokerAccount.user_id == user_id,
        )
        .with_for_update(of=AccountSubaccount)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Account wallet was not found")
    subaccount, account = row
    if account.provider_code == "SAMPLE":
        raise HTTPException(status_code=409, detail="Legacy sample accounts cannot be edited")
    rate, start_date = _resolve_interest_settings(
        account.account_type, payload.annual_interest_rate, payload.interest_start_date
    )
    subaccount.annual_interest_rate = rate
    subaccount.interest_start_date = start_date
    session.commit()
    session.refresh(subaccount)
    return _subaccount_summary(subaccount)


def delete_account(session: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> None:
    _get_user(session, user_id)
    account = session.scalar(
        select(BrokerAccount)
        .where(BrokerAccount.id == account_id, BrokerAccount.user_id == user_id)
        .with_for_update()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Account was not found")
    if account.provider_code == "SAMPLE":
        raise HTTPException(status_code=409, detail="Legacy sample accounts cannot be deleted")
    for schedule in session.scalars(
        select(CashFlowSchedule).where(
            CashFlowSchedule.account_id == account.id,
            CashFlowSchedule.auto_post.is_(True),
            CashFlowSchedule.is_active.is_(True),
        )
    ):
        schedule.is_active = False
        schedule.auto_post = False
    session.delete(account)
    session.commit()


def create_fixed_deposit(
    session: Session, user_id: uuid.UUID, payload: FixedDepositCreate
) -> FixedDepositCreateResponse:
    user = _get_user(session, user_id)
    account = session.scalar(
        select(BrokerAccount).where(
            BrokerAccount.id == payload.account_id,
            BrokerAccount.user_id == user.id,
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Selected deposit account was not found")
    if account.account_type not in {AccountType.BANK, AccountType.SAVINGS}:
        raise HTTPException(
            status_code=422,
            detail="Term deposits can only be added to bank or savings accounts.",
        )
    subaccount = session.scalar(
        select(AccountSubaccount)
        .where(
            AccountSubaccount.id == payload.subaccount_id,
            AccountSubaccount.account_id == account.id,
        )
        .with_for_update()
    )
    if subaccount is None:
        raise HTTPException(
            status_code=404,
            detail="Choose a currency wallet belonging to the selected account.",
        )
    fx_rates = _fx_matrix(session, user)
    if not _can_convert(
        subaccount.currency, user.base_currency, fx_rates, user.usd_per_eur
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Refresh market data or set a manual FX reference before adding a deposit "
                "in another currency."
            ),
        )
    if subaccount.cash_balance < payload.principal:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Insufficient {subaccount.currency.value} cash to fund this deposit. "
                f"Available: {subaccount.cash_balance:.2f}."
            ),
        )
    maturity_date = add_months(payload.start_date, payload.period_months)
    compounding = (
        CompoundingFrequency.MONTHLY
        if payload.capitalization
        else CompoundingFrequency.AT_MATURITY
    )
    deposit = FixedDeposit(
        user_id=user.id,
        account_id=account.id,
        source_subaccount_id=subaccount.id,
        name=payload.name,
        principal=payload.principal,
        currency=subaccount.currency,
        annual_rate=payload.annual_profit_rate,
        rate_basis=RateBasis.NOMINAL_APR,
        compounding=compounding,
        period_months=payload.period_months,
        start_date=payload.start_date,
        maturity_date=maturity_date,
    )
    subaccount.cash_balance -= payload.principal
    session.add(deposit)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="The deposit could not be saved. Refresh the account and try again.",
        ) from error
    session.refresh(deposit)
    return FixedDepositCreateResponse(
        id=deposit.id,
        name=deposit.name,
        principal=deposit.principal,
        currency=deposit.currency,
        start_date=deposit.start_date,
        maturity_date=deposit.maturity_date,
        period_months=deposit.period_months,
        annual_rate=deposit.annual_rate,
        capitalization=deposit.compounding != CompoundingFrequency.AT_MATURITY,
    )


def delete_fixed_deposit(session: Session, user_id: uuid.UUID, deposit_id: uuid.UUID) -> None:
    _get_user(session, user_id)
    deposit = session.scalar(
        select(FixedDeposit)
        .join(BrokerAccount, BrokerAccount.id == FixedDeposit.account_id)
        .where(
            FixedDeposit.id == deposit_id,
            FixedDeposit.user_id == user_id,
            BrokerAccount.user_id == user_id,
        )
        .with_for_update()
    )
    if deposit is None:
        raise HTTPException(status_code=404, detail="Deposit was not found")
    if deposit.source_subaccount_id is not None:
        subaccount = session.scalar(
            select(AccountSubaccount)
            .join(BrokerAccount, BrokerAccount.id == AccountSubaccount.account_id)
            .where(
                AccountSubaccount.id == deposit.source_subaccount_id,
                AccountSubaccount.account_id == deposit.account_id,
                BrokerAccount.user_id == user_id,
            )
            .with_for_update()
        )
        if subaccount is not None:
            subaccount.cash_balance += deposit.principal
    session.delete(deposit)
    session.commit()


def register_user(session: Session, payload: RegisterRequest, session_days: int) -> AuthResponse:
    username = payload.username
    user = User(
        id=uuid.uuid4(),
        username=username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or username,
        base_currency=payload.base_currency,
        usd_per_eur=payload.usd_per_eur,
    )
    access_token = create_access_token()
    expires_at = datetime.now(UTC) + timedelta(days=session_days)
    session.add(user)
    try:
        session.flush()
        session.add(
            AllocationPolicy(
                user_id=user.id,
                funding_rule=None,
                emergency_reserve=ZERO,
                target_weights={},
            )
        )
        session.add(FinancialPlan(
            user_id=user.id,
            configuration=FinancialPlanPayload(
                anchor_date=date.today(), expenses_currency=user.base_currency
            ).model_dump(mode="json"),
        ))
        session.add(
            LoginSession(
                user_id=user.id,
                token_digest=digest_access_token(access_token),
                expires_at=expires_at,
            )
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="That username is already registered"
        ) from error
    return AuthResponse(
        access_token=access_token,
        expires_at=expires_at,
        user=_profile_response(user),
    )


def login_user(session: Session, payload: LoginRequest, session_days: int) -> AuthResponse:
    user = session.scalar(select(User).where(User.username == payload.username))
    password_matches = verify_password(
        payload.password, user.password_hash if user is not None else None
    )
    if user is None or not password_matches:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    access_token = create_access_token()
    expires_at = datetime.now(UTC) + timedelta(days=session_days)
    session.add(
        LoginSession(
            user_id=user.id,
            token_digest=digest_access_token(access_token),
            expires_at=expires_at,
        )
    )
    session.commit()
    return AuthResponse(
        access_token=access_token,
        expires_at=expires_at,
        user=_profile_response(user),
    )


def authenticate_token(session: Session, access_token: str | None) -> User:
    if not access_token:
        raise HTTPException(status_code=401, detail="Sign in to access your application account")
    login_session = session.scalar(
        select(LoginSession).where(
            LoginSession.token_digest == digest_access_token(access_token),
            LoginSession.expires_at > datetime.now(UTC),
        )
    )
    if login_session is None:
        raise HTTPException(status_code=401, detail="Application session is invalid or expired")
    user = _get_user(session, login_session.user_id)
    if user.username is None or user.password_hash is None:
        raise HTTPException(status_code=401, detail="Application session is invalid or expired")
    return user


def logout_user(session: Session, user_id: uuid.UUID, access_token: str | None) -> None:
    if not access_token:
        return
    login_session = session.scalar(
        select(LoginSession).where(
            LoginSession.user_id == user_id,
            LoginSession.token_digest == digest_access_token(access_token),
        )
    )
    if login_session is not None:
        session.delete(login_session)
        session.commit()


def get_profile(session: Session, user_id: uuid.UUID) -> UserProfileResponse:
    return _profile_response(_get_user(session, user_id))


def update_profile(
    session: Session, user_id: uuid.UUID, payload: ProfileUpdate
) -> UserProfileResponse:
    user = _get_user(session, user_id)
    rates = _market_fx_matrix(session)
    if payload.usd_per_eur is not None:
        rates[(Currency.EUR, Currency.USD)] = payload.usd_per_eur
        rates[(Currency.USD, Currency.EUR)] = ONE / payload.usd_per_eur
    if _has_unconvertible_currency_data(
        session, user.id, payload.base_currency, rates, payload.usd_per_eur
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Refresh market data or keep a manual FX reference while your profile contains "
                "data in another currency."
            ),
        )
    user.display_name = payload.display_name
    user.base_currency = payload.base_currency
    user.usd_per_eur = payload.usd_per_eur
    tax_period_changed = (
        "tax_residence_country_code" in payload.model_fields_set
        and payload.tax_residence_country_code != user.tax_residence_country_code
    ) or ("tax_year" in payload.model_fields_set and payload.tax_year != user.tax_year)
    if "tax_residence_country_code" in payload.model_fields_set:
        user.tax_residence_country_code = payload.tax_residence_country_code
    if "tax_year" in payload.model_fields_set:
        user.tax_year = payload.tax_year
    if user.tax_residence_country_code is None or user.tax_year is None:
        user.tax_minimum_monthly_wage = None
    elif "tax_minimum_monthly_wage" in payload.model_fields_set:
        user.tax_minimum_monthly_wage = payload.tax_minimum_monthly_wage
    elif tax_period_changed:
        user.tax_minimum_monthly_wage = None
    session.commit()
    session.refresh(user)
    return _profile_response(user)


def _has_unconvertible_currency_data(
    session: Session,
    user_id: uuid.UUID,
    base_currency: Currency,
    rates: dict[tuple[Currency, Currency], Decimal],
    usd_per_eur: Decimal | None,
) -> bool:
    statements = [
        select(AccountSubaccount.currency)
        .join(BrokerAccount, BrokerAccount.id == AccountSubaccount.account_id)
        .where(BrokerAccount.user_id == user_id),
        select(Goal.target_currency).where(Goal.user_id == user_id),
        select(CashFlow.currency).where(CashFlow.user_id == user_id),
        select(CashFlowSchedule.currency).where(CashFlowSchedule.user_id == user_id),
        select(FixedDeposit.currency).where(FixedDeposit.user_id == user_id),
        select(Instrument.currency)
        .select_from(Holding)
        .join(Instrument, Instrument.id == Holding.instrument_id)
        .where(Holding.user_id == user_id),
        select(Instrument.currency)
        .select_from(VestingGrant)
        .join(Instrument, Instrument.id == VestingGrant.instrument_id)
        .where(VestingGrant.user_id == user_id),
        select(ValuationSnapshot.currency).where(ValuationSnapshot.user_id == user_id),
    ]
    for statement in statements:
        for currency in session.scalars(statement):
            if currency != base_currency and not _can_convert(
                currency, base_currency, rates, usd_per_eur
            ):
                return True
    return False


def _flow_direction(kind: FlowKind) -> FlowDirection:
    if kind == FlowKind.BILL:
        return FlowDirection.OUTFLOW
    if kind == FlowKind.CONTRIBUTION:
        return FlowDirection.TRANSFER
    return FlowDirection.INFLOW


def list_cash_flow_schedules(
    session: Session, user_id: uuid.UUID
) -> list[CashFlowScheduleResponse]:
    user = _get_user(session, user_id)
    schedules = session.scalars(
        select(CashFlowSchedule)
        .where(CashFlowSchedule.user_id == user.id, CashFlowSchedule.is_active.is_(True))
        .order_by(CashFlowSchedule.start_date, CashFlowSchedule.label)
    )
    return [CashFlowScheduleResponse.model_validate(schedule) for schedule in schedules]


def _post_due_cash_flow_schedules(
    session: Session, user_id: uuid.UUID, as_of: date | None = None
) -> None:
    today = as_of or date.today()
    schedules = list(
        session.scalars(
            select(CashFlowSchedule)
            .where(
                CashFlowSchedule.user_id == user_id,
                CashFlowSchedule.is_active.is_(True),
                CashFlowSchedule.auto_post.is_(True),
                CashFlowSchedule.start_date <= today,
            )
            .order_by(CashFlowSchedule.start_date, CashFlowSchedule.id)
            .with_for_update()
        )
    )
    changed = False
    for schedule in schedules:
        if schedule.account_id is None or schedule.subaccount_id is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Automatic income schedule “{schedule.label}” has no destination wallet. "
                    "Stop the schedule or choose a new wallet."
                ),
            )
        account = session.scalar(
            select(BrokerAccount).where(
                BrokerAccount.id == schedule.account_id,
                BrokerAccount.user_id == user_id,
            )
        )
        if account is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Automatic income schedule “{schedule.label}” has no valid destination "
                    "account. Stop the schedule or choose a new account."
                ),
            )
        through_date = min(today, schedule.end_date) if schedule.end_date else today
        if through_date < schedule.start_date:
            continue
        for occurrence in occurrence_dates(
            schedule.recurrence,
            schedule.start_date,
            schedule.end_date,
            schedule.start_date,
            through_date,
        ):
            source_event_id = f"{schedule.id}:{occurrence.isoformat()}"
            existing = session.scalar(
                select(CashFlow.id).where(
                    CashFlow.user_id == user_id,
                    CashFlow.source_system == "SCHEDULED_CASH_FLOW",
                    CashFlow.source_event_id == source_event_id,
                )
            )
            if existing is not None:
                continue
            subaccount = session.scalar(
                select(AccountSubaccount)
                .where(
                    AccountSubaccount.id == schedule.subaccount_id,
                    AccountSubaccount.account_id == account.id,
                    AccountSubaccount.currency == schedule.currency,
                )
                .with_for_update()
            )
            if subaccount is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Automatic income schedule “{schedule.label}” has no valid "
                        "destination wallet. Stop the schedule or choose a new wallet."
                    ),
                )
            occurred_at = datetime.combine(occurrence, datetime.min.time(), tzinfo=UTC) + timedelta(
                hours=12
            )
            subaccount.cash_balance += schedule.amount
            session.add(
                CashFlow(
                    user_id=user_id,
                    account_id=account.id,
                    subaccount_id=subaccount.id,
                    schedule_id=schedule.id,
                    label=schedule.label,
                    kind=schedule.kind,
                    status=FlowStatus.CONFIRMED,
                    amount=schedule.amount,
                    currency=schedule.currency,
                    expected_date=occurrence,
                    occurred_at=occurred_at,
                    source_system="SCHEDULED_CASH_FLOW",
                    source_event_id=source_event_id,
                )
            )
            changed = True
    if changed:
        session.commit()


def _monthly_payment_dates(start_date: date, through: date) -> list[date]:
    dates: list[date] = []
    for month_index in range(1, MAX_INTEREST_CATCH_UP_MONTHS + 1):
        payment_date = add_months(start_date, month_index)
        if payment_date > through:
            break
        dates.append(payment_date)
    return dates


def _post_due_savings_interest(
    session: Session, user_id: uuid.UUID, as_of: date | None = None
) -> None:
    today = as_of or date.today()
    rows = session.execute(
        select(AccountSubaccount, BrokerAccount)
        .join(BrokerAccount, BrokerAccount.id == AccountSubaccount.account_id)
        .where(
            BrokerAccount.user_id == user_id,
            AccountSubaccount.annual_interest_rate.is_not(None),
            AccountSubaccount.annual_interest_rate > ZERO,
            AccountSubaccount.interest_start_date.is_not(None),
            AccountSubaccount.interest_start_date < today,
        )
        .order_by(AccountSubaccount.id)
        .with_for_update(of=AccountSubaccount)
    ).all()
    changed = False
    for subaccount, account in rows:
        assert subaccount.annual_interest_rate is not None
        assert subaccount.interest_start_date is not None
        for payment_date in _monthly_payment_dates(subaccount.interest_start_date, today):
            source_event_id = f"{subaccount.id}:{payment_date.isoformat()}"
            existing = session.scalar(
                select(CashFlow.id).where(
                    CashFlow.user_id == user_id,
                    CashFlow.source_system == SAVINGS_INTEREST_SOURCE,
                    CashFlow.source_event_id == source_event_id,
                )
            )
            if existing is not None:
                continue
            interest = round_money(
                subaccount.cash_balance * subaccount.annual_interest_rate / Decimal(12)
            )
            if interest <= ZERO:
                continue
            subaccount.cash_balance += interest
            session.add(
                CashFlow(
                    user_id=user_id,
                    account_id=account.id,
                    subaccount_id=subaccount.id,
                    label=f"Monthly interest · {account.display_name}",
                    kind=FlowKind.INTEREST,
                    status=FlowStatus.CONFIRMED,
                    amount=interest,
                    currency=subaccount.currency,
                    expected_date=payment_date,
                    occurred_at=datetime.combine(
                        payment_date, datetime.min.time(), tzinfo=UTC
                    )
                    + timedelta(hours=12),
                    source_system=SAVINGS_INTEREST_SOURCE,
                    source_event_id=source_event_id,
                )
            )
            changed = True
    if changed:
        session.commit()


def create_cash_flow_schedule(
    session: Session, user_id: uuid.UUID, payload: CashFlowScheduleCreate
) -> CashFlowScheduleResponse:
    user = _get_user(session, user_id)
    if payload.account_id is not None or payload.subaccount_id is not None:
        if payload.account_id is None or payload.subaccount_id is None:
            raise HTTPException(
                status_code=422,
                detail="A destination account and wallet must be selected together.",
            )
        account = session.scalar(
            select(BrokerAccount).where(
                BrokerAccount.id == payload.account_id,
                BrokerAccount.user_id == user.id,
            )
        )
        if account is None:
            raise HTTPException(status_code=404, detail="Destination account was not found")
        subaccount = session.scalar(
            select(AccountSubaccount).where(
                AccountSubaccount.id == payload.subaccount_id,
                AccountSubaccount.account_id == account.id,
            )
        )
        if subaccount is None:
            raise HTTPException(status_code=404, detail="Destination wallet was not found")
        if payload.auto_post and account.account_type == AccountType.EMPLOYER_PLAN:
            raise HTTPException(
                status_code=422,
                detail="Scheduled cash income must be credited to a liquid account.",
            )
        if payload.auto_post and subaccount.currency != payload.currency:
            raise HTTPException(
                status_code=422,
                detail="The scheduled income currency must match the destination wallet.",
            )
    if not _can_convert(
        payload.currency, user.base_currency, _fx_matrix(session, user), user.usd_per_eur
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Refresh market data or set a manual USD-per-EUR reference rate before "
                "adding a forecast in another currency."
            ),
        )
    active_count = session.scalar(
        select(func.count())
        .select_from(CashFlowSchedule)
        .where(CashFlowSchedule.user_id == user.id, CashFlowSchedule.is_active.is_(True))
    )
    if (active_count or 0) >= 100:
        raise HTTPException(
            status_code=409, detail="Archive an existing schedule before adding another"
        )
    schedule = CashFlowSchedule(user_id=user.id, **payload.model_dump())
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    return CashFlowScheduleResponse.model_validate(schedule)


def _cash_receipt_response(
    flow: CashFlow,
    usd_per_eur: Decimal | None,
    base_currency: Currency,
    fx_rates: dict[tuple[Currency, Currency], Decimal],
) -> FlowResponse:
    return FlowResponse(
        id=flow.id,
        label=flow.label,
        kind=flow.kind,
        direction=FlowDirection.INFLOW,
        status=flow.status,
        amount=flow.amount,
        currency=flow.currency,
        expected_date=flow.expected_date,
        occurred_at=flow.occurred_at,
        reporting_amount=round_money(
            _to_base(flow.amount, flow.currency, base_currency, usd_per_eur, fx_rates)
        ),
        reporting_currency=base_currency,
        schedule_id=None,
        recurrence=None,
    )


def record_extra_cash(
    session: Session, user_id: uuid.UUID, payload: CashReceiptCreate
) -> FlowResponse:
    user = _get_user(session, user_id)
    event_id = str(payload.idempotency_key)
    existing = session.scalar(
        select(CashFlow).where(
            CashFlow.user_id == user.id,
            CashFlow.source_system == "USER_ENTRY",
            CashFlow.source_event_id == event_id,
        )
    )
    if existing is not None:
        same_receipt = (
            existing.account_id == payload.account_id
            and (
                payload.subaccount_id is None
                or existing.subaccount_id == payload.subaccount_id
            )
            and existing.amount == payload.amount
            and existing.label == f"Extra cash · {payload.source}"
            and existing.expected_date == payload.received_date
        )
        if not same_receipt:
            raise HTTPException(
                status_code=409,
                detail="This receipt idempotency key was already used for different data",
            )
        return _cash_receipt_response(
            existing, user.usd_per_eur, user.base_currency, _fx_matrix(session, user)
        )

    account = session.scalar(
        select(BrokerAccount)
        .where(
            BrokerAccount.id == payload.account_id,
            BrokerAccount.user_id == user.id,
        )
        .with_for_update()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Cash-receiving account was not found")
    if account.account_type == AccountType.EMPLOYER_PLAN:
        raise HTTPException(
            status_code=422,
            detail="Extra cash receipts must go to a liquid bank, savings, or brokerage account",
        )
    subaccount_query = select(AccountSubaccount).where(
        AccountSubaccount.account_id == account.id
    )
    if payload.subaccount_id is None:
        subaccount_query = subaccount_query.where(AccountSubaccount.is_primary.is_(True))
    else:
        subaccount_query = subaccount_query.where(AccountSubaccount.id == payload.subaccount_id)
    subaccount = session.scalar(subaccount_query.with_for_update())
    if subaccount is None:
        raise HTTPException(
            status_code=404, detail="Cash sub-account was not found on the selected account"
        )
    if not _can_convert(
        subaccount.currency,
        user.base_currency,
        _fx_matrix(session, user),
        user.usd_per_eur,
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Refresh market data or set a manual USD-per-EUR reference rate before "
                "recording cash in another currency."
            ),
        )

    occurred_at = datetime.combine(
        payload.received_date, datetime.min.time(), tzinfo=UTC
    ) + timedelta(hours=12)
    flow = CashFlow(
        user_id=user.id,
        account_id=account.id,
        subaccount_id=subaccount.id,
        label=f"Extra cash · {payload.source}",
        kind=FlowKind.WINDFALL,
        status=FlowStatus.CONFIRMED,
        amount=payload.amount,
        currency=subaccount.currency,
        expected_date=payload.received_date,
        occurred_at=occurred_at,
        source_system="USER_ENTRY",
        source_event_id=event_id,
    )
    subaccount.cash_balance += payload.amount
    session.add(flow)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This receipt was already recorded; refresh the cash-flow list.",
        ) from error
    session.refresh(flow)
    return _cash_receipt_response(
        flow, user.usd_per_eur, user.base_currency, _fx_matrix(session, user)
    )


def archive_cash_flow_schedule(
    session: Session, user_id: uuid.UUID, schedule_id: uuid.UUID
) -> CashFlowScheduleResponse:
    user = _get_user(session, user_id)
    schedule = session.scalar(
        select(CashFlowSchedule).where(
            CashFlowSchedule.id == schedule_id,
            CashFlowSchedule.user_id == user.id,
            CashFlowSchedule.is_active.is_(True),
        )
    )
    if schedule is None:
        raise HTTPException(status_code=404, detail="Active cash-flow schedule not found")
    schedule.is_active = False
    session.commit()
    session.refresh(schedule)
    return CashFlowScheduleResponse.model_validate(schedule)


def _project_cash_flows(
    session: Session,
    user_id: uuid.UUID,
    base_currency: Currency,
    usd_per_eur: Decimal | None,
    fx_rates: dict[tuple[Currency, Currency], Decimal],
    months: int,
) -> list[FlowResponse]:
    today = date.today()
    through_date = add_months(today, months)
    entries: list[FlowResponse] = []

    flow_rows = session.scalars(
        select(CashFlow).where(
            CashFlow.user_id == user_id,
            or_(
                (
                    (CashFlow.status == FlowStatus.FORECAST)
                    & (CashFlow.expected_date >= today)
                    & (CashFlow.expected_date <= through_date)
                ),
                CashFlow.status == FlowStatus.CONFIRMED,
            ),
        )
    )
    for flow in flow_rows:
        entries.append(
            FlowResponse(
                id=flow.id,
                label=flow.label,
                kind=flow.kind,
                direction=_flow_direction(flow.kind),
                status=flow.status,
                amount=flow.amount,
                currency=flow.currency,
                expected_date=flow.expected_date,
                occurred_at=flow.occurred_at,
                reporting_amount=round_money(
                    _to_base(flow.amount, flow.currency, base_currency, usd_per_eur, fx_rates)
                ),
                reporting_currency=base_currency,
                schedule_id=flow.schedule_id,
                automatically_posted=flow.source_system == "SCHEDULED_CASH_FLOW",
            )
        )

    schedules = session.scalars(
        select(CashFlowSchedule).where(
            CashFlowSchedule.user_id == user_id,
            CashFlowSchedule.is_active.is_(True),
        )
    )
    for schedule in schedules:
        forecast_start = today + timedelta(days=1) if schedule.auto_post else today
        for occurrence in occurrence_dates(
            schedule.recurrence,
            schedule.start_date,
            schedule.end_date,
            forecast_start,
            through_date,
        ):
            entries.append(
                FlowResponse(
                    id=uuid.uuid5(schedule.id, f"occurrence:{occurrence.isoformat()}"),
                    label=schedule.label,
                    kind=schedule.kind,
                    direction=_flow_direction(schedule.kind),
                    status=FlowStatus.FORECAST,
                    amount=schedule.amount,
                    currency=schedule.currency,
                    expected_date=occurrence,
                    occurred_at=None,
                    reporting_amount=round_money(
                        _to_base(
                            schedule.amount,
                            schedule.currency,
                            base_currency,
                            usd_per_eur,
                            fx_rates,
                        )
                    ),
                    reporting_currency=base_currency,
                    schedule_id=schedule.id,
                    recurrence=schedule.recurrence,
                )
            )

    def event_date(flow: FlowResponse) -> date:
        if flow.expected_date is not None:
            return flow.expected_date
        if flow.occurred_at is not None:
            return flow.occurred_at.date()
        return date.max

    entries.sort(key=lambda flow: (event_date(flow), flow.label, str(flow.id)))
    return entries


def update_policy(session: Session, user_id: uuid.UUID, payload: PolicyUpdate) -> PolicyResponse:
    user = _get_user(session, user_id)
    policy = _get_policy(session, user.id)
    active_goals = list(
        session.scalars(select(Goal).where(Goal.user_id == user.id, Goal.is_active.is_(True)))
    )
    if payload.funding_rule == FundingRule.FIXED_PERCENTAGES:
        percentages = [goal.fixed_percent or ZERO for goal in active_goals]
        if not active_goals or sum(percentages, ZERO) != ONE:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Active goals need fixed percentages that sum to 100% "
                    "before selecting this rule"
                ),
            )
    policy.funding_rule = payload.funding_rule
    policy.emergency_reserve = payload.emergency_reserve
    policy.target_weights = {
        asset_class.value: str(weight) for asset_class, weight in payload.target_weights.items()
    }
    policy.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(policy)
    return PolicyResponse(
        funding_rule=policy.funding_rule,
        emergency_reserve=policy.emergency_reserve,
        target_weights=_target_weights(policy),
    )


def list_goals(session: Session, user_id: uuid.UUID) -> list[GoalResponse]:
    user = _get_user(session, user_id)
    goals = list(
        session.scalars(
            select(Goal)
            .where(Goal.user_id == user.id, Goal.is_active.is_(True))
            .order_by(Goal.name, Goal.id)
        )
    )
    return [_goal_response(session, goal) for goal in goals]


def get_financial_plan(session: Session, user_id: uuid.UUID) -> FinancialPlanPayload:
    user = _get_user(session, user_id)
    stored = session.get(FinancialPlan, user.id)
    if stored is None:
        return FinancialPlanPayload(anchor_date=date.today(), expenses_currency=user.base_currency)
    return FinancialPlanPayload.model_validate(stored.configuration)


def _validate_contribution_sources(
    plan: FinancialPlanPayload, rule_sets: list[list[ContributionRule] | None]
) -> None:
    sources = {source.id: source for source in plan.income_sources}
    changes: dict[str, dict[date, Decimal]] = {}
    for rules in rule_sets:
        for rule in rules or []:
            if rule.source_id is None and rule.source_kind is None:
                continue
            applicable = matching_sources(rule, plan)
            if not applicable:
                raise HTTPException(
                    status_code=422,
                    detail="A contribution references income missing from this plan.",
                )
            if rule.calculation != "percentage":
                continue
            for source in applicable:
                start = max(rule.start_date, source.start_date)
                end = min(rule.end_date or date.max, source.end_date or date.max)
                if start > end:
                    continue
                deltas = changes.setdefault(source.id, {})
                deltas[start] = deltas.get(start, ZERO) + rule.value
                if end != date.max:
                    after = end + timedelta(days=1)
                    deltas[after] = deltas.get(after, ZERO) - rule.value
    for source_id, deltas in changes.items():
        total = ZERO
        for at in sorted(deltas):
            total += deltas[at]
            if total > ONE:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Contributions from {sources[source_id].name} exceed 100% on {at}. "
                        "Reduce overlapping shares across goals."
                    ),
                )


def _goal_rules(goal: Goal) -> list[ContributionRule] | None:
    if goal.contribution_rules is None:
        return None
    return [ContributionRule.model_validate(rule) for rule in goal.contribution_rules]


def update_financial_plan(
    session: Session, user_id: uuid.UUID, payload: FinancialPlanPayload
) -> FinancialPlanPayload:
    session.scalar(select(User).where(User.id == user_id).with_for_update())
    _get_user(session, user_id)
    stored = session.get(FinancialPlan, user_id)
    if payload.anchor_date > date.today():
        raise HTTPException(status_code=422, detail="The planning reference date cannot be future.")
    if payload.anchor_date < add_months(date.today(), -1200):
        raise HTTPException(
            status_code=422, detail="The planning reference date cannot be over 100 years ago."
        )
    if stored is not None and (
        payload.anchor_date != FinancialPlanPayload.model_validate(stored.configuration).anchor_date
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "The reference date is fixed so existing today's-money amounts "
                "keep their meaning."
            ),
        )
    goals = list(session.scalars(select(Goal).where(
        Goal.user_id == user_id, Goal.is_active.is_(True)
    )))
    _validate_contribution_sources(payload, [_goal_rules(goal) for goal in goals])
    if stored is None:
        stored = FinancialPlan(user_id=user_id, configuration=payload.model_dump(mode="json"))
        session.add(stored)
    else:
        stored.configuration = payload.model_dump(mode="json")
    session.commit()
    return payload


def _ensure_financial_plan(session: Session, user_id: uuid.UUID) -> FinancialPlanPayload:
    plan = get_financial_plan(session, user_id)
    if session.get(FinancialPlan, user_id) is None:
        session.add(FinancialPlan(user_id=user_id, configuration=plan.model_dump(mode="json")))
        session.flush()
    return plan


def _planning_convert(session: Session, user: User) -> Convert:
    rates = _fx_matrix(session, user)

    def convert(value: Decimal, source: Currency, destination: Currency) -> Decimal:
        return _to_base(value, source, destination, user.usd_per_eur, rates)

    return convert


def goal_contribution_schedule(
    session: Session, user_id: uuid.UUID, goal_id: uuid.UUID, months: int = 120
) -> ContributionSchedule:
    user = _get_user(session, user_id)
    goals = list(session.scalars(select(Goal).where(
        Goal.user_id == user.id, Goal.is_active.is_(True)
    )))
    goal = next((item for item in goals if item.id == goal_id), None)
    if goal is None:
        raise HTTPException(status_code=404, detail="Active goal was not found")
    plan = get_financial_plan(session, user.id)
    convert = _planning_convert(session, user)
    today = date.today()
    own_months = contribution_months(
        plan, _goal_rules(goal), goal.monthly_contribution,
        goal.target_currency, today, months, convert,
    )
    totals = [ZERO] * months
    for item in goals:
        schedule = own_months if item.id == goal.id else contribution_months(
            plan, _goal_rules(item), item.monthly_contribution,
            item.target_currency, today, months, convert,
        )
        amounts = [
            convert(point.nominal_contribution, item.target_currency, goal.target_currency)
            for point in schedule
        ]
        for index, value in enumerate(amounts):
            totals[index] += value
    warnings = []
    if plan.monthly_expenses is None:
        warnings.append(
            "Living expenses are not configured; income is not the same as disposable income."
        )
    overcommitted = [
        point.date.isoformat() for index, point in enumerate(own_months)
        if totals[index] > max(ZERO, point.nominal_income - point.nominal_expenses)
    ]
    if overcommitted:
        warnings.append(
            f"Combined goal contributions exceed projected disposable income in "
            f"{len(overcommitted)} month(s), first on {overcommitted[0]}. "
            "These projections assume additional funding; no goal is silently deprioritized."
        )
    return ContributionSchedule(
        anchor_date=plan.anchor_date, currency=goal.target_currency,
        months=own_months, warnings=warnings,
    )


def _allocation_pairs(items: list[Any]) -> list[tuple[uuid.UUID, Decimal]]:
    return [(item.id, item.allocated_percentage) for item in items]


def _goal_response(session: Session, goal: Goal) -> GoalResponse:
    values = {column.key: getattr(goal, column.key) for column in Goal.__table__.columns}
    holding_allocations = session.execute(
        select(GoalHoldingAllocation.holding_id, GoalHoldingAllocation.allocated_percentage)
        .where(GoalHoldingAllocation.goal_id == goal.id)
        .order_by(GoalHoldingAllocation.holding_id)
    ).all()
    deposit_allocations = session.execute(
        select(GoalDepositAllocation.fixed_deposit_id, GoalDepositAllocation.allocated_percentage)
        .where(GoalDepositAllocation.goal_id == goal.id)
        .order_by(GoalDepositAllocation.fixed_deposit_id)
    ).all()
    values.update(
        linked_account_ids=list(
            session.scalars(
                select(GoalAccountLink.account_id).where(GoalAccountLink.goal_id == goal.id)
            )
        ),
        holding_ids=[row.holding_id for row in holding_allocations],
        fixed_deposit_ids=[row.fixed_deposit_id for row in deposit_allocations],
        holding_allocations=[
            {"id": row.holding_id, "allocated_percentage": row.allocated_percentage}
            for row in holding_allocations
        ],
        fixed_deposit_allocations=[
            {"id": row.fixed_deposit_id, "allocated_percentage": row.allocated_percentage}
            for row in deposit_allocations
        ],
    )
    return GoalResponse.model_validate(values)


def _ensure_within_full_allocation(
    existing_totals: list[tuple[uuid.UUID, Decimal]],
    requested: dict[uuid.UUID, Decimal],
    message: str,
) -> None:
    for source_id, already_allocated in existing_totals:
        if already_allocated + requested.get(source_id, ZERO) > Decimal("100"):
            raise HTTPException(status_code=409, detail=message)


def _replace_goal_sources(
    session: Session,
    user_id: uuid.UUID,
    goal_id: uuid.UUID,
    linked_account_ids: list[uuid.UUID],
    holding_allocations: list[tuple[uuid.UUID, Decimal]],
    deposit_allocations: list[tuple[uuid.UUID, Decimal]],
) -> None:
    holding_ids = [holding_id for holding_id, _ in holding_allocations]
    fixed_deposit_ids = [deposit_id for deposit_id, _ in deposit_allocations]
    account_ids = set(linked_account_ids)
    accounts = list(
        session.scalars(
            select(BrokerAccount).where(
                BrokerAccount.user_id == user_id,
                BrokerAccount.id.in_(account_ids),
            )
        )
    ) if account_ids else []
    if len(accounts) != len(account_ids):
        raise HTTPException(status_code=404, detail="A selected account was not found")

    holdings_by_id: dict[uuid.UUID, Holding] = {}
    if holding_ids:
        holdings_by_id = {
            holding.id: holding
            for holding in session.scalars(
                select(Holding).where(
                    Holding.user_id == user_id,
                    Holding.id.in_(holding_ids),
                )
            )
        }
        if len(holdings_by_id) != len(holding_ids):
            raise HTTPException(status_code=404, detail="A selected stock or ETF was not found")
        if any(holding.account_id not in account_ids for holding in holdings_by_id.values()):
            raise HTTPException(
                status_code=422,
                detail="Link each holding's account to this goal before selecting the holding.",
            )
        existing_holding_totals = [
            (holding_id, Decimal(total))
            for holding_id, total in session.execute(
                select(
                    GoalHoldingAllocation.holding_id,
                    func.sum(GoalHoldingAllocation.allocated_percentage),
                )
                .where(
                    GoalHoldingAllocation.holding_id.in_(holding_ids),
                    GoalHoldingAllocation.goal_id != goal_id,
                )
                .group_by(GoalHoldingAllocation.holding_id)
            ).all()
        ]
        _ensure_within_full_allocation(
            existing_holding_totals,
            dict(holding_allocations),
            "A stock or ETF's allocations across goals cannot exceed 100%.",
        )

    deposits_by_id: dict[uuid.UUID, FixedDeposit] = {}
    if fixed_deposit_ids:
        deposits_by_id = {
            deposit.id: deposit
            for deposit in session.scalars(
                select(FixedDeposit).where(
                    FixedDeposit.user_id == user_id,
                    FixedDeposit.id.in_(fixed_deposit_ids),
                )
            )
        }
        if len(deposits_by_id) != len(fixed_deposit_ids):
            raise HTTPException(status_code=404, detail="A selected deposit was not found")
        if any(deposit.account_id not in account_ids for deposit in deposits_by_id.values()):
            raise HTTPException(
                status_code=422,
                detail="Link each deposit's account to this goal before selecting the deposit.",
            )
        existing_deposit_totals = [
            (deposit_id, Decimal(total))
            for deposit_id, total in session.execute(
                select(
                    GoalDepositAllocation.fixed_deposit_id,
                    func.sum(GoalDepositAllocation.allocated_percentage),
                )
                .where(
                    GoalDepositAllocation.fixed_deposit_id.in_(fixed_deposit_ids),
                    GoalDepositAllocation.goal_id != goal_id,
                )
                .group_by(GoalDepositAllocation.fixed_deposit_id)
            ).all()
        ]
        _ensure_within_full_allocation(
            existing_deposit_totals,
            dict(deposit_allocations),
            "A fixed deposit's allocations across goals cannot exceed 100%.",
        )

    session.execute(delete(GoalAccountLink).where(GoalAccountLink.goal_id == goal_id))
    session.execute(
        delete(GoalHoldingAllocation).where(GoalHoldingAllocation.goal_id == goal_id)
    )
    session.execute(
        delete(GoalDepositAllocation).where(GoalDepositAllocation.goal_id == goal_id)
    )
    session.add_all(
        [
            GoalAccountLink(user_id=user_id, goal_id=goal_id, account_id=account_id)
            for account_id in linked_account_ids
        ]
    )
    session.add_all(
        [
            GoalHoldingAllocation(
                user_id=user_id,
                goal_id=goal_id,
                holding_id=holding_id,
                allocated_percentage=percentage,
            )
            for holding_id, percentage in holding_allocations
        ]
    )
    session.add_all(
        [
            GoalDepositAllocation(
                user_id=user_id,
                goal_id=goal_id,
                fixed_deposit_id=deposit_id,
                allocated_percentage=percentage,
            )
            for deposit_id, percentage in deposit_allocations
        ]
    )


def create_goal(session: Session, user_id: uuid.UUID, payload: GoalCreate) -> GoalResponse:
    session.scalar(select(User).where(User.id == user_id).with_for_update())
    user = _get_user(session, user_id)
    plan = _ensure_financial_plan(session, user.id)
    existing = list(session.scalars(select(Goal).where(
        Goal.user_id == user.id, Goal.is_active.is_(True)
    )))
    _validate_contribution_sources(
        plan, [_goal_rules(goal) for goal in existing] + [payload.contribution_rules]
    )
    if not _can_convert(
        payload.target_currency, user.base_currency, _fx_matrix(session, user), user.usd_per_eur
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Refresh market data or set a manual USD-per-EUR reference rate before "
                "adding a goal in another currency."
            ),
        )
    policy = _get_policy(session, user.id)
    if policy.funding_rule == FundingRule.FIXED_PERCENTAGES:
        current_total = sum(
            (
                goal.fixed_percent or ZERO
                for goal in session.scalars(
                    select(Goal).where(Goal.user_id == user.id, Goal.is_active.is_(True))
                )
            ),
            ZERO,
        )
        proposed_total = current_total + (payload.fixed_percent or ZERO)
        if proposed_total != ONE:
            raise HTTPException(
                status_code=422,
                detail="New goal percentages must keep the active fixed allocation at 100%",
            )
    goal_values = payload.model_dump(
        exclude={"linked_account_ids", "holding_allocations", "fixed_deposit_allocations"}
    )
    goal_values["contribution_rules"] = (
        [rule.model_dump(mode="json") for rule in payload.contribution_rules]
        if payload.contribution_rules is not None else None
    )
    goal = Goal(user_id=user.id, **goal_values)
    session.add(goal)
    session.flush()
    _replace_goal_sources(
        session,
        user.id,
        goal.id,
        payload.linked_account_ids,
        _allocation_pairs(payload.holding_allocations),
        _allocation_pairs(payload.fixed_deposit_allocations),
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A selected stock or deposit was assigned to another goal at the same time.",
        ) from error
    session.refresh(goal)
    return _goal_response(session, goal)


def update_goal(
    session: Session, user_id: uuid.UUID, goal_id: uuid.UUID, payload: GoalUpdate
) -> GoalResponse:
    session.scalar(select(User).where(User.id == user_id).with_for_update())
    user = _get_user(session, user_id)
    goal = session.scalar(
        select(Goal)
        .where(
            Goal.id == goal_id,
            Goal.user_id == user.id,
            Goal.is_active.is_(True),
        )
        .with_for_update()
    )
    if goal is None:
        raise HTTPException(status_code=404, detail="Active goal was not found")
    plan = _ensure_financial_plan(session, user.id)
    existing = list(session.scalars(select(Goal).where(
        Goal.user_id == user.id, Goal.is_active.is_(True), Goal.id != goal.id
    )))
    requested_rules = (
        payload.contribution_rules if "contribution_rules" in payload.model_fields_set
        else _goal_rules(goal)
    )
    _validate_contribution_sources(
        plan, [_goal_rules(item) for item in existing] + [requested_rules]
    )
    if not _can_convert(
        payload.target_currency, user.base_currency, _fx_matrix(session, user), user.usd_per_eur
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Refresh market data or set a manual USD-per-EUR reference rate before "
                "updating a goal in another currency."
            ),
        )
    policy = _get_policy(session, user.id)
    if policy.funding_rule == FundingRule.FIXED_PERCENTAGES:
        other_percentages = sum(
            (
                active_goal.fixed_percent or ZERO
                for active_goal in session.scalars(
                    select(Goal).where(
                        Goal.user_id == user.id,
                        Goal.is_active.is_(True),
                        Goal.id != goal.id,
                    )
                )
            ),
            ZERO,
        )
        if other_percentages + (payload.fixed_percent or ZERO) != ONE:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Updated fixed goal percentages must keep active goal shares at exactly 100%."
                ),
            )
    goal_values = payload.model_dump(
        exclude={"linked_account_ids", "holding_allocations", "fixed_deposit_allocations"}
    )
    for field in ("contribution_rules", "annual_inflation_rate", "target_money_basis"):
        if field not in payload.model_fields_set:
            goal_values.pop(field, None)
    if "contribution_rules" in goal_values:
        goal_values["contribution_rules"] = (
            [rule.model_dump(mode="json") for rule in requested_rules]
            if requested_rules is not None else None
        )
    for field, value in goal_values.items():
        setattr(goal, field, value)
    _replace_goal_sources(
        session,
        user.id,
        goal.id,
        payload.linked_account_ids,
        _allocation_pairs(payload.holding_allocations),
        _allocation_pairs(payload.fixed_deposit_allocations),
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A selected stock or deposit was assigned to another goal at the same time.",
        ) from error
    session.refresh(goal)
    return _goal_response(session, goal)


def archive_goal(session: Session, user_id: uuid.UUID, goal_id: uuid.UUID) -> None:
    user = _get_user(session, user_id)
    goal = session.scalar(
        select(Goal)
        .where(
            Goal.id == goal_id,
            Goal.user_id == user.id,
            Goal.is_active.is_(True),
        )
        .with_for_update()
    )
    if goal is None:
        raise HTTPException(status_code=404, detail="Active goal was not found")

    policy = _get_policy(session, user.id)
    if policy.funding_rule == FundingRule.FIXED_PERCENTAGES:
        remaining_goals = list(
            session.scalars(
                select(Goal).where(
                    Goal.user_id == user.id,
                    Goal.is_active.is_(True),
                    Goal.id != goal.id,
                )
            )
        )
        remaining_total = sum(
            (active_goal.fixed_percent or ZERO for active_goal in remaining_goals),
            ZERO,
        )
        if remaining_total > ZERO:
            allocated = ZERO
            for active_goal in remaining_goals[:-1]:
                share = ((active_goal.fixed_percent or ZERO) / remaining_total).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP
                )
                active_goal.fixed_percent = share
                allocated += share
            remaining_goals[-1].fixed_percent = ONE - allocated
        else:
            policy.funding_rule = None
            for active_goal in remaining_goals:
                active_goal.fixed_percent = None

    goal.is_active = False
    goal.fixed_percent = None
    session.execute(delete(GoalAccountLink).where(GoalAccountLink.goal_id == goal.id))
    session.execute(
        delete(GoalHoldingAllocation).where(GoalHoldingAllocation.goal_id == goal.id)
    )
    session.execute(
        delete(GoalDepositAllocation).where(GoalDepositAllocation.goal_id == goal.id)
    )
    session.commit()


def update_fixed_shares(
    session: Session, user_id: uuid.UUID, payload: FixedSharesUpdate
) -> dict[str, Decimal]:
    user = _get_user(session, user_id)
    goals = list(
        session.scalars(select(Goal).where(Goal.user_id == user.id, Goal.is_active.is_(True)))
    )
    requested = {item.goal_id: item.percentage for item in payload.shares}
    expected_ids = {goal.id for goal in goals}
    if len(requested) != len(payload.shares) or set(requested) != expected_ids:
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one fixed percentage for every active goal",
        )
    if sum(requested.values(), ZERO) != ONE:
        raise HTTPException(status_code=422, detail="Fixed goal percentages must sum to 100%")
    for goal in goals:
        goal.fixed_percent = requested[goal.id]
    session.commit()
    return {str(goal_id): percentage for goal_id, percentage in requested.items()}


def goal_insights(
    session: Session, user_id: uuid.UUID, goal_id: uuid.UUID
) -> GoalInsightsResponse:
    user = _get_user(session, user_id)
    goal = session.scalar(
        select(Goal).where(
            Goal.id == goal_id,
            Goal.user_id == user.id,
            Goal.is_active.is_(True),
        )
    )
    if goal is None:
        raise HTTPException(status_code=404, detail="Active goal was not found")
    if goal.target_amount is None or goal.target_date is None:
        return GoalInsightsResponse(
            available=False,
            unavailable_reason="Set a target amount and a target date to see goal insights.",
        )
    today = date.today()
    if goal.target_date <= today:
        return GoalInsightsResponse(
            available=False,
            unavailable_reason="The target date has passed. Move it forward to see projections.",
        )
    horizon = max(1, round(max(0.1, (goal.target_date - today).days / 365.25) * 12))
    if horizon > 1200:
        return GoalInsightsResponse(
            available=False,
            unavailable_reason="Goal projections support deadlines up to 100 years from today.",
        )

    fx_rates = _fx_matrix(session, user)

    def spot_rate(from_code: str, to_code: str) -> float:
        return float(
            _to_base(
                Decimal(1),
                Currency(from_code),
                Currency(to_code),
                user.usd_per_eur,
                fx_rates,
            )
        )

    default_rate = float(DEFAULT_SALE_TAX_RATE)
    allocations, notes = load_allocated_holdings(session, goal, spot_rate, today, default_rate)
    spec = build_goal_spec(goal, allocations, spot_rate, default_rate)
    plan = get_financial_plan(session, user.id)
    convert = _planning_convert(session, user)
    months = horizon + MAX_EXTENSION_MONTHS
    schedule = contribution_months(
        plan, _goal_rules(goal), goal.monthly_contribution,
        goal.target_currency, today, months, convert,
    )
    target_plan = plan
    if goal.annual_inflation_rate is not None:
        target_plan = plan.model_copy(update={
            "annual_inflation_rate": goal.annual_inflation_rate, "inflation_changes": [],
        })
    today_factor = inflation_factor(target_plan, today)
    target_factors = (1.0,) + tuple(
        float(inflation_factor(target_plan, point.date) / today_factor) for point in schedule
    )
    spec = replace(
        spec,
        target_amount=(
            spec.target_amount * float(today_factor)
            if goal.target_money_basis == "real" else spec.target_amount
        ),
        monthly_contribution=float(schedule[0].nominal_contribution),
        monthly_contributions=tuple(float(point.nominal_contribution) for point in schedule),
        inflation_factors=target_factors,
        tax_profile=replace(
            spec.tax_profile,
            annual_inflation_rate=float(target_plan.annual_inflation_rate),
            is_target_in_todays_dollars=goal.target_money_basis == "real",
            index_contributions_to_inflation=False,
        ),
    )
    notes.extend([
        "Income and contribution timelines are forecast assumptions, not wallet credits or trades.",
        "Annual salary growth is the total nominal raise before inflation, "
        "not growth above inflation.",
        f"Today's-money inputs use the fixed reference date {plan.anchor_date.isoformat()}.",
        "Future currency conversions hold current FX rates constant; "
        "future payroll taxes are not modeled.",
    ])
    notes.extend(goal_contribution_schedule(
        session, user.id, goal.id, min(horizon, 1200)
    ).warnings)
    now = datetime(today.year, today.month, today.day, tzinfo=UTC)
    insights = build_goal_insights(spec, allocations, spot_rate, now, notes=notes)
    return GoalInsightsResponse.model_validate({"available": True, **to_plain(insights)})


def _latest_instrument_quote(
    session: Session, instrument_id: uuid.UUID
) -> MarketPriceCache | None:
    return session.scalar(
        select(MarketPriceCache)
        .where(MarketPriceCache.instrument_id == instrument_id)
        .order_by(MarketPriceCache.received_at.desc(), MarketPriceCache.id.desc())
        .limit(1)
    )


def _plan_economics(
    shares: Decimal, market_price: Decimal, discount_rate: Decimal, receipt_tax_rate: Decimal
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    purchase_price = market_price * (ONE - discount_rate)
    purchase_cost = shares * purchase_price
    discount_benefit = shares * market_price * discount_rate
    receipt_tax = discount_benefit * receipt_tax_rate
    return purchase_price, purchase_cost, discount_benefit, receipt_tax


async def create_purchase_plan(
    session: Session, user_id: uuid.UUID, payload: StockPurchasePlanCreate
) -> uuid.UUID:
    user = _get_user(session, user_id)
    account = session.scalar(
        select(BrokerAccount).where(
            BrokerAccount.id == payload.account_id, BrokerAccount.user_id == user.id
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Selected share account was not found")
    if account.account_type == AccountType.SAVINGS:
        raise HTTPException(
            status_code=422,
            detail="Purchased shares cannot be held in a savings account",
        )
    wallet_row = session.execute(
        select(AccountSubaccount, BrokerAccount)
        .join(BrokerAccount, BrokerAccount.id == AccountSubaccount.account_id)
        .where(
            AccountSubaccount.id == payload.subaccount_id,
            BrokerAccount.user_id == user.id,
        )
    ).first()
    if wallet_row is None:
        raise HTTPException(status_code=404, detail="Selected paying wallet was not found")
    wallet, wallet_account = wallet_row
    if wallet_account.account_type == AccountType.EMPLOYER_PLAN:
        raise HTTPException(
            status_code=422,
            detail="Employer-plan accounts cannot hold the cash that pays for the shares",
        )

    client = _market_client()
    try:
        quote = await client.quote(payload.symbol, payload.mic_code, payload.exchange)
    except MarketDataProviderError as error:
        _raise_provider_error(error)
    fx_rates = _fx_matrix(session, user)
    await _ensure_fx_conversion(session, client, quote.currency, user.base_currency, fx_rates)
    await _ensure_fx_conversion(session, client, quote.currency, wallet.currency, fx_rates)

    symbol = quote.symbol.upper()
    mic = (quote.mic_code or payload.mic_code or "UNKNOWN").upper()
    exchange = quote.exchange or payload.exchange or ""
    instrument = session.scalar(
        select(Instrument).where(Instrument.symbol == symbol, Instrument.mic == mic)
    )
    if instrument is None:
        instrument = Instrument(
            symbol=symbol,
            name=quote.name,
            asset_class=AssetClass.EQUITIES,
            currency=quote.currency,
            mic=mic,
            exchange=exchange,
            instrument_type="STOCK",
            estimated_annual_yield=ZERO,
            is_demo=False,
        )
        session.add(instrument)
        session.flush()
    elif instrument.currency != quote.currency or instrument.instrument_type != "STOCK":
        raise HTTPException(
            status_code=409,
            detail=(
                f"{symbol} is already tracked using a different listing. "
                "Select its existing stock exchange listing."
            ),
        )
    else:
        instrument.name = quote.name
        instrument.is_demo = False

    plan = StockPurchasePlan(
        user_id=user.id,
        account_id=account.id,
        funding_subaccount_id=wallet.id,
        instrument_id=instrument.id,
        name=payload.name or f"{symbol} purchase",
        shares=payload.shares,
        purchase_date=payload.purchase_date,
        discount_rate=payload.discount_rate,
        receipt_tax_rate=payload.receipt_tax_rate,
        sale_profit_tax_rate=payload.sale_profit_tax_rate,
        reference_price=payload.reference_price,
        status="scheduled",
    )
    session.add(plan)
    session.add(
        MarketPriceCache(
            instrument_id=instrument.id,
            price=quote.price,
            currency=quote.currency,
            source=PROVIDER_NAME,
            feed_type="QUOTE",
            observed_at=quote.observed_at,
            is_market_open=quote.is_market_open,
        )
    )
    session.flush()
    plan_id = plan.id
    session.commit()
    return plan_id


def delete_purchase_plan(session: Session, user_id: uuid.UUID, plan_id: uuid.UUID) -> None:
    plan = session.scalar(
        select(StockPurchasePlan).where(
            StockPurchasePlan.id == plan_id, StockPurchasePlan.user_id == user_id
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Share purchase plan was not found")
    session.delete(plan)
    session.commit()


def _execute_due_purchase_plans(
    session: Session, user_id: uuid.UUID, today: date
) -> list[str]:
    plans = list(
        session.scalars(
            select(StockPurchasePlan)
            .where(
                StockPurchasePlan.user_id == user_id,
                StockPurchasePlan.status == "scheduled",
                StockPurchasePlan.purchase_date <= today,
            )
            .order_by(StockPurchasePlan.purchase_date, StockPurchasePlan.id)
            .with_for_update()
        )
    )
    if not plans:
        return []
    user = _get_user(session, user_id)
    fx_rates = _fx_matrix(session, user)
    warnings: list[str] = []
    changed = False
    for plan in plans:
        instrument = session.get(Instrument, plan.instrument_id)
        wallet = session.scalar(
            select(AccountSubaccount)
            .where(AccountSubaccount.id == plan.funding_subaccount_id)
            .with_for_update()
        )
        if instrument is None or wallet is None:
            continue
        quote = _latest_instrument_quote(session, instrument.id)
        market_price = plan.reference_price or (quote.price if quote is not None else None)
        if market_price is None:
            warnings.append(
                f"“{plan.name}” is due but {instrument.symbol} has no price. Add a reference "
                "price or refresh quotes."
            )
            continue
        _, purchase_cost, _, receipt_tax = _plan_economics(
            plan.shares, market_price, plan.discount_rate, plan.receipt_tax_rate
        )
        try:
            wallet_cost = round_money(
                _to_base(
                    purchase_cost + receipt_tax,
                    instrument.currency,
                    wallet.currency,
                    user.usd_per_eur,
                    fx_rates,
                )
            )
        except HTTPException:
            warnings.append(
                f"“{plan.name}” is due but no FX rate converts {instrument.currency.value} to "
                f"{wallet.currency.value}. Refresh market data."
            )
            continue
        if wallet.cash_balance < wallet_cost:
            warnings.append(
                f"“{plan.name}” is due but the paying {wallet.currency.value} wallet has "
                f"{wallet.cash_balance:.2f}; {wallet_cost:.2f} is needed for the discounted "
                "purchase and tax at receipt."
            )
            continue
        holding = session.scalar(
            select(Holding).where(
                Holding.user_id == user_id,
                Holding.account_id == plan.account_id,
                Holding.instrument_id == instrument.id,
            )
        )
        if holding is None:
            holding = Holding(
                user_id=user_id,
                account_id=plan.account_id,
                instrument_id=instrument.id,
                quantity=plan.shares,
                average_cost=market_price,
                purchase_date=plan.purchase_date,
                risk_tier="Y",
                expected_annual_return=Decimal("0.05"),
                funding_cost=ZERO,
                sale_tax_rate=plan.sale_profit_tax_rate,
            )
            session.add(holding)
        else:
            total_quantity = holding.quantity + plan.shares
            existing_rate = (
                holding.sale_tax_rate
                if holding.sale_tax_rate is not None
                else DEFAULT_SALE_TAX_RATE
            )
            holding.sale_tax_rate = (
                holding.quantity * existing_rate + plan.shares * plan.sale_profit_tax_rate
            ) / total_quantity
            holding.average_cost = (
                holding.quantity * holding.average_cost + plan.shares * market_price
            ) / total_quantity
            weighted_ordinal = (
                Decimal(holding.purchase_date.toordinal()) * holding.quantity
                + Decimal(plan.purchase_date.toordinal()) * plan.shares
            ) / total_quantity
            holding.purchase_date = date.fromordinal(
                int(weighted_ordinal.to_integral_value(rounding=ROUND_HALF_UP))
            )
            holding.quantity = total_quantity
        session.flush()
        wallet.cash_balance -= wallet_cost
        plan.status = "executed"
        plan.holding_id = holding.id
        plan.executed_price = market_price
        plan.executed_cost = wallet_cost
        plan.executed_at = datetime.now(UTC)
        changed = True
    if changed:
        session.commit()
    return warnings


def _purchase_plan_summaries(
    session: Session,
    user: User,
    base_currency: Currency,
    fx_rates: dict[tuple[Currency, Currency], Decimal],
    latest_quotes: dict[uuid.UUID, MarketPriceCache],
) -> list[StockPurchasePlanSummary]:
    rows = session.execute(
        select(StockPurchasePlan, Instrument, BrokerAccount, AccountSubaccount)
        .join(Instrument, Instrument.id == StockPurchasePlan.instrument_id)
        .join(BrokerAccount, BrokerAccount.id == StockPurchasePlan.account_id)
        .join(AccountSubaccount, AccountSubaccount.id == StockPurchasePlan.funding_subaccount_id)
        .where(StockPurchasePlan.user_id == user.id)
        .order_by(StockPurchasePlan.purchase_date, StockPurchasePlan.name)
    ).all()
    summaries: list[StockPurchasePlanSummary] = []
    for plan, instrument, account, wallet in rows:
        quote = latest_quotes.get(instrument.id)
        market_price = plan.executed_price or plan.reference_price or (
            quote.price if quote is not None else None
        )
        if market_price is None:
            continue
        purchase_price, purchase_cost, benefit, receipt_tax = _plan_economics(
            plan.shares, market_price, plan.discount_rate, plan.receipt_tax_rate
        )

        def to_report(value: Decimal, currency: Currency = instrument.currency) -> Decimal:
            return round_money(
                _to_base(value, currency, base_currency, user.usd_per_eur, fx_rates)
            )

        summaries.append(
            StockPurchasePlanSummary(
                id=plan.id,
                name=plan.name,
                symbol=instrument.symbol,
                instrument_name=instrument.name,
                account_id=account.id,
                account_name=account.display_name,
                funding_currency=wallet.currency,
                shares=plan.shares,
                purchase_date=plan.purchase_date,
                discount_rate=plan.discount_rate,
                receipt_tax_rate=plan.receipt_tax_rate,
                sale_profit_tax_rate=plan.sale_profit_tax_rate,
                status="executed" if plan.status == "executed" else "scheduled",
                price_currency=instrument.currency,
                market_price=market_price,
                purchase_price=purchase_price,
                price_is_estimate=plan.status != "executed" and plan.reference_price is None,
                reporting_currency=base_currency,
                market_value=to_report(plan.shares * market_price),
                purchase_cost=to_report(purchase_cost),
                gross_discount_benefit=to_report(benefit),
                receipt_tax=to_report(receipt_tax),
                net_benefit=to_report(benefit - receipt_tax),
                holding_id=plan.holding_id,
            )
        )
    return summaries


def dashboard(
    session: Session, user_id: uuid.UUID, requested_currency: Currency | None = None
) -> dict[str, Any]:
    user = _get_user(session, user_id)
    base_currency = requested_currency or user.base_currency
    usd_per_eur = user.usd_per_eur
    fx_rates = _fx_matrix(session, user)
    policy = _get_policy(session, user.id)
    now = datetime.now(UTC)
    today = date.today()
    _post_due_cash_flow_schedules(session, user.id, today)
    _post_due_savings_interest(session, user.id, today)
    purchase_plan_warnings = _execute_due_purchase_plans(session, user.id, today)

    quote_rows = list(
        session.scalars(
            select(MarketPriceCache).order_by(
                MarketPriceCache.received_at.desc(), MarketPriceCache.id.desc()
            )
        )
    )
    latest_quotes: dict[uuid.UUID, MarketPriceCache] = {}
    previous_quotes: dict[uuid.UUID, MarketPriceCache] = {}
    for quote in quote_rows:
        latest = latest_quotes.get(quote.instrument_id)
        if latest is None:
            latest_quotes[quote.instrument_id] = quote
        elif (
            quote.source == latest.source
            and quote.feed_type == latest.feed_type
            and quote.source == "TWELVE_DATA"
        ):
            previous_quotes.setdefault(quote.instrument_id, quote)

    holding_rows = session.execute(
        select(Holding, Instrument, BrokerAccount, AccountSubaccount)
        .join(Instrument, Instrument.id == Holding.instrument_id)
        .join(BrokerAccount, BrokerAccount.id == Holding.account_id)
        .outerjoin(AccountSubaccount, AccountSubaccount.id == Holding.funding_subaccount_id)
        .where(Holding.user_id == user.id)
    ).all()

    assigned_holding_goals = {
        holding_id: (goal_id, goal_name)
        for holding_id, goal_id, goal_name in session.execute(
            select(
                GoalHoldingAllocation.holding_id,
                Goal.id,
                Goal.name,
            )
            .join(Goal, Goal.id == GoalHoldingAllocation.goal_id)
            .where(
                GoalHoldingAllocation.user_id == user.id,
                Goal.is_active.is_(True),
            )
        ).all()
    }
    allocated_holding_percentages: dict[uuid.UUID, Decimal] = {
        holding_id: Decimal(total)
        for holding_id, total in session.execute(
            select(
                GoalHoldingAllocation.holding_id,
                func.sum(GoalHoldingAllocation.allocated_percentage),
            )
            .join(Goal, Goal.id == GoalHoldingAllocation.goal_id)
            .where(
                GoalHoldingAllocation.user_id == user.id,
                Goal.is_active.is_(True),
            )
            .group_by(GoalHoldingAllocation.holding_id)
        ).all()
    }
    holdings: list[HoldingSummary] = []
    holding_values_by_id: dict[uuid.UUID, Decimal] = {}
    values_by_class = {asset_class.value: ZERO for asset_class in AssetClass}
    gross_holdings_by_account: dict[uuid.UUID, Decimal] = {}
    after_tax_holdings_by_account: dict[uuid.UUID, Decimal] = {}
    sale_tax_by_account: dict[uuid.UUID, Decimal] = {}
    annual_dividend_income = ZERO
    sample_data = bool(holding_rows) and all(
        instrument.is_demo for _, instrument, _, _ in holding_rows
    )
    warnings: list[str] = list(purchase_plan_warnings)
    has_fixed_deposits = session.scalar(
        select(FixedDeposit.id)
        .where(FixedDeposit.user_id == user.id)
        .limit(1)
    ) is not None
    has_interest_bearing_accounts = session.scalar(
        select(AccountSubaccount.id)
        .join(BrokerAccount, BrokerAccount.id == AccountSubaccount.account_id)
        .where(
            BrokerAccount.user_id == user.id,
            AccountSubaccount.annual_interest_rate.is_not(None),
        )
        .limit(1)
    ) is not None
    has_vesting_grants = session.scalar(
        select(VestingGrant.id).where(VestingGrant.user_id == user.id).limit(1)
    ) is not None
    if holding_rows or has_fixed_deposits or has_interest_bearing_accounts or has_vesting_grants:
        warnings.extend(_tax_profile_warnings(user))
    if sample_data:
        warnings.extend(
            [
                "Illustrative demo holdings and marks are not live market data.",
                (
                    "Demo cost basis and performance history are synthetic and are not "
                    "tax-lot accounting."
                ),
            ]
        )
    if any(quote.source == "XTB_SCREENSHOT" for quote in latest_quotes.values()):
        warnings.append(
            "Some XTB position prices were reconstructed from the screenshots' account-currency "
            "market values using cached FX. They are historical imported marks, not live quotes; "
            "refresh market data to replace them."
        )
    for holding, instrument, account, funding_subaccount in holding_rows:
        quote = latest_quotes.get(instrument.id)
        if quote is None:
            warnings.append(
                f"{instrument.symbol} has no quote and is excluded from portfolio totals."
            )
            sample_data = False
            continue
        native_value = holding.quantity * quote.price
        gross_current_value = _to_base(
            native_value, quote.currency, base_currency, usd_per_eur, fx_rates
        )
        cost_basis_base = _to_base(
            holding.quantity * holding.average_cost,
            instrument.currency,
            base_currency,
            usd_per_eur,
            fx_rates,
        )
        tax_estimate = estimate_capital_gain_tax(
            gross_proceeds=native_value,
            cost_basis=holding.quantity * holding.average_cost,
            acquired_on=holding.purchase_date,
            sold_on=today,
            country_code=user.tax_residence_country_code,
            tax_year=user.tax_year,
            intermediary_country_code=account.broker_country_code,
            reporting_method=str(account.tax_reporting_method),
            manual_rate=holding.sale_tax_rate,
            legacy_rate=DEFAULT_SALE_TAX_RATE,
            tax_exempt=account.tax_reporting_method == TaxReportingMethod.TAX_EXEMPT,
        )
        warnings.extend(tax_estimate.warnings)
        sale_tax_rate = tax_estimate.rate or ZERO
        sale_tax_native = tax_estimate.tax_amount or ZERO
        sale_tax = _to_base(
            sale_tax_native,
            quote.currency,
            base_currency,
            usd_per_eur,
            fx_rates,
        )
        current_value = gross_current_value - sale_tax
        estimated_gain = current_value - cost_basis_base
        estimated_gain_percent = (
            (estimated_gain * Decimal(100) / cost_basis_base).quantize(Decimal("0.01"))
            if cost_basis_base > ZERO
            else ZERO
        )
        holding_values_by_id[holding.id] = current_value
        values_by_class[instrument.asset_class.value] += current_value
        gross_holdings_by_account[account.id] = (
            gross_holdings_by_account.get(account.id, ZERO) + gross_current_value
        )
        after_tax_holdings_by_account[account.id] = (
            after_tax_holdings_by_account.get(account.id, ZERO) + current_value
        )
        sale_tax_by_account[account.id] = sale_tax_by_account.get(account.id, ZERO) + sale_tax
        annual_dividend_income += _to_base(
            native_value * instrument.estimated_annual_yield,
            quote.currency,
            base_currency,
            usd_per_eur,
            fx_rates,
        )
        holdings.append(
            HoldingSummary(
                id=holding.id,
                account_id=account.id,
                assigned_goal_id=(
                    assigned_holding_goals.get(holding.id, (None, None))[0]
                ),
                assigned_goal_name=(
                    assigned_holding_goals.get(holding.id, (None, None))[1]
                ),
                allocated_percentage=allocated_holding_percentages.get(holding.id, ZERO),
                symbol=instrument.symbol,
                name=instrument.name,
                account_name=account.display_name,
                exchange=instrument.exchange,
                mic_code=instrument.mic,
                asset_class=instrument.asset_class,
                instrument_type=instrument.instrument_type,
                tax_domicile_country_code=holding.tax_domicile_country_code,
                quantity=holding.quantity,
                average_cost=holding.average_cost,
                purchase_date=holding.purchase_date,
                risk_tier=holding.risk_tier,
                expected_annual_return=holding.expected_annual_return,
                funding_currency=(
                    funding_subaccount.currency if funding_subaccount is not None else None
                ),
                funding_cost=holding.funding_cost,
                price=quote.price,
                price_currency=quote.currency,
                quote_source=quote.source,
                quote_observed_at=quote.observed_at,
                is_market_open=quote.is_market_open,
                change_since_refresh_percent=(
                    (
                        (quote.price - previous_quotes[instrument.id].price)
                        * Decimal(100)
                        / previous_quotes[instrument.id].price
                    ).quantize(Decimal("0.01"))
                    if instrument.id in previous_quotes
                    and previous_quotes[instrument.id].price
                    else None
                ),
                market_value=round_money(current_value),
                gross_market_value=round_money(gross_current_value),
                cost_basis_value=round_money(cost_basis_base),
                estimated_gain=round_money(estimated_gain),
                estimated_gain_percent=estimated_gain_percent,
                estimated_sale_tax=round_money(sale_tax),
                estimated_tax_rate=sale_tax_rate,
                estimated_tax_status=tax_estimate.status,
                base_currency=base_currency,
                is_demo=instrument.is_demo,
            )
        )

    account_summaries = list_accounts(session, user.id)
    account_cash_values = {
        account.id: sum(
            (
                _to_base(
                    subaccount.cash_balance,
                    subaccount.currency,
                    base_currency,
                    usd_per_eur,
                    fx_rates,
                )
                for subaccount in account.subaccounts
            ),
            ZERO,
        )
        for account in account_summaries
    }
    available_cash = sum(
        (
            _to_base(
                subaccount.cash_balance,
                subaccount.currency,
                base_currency,
                usd_per_eur,
                fx_rates,
            )
            for subaccount, account_type in session.execute(
                select(AccountSubaccount, BrokerAccount.account_type)
                .join(BrokerAccount, BrokerAccount.id == AccountSubaccount.account_id)
                .where(BrokerAccount.user_id == user.id)
            ).all()
            if account_type
            in {AccountType.BROKERAGE, AccountType.BANK, AccountType.SAVINGS}
        ),
        ZERO,
    )

    deposits: list[DepositSummary] = []
    deposit_value = ZERO
    deposit_values_by_id: dict[uuid.UUID, Decimal] = {}
    deposit_value_by_account: dict[uuid.UUID, Decimal] = {}
    annual_interest_income = ZERO
    assigned_deposit_goals = {
        deposit_id: (goal_id, goal_name)
        for deposit_id, goal_id, goal_name in session.execute(
            select(
                GoalDepositAllocation.fixed_deposit_id,
                Goal.id,
                Goal.name,
            )
            .join(Goal, Goal.id == GoalDepositAllocation.goal_id)
            .where(
                GoalDepositAllocation.user_id == user.id,
                Goal.is_active.is_(True),
            )
        ).all()
    }
    allocated_deposit_percentages: dict[uuid.UUID, Decimal] = {
        deposit_id: Decimal(total)
        for deposit_id, total in session.execute(
            select(
                GoalDepositAllocation.fixed_deposit_id,
                func.sum(GoalDepositAllocation.allocated_percentage),
            )
            .join(Goal, Goal.id == GoalDepositAllocation.goal_id)
            .where(
                GoalDepositAllocation.user_id == user.id,
                Goal.is_active.is_(True),
            )
            .group_by(GoalDepositAllocation.fixed_deposit_id)
        ).all()
    }
    fixed_deposits = session.scalars(select(FixedDeposit).where(FixedDeposit.user_id == user.id))
    for deposit in fixed_deposits:
        valuation_date = min(today, deposit.maturity_date)
        accrued_value = fixed_deposit_value(
            deposit.principal,
            deposit.annual_rate,
            deposit.start_date,
            valuation_date,
            deposit.compounding,
            deposit.rate_basis,
        )
        accrued_interest = max(ZERO, accrued_value - deposit.principal)
        deposit_base_value = _to_base(
            accrued_value, deposit.currency, base_currency, usd_per_eur, fx_rates
        )
        deposit_value += deposit_base_value
        deposit_values_by_id[deposit.id] = deposit_base_value
        deposit_value_by_account[deposit.account_id] = (
            deposit_value_by_account.get(deposit.account_id, ZERO) + deposit_base_value
        )
        annual_interest_income += _to_base(
            deposit.principal * deposit.annual_rate,
            deposit.currency,
            base_currency,
            usd_per_eur,
            fx_rates,
        )
        deposits.append(
            DepositSummary(
                id=deposit.id,
                account_id=deposit.account_id,
                source_subaccount_id=deposit.source_subaccount_id,
                assigned_goal_id=assigned_deposit_goals.get(deposit.id, (None, None))[0],
                assigned_goal_name=assigned_deposit_goals.get(deposit.id, (None, None))[1],
                allocated_percentage=allocated_deposit_percentages.get(deposit.id, ZERO),
                name=deposit.name,
                principal=deposit.principal,
                accrued_interest=accrued_interest,
                current_value=accrued_value,
                current_value_base=round_money(deposit_base_value),
                principal_value_base=round_money(
                    _to_base(
                        deposit.principal,
                        deposit.currency,
                        base_currency,
                        usd_per_eur,
                        fx_rates,
                    )
                ),
                currency=deposit.currency,
                annual_rate=deposit.annual_rate,
                annual_return_volatility_assumption=Decimal(
                    str(CMA_CONFIG["CASH_DEPOSIT"].volatility)
                ),
                rate_basis=deposit.rate_basis,
                compounding=deposit.compounding,
                period_months=deposit.period_months,
                start_date=deposit.start_date,
                maturity_date=deposit.maturity_date,
                days_to_maturity=max((deposit.maturity_date - today).days, 0),
            )
        )

    account_wealth = [
        AccountWealthSummary(
            id=account.id,
            display_name=account.display_name,
            account_type=account.account_type,
            currency=base_currency,
            cash_value=round_money(account_cash_values[account.id]),
            gross_holdings_value=round_money(
                gross_holdings_by_account.get(account.id, ZERO)
            ),
            estimated_sale_tax=round_money(sale_tax_by_account.get(account.id, ZERO)),
            after_tax_holdings_value=round_money(
                after_tax_holdings_by_account.get(account.id, ZERO)
            ),
            fixed_deposit_value=round_money(
                deposit_value_by_account.get(account.id, ZERO)
            ),
            total_after_tax_value=round_money(
                account_cash_values[account.id]
                + after_tax_holdings_by_account.get(account.id, ZERO)
                + deposit_value_by_account.get(account.id, ZERO)
            ),
        )
        for account in account_summaries
    ]

    grants = list(session.scalars(select(VestingGrant).where(VestingGrant.user_id == user.id)))
    vesting: list[VestingSummary] = []
    unvested_gross = ZERO
    unvested_net = ZERO
    unvested_short_term_sale_value = ZERO
    unvested_long_term_sale_value = ZERO
    for grant in grants:
        instrument = session.get(Instrument, grant.instrument_id)
        quote = latest_quotes.get(grant.instrument_id)
        if instrument is None:
            continue
        grant_tranches = sorted(
            session.scalars(
                select(VestingTranche).where(VestingTranche.grant_id == grant.id)
            ),
            key=lambda tranche: (tranche.available_date, tranche.vest_date),
        )
        future_tranches = [
            tranche
            for tranche in grant_tranches
            if tranche.available_date > today and tranche.status == TrancheStatus.SCHEDULED
        ]
        vested_units = sum(
            (
                tranche.units
                for tranche in grant_tranches
                if tranche.status in {TrancheStatus.VESTED, TrancheStatus.RELEASED}
                or (
                    tranche.status == TrancheStatus.SCHEDULED
                    and tranche.available_date <= today
                )
            ),
            ZERO,
        )
        units = sum((tranche.units for tranche in future_tranches), ZERO)
        if quote is None:
            warnings.append(
                f"{instrument.symbol} equity grant has no cached market quote and is excluded "
                "from its current value estimate."
            )
            intrinsic_value = ZERO
        elif grant.grant_type == GrantType.OPTION:
            intrinsic_value = units * max(quote.price - (grant.strike_price or ZERO), ZERO)
        else:
            intrinsic_value = units * quote.price
        gross = (
            _to_base(intrinsic_value, quote.currency, base_currency, usd_per_eur, fx_rates)
            if quote is not None
            else ZERO
        )
        net = gross * (ONE - grant.tax_rate_assumption)
        short_term_sale_value = gross * (ONE - grant.short_term_sale_tax_rate)
        long_term_sale_value = gross * (ONE - grant.long_term_sale_tax_rate)
        unvested_gross += gross
        unvested_net += net
        unvested_short_term_sale_value += short_term_sale_value
        unvested_long_term_sale_value += long_term_sale_value
        vesting.append(
            VestingSummary(
                id=grant.id,
                symbol=instrument.symbol,
                name=instrument.name,
                grant_type=grant.grant_type,
                grant_label=grant.grant_label,
                grant_date=grant.grant_date,
                total_units=grant.total_units,
                units=units,
                vested_units=vested_units,
                vested_percent=(
                    min(Decimal(100), vested_units * Decimal(100) / grant.total_units)
                    if grant.total_units
                    else ZERO
                ),
                next_vest_date=min(
                    (tranche.vest_date for tranche in future_tranches), default=None
                ),
                strike_price=grant.strike_price,
                strike_currency=grant.strike_currency,
                tax_rate_assumption=grant.tax_rate_assumption,
                short_term_sale_tax_rate=grant.short_term_sale_tax_rate,
                long_term_sale_tax_rate=grant.long_term_sale_tax_rate,
                long_term_holding_period_days=grant.long_term_holding_period_days,
                gross_value=round_money(gross),
                estimated_net_value=round_money(net),
                estimated_short_term_sale_value=round_money(short_term_sale_value),
                estimated_long_term_sale_value=round_money(long_term_sale_value),
                currency=base_currency,
                price=quote.price if quote is not None else None,
                price_currency=quote.currency if quote is not None else None,
                quote_source=quote.source if quote is not None else None,
                quote_observed_at=quote.observed_at if quote is not None else None,
                tranches=[
                    VestingTrancheSummary(
                        vest_date=tranche.vest_date,
                        available_date=tranche.available_date,
                        units=tranche.units,
                        status=(
                            TrancheStatus.VESTED.value
                            if tranche.status == TrancheStatus.SCHEDULED
                            and tranche.available_date <= today
                            else tranche.status.value
                        ),
                    )
                    for tranche in grant_tranches
                ],
            )
        )

    total_invested = sum(values_by_class.values(), ZERO)
    net_worth = total_invested + available_cash + deposit_value
    annual_income = annual_dividend_income + annual_interest_income
    goals: list[GoalSummary] = []
    goal_rows = list(
        session.scalars(
            select(Goal)
            .where(Goal.user_id == user.id, Goal.is_active.is_(True))
            .order_by(Goal.name, Goal.id)
        )
    )
    financial_plan = get_financial_plan(session, user.id)

    def goal_convert(value: Decimal, source: Currency, destination: Currency) -> Decimal:
        return _to_base(value, source, destination, usd_per_eur, fx_rates)

    linked_accounts_by_goal: dict[uuid.UUID, list[uuid.UUID]] = {}
    for goal_id, account_id in session.execute(
        select(GoalAccountLink.goal_id, GoalAccountLink.account_id)
        .join(Goal, Goal.id == GoalAccountLink.goal_id)
        .where(GoalAccountLink.user_id == user.id, Goal.is_active.is_(True))
        .order_by(GoalAccountLink.account_id)
    ):
        linked_accounts_by_goal.setdefault(goal_id, []).append(account_id)
    linked_holdings_by_goal: dict[uuid.UUID, list[tuple[uuid.UUID, Decimal]]] = {}
    for goal_id, holding_id, percentage in session.execute(
        select(
            GoalHoldingAllocation.goal_id,
            GoalHoldingAllocation.holding_id,
            GoalHoldingAllocation.allocated_percentage,
        )
        .join(Goal, Goal.id == GoalHoldingAllocation.goal_id)
        .where(GoalHoldingAllocation.user_id == user.id, Goal.is_active.is_(True))
        .order_by(GoalHoldingAllocation.holding_id)
    ):
        linked_holdings_by_goal.setdefault(goal_id, []).append((holding_id, percentage))
    linked_deposits_by_goal: dict[uuid.UUID, list[tuple[uuid.UUID, Decimal]]] = {}
    for goal_id, deposit_id, percentage in session.execute(
        select(
            GoalDepositAllocation.goal_id,
            GoalDepositAllocation.fixed_deposit_id,
            GoalDepositAllocation.allocated_percentage,
        )
        .join(Goal, Goal.id == GoalDepositAllocation.goal_id)
        .where(GoalDepositAllocation.user_id == user.id, Goal.is_active.is_(True))
        .order_by(GoalDepositAllocation.fixed_deposit_id)
    ):
        linked_deposits_by_goal.setdefault(goal_id, []).append((deposit_id, percentage))
    for goal in goal_rows:
        manual_current_amount = _to_base(
            goal.current_amount, goal.target_currency, base_currency, usd_per_eur, fx_rates
        )
        goal_holding_pairs = linked_holdings_by_goal.get(goal.id, [])
        goal_deposit_pairs = linked_deposits_by_goal.get(goal.id, [])
        goal_holding_ids = [holding_id for holding_id, _ in goal_holding_pairs]
        goal_deposit_ids = [deposit_id for deposit_id, _ in goal_deposit_pairs]
        linked_asset_value = sum(
            (
                holding_values_by_id.get(holding_id, ZERO) * percentage / Decimal(100)
                for holding_id, percentage in goal_holding_pairs
            ),
            ZERO,
        ) + sum(
            (
                deposit_values_by_id.get(deposit_id, ZERO) * percentage / Decimal(100)
                for deposit_id, percentage in goal_deposit_pairs
            ),
            ZERO,
        )
        current_amount = manual_current_amount + linked_asset_value
        current_annual_income = _to_base(
            goal.current_annual_income, goal.target_currency, base_currency, usd_per_eur, fx_rates
        )
        target_amount = (
            _to_base(
                goal.target_amount, goal.target_currency, base_currency, usd_per_eur, fx_rates
            )
            if goal.target_amount is not None
            else None
        )
        target_annual_income = (
            _to_base(
                goal.target_annual_income,
                goal.target_currency,
                base_currency,
                usd_per_eur,
                fx_rates,
            )
            if goal.target_annual_income is not None
            else None
        )
        progress_value, progress_percent = goal_progress(
            goal.goal_type,
            target_amount,
            target_annual_income,
            current_amount,
            current_annual_income,
        )
        goals.append(
            GoalSummary(
                id=goal.id,
                name=goal.name,
                goal_type=goal.goal_type,
                target_amount=target_amount,
                target_annual_income=target_annual_income,
                current_amount=progress_value,
                linked_asset_value=round_money(linked_asset_value),
                current_annual_income=current_annual_income,
                currency=base_currency,
                progress_percent=progress_percent.quantize(Decimal("0.01")),
                target_date=goal.target_date,
                risk_level=goal.risk_level,
                monthly_contribution=round_money(goal_convert(
                    contribution_months(
                        financial_plan, _goal_rules(goal), goal.monthly_contribution,
                        goal.target_currency, today, 1, goal_convert,
                    )[0].nominal_contribution,
                    goal.target_currency, base_currency,
                )),
                target_money_basis=goal.target_money_basis,
                annual_inflation_rate=goal.annual_inflation_rate,
                contribution_rules=_goal_rules(goal),
                visualization_budget_amount=goal.visualization_budget_amount,
                visualization_budget_period=goal.visualization_budget_period,
                fixed_percent=goal.fixed_percent,
                flexibility=goal.flexibility,
                linked_account_ids=linked_accounts_by_goal.get(goal.id, []),
                holding_ids=goal_holding_ids,
                fixed_deposit_ids=goal_deposit_ids,
            )
        )

    cash_flow_responses = _project_cash_flows(
        session, user.id, base_currency, usd_per_eur, fx_rates, months=12
    )[:8]
    cash_flow_schedules = list_cash_flow_schedules(session, user.id)

    snapshot_rows = list(
        session.scalars(
            select(ValuationSnapshot)
            .where(ValuationSnapshot.user_id == user.id)
            .order_by(ValuationSnapshot.observed_at)
        )
    )
    chart = [
        ChartPoint(
            label=snapshot.observed_at.strftime("%b"),
            date=snapshot.observed_at.date(),
            value=round_money(
                _to_base(
                    snapshot.total_value,
                    snapshot.currency,
                    base_currency,
                    usd_per_eur,
                    fx_rates,
                )
            ),
        )
        for snapshot in snapshot_rows
    ]
    if chart:
        chart[-1].value = round_money(net_worth)
    else:
        chart = [ChartPoint(label="Today", date=today, value=round_money(net_worth))]
    six_month_change = chart[-1].value - chart[0].value
    six_month_change_percent = (
        six_month_change * Decimal(100) / chart[0].value if chart[0].value else ZERO
    )

    current_allocation = [
        AllocationSummary(
            asset_class=AssetClass(asset_class.value),
            value=round_money(values_by_class[asset_class.value]),
            percentage=(
                values_by_class[asset_class.value] * Decimal(100) / total_invested
                if total_invested
                else ZERO
            ),
            target_percentage=_target_weights(policy).get(asset_class.value, ZERO) * Decimal(100),
        )
        for asset_class in AssetClass
    ]

    return {
        "base_currency": base_currency,
        "profile": _profile_response(user),
        "as_of": now,
        "sample_data": sample_data,
        "market_data_provider_configured": bool(get_settings().twelve_data_api_key.strip()),
        "totals": {
            "net_worth": round_money(net_worth),
            "invested_assets": round_money(total_invested),
            "available_cash": round_money(available_cash),
            "fixed_deposits": round_money(deposit_value),
            "unvested_equity_gross": round_money(unvested_gross),
            "unvested_equity_net_estimate": round_money(unvested_net),
            "unvested_equity_short_term_sale_estimate": round_money(
                unvested_short_term_sale_value
            ),
            "unvested_equity_long_term_sale_estimate": round_money(
                unvested_long_term_sale_value
            ),
            "estimated_monthly_income": round_money(annual_income / Decimal(12)),
            "emergency_reserve_target": round_money(policy.emergency_reserve),
            "reserve_shortfall": round_money(
                max(
                    ZERO,
                    _to_base(
                        policy.emergency_reserve,
                        user.base_currency,
                        base_currency,
                        usd_per_eur,
                        fx_rates,
                    )
                    - available_cash,
                )
            ),
        },
        "six_month_change": round_money(six_month_change),
        "six_month_change_percent": six_month_change_percent.quantize(Decimal("0.01")),
        "allocation": current_allocation,
        "chart": chart,
        "accounts": account_summaries,
        "account_wealth": account_wealth,
        "holdings": holdings,
        "market_fx_rates": _market_fx_summaries(session),
        "goals": goals,
        "cash_flows": cash_flow_responses,
        "cash_flow_schedules": cash_flow_schedules,
        "deposits": deposits,
        "vesting": vesting,
        "purchase_plans": _purchase_plan_summaries(
            session, user, base_currency, fx_rates, latest_quotes
        ),
        "warnings": warnings,
        "policy": PolicyResponse(
            funding_rule=policy.funding_rule,
            emergency_reserve=_to_base(
                policy.emergency_reserve,
                user.base_currency,
                base_currency,
                usd_per_eur,
                fx_rates,
            ),
            target_weights=_target_weights(policy),
        ),
    }


def portfolio_projection(
    session: Session,
    user_id: uuid.UUID,
    target_date: date,
    requested_currency: Currency | None = None,
    *,
    snapshot: dict[str, Any] | None = None,
    include_taxes: bool = True,
    annual_inflation_rate: Decimal = ZERO,
) -> PortfolioProjectionResponse:
    user = _get_user(session, user_id)
    today = date.today()
    if target_date <= today:
        raise HTTPException(status_code=422, detail="Choose a future projection date")
    maximum_date = add_months(today, 40 * 12)
    if target_date > maximum_date:
        raise HTTPException(
            status_code=422,
            detail="Projection dates can be at most 40 years in the future.",
        )
    if annual_inflation_rate <= -ONE:
        raise HTTPException(
            status_code=422,
            detail="Annual inflation must be greater than −100%.",
        )

    snapshot = snapshot if snapshot is not None else dashboard(session, user.id, requested_currency)
    base_currency = snapshot["base_currency"]
    usd_per_eur = user.usd_per_eur
    fx_rates = _fx_matrix(session, user)
    current_accounts = snapshot["account_wealth"]
    holdings = snapshot["holdings"]
    savings_wallets = [
        (account.id, subaccount)
        for account in snapshot["accounts"]
        for subaccount in account.subaccounts
        if subaccount.annual_interest_rate and subaccount.interest_start_date is not None
    ]
    accounts_by_id = {account.id: account for account in snapshot["accounts"]}
    deposits = list(session.scalars(select(FixedDeposit).where(FixedDeposit.user_id == user.id)))
    deposit_tax_rates: dict[uuid.UUID, Decimal] = {}
    projection_warnings: list[str] = []
    for deposit in deposits:
        account = accounts_by_id.get(deposit.account_id)
        if account is None:
            continue
        rate, warnings = _interest_tax_rate_for_account(user, account)
        deposit_tax_rates[deposit.id] = rate
        if include_taxes:
            projection_warnings.extend(warnings)

    current_sale_tax_by_account: dict[uuid.UUID, Decimal] = {}
    if not include_taxes:
        for holding in holdings:
            current_sale_tax_by_account[holding.account_id] = (
                current_sale_tax_by_account.get(holding.account_id, ZERO)
                + holding.estimated_sale_tax
            )

    current_deposit_tax_by_account: dict[uuid.UUID, Decimal] = {}
    if include_taxes:
        for deposit in deposits:
            tax_rate = deposit_tax_rates.get(deposit.id, ZERO)
            current_value = fixed_deposit_value(
                deposit.principal,
                deposit.annual_rate,
                deposit.start_date,
                min(today, deposit.maturity_date),
                deposit.compounding,
                deposit.rate_basis,
            )
            current_tax = max(ZERO, current_value - deposit.principal) * tax_rate
            current_deposit_tax_by_account[deposit.account_id] = (
                current_deposit_tax_by_account.get(deposit.account_id, ZERO)
                + _to_base(
                    current_tax,
                    deposit.currency,
                    base_currency,
                    usd_per_eur,
                    fx_rates,
                )
            )

    def project_at(projection_date: date) -> list[ProjectionAccountValue]:
        years = Decimal((projection_date - today).days) / Decimal(365)
        cash_by_account = {
            account.id: account.cash_value for account in current_accounts
        }
        for account_id, wallet in savings_wallets:
            assert wallet.annual_interest_rate is not None
            assert wallet.interest_start_date is not None
            future_payments = len(
                _monthly_payment_dates(wallet.interest_start_date, projection_date)
            ) - len(_monthly_payment_dates(wallet.interest_start_date, today))
            if future_payments <= 0:
                continue
            monthly_growth = (ONE + wallet.annual_interest_rate / Decimal(12)) ** future_payments
            future_interest = wallet.cash_balance * (monthly_growth - ONE)
            account = accounts_by_id.get(account_id)
            interest_tax = ZERO
            if include_taxes and account is not None:
                tax_rate, warnings = _interest_tax_rate_for_account(user, account)
                interest_tax = max(ZERO, future_interest) * tax_rate
                if future_interest > ZERO:
                    projection_warnings.extend(warnings)
            cash_by_account[account_id] = cash_by_account.get(account_id, ZERO) + _to_base(
                future_interest - interest_tax,
                wallet.currency,
                base_currency,
                usd_per_eur,
                fx_rates,
            )
        holding_by_account: dict[uuid.UUID, Decimal] = {}
        for holding in holdings:
            growth_factor = compound_growth_factor(
                holding.expected_annual_return,
                years,
            )
            future_gross_native = holding.quantity * holding.price * growth_factor
            future_gross_base = _to_base(
                future_gross_native,
                holding.price_currency,
                base_currency,
                usd_per_eur,
                fx_rates,
            )
            cost_basis_base = _to_base(
                holding.quantity * holding.average_cost,
                holding.price_currency,
                base_currency,
                usd_per_eur,
                fx_rates,
            )
            future_tax = (
                max(ZERO, future_gross_base - cost_basis_base) * holding.estimated_tax_rate
                if include_taxes
                else ZERO
            )
            projected_value = future_gross_base - future_tax
            holding_by_account[holding.account_id] = (
                holding_by_account.get(holding.account_id, ZERO) + projected_value
            )

        deposit_by_account: dict[uuid.UUID, Decimal] = {}
        for deposit in deposits:
            accrual_date = min(projection_date, deposit.maturity_date)
            value_at_accrual_date = fixed_deposit_value(
                deposit.principal,
                deposit.annual_rate,
                deposit.start_date,
                accrual_date,
                deposit.compounding,
                deposit.rate_basis,
            )
            deposit_tax = (
                max(ZERO, value_at_accrual_date - deposit.principal)
                * deposit_tax_rates.get(deposit.id, ZERO)
                if include_taxes
                else ZERO
            )
            if include_taxes and value_at_accrual_date > deposit.principal:
                account = accounts_by_id.get(deposit.account_id)
                if account is not None:
                    _, warnings = _interest_tax_rate_for_account(user, account)
                    projection_warnings.extend(warnings)
            deposit_by_account[deposit.account_id] = (
                deposit_by_account.get(deposit.account_id, ZERO)
                + _to_base(
                    value_at_accrual_date - deposit_tax,
                    deposit.currency,
                    base_currency,
                    usd_per_eur,
                    fx_rates,
                )
            )

        result: list[ProjectionAccountValue] = []
        for account in current_accounts:
            projected_cash = cash_by_account.get(account.id, ZERO)
            projected_holdings = holding_by_account.get(account.id, ZERO)
            projected_deposits = deposit_by_account.get(account.id, ZERO)
            projected_total = projected_cash + projected_holdings + projected_deposits
            real_factor = compound_growth_factor(
                annual_inflation_rate,
                Decimal((projection_date - today).days) / Decimal(365),
            )
            result.append(
                ProjectionAccountValue(
                    account_id=account.id,
                    account_name=account.display_name,
                    current_value=round_money(
                        account.total_after_tax_value
                        + current_sale_tax_by_account.get(account.id, ZERO)
                        - current_deposit_tax_by_account.get(account.id, ZERO)
                    ),
                    projected_cash_value=round_money(projected_cash),
                    projected_holdings_value=round_money(projected_holdings),
                    projected_deposit_value=round_money(projected_deposits),
                    projected_total_value=round_money(projected_total),
                    real_projected_total_value=round_money(projected_total / real_factor),
                )
            )
        return result

    dates = [today]
    year_index = 1
    while add_months(today, year_index * 12) < target_date:
        dates.append(add_months(today, year_index * 12))
        year_index += 1
    if dates[-1] != target_date:
        dates.append(target_date)

    timeline: list[ProjectionPoint] = []
    for point_date in dates:
        account_values = project_at(point_date)
        timeline.append(
            ProjectionPoint(
                date=point_date,
                label=(
                    point_date.strftime("%Y")
                    if point_date.month == today.month
                    else point_date.strftime("%b %Y")
                ),
                total_value=round_money(
                    sum(
                        (account.projected_total_value for account in account_values),
                        ZERO,
                    )
                ),
                accounts=account_values,
                real_total_value=round_money(
                    sum(
                        (
                            account.real_projected_total_value or ZERO
                            for account in account_values
                        ),
                        ZERO,
                    )
                ),
            )
        )

    projected_accounts = timeline[-1].accounts
    projected_total = sum(
        (account.projected_total_value for account in projected_accounts),
        ZERO,
    )
    current_net_worth = (
        snapshot["totals"]["net_worth"]
        + sum(current_sale_tax_by_account.values(), ZERO)
        - sum(current_deposit_tax_by_account.values(), ZERO)
    )
    tax_assumption = (
        "Taxes are excluded from projected amounts."
        if not include_taxes
        else "Stocks/ETFs use their estimated sale-tax rate on positive gains; "
        "savings and fixed-deposit interest use the account's country-rule estimate "
        "when available, otherwise the labeled 10% interest-tax assumption. Tax is "
        "estimated at the projection date."
    )
    return PortfolioProjectionResponse(
        base_currency=base_currency,
        as_of=datetime.now(UTC),
        target_date=target_date,
        current_net_worth=round_money(current_net_worth),
        projected_net_worth=round_money(projected_total),
        estimated_change=round_money(projected_total - current_net_worth),
        accounts=projected_accounts,
        timeline=timeline,
        warnings=list(dict.fromkeys([
            (
                "Illustrative deterministic scenario, not a prediction or guarantee. "
                "Annual returns are user-editable assumptions and are not forecasts."
            ),
            (
                "Stock/ETF assumptions are nominal total returns (including reinvested dividends) "
                "in listing currency. Current FX rates are held constant."
            ),
            tax_assumption,
            (
                "Unvested awards, scheduled share purchases, future cash-flow forecasts, and "
                "additional contributions are excluded."
            ),
            (
                f"Inflation of {annual_inflation_rate * Decimal(100):.2f}% a year is held "
                "constant; real values show purchasing power in today's currency."
            ),
            *projection_warnings,
            (
                "Country-specific annual social contributions (including CASS) and future tax "
                "law changes are not included."
            ),
        ])),
        real_projected_net_worth=timeline[-1].real_total_value,
        include_taxes=include_taxes,
        annual_inflation_rate=annual_inflation_rate,
    )


def portfolio_projection_scenario(
    session: Session,
    user_id: uuid.UUID,
    payload: PortfolioProjectionScenarioRequest,
) -> PortfolioProjectionScenarioResponse:
    user = _get_user(session, user_id)
    snapshot = dashboard(session, user.id, payload.currency)
    baseline = portfolio_projection(
        session,
        user.id,
        payload.target_date,
        payload.currency,
        snapshot=snapshot,
    )
    fx_rates = _fx_matrix(session, user)
    today = date.today()

    accounts_by_id = {account.id: account for account in snapshot["accounts"]}
    scope_account = (
        accounts_by_id.get(payload.scope_account_id)
        if payload.scope_account_id is not None
        else None
    )
    if payload.scope_account_id is not None and scope_account is None:
        raise HTTPException(status_code=404, detail="Projection account was not found")

    all_holdings = {holding.id: holding for holding in snapshot["holdings"]}
    scoped_holdings = [
        holding
        for holding in snapshot["holdings"]
        if payload.scope_account_id is None or holding.account_id == payload.scope_account_id
    ]
    for allocation in payload.investments:
        holding = all_holdings.get(allocation.holding_id)
        if holding is None:
            raise HTTPException(
                status_code=404,
                detail="A selected investment was not found or has no current quote.",
            )
        if (
            payload.scope_account_id is not None
            and holding.account_id != payload.scope_account_id
        ):
            raise HTTPException(
                status_code=422,
                detail="Selected investments must belong to the selected projection account.",
            )
        account = accounts_by_id.get(holding.account_id)
        if account is None or account.account_type == AccountType.EMPLOYER_PLAN:
            raise HTTPException(
                status_code=422,
                detail="Monthly contributions cannot be projected into employer-plan holdings.",
            )

    invested_value_by_tier = {tier: ZERO for tier in ("X", "Y", "Z")}
    for holding in scoped_holdings:
        invested_value_by_tier[holding.risk_tier] += holding.market_value
    current_invested_value = sum(invested_value_by_tier.values(), ZERO)
    risk_mix = {
        tier: (
            (invested_value_by_tier[tier] / current_invested_value).quantize(
                Decimal("0.0001")
            )
            if current_invested_value > ZERO
            else ZERO
        )
        for tier in ("X", "Y", "Z")
    }
    risk_scores = {"X": Decimal("1"), "Y": Decimal("2"), "Z": Decimal("3")}
    weighted_risk_score = (
        sum(
            (
                invested_value_by_tier[tier] * risk_scores[tier]
                for tier in ("X", "Y", "Z")
            ),
            ZERO,
        )
        / current_invested_value
        if current_invested_value > ZERO
        else None
    )

    monthly_contribution = _to_base(
        payload.monthly_contribution,
        payload.currency,
        baseline.base_currency,
        user.usd_per_eur,
        fx_rates,
    )
    holding_contributions: dict[uuid.UUID, Decimal] = {}
    holding_rates: dict[uuid.UUID, Decimal] = {}
    holding_percentages: dict[uuid.UUID, Decimal] = {}
    contribution_weighted_risk_score = ZERO
    weighted_return = ZERO
    for allocation in payload.investments:
        holding = all_holdings[allocation.holding_id]
        assumed_return = (
            allocation.assumed_annual_return
            if allocation.assumed_annual_return is not None
            else holding.expected_annual_return
        )
        percentage = allocation.contribution_percentage / Decimal("100")
        holding_contributions[holding.id] = monthly_contribution * percentage
        holding_rates[holding.id] = assumed_return
        holding_percentages[holding.id] = allocation.contribution_percentage
        contribution_weighted_risk_score += percentage * risk_scores[holding.risk_tier]
        weighted_return += percentage * assumed_return

    def contribution_values_at(
        projection_date: date,
    ) -> tuple[dict[uuid.UUID, Decimal], dict[uuid.UUID, tuple[Decimal, Decimal, Decimal]]]:
        payment_count = len(_monthly_payment_dates(today, projection_date))
        monthly_growth_by_holding: dict[uuid.UUID, Decimal] = {}
        account_values: dict[uuid.UUID, Decimal] = {}
        investment_values: dict[uuid.UUID, tuple[Decimal, Decimal, Decimal]] = {}

        for holding_id, monthly_amount in holding_contributions.items():
            holding = all_holdings[holding_id]
            monthly_growth = monthly_growth_by_holding.get(holding_id)
            if monthly_growth is None:
                monthly_growth = compound_growth_factor(
                    holding_rates[holding_id], Decimal("1") / Decimal("12")
                )
                monthly_growth_by_holding[holding_id] = monthly_growth

            if payment_count == 0:
                gross_value = ZERO
            elif abs(monthly_growth - ONE) < Decimal("1e-24"):
                gross_value = monthly_amount * payment_count
            else:
                gross_value = (
                    monthly_amount
                    * (monthly_growth**payment_count - ONE)
                    / (monthly_growth - ONE)
                )
            contribution_principal = monthly_amount * payment_count
            estimated_tax = max(ZERO, gross_value - contribution_principal) * (
                holding.estimated_tax_rate
            )
            after_tax_value = gross_value - estimated_tax
            account_values[holding.account_id] = (
                account_values.get(holding.account_id, ZERO) + after_tax_value
            )
            investment_values[holding_id] = (
                contribution_principal,
                gross_value,
                estimated_tax,
            )
        return account_values, investment_values

    scenario_timeline: list[ProjectionPoint] = []
    for point in baseline.timeline:
        contribution_by_account, _ = contribution_values_at(point.date)
        scenario_accounts = [
            account.model_copy(
                update={
                    "projected_holdings_value": round_money(
                        account.projected_holdings_value
                        + contribution_by_account.get(account.account_id, ZERO)
                    ),
                    "projected_total_value": round_money(
                        account.projected_total_value
                        + contribution_by_account.get(account.account_id, ZERO)
                    ),
                }
            )
            for account in point.accounts
        ]
        scenario_timeline.append(
            ProjectionPoint(
                date=point.date,
                label=point.label,
                total_value=round_money(
                    sum(
                        (account.projected_total_value for account in scenario_accounts),
                        ZERO,
                    )
                ),
                accounts=scenario_accounts,
            )
        )

    scenario_accounts = scenario_timeline[-1].accounts
    scenario_total = sum(
        (account.projected_total_value for account in scenario_accounts),
        ZERO,
    )
    scenario_warnings = [
        (
            warning.replace(
                "Unvested awards, scheduled share purchases, future cash-flow forecasts, and "
                "additional contributions are excluded.",
                "Unvested awards, scheduled share purchases, and future cash-flow forecasts are "
                "excluded; the requested monthly contributions are included.",
            )
        )
        for warning in baseline.warnings
    ]
    with_contributions = PortfolioProjectionResponse(
        base_currency=baseline.base_currency,
        as_of=baseline.as_of,
        target_date=baseline.target_date,
        current_net_worth=baseline.current_net_worth,
        projected_net_worth=round_money(scenario_total),
        estimated_change=round_money(scenario_total - baseline.current_net_worth),
        accounts=scenario_accounts,
        timeline=scenario_timeline,
        warnings=scenario_warnings,
    )

    _, investment_values = contribution_values_at(payload.target_date)
    investment_results: list[ProjectionScenarioInvestment] = []
    for allocation in payload.investments:
        holding = all_holdings[allocation.holding_id]
        principal, gross_value, estimated_tax = investment_values[holding.id]
        investment_results.append(
            ProjectionScenarioInvestment(
                holding_id=holding.id,
                symbol=holding.symbol,
                name=holding.name,
                account_id=holding.account_id,
                account_name=holding.account_name,
                exchange=holding.exchange,
                risk_tier=holding.risk_tier,
                current_value=holding.market_value,
                current_weight=(
                    (holding.market_value / current_invested_value).quantize(
                        Decimal("0.0001")
                    )
                    if current_invested_value > ZERO
                    else ZERO
                ),
                contribution_percentage=holding_percentages[holding.id],
                monthly_contribution=round_money(holding_contributions[holding.id]),
                assumed_annual_return=holding_rates[holding.id],
                contribution_principal=round_money(principal),
                projected_gross_value=round_money(gross_value),
                estimated_tax=round_money(estimated_tax),
                projected_after_tax_value=round_money(gross_value - estimated_tax),
            )
        )

    scope_name = scope_account.display_name if scope_account is not None else "All tracked accounts"
    return PortfolioProjectionScenarioResponse(
        baseline=baseline,
        with_contributions=with_contributions,
        monthly_contribution=round_money(monthly_contribution),
        monthly_contribution_currency=baseline.base_currency,
        weighted_annual_return_assumption=weighted_return,
        risk_summary=ProjectionScenarioRiskSummary(
            scope_account_id=payload.scope_account_id,
            scope_account_name=scope_name,
            current_invested_value=round_money(current_invested_value),
            risk_mix=risk_mix,
            weighted_risk_score=(
                weighted_risk_score.quantize(Decimal("0.01"))
                if weighted_risk_score is not None
                else None
            ),
            contribution_weighted_risk_score=contribution_weighted_risk_score.quantize(
                Decimal("0.01")
            ),
            methodology=(
                "Current risk is a market-value-weighted mean of the app's qualitative tiers "
                "(X=1, Y=2, Z=3), across quoted stocks/ETFs in scope. It is not measured "
                "volatility, a loss probability, or a safety rating."
            ),
        ),
        investments=investment_results,
        assumptions=[
            (
                "The baseline is the existing deterministic projection: current holdings use "
                "their saved annual-return assumptions; current FX is held constant; cash, "
                "savings interest, deposits, and estimated sale tax follow the baseline rules."
            ),
            (
                "The extra monthly contribution is hypothetical, does not change tracked "
                "balances, and is invested only in the selected quoted holdings at the "
                "entered percentages."
            ),
            (
                "Contribution weights must sum to 100%. Each selected investment compounds "
                "monthly at its own assumed effective annual return. Contributions are "
                "modelled at the end of each monthly period, with the first contribution one "
                "month after today; only scheduled monthly dates on or before the target "
                "are counted."
            ),
            (
                "FX is held at today's rate. At the target date, estimated tax is applied to "
                "positive gains on the hypothetical contributions using each holding's "
                "current estimated sale-tax rate. Losses receive no tax credit."
            ),
            (
                "The account risk score and X/Y/Z mix use qualitative holding tiers weighted "
                "by current after-tax market value; the tiers are not measured volatility."
            ),
            (
                "This is a deterministic what-if scenario, not a forecast, guarantee, or "
                "investment recommendation. Return assumptions are user-editable inputs."
            ),
        ],
    )


def portfolio_projection_range(
    session: Session,
    user_id: uuid.UUID,
    payload: PortfolioProjectionRangeRequest,
) -> PortfolioProjectionRangeResponse:
    user = _get_user(session, user_id)
    snapshot = dashboard(session, user.id, payload.currency)
    baseline = portfolio_projection(
        session,
        user.id,
        payload.target_date,
        payload.currency,
        snapshot=snapshot,
        include_taxes=payload.include_taxes,
        annual_inflation_rate=payload.annual_inflation_rate,
    )
    today = date.today()
    fx_rates = _fx_matrix(session, user)
    accounts = {account.id: account for account in snapshot["accounts"]}
    if payload.scope_account_id is not None and payload.scope_account_id not in accounts:
        raise HTTPException(status_code=404, detail="Projection account was not found")
    scope_account = (
        accounts.get(payload.scope_account_id)
        if payload.scope_account_id is not None
        else None
    )
    all_holdings = {holding.id: holding for holding in snapshot["holdings"]}
    deposits = {
        deposit.id: deposit
        for deposit in session.scalars(
            select(FixedDeposit).where(FixedDeposit.user_id == user.id)
        )
    }
    deposit_summaries = {deposit.id: deposit for deposit in snapshot["deposits"]}
    warnings = list(baseline.warnings)
    assets: list[dict[str, Any]] = []

    for investment in payload.investments:
        if investment.asset_type == "holding":
            holding = all_holdings.get(investment.asset_id)
            if holding is None:
                raise HTTPException(
                    status_code=404,
                    detail="A selected holding was not found or has no current quote.",
                )
            account = accounts.get(holding.account_id)
            if account is None:
                raise HTTPException(status_code=404, detail="A selected account was not found")
            if (
                payload.scope_account_id is not None
                and holding.account_id != payload.scope_account_id
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Selected investments must belong to the selected projection account.",
                )
            if account.account_type == AccountType.EMPLOYER_PLAN:
                raise HTTPException(
                    status_code=422,
                    detail="Employer-plan holdings cannot be included in a projection scenario.",
                )
            current_gross = _to_base(
                holding.quantity * holding.price,
                holding.price_currency,
                baseline.base_currency,
                user.usd_per_eur,
                fx_rates,
            )
            cost_basis = _to_base(
                holding.quantity * holding.average_cost,
                holding.price_currency,
                baseline.base_currency,
                user.usd_per_eur,
                fx_rates,
            )
            assets.append(
                {
                    "input": investment,
                    "type": "holding",
                    "name": f"{holding.symbol} · {holding.account_name}",
                    "account_id": holding.account_id,
                    "risk_tier": holding.risk_tier,
                    "volatility": holding.annual_return_volatility_assumption,
                    "current_value": current_gross,
                    "cost_basis": cost_basis,
                    "tax_rate": holding.estimated_tax_rate,
                    "expected_return": holding.expected_annual_return,
                    "model": holding,
                    "maturity_date": None,
                }
            )
        elif investment.asset_type == "deposit":
            deposit = deposits.get(investment.asset_id)
            summary = deposit_summaries.get(investment.asset_id)
            if deposit is None or summary is None:
                raise HTTPException(status_code=404, detail="A selected deposit was not found")
            account = accounts.get(deposit.account_id)
            if account is None:
                raise HTTPException(status_code=404, detail="A selected account was not found")
            if (
                payload.scope_account_id is not None
                and deposit.account_id != payload.scope_account_id
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Selected investments must belong to the selected projection account.",
                )
            tax_rate, tax_warnings = _interest_tax_rate_for_account(user, account)
            if payload.include_taxes:
                warnings.extend(tax_warnings)
            assets.append(
                {
                    "input": investment,
                    "type": "deposit",
                    "name": f"{deposit.name} · {account.display_name}",
                    "account_id": deposit.account_id,
                    "risk_tier": None,
                    "volatility": summary.annual_return_volatility_assumption,
                    "current_value": _to_base(
                        summary.current_value,
                        deposit.currency,
                        baseline.base_currency,
                        user.usd_per_eur,
                        fx_rates,
                    ),
                    "cost_basis": _to_base(
                        deposit.principal,
                        deposit.currency,
                        baseline.base_currency,
                        user.usd_per_eur,
                        fx_rates,
                    ),
                    "tax_rate": tax_rate,
                    "expected_return": deposit.annual_rate,
                    "model": deposit,
                    "maturity_date": deposit.maturity_date,
                }
            )
        else:
            assert investment.name is not None
            assert investment.current_value is not None
            assert investment.cost_basis is not None
            assert investment.tax_rate is not None
            assets.append(
                {
                    "input": investment,
                    "type": "other",
                    "name": investment.name,
                    "account_id": payload.scope_account_id,
                    "risk_tier": None,
                    "volatility": None,
                    "current_value": investment.current_value,
                    "cost_basis": investment.cost_basis,
                    "tax_rate": investment.tax_rate,
                    "expected_return": None,
                    "model": None,
                    "maturity_date": None,
                }
            )

    monthly_contribution = _to_base(
        payload.monthly_contribution,
        payload.currency,
        baseline.base_currency,
        user.usd_per_eur,
        fx_rates,
    )
    for asset in assets:
        asset["monthly_contribution"] = (
            monthly_contribution
            * asset["input"].contribution_percentage
            / Decimal("100")
        )

    def selected_baseline_value(asset: dict[str, Any], at_date: date) -> Decimal:
        years = Decimal((at_date - today).days) / Decimal(365)
        if asset["type"] == "holding":
            holding = asset["model"]
            gross = _to_base(
                holding.quantity
                * holding.price
                * compound_growth_factor(holding.expected_annual_return, years),
                holding.price_currency,
                baseline.base_currency,
                user.usd_per_eur,
                fx_rates,
            )
            basis = _to_base(
                holding.quantity * holding.average_cost,
                holding.price_currency,
                baseline.base_currency,
                user.usd_per_eur,
                fx_rates,
            )
        elif asset["type"] == "deposit":
            deposit = asset["model"]
            gross = _to_base(
                fixed_deposit_value(
                    deposit.principal,
                    deposit.annual_rate,
                    deposit.start_date,
                    min(at_date, deposit.maturity_date),
                    deposit.compounding,
                    deposit.rate_basis,
                ),
                deposit.currency,
                baseline.base_currency,
                user.usd_per_eur,
                fx_rates,
            )
            basis = asset["cost_basis"]
        else:
            return asset["current_value"]
        tax = (
            max(ZERO, gross - basis) * asset["tax_rate"]
            if payload.include_taxes
            else ZERO
        )
        return gross - tax

    def monthly_future_value(
        monthly_amount: Decimal, annual_return: Decimal, payment_count: int
    ) -> Decimal:
        if payment_count <= 0 or monthly_amount == ZERO:
            return ZERO
        monthly_growth = compound_growth_factor(
            annual_return, Decimal("1") / Decimal("12")
        )
        if abs(monthly_growth - ONE) < Decimal("1e-24"):
            return monthly_amount * payment_count
        return (
            monthly_amount
            * (monthly_growth**payment_count - ONE)
            / (monthly_growth - ONE)
        )

    def evaluate_asset(
        asset: dict[str, Any], annual_return: Decimal, at_date: date
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        years = Decimal((at_date - today).days) / Decimal(365)
        payment_dates = _monthly_payment_dates(today, at_date)
        contribution_principal = asset["monthly_contribution"] * len(payment_dates)
        if asset["type"] == "deposit":
            maturity_date = asset["maturity_date"]
            earning_days = max(0, min((at_date - today).days, (maturity_date - today).days))
            earning_years = Decimal(earning_days) / Decimal(365)
        else:
            earning_years = years
        gross = asset["current_value"] * compound_growth_factor(
            annual_return, earning_years
        )
        if asset["type"] == "deposit":
            maturity_date = asset["maturity_date"]
            active_contributions = sum(
                payment_date <= maturity_date for payment_date in payment_dates
            )
            contribution_value = monthly_future_value(
                asset["monthly_contribution"],
                annual_return,
                active_contributions,
            )
            contribution_value += asset["monthly_contribution"] * (
                len(payment_dates) - active_contributions
            )
        else:
            contribution_value = monthly_future_value(
                asset["monthly_contribution"],
                annual_return,
                len(payment_dates),
            )
        gross += contribution_value
        taxable_basis = asset["cost_basis"] + contribution_principal
        estimated_tax = (
            max(ZERO, gross - taxable_basis) * asset["tax_rate"]
            if payload.include_taxes
            else ZERO
        )
        return gross, estimated_tax, gross - estimated_tax, contribution_principal

    def baseline_total_at(point: ProjectionPoint, *, real: bool = False) -> Decimal:
        if payload.scope_account_id is None:
            value = point.real_total_value if real else point.total_value
            return value if value is not None else point.total_value
        account = next(
            (
                item
                for item in point.accounts
                if item.account_id == payload.scope_account_id
            ),
            None,
        )
        if account is None:
            return ZERO
        if real and account.real_projected_total_value is not None:
            return account.real_projected_total_value
        return account.projected_total_value

    custom_current_value = sum(
        (
            asset["current_value"]
            - (
                max(ZERO, asset["current_value"] - asset["cost_basis"])
                * asset["tax_rate"]
                if payload.include_taxes
                else ZERO
            )
            for asset in assets
            if asset["type"] == "other"
        ),
        ZERO,
    )
    scoped_baseline_account = next(
        (
            account
            for account in baseline.accounts
            if account.account_id == payload.scope_account_id
        ),
        None,
    )
    if payload.scope_account_id is not None and scoped_baseline_account is None:
        raise HTTPException(status_code=404, detail="Projection account was not found")
    baseline_current_value = (
        scoped_baseline_account.current_value
        if scoped_baseline_account is not None
        else baseline.current_net_worth
    )
    scenario_current_value = baseline_current_value + custom_current_value
    custom_current_net_by_key = {
        asset["input"].asset_key: (
            asset["current_value"]
            - (
                max(ZERO, asset["current_value"] - asset["cost_basis"])
                * asset["tax_rate"]
                if payload.include_taxes
                else ZERO
            )
        )
        for asset in assets
        if asset["type"] == "other"
    }
    scenario_baseline_timeline: list[ProjectionRangeLinePoint] = []
    for point in baseline.timeline:
        years = Decimal((point.date - today).days) / Decimal(365)
        deflator = compound_growth_factor(payload.annual_inflation_rate, years)
        nominal = baseline_total_at(point) + custom_current_value
        real = baseline_total_at(point, real=True) + custom_current_value / deflator
        scenario_baseline_timeline.append(
            ProjectionRangeLinePoint(
                date=point.date,
                label=point.label,
                nominal_value=round_money(nominal),
                real_value=round_money(real),
            )
        )

    baseline_target_nominal = baseline_total_at(baseline.timeline[-1])
    baseline_target_real = baseline_total_at(baseline.timeline[-1], real=True)
    target_years = Decimal((payload.target_date - today).days) / Decimal(365)
    target_deflator = compound_growth_factor(payload.annual_inflation_rate, target_years)
    baseline_with_custom_nominal = baseline_target_nominal + custom_current_value
    baseline_with_custom_real = (
        baseline_target_real
        + custom_current_value / target_deflator
    )
    lines: list[ProjectionRangeLine] = []
    results: list[ProjectionRangeInvestmentResult] = []
    combined_worst = baseline_with_custom_nominal
    combined_best = baseline_with_custom_nominal

    for asset in assets:
        input_asset = asset["input"]
        target_contribution_principal = asset["monthly_contribution"] * len(
            _monthly_payment_dates(today, payload.target_date)
        )
        for case, annual_return in (
            ("worst", input_asset.worst_annual_return),
            ("best", input_asset.best_annual_return),
        ):
            line_points: list[ProjectionRangeLinePoint] = []
            final_gross = ZERO
            final_tax = ZERO
            final_value = ZERO
            for point in baseline.timeline:
                gross, tax, net, _ = evaluate_asset(asset, annual_return, point.date)
                if asset["type"] == "other":
                    delta = net - custom_current_net_by_key[input_asset.asset_key]
                else:
                    delta = net - selected_baseline_value(asset, point.date)
                nominal_total = baseline_total_at(point) + custom_current_value + delta
                years = Decimal((point.date - today).days) / Decimal(365)
                real_total = nominal_total / compound_growth_factor(
                    payload.annual_inflation_rate, years
                )
                line_points.append(
                    ProjectionRangeLinePoint(
                        date=point.date,
                        label=point.label,
                        nominal_value=round_money(nominal_total),
                        real_value=round_money(real_total),
                    )
                )
                final_gross = gross
                final_tax = tax
                final_value = net

            final_real_value = final_value / target_deflator
            lines.append(
                ProjectionRangeLine(
                    asset_key=input_asset.asset_key,
                    asset_name=asset["name"],
                    case=case,
                    annual_return_assumption=annual_return,
                    projected_net_worth=line_points[-1].nominal_value,
                    real_projected_net_worth=line_points[-1].real_value,
                    points=line_points,
                )
            )
            if case == "worst":
                worst_gross, worst_tax, worst_value = final_gross, final_tax, final_value
                worst_real = final_real_value
                if asset["type"] == "other":
                    combined_worst += final_value - custom_current_net_by_key[
                        input_asset.asset_key
                    ]
                else:
                    combined_worst += final_value - selected_baseline_value(
                        asset, payload.target_date
                    )
            else:
                best_gross, best_tax, best_value = final_gross, final_tax, final_value
                best_real = final_real_value
                if asset["type"] == "other":
                    combined_best += final_value - custom_current_net_by_key[
                        input_asset.asset_key
                    ]
                else:
                    combined_best += final_value - selected_baseline_value(
                        asset, payload.target_date
                    )
        results.append(
            ProjectionRangeInvestmentResult(
                asset_key=input_asset.asset_key,
                asset_type=asset["type"],
                name=asset["name"],
                risk_tier=asset["risk_tier"],
                annual_return_volatility_assumption=asset["volatility"],
                current_value=round_money(asset["current_value"]),
                contribution_percentage=input_asset.contribution_percentage,
                monthly_contribution=round_money(asset["monthly_contribution"]),
                contribution_principal=round_money(target_contribution_principal),
                worst_annual_return=input_asset.worst_annual_return,
                best_annual_return=input_asset.best_annual_return,
                estimated_tax_rate=asset["tax_rate"],
                worst_projected_gross_value=round_money(worst_gross),
                best_projected_gross_value=round_money(best_gross),
                worst_estimated_tax=round_money(worst_tax),
                best_estimated_tax=round_money(best_tax),
                worst_projected_value=round_money(worst_value),
                best_projected_value=round_money(best_value),
                worst_real_projected_value=round_money(worst_real),
                best_real_projected_value=round_money(best_real),
            )
        )

    risk_values = {tier: ZERO for tier in ("X", "Y", "Z")}
    scoped_holdings = [
        holding
        for holding in snapshot["holdings"]
        if payload.scope_account_id is None
        or holding.account_id == payload.scope_account_id
    ]
    for holding in scoped_holdings:
        risk_values[holding.risk_tier] += holding.market_value
    current_invested_value = sum(risk_values.values(), ZERO)
    risk_scores = {"X": Decimal("1"), "Y": Decimal("2"), "Z": Decimal("3")}
    risk_mix = {
        tier: (
            (risk_values[tier] / current_invested_value).quantize(Decimal("0.0001"))
            if current_invested_value > ZERO
            else ZERO
        )
        for tier in ("X", "Y", "Z")
    }
    weighted_risk_score = (
        sum(
            (risk_values[tier] * risk_scores[tier] for tier in ("X", "Y", "Z")),
            ZERO,
        )
        / current_invested_value
        if current_invested_value > ZERO
        else None
    )
    selected_stock_contribution_weight = sum(
        (
            asset["input"].contribution_percentage
            for asset in assets
            if asset["type"] == "holding"
        ),
        ZERO,
    )
    contribution_risk_score = (
        sum(
            (
                asset["input"].contribution_percentage
                * risk_scores[asset["risk_tier"]]
                for asset in assets
                if asset["type"] == "holding"
            ),
            ZERO,
        )
        / selected_stock_contribution_weight
        if selected_stock_contribution_weight > ZERO
        else ZERO
    )
    scope_name = (
        scope_account.display_name if scope_account is not None else "All tracked accounts"
    )
    return PortfolioProjectionRangeResponse(
        baseline=baseline,
        scenario_baseline_timeline=scenario_baseline_timeline,
        scenario_current_net_worth=round_money(scenario_current_value),
        baseline_projected_net_worth=round_money(baseline_with_custom_nominal),
        baseline_real_projected_net_worth=round_money(baseline_with_custom_real),
        worst_case_projected_net_worth=round_money(combined_worst),
        best_case_projected_net_worth=round_money(combined_best),
        worst_case_real_projected_net_worth=round_money(combined_worst / target_deflator),
        best_case_real_projected_net_worth=round_money(combined_best / target_deflator),
        monthly_contribution=round_money(monthly_contribution),
        scope_account_id=payload.scope_account_id,
        include_taxes=payload.include_taxes,
        annual_inflation_rate=payload.annual_inflation_rate,
        risk_summary=ProjectionScenarioRiskSummary(
            scope_account_id=payload.scope_account_id,
            scope_account_name=scope_name,
            current_invested_value=round_money(current_invested_value),
            risk_mix=risk_mix,
            weighted_risk_score=(
                weighted_risk_score.quantize(Decimal("0.01"))
                if weighted_risk_score is not None
                else None
            ),
            contribution_weighted_risk_score=contribution_risk_score.quantize(
                Decimal("0.01")
            ),
            methodology=(
                "Current risk is the value-weighted mix of the app's qualitative X/Y/Z "
                "holding tiers; deposits and custom investments are not included. It is not "
                "measured volatility or a probability of loss."
            ),
        ),
        investments=results,
        lines=lines,
        assumptions=[
            (
                "Each investment's best and worst lines change only that investment while "
                "holding the rest of the portfolio at its baseline assumptions. The summary "
                "best/worst totals apply every selected investment's corresponding case at once."
            ),
            (
                "Monthly contributions are paid at month-end and use each selected investment's "
                "own annual return assumption. Contribution weights must total 100% when a "
                "monthly amount is entered."
            ),
            (
                "Existing stocks/ETFs use the selected annual return compounded from today's "
                "gross value. Fixed deposits accrue only through maturity; future contributions "
                "made after maturity are held as flat cash. FX is held at today's rate."
            ),
            (
                "With tax enabled, stock/ETF gains use the current estimated sale-tax rate; "
                "deposit and savings interest use the account-country rule when available or "
                "the labeled 10% legacy estimate; custom investments use the tax rate you enter. "
                "Tax is calculated at each displayed date on gains above cost basis plus "
                "contribution principal. Losses do not receive a tax credit."
            ),
            (
                "The annual inflation assumption is held constant for the selected period. "
                "Real values equal nominal values divided by (1 + inflation)^(elapsed days / 365)."
            ),
            (
                "Default stock/ETF return ranges are the saved expected return plus or minus "
                "the app's asset-class volatility assumption; deposit ranges start at the "
                "contract rate plus or minus the cash-deposit assumption. Edit both cases. "
                "These are sensitivity bands, not confidence intervals or predictions."
            ),
            (
                "Custom investments are projection-only inputs and are not saved to your "
                "holdings or account balances. Country-specific annual social contributions "
                "and future tax-law changes are excluded."
            ),
        ],
        warnings=list(dict.fromkeys(warnings)),
    )


def list_cash_flows(session: Session, user_id: uuid.UUID, months: int = 12) -> list[FlowResponse]:
    user = _get_user(session, user_id)
    _post_due_cash_flow_schedules(session, user.id)
    _post_due_savings_interest(session, user.id)
    return _project_cash_flows(
        session, user.id, user.base_currency, user.usd_per_eur, _fx_matrix(session, user), months
    )


def preview_recommendation(
    session: Session, user_id: uuid.UUID, request: RecommendationRequest
) -> RecommendationResponse:
    user = _get_user(session, user_id)
    policy = _get_policy(session, user.id)
    if policy.funding_rule is None:
        raise HTTPException(
            status_code=409,
            detail="Choose a goal-funding rule and asset-class targets in Goals & plan first.",
        )
    fx = user.usd_per_eur
    fx_rates = _fx_matrix(session, user)
    now = datetime.now(UTC)
    base_currency = user.base_currency
    input_base = _to_base(request.amount, request.currency, base_currency, fx, fx_rates)
    available_cash_base = dashboard(session, user.id, base_currency)["totals"]["available_cash"]
    reserve_base = _to_base(
        policy.emergency_reserve, user.base_currency, base_currency, fx, fx_rates
    )
    reserve_top_up = min(input_base, max(ZERO, reserve_base - available_cash_base))
    deployable = max(ZERO, input_base - reserve_top_up)

    goals = list(
        session.scalars(
            select(Goal)
            .where(Goal.user_id == user.id, Goal.is_active.is_(True))
            .order_by(Goal.name, Goal.id)
        )
    )
    plan = get_financial_plan(session, user.id)
    convert = _planning_convert(session, user)
    planned = {
        goal: sum((
            convert(point.nominal_contribution, goal.target_currency, base_currency)
            for point in contribution_months(
                plan, _goal_rules(goal), goal.monthly_contribution,
                goal.target_currency, date.today(), 12, convert,
            )
        ), ZERO) / Decimal(12)
        for goal in goals
    }
    try:
        goal_amounts = route_funding_to_goals(
            deployable, goals, policy.funding_rule, date.today(), planned
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    rounded_goal_amounts = round_allocations(goal_amounts)

    goal_allocations = [
        GoalAllocation(
            goal_id=goal.id,
            goal_name=goal.name,
            amount=amount,
            percentage=(amount * Decimal(100) / deployable if deployable else ZERO).quantize(
                Decimal("0.01")
            ),
            rationale=(
                f"{round_money(planned[goal])} {base_currency.value}/month planned "
                "(average of the next 12 scheduled months)"
            ),
        )
        for goal, amount in rounded_goal_amounts.items()
    ]
    near_term_goal_amount = ZERO
    warnings: list[str] = []
    for goal, amount in rounded_goal_amounts.items():
        days_to_goal = (
            (goal.target_date - date.today()).days if goal.target_date is not None else None
        )
        is_short_horizon_purchase = (
            goal.goal_type == GoalType.PURCHASE and days_to_goal is not None and days_to_goal <= 730
        )
        if goal.goal_type in {GoalType.PRESERVATION, GoalType.DEBT_REPAYMENT} or (
            is_short_horizon_purchase
        ):
            near_term_goal_amount += amount
        if days_to_goal is not None and days_to_goal < 1095 and goal.risk_level == RiskLevel.HIGH:
            warnings.append(
                f"{goal.name} has a short deadline for its selected high-risk profile; "
                "review suitability."
            )

    investable = max(ZERO, deployable - near_term_goal_amount)
    holding_rows = session.execute(
        select(Holding, Instrument)
        .join(Instrument, Instrument.id == Holding.instrument_id)
        .where(Holding.user_id == user.id)
    ).all()
    latest_quotes: dict[uuid.UUID, MarketPriceCache] = {}
    for quote in session.scalars(
        select(MarketPriceCache).order_by(MarketPriceCache.observed_at.desc())
    ):
        latest_quotes.setdefault(quote.instrument_id, quote)
    current_values = {asset_class.value: ZERO for asset_class in AssetClass}
    for holding, instrument in holding_rows:
        quote = latest_quotes.get(instrument.id)
        if quote is None:
            continue
        native_value = holding.quantity * quote.price
        current_values[instrument.asset_class.value] += _to_base(
            native_value, quote.currency, base_currency, fx, fx_rates
        )

    target_weights = _target_weights(policy)
    try:
        asset_amounts = rebalance_with_contribution(current_values, target_weights, investable)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    pre_contribution_total = sum(current_values.values(), ZERO)
    post_total = pre_contribution_total + investable
    rounded_asset_amounts = round_allocations(asset_amounts)
    asset_allocations = []
    for asset_class in AssetClass:
        key = asset_class.value
        amount = rounded_asset_amounts.get(key, ZERO)
        post_weight = (current_values[key] + amount) / post_total if post_total else ZERO
        current_weight = (
            current_values[key] / pre_contribution_total if pre_contribution_total else ZERO
        )
        rationale = (
            "Below target; fresh cash moves the portfolio toward policy."
            if current_weight < target_weights[key]
            else "At or above target; buy-only allocation limits further drift."
        )
        asset_allocations.append(
            BucketAllocation(
                asset_class=asset_class,
                amount=amount,
                target_weight=target_weights[key],
                current_value=round_money(current_values[key]),
                post_contribution_weight=(post_weight * Decimal(100)).quantize(Decimal("0.01")),
                rationale=rationale,
            )
        )

    passive_goals = [goal for goal in goals if goal.goal_type == GoalType.PASSIVE_INCOME]
    passive_income_target = max(
        (
            _to_base(
                goal.target_annual_income or ZERO,
                goal.target_currency,
                base_currency,
                fx,
                fx_rates,
            )
            for goal in passive_goals
        ),
        default=ZERO,
    )
    estimated_current_income = dashboard(session, user.id, base_currency)["totals"][
        "estimated_monthly_income"
    ] * Decimal(12)
    passive_income_gap = max(ZERO, passive_income_target - estimated_current_income)
    if passive_income_gap:
        warnings.append(
            "Passive-income goal remains a separate objective; allocation weights are not "
            "optimized for yield."
        )
    if not goals:
        warnings.append("Create at least one goal to receive goal-specific funding breakdowns.")
    warnings.extend(
        [
            (
                "This is a deterministic, buy-only preview using sample marks; "
                "it is not investment advice or an order."
            ),
            ("Goal progress values are illustrative and are not linked to specific holdings."),
        ]
    )

    snapshot = {
        "reserve_top_up": str(round_money(reserve_top_up)),
        "deployable_amount": str(round_money(deployable)),
        "near_term_goal_amount": str(round_money(near_term_goal_amount)),
        "investable_amount": str(round_money(investable)),
        "target_weights": {key: str(value) for key, value in target_weights.items()},
        "goal_allocations": [
            {"goal_id": str(line.goal_id), "amount": str(line.amount)} for line in goal_allocations
        ],
        "asset_allocations": [
            {"asset_class": line.asset_class.value, "amount": str(line.amount)}
            for line in asset_allocations
        ],
    }
    recommendation = Recommendation(
        user_id=user.id,
        input_amount=request.amount,
        input_currency=request.currency,
        base_currency=base_currency,
        funding_rule=policy.funding_rule,
        result_snapshot=snapshot,
        created_at=now,
    )
    session.add(recommendation)
    session.commit()
    session.refresh(recommendation)

    return RecommendationResponse(
        id=recommendation.id,
        status="PREVIEW_ONLY",
        input_amount=request.amount,
        input_currency=request.currency,
        base_currency=base_currency,
        funding_rule=policy.funding_rule,
        reserve_top_up=round_money(reserve_top_up),
        deployable_amount=round_money(deployable),
        retained_for_near_term_goals=round_money(near_term_goal_amount),
        investable_amount=round_money(investable),
        passive_income_gap=round_money(passive_income_gap),
        goal_allocations=goal_allocations,
        asset_allocations=asset_allocations,
        warnings=warnings,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        explanation=(
            "Cash is reserved first, then divided using your selected goal rule. "
            "Only the remaining amount is routed toward portfolio target weights. "
            "Near-term purchases, debt repayment, and capital-preservation goals are kept out "
            "of the investment allocation."
        ),
    )
