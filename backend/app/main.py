import json
from collections.abc import Generator
from datetime import UTC, date
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database import SessionFactory, get_session
from app.models import Currency, User
from app.schemas import (
    AccountCreate,
    AccountSubaccountCreate,
    AccountSubaccountSummary,
    AccountSummary,
    AuthResponse,
    CashFlowScheduleCreate,
    CashFlowScheduleResponse,
    CashReceiptCreate,
    CashTransferCreate,
    CashTransferResponse,
    ChatRequest,
    ChatResponse,
    DashboardResponse,
    FixedDepositCreate,
    FixedDepositCreateResponse,
    FixedSharesUpdate,
    FlowResponse,
    GoalCreate,
    GoalResponse,
    GoalUpdate,
    HoldingCreate,
    HoldingCreateResponse,
    HoldingUpdate,
    InitialPortfolioRequest,
    InitialPortfolioResponse,
    LoginRequest,
    MarketDataStatusResponse,
    MarketRefreshResponse,
    MarketSymbolSearchResponse,
    PolicyResponse,
    PolicyUpdate,
    PortfolioProjectionResponse,
    ProfileUpdate,
    RecommendationRequest,
    RecommendationResponse,
    RegisterRequest,
    StockPurchasePlanCreate,
    StockSaleCreate,
    StockSaleResponse,
    SubaccountInterestUpdate,
    UserProfileResponse,
    VestingGrantCreate,
)
from app.services import (
    archive_cash_flow_schedule,
    archive_goal,
    authenticate_token,
    create_account,
    create_account_subaccount,
    create_cash_flow_schedule,
    create_fixed_deposit,
    create_goal,
    create_holding,
    create_purchase_plan,
    create_vesting_grant,
    dashboard,
    delete_account,
    delete_fixed_deposit,
    delete_holding,
    delete_purchase_plan,
    delete_vesting_grant,
    get_policy_response,
    get_profile,
    initialize_portfolio,
    list_accounts,
    list_cash_flow_schedules,
    list_cash_flows,
    list_goals,
    login_user,
    logout_user,
    market_data_status,
    portfolio_projection,
    preview_recommendation,
    record_extra_cash,
    refresh_market_data,
    register_user,
    search_market_symbols,
    sell_holding,
    transfer_cash,
    update_fixed_shares,
    update_goal,
    update_holding,
    update_policy,
    update_profile,
    update_subaccount_interest,
)

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)
SYSTEM_PROMPT = (
    "You are a read-only assistant inside a personal wealth tracker. Explain the supplied "
    "portfolio snapshot and help users understand calculations. Use only the provided context; "
    "never invent prices, balances, tax rules, or returns. Do not place trades or tell the user "
    "to buy or sell a named security. You may explain an existing deterministic allocation "
    "preview, but must label it as illustrative and not investment advice. If the context is "
    "sample data, say so. State uncertainty and encourage the user to verify important "
    "financial or tax decisions with a qualified professional."
)


def create_app(
    session_factory: sessionmaker[Session] = SessionFactory,
) -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Local personal wealth tracking with username/password accounts. "
            "Broker connections are not enabled. Optional Twelve Data market quotes and FX "
            "are fetched only after explicit search or refresh requests."
        ),
    )
    app.state.session_factory = session_factory
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["DELETE", "GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Provider-API-Key"],
    )

    def session_dependency() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency

    def get_current_user(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
        session: Annotated[Session, Depends(get_session)],
    ) -> User:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=401,
                detail="Sign in to access your application account",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return authenticate_token(session, credentials.credentials)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "northstar-api"}

    @app.post("/api/auth/register", response_model=AuthResponse, status_code=201)
    def post_register(
        payload: RegisterRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> AuthResponse:
        return register_user(session, payload, settings.login_session_days)

    @app.post("/api/auth/login", response_model=AuthResponse)
    def post_login(
        payload: LoginRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> AuthResponse:
        return login_user(session, payload, settings.login_session_days)

    @app.post("/api/auth/logout", status_code=204)
    def post_logout(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> None:
        logout_user(
            session,
            current_user.id,
            credentials.credentials if credentials else None,
        )
        return None

    @app.get("/api/auth/me", response_model=UserProfileResponse)
    def get_current_profile(
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> UserProfileResponse:
        return get_profile(session, current_user.id)

    @app.get("/api/profile", response_model=UserProfileResponse)
    def get_profile_route(
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> UserProfileResponse:
        return get_profile(session, current_user.id)

    @app.put("/api/profile", response_model=UserProfileResponse)
    def put_profile_route(
        payload: ProfileUpdate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> UserProfileResponse:
        return update_profile(session, current_user.id, payload)

    @app.get("/api/dashboard", response_model=DashboardResponse)
    def get_dashboard(
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
        currency: Currency | None = None,
    ) -> dict:
        return dashboard(session, current_user.id, currency)

    @app.get("/api/projections/portfolio", response_model=PortfolioProjectionResponse)
    def get_portfolio_projection(
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
        target_date: date,
        currency: Currency | None = None,
    ) -> PortfolioProjectionResponse:
        return portfolio_projection(session, current_user.id, target_date, currency)

    @app.get("/api/accounts", response_model=list[AccountSummary])
    def get_accounts(
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[AccountSummary]:
        return list_accounts(session, current_user.id)

    @app.post(
        "/api/portfolio/initialize",
        response_model=InitialPortfolioResponse,
        status_code=201,
    )
    async def post_portfolio_initialize(
        payload: InitialPortfolioRequest,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> InitialPortfolioResponse:
        return await initialize_portfolio(session, current_user.id, payload)

    @app.post("/api/accounts", response_model=AccountSummary, status_code=201)
    def post_account(
        payload: AccountCreate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> AccountSummary:
        return create_account(session, current_user.id, payload)

    @app.post(
        "/api/accounts/{account_id}/subaccounts",
        response_model=AccountSubaccountSummary,
        status_code=201,
    )
    def post_account_subaccount(
        account_id: UUID,
        payload: AccountSubaccountCreate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> AccountSubaccountSummary:
        return create_account_subaccount(session, current_user.id, account_id, payload)

    @app.put(
        "/api/accounts/{account_id}/subaccounts/{subaccount_id}/interest",
        response_model=AccountSubaccountSummary,
    )
    def put_subaccount_interest(
        account_id: UUID,
        subaccount_id: UUID,
        payload: SubaccountInterestUpdate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> AccountSubaccountSummary:
        return update_subaccount_interest(
            session, current_user.id, account_id, subaccount_id, payload
        )

    @app.delete("/api/accounts/{account_id}", status_code=204)
    def remove_account(
        account_id: UUID,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> None:
        delete_account(session, current_user.id, account_id)
        return None

    @app.get(
        "/api/market/status",
        response_model=MarketDataStatusResponse,
        dependencies=[Depends(get_current_user)],
    )
    def get_market_status() -> MarketDataStatusResponse:
        return market_data_status()

    @app.get(
        "/api/market/search",
        response_model=MarketSymbolSearchResponse,
        dependencies=[Depends(get_current_user)],
    )
    async def get_market_search(
        query: Annotated[str, Query(min_length=2, max_length=80, alias="q")],
    ) -> MarketSymbolSearchResponse:
        return MarketSymbolSearchResponse(results=await search_market_symbols(query))

    @app.post("/api/market/refresh", response_model=MarketRefreshResponse)
    async def post_market_refresh(
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> MarketRefreshResponse:
        return await refresh_market_data(session, current_user.id)

    @app.post("/api/holdings", response_model=HoldingCreateResponse, status_code=201)
    async def post_holding(
        payload: HoldingCreate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> HoldingCreateResponse:
        return await create_holding(session, current_user.id, payload)

    @app.put("/api/holdings/{holding_id}", status_code=204)
    def put_holding(
        holding_id: UUID,
        payload: HoldingUpdate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> None:
        update_holding(session, current_user.id, holding_id, payload)
        return None

    @app.delete("/api/holdings/{holding_id}", status_code=204)
    def remove_holding(
        holding_id: UUID,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> None:
        delete_holding(session, current_user.id, holding_id)
        return None

    @app.post("/api/holdings/{holding_id}/sell", response_model=StockSaleResponse, status_code=201)
    def post_holding_sale(
        holding_id: UUID,
        payload: StockSaleCreate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> StockSaleResponse:
        return sell_holding(session, current_user.id, holding_id, payload)

    @app.post("/api/cash-transfers", response_model=CashTransferResponse, status_code=201)
    def post_cash_transfer(
        payload: CashTransferCreate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> CashTransferResponse:
        return transfer_cash(session, current_user.id, payload)

    @app.post("/api/vesting-grants", status_code=201)
    async def post_vesting_grant(
        payload: VestingGrantCreate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, UUID]:
        grant_id = await create_vesting_grant(session, current_user.id, payload)
        return {"id": grant_id}

    @app.post("/api/stock-purchase-plans", status_code=201)
    async def post_stock_purchase_plan(
        payload: StockPurchasePlanCreate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, UUID]:
        plan_id = await create_purchase_plan(session, current_user.id, payload)
        return {"id": plan_id}

    @app.delete("/api/stock-purchase-plans/{plan_id}", status_code=204)
    def remove_stock_purchase_plan(
        plan_id: UUID,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> None:
        delete_purchase_plan(session, current_user.id, plan_id)
        return None

    @app.delete("/api/vesting-grants/{grant_id}", status_code=204)
    def remove_vesting_grant(
        grant_id: UUID,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> None:
        delete_vesting_grant(session, current_user.id, grant_id)
        return None

    @app.get("/api/goals", response_model=list[GoalResponse])
    def get_goals(
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[GoalResponse]:
        return list_goals(session, current_user.id)

    @app.post("/api/goals", response_model=GoalResponse, status_code=201)
    def post_goal(
        payload: GoalCreate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> GoalResponse:
        return create_goal(session, current_user.id, payload)

    @app.put("/api/goals/funding-shares")
    def put_goal_funding_shares(
        payload: FixedSharesUpdate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, dict[str, str]]:
        shares = update_fixed_shares(session, current_user.id, payload)
        return {"shares": {goal_id: str(weight) for goal_id, weight in shares.items()}}

    @app.put("/api/goals/{goal_id}", response_model=GoalResponse)
    def put_goal(
        goal_id: UUID,
        payload: GoalUpdate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> GoalResponse:
        return update_goal(session, current_user.id, goal_id, payload)

    @app.delete("/api/goals/{goal_id}", status_code=204)
    def remove_goal(
        goal_id: UUID,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> None:
        archive_goal(session, current_user.id, goal_id)
        return None

    @app.post("/api/deposits", response_model=FixedDepositCreateResponse, status_code=201)
    def post_deposit(
        payload: FixedDepositCreate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> FixedDepositCreateResponse:
        return create_fixed_deposit(session, current_user.id, payload)

    @app.delete("/api/deposits/{deposit_id}", status_code=204)
    def remove_deposit(
        deposit_id: UUID,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> None:
        delete_fixed_deposit(session, current_user.id, deposit_id)
        return None

    @app.get("/api/policy", response_model=PolicyResponse)
    def get_policy(
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> PolicyResponse:
        return get_policy_response(session, current_user.id)

    @app.put("/api/policy", response_model=PolicyResponse)
    def put_policy(
        payload: PolicyUpdate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> PolicyResponse:
        return update_policy(session, current_user.id, payload)

    @app.get("/api/cash-flows", response_model=list[FlowResponse])
    def get_cash_flows(
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
        months: int = Query(default=12, ge=1, le=24),
    ) -> list[FlowResponse]:
        return list_cash_flows(session, current_user.id, months)

    @app.post("/api/cash-flows/extra-cash", response_model=FlowResponse, status_code=201)
    def post_extra_cash(
        payload: CashReceiptCreate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> FlowResponse:
        return record_extra_cash(session, current_user.id, payload)

    @app.get("/api/cash-flow-schedules", response_model=list[CashFlowScheduleResponse])
    def get_cash_flow_schedules(
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[CashFlowScheduleResponse]:
        return list_cash_flow_schedules(session, current_user.id)

    @app.post(
        "/api/cash-flow-schedules",
        response_model=CashFlowScheduleResponse,
        status_code=201,
    )
    def post_cash_flow_schedule(
        payload: CashFlowScheduleCreate,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> CashFlowScheduleResponse:
        return create_cash_flow_schedule(session, current_user.id, payload)

    @app.delete(
        "/api/cash-flow-schedules/{schedule_id}",
        response_model=CashFlowScheduleResponse,
    )
    def delete_cash_flow_schedule(
        schedule_id: UUID,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> CashFlowScheduleResponse:
        return archive_cash_flow_schedule(session, current_user.id, schedule_id)

    @app.post(
        "/api/recommendations/preview",
        response_model=RecommendationResponse,
    )
    def post_recommendation_preview(
        payload: RecommendationRequest,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> RecommendationResponse:
        return preview_recommendation(session, current_user.id, payload)

    @app.post("/api/chat", response_model=ChatResponse)
    async def post_chat(
        payload: ChatRequest,
        current_user: Annotated[User, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
        provider_key: Annotated[str | None, Header(alias="X-Provider-API-Key")] = None,
    ) -> ChatResponse:
        if not provider_key or not provider_key.strip():
            raise HTTPException(
                status_code=401,
                detail="Enter a provider API key to use the assistant. The key is not stored.",
            )
        if len(provider_key) > 512:
            raise HTTPException(status_code=422, detail="Provider API key is too long")
        if not settings.ai_model.strip():
            raise HTTPException(
                status_code=503,
                detail="AI_MODEL is not configured. Set a model name in your local .env first.",
            )

        snapshot = dashboard(session, current_user.id)
        context = {
            "as_of": snapshot["as_of"].astimezone(UTC).isoformat(),
            "sample_data": snapshot["sample_data"],
            "base_currency": snapshot["base_currency"].value,
            "totals": {key: str(value) for key, value in snapshot["totals"].items()},
            "allocation": [
                {
                    "asset_class": item.asset_class.value,
                    "value": str(item.value),
                    "current_percent": str(item.percentage),
                    "target_percent": str(item.target_percentage),
                }
                for item in snapshot["allocation"]
            ],
            "holdings": [
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "instrument_type": item.instrument_type,
                    "quantity": str(item.quantity),
                    "latest_price": str(item.price),
                    "price_currency": item.price_currency.value,
                    "gross_market_value": str(item.gross_market_value),
                    "estimated_after_tax_value": str(item.market_value),
                    "estimated_sale_tax": str(item.estimated_sale_tax),
                    "purchase_date": item.purchase_date.isoformat(),
                    "quote_source": item.quote_source,
                    "quote_observed_at": item.quote_observed_at.astimezone(UTC).isoformat(),
                    "market_open": item.is_market_open,
                }
                for item in sorted(
                    snapshot["holdings"], key=lambda holding: holding.market_value, reverse=True
                )[:50]
            ],
            "market_fx_rates": [
                {
                    "base_currency": item.base_currency.value,
                    "quote_currency": item.quote_currency.value,
                    "rate": str(item.rate),
                    "provider": item.provider,
                    "observed_at": item.observed_at.astimezone(UTC).isoformat(),
                }
                for item in snapshot["market_fx_rates"]
            ],
            "goals": [
                {
                    "name": item.name,
                    "type": item.goal_type.value,
                    "progress_percent": str(item.progress_percent),
                    "deadline": item.target_date.isoformat() if item.target_date else None,
                }
                for item in snapshot["goals"]
            ],
            "quality_warnings": snapshot["warnings"],
        }
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(payload.history[-8:])
        messages.append(
            {
                "role": "user",
                "content": (
                    f"User question: {payload.question.strip()}\n\n"
                    f"Current app context (JSON): {json.dumps(context, separators=(',', ':'))}"
                ),
            }
        )
        request_body = {
            "model": settings.ai_model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 700,
        }
        try:
            async with httpx.AsyncClient(
                timeout=settings.chat_timeout_seconds, follow_redirects=False
            ) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {provider_key.strip()}"},
                    json=request_body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(
                status_code=504, detail="The AI provider did not respond before the timeout"
            ) from error
        except httpx.RequestError as error:
            raise HTTPException(
                status_code=502, detail="The AI provider could not be reached"
            ) from error

        if not response.is_success:
            if response.status_code in {401, 403}:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "The AI provider rejected this key or model access. "
                        "Check your provider account."
                    ),
                )
            raise HTTPException(
                status_code=502,
                detail=f"The AI provider returned HTTP {response.status_code}",
            )

        try:
            provider_payload = response.json()
            answer = provider_payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise HTTPException(
                status_code=502, detail="The AI provider returned an invalid response"
            ) from error
        if not isinstance(answer, str) or not answer.strip():
            raise HTTPException(status_code=502, detail="The AI provider returned an empty answer")

        return ChatResponse(
            answer=answer.strip(),
            model=settings.ai_model,
            data_as_of=snapshot["as_of"],
            used_context=[
                "Portfolio and cash totals",
                "Tracked holdings and latest quote timestamps",
                "Cached EUR/USD/RON FX rates",
                "Asset allocation targets",
                "Goal progress",
                "Data-quality warnings",
            ],
        )

    return app


app = create_app()
