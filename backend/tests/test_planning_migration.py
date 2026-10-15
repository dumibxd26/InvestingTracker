import importlib.util
import json
from datetime import date
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.database import make_engine
from app.planning import FinancialPlanPayload


def test_timeline_migration_preserves_legacy_savings_and_retires_priority(tmp_path) -> None:
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20261015_21_financial_timeline.py"
    spec = importlib.util.spec_from_file_location("timeline_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = make_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id CHAR(32) PRIMARY KEY, base_currency TEXT)"))
        connection.execute(
            text(
                "CREATE TABLE financial_goals "
                "(id CHAR(32) PRIMARY KEY, priority INTEGER NOT NULL, monthly_contribution NUMERIC)"
            )
        )
        connection.execute(text("CREATE TABLE allocation_policies (funding_rule TEXT)"))
        connection.execute(text("CREATE TABLE recommendations (funding_rule TEXT)"))
        user_id = uuid4().hex
        connection.execute(
            text("INSERT INTO users (id, base_currency) VALUES (:id, 'EUR')"), {"id": user_id}
        )
        connection.execute(
            text("INSERT INTO financial_goals VALUES (:id, 2, 600)"), {"id": uuid4().hex}
        )
        connection.execute(text("INSERT INTO allocation_policies VALUES ('priority_first')"))
        connection.execute(text("INSERT INTO recommendations VALUES ('priority_first')"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("financial_goals")}
        assert "priority" not in columns
        assert {"target_money_basis", "annual_inflation_rate", "contribution_rules"} <= columns
        goal = connection.execute(
            text(
                "SELECT monthly_contribution, target_money_basis, contribution_rules "
                "FROM financial_goals"
            )
        ).one()
        assert goal.monthly_contribution == 600
        assert goal.target_money_basis == "real"
        assert goal.contribution_rules is None
        for table in ("allocation_policies", "recommendations"):
            assert (
                connection.execute(text(f"SELECT funding_rule FROM {table}")).scalar_one()
                == "proportional"
            )
        saved = connection.execute(
            text("SELECT configuration FROM financial_plans WHERE user_id = :id"), {"id": user_id}
        ).scalar_one()
        plan = FinancialPlanPayload.model_validate(json.loads(saved))
        assert plan.anchor_date == date.today()
        assert plan.income_sources == []
        with Operations.context(context):
            migration.downgrade()
        restored = connection.execute(
            text("SELECT priority, monthly_contribution FROM financial_goals")
        ).one()
        assert restored.priority == 3
        assert restored.monthly_contribution == 600
    engine.dispose()
