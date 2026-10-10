from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.cash_flow_logic import add_months
from app.database import Base, make_engine
from app.main import create_app


def create_test_client(tmp_path) -> TestClient:
    test_engine = make_engine(f"sqlite:///{tmp_path / 'northstar-test.db'}")
    Base.metadata.create_all(bind=test_engine)
    factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    return TestClient(create_app(factory, test_engine, seed_demo=True))


def test_demo_dashboard_is_explicitly_labelled_and_supports_currency_switch(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        euro_response = client.get("/api/dashboard")
        dollar_response = client.get("/api/dashboard?currency=USD")

    assert euro_response.status_code == 200
    assert dollar_response.status_code == 200
    euro_dashboard = euro_response.json()
    dollar_dashboard = dollar_response.json()
    assert euro_dashboard["base_currency"] == "EUR"
    assert dollar_dashboard["base_currency"] == "USD"
    assert euro_dashboard["sample_data"] is True
    assert "no live market" in euro_dashboard["warnings"][0].lower()
    assert Decimal(euro_dashboard["totals"]["net_worth"]) > 0
    assert Decimal(dollar_dashboard["totals"]["net_worth"]) > Decimal(
        euro_dashboard["totals"]["net_worth"]
    )
    assert len(euro_dashboard["holdings"]) >= 3
    assert len(euro_dashboard["goals"]) == 3
    assert len(euro_dashboard["chart"]) == 6


def test_allocation_preview_conserves_the_investable_budget(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.post(
            "/api/recommendations/preview",
            json={"amount": "1000.00", "currency": "EUR"},
        )

    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["status"] == "PREVIEW_ONLY"
    assert sum(
        (Decimal(line["amount"]) for line in preview["goal_allocations"]),
        Decimal("0"),
    ) == Decimal(preview["deployable_amount"])
    assert sum(
        (Decimal(line["amount"]) for line in preview["asset_allocations"]),
        Decimal("0"),
    ) == Decimal(preview["investable_amount"])
    assert all(Decimal(line["amount"]) >= 0 for line in preview["asset_allocations"])
    assert preview["expires_at"]


def test_creating_goals_and_changing_funding_policy(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        created = client.post(
            "/api/goals",
            json={
                "name": "Education fund",
                "goal_type": "purchase",
                "target_amount": "24000",
                "current_amount": "2500",
                "target_currency": "EUR",
                "target_date": "2030-06-01",
                "priority": 4,
                "risk_level": "low",
                "monthly_contribution": "300",
                "flexibility": "flexible",
            },
        )
        policy = client.put(
            "/api/policy",
            json={
                "funding_rule": "proportional",
                "emergency_reserve": "9000",
                "target_weights": {
                    "equities": "0.70",
                    "fixed_income": "0.15",
                    "satellite": "0.15",
                },
            },
        )

    assert created.status_code == 201, created.text
    assert UUID(created.json()["id"])
    assert policy.status_code == 200, policy.text
    assert policy.json()["funding_rule"] == "proportional"


def test_policy_rejects_target_weights_that_do_not_sum_to_one(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.put(
            "/api/policy",
            json={
                "funding_rule": "priority_first",
                "emergency_reserve": "9000",
                "target_weights": {
                    "equities": "0.70",
                    "fixed_income": "0.10",
                    "satellite": "0.10",
                },
            },
        )

    assert response.status_code == 422


def test_chat_requires_a_key_and_does_not_call_the_provider_without_one(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.post("/api/chat", json={"question": "Explain my goal progress"})

    assert response.status_code == 401
    assert "not stored" in response.json()["detail"]


def test_recurring_salary_generates_forecasts_without_changing_available_cash(tmp_path) -> None:
    start_date = date.today() + timedelta(days=5)
    end_date = add_months(start_date, 2)
    payload = {
        "label": "Monthly salary",
        "kind": "salary",
        "amount": "5200",
        "currency": "EUR",
        "recurrence": "monthly",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    with create_test_client(tmp_path) as client:
        balance_before = client.get("/api/dashboard").json()["totals"]["available_cash"]
        created = client.post("/api/cash-flow-schedules", json=payload)
        flows = client.get("/api/cash-flows?months=12")
        dashboard = client.get("/api/dashboard").json()
        balance_after = dashboard["totals"]["available_cash"]

    assert created.status_code == 201, created.text
    assert flows.status_code == 200, flows.text
    schedule_id = created.json()["id"]
    occurrences = [flow for flow in flows.json() if flow["schedule_id"] == schedule_id]
    assert [flow["expected_date"] for flow in occurrences] == [
        start_date.isoformat(),
        add_months(start_date, 1).isoformat(),
        add_months(start_date, 2).isoformat(),
    ]
    assert all(flow["status"] == "forecast" for flow in occurrences)
    assert all(flow["direction"] == "inflow" for flow in occurrences)
    assert all(flow["amount"] == "5200.0000" for flow in occurrences)
    assert balance_after == balance_before
    assert any(flow["schedule_id"] == schedule_id for flow in dashboard["cash_flows"])


def test_scheduled_bill_is_a_forecast_outflow_and_can_be_archived(tmp_path) -> None:
    start_date = date.today() + timedelta(days=5)
    payload = {
        "label": "Rent",
        "kind": "bill",
        "amount": "1450",
        "currency": "EUR",
        "recurrence": "monthly",
        "start_date": start_date.isoformat(),
    }
    with create_test_client(tmp_path) as client:
        created = client.post("/api/cash-flow-schedules", json=payload)
        schedule_id = created.json()["id"]
        forecast = client.get("/api/cash-flows?months=3").json()
        balance_before = client.get("/api/dashboard").json()["totals"]["available_cash"]
        archived = client.delete(f"/api/cash-flow-schedules/{schedule_id}")
        flows_after_archive = client.get("/api/cash-flows?months=3").json()
        active_schedules = client.get("/api/cash-flow-schedules").json()
        balance_after = client.get("/api/dashboard").json()["totals"]["available_cash"]

    assert created.status_code == 201
    assert [flow for flow in forecast if flow["schedule_id"] == schedule_id]
    assert all(
        flow["direction"] == "outflow" and flow["status"] == "forecast"
        for flow in forecast
        if flow["schedule_id"] == schedule_id
    )
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    assert all(flow["schedule_id"] != schedule_id for flow in flows_after_archive)
    assert all(schedule["id"] != schedule_id for schedule in active_schedules)
    assert balance_after == balance_before


def test_cash_flow_schedule_rejects_end_date_before_start_and_long_projection(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        invalid_schedule = client.post(
            "/api/cash-flow-schedules",
            json={
                "label": "Invalid salary",
                "kind": "salary",
                "amount": "4000",
                "currency": "EUR",
                "recurrence": "monthly",
                "start_date": "2030-06-01",
                "end_date": "2030-05-31",
            },
        )
        excessive_horizon = client.get("/api/cash-flows?months=25")

    assert invalid_schedule.status_code == 422
    assert excessive_horizon.status_code == 422
