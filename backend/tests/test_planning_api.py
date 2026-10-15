from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from test_api import create_test_client

from app.cash_flow_logic import add_months

D = Decimal


def goal_payload(**changes) -> dict:
    return {
        "name": "Retirement",
        "goal_type": "wealth",
        "target_amount": "100000",
        "target_date": add_months(date.today(), 24).isoformat(),
        "target_currency": "EUR",
        "risk_level": "moderate",
        "flexibility": "flexible",
        **changes,
    }


def source_payload(**changes) -> dict:
    return {
        "id": "salary",
        "name": "Net salary",
        "kind": "salary",
        "amount": "4000",
        "currency": "EUR",
        "recurrence": "monthly",
        "start_date": date.today().isoformat(),
        "annual_growth_rate": "0",
        "money_basis": "real",
        **changes,
    }


def rule_payload(**changes) -> dict:
    return {
        "calculation": "fixed",
        "value": "500",
        "start_date": date.today().isoformat(),
        "money_basis": "nominal",
        "recurrence": "monthly",
        **changes,
    }


def save_plan(client, **changes) -> dict:
    plan = client.get("/api/financial-plan").json()
    response = client.put("/api/financial-plan", json={**plan, **changes})
    assert response.status_code == 200, response.text
    return response.json()


def test_financial_plan_roundtrip_is_persistent_and_never_credits_cash(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        before = client.get("/api/dashboard").json()["totals"]["available_cash"]
        plan = save_plan(
            client,
            annual_inflation_rate="0.04",
            income_sources=[source_payload()],
            monthly_expenses="2000",
            expenses_currency="EUR",
        )
        assert client.get("/api/financial-plan").json() == plan
        assert client.get("/api/cash-flow-schedules").json() == []
        assert client.get("/api/dashboard").json()["totals"]["available_cash"] == before
        changed_anchor = {**plan, "anchor_date": (date.today() - timedelta(days=1)).isoformat()}
        assert client.put("/api/financial-plan", json=changed_anchor).status_code == 422


def test_goal_rules_mix_salary_bonus_and_fixed_savings_without_priority(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        bonus_date = add_months(date.today(), 3)
        save_plan(
            client,
            income_sources=[
                source_payload(),
                source_payload(
                    id="bonus",
                    name="Annual bonus",
                    kind="bonus",
                    amount="10000",
                    start_date=bonus_date.isoformat(),
                    recurrence="annual",
                    money_basis="nominal",
                ),
            ],
        )
        response = client.post(
            "/api/goals",
            json=goal_payload(
                contribution_rules=[
                    rule_payload(source_id="salary", calculation="percentage", value="0.15"),
                    rule_payload(source_id="bonus", calculation="percentage", value="0.5"),
                    rule_payload(value="200"),
                ]
            ),
        )
        assert response.status_code == 201, response.text
        goal = response.json()
        assert "priority" not in goal
        assert len(goal["contribution_rules"]) == 3
        points = client.get(f"/api/goals/{goal['id']}/contributions?months=12").json()
        assert D(points["months"][0]["nominal_contribution"]) == D("800")
        assert D(points["months"][2]["nominal_contribution"]) == D("5800")
        assert all(
            D(point["nominal_contribution"]) == D("800")
            for index, point in enumerate(points["months"])
            if index != 2
        )
        dashboard_goal = client.get("/api/dashboard").json()["goals"][0]
        assert "priority" not in dashboard_goal
        assert D(dashboard_goal["monthly_contribution"]) == D("800")
        insights = client.get(f"/api/goals/{goal['id']}/insights")
        assert insights.status_code == 200, insights.text
        assert insights.json()["available"] is True
        assert insights.json()["goal"]["monthly_contributions"][:12] == [
            float(point["nominal_contribution"]) for point in points["months"]
        ]
        assert "before inflation" in " ".join(insights.json()["assumptions"])


def test_salary_percentages_cannot_overallocate_source_across_goals(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        plan = save_plan(client, income_sources=[source_payload()])
        first = client.post(
            "/api/goals",
            json=goal_payload(
                contribution_rules=[
                    rule_payload(source_id="salary", calculation="percentage", value="0.6")
                ]
            ),
        )
        assert first.status_code == 201, first.text
        second = client.post(
            "/api/goals",
            json=goal_payload(
                name="House",
                contribution_rules=[
                    rule_payload(source_id="salary", calculation="percentage", value="0.5")
                ],
            ),
        )
        assert second.status_code == 422
        assert "100%" in second.json()["detail"]
        removal = client.put("/api/financial-plan", json={**plan, "income_sources": []})
        assert removal.status_code == 422
        assert "missing" in removal.json()["detail"]
        assert len(client.get("/api/goals").json()) == 1


def test_salary_category_follows_future_jobs_and_checks_specific_source_shares(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        plan = save_plan(client, annual_inflation_rate="0", income_sources=[source_payload()])
        created = client.post(
            "/api/goals",
            json=goal_payload(
                contribution_rules=[
                    rule_payload(source_kind="salary", calculation="percentage", value="0.15")
                ]
            ),
        )
        assert created.status_code == 201, created.text
        goal_id = created.json()["id"]
        boundary = add_months(date.today(), 6)
        plan["income_sources"][0]["end_date"] = (boundary - timedelta(days=1)).isoformat()
        plan["income_sources"].append(
            source_payload(
                id="new_job", name="New job salary", amount="5000", start_date=boundary.isoformat()
            )
        )
        updated = client.put("/api/financial-plan", json=plan)
        assert updated.status_code == 200, updated.text
        schedule = client.get(f"/api/goals/{goal_id}/contributions?months=12").json()
        assert D(schedule["months"][0]["nominal_contribution"]) == D("600")
        assert D(schedule["months"][5]["nominal_contribution"]) == D("750")
        assert D(schedule["months"][-1]["nominal_contribution"]) == D("750")
        excess = client.post(
            "/api/goals",
            json=goal_payload(
                name="House",
                contribution_rules=[
                    rule_payload(source_id="new_job", calculation="percentage", value="0.9")
                ],
            ),
        )
        assert excess.status_code == 422
        assert "100%" in excess.json()["detail"]


def test_nonoverlapping_percentage_periods_are_allowed(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        save_plan(client, income_sources=[source_payload()])
        boundary = add_months(date.today(), 12)
        first = client.post(
            "/api/goals",
            json=goal_payload(
                contribution_rules=[
                    rule_payload(
                        source_id="salary",
                        calculation="percentage",
                        value="0.8",
                        end_date=(boundary - timedelta(days=1)).isoformat(),
                    )
                ]
            ),
        )
        assert first.status_code == 201, first.text
        second = client.post(
            "/api/goals",
            json=goal_payload(
                name="House",
                contribution_rules=[
                    rule_payload(
                        source_id="salary",
                        calculation="percentage",
                        value="0.8",
                        start_date=boundary.isoformat(),
                    )
                ],
            ),
        )
        assert second.status_code == 201, second.text


def test_overcommitted_plan_warns_instead_of_deprioritizing_goals(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        save_plan(client, income_sources=[source_payload(amount="1000")], monthly_expenses="500")
        ids = []
        for name in ("House", "Retirement"):
            created = client.post(
                "/api/goals",
                json=goal_payload(name=name, contribution_rules=[rule_payload(value="400")]),
            )
            assert created.status_code == 201, created.text
            ids.append(created.json()["id"])
        for goal_id in ids:
            schedule = client.get(f"/api/goals/{goal_id}/contributions?months=1").json()
            assert D(schedule["months"][0]["nominal_contribution"]) == D("400")
            assert any("exceed" in warning for warning in schedule["warnings"])
            assert any("additional funding" in warning for warning in schedule["warnings"])


def test_nominal_and_real_target_modes_use_configured_inflation(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        save_plan(client, annual_inflation_rate="0.1")
        created = client.post("/api/goals", json=goal_payload(target_money_basis="nominal"))
        assert created.status_code == 201, created.text
        goal_id = created.json()["id"]
        nominal = client.get(f"/api/goals/{goal_id}/insights")
        assert nominal.status_code == 200, nominal.text
        assert nominal.json()["simulation"]["nominal_target_at_maturity"] == 100000
        updated = client.put(
            f"/api/goals/{goal_id}",
            json=goal_payload(target_money_basis="real", annual_inflation_rate="0.05"),
        )
        assert updated.status_code == 200, updated.text
        real = client.get(f"/api/goals/{goal_id}/insights").json()
        assert 110000 < real["simulation"]["nominal_target_at_maturity"] < 111000


def test_old_client_update_preserves_new_rules_and_nominal_target(tmp_path) -> None:
    with create_test_client(tmp_path) as client:
        created = client.post(
            "/api/goals",
            json=goal_payload(
                target_money_basis="nominal",
                annual_inflation_rate="0.04",
                contribution_rules=[rule_payload()],
            ),
        )
        assert created.status_code == 201, created.text
        goal_id = created.json()["id"]
        updated = client.put(f"/api/goals/{goal_id}", json=goal_payload(name="Renamed"))
        assert updated.status_code == 200, updated.text
        saved = updated.json()
        assert saved["target_money_basis"] == "nominal"
        assert D(saved["annual_inflation_rate"]) == D("0.04")
        assert len(saved["contribution_rules"]) == 1
        assert client.get(f"/api/goals/{goal_id}/contributions?months=0").status_code == 422
        assert client.get(f"/api/goals/{goal_id}/contributions?months=1201").status_code == 422


def test_priority_funding_is_rejected_and_scheduled_proportional_routing_conserves_cash(
    tmp_path,
) -> None:
    with create_test_client(tmp_path) as client:
        for name, value in (("House", "300"), ("Retirement", "700")):
            created = client.post(
                "/api/goals",
                json=goal_payload(name=name, contribution_rules=[rule_payload(value=value)]),
            )
            assert created.status_code == 201, created.text
        policy = {
            "funding_rule": "priority_first",
            "emergency_reserve": "0",
            "target_weights": {"equities": "0.7", "fixed_income": "0.2", "satellite": "0.1"},
        }
        assert client.put("/api/policy", json=policy).status_code == 422
        assert (
            client.put("/api/policy", json={**policy, "funding_rule": "proportional"}).status_code
            == 200
        )
        preview = client.post(
            "/api/recommendations/preview",
            json={
                "amount": "1000",
                "currency": "EUR",
            },
        )
        assert preview.status_code == 200, preview.text
        amounts = {row["goal_name"]: D(row["amount"]) for row in preview.json()["goal_allocations"]}
        assert amounts == {"House": D("300"), "Retirement": D("700")}


def test_financial_plan_endpoints_require_authentication_and_tenant_ownership(tmp_path) -> None:
    with create_test_client(tmp_path, authenticated=False) as client:
        assert client.get("/api/financial-plan").status_code == 401
        assert (
            client.put(
                "/api/financial-plan",
                json={
                    "anchor_date": date.today().isoformat(),
                },
            ).status_code
            == 401
        )
        assert client.get(f"/api/goals/{uuid4()}/contributions").status_code == 401
    with create_test_client(tmp_path) as client:
        save_plan(client, income_sources=[source_payload()])
        created = client.post("/api/goals", json=goal_payload())
        assert created.status_code == 201, created.text
        other = client.post(
            "/api/auth/register",
            json={
                "username": f"other_{uuid4().hex[:12]}",
                "password": "independent-test-passphrase",
                "base_currency": "EUR",
            },
        )
        assert other.status_code == 201, other.text
        client.headers["Authorization"] = f"Bearer {other.json()['access_token']}"
        assert client.get("/api/financial-plan").json()["income_sources"] == []
        assert client.get(f"/api/goals/{created.json()['id']}/contributions").status_code == 404
