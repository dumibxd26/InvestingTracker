from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.calculations import (
    compound_growth_factor,
    fixed_deposit_value,
    generate_vesting_schedule,
    goal_progress,
    rebalance_with_contribution,
    round_money,
    route_funding_to_goals,
)
from app.cash_flow_logic import add_months, occurrence_dates
from app.config import get_settings
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
    CashFlow,
    CashFlowSchedule,
    CompoundingFrequency,
    Currency,
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
    TrancheStatus,
    User,
    ValuationSnapshot,
    VestingGrant,
    VestingTranche,
)
from app.schemas import (
    AccountCreate,
    AccountSubaccountCreate,
    AccountSubaccountSummary,
    AccountSummary,
    AccountWealthSummary,
    AllocationSummary,
    AuthResponse,
    BucketAllocation,
    CashFlowScheduleCreate,
    CashFlowScheduleResponse,
    CashReceiptCreate,
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
    PortfolioProjectionResponse,
    ProfileUpdate,
    ProjectionAccountValue,
    ProjectionPoint,
    RecommendationRequest,
    RecommendationResponse,
    RegisterRequest,
    UserProfileResponse,
    VestingGrantCreate,
    VestingSummary,
    VestingTrancheSummary,
)
from app.security import create_access_token, digest_access_token, hash_password, verify_password

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")


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
    if account.account_type not in {AccountType.BROKERAGE, AccountType.EMPLOYER_PLAN}:
        raise HTTPException(
            status_code=422,
            detail="Stocks and ETFs can only be added to brokerage or employer-plan accounts",
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
    return UserProfileResponse(
        id=user.id,
        username=user.username or "",
        display_name=user.display_name,
        base_currency=user.base_currency,
        usd_per_eur=user.usd_per_eur,
    )


def get_policy_response(session: Session, user_id: uuid.UUID) -> PolicyResponse:
    user = _get_user(session, user_id)
    policy = _get_policy(session, user.id)
    return PolicyResponse(
        funding_rule=policy.funding_rule,
        emergency_reserve=policy.emergency_reserve,
        target_weights=_target_weights(policy),
    )


def list_accounts(session: Session, user_id: uuid.UUID) -> list[AccountSummary]:
    user = _get_user(session, user_id)
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
            currency=(subaccounts_by_account[account.id][0].currency),
            cash_balance=(subaccounts_by_account[account.id][0].cash_balance),
            position_count=position_counts.get(account.id, 0),
            is_sample=account.provider_code == "SAMPLE",
            subaccounts=[
                AccountSubaccountSummary(
                    id=subaccount.id,
                    currency=subaccount.currency,
                    cash_balance=subaccount.cash_balance,
                    is_primary=subaccount.is_primary,
                )
                for subaccount in subaccounts_by_account[account.id]
            ],
        )
        for account in accounts
    ]


def create_account(session: Session, user_id: uuid.UUID, payload: AccountCreate) -> AccountSummary:
    user = _get_user(session, user_id)
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
    )
    session.add(account)
    try:
        session.flush()
        primary_subaccount = AccountSubaccount(
            account_id=account.id,
            currency=payload.currency,
            cash_balance=payload.opening_cash,
            is_primary=True,
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
        currency=primary_subaccount.currency,
        cash_balance=primary_subaccount.cash_balance,
        position_count=0,
        is_sample=False,
        subaccounts=[
            AccountSubaccountSummary(
                id=primary_subaccount.id,
                currency=primary_subaccount.currency,
                cash_balance=primary_subaccount.cash_balance,
                is_primary=True,
            )
        ],
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
    subaccount = AccountSubaccount(
        account_id=account.id,
        currency=payload.currency,
        cash_balance=payload.opening_balance,
        is_primary=False,
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
    return AccountSubaccountSummary(
        id=subaccount.id,
        currency=subaccount.currency,
        cash_balance=subaccount.cash_balance,
        is_primary=subaccount.is_primary,
    )


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
            .order_by(Goal.priority, Goal.name)
        )
    )
    return [_goal_response(session, goal) for goal in goals]


def _goal_response(session: Session, goal: Goal) -> GoalResponse:
    values = {column.key: getattr(goal, column.key) for column in Goal.__table__.columns}
    values.update(
        linked_account_ids=list(
            session.scalars(
                select(GoalAccountLink.account_id).where(GoalAccountLink.goal_id == goal.id)
            )
        ),
        holding_ids=list(
            session.scalars(
                select(GoalHoldingAllocation.holding_id).where(
                    GoalHoldingAllocation.goal_id == goal.id
                )
            )
        ),
        fixed_deposit_ids=list(
            session.scalars(
                select(GoalDepositAllocation.fixed_deposit_id).where(
                    GoalDepositAllocation.goal_id == goal.id
                )
            )
        ),
    )
    return GoalResponse.model_validate(values)


def _replace_goal_sources(
    session: Session,
    user_id: uuid.UUID,
    goal_id: uuid.UUID,
    linked_account_ids: list[uuid.UUID],
    holding_ids: list[uuid.UUID],
    fixed_deposit_ids: list[uuid.UUID],
) -> None:
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
        conflicting_holding = session.scalar(
            select(GoalHoldingAllocation)
            .where(
                GoalHoldingAllocation.holding_id.in_(holding_ids),
                GoalHoldingAllocation.goal_id != goal_id,
            )
            .limit(1)
        )
        if conflicting_holding is not None:
            raise HTTPException(
                status_code=409,
                detail="A stock or ETF can only be assigned to one goal at a time.",
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
        conflicting_deposit = session.scalar(
            select(GoalDepositAllocation)
            .where(
                GoalDepositAllocation.fixed_deposit_id.in_(fixed_deposit_ids),
                GoalDepositAllocation.goal_id != goal_id,
            )
            .limit(1)
        )
        if conflicting_deposit is not None:
            raise HTTPException(
                status_code=409,
                detail="A fixed deposit can only be assigned to one goal at a time.",
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
            GoalHoldingAllocation(user_id=user_id, goal_id=goal_id, holding_id=holding_id)
            for holding_id in holding_ids
        ]
    )
    session.add_all(
        [
            GoalDepositAllocation(
                user_id=user_id,
                goal_id=goal_id,
                fixed_deposit_id=deposit_id,
            )
            for deposit_id in fixed_deposit_ids
        ]
    )


def create_goal(session: Session, user_id: uuid.UUID, payload: GoalCreate) -> GoalResponse:
    user = _get_user(session, user_id)
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
        exclude={"linked_account_ids", "holding_ids", "fixed_deposit_ids"}
    )
    goal = Goal(user_id=user.id, **goal_values)
    session.add(goal)
    session.flush()
    _replace_goal_sources(
        session,
        user.id,
        goal.id,
        payload.linked_account_ids,
        payload.holding_ids,
        payload.fixed_deposit_ids,
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
        exclude={"linked_account_ids", "holding_ids", "fixed_deposit_ids"}
    )
    for field, value in goal_values.items():
        setattr(goal, field, value)
    _replace_goal_sources(
        session,
        user.id,
        goal.id,
        payload.linked_account_ids,
        payload.holding_ids,
        payload.fixed_deposit_ids,
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
    warnings: list[str] = []
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
        taxable_gain = max(
            ZERO,
            native_value - holding.quantity * holding.average_cost,
        )
        sale_tax_rate = Decimal("0.03")
        sale_tax = _to_base(
            taxable_gain * sale_tax_rate,
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
                symbol=instrument.symbol,
                name=instrument.name,
                account_name=account.display_name,
                exchange=instrument.exchange,
                mic_code=instrument.mic,
                asset_class=instrument.asset_class,
                instrument_type=instrument.instrument_type,
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
                name=deposit.name,
                principal=deposit.principal,
                accrued_interest=accrued_interest,
                current_value=accrued_value,
                currency=deposit.currency,
                annual_rate=deposit.annual_rate,
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
            .order_by(Goal.priority, Goal.name)
        )
    )
    linked_accounts_by_goal: dict[uuid.UUID, list[uuid.UUID]] = {}
    for goal_id, account_id in session.execute(
        select(GoalAccountLink.goal_id, GoalAccountLink.account_id)
        .join(Goal, Goal.id == GoalAccountLink.goal_id)
        .where(GoalAccountLink.user_id == user.id, Goal.is_active.is_(True))
        .order_by(GoalAccountLink.account_id)
    ):
        linked_accounts_by_goal.setdefault(goal_id, []).append(account_id)
    linked_holdings_by_goal: dict[uuid.UUID, list[uuid.UUID]] = {}
    for goal_id, holding_id in session.execute(
        select(GoalHoldingAllocation.goal_id, GoalHoldingAllocation.holding_id)
        .join(Goal, Goal.id == GoalHoldingAllocation.goal_id)
        .where(GoalHoldingAllocation.user_id == user.id, Goal.is_active.is_(True))
        .order_by(GoalHoldingAllocation.holding_id)
    ):
        linked_holdings_by_goal.setdefault(goal_id, []).append(holding_id)
    linked_deposits_by_goal: dict[uuid.UUID, list[uuid.UUID]] = {}
    for goal_id, deposit_id in session.execute(
        select(GoalDepositAllocation.goal_id, GoalDepositAllocation.fixed_deposit_id)
        .join(Goal, Goal.id == GoalDepositAllocation.goal_id)
        .where(GoalDepositAllocation.user_id == user.id, Goal.is_active.is_(True))
        .order_by(GoalDepositAllocation.fixed_deposit_id)
    ):
        linked_deposits_by_goal.setdefault(goal_id, []).append(deposit_id)
    for goal in goal_rows:
        manual_current_amount = _to_base(
            goal.current_amount, goal.target_currency, base_currency, usd_per_eur, fx_rates
        )
        goal_holding_ids = linked_holdings_by_goal.get(goal.id, [])
        goal_deposit_ids = linked_deposits_by_goal.get(goal.id, [])
        linked_asset_value = sum(
            (holding_values_by_id.get(holding_id, ZERO) for holding_id in goal_holding_ids),
            ZERO,
        ) + sum(
            (deposit_values_by_id.get(deposit_id, ZERO) for deposit_id in goal_deposit_ids),
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
                priority=goal.priority,
                risk_level=goal.risk_level,
                monthly_contribution=goal.monthly_contribution,
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

    snapshot = dashboard(session, user.id, requested_currency)
    base_currency = snapshot["base_currency"]
    usd_per_eur = user.usd_per_eur
    fx_rates = _fx_matrix(session, user)
    current_accounts = snapshot["account_wealth"]
    holdings = snapshot["holdings"]
    deposits = list(session.scalars(select(FixedDeposit).where(FixedDeposit.user_id == user.id)))

    def project_at(projection_date: date) -> list[ProjectionAccountValue]:
        years = Decimal((projection_date - today).days) / Decimal(365)
        cash_by_account = {
            account.id: account.cash_value for account in current_accounts
        }
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
            future_tax = max(ZERO, future_gross_base - cost_basis_base) * Decimal("0.03")
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
            deposit_by_account[deposit.account_id] = (
                deposit_by_account.get(deposit.account_id, ZERO)
                + _to_base(
                    value_at_accrual_date,
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
            result.append(
                ProjectionAccountValue(
                    account_id=account.id,
                    account_name=account.display_name,
                    current_value=account.total_after_tax_value,
                    projected_cash_value=round_money(projected_cash),
                    projected_holdings_value=round_money(projected_holdings),
                    projected_deposit_value=round_money(projected_deposits),
                    projected_total_value=round_money(
                        projected_cash + projected_holdings + projected_deposits
                    ),
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
            )
        )

    projected_accounts = timeline[-1].accounts
    projected_total = sum(
        (account.projected_total_value for account in projected_accounts),
        ZERO,
    )
    return PortfolioProjectionResponse(
        base_currency=base_currency,
        as_of=datetime.now(UTC),
        target_date=target_date,
        current_net_worth=snapshot["totals"]["net_worth"],
        projected_net_worth=round_money(projected_total),
        estimated_change=round_money(projected_total - snapshot["totals"]["net_worth"]),
        accounts=projected_accounts,
        timeline=timeline,
        warnings=[
            (
                "Illustrative deterministic scenario, not a prediction or guarantee. "
                "Annual returns are user-editable and not inferred from historical volatility. "
                "Existing positions start at a 5% nominal assumption."
            ),
            (
                "Stock/ETF assumptions are nominal total returns (including reinvested dividends) "
                "in listing currency. Current FX rates are held constant."
            ),
            (
                "The model applies the current 3% estimate to positive projected holding gains. "
                "Cash stays flat; deposits accrue to maturity and are not reinvested."
            ),
            (
                "Unvested awards, future cash-flow forecasts, and additional contributions "
                "are excluded."
            ),
            (
                "Risk tiers are qualitative placeholders: ETFs default to X and individual "
                "stocks to Y. No return distribution, volatility, or probability of loss is "
                "calculated."
            ),
        ],
    )


def list_cash_flows(session: Session, user_id: uuid.UUID, months: int = 12) -> list[FlowResponse]:
    user = _get_user(session, user_id)
    _post_due_cash_flow_schedules(session, user.id)
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
            .order_by(Goal.priority, Goal.name)
        )
    )
    try:
        goal_amounts = route_funding_to_goals(deployable, goals, policy.funding_rule, date.today())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    rounded_goal_amounts = {goal: round_money(amount) for goal, amount in goal_amounts.items()}
    goal_residual = round_money(deployable) - sum(rounded_goal_amounts.values(), ZERO)
    if rounded_goal_amounts:
        highest_priority_goal = min(
            rounded_goal_amounts, key=lambda item: (item.priority, item.name)
        )
        rounded_goal_amounts[highest_priority_goal] += goal_residual

    goal_allocations = [
        GoalAllocation(
            goal_id=goal.id,
            goal_name=goal.name,
            amount=amount,
            percentage=(amount * Decimal(100) / deployable if deployable else ZERO).quantize(
                Decimal("0.01")
            ),
            rationale=(
                f"Priority {goal.priority}; "
                f"{goal.monthly_contribution} {goal.target_currency.value}/month planned"
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
    rounded_asset_amounts = {key: round_money(amount) for key, amount in asset_amounts.items()}
    asset_residual = round_money(investable) - sum(rounded_asset_amounts.values(), ZERO)
    if rounded_asset_amounts:
        largest_allocation = max(rounded_asset_amounts, key=rounded_asset_amounts.get)
        rounded_asset_amounts[largest_allocation] += asset_residual
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
