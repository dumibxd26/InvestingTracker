import importlib.util
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import inspect, text
from test_api import _seed_priced_holding, create_test_client
from test_planning_api import goal_payload

from app.cash_flow_logic import add_months
from app.database import make_engine
from app.models import CompoundingFrequency, Currency, RateBasis, RetirementHistory
from app.retirement import (
    DepositContract,
    RetirementAsset,
    RetirementInvestment,
    RetirementSettings,
    historical_suggestion,
    parse_history,
    project_retirement,
)

D = Decimal
TODAY = date(2025, 1, 1)


def item(key="a", **changes):
    return RetirementInvestment(
        key=key, kind="etf", name=key, lower_return=0, upper_return=0, tax_rate=0, **changes
    )


def settings(investments, months=12, **changes):
    return RetirementSettings.model_validate(
        {
            "target_date": add_months(TODAY, months),
            "currency": Currency.EUR,
            "annual_inflation_rate": 0,
            "investments": investments,
            **changes,
        }
    )


def end(result, key="user_lower", real=False):
    return D(result["lines"][key][-1]["real_value" if real else "nominal_value"])


def history(values):
    return [
        {
            "date": (add_months(date(2000, 1, 1), i + 1) - timedelta(days=1)).isoformat(),
            "index": str(value),
        }
        for i, value in enumerate(values)
    ]


def test_zero_return_monthly_and_yearly_timing_and_real_values():
    investment = item(contribution_percentage=100)
    asset = RetirementAsset(investment, D(10000), D(10000), D(0))
    monthly = project_retirement(
        settings(
            [investment],
            contribution_amount=100,
            annual_inflation_rate=D("0.05"),
        ),
        [asset],
        TODAY,
    )
    assert end(monthly) == 11200
    assert D(monthly["contributions_paid"]) == 1200
    expected = D(11200) / D("1.05") ** (D(365) / D("365.25"))
    assert abs(end(monthly, real=True) - expected) < D("0.000001")
    yearly = project_retirement(
        settings(
            [investment],
            contribution_amount=100,
            contribution_frequency="yearly",
        ),
        [asset],
        TODAY,
    )
    assert end(yearly) == 10100
    assert D(yearly["contributions_paid"]) == 100
    partial = settings([investment], contribution_amount=100, contribution_frequency="yearly")
    partial.target_date -= timedelta(days=1)
    assert end(project_retirement(partial, [asset], TODAY)) == 10000


def test_future_split_does_not_rebalance_initial_assets():
    a, b = item("a", contribution_percentage=70), item("b", contribution_percentage=30)
    assets = [
        RetirementAsset(a, D(10000), D(10000), D(0)),
        RetirementAsset(b, D(0), D(0), D(0)),
    ]
    result = project_retirement(settings([a, b], months=1, contribution_amount=100), assets, TODAY)
    assert end(result) == 10100
    assert result["settings"]["investments"][0]["contribution_percentage"] == "70"


def test_historical_extremes_use_synchronized_windows_not_sum_of_asset_extremes():
    a, b = item("a", contribution_percentage=50), item("b", contribution_percentage=50)
    assets = [
        RetirementAsset(a, D(100), D(100), D(0), history([100, 200, 100])),
        RetirementAsset(b, D(100), D(100), D(0), history([100, 50, 100])),
    ]
    result = project_retirement(settings([a, b], months=1, contribution_amount=100), assets, TODAY)
    assert end(result, "historical_lower") == 350
    assert end(result, "historical_upper") == 350
    assert result["historical_windows"] == 2
    assert end(result) == 300


def test_historical_tax_and_no_false_history_for_missing_series():
    investment = item()
    asset = RetirementAsset(investment, D(100), D(100), D("0.25"), history([100, 200]))
    result = project_retirement(settings([investment], months=1), [asset], TODAY)
    assert end(result, "historical_lower") == 175
    gross = project_retirement(
        settings([investment], months=1, include_taxes=False), [asset], TODAY
    )
    assert end(gross, "historical_upper") == 200
    absent = RetirementAsset(investment, D(100), D(100), D(0))
    result = project_retirement(settings([investment]), [absent], TODAY)
    assert result["lines"]["historical_lower"] is None
    assert result["historical_windows"] == 0


def test_deposit_contract_matures_without_topups_or_renewal():
    investment = RetirementInvestment(
        key="deposit",
        kind="deposit",
        asset_id=uuid4(),
        name="Deposit",
        lower_return=0,
        upper_return=1,
    )
    contract = DepositContract(
        D(1000),
        D("0.1"),
        TODAY,
        add_months(TODAY, 12),
        CompoundingFrequency.ANNUAL,
        RateBasis.EFFECTIVE_APY,
    )
    asset = RetirementAsset(investment, D(1000), D(1000), D("0.1"), contract=contract)
    result = project_retirement(settings([investment], months=24), [asset], TODAY)
    assert abs(end(result) - D(1090)) < D("0.2")
    assert end(result) == end(result, "user_upper")
    with pytest.raises(ValidationError, match="top-ups"):
        RetirementInvestment.model_validate(
            {
                **investment.model_dump(),
                "contribution_percentage": 100,
            }
        )


def test_rounded_contributions_reconcile():
    investments = [
        item("a", contribution_percentage="33.33"),
        item("b", contribution_percentage="33.33"),
        item("c", contribution_percentage="33.34"),
    ]
    assets = [RetirementAsset(row, D(0), D(0), D(0)) for row in investments]
    result = project_retirement(
        settings(investments, months=1, contribution_amount="0.01"),
        assets,
        TODAY,
    )
    assert end(result) == D("0.01")


def test_history_format_and_matching_horizon():
    parsed = parse_history("date,total_return_index\n2000-01-31,100\n2000-02-29,110\n")
    suggestion = historical_suggestion(parsed, 1)
    assert suggestion["available"]
    assert abs(suggestion["median_return"] - float(D("1.1") ** 12 - 1)) < 1e-9
    assert not historical_suggestion(parsed, 2)["available"]


@pytest.mark.parametrize(
    "text",
    [
        "date,total_return_index\n2000-01-30,100\n2000-02-29,110\n",
        "date,total_return_index\n2000-01-31,100\n2000-03-31,110\n",
        "date,total_return_index\n2000-01-31,NaN\n2000-02-29,110\n",
        "date,total_return_index\n2000-01-31,0\n2000-02-29,110\n",
        "date,price\n2000-01-31,100\n2000-02-29,110\n",
    ],
)
def test_invalid_history_is_explicitly_rejected(text):
    with pytest.raises(ValueError):
        parse_history(text)


def test_retirement_api_persists_private_history_and_ignores_shared_timeline(tmp_path):
    with create_test_client(tmp_path) as client:
        goal = client.post(
            "/api/goals",
            json=goal_payload(
                goal_type="retirement",
                target_amount=None,
                current_amount="10000",
            ),
        )
        assert goal.status_code == 201, goal.text
        goal_id = goal.json()["id"]
        imported = client.post(
            "/api/retirement/history",
            json={
                "name": "Synthetic fixture, not market evidence",
                "currency": "EUR",
                "source": "Generated test data",
                "license": "Test fixture only",
                "personal_storage_permitted": True,
                "total_return_confirmed": True,
                "csv": "date,total_return_index\n2000-01-31,100\n2000-02-29,100\n",
            },
        )
        assert imported.status_code == 201, imported.text
        history_id = imported.json()["id"]
        assert len(client.get("/api/retirement/history").json()) == 1
        investment = item(contribution_percentage=100, history_id=history_id)
        payload = settings([investment], contribution_amount=100).model_dump(mode="json")
        payload["target_date"] = add_months(date.today(), 12).isoformat()
        response = client.put(f"/api/goals/{goal_id}/retirement", json=payload)
        assert response.status_code == 200, response.text
        assert end(response.json()) == 11200
        reloaded = client.get(f"/api/goals/{goal_id}/retirement")
        assert reloaded.status_code == 200, reloaded.text
        assert end(reloaded.json()) == 11200
        assert (
            client.get("/api/goals").json()[0]["retirement_settings"]["contribution_amount"]
            == "100"
        )
        assert client.delete(f"/api/retirement/history/{history_id}").status_code == 409
        other = client.post(
            "/api/auth/register",
            json={
                "username": "other_retirement",
                "password": "test-passphrase-for-investingtracker",
                "display_name": "Other",
                "base_currency": "EUR",
            },
        )
        client.headers["Authorization"] = f"Bearer {other.json()['access_token']}"
        assert client.get("/api/retirement/history").json() == []
        assert client.get(f"/api/goals/{goal_id}/retirement").status_code == 404
        assert client.delete(f"/api/retirement/history/{history_id}").status_code == 404


def test_retirement_requires_inflation_and_valid_future_split():
    investment = item(contribution_percentage=99)
    with pytest.raises(ValidationError, match="100%"):
        settings([investment], contribution_amount=100)
    with pytest.raises(ValidationError):
        RetirementSettings.model_validate(
            {
                "target_date": "2030-01-01",
                "currency": "EUR",
                "investments": [],
            }
        )


def test_sales_refresh_current_assets_without_assigning_account_cash(tmp_path):
    with create_test_client(tmp_path) as client:
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "Retirement broker",
                "provider_code": "MANUAL",
                "account_type": "BROKERAGE",
                "currency": "EUR",
                "opening_cash": "0",
            },
        )
        assert account.status_code == 201, account.text
        account_id = account.json()["id"]
        holding_id = _seed_priced_holding(client, account_id, "RETETF", "10", "10", "20")
        goal = client.post(
            "/api/goals",
            json=goal_payload(
                goal_type="retirement",
                target_amount=None,
                linked_account_ids=[account_id],
                holding_allocations=[{"id": holding_id, "allocated_percentage": "50"}],
            ),
        )
        assert goal.status_code == 201, goal.text
        goal_id = goal.json()["id"]
        tracked = RetirementInvestment(
            key=holding_id,
            kind="holding",
            asset_id=holding_id,
            name="RETETF",
            lower_return=0,
            upper_return=0,
        )
        payload = settings([tracked], include_taxes=False).model_dump(mode="json")
        payload["target_date"] = add_months(date.today(), 12).isoformat()
        before = client.put(f"/api/goals/{goal_id}/retirement", json=payload)
        assert before.status_code == 200, before.text
        assert end(before.json()) == 100
        impact = client.get(f"/api/retirement/asset-impact/holding/{holding_id}")
        assert impact.json() == [{"name": "Retirement", "percentage": "50.0000"}]
        sale_payload = {
            "sell_date": date.today().isoformat(),
            "sell_price": "20",
            "quantity": "4",
            "idempotency_key": str(uuid4()),
        }
        sale = client.post(f"/api/holdings/{holding_id}/sell", json=sale_payload)
        assert sale.status_code == 201, sale.text
        remaining = client.get(f"/api/goals/{goal_id}/retirement")
        assert remaining.status_code == 200, remaining.text
        assert end(remaining.json()) == 60
        sale_payload.update(quantity="6", idempotency_key=str(uuid4()))
        full = client.post(f"/api/holdings/{holding_id}/sell", json=sale_payload)
        assert full.status_code == 201, full.text
        after = client.get(f"/api/goals/{goal_id}/retirement")
        assert after.status_code == 200, after.text
        assert end(after.json()) == 0
        assert D(client.get("/api/dashboard").json()["totals"]["available_cash"]) == 200
        replacement = _seed_priced_holding(client, account_id, "RETNEW", "5", "20", "20")
        assert end(client.get(f"/api/goals/{goal_id}/retirement").json()) == 0
        changed = client.put(
            f"/api/goals/{goal_id}",
            json=goal_payload(
                goal_type="retirement",
                target_amount=None,
                linked_account_ids=[account_id],
                holding_allocations=[{"id": replacement, "allocated_percentage": "100"}],
            ),
        )
        assert changed.status_code == 200, changed.text
        tracked.asset_id = UUID(replacement)
        tracked.key = replacement
        payload["investments"] = [tracked.model_dump(mode="json")]
        linked = client.put(f"/api/goals/{goal_id}/retirement", json=payload)
        assert linked.status_code == 200, linked.text
        assert end(linked.json()) == 100


def test_disposed_future_destination_requires_explicit_review(tmp_path):
    with create_test_client(tmp_path) as client:
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "Contribution broker",
                "provider_code": "MANUAL",
                "account_type": "BROKERAGE",
                "currency": "EUR",
                "opening_cash": "0",
            },
        ).json()
        holding_id = _seed_priced_holding(client, account["id"], "RETFUT", "1", "10", "10")
        goal = client.post(
            "/api/goals",
            json=goal_payload(
                goal_type="retirement",
                target_amount=None,
                linked_account_ids=[account["id"]],
                holding_allocations=[{"id": holding_id}],
            ),
        ).json()
        tracked = RetirementInvestment(
            key=holding_id,
            kind="holding",
            asset_id=holding_id,
            name="RETFUT",
            lower_return=0,
            upper_return=0,
            contribution_percentage=100,
        )
        payload = settings([tracked], contribution_amount=100).model_dump(mode="json")
        payload["target_date"] = add_months(date.today(), 12).isoformat()
        assert client.put(f"/api/goals/{goal['id']}/retirement", json=payload).status_code == 200
        sale = client.post(
            f"/api/holdings/{holding_id}/sell",
            json={
                "sell_date": date.today().isoformat(),
                "sell_price": "10",
                "idempotency_key": str(uuid4()),
            },
        )
        assert sale.status_code == 201, sale.text
        assert client.get(f"/api/goals/{goal['id']}/retirement").status_code == 409


def test_world_inflation_is_attributed_cached_and_never_silently_applied(monkeypatch, tmp_path):
    calls = []

    async def get(_client, url, **_kwargs):
        calls.append(url)
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json=[
                {"pages": 1},
                [
                    {"date": "2020", "value": 2},
                    {"date": "2021", "value": 4},
                    {"date": "2022", "value": 3},
                ],
            ],
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    with create_test_client(tmp_path) as client:
        date_string = add_months(date.today(), 12).isoformat()
        first = client.get(f"/api/retirement/inflation?target_date={date_string}")
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["available"] and 0.02 <= body["suggested_rate"] <= 0.04
        assert "CC BY 4.0" in body["license"]
        assert body["sample_start"] == "2020-12-31"
        assert client.get(f"/api/retirement/inflation?target_date={date_string}").status_code == 200
        assert len(calls) == 1
        assert client.get("/api/retirement/history").json() == []


def test_retirement_migration_preserves_legacy_goals(tmp_path):
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20261101_24_retirement_accumulation.py"
    )
    spec = importlib.util.spec_from_file_location("retirement_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = make_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id CHAR(32) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE financial_goals (id CHAR(32), name TEXT)"))
        connection.execute(text("INSERT INTO financial_goals VALUES ('a', 'Legacy retirement')"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        assert "retirement_history" in inspect(connection).get_table_names()
        saved = connection.execute(
            text("SELECT name, retirement_settings FROM financial_goals")
        ).one()
        assert saved.name == "Legacy retirement" and saved.retirement_settings is None
        with Operations.context(context):
            migration.downgrade()
        assert (
            connection.execute(text("SELECT name FROM financial_goals")).scalar_one()
            == "Legacy retirement"
        )
    engine.dispose()


def test_closed_deposit_releases_bank_principal_but_not_retirement_cash(tmp_path):
    with create_test_client(tmp_path) as client:
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "Retirement bank",
                "provider_code": "MANUAL",
                "account_type": "SAVINGS",
                "currency": "EUR",
                "opening_cash": "1000",
            },
        ).json()
        deposit = client.post(
            "/api/deposits",
            json={
                "account_id": account["id"],
                "subaccount_id": account["subaccounts"][0]["id"],
                "name": "Retirement term deposit",
                "principal": "1000",
                "start_date": date.today().isoformat(),
                "period_months": 12,
                "annual_profit_rate": "0.05",
                "capitalization": True,
            },
        )
        assert deposit.status_code == 201, deposit.text
        deposit_id = client.get("/api/dashboard").json()["deposits"][0]["id"]
        goal = client.post(
            "/api/goals",
            json=goal_payload(
                goal_type="retirement",
                target_amount=None,
                linked_account_ids=[account["id"]],
                fixed_deposit_allocations=[{"id": deposit_id}],
            ),
        )
        assert goal.status_code == 201, goal.text
        goal_id = goal.json()["id"]
        investment = RetirementInvestment(
            key=deposit_id,
            kind="deposit",
            asset_id=deposit_id,
            name="Deposit",
            lower_return=0,
            upper_return=0,
        )
        payload = settings([investment]).model_dump(mode="json")
        payload["target_date"] = add_months(date.today(), 24).isoformat()
        projection = client.put(f"/api/goals/{goal_id}/retirement", json=payload)
        assert projection.status_code == 200, projection.text
        assert end(projection.json()) > 1000
        impact = client.get(f"/api/retirement/asset-impact/deposit/{deposit_id}").json()
        assert impact[0]["name"] == "Retirement"
        assert client.delete(f"/api/deposits/{deposit_id}").status_code == 204
        assert end(client.get(f"/api/goals/{goal_id}/retirement").json()) == 0
        assert D(client.get("/api/dashboard").json()["totals"]["available_cash"]) == 1000


def test_future_deposits_cap_each_payment_at_its_own_maturity():
    investment = RetirementInvestment(
        key="future",
        kind="future_deposit",
        name="Future deposits",
        contribution_percentage=100,
        lower_return=D("0.12"),
        upper_return=D("0.12"),
        deposit_term_months=1,
        tax_rate=0,
    )
    asset = RetirementAsset(investment, D(0), D(0), D(0))
    result = project_retirement(
        settings([investment], months=3, contribution_amount=100),
        [asset],
        TODAY,
    )
    expected = (
        D(100) * D("1.12") ** (D(28) / D("365.25"))
        + D(100) * D("1.12") ** (D(31) / D("365.25"))
        + D(100)
    )
    assert abs(end(result) - expected) < D("0.000001")


def test_history_permissions_and_currency_are_explicit(tmp_path):
    with create_test_client(tmp_path) as client:
        invalid = client.post(
            "/api/retirement/history",
            json={
                "name": "History",
                "currency": "EUR",
                "source": "Licensed source",
                "license": "Local use",
                "personal_storage_permitted": False,
                "total_return_confirmed": True,
                "csv": "date,total_return_index\n2000-01-31,100\n2000-02-29,110\n",
            },
        )
        assert invalid.status_code == 422
        assert client.get("/api/retirement/history").json() == []


def test_history_limit_excludes_the_world_cpi_cache(tmp_path):
    with create_test_client(tmp_path) as client:
        user_id = UUID(client.get("/api/auth/me").json()["id"])
        with client.app.state.session_factory() as session:
            session.add_all(
                [
                    RetirementHistory(
                        user_id=user_id,
                        name=f"Test fixture {i}",
                        currency="EUR",
                        source="Synthetic fixture",
                        license="Test only",
                        observations=history([100, 101]),
                    )
                    for i in range(199)
                ]
            )
            session.add(
                RetirementHistory(
                    user_id=user_id,
                    name="CPI cache",
                    currency="WLD",
                    source="Synthetic fixture",
                    license="Test only",
                    observations=[{"date": "2020-12-31", "rate": "0.02"}],
                )
            )
            session.commit()
        payload = {
            "name": "Final permitted dataset",
            "currency": "EUR",
            "source": "Synthetic fixture",
            "license": "Test only",
            "personal_storage_permitted": True,
            "total_return_confirmed": True,
            "csv": "date,total_return_index\n2000-01-31,100\n2000-02-29,110\n",
        }
        assert client.post("/api/retirement/history", json=payload).status_code == 201
        assert len(client.get("/api/retirement/history").json()) == 200
        assert client.post("/api/retirement/history", json=payload).status_code == 422
