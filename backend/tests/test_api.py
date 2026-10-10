from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.cash_flow_logic import add_months
from app.config import Settings
from app.database import Base, make_engine
from app.main import create_app
from app.market_data import ExchangeRateQuote, MarketQuote, MarketSymbol
from app.models import (
    AssetClass,
    CashFlow,
    CompoundingFrequency,
    Currency,
    FixedDeposit,
    Holding,
    Instrument,
    MarketFXRate,
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
        second_dashboard = client.get("/api/dashboard").json()

        client.headers.update({"Authorization": f"Bearer {first.json()['access_token']}"})
        first_accounts = client.get("/api/accounts").json()

    assert Decimal(first_balance) == Decimal("425.50")
    assert second_dashboard["profile"]["username"] == second_username
    assert second_dashboard["accounts"] == []
    assert Decimal(second_dashboard["totals"]["available_cash"]) == 0
    assert second_dashboard["goals"] == []
    assert foreign_account_delete.status_code == 404
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
        account = client.post(
            "/api/accounts",
            json={
                "display_name": "USD brokerage",
                "provider_code": "MANUAL",
                "account_type": "BROKERAGE",
                "currency": "EUR",
                "opening_cash": "0",
            },
        )
        added = client.post(
            "/api/holdings",
            json={
                "account_id": account.json()["id"],
                "symbol": "MSFT",
                "mic_code": "XNAS",
                "exchange": "NASDAQ",
                "instrument_type": "STOCK",
                "quantity": "2",
                "average_cost": "300",
            },
        )
        dashboard = client.get("/api/dashboard")
        holding_id = dashboard.json()["holdings"][0]["id"]
        update = client.put(
            f"/api/holdings/{holding_id}",
            json={"quantity": "3", "average_cost": "350"},
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
    assert account.status_code == 201, account.text
    assert added.status_code == 201, added.text
    assert Decimal(dashboard.json()["holdings"][0]["market_value"]) == Decimal("640.00")
    assert dashboard.json()["holdings"][0]["quote_source"] == "TWELVE_DATA"
    assert update.status_code == 204, update.text
    assert Decimal(updated_dashboard.json()["holdings"][0]["quantity"]) == Decimal("3")
    assert Decimal(updated_dashboard.json()["holdings"][0]["average_cost"]) == Decimal("350")
    assert Decimal(updated_dashboard.json()["holdings"][0]["market_value"]) == Decimal("960.00")
    assert other_user_update.status_code == 404
    assert other_user_delete.status_code == 404
    assert missing_holding_delete.status_code == 404
    assert delete.status_code == 204, delete.text
    assert deleted_dashboard.json()["holdings"] == []


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
