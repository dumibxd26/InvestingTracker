from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.cash_flow_logic import add_months
from app.config import Settings
from app.database import Base, make_engine
from app.main import create_app
from app.market_data import ExchangeRateQuote, MarketQuote, MarketSymbol
from app.models import (
    AccountSubaccount,
    AssetClass,
    CashFlow,
    CompoundingFrequency,
    Currency,
    FixedDeposit,
    Holding,
    Instrument,
    MarketFXRate,
    MarketPriceCache,
    RateBasis,
    User,
)


@contextmanager
def create_test_client(tmp_path, authenticated: bool = True) -> Iterator[TestClient]:
    test_engine = make_engine(f"sqlite:///{tmp_path / 'northstar-test.db'}")
    Base.metadata.create_all(bind=test_engine)
    factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    app = create_app(factory)
    app.state.session_factory = factory
    with TestClient(app) as client:
        if authenticated:
            registration = client.post(
                "/api/auth/register",
                json={
                    "username": f"test_{uuid4().hex[:12]}",
                    "password": "test-passphrase-for-northstar",
                    "display_name": "Test user",
                    "base_currency": "EUR",
                },
            )
            assert registration.status_code == 201, registration.text
            client.headers.update(
                {"Authorization": f"Bearer {registration.json()['access_token']}"}
            )
        yield client


def test_new_user_dashboard_starts_blank_and_supports_same_value_currency_switch(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        euro_response = client.get("/api/dashboard")
        dollar_response = client.get("/api/dashboard?currency=USD")

    assert euro_response.status_code == 200
    assert dollar_response.status_code == 200
    euro_dashboard = euro_response.json()
    dollar_dashboard = dollar_response.json()
    assert euro_dashboard["base_currency"] == "EUR"
    assert dollar_dashboard["base_currency"] == "USD"
    assert euro_dashboard["sample_data"] is False
    assert euro_dashboard["warnings"] == []
    assert Decimal(euro_dashboard["totals"]["net_worth"]) == 0
    assert Decimal(dollar_dashboard["totals"]["net_worth"]) == 0
    assert euro_dashboard["accounts"] == []
    assert euro_dashboard["holdings"] == []
    assert euro_dashboard["goals"] == []
    assert euro_dashboard["profile"]["username"].startswith("test_")
    assert len(euro_dashboard["chart"]) == 1
    assert client.get("/api/policy").json()["funding_rule"] is None
    assert (
        client.post(
            "/api/recommendations/preview",
            json={"amount": "100", "currency": "EUR"},
        ).status_code
        == 409
    )


def test_personal_financial_endpoints_require_a_valid_application_session(tmp_path) -> None:
    with create_test_client(tmp_path, authenticated=False) as client:
        responses = [
            client.get("/api/auth/me"),
            client.get("/api/profile"),
            client.get("/api/dashboard"),
            client.get("/api/accounts"),
            client.get("/api/goals"),
            client.get("/api/policy"),
            client.get("/api/cash-flows"),
            client.get("/api/cash-flow-schedules"),
            client.delete(f"/api/accounts/{uuid4()}"),
            client.post("/api/portfolio/initialize", json={"accounts": []}),
            client.post(
                f"/api/accounts/{uuid4()}/subaccounts",
                json={"currency": "USD", "opening_balance": "0"},
            ),
            client.get("/api/market/status"),
            client.get("/api/market/search?q=MSFT"),
            client.post("/api/market/refresh"),
            client.post("/api/holdings"),
            client.put(
                f"/api/holdings/{uuid4()}",
                json={"quantity": "1", "average_cost": "100"},
            ),
            client.delete(f"/api/holdings/{uuid4()}"),
        ]

    assert [response.status_code for response in responses] == [401] * len(responses)


def test_registration_login_and_logout_use_hashed_passwords(tmp_path) -> None:
    with create_test_client(tmp_path, authenticated=False) as client:
        payload = {
            "username": f"wealth_owner_{uuid4().hex[:8]}",
            "password": "correct-horse-battery-77",
            "display_name": "Wealth Owner",
            "base_currency": "EUR",
        }
        registered = client.post("/api/auth/register", json=payload)
        assert registered.status_code == 201, registered.text
        user_id = UUID(registered.json()["user"]["id"])
        access_token = registered.json()["access_token"]

        with client.app.state.session_factory() as session:
            stored_user = session.get(User, user_id)
            assert stored_user is not None
            assert stored_user.password_hash != payload["password"]
            assert stored_user.password_hash.startswith("$argon2")

        duplicate = client.post("/api/auth/register", json=payload)
        bad_login = client.post(
            "/api/auth/login",
            json={"username": payload["username"], "password": "incorrect-password"},
        )
        login = client.post(
            "/api/auth/login",
            json={"username": payload["username"], "password": payload["password"]},
        )
        assert duplicate.status_code == 409
        assert bad_login.status_code == 401
        assert login.status_code == 200, login.text
        assert login.json()["user"]["username"] == payload["username"]

        client.headers.update({"Authorization": f"Bearer {access_token}"})
        assert client.get("/api/auth/me").status_code == 200
        logout = client.post("/api/auth/logout")
        assert logout.status_code == 204
        assert client.get("/api/accounts").status_code == 401


def test_users_cannot_see_each_others_accounts_or_goals(tmp_path) -> None:
    with create_test_client(tmp_path, authenticated=False) as client:
        first_username = f"first_owner_{uuid4().hex[:8]}"
        second_username = f"second_owner_{uuid4().hex[:8]}"
        first = client.post(
            "/api/auth/register",
            json={
                "username": first_username,
                "password": "correct-horse-battery-88",
                "base_currency": "EUR",
            },
        )
        assert first.status_code == 201, first.text
        client.headers.update({"Authorization": f"Bearer {first.json()['access_token']}"})
        created = client.post(
            "/api/accounts",
            json={
                "display_name": "First owner bank",
                "provider_code": "MANUAL",
                "account_type": "BANK",
                "currency": "EUR",
                "opening_cash": "425.50",
            },
        )
        assert created.status_code == 201, created.text
        first_account_id = created.json()["id"]
        first_balance = client.get("/api/dashboard").json()["totals"]["available_cash"]

        second = client.post(
            "/api/auth/register",
            json={
                "username": second_username,
                "password": "correct-horse-battery-99",
                "base_currency": "EUR",
            },
        )
        assert second.status_code == 201, second.text
        client.headers.update({"Authorization": f"Bearer {second.json()['access_token']}"})
        foreign_account_delete = client.delete(f"/api/accounts/{first_account_id}")
        foreign_subaccount_create = client.post(
            f"/api/accounts/{first_account_id}/subaccounts",
            json={"currency": "USD", "opening_balance": "0"},
        )
        second_dashboard = client.get("/api/dashboard").json()

        client.headers.update({"Authorization": f"Bearer {first.json()['access_token']}"})
        first_accounts = client.get("/api/accounts").json()

    assert Decimal(first_balance) == Decimal("425.50")
    assert second_dashboard["profile"]["username"] == second_username
    assert second_dashboard["accounts"] == []
    assert Decimal(second_dashboard["totals"]["available_cash"]) == 0
    assert second_dashboard["goals"] == []
    assert foreign_account_delete.status_code == 404
    assert foreign_subaccount_create.status_code == 404
    assert [account["display_name"] for account in first_accounts] == ["First owner bank"]


def test_signup_fx_setting_is_per_user_and_not_a_seeded_global_rate(tmp_path) -> None:
    with create_test_client(tmp_path, authenticated=False) as client:
        registration = client.post(
            "/api/auth/register",
            json={
                "username": "fx_owner",
                "password": "correct-horse-battery-fx",
                "base_currency": "EUR",
                "usd_per_eur": "1.25",
            },
        )
        assert registration.status_code == 201, registration.text
        client.headers.update({"Authorization": f"Bearer {registration.json()['access_token']}"})
        usd_account = client.post(
            "/api/accounts",
            json={
                "display_name": "USD brokerage",
                "provider_code": "MANUAL",
                "account_type": "BROKERAGE",
                "currency": "USD",
                "opening_cash": "125",
            },
        )
        dashboard = client.get("/api/dashboard")

    assert usd_account.status_code == 201, usd_account.text
    assert Decimal(dashboard.json()["totals"]["available_cash"]) == Decimal("100")
    assert dashboard.json()["profile"]["usd_per_eur"] == "1.2500000000"


def test_cross_currency_valuation_requires_user_configured_fx_rate(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        created = client.post(
            "/api/accounts",
            json={
                "display_name": "USD savings",
                "provider_code": "MANUAL",
                "account_type": "SAVINGS",
                "currency": "USD",
                "opening_cash": "125",
            },
        )
        dashboard = client.get("/api/dashboard")

    assert created.status_code == 409
    assert "manual USD-per-EUR" in created.json()["detail"]
    assert dashboard.status_code == 200


def test_cached_provider_fx_rates_value_eur_usd_and_ron_accounts(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        observed_at = datetime.now(UTC)
        with client.app.state.session_factory() as session:
            session.add_all(
                [
                    MarketFXRate(
                        base_currency=Currency.EUR,
                        quote_currency=Currency.USD,
                        rate=Decimal("1.25"),
                        provider="Twelve Data",
                        observed_at=observed_at,
                    ),
                    MarketFXRate(
                        base_currency=Currency.EUR,
                        quote_currency=Currency.RON,
                        rate=Decimal("5"),
                        provider="Twelve Data",
                        observed_at=observed_at,
                    ),
                    MarketFXRate(
                        base_currency=Currency.USD,
                        quote_currency=Currency.RON,
                        rate=Decimal("4"),
                        provider="Twelve Data",
                        observed_at=observed_at,
                    ),
                ]
            )
            session.commit()

        usd_account = client.post(
            "/api/accounts",
            json={
                "display_name": "US brokerage",
                "provider_code": "MANUAL",
                "account_type": "BROKERAGE",
                "currency": "USD",
                "opening_cash": "100",
            },
        )
        ron_account = client.post(
            "/api/accounts",
            json={
                "display_name": "RON bank",
                "provider_code": "MANUAL",
                "account_type": "BANK",
                "currency": "RON",
                "opening_cash": "500",
            },
        )
        dashboard = client.get("/api/dashboard")

    assert usd_account.status_code == 201, usd_account.text
    assert ron_account.status_code == 201, ron_account.text
    assert Decimal(dashboard.json()["totals"]["available_cash"]) == Decimal("180.00")


def test_search_and_add_holding_use_provider_results_and_quote_fx(monkeypatch, tmp_path) -> None:
    import app.services as services

    class FakeTwelveDataClient:
        def __init__(self, api_key: str, timeout_seconds: float = 10) -> None:
            assert api_key == "test-provider-key"
            assert timeout_seconds == 10

        async def search_symbols(self, query: str) -> list[MarketSymbol]:
            assert query == "MSFT"
            return [
                MarketSymbol(
                    symbol="MSFT",
                    name="Microsoft Corporation",
                    exchange="NASDAQ",
                    mic_code="XNAS",
                    currency=Currency.USD,
                    instrument_type="STOCK",
                    country="United States",
                )
            ]

        async def quote(
            self, symbol: str, mic_code: str | None = None, exchange: str | None = None
        ) -> MarketQuote:
            assert symbol == "MSFT"
            assert mic_code == "XNAS"
            return MarketQuote(
                symbol="MSFT",
                name="Microsoft Corporation",
                price=Decimal("400"),
                currency=Currency.USD,
                observed_at=datetime(2026, 10, 10, 12, tzinfo=UTC),
                is_market_open=True,
                mic_code="XNAS",
                exchange="NASDAQ",
            )

        async def exchange_rate(self, pair: str) -> ExchangeRateQuote:
            assert pair == "USD/EUR"
            return ExchangeRateQuote(
                base_currency=Currency.USD,
                quote_currency=Currency.EUR,
                rate=Decimal("0.8"),
                observed_at=datetime(2026, 10, 10, 12, tzinfo=UTC),
            )

    monkeypatch.setattr(
        services, "get_settings", lambda: Settings(twelve_data_api_key="test-provider-key")
    )
    monkeypatch.setattr(services, "TwelveDataClient", FakeTwelveDataClient)

    with create_test_client(tmp_path) as client:
        search = client.get("/api/market/search?q=MSFT")
        fx_profile = client.put(
            "/api/profile",
            json={
                "display_name": "Test user",
                "base_currency": "EUR",
                "usd_per_eur": "1.25",
            },
        )
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "USD brokerage",
                "provider_code": "MANUAL",
                "account_type": "BROKERAGE",
                "currency": "USD",
                "opening_cash": "2000",
            },
        )
        eur_wallet = client.post(
            f"/api/accounts/{account.json()['id']}/subaccounts",
            json={"currency": "EUR", "opening_balance": "1000"},
        )
        holding_payload = {
            "account_id": account.json()["id"],
            "subaccount_id": eur_wallet.json()["id"],
            "symbol": "MSFT",
            "mic_code": "XNAS",
            "exchange": "NASDAQ",
            "instrument_type": "STOCK",
            "quantity": "2",
            "average_cost": "300",
        }
        insufficient = client.post(
            "/api/holdings",
            json={**holding_payload, "average_cost": "1100"},
        )
        before_buy_dashboard = client.get("/api/dashboard").json()
        added = client.post(
            "/api/holdings",
            json=holding_payload,
        )
        dashboard = client.get("/api/dashboard")
        holding_id = dashboard.json()["holdings"][0]["id"]
        update = client.put(
            f"/api/holdings/{holding_id}",
            json={
                "quantity": "3",
                "average_cost": "350",
                "purchase_date": "2024-06-15",
            },
        )
        updated_dashboard = client.get("/api/dashboard")

        owner_authorization = client.headers["Authorization"]
        second_user = client.post(
            "/api/auth/register",
            json={
                "username": f"other_owner_{uuid4().hex[:8]}",
                "password": "another-long-test-passphrase",
                "base_currency": "EUR",
            },
        )
        client.headers.update(
            {"Authorization": f"Bearer {second_user.json()['access_token']}"}
        )
        other_user_update = client.put(
            f"/api/holdings/{holding_id}",
            json={"quantity": "9", "average_cost": "100"},
        )
        other_user_delete = client.delete(f"/api/holdings/{holding_id}")
        missing_holding_delete = client.delete(f"/api/holdings/{uuid4()}")
        client.headers.update({"Authorization": owner_authorization})
        delete = client.delete(f"/api/holdings/{holding_id}")
        deleted_dashboard = client.get("/api/dashboard")

    assert search.status_code == 200, search.text
    assert search.json()["results"][0]["symbol"] == "MSFT"
    assert fx_profile.status_code == 200, fx_profile.text
    assert account.status_code == 201, account.text
    assert insufficient.status_code == 409
    assert Decimal(before_buy_dashboard["totals"]["available_cash"]) == Decimal("2600.00")
    assert added.status_code == 201, added.text
    assert added.json()["funding_currency"] == "EUR"
    assert Decimal(added.json()["funding_cost"]) == Decimal("480.00")
    assert dashboard.json()["holdings"][0]["purchase_date"] == date.today().isoformat()
    assert Decimal(dashboard.json()["holdings"][0]["gross_market_value"]) == Decimal("640.00")
    assert Decimal(dashboard.json()["holdings"][0]["estimated_sale_tax"]) == Decimal("4.80")
    assert Decimal(dashboard.json()["holdings"][0]["market_value"]) == Decimal("635.20")
    assert dashboard.json()["holdings"][0]["quote_source"] == "TWELVE_DATA"
    assert Decimal(dashboard.json()["totals"]["available_cash"]) == Decimal("2120.00")
    assert update.status_code == 204, update.text
    assert Decimal(updated_dashboard.json()["holdings"][0]["quantity"]) == Decimal("3")
    assert Decimal(updated_dashboard.json()["holdings"][0]["average_cost"]) == Decimal("350")
    assert updated_dashboard.json()["holdings"][0]["purchase_date"] == "2024-06-15"
    assert (
        Decimal(updated_dashboard.json()["holdings"][0]["gross_market_value"])
        == Decimal("960.00")
    )
    assert Decimal(updated_dashboard.json()["holdings"][0]["estimated_sale_tax"]) == Decimal("3.60")
    assert Decimal(updated_dashboard.json()["holdings"][0]["market_value"]) == Decimal("956.40")
    assert Decimal(updated_dashboard.json()["totals"]["invested_assets"]) == Decimal("956.40")
    assert Decimal(updated_dashboard.json()["totals"]["net_worth"]) == Decimal("2716.40")
    assert Decimal(updated_dashboard.json()["totals"]["available_cash"]) == Decimal("1760.00")
    account_value = updated_dashboard.json()["account_wealth"][0]
    assert account_value["display_name"] == "USD brokerage"
    assert Decimal(account_value["cash_value"]) == Decimal("1760.00")
    assert Decimal(account_value["gross_holdings_value"]) == Decimal("960.00")
    assert Decimal(account_value["estimated_sale_tax"]) == Decimal("3.60")
    assert Decimal(account_value["after_tax_holdings_value"]) == Decimal("956.40")
    assert Decimal(account_value["total_after_tax_value"]) == Decimal("2716.40")
    assert other_user_update.status_code == 404
    assert other_user_delete.status_code == 404
    assert missing_holding_delete.status_code == 404
    assert delete.status_code == 204, delete.text
    assert deleted_dashboard.json()["holdings"] == []
    assert Decimal(deleted_dashboard.json()["totals"]["available_cash"]) == Decimal("2600.00")


def test_foreign_currency_goal_schedule_and_fx_removal_need_a_manual_rate(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "EUR current account",
                "provider_code": "MANUAL",
                "account_type": "BANK",
                "currency": "EUR",
                "opening_cash": "100",
            },
        )
        goal = client.post(
            "/api/goals",
            json={
                "name": "USD purchase",
                "goal_type": "purchase",
                "target_amount": "1000",
                "target_currency": "USD",
                "priority": 2,
                "risk_level": "low",
                "monthly_contribution": "100",
                "flexibility": "essential",
            },
        )
        schedule = client.post(
            "/api/cash-flow-schedules",
            json={
                "label": "USD salary",
                "kind": "salary",
                "amount": "1000",
                "currency": "USD",
                "recurrence": "monthly",
                "start_date": date.today().isoformat(),
            },
        )
        fx = client.put(
            "/api/profile",
            json={
                "display_name": "Test user",
                "base_currency": "EUR",
                "usd_per_eur": "1.08",
            },
        )
        foreign_goal = client.post(
            "/api/goals",
            json={
                "name": "USD purchase",
                "goal_type": "purchase",
                "target_amount": "1000",
                "target_currency": "USD",
                "priority": 2,
                "risk_level": "low",
                "monthly_contribution": "100",
                "flexibility": "essential",
            },
        )
        clear_fx = client.put(
            "/api/profile",
            json={
                "display_name": "Test user",
                "base_currency": "EUR",
                "usd_per_eur": None,
            },
        )
        dashboard = client.get("/api/dashboard")

    assert account.status_code == 201, account.text
    assert goal.status_code == 409
    assert schedule.status_code == 409
    assert fx.status_code == 200, fx.text
    assert foreign_goal.status_code == 201, foreign_goal.text
    assert clear_fx.status_code == 409
    assert dashboard.status_code == 200


def test_allocation_preview_conserves_the_investable_budget(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        goal = client.post(
            "/api/goals",
            json={
                "name": "Long term",
                "goal_type": "wealth",
                "target_amount": "50000",
                "target_currency": "EUR",
                "monthly_contribution": "600",
                "priority": 1,
                "risk_level": "moderate",
                "flexibility": "flexible",
            },
        )
        policy = client.put(
            "/api/policy",
            json={
                "funding_rule": "priority_first",
                "emergency_reserve": "0",
                "target_weights": {
                    "equities": "0.70",
                    "fixed_income": "0.15",
                    "satellite": "0.15",
                },
            },
        )
        response = client.post(
            "/api/recommendations/preview",
            json={"amount": "1000.00", "currency": "EUR"},
        )

    assert goal.status_code == 201, goal.text
    assert policy.status_code == 200, policy.text
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


def test_goal_can_be_updated_archived_and_is_user_scoped(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        created = client.post(
            "/api/goals",
            json={
                "name": "Starter goal",
                "goal_type": "purchase",
                "target_amount": "10000",
                "current_amount": "1000",
                "target_currency": "EUR",
                "priority": 4,
                "risk_level": "low",
                "monthly_contribution": "200",
                "flexibility": "flexible",
            },
        )
        goal_id = created.json()["id"]
        updated = client.put(
            f"/api/goals/{goal_id}",
            json={
                "name": "Home down payment",
                "goal_type": "purchase",
                "target_amount": "25000",
                "current_amount": "4500",
                "current_annual_income": "0",
                "target_currency": "EUR",
                "target_date": "2032-05-01",
                "priority": 1,
                "risk_level": "moderate",
                "monthly_contribution": "500",
                "fixed_percent": "0.4",
                "flexibility": "essential",
            },
        )
        owner_authorization = client.headers["Authorization"]
        second_user = client.post(
            "/api/auth/register",
            json={
                "username": f"goal_owner_{uuid4().hex[:8]}",
                "password": "another-long-test-passphrase",
                "base_currency": "EUR",
            },
        )
        client.headers.update(
            {"Authorization": "Bearer " + second_user.json()["access_token"]}
        )
        other_user_update = client.put(
            f"/api/goals/{goal_id}",
            json={
                "name": "Someone else's goal",
                "goal_type": "purchase",
                "target_amount": "1",
                "target_currency": "EUR",
                "priority": 1,
                "risk_level": "low",
                "monthly_contribution": "0",
                "flexibility": "flexible",
            },
        )
        other_user_delete = client.delete(f"/api/goals/{goal_id}")
        client.headers.update({"Authorization": owner_authorization})
        deleted = client.delete(f"/api/goals/{goal_id}")
        active_goals = client.get("/api/goals")
        dashboard = client.get("/api/dashboard")
        repeated_delete = client.delete(f"/api/goals/{goal_id}")

    assert created.status_code == 201, created.text
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Home down payment"
    assert Decimal(updated.json()["target_amount"]) == 25000
    assert Decimal(updated.json()["current_amount"]) == 4500
    assert updated.json()["target_date"] == "2032-05-01"
    assert second_user.status_code == 201, second_user.text
    assert other_user_update.status_code == 404
    assert other_user_delete.status_code == 404
    assert deleted.status_code == 204
    assert active_goals.json() == []
    assert dashboard.json()["goals"] == []
    assert repeated_delete.status_code == 404


def test_archiving_goal_keeps_fixed_funding_shares_valid(tmp_path) -> None:
    base_payload = {
        "goal_type": "wealth",
        "target_amount": "10000",
        "target_currency": "EUR",
        "priority": 1,
        "risk_level": "moderate",
        "monthly_contribution": "100",
        "flexibility": "flexible",
    }
    with create_test_client(tmp_path) as client:
        first = client.post(
            "/api/goals",
            json={**base_payload, "name": "First goal", "fixed_percent": "0.6"},
        )
        second = client.post(
            "/api/goals",
            json={**base_payload, "name": "Second goal", "priority": 2, "fixed_percent": "0.4"},
        )
        policy = client.put(
            "/api/policy",
            json={
                "funding_rule": "fixed_percentages",
                "emergency_reserve": "0",
                "target_weights": {
                    "equities": "0.70",
                    "fixed_income": "0.15",
                    "satellite": "0.15",
                },
            },
        )
        delete_first = client.delete(f"/api/goals/{first.json()['id']}")
        after_first = client.get("/api/goals").json()
        policy_after_first = client.get("/api/policy").json()
        delete_second = client.delete(f"/api/goals/{second.json()['id']}")
        policy_after_last = client.get("/api/policy").json()

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert policy.status_code == 200, policy.text
    assert delete_first.status_code == 204
    assert len(after_first) == 1
    assert after_first[0]["id"] == second.json()["id"]
    assert Decimal(after_first[0]["fixed_percent"]) == 1
    assert policy_after_first["funding_rule"] == "fixed_percentages"
    assert delete_second.status_code == 204
    assert policy_after_last["funding_rule"] is None


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


def test_creating_an_account_persists_cash_and_rejects_duplicate_names(tmp_path) -> None:
    payload = {
        "display_name": "Holiday savings",
        "provider_code": "MANUAL",
        "account_type": "SAVINGS",
        "currency": "EUR",
        "opening_cash": "1250.50",
    }
    with create_test_client(tmp_path) as client:
        initial_balance = Decimal(client.get("/api/dashboard").json()["totals"]["available_cash"])
        created = client.post("/api/accounts", json=payload)
        accounts = client.get("/api/accounts").json()
        dashboard = client.get("/api/dashboard").json()
        duplicate = client.post("/api/accounts", json=payload)

    assert created.status_code == 201, created.text
    account = created.json()
    assert account["display_name"] == "Holiday savings"
    assert account["cash_balance"] == "1250.5000"
    assert account["position_count"] == 0
    assert account["is_sample"] is False
    assert any(row["id"] == account["id"] for row in accounts)
    assert Decimal(dashboard["totals"]["available_cash"]) == initial_balance + Decimal("1250.50")
    assert duplicate.status_code == 409


def test_account_subaccounts_are_unique_and_balance_by_currency(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        profile = client.put(
            "/api/profile",
            json={
                "display_name": "Test user",
                "base_currency": "EUR",
                "usd_per_eur": "1.25",
            },
        )
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "Multi-currency broker",
                "provider_code": "MANUAL",
                "account_type": "BROKERAGE",
                "currency": "EUR",
                "opening_cash": "100",
            },
        )
        usd_wallet = client.post(
            f"/api/accounts/{account.json()['id']}/subaccounts",
            json={"currency": "USD", "opening_balance": "50"},
        )
        duplicate = client.post(
            f"/api/accounts/{account.json()['id']}/subaccounts",
            json={"currency": "USD", "opening_balance": "10"},
        )
        ron_wallet = client.post(
            f"/api/accounts/{account.json()['id']}/subaccounts",
            json={"currency": "RON", "opening_balance": "0"},
        )
        dashboard = client.get("/api/dashboard")
        accounts = client.get("/api/accounts")

    assert profile.status_code == 200, profile.text
    assert account.status_code == 201, account.text
    assert account.json()["subaccounts"][0]["is_primary"] is True
    assert account.json()["subaccounts"][0]["currency"] == "EUR"
    assert usd_wallet.status_code == 201, usd_wallet.text
    assert duplicate.status_code == 409
    assert ron_wallet.status_code == 201, ron_wallet.text
    assert len(accounts.json()[0]["subaccounts"]) == 3
    assert Decimal(dashboard.json()["totals"]["available_cash"]) == Decimal("140.00")


def test_initial_portfolio_setup_creates_accounts_wallets_and_owned_stocks_atomically(
    monkeypatch, tmp_path
) -> None:
    import app.services as services

    class FakeTwelveDataClient:
        def __init__(self, api_key: str, timeout_seconds: float = 10) -> None:
            assert api_key == "test-provider-key"
            assert timeout_seconds == 10

        async def quote(
            self, symbol: str, mic_code: str | None = None, exchange: str | None = None
        ) -> MarketQuote:
            assert symbol == "AAPL"
            assert mic_code == "XNAS"
            assert exchange == "NASDAQ"
            return MarketQuote(
                symbol="AAPL",
                name="Apple Inc.",
                price=Decimal("225"),
                currency=Currency.USD,
                observed_at=datetime(2026, 10, 11, 12, tzinfo=UTC),
                is_market_open=True,
                mic_code="XNAS",
                exchange="NASDAQ",
            )

    monkeypatch.setattr(
        services, "get_settings", lambda: Settings(twelve_data_api_key="test-provider-key")
    )
    monkeypatch.setattr(services, "TwelveDataClient", FakeTwelveDataClient)

    with create_test_client(tmp_path) as client:
        profile = client.put(
            "/api/profile",
            json={
                "display_name": "Test user",
                "base_currency": "EUR",
                "usd_per_eur": "1.25",
            },
        )
        initialized = client.post(
            "/api/portfolio/initialize",
            json={
                "accounts": [
                    {
                        "display_name": "Daily bank",
                        "provider_code": "MANUAL",
                        "account_type": "BANK",
                        "subaccounts": [{"currency": "EUR", "opening_balance": "1000"}],
                    },
                    {
                        "display_name": "Main broker",
                        "provider_code": "INTERACTIVE_BROKERS",
                        "account_type": "BROKERAGE",
                        "subaccounts": [
                            {"currency": "USD", "opening_balance": "2000"},
                            {"currency": "EUR", "opening_balance": "500"},
                        ],
                    },
                ],
                "holdings": [
                    {
                        "account_index": 1,
                        "symbol": "AAPL",
                        "mic_code": "XNAS",
                        "exchange": "NASDAQ",
                        "instrument_type": "STOCK",
                        "quantity": "2",
                        "average_cost": "300",
                        "average_cost_currency": "EUR",
                    }
                ],
            },
        )
        dashboard = client.get("/api/dashboard")

    assert profile.status_code == 200, profile.text
    assert initialized.status_code == 201, initialized.text
    assert len(initialized.json()["accounts"]) == 2
    broker = next(
        account
        for account in initialized.json()["accounts"]
        if account["display_name"] == "Main broker"
    )
    assert {wallet["currency"] for wallet in broker["subaccounts"]} == {"USD", "EUR"}
    assert [wallet["currency"] for wallet in broker["subaccounts"] if wallet["is_primary"]] == [
        "USD"
    ]
    assert initialized.json()["holdings"][0]["symbol"] == "AAPL"
    assert initialized.json()["holdings"][0]["funding_currency"] is None
    assert Decimal(initialized.json()["holdings"][0]["funding_cost"]) == 0
    snapshot = dashboard.json()
    assert len(snapshot["accounts"]) == 2
    assert snapshot["holdings"][0]["symbol"] == "AAPL"
    assert Decimal(snapshot["holdings"][0]["average_cost"]) == Decimal("375.00")
    assert snapshot["holdings"][0]["purchase_date"] == "2025-01-01"
    assert Decimal(snapshot["totals"]["available_cash"]) == Decimal("3100.00")
    assert Decimal(snapshot["totals"]["invested_assets"]) == Decimal("360.00")
    assert "unrealized_pnl_estimate" not in snapshot["totals"]
    assert "change_percent" not in snapshot["holdings"][0]


def test_initial_portfolio_setup_preserves_current_cash_when_importing_owned_positions(
    monkeypatch, tmp_path
) -> None:
    import app.services as services

    class FakeTwelveDataClient:
        def __init__(self, api_key: str, timeout_seconds: float = 10) -> None:
            pass

        async def quote(
            self, symbol: str, mic_code: str | None = None, exchange: str | None = None
        ) -> MarketQuote:
            return MarketQuote(
                symbol="MSFT",
                name="Microsoft Corporation",
                price=Decimal("400"),
                currency=Currency.USD,
                observed_at=datetime(2026, 10, 11, 12, tzinfo=UTC),
                is_market_open=True,
                mic_code="XNAS",
                exchange="NASDAQ",
            )

    monkeypatch.setattr(
        services, "get_settings", lambda: Settings(twelve_data_api_key="test-provider-key")
    )
    monkeypatch.setattr(services, "TwelveDataClient", FakeTwelveDataClient)

    with create_test_client(tmp_path) as client:
        client.put(
            "/api/profile",
            json={
                "display_name": "Test user",
                "base_currency": "EUR",
                "usd_per_eur": "1.25",
            },
        )
        response = client.post(
            "/api/portfolio/initialize",
            json={
                "accounts": [
                    {
                        "display_name": "My broker",
                        "provider_code": "MANUAL",
                        "account_type": "BROKERAGE",
                        "subaccounts": [{"currency": "USD", "opening_balance": "100"}],
                    }
                ],
                "holdings": [
                    {
                        "account_index": 0,
                        "symbol": "MSFT",
                        "mic_code": "XNAS",
                        "exchange": "NASDAQ",
                        "instrument_type": "STOCK",
                        "quantity": "1",
                        "average_cost": "200",
                    }
                ],
            },
        )
        accounts = client.get("/api/accounts").json()
        dashboard = client.get("/api/dashboard").json()

    assert response.status_code == 201, response.text
    assert [account["display_name"] for account in accounts] == ["My broker"]
    assert Decimal(dashboard["accounts"][0]["subaccounts"][0]["cash_balance"]) == Decimal("100")
    assert dashboard["holdings"][0]["symbol"] == "MSFT"
    assert Decimal(dashboard["totals"]["available_cash"]) == Decimal("80.00")


def test_deleting_account_removes_attached_assets_but_preserves_cash_flow_history(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        user_id = UUID(client.get("/api/auth/me").json()["id"])
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "Savings to remove",
                "provider_code": "MANUAL",
                "account_type": "SAVINGS",
                "currency": "EUR",
                "opening_cash": "100",
            },
        )
        assert account.status_code == 201, account.text
        account_id = UUID(account.json()["id"])
        cash_flow = client.post(
            "/api/cash-flows/extra-cash",
            json={
                "account_id": str(account_id),
                "source": "Old transfer",
                "amount": "25",
                "received_date": date.today().isoformat(),
                "idempotency_key": str(uuid4()),
            },
        )
        assert cash_flow.status_code == 201, cash_flow.text

        with client.app.state.session_factory() as session:
            primary_subaccount = session.scalar(
                select(AccountSubaccount).where(
                    AccountSubaccount.account_id == account_id,
                    AccountSubaccount.is_primary.is_(True),
                )
            )
            assert primary_subaccount is not None
            instrument = Instrument(
                symbol=f"DEL{uuid4().hex[:8].upper()}",
                name="Test security",
                asset_class=AssetClass.EQUITIES,
                currency=Currency.EUR,
                mic="XNAS",
                estimated_annual_yield=Decimal("0"),
                is_demo=False,
            )
            session.add(instrument)
            session.flush()
            holding = Holding(
                user_id=user_id,
                account_id=account_id,
                funding_subaccount_id=primary_subaccount.id,
                instrument_id=instrument.id,
                quantity=Decimal("2"),
                average_cost=Decimal("10"),
            )
            deposit = FixedDeposit(
                user_id=user_id,
                account_id=account_id,
                name="Linked term deposit",
                principal=Decimal("500"),
                currency=Currency.EUR,
                annual_rate=Decimal("0.03"),
                rate_basis=RateBasis.NOMINAL_APR,
                compounding=CompoundingFrequency.MONTHLY,
                start_date=date.today(),
                maturity_date=date.today() + timedelta(days=90),
            )
            session.add_all([holding, deposit])
            session.flush()
            holding_id = holding.id
            deposit_id = deposit.id
            session.commit()

        deleted = client.delete(f"/api/accounts/{account_id}")
        dashboard = client.get("/api/dashboard").json()
        with client.app.state.session_factory() as session:
            history = session.get(CashFlow, UUID(cash_flow.json()["id"]))
            remaining_holding = session.get(Holding, holding_id)
            remaining_deposit = session.get(FixedDeposit, deposit_id)

    assert deleted.status_code == 204, deleted.text
    assert dashboard["accounts"] == []
    assert dashboard["holdings"] == []
    assert Decimal(dashboard["totals"]["available_cash"]) == 0
    assert Decimal(dashboard["totals"]["fixed_deposits"]) == 0
    assert any(flow["id"] == cash_flow.json()["id"] for flow in dashboard["cash_flows"])
    assert history is not None
    assert history.account_id is None
    assert history.subaccount_id is None
    assert remaining_holding is None
    assert remaining_deposit is None


def test_recording_extra_cash_updates_account_once_and_is_a_confirmed_inflow(
    tmp_path,
) -> None:
    with create_test_client(tmp_path) as client:
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "Everyday bank",
                "provider_code": "MANUAL",
                "account_type": "BANK",
                "currency": "EUR",
                "opening_cash": "1000",
            },
        )
        assert account.status_code == 201, account.text
        initial_balance = Decimal(client.get("/api/dashboard").json()["totals"]["available_cash"])
        payload = {
            "account_id": account.json()["id"],
            "source": "Freelance payment",
            "amount": "425.75",
            "received_date": date.today().isoformat(),
            "idempotency_key": str(uuid4()),
        }
        received = client.post("/api/cash-flows/extra-cash", json=payload)
        after_first_receipt = Decimal(
            client.get("/api/dashboard").json()["totals"]["available_cash"]
        )
        duplicate = client.post("/api/cash-flows/extra-cash", json=payload)
        after_retry = Decimal(client.get("/api/dashboard").json()["totals"]["available_cash"])
        flows = client.get("/api/cash-flows").json()

    assert received.status_code == 201, received.text
    assert received.json()["status"] == "confirmed"
    assert received.json()["kind"] == "windfall"
    assert received.json()["direction"] == "inflow"
    assert Decimal(received.json()["amount"]) == Decimal("425.75")
    assert after_first_receipt == initial_balance + Decimal("425.75")
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == received.json()["id"]
    assert after_retry == after_first_receipt
    assert (
        len(
            [
                flow
                for flow in flows
                if flow["id"] == received.json()["id"] and flow["status"] == "confirmed"
            ]
        )
        == 1
    )


def test_extra_cash_rejects_accounts_owned_by_another_user(tmp_path) -> None:
    with create_test_client(tmp_path, authenticated=False) as client:
        first = client.post(
            "/api/auth/register",
            json={
                "username": f"cash_owner_{uuid4().hex[:8]}",
                "password": "correct-horse-battery-cash1",
                "base_currency": "EUR",
            },
        )
        assert first.status_code == 201, first.text
        client.headers.update({"Authorization": f"Bearer {first.json()['access_token']}"})
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "Private bank",
                "provider_code": "MANUAL",
                "account_type": "BANK",
                "currency": "EUR",
                "opening_cash": "0",
            },
        )
        assert account.status_code == 201, account.text
        second = client.post(
            "/api/auth/register",
            json={
                "username": f"cash_other_{uuid4().hex[:8]}",
                "password": "correct-horse-battery-cash2",
                "base_currency": "EUR",
            },
        )
        assert second.status_code == 201, second.text
        client.headers.update({"Authorization": f"Bearer {second.json()['access_token']}"})
        receipt = client.post(
            "/api/cash-flows/extra-cash",
            json={
                "account_id": account.json()["id"],
                "source": "Private gift",
                "amount": "100",
                "received_date": date.today().isoformat(),
                "idempotency_key": str(uuid4()),
            },
        )

    assert receipt.status_code == 404


def test_employer_plan_accounts_cannot_claim_liquid_opening_cash(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.post(
            "/api/accounts",
            json={
                "display_name": "Equity plan",
                "provider_code": "MANUAL",
                "account_type": "employer_plan",
                "currency": "EUR",
                "opening_cash": "100",
            },
        )

    assert response.status_code == 422


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
        before_dashboard = client.get("/api/dashboard").json()
        balance_before = before_dashboard["totals"]["available_cash"]
        wealth_before = before_dashboard["totals"]["net_worth"]
        created = client.post("/api/cash-flow-schedules", json=payload)
        flows = client.get("/api/cash-flows?months=12")
        dashboard = client.get("/api/dashboard").json()
        balance_after = dashboard["totals"]["available_cash"]
        wealth_after = dashboard["totals"]["net_worth"]

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
    assert wealth_after == wealth_before
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


def test_scheduled_salary_credits_selected_wallet_once_when_due(tmp_path) -> None:
    today = date.today()
    with create_test_client(tmp_path) as client:
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "Salary account",
                "provider_code": "MANUAL",
                "account_type": "BANK",
                "currency": "EUR",
                "opening_cash": "1000",
            },
        )
        wallet_id = account.json()["subaccounts"][0]["id"]
        schedule = client.post(
            "/api/cash-flow-schedules",
            json={
                "label": "Monthly salary",
                "kind": "salary",
                "amount": "5200",
                "currency": "EUR",
                "recurrence": "monthly",
                "start_date": today.isoformat(),
                "end_date": add_months(today, 2).isoformat(),
                "account_id": account.json()["id"],
                "subaccount_id": wallet_id,
                "auto_post": True,
            },
        )
        first_dashboard = client.get("/api/dashboard")
        first_flows = client.get("/api/cash-flows?months=12")
        second_dashboard = client.get("/api/dashboard")
        second_flows = client.get("/api/cash-flows?months=12")

    assert account.status_code == 201, account.text
    assert schedule.status_code == 201, schedule.text
    assert schedule.json()["auto_post"] is True
    assert schedule.json()["account_id"] == account.json()["id"]
    assert Decimal(first_dashboard.json()["accounts"][0]["subaccounts"][0]["cash_balance"]) == 6200
    assert Decimal(second_dashboard.json()["accounts"][0]["subaccounts"][0]["cash_balance"]) == 6200
    auto_credits = [
        flow
        for flow in second_flows.json()
        if flow["schedule_id"] == schedule.json()["id"] and flow["automatically_posted"]
    ]
    assert len(auto_credits) == 1
    assert auto_credits[0]["status"] == "confirmed"
    assert auto_credits[0]["expected_date"] == today.isoformat()
    assert len(
        [
            flow
            for flow in first_flows.json()
            if flow["schedule_id"] == schedule.json()["id"] and flow["automatically_posted"]
        ]
    ) == 1


def test_scheduled_income_rejects_non_salary_kind_for_automatic_credit(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.post(
            "/api/cash-flow-schedules",
            json={
                "label": "Automatic rent",
                "kind": "bill",
                "amount": "100",
                "currency": "EUR",
                "recurrence": "monthly",
                "start_date": date.today().isoformat(),
                "account_id": str(uuid4()),
                "subaccount_id": str(uuid4()),
                "auto_post": True,
            },
        )

    assert response.status_code == 422


def test_vesting_grant_uses_quote_and_generated_cliff_schedule(monkeypatch, tmp_path) -> None:
    import app.services as services

    class FakeTwelveDataClient:
        def __init__(self, api_key: str, timeout_seconds: float = 10) -> None:
            assert api_key == "test-provider-key"

        async def quote(
            self, symbol: str, mic_code: str | None = None, exchange: str | None = None
        ) -> MarketQuote:
            assert symbol == "MSFT"
            return MarketQuote(
                symbol="MSFT",
                name="Microsoft Corporation",
                price=Decimal("400"),
                currency=Currency.USD,
                observed_at=datetime(2026, 10, 11, 12, tzinfo=UTC),
                is_market_open=True,
                mic_code="XNAS",
                exchange="NASDAQ",
            )

        async def exchange_rate(self, pair: str) -> ExchangeRateQuote:
            raise AssertionError(f"Unexpected FX lookup: {pair}")

    monkeypatch.setattr(
        services, "get_settings", lambda: Settings(twelve_data_api_key="test-provider-key")
    )
    monkeypatch.setattr(services, "TwelveDataClient", FakeTwelveDataClient)
    grant_date = add_months(date.today(), -12)
    with create_test_client(tmp_path) as client:
        profile = client.put(
            "/api/profile",
            json={
                "display_name": "Test user",
                "base_currency": "EUR",
                "usd_per_eur": "1.25",
            },
        )
        created = client.post(
            "/api/vesting-grants",
            json={
                "symbol": "MSFT",
                "mic_code": "XNAS",
                "exchange": "NASDAQ",
                "grant_type": "rsu",
                "grant_date": grant_date.isoformat(),
                "total_units": "120",
                "duration_months": 48,
                "cliff_months": 12,
                "interval_months": 3,
                "tax_rate_assumption": "0.3",
            },
        )
        dashboard = client.get("/api/dashboard")
        removed = client.delete(f"/api/vesting-grants/{created.json()['id']}")
        after_delete = client.get("/api/dashboard")

    assert profile.status_code == 200, profile.text
    assert created.status_code == 201, created.text
    assert dashboard.status_code == 200, dashboard.text
    grant = dashboard.json()["vesting"][0]
    assert grant["symbol"] == "MSFT"
    assert Decimal(grant["total_units"]) == 120
    assert Decimal(grant["vested_units"]) == 30
    assert Decimal(grant["vested_percent"]) == 25
    assert Decimal(grant["units"]) == 90
    assert Decimal(grant["price"]) == 400
    assert Decimal(grant["gross_value"]) == 28800
    assert Decimal(grant["estimated_net_value"]) == 20160
    assert Decimal(grant["short_term_sale_tax_rate"]) == Decimal("0.06")
    assert Decimal(grant["long_term_sale_tax_rate"]) == Decimal("0.03")
    assert grant["long_term_holding_period_days"] == 365
    assert Decimal(grant["estimated_short_term_sale_value"]) == 27072
    assert Decimal(grant["estimated_long_term_sale_value"]) == 27936
    assert Decimal(dashboard.json()["totals"]["unvested_equity_gross"]) == 28800
    assert Decimal(dashboard.json()["totals"]["net_worth"]) == 0
    assert len(grant["tranches"]) == 13
    assert grant["tranches"][0]["status"] == "vested"
    assert removed.status_code == 204
    assert after_delete.json()["vesting"] == []


def test_named_grant_accepts_custom_vesting_dates_and_sale_tax_rates(monkeypatch, tmp_path) -> None:
    import app.services as services

    class FakeTwelveDataClient:
        def __init__(self, api_key: str, timeout_seconds: float = 10) -> None:
            assert api_key == "test-provider-key"

        async def quote(
            self, symbol: str, mic_code: str | None = None, exchange: str | None = None
        ) -> MarketQuote:
            assert symbol == "MSFT"
            return MarketQuote(
                symbol="MSFT",
                name="Microsoft Corporation",
                price=Decimal("535"),
                currency=Currency.USD,
                observed_at=datetime(2026, 10, 11, 12, tzinfo=UTC),
                is_market_open=True,
                mic_code="XNAS",
                exchange="NASDAQ",
            )

    monkeypatch.setattr(
        services, "get_settings", lambda: Settings(twelve_data_api_key="test-provider-key")
    )
    monkeypatch.setattr(services, "TwelveDataClient", FakeTwelveDataClient)
    first_vest = add_months(date.today(), 2)
    second_vest = add_months(date.today(), 5)
    payload = {
        "symbol": "MSFT",
        "mic_code": "XNAS",
        "exchange": "NASDAQ",
        "grant_type": "rsu",
        "grant_label": "On-Hire",
        "grant_date": date.today().isoformat(),
        "total_units": "20",
        "tranches": [
            {"vest_date": first_vest.isoformat(), "units": "9"},
            {"vest_date": second_vest.isoformat(), "units": "11"},
        ],
        "tax_rate_assumption": "0.05",
        "short_term_sale_tax_rate": "0.06",
        "long_term_sale_tax_rate": "0.03",
        "long_term_holding_period_days": 365,
    }
    fy26_payload = {
        **payload,
        "grant_label": "FY26 Annual SA",
        "grant_date": "2026-09-01",
        "total_units": "1",
        "tranches": [
            {"vest_date": add_months(date.today(), 5).isoformat(), "units": "1"}
        ],
        "short_term_sale_tax_rate": "0.40",
    }
    with create_test_client(tmp_path) as client:
        profile = client.put(
            "/api/profile",
            json={"display_name": "Test user", "base_currency": "USD"},
        )
        invalid_total = client.post(
            "/api/vesting-grants",
            json={**payload, "total_units": "21"},
        )
        created = client.post("/api/vesting-grants", json=payload)
        fy26_created = client.post("/api/vesting-grants", json=fy26_payload)
        dashboard = client.get("/api/dashboard")

    assert profile.status_code == 200, profile.text
    assert invalid_total.status_code == 422
    assert created.status_code == 201, created.text
    assert fy26_created.status_code == 201, fy26_created.text
    grants = {grant["grant_label"]: grant for grant in dashboard.json()["vesting"]}
    grant = grants["On-Hire"]
    assert grant["grant_label"] == "On-Hire"
    assert Decimal(grant["total_units"]) == 20
    assert Decimal(grant["units"]) == 20
    assert Decimal(grant["gross_value"]) == 10700
    assert Decimal(grant["estimated_net_value"]) == 10165
    assert Decimal(grant["estimated_short_term_sale_value"]) == 10058
    assert Decimal(grant["estimated_long_term_sale_value"]) == 10379
    assert [tranche["vest_date"] for tranche in grant["tranches"]] == [
        first_vest.isoformat(),
        second_vest.isoformat(),
    ]
    fy26 = grants["FY26 Annual SA"]
    assert fy26["grant_date"] == "2026-09-01"
    assert Decimal(fy26["short_term_sale_tax_rate"]) == Decimal("0.40")
    assert Decimal(fy26["long_term_sale_tax_rate"]) == Decimal("0.03")
    assert Decimal(fy26["estimated_short_term_sale_value"]) == 321
    assert Decimal(fy26["estimated_long_term_sale_value"]) == Decimal("518.95")
    assert (
        Decimal(dashboard.json()["totals"]["unvested_equity_short_term_sale_estimate"])
        == 10379
    )
    assert (
        Decimal(dashboard.json()["totals"]["unvested_equity_long_term_sale_estimate"])
        == Decimal("10897.95")
    )


def test_fixed_deposit_is_account_funded_and_uses_capitalization_terms(tmp_path) -> None:
    start_date = date.today() - timedelta(days=365)
    with create_test_client(tmp_path) as client:
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "Deposit bank",
                "provider_code": "MANUAL",
                "account_type": "SAVINGS",
                "currency": "EUR",
                "opening_cash": "5000",
            },
        )
        wallet_id = account.json()["subaccounts"][0]["id"]
        created = client.post(
            "/api/deposits",
            json={
                "account_id": account.json()["id"],
                "subaccount_id": wallet_id,
                "name": "One-year capitalized deposit",
                "principal": "1000",
                "start_date": start_date.isoformat(),
                "period_months": 12,
                "annual_profit_rate": "0.05",
                "capitalization": True,
            },
        )
        simple_created = client.post(
            "/api/deposits",
            json={
                "account_id": account.json()["id"],
                "subaccount_id": wallet_id,
                "name": "Simple-interest deposit",
                "principal": "500",
                "start_date": start_date.isoformat(),
                "period_months": 12,
                "annual_profit_rate": "0.04",
                "capitalization": False,
            },
        )
        after_create = client.get("/api/dashboard").json()
        invalid_account = client.post(
            "/api/accounts",
            json={
                "display_name": "Broker",
                "provider_code": "MANUAL",
                "account_type": "BROKERAGE",
                "currency": "EUR",
                "opening_cash": "1000",
            },
        )
        rejected_deposit = client.post(
            "/api/deposits",
            json={
                "account_id": invalid_account.json()["id"],
                "subaccount_id": invalid_account.json()["subaccounts"][0]["id"],
                "name": "Invalid brokerage deposit",
                "principal": "100",
                "start_date": date.today().isoformat(),
                "period_months": 6,
                "annual_profit_rate": "0.04",
                "capitalization": False,
            },
        )
        deleted = client.delete(f"/api/deposits/{created.json()['id']}")
        deleted_simple = client.delete(f"/api/deposits/{simple_created.json()['id']}")
        after_delete = client.get("/api/dashboard").json()

    assert account.status_code == 201, account.text
    assert created.status_code == 201, created.text
    assert simple_created.status_code == 201, simple_created.text
    assert created.json()["maturity_date"] == add_months(start_date, 12).isoformat()
    assert created.json()["period_months"] == 12
    assert created.json()["capitalization"] is True
    bank_after_create = next(
        item for item in after_create["accounts"] if item["id"] == account.json()["id"]
    )
    assert Decimal(bank_after_create["subaccounts"][0]["cash_balance"]) == 3500
    deposits = {deposit["name"]: deposit for deposit in after_create["deposits"]}
    deposit = deposits["One-year capitalized deposit"]
    assert deposit["name"] == "One-year capitalized deposit"
    assert deposit["compounding"] == "monthly"
    assert deposit["period_months"] == 12
    assert Decimal(deposit["annual_rate"]) == Decimal("0.05")
    assert Decimal(deposit["current_value"]) > Decimal("1000")
    simple_deposit = deposits["Simple-interest deposit"]
    assert simple_deposit["compounding"] == "at_maturity"
    assert Decimal(simple_deposit["current_value"]) == Decimal("520.00")
    assert invalid_account.status_code == 201
    assert rejected_deposit.status_code == 422
    assert deleted.status_code == 204
    assert deleted_simple.status_code == 204
    assert after_delete["deposits"] == []
    bank_after_delete = next(
        item for item in after_delete["accounts"] if item["id"] == account.json()["id"]
    )
    assert Decimal(bank_after_delete["subaccounts"][0]["cash_balance"]) == 5000


def test_goal_links_account_selected_assets_and_visualization_only_budget(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        brokerage = client.post(
            "/api/accounts",
            json={
                "display_name": "Goal brokerage",
                "provider_code": "MANUAL",
                "account_type": "BROKERAGE",
                "currency": "EUR",
                "opening_cash": "0",
            },
        )
        bank = client.post(
            "/api/accounts",
            json={
                "display_name": "Goal savings bank",
                "provider_code": "MANUAL",
                "account_type": "BANK",
                "currency": "EUR",
                "opening_cash": "2000",
            },
        )
        created_deposit = client.post(
            "/api/deposits",
            json={
                "account_id": bank.json()["id"],
                "subaccount_id": bank.json()["subaccounts"][0]["id"],
                "name": "Goal deposit",
                "principal": "1000",
                "start_date": date.today().isoformat(),
                "period_months": 12,
                "annual_profit_rate": "0.04",
                "capitalization": False,
            },
        )
        user_id = UUID(client.get("/api/auth/me").json()["id"])
        with client.app.state.session_factory() as session:
            instrument = Instrument(
                symbol="GOALTEST",
                name="Goal Test Corp",
                asset_class=AssetClass.EQUITIES,
                currency=Currency.EUR,
                mic="XNAS",
                exchange="NASDAQ",
                instrument_type="STOCK",
                is_demo=False,
            )
            session.add(instrument)
            session.flush()
            holding = Holding(
                user_id=user_id,
                account_id=UUID(brokerage.json()["id"]),
                funding_subaccount_id=None,
                instrument_id=instrument.id,
                quantity=Decimal("2"),
                average_cost=Decimal("40"),
                purchase_date=date(2025, 1, 1),
                funding_cost=Decimal("0"),
            )
            session.add(holding)
            session.flush()
            session.add(
                MarketPriceCache(
                    instrument_id=instrument.id,
                    price=Decimal("100"),
                    currency=Currency.EUR,
                    source="TEST",
                    feed_type="QUOTE",
                    observed_at=datetime.now(UTC),
                )
            )
            session.commit()
            holding_id = str(holding.id)

        payload = {
            "name": "Home fund",
            "goal_type": "purchase",
            "target_amount": "5000",
            "current_amount": "0",
            "target_currency": "EUR",
            "priority": 1,
            "risk_level": "moderate",
            "monthly_contribution": "0",
            "visualization_budget_amount": "500",
            "visualization_budget_period": "yearly",
            "flexibility": "flexible",
            "linked_account_ids": [brokerage.json()["id"], bank.json()["id"]],
            "holding_ids": [holding_id],
            "fixed_deposit_ids": [created_deposit.json()["id"]],
        }
        created_goal = client.post("/api/goals", json=payload)
        dashboard = client.get("/api/dashboard").json()
        duplicate_assignment = client.post(
            "/api/goals",
            json={
                **payload,
                "name": "Second goal",
                "linked_account_ids": [brokerage.json()["id"]],
                "fixed_deposit_ids": [],
            },
        )
        duplicate_deposit_assignment = client.post(
            "/api/goals",
            json={
                **payload,
                "name": "Second deposit goal",
                "linked_account_ids": [bank.json()["id"]],
                "holding_ids": [],
            },
        )
        invalid_account_link = client.post(
            "/api/goals",
            json={
                **payload,
                "name": "Unlinked source",
                "linked_account_ids": [],
                "holding_ids": [holding_id],
                "fixed_deposit_ids": [],
            },
        )
        updated_goal = client.put(
            f"/api/goals/{created_goal.json()['id']}",
            json={
                **payload,
                "visualization_budget_amount": "700",
                "visualization_budget_period": "yearly",
                "linked_account_ids": [brokerage.json()["id"]],
                "holding_ids": [],
                "fixed_deposit_ids": [],
            },
        )
        dashboard_after_update = client.get("/api/dashboard").json()

    assert created_deposit.status_code == 201, created_deposit.text
    assert created_goal.status_code == 201, created_goal.text
    assert created_goal.json()["linked_account_ids"] == sorted(
        [brokerage.json()["id"], bank.json()["id"]]
    ) or set(created_goal.json()["linked_account_ids"]) == {
        brokerage.json()["id"],
        bank.json()["id"],
    }
    assert created_goal.json()["holding_ids"] == [holding_id]
    assert created_goal.json()["fixed_deposit_ids"] == [created_deposit.json()["id"]]
    assert Decimal(created_goal.json()["visualization_budget_amount"]) == 500
    assert created_goal.json()["visualization_budget_period"] == "yearly"
    assert Decimal(created_goal.json()["monthly_contribution"]) == 0
    goal = dashboard["goals"][0]
    assert Decimal(goal["linked_asset_value"]) > Decimal("1196")
    assert Decimal(goal["current_amount"]) == Decimal(goal["linked_asset_value"])
    assert Decimal(goal["visualization_budget_amount"]) == 500
    assert goal["visualization_budget_period"] == "yearly"
    assert dashboard["holdings"][0]["assigned_goal_id"] == created_goal.json()["id"]
    assert dashboard["deposits"][0]["assigned_goal_id"] == created_goal.json()["id"]
    assert duplicate_assignment.status_code == 409
    assert duplicate_deposit_assignment.status_code == 409
    assert invalid_account_link.status_code == 422
    assert updated_goal.status_code == 200, updated_goal.text
    assert Decimal(updated_goal.json()["visualization_budget_amount"]) == 700
    assert updated_goal.json()["holding_ids"] == []
    assert updated_goal.json()["fixed_deposit_ids"] == []
    assert Decimal(dashboard_after_update["goals"][0]["linked_asset_value"]) == 0
    assert dashboard_after_update["holdings"][0]["assigned_goal_id"] is None
    assert dashboard_after_update["deposits"][0]["assigned_goal_id"] is None
