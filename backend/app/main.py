import json
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from datetime import UTC
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database import Base, SessionFactory, engine, get_session
from app.models import Currency
from app.schemas import (
    CashFlowScheduleCreate,
    CashFlowScheduleResponse,
    ChatRequest,
    ChatResponse,
    DashboardResponse,
    FixedSharesUpdate,
    FlowResponse,
    GoalCreate,
    GoalResponse,
    PolicyResponse,
    PolicyUpdate,
    RecommendationRequest,
    RecommendationResponse,
)
from app.seed import seed_demo_data
from app.services import (
    USER_ID,
    archive_cash_flow_schedule,
    create_cash_flow_schedule,
    create_goal,
    dashboard,
    get_policy_response,
    list_cash_flow_schedules,
    list_cash_flows,
    list_goals,
    preview_recommendation,
    update_fixed_shares,
    update_policy,
)

settings = get_settings()
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
    db_engine=engine,
    seed_demo: bool | None = None,
) -> FastAPI:
    should_seed = settings.seed_demo_data if seed_demo is None else seed_demo

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        Base.metadata.create_all(bind=db_engine)
        if should_seed:
            with session_factory() as session:
                seed_demo_data(session, USER_ID)
        yield

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Local-first personal wealth tracking prototype. Demo data only; "
            "not intended for public deployment or real financial records."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["DELETE", "GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Content-Type", "X-Provider-API-Key"],
    )

    def session_dependency() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "northstar-api"}

    @app.get("/api/dashboard", response_model=DashboardResponse)
    def get_dashboard(
        session: Annotated[Session, Depends(get_session)],
        currency: Currency | None = None,
    ) -> dict:
        return dashboard(session, currency)

    @app.get("/api/goals", response_model=list[GoalResponse])
    def get_goals(session: Annotated[Session, Depends(get_session)]) -> list[GoalResponse]:
        return list_goals(session)

    @app.post("/api/goals", response_model=GoalResponse, status_code=201)
    def post_goal(
        payload: GoalCreate,
        session: Annotated[Session, Depends(get_session)],
    ) -> GoalResponse:
        return create_goal(session, payload)

    @app.put("/api/goals/funding-shares")
    def put_goal_funding_shares(
        payload: FixedSharesUpdate,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, dict[str, str]]:
        shares = update_fixed_shares(session, payload)
        return {"shares": {goal_id: str(weight) for goal_id, weight in shares.items()}}

    @app.get("/api/policy", response_model=PolicyResponse)
    def get_policy(session: Annotated[Session, Depends(get_session)]) -> PolicyResponse:
        return get_policy_response(session)

    @app.put("/api/policy", response_model=PolicyResponse)
    def put_policy(
        payload: PolicyUpdate,
        session: Annotated[Session, Depends(get_session)],
    ) -> PolicyResponse:
        return update_policy(session, payload)

    @app.get("/api/cash-flows", response_model=list[FlowResponse])
    def get_cash_flows(
        session: Annotated[Session, Depends(get_session)],
        months: int = Query(default=12, ge=1, le=24),
    ) -> list[FlowResponse]:
        return list_cash_flows(session, months)

    @app.get("/api/cash-flow-schedules", response_model=list[CashFlowScheduleResponse])
    def get_cash_flow_schedules(
        session: Annotated[Session, Depends(get_session)],
    ) -> list[CashFlowScheduleResponse]:
        return list_cash_flow_schedules(session)

    @app.post(
        "/api/cash-flow-schedules",
        response_model=CashFlowScheduleResponse,
        status_code=201,
    )
    def post_cash_flow_schedule(
        payload: CashFlowScheduleCreate,
        session: Annotated[Session, Depends(get_session)],
    ) -> CashFlowScheduleResponse:
        return create_cash_flow_schedule(session, payload)

    @app.delete(
        "/api/cash-flow-schedules/{schedule_id}",
        response_model=CashFlowScheduleResponse,
    )
    def delete_cash_flow_schedule(
        schedule_id: UUID,
        session: Annotated[Session, Depends(get_session)],
    ) -> CashFlowScheduleResponse:
        return archive_cash_flow_schedule(session, schedule_id)

    @app.post(
        "/api/recommendations/preview",
        response_model=RecommendationResponse,
    )
    def post_recommendation_preview(
        payload: RecommendationRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> RecommendationResponse:
        return preview_recommendation(session, payload)

    @app.post("/api/chat", response_model=ChatResponse)
    async def post_chat(
        payload: ChatRequest,
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

        snapshot = dashboard(session)
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
                "Asset allocation targets",
                "Goal progress",
                "Data-quality warnings",
            ],
        )

    return app


app = create_app()
