import importlib.util
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import inspect, text
from test_api import create_test_client

from app.cash_flow_logic import add_months, nominal_income_amount
from app.database import make_engine
from app.schemas import CashFlowScheduleCreate


def salary_payload(**changes):
    return {
        "label": "Monthly salary",
        "kind": "salary",
        "amount": "4000",
        "currency": "EUR",
        "recurrence": "monthly",
        "start_date": date.today().isoformat(),
        "annual_growth_rate": "0.05",
        **changes,
    }


def bonus_payload(salary_id, **changes):
    return {
        "label": "Annual salary bonus",
        "kind": "bonus",
        "currency": "EUR",
        "recurrence": "annual",
        "start_date": date.today().isoformat(),
        "salary_schedule_id": salary_id,
        "salary_percentage": "0.1",
        **changes,
    }


def expected_salary(start: date, payment: date, rate: str = "0.05") -> Decimal:
    return Decimal(4000) * (1 + Decimal(rate)) ** (
        Decimal((payment - start).days) / Decimal("365.25")
    )


def cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def test_nominal_income_growth_compounds_without_adding_inflation() -> None:
    start = date(2024, 1, 1)
    assert nominal_income_amount(Decimal(4000), Decimal(".05"), start, date(2028, 1, 1)) == (
        Decimal(4000) * Decimal("1.05") ** 4
    )
    assert nominal_income_amount(Decimal(4000), Decimal("0"), start, date(2028, 1, 1)) == 4000
    assert nominal_income_amount(Decimal(4000), Decimal("-.05"), start, date(2028, 1, 1)) == (
        Decimal(4000) * Decimal(".95") ** 4
    )


@pytest.mark.parametrize(
    "recurrence,multiplier", [("monthly", 12), ("quarterly", 4), ("annual", 1)]
)
def test_forecasts_annualize_growing_salary_and_bonus(tmp_path, recurrence, multiplier) -> None:
    start = date.today() - timedelta(days=365)
    with create_test_client(tmp_path) as client:
        salary = client.post(
            "/api/cash-flow-schedules",
            json=salary_payload(
                start_date=start.isoformat(),
                recurrence=recurrence,
                end_date=add_months(date.today(), 13).isoformat(),
            ),
        )
        assert salary.status_code == 201, salary.text
        bonus = client.post("/api/cash-flow-schedules", json=bonus_payload(salary.json()["id"]))
        assert bonus.status_code == 201, bonus.text
        assert bonus.json()["salary_percentage"] == "0.10000000"
        flows = client.get("/api/cash-flows?months=24")
        assert flows.status_code == 200, flows.text
        bonus_flows = [flow for flow in flows.json() if flow["schedule_id"] == bonus.json()["id"]]
        assert len(bonus_flows) == 2  # No bonuses after the linked salary ends.
        assert Decimal(bonus.json()["amount"]) == Decimal(bonus_flows[0]["amount"])
        for flow in flows.json():
            payment = date.fromisoformat(flow["expected_date"])
            expected = expected_salary(start, payment)
            if flow["schedule_id"] == bonus.json()["id"]:
                expected *= Decimal(multiplier) * Decimal(".1")
            assert Decimal(flow["amount"]) == cents(expected)
            assert Decimal(flow["reporting_amount"]) == cents(expected)
        assert Decimal(bonus_flows[1]["amount"]) > Decimal(bonus_flows[0]["amount"])
        stopped = client.delete(f"/api/cash-flow-schedules/{salary.json()['id']}")
        assert stopped.status_code == 200
        assert client.get("/api/cash-flow-schedules").json() == []
        assert client.get("/api/cash-flows?months=24").json() == []


def test_forecast_and_posted_income_match_and_are_idempotent(monkeypatch, tmp_path) -> None:
    import app.services as services

    today = date.today()
    future = today + timedelta(days=366)

    class FutureDate(date):
        @classmethod
        def today(cls):
            return future

    with create_test_client(tmp_path) as client:
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "Income account",
                "provider_code": "MANUAL",
                "account_type": "BANK",
                "currency": "EUR",
                "opening_cash": "0",
            },
        )
        assert account.status_code == 201, account.text
        destination = {
            "account_id": account.json()["id"],
            "subaccount_id": account.json()["subaccounts"][0]["id"],
            "auto_post": True,
        }
        salary = client.post("/api/cash-flow-schedules", json=salary_payload(**destination))
        assert salary.status_code == 201, salary.text
        bonus = client.post(
            "/api/cash-flow-schedules",
            json=bonus_payload(
                salary.json()["id"],
                start_date=(today + timedelta(days=1)).isoformat(),
                **destination,
            ),
        )
        assert bonus.status_code == 201, bonus.text
        initial = client.get("/api/cash-flows?months=24")
        assert initial.status_code == 200, initial.text
        expected = {
            (flow["schedule_id"], flow["expected_date"]): Decimal(flow["amount"])
            for flow in initial.json()
            if flow["expected_date"] <= future.isoformat()
        }
        monkeypatch.setattr(services, "date", FutureDate)
        for _ in range(2):
            result = client.get("/api/cash-flows?months=24")
            assert result.status_code == 200, result.text
            confirmed = [flow for flow in result.json() if flow["status"] == "confirmed"]
            assert len(confirmed) == len(expected)
            assert {
                (flow["schedule_id"], flow["expected_date"]): Decimal(flow["amount"])
                for flow in confirmed
            } == expected
            dashboard = client.get("/api/dashboard")
            assert dashboard.status_code == 200, dashboard.text
            assert Decimal(dashboard.json()["accounts"][0]["subaccounts"][0]["cash_balance"]) == (
                sum(expected.values())
            )
        stopped = client.delete(f"/api/cash-flow-schedules/{salary.json()['id']}")
        assert stopped.status_code == 200
        remaining = client.get("/api/cash-flows?months=24").json()
        assert len(remaining) == len(expected)
        assert all(flow["status"] == "confirmed" for flow in remaining)


def test_linked_bonus_uses_configured_fx_and_rejects_missing_fx(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        salary = client.post(
            "/api/cash-flow-schedules", json=salary_payload(annual_growth_rate="0")
        )
        assert salary.status_code == 201, salary.text
        payload = bonus_payload(salary.json()["id"], currency="USD")
        missing = client.post("/api/cash-flow-schedules", json=payload)
        assert missing.status_code == 409
        profile = client.put(
            "/api/profile",
            json={
                "display_name": "Test user",
                "base_currency": "EUR",
                "usd_per_eur": "1.25",
            },
        )
        assert profile.status_code == 200, profile.text
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "USD bonus account",
                "provider_code": "MANUAL",
                "account_type": "BANK",
                "currency": "USD",
                "opening_cash": "0",
            },
        )
        assert account.status_code == 201, account.text
        payload.update(
            {
                "auto_post": True,
                "account_id": account.json()["id"],
                "subaccount_id": account.json()["subaccounts"][0]["id"],
            }
        )
        bonus = client.post("/api/cash-flow-schedules", json=payload)
        assert bonus.status_code == 201, bonus.text
        assert Decimal(bonus.json()["amount"]) == Decimal(6000)
        flows = client.get("/api/cash-flows").json()
        for flow in flows:
            if flow["schedule_id"] == bonus.json()["id"]:
                assert Decimal(flow["amount"]) == 6000
                assert Decimal(flow["reporting_amount"]) == 4800
                expected_status = (
                    "confirmed" if flow["expected_date"] == date.today().isoformat() else "forecast"
                )
                assert flow["status"] == expected_status
        for _ in range(2):
            dashboard = client.get("/api/dashboard").json()
            assert Decimal(dashboard["accounts"][0]["subaccounts"][0]["cash_balance"]) == 6000


def test_default_fixed_schedules_retain_existing_amounts(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        payload = salary_payload(amount="4000.1234")
        del payload["annual_growth_rate"]
        salary = client.post("/api/cash-flow-schedules", json=payload)
        assert salary.status_code == 201, salary.text
        assert Decimal(salary.json()["annual_growth_rate"]) == 0
        assert salary.json()["salary_schedule_id"] is None
        assert salary.json()["salary_percentage"] is None
        flows = client.get("/api/cash-flows")
        assert flows.status_code == 200, flows.text
        assert flows.json()
        assert all(Decimal(flow["amount"]) == Decimal("4000.1234") for flow in flows.json())


@pytest.mark.parametrize(
    "changes",
    [
        {"salary_schedule_id": None},
        {"salary_percentage": None},
        {"salary_percentage": "0"},
        {"salary_percentage": "1.01"},
        {"annual_growth_rate": ".05"},
        {"amount": "100"},
        {"recurrence": "monthly"},
        {"kind": "salary"},
    ],
)
def test_invalid_percentage_bonus_configuration_is_rejected(changes) -> None:
    with pytest.raises(ValidationError):
        CashFlowScheduleCreate.model_validate(bonus_payload(str(uuid4()), **changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"annual_growth_rate": "1.01"},
        {"annual_growth_rate": "-.51"},
        {"recurrence": "one_time"},
        {"kind": "bill"},
        {"amount": None},
    ],
)
def test_invalid_salary_growth_configuration_is_rejected(changes) -> None:
    with pytest.raises(ValidationError):
        CashFlowScheduleCreate.model_validate(salary_payload(**changes))


def test_bonus_references_require_owned_active_recurring_salary_and_valid_dates(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        for changes, status in [
            ({"kind": "bill", "annual_growth_rate": "0"}, 404),
            ({"recurrence": "one_time", "annual_growth_rate": "0"}, 422),
            ({"start_date": (date.today() + timedelta(days=20)).isoformat()}, 422),
            (
                {
                    "end_date": (date.today() - timedelta(days=1)).isoformat(),
                    "start_date": (date.today() - timedelta(days=20)).isoformat(),
                },
                422,
            ),
        ]:
            salary = client.post("/api/cash-flow-schedules", json=salary_payload(**changes))
            assert salary.status_code == 201, salary.text
            bonus = client.post("/api/cash-flow-schedules", json=bonus_payload(salary.json()["id"]))
            assert bonus.status_code == status, bonus.text
        salary = client.post("/api/cash-flow-schedules", json=salary_payload())
        assert salary.status_code == 201, salary.text
        salary_id = salary.json()["id"]
        registered = client.post(
            "/api/auth/register",
            json={
                "username": f"second_{uuid4().hex[:12]}",
                "password": "test-passphrase-for-investingtracker",
                "display_name": "Second user",
                "base_currency": "EUR",
            },
        )
        assert registered.status_code == 201, registered.text
        original_auth = client.headers["Authorization"]
        client.headers["Authorization"] = f"Bearer {registered.json()['access_token']}"
        assert (
            client.post("/api/cash-flow-schedules", json=bonus_payload(salary_id)).status_code
            == 404
        )
        client.headers["Authorization"] = original_auth
        assert client.delete(f"/api/cash-flow-schedules/{salary_id}").status_code == 200
        assert (
            client.post("/api/cash-flow-schedules", json=bonus_payload(salary_id)).status_code
            == 404
        )


def test_income_schedule_migration_preserves_existing_amounts_and_downgrades(tmp_path) -> None:
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / ("20261018_23_cash_flow_income_growth.py")
    )
    spec = importlib.util.spec_from_file_location("income_schedule_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = make_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    salary_id = uuid4().hex
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE cash_flow_schedules "
                "(id CHAR(32) PRIMARY KEY, kind TEXT NOT NULL, recurrence TEXT NOT NULL, "
                "amount NUMERIC NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO cash_flow_schedules VALUES (:id, 'salary', 'monthly', 4000)"),
            {"id": salary_id},
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        saved = connection.execute(
            text(
                "SELECT amount, annual_growth_rate, salary_schedule_id, salary_percentage "
                "FROM cash_flow_schedules"
            )
        ).one()
        assert tuple(saved) == (4000, 0, None, None)
        connection.execute(
            text(
                "INSERT INTO cash_flow_schedules "
                "(id, kind, recurrence, amount, salary_schedule_id, salary_percentage) "
                "VALUES (:id, 'bonus', 'annual', 4800, :salary, .1)"
            ),
            {"id": uuid4().hex, "salary": salary_id},
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        columns = {
            column["name"] for column in inspect(connection).get_columns("cash_flow_schedules")
        }
        assert columns == {"id", "kind", "recurrence", "amount"}
        assert (
            connection.execute(text("SELECT COUNT(*) FROM cash_flow_schedules")).scalar_one() == 2
        )
    engine.dispose()
