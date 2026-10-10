from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.calculations import (
    fixed_deposit_value,
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
    TwelveDataClient,
)
from app.models import (
    AccountType,
    AllocationPolicy,
    AssetClass,
    BrokerAccount,
    CashFlow,
    CashFlowSchedule,
    Currency,
    FixedDeposit,
    FlowDirection,
    FlowKind,
    FlowStatus,
    FundingRule,
    Goal,
    GoalType,
    Holding,
    Instrument,
    LoginSession,
    MarketFXRate,
    MarketPriceCache,
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
    AccountSummary,
    AllocationSummary,
    AuthResponse,
    BucketAllocation,
    CashFlowScheduleCreate,
    CashFlowScheduleResponse,
    CashReceiptCreate,
    ChartPoint,
    DepositSummary,
    FixedSharesUpdate,
    FlowResponse,
    GoalAllocation,
    GoalCreate,
    GoalResponse,
    GoalSummary,
    HoldingCreate,
    HoldingCreateResponse,
    HoldingSummary,
    HoldingUpdate,
    LoginRequest,
    MarketDataStatusResponse,
    MarketFXRateSummary,
    MarketRefreshResponse,
    MarketSymbolSearchResult,
    PolicyResponse,
    PolicyUpdate,
    ProfileUpdate,
    RecommendationRequest,
    RecommendationResponse,
    RegisterRequest,
    UserProfileResponse,
    VestingSummary,
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
    if not _can_convert(quote.currency, user.base_currency, fx_rates, user.usd_per_eur):
        try:
            fx_quote = await client.exchange_rate(
                f"{quote.currency.value}/{user.base_currency.value}"
            )
        except MarketDataProviderError as error:
            _raise_provider_error(error)
        _save_market_fx_quote(session, fx_quote)

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
            instrument_id=instrument.id,
            quantity=payload.quantity,
            average_cost=payload.average_cost,
        )
        session.add(holding)
        total_quantity = payload.quantity
    else:
        total_quantity = holding.quantity + payload.quantity
        holding.average_cost = (
            holding.quantity * holding.average_cost + payload.quantity * payload.average_cost
        ) / total_quantity
        holding.quantity = total_quantity

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
    )


def update_holding(
    session: Session, user_id: uuid.UUID, holding_id: uuid.UUID, payload: HoldingUpdate
) -> None:
    _get_user(session, user_id)
    holding = session.scalar(
        select(Holding)
        .where(Holding.id == holding_id, Holding.user_id == user_id)
        .with_for_update()
    )
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding was not found")
    holding.quantity = payload.quantity
    holding.average_cost = payload.average_cost
    session.commit()


def delete_holding(session: Session, user_id: uuid.UUID, holding_id: uuid.UUID) -> None:
    _get_user(session, user_id)
    holding = session.scalar(
        select(Holding)
        .where(Holding.id == holding_id, Holding.user_id == user_id)
        .with_for_update()
    )
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding was not found")
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
    instruments = list(
        session.scalars(
            select(Instrument)
            .join(Holding, Holding.instrument_id == Instrument.id)
            .where(Holding.user_id == user.id)
            .distinct()
            .order_by(Instrument.symbol)
        )
    )
    if len(instruments) > settings.market_data_max_symbols:
        raise HTTPException(
            status_code=413,
            detail=(
                f"This profile has {len(instruments)} different holdings; "
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
        detail = errors[0] if errors else "No held symbols or supported FX pairs were refreshed."
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
    return [
        AccountSummary(
            id=account.id,
            display_name=account.display_name,
            provider_code=account.provider_code,
            account_type=account.account_type,
            currency=account.currency,
            cash_balance=account.cash_balance,
            position_count=position_counts.get(account.id, 0),
            is_sample=account.provider_code == "SAMPLE",
        )
        for account in accounts
    ]


def create_account(session: Session, user_id: uuid.UUID, payload: AccountCreate) -> AccountSummary:
    user = _get_user(session, user_id)
    if not _can_convert(
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
        currency=payload.currency,
        cash_balance=payload.opening_cash,
    )
    session.add(account)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account with that name already exists in this profile",
        ) from error
    session.refresh(account)
    return AccountSummary(
        id=account.id,
        display_name=account.display_name,
        provider_code=account.provider_code,
        account_type=account.account_type,
        currency=account.currency,
        cash_balance=account.cash_balance,
        position_count=0,
        is_sample=False,
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
    session.delete(account)
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
        select(BrokerAccount.currency).where(BrokerAccount.user_id == user_id),
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


def create_cash_flow_schedule(
    session: Session, user_id: uuid.UUID, payload: CashFlowScheduleCreate
) -> CashFlowScheduleResponse:
    user = _get_user(session, user_id)
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
    if not _can_convert(
        account.currency, user.base_currency, _fx_matrix(session, user), user.usd_per_eur
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
        label=f"Extra cash · {payload.source}",
        kind=FlowKind.WINDFALL,
        status=FlowStatus.CONFIRMED,
        amount=payload.amount,
        currency=account.currency,
        expected_date=payload.received_date,
        occurred_at=occurred_at,
        source_system="USER_ENTRY",
        source_event_id=event_id,
    )
    account.cash_balance += payload.amount
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
            )
        )

    schedules = session.scalars(
        select(CashFlowSchedule).where(
            CashFlowSchedule.user_id == user_id,
            CashFlowSchedule.is_active.is_(True),
        )
    )
    for schedule in schedules:
        for occurrence in occurrence_dates(
            schedule.recurrence,
            schedule.start_date,
            schedule.end_date,
            today,
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
    goals = session.scalars(
        select(Goal).where(Goal.user_id == user.id).order_by(Goal.priority, Goal.name)
    )
    return [GoalResponse.model_validate(goal) for goal in goals]


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
    goal = Goal(user_id=user.id, **payload.model_dump())
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return GoalResponse.model_validate(goal)


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
        select(Holding, Instrument, BrokerAccount)
        .join(Instrument, Instrument.id == Holding.instrument_id)
        .join(BrokerAccount, BrokerAccount.id == Holding.account_id)
        .where(Holding.user_id == user.id)
    ).all()

    holdings: list[HoldingSummary] = []
    values_by_class = {asset_class.value: ZERO for asset_class in AssetClass}
    position_counts: dict[uuid.UUID, int] = {}
    annual_dividend_income = ZERO
    unrealized_pnl = ZERO
    sample_data = bool(holding_rows) and all(
        instrument.is_demo for _, instrument, _ in holding_rows
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
    for holding, instrument, account in holding_rows:
        position_counts[account.id] = position_counts.get(account.id, 0) + 1
        quote = latest_quotes.get(instrument.id)
        if quote is None:
            warnings.append(
                f"{instrument.symbol} has no quote and is excluded from portfolio totals."
            )
            sample_data = False
            continue
        native_value = holding.quantity * quote.price
        current_value = _to_base(native_value, quote.currency, base_currency, usd_per_eur, fx_rates)
        cost_value = _to_base(
            holding.quantity * holding.average_cost,
            instrument.currency,
            base_currency,
            usd_per_eur,
            fx_rates,
        )
        unrealized_pnl += current_value - cost_value
        values_by_class[instrument.asset_class.value] += current_value
        annual_dividend_income += _to_base(
            native_value * instrument.estimated_annual_yield,
            quote.currency,
            base_currency,
            usd_per_eur,
            fx_rates,
        )
        change_percent = (
            (quote.price - holding.average_cost) * Decimal(100) / holding.average_cost
            if holding.average_cost
            else ZERO
        )
        holdings.append(
            HoldingSummary(
                id=holding.id,
                symbol=instrument.symbol,
                name=instrument.name,
                account_name=account.display_name,
                asset_class=instrument.asset_class,
                instrument_type=instrument.instrument_type,
                quantity=holding.quantity,
                average_cost=holding.average_cost,
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
                base_currency=base_currency,
                change_percent=change_percent.quantize(Decimal("0.01")),
                is_demo=instrument.is_demo,
            )
        )

    accounts = list(session.scalars(select(BrokerAccount).where(BrokerAccount.user_id == user.id)))
    account_summaries = [
        AccountSummary(
            id=account.id,
            display_name=account.display_name,
            provider_code=account.provider_code,
            account_type=account.account_type,
            currency=account.currency,
            cash_balance=account.cash_balance,
            position_count=position_counts.get(account.id, 0),
            is_sample=account.provider_code == "SAMPLE",
        )
        for account in accounts
    ]
    available_cash = sum(
        (
            _to_base(account.cash_balance, account.currency, base_currency, usd_per_eur, fx_rates)
            for account in accounts
            if account.account_type
            in {AccountType.BROKERAGE, AccountType.BANK, AccountType.SAVINGS}
        ),
        ZERO,
    )

    deposits: list[DepositSummary] = []
    deposit_value = ZERO
    annual_interest_income = ZERO
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
        deposit_value += _to_base(
            accrued_value, deposit.currency, base_currency, usd_per_eur, fx_rates
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
                name=deposit.name,
                principal=deposit.principal,
                accrued_interest=accrued_interest,
                currency=deposit.currency,
                annual_rate=deposit.annual_rate,
                rate_basis=deposit.rate_basis,
                maturity_date=deposit.maturity_date,
                days_to_maturity=max((deposit.maturity_date - today).days, 0),
            )
        )

    grants = list(session.scalars(select(VestingGrant).where(VestingGrant.user_id == user.id)))
    vesting: list[VestingSummary] = []
    unvested_gross = ZERO
    unvested_net = ZERO
    for grant in grants:
        instrument = session.get(Instrument, grant.instrument_id)
        quote = latest_quotes.get(grant.instrument_id)
        if instrument is None or quote is None:
            continue
        grant_tranches = list(
            session.scalars(select(VestingTranche).where(VestingTranche.grant_id == grant.id))
        )
        future_tranches = [
            tranche
            for tranche in grant_tranches
            if tranche.available_date >= today and tranche.status == TrancheStatus.SCHEDULED
        ]
        vested_units = sum(
            (
                tranche.units
                for tranche in grant_tranches
                if tranche.status in {TrancheStatus.VESTED, TrancheStatus.RELEASED}
            ),
            ZERO,
        )
        units = sum((tranche.units for tranche in future_tranches), ZERO)
        if grant.grant_type.value == "option":
            intrinsic_value = units * max(quote.price - (grant.strike_price or ZERO), ZERO)
        else:
            intrinsic_value = units * quote.price
        gross = _to_base(intrinsic_value, quote.currency, base_currency, usd_per_eur, fx_rates)
        net = gross * (ONE - grant.tax_rate_assumption)
        unvested_gross += gross
        unvested_net += net
        vesting.append(
            VestingSummary(
                symbol=instrument.symbol,
                name=instrument.name,
                grant_type=grant.grant_type.value,
                units=units,
                vested_percent=(
                    min(Decimal(100), vested_units * Decimal(100) / grant.total_units)
                    if grant.total_units
                    else ZERO
                ),
                next_vest_date=min(
                    (tranche.vest_date for tranche in future_tranches), default=None
                ),
                gross_value=round_money(gross),
                estimated_net_value=round_money(net),
                currency=base_currency,
            )
        )

    total_invested = sum(values_by_class.values(), ZERO)
    net_worth = total_invested + available_cash + deposit_value + unvested_gross
    annual_income = annual_dividend_income + annual_interest_income
    goals: list[GoalSummary] = []
    goal_rows = list(
        session.scalars(
            select(Goal)
            .where(Goal.user_id == user.id, Goal.is_active.is_(True))
            .order_by(Goal.priority, Goal.name)
        )
    )
    for goal in goal_rows:
        current_amount = _to_base(
            goal.current_amount, goal.target_currency, base_currency, usd_per_eur, fx_rates
        )
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
                current_annual_income=current_annual_income,
                currency=base_currency,
                progress_percent=progress_percent.quantize(Decimal("0.01")),
                target_date=goal.target_date,
                priority=goal.priority,
                risk_level=goal.risk_level,
                monthly_contribution=goal.monthly_contribution,
                fixed_percent=goal.fixed_percent,
                flexibility=goal.flexibility,
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
            "unrealized_pnl_estimate": round_money(unrealized_pnl),
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


def list_cash_flows(session: Session, user_id: uuid.UUID, months: int = 12) -> list[FlowResponse]:
    user = _get_user(session, user_id)
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
