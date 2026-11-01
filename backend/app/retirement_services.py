from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from statistics import median
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cash_flow_logic import add_months
from app.models import (
    FixedDeposit,
    Goal,
    GoalDepositAllocation,
    GoalHoldingAllocation,
    GoalType,
    RetirementHistory,
)
from app.retirement import (
    DepositContract,
    HistoryImport,
    RetirementAsset,
    RetirementInvestment,
    RetirementSettings,
    parse_history,
    project_retirement,
)
from app.services import _fx_matrix, _get_user, _interest_tax_rate_for_account, _to_base, dashboard

WORLD_SOURCE = "https://data.worldbank.org/indicator/FP.CPI.TOTL.ZG?locations=1W"
WORLD_LICENSE = "World Bank WDI / IMF, FP.CPI.TOTL.ZG, CC BY 4.0"


def retirement_goal(session: Session, user_id: UUID, goal_id: UUID) -> Goal:
    goal = session.scalar(
        select(Goal).where(
            Goal.id == goal_id,
            Goal.user_id == user_id,
            Goal.is_active.is_(True),
            Goal.goal_type == GoalType.RETIREMENT,
        )
    )
    if goal is None:
        raise HTTPException(404, "Active retirement goal was not found")
    return goal


def history_summary(row: RetirementHistory) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "currency": row.currency,
        "source": row.source,
        "license": row.license,
        "sample_start": row.observations[0]["date"],
        "sample_end": row.observations[-1]["date"],
        "observations": len(row.observations),
        "created_at": row.created_at.isoformat(),
    }


def list_retirement_history(session: Session, user_id: UUID) -> list[dict]:
    return [
        history_summary(row)
        for row in session.scalars(
            select(RetirementHistory)
            .where(
                RetirementHistory.user_id == user_id,
                RetirementHistory.currency != "WLD",
            )
            .order_by(RetirementHistory.name, RetirementHistory.id)
        )
    ]


def import_retirement_history(session: Session, user_id: UUID, payload: HistoryImport) -> dict:
    try:
        observations = parse_history(payload.csv)
    except (ValueError, csv.Error) as error:
        raise HTTPException(422, str(error)) from error
    count = len(
        list(
            session.scalars(
                select(RetirementHistory.id).where(
                    RetirementHistory.user_id == user_id,
                    RetirementHistory.currency != "WLD",
                )
            )
        )
    )
    if count >= 200:
        raise HTTPException(422, "At most 200 local datasets per user; delete unused history first")
    row = RetirementHistory(
        user_id=user_id,
        name=payload.name,
        currency=payload.currency.value,
        source=payload.source,
        license=payload.license,
        observations=observations,
    )
    session.add(row)
    session.commit()
    return history_summary(row)


def delete_retirement_history(session: Session, user_id: UUID, history_id: UUID) -> None:
    row = session.scalar(
        select(RetirementHistory).where(
            RetirementHistory.id == history_id,
            RetirementHistory.user_id == user_id,
            RetirementHistory.currency != "WLD",
        )
    )
    if row is None:
        raise HTTPException(404, "History dataset was not found")
    for goal in session.scalars(
        select(Goal).where(
            Goal.user_id == user_id,
            Goal.is_active.is_(True),
        )
    ):
        settings = goal.retirement_settings or {}
        if any(
            item.get("history_id") == str(history_id) for item in settings.get("investments", [])
        ):
            raise HTTPException(409, "This dataset is used by an active goal; unlink it first")
    session.delete(row)
    session.commit()


async def retirement_inflation(session: Session, user_id: UUID, target_date: date) -> dict:
    today = date.today()
    if not today < target_date <= add_months(today, 1200):
        raise HTTPException(422, "Choose a future horizon of at most 100 years")
    row = session.scalar(
        select(RetirementHistory)
        .where(
            RetirementHistory.user_id == user_id,
            RetirementHistory.currency == "WLD",
        )
        .order_by(RetirementHistory.created_at.desc())
    )
    created = row.created_at.replace(tzinfo=UTC) if row else None
    if created is None or datetime.now(UTC) - created > timedelta(days=1):
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.get(
                    "https://api.worldbank.org/v2/country/WLD/indicator/FP.CPI.TOTL.ZG",
                    params={"format": "json", "per_page": "20000"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(
                502, "World Bank inflation data could not be loaded. Enter inflation manually."
            ) from error
        if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[1], list):
            raise HTTPException(502, "World Bank returned invalid inflation data")
        observations = []
        try:
            for item in payload[1]:
                if item["value"] is None:
                    continue
                rate = Decimal(str(item["value"])) / 100
                year = int(item["date"])
                if not rate.is_finite() or rate <= -1:
                    raise ValueError("Invalid annual CPI observation")
                if year < today.year:
                    observations.append({"date": f"{year}-12-31", "rate": str(rate)})
        except (KeyError, TypeError, ArithmeticError, ValueError) as error:
            raise HTTPException(502, "World Bank returned invalid CPI observations") from error
        observations.sort(key=lambda item: item["date"])
        if not observations:
            raise HTTPException(502, "No complete worldwide inflation years were returned")
        if row is None:
            row = RetirementHistory(
                user_id=user_id,
                name="Worldwide consumer inflation",
                currency="WLD",
                source=WORLD_SOURCE,
                license=WORLD_LICENSE,
            )
            session.add(row)
        row.observations = observations
        row.created_at = datetime.now(UTC)
        session.commit()
    assert row is not None
    years = Decimal((target_date - today).days) / Decimal("365.25")
    complete = int(years)
    fraction = years - complete
    width = complete + (1 if fraction else 0)
    rates = []
    observations = row.observations
    for start in range(len(observations) - width + 1):
        window = observations[start : start + width]
        if any(
            int(window[i]["date"][:4]) != int(window[0]["date"][:4]) + i for i in range(len(window))
        ):
            continue
        factor = Decimal(1)
        for i, item in enumerate(window):
            weight = fraction if i == complete else Decimal(1)
            factor *= (Decimal(1) + Decimal(item["rate"])) ** weight
        rates.append(float(factor ** (Decimal(1) / years) - 1))
    return {
        "available": bool(rates),
        "suggested_rate": median(rates) if rates else None,
        "lower_rate": min(rates) if rates else None,
        "upper_rate": max(rates) if rates else None,
        "windows": len(rates),
        "source": row.source,
        "license": row.license,
        "sample_start": observations[0]["date"],
        "sample_end": observations[-1]["date"],
        "method": "Median annualized compounded CPI across complete matching historical windows; "
        "a partial year is geometrically interpolated. World CPI aggregates country medians, "
        "not your personal spending basket. This is a historical assumption, not a forecast.",
        "reason": None if rates else "Insufficient complete history for this horizon",
    }


def retirement_assets(
    session: Session, user_id: UUID, goal: Goal, settings: RetirementSettings
) -> list[RetirementAsset]:
    user = _get_user(session, user_id)
    snapshot = dashboard(session, user_id, settings.currency)
    holdings = {row.id: row for row in snapshot["holdings"]}
    deposits = {row.id: row for row in snapshot["deposits"]}
    accounts = {row.id: row for row in snapshot["accounts"]}
    shares = dict(
        session.execute(
            select(
                GoalHoldingAllocation.holding_id,
                GoalHoldingAllocation.allocated_percentage,
            ).where(GoalHoldingAllocation.goal_id == goal.id)
        ).all()
    )
    deposit_shares = dict(
        session.execute(
            select(
                GoalDepositAllocation.fixed_deposit_id,
                GoalDepositAllocation.allocated_percentage,
            ).where(GoalDepositAllocation.goal_id == goal.id)
        ).all()
    )
    selected_holding_ids = {
        item.asset_id for item in settings.investments if item.kind == "holding"
    }
    selected_deposit_ids = {
        item.asset_id for item in settings.investments if item.kind == "deposit"
    }
    if set(shares) - selected_holding_ids or set(deposit_shares) - selected_deposit_ids:
        raise HTTPException(409, "Add return assumptions for all current retirement-linked assets")
    histories = {
        row.id: row
        for row in session.scalars(
            select(RetirementHistory).where(
                RetirementHistory.user_id == user_id,
                RetirementHistory.currency != "WLD",
            )
        )
    }
    assets = []
    for item in settings.investments:
        current, basis, rate, contract = Decimal(0), Decimal(0), item.tax_rate or Decimal(0), None
        warnings: list[str] = []
        if item.kind == "holding":
            holding = holdings.get(item.asset_id)
            if holding is None or item.asset_id not in shares:
                raise HTTPException(409, f"{item.name}: asset is no longer linked; review the plan")
            percentage = shares[item.asset_id] / 100
            current = holding.gross_market_value * percentage
            basis = holding.cost_basis_value * percentage
            rate = holding.estimated_tax_rate
        elif item.kind == "deposit":
            summary = deposits.get(item.asset_id)
            model = session.get(FixedDeposit, item.asset_id)
            if summary is None or model is None or item.asset_id not in deposit_shares:
                raise HTTPException(
                    409, f"{item.name}: deposit is no longer linked; review the plan"
                )
            percentage = deposit_shares[item.asset_id] / 100
            current = summary.current_value_base * percentage
            basis = summary.principal_value_base * percentage
            account = accounts[summary.account_id]
            rate, warnings = _interest_tax_rate_for_account(user, account)
            contract = DepositContract(
                basis,
                model.annual_rate,
                model.start_date,
                model.maturity_date,
                model.compounding,
                model.rate_basis,
            )
        history = histories.get(item.history_id) if item.history_id else None
        if item.history_id and history is None:
            raise HTTPException(
                409, f"{item.name}: history is unavailable or belongs to another user"
            )
        if history and history.currency != settings.currency.value:
            raise HTTPException(
                422,
                f"{item.name}: import total-return history in {settings.currency.value}, "
                "including historical FX; current FX cannot normalize historical returns",
            )
        assets.append(
            RetirementAsset(
                item,
                current,
                basis,
                rate,
                history.observations if history else None,
                contract,
                tuple(warnings),
            )
        )
    if goal.current_amount:
        cash = RetirementInvestment(
            key="manual-goal-cash",
            kind="cash",
            name="Explicit manual retirement savings",
            lower_return=0,
            upper_return=0,
        )
        current_cash = _to_base(
            goal.current_amount,
            goal.target_currency,
            settings.currency,
            user.usd_per_eur,
            _fx_matrix(session, user),
        )
        assets.append(RetirementAsset(cash, current_cash, current_cash, Decimal(0)))
    return assets


def calculate_retirement(
    session: Session,
    user_id: UUID,
    goal_id: UUID,
    settings: RetirementSettings,
    *,
    persist: bool = False,
) -> dict:
    goal = retirement_goal(session, user_id, goal_id)
    assets = retirement_assets(session, user_id, goal, settings)
    try:
        result = project_retirement(settings, assets, date.today())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if persist:
        goal.retirement_settings = settings.model_dump(mode="json")
        goal.target_date = settings.target_date
        goal.annual_inflation_rate = settings.annual_inflation_rate
        session.commit()
    return result


def saved_retirement_settings(session: Session, goal: Goal) -> RetirementSettings:
    settings = RetirementSettings.model_validate(goal.retirement_settings)
    holding_ids = set(
        session.scalars(
            select(GoalHoldingAllocation.holding_id).where(
                GoalHoldingAllocation.goal_id == goal.id,
            )
        )
    )
    deposit_ids = set(
        session.scalars(
            select(GoalDepositAllocation.fixed_deposit_id).where(
                GoalDepositAllocation.goal_id == goal.id,
            )
        )
    )
    retained = [
        item
        for item in settings.investments
        if item.contribution_percentage > 0
        or item.kind not in {"holding", "deposit"}
        or (item.kind == "holding" and item.asset_id in holding_ids)
        or (item.kind == "deposit" and item.asset_id in deposit_ids)
    ]
    return settings.model_copy(
        update={
            "investments": retained,
            "target_date": goal.target_date or settings.target_date,
        }
    )


def goal_asset_impact(session: Session, user_id: UUID, kind: str, asset_id: UUID) -> list[dict]:
    link = GoalHoldingAllocation if kind == "holding" else GoalDepositAllocation
    asset_column = link.holding_id if kind == "holding" else link.fixed_deposit_id
    rows = session.execute(
        select(Goal.name, link.allocated_percentage)
        .join(
            Goal,
            Goal.id == link.goal_id,
        )
        .where(
            Goal.user_id == user_id,
            Goal.is_active.is_(True),
            asset_column == asset_id,
        )
    ).all()
    return [{"name": row.name, "percentage": str(row.allocated_percentage)} for row in rows]
