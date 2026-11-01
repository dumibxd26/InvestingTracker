from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.calculations import fixed_deposit_value, round_allocations
from app.cash_flow_logic import add_months
from app.models import CompoundingFrequency, Currency, RateBasis

ZERO = Decimal("0")
ONE = Decimal("1")
METHOD = "monthly-total-return-replay-v1"


class RetirementInvestment(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    kind: Literal["holding", "deposit", "stock", "etf", "bond", "future_deposit", "cash"]
    asset_id: UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    history_id: UUID | None = None
    contribution_percentage: Decimal = Field(default=ZERO, ge=0, le=100)
    lower_return: Decimal = Field(gt=-1, le=1)
    upper_return: Decimal = Field(gt=-1, le=1)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=1)
    deposit_term_months: int = Field(default=12, ge=1, le=1200)

    @model_validator(mode="after")
    def validate_investment(self) -> RetirementInvestment:
        if self.lower_return > self.upper_return:
            raise ValueError("Lower annual return must not exceed upper annual return")
        tracked = self.kind in {"holding", "deposit"}
        if tracked != (self.asset_id is not None):
            raise ValueError("Only tracked holdings/deposits require an asset ID")
        if self.kind == "deposit" and self.contribution_percentage:
            raise ValueError(
                "An existing term deposit cannot receive top-ups; add a future deposit destination"
            )
        return self


class RetirementSettings(BaseModel):
    target_date: date
    currency: Currency
    contribution_amount: Decimal = Field(default=ZERO, ge=0, le=100000000)
    contribution_frequency: Literal["monthly", "yearly"] = "monthly"
    annual_inflation_rate: Decimal = Field(gt=-1, le=1)
    include_taxes: bool = True
    investments: list[RetirementInvestment] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_settings(self) -> RetirementSettings:
        if any(item.key == "manual-goal-cash" or item.kind == "cash" for item in self.investments):
            raise ValueError(
                "Manual goal savings are loaded from the goal, not investment settings"
            )
        if self.include_taxes and any(
            item.kind not in {"holding", "deposit"} and item.tax_rate is None
            for item in self.investments
        ):
            raise ValueError("Enter an explicit estimated tax rate for every future investment")
        if len({item.key for item in self.investments}) != len(self.investments):
            raise ValueError("Investment keys must be unique")
        references = [
            (item.kind, item.asset_id) for item in self.investments if item.asset_id is not None
        ]
        if len(set(references)) != len(references):
            raise ValueError("A tracked asset can only appear once")
        if (
            self.contribution_amount
            and sum((item.contribution_percentage for item in self.investments), ZERO) != 100
        ):
            raise ValueError("Future contribution percentages must total exactly 100%")
        return self


class HistoryImport(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    currency: Currency
    source: str = Field(min_length=3, max_length=500)
    license: str = Field(min_length=3, max_length=200)
    personal_storage_permitted: Literal[True]
    total_return_confirmed: Literal[True]
    csv: str = Field(min_length=10, max_length=1000000)


def parse_history(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if reader.fieldnames != ["date", "total_return_index"]:
        raise ValueError("CSV needs exactly: date,total_return_index")
    observations: list[dict[str, str]] = []
    previous: date | None = None
    for row in reader:
        if len(observations) >= 2401:
            raise ValueError("History is limited to 2,401 monthly observations (200 years)")
        if set(row) != {"date", "total_return_index"}:
            raise ValueError("Each CSV row must contain exactly two columns")
        try:
            at = date.fromisoformat(row["date"])
            index = Decimal(row["total_return_index"])
        except (ValueError, TypeError, ArithmeticError) as error:
            raise ValueError("Each row needs an ISO month-end date and positive index") from error
        if (
            not index.is_finite()
            or index <= 0
            or index > Decimal("1e20")
            or at > date.today()
            or at != add_months(at.replace(day=1), 1) - timedelta(days=1)
        ):
            raise ValueError("Indices must be finite and positive at completed month-end dates")
        if previous is not None:
            next_month = add_months(previous.replace(day=1), 1)
            if (at.year, at.month) != (next_month.year, next_month.month):
                raise ValueError("History must be ascending, unique, and have no missing months")
        observations.append({"date": at.isoformat(), "index": str(index)})
        previous = at
    if len(observations) < 2:
        raise ValueError("Import at least two month-end observations")
    return observations


@dataclass(frozen=True)
class DepositContract:
    principal: Decimal
    annual_rate: Decimal
    start: date
    maturity: date
    compounding: CompoundingFrequency
    rate_basis: RateBasis


@dataclass(frozen=True)
class RetirementAsset:
    investment: RetirementInvestment
    current: Decimal
    basis: Decimal
    tax_rate: Decimal
    history: list[dict[str, str]] | None = None
    contract: DepositContract | None = None
    warnings: tuple[str, ...] = ()


def monthly_timeline(start: date, end: date) -> list[date]:
    points = [start]
    count = 1
    while add_months(start, count) < end:
        points.append(add_months(start, count))
        count += 1
    points.append(end)
    return points


def growth(rate: Decimal, years: Decimal) -> Decimal:
    return ((ONE + rate).ln() * years).exp()


def historical_suggestion(
    history: list[dict[str, str]],
    months: int,
    final_fraction: Decimal = ONE,
    elapsed_years: Decimal | None = None,
) -> dict:
    if len(history) <= months:
        return {"available": False, "reason": f"Need at least {months + 1} monthly observations"}
    years = elapsed_years or (Decimal(months - 1) + final_fraction) / 12
    rates = []
    for i in range(len(history) - months):
        first = Decimal(history[i]["index"])
        prior = Decimal(history[i + months - 1]["index"])
        last = Decimal(history[i + months]["index"])
        factor = prior / first * (last / prior) ** final_fraction
        rates.append(float(factor ** (ONE / years) - ONE))
    return {
        "available": True,
        "lower_return": min(rates),
        "upper_return": max(rates),
        "median_return": median(rates),
        "windows": len(rates),
        "sample_start": history[0]["date"],
        "sample_end": history[-1]["date"],
        "matching_months": months,
        "matching_elapsed_years": str(years),
        "method": METHOD,
    }


def project_retirement(
    settings: RetirementSettings, assets: list[RetirementAsset], today: date
) -> dict:
    if not today < settings.target_date <= add_months(today, 1200):
        raise ValueError("Choose a future horizon of at most 100 years")
    points = monthly_timeline(today, settings.target_date)
    months = len(points) - 1
    # A partial last month uses a fraction of the last observed monthly return.
    fractions = [
        Decimal((points[i] - points[i - 1]).days)
        / Decimal((add_months(today, i) - add_months(today, i - 1)).days)
        for i in range(1, len(points))
    ]
    allocation = round_allocations(
        {
            asset.investment.key: settings.contribution_amount
            * asset.investment.contribution_percentage
            / 100
            for asset in assets
        }
    )
    payment_step = 1 if settings.contribution_frequency == "monthly" else 12
    payments = [
        settings.contribution_amount
        if i % payment_step == 0 and points[i] == add_months(today, i)
        else ZERO
        for i in range(len(points))
    ]
    payments[0] = ZERO
    suggestions = {}
    for asset in assets:
        if asset.history:
            suggestions[asset.investment.key] = historical_suggestion(
                asset.history,
                months,
                fractions[-1],
                Decimal((settings.target_date - today).days) / Decimal("365.25"),
            )
        else:
            suggestions[asset.investment.key] = {
                "available": False,
                "reason": "Import and select licensed monthly total-return history"
                if not asset.contract
                else "Contractual deposit rate, not a historical return series",
            }
    warnings = [
        "Historical extremes are observations, not bounds on future results.",
        "Historical series must include reinvested dividends/coupons and historical FX "
        "in the projection currency. No implicit benchmark substitutions are made.",
        "Historical boundary lines are envelopes; different points may come "
        "from different windows.",
        "Tax views estimate horizon gain/interest tax using today's rates. "
        "Separate annual dividend withholding and future tax-law changes are not modeled.",
        "User return assumptions are effective nominal total returns; fees should be included "
        "in the entered rates. Future FX is held at today's rates for manual scenarios.",
        "Monthly history is replayed at plan anniversaries; a partial final month is "
        "geometrically interpolated, not an observed daily outcome.",
    ]
    warnings.extend(note for asset in assets for note in asset.warnings)
    history_maps = {
        asset.investment.key: {
            row["date"][:7]: Decimal(row["index"]) for row in asset.history or []
        }
        for asset in assets
    }

    def path(case: str, start_month: str | None = None) -> list[Decimal]:
        totals = [ZERO for _ in points]
        for asset in assets:
            item = asset.investment
            balance, basis = asset.current, asset.basis
            lots: list[tuple[int, date, Decimal]] = []
            index_by_date = history_maps[item.key]
            historical_start = date.fromisoformat(start_month + "-01") if start_month else None
            for i, at in enumerate(points):
                if asset.contract:
                    contract = asset.contract
                    gross = fixed_deposit_value(
                        contract.principal,
                        contract.annual_rate,
                        contract.start,
                        max(contract.start, min(at, contract.maturity)),
                        contract.compounding,
                        contract.rate_basis,
                    )
                elif item.kind == "cash":
                    gross = balance
                elif item.kind == "future_deposit":
                    gross = ZERO
                    for bought_i, bought, principal in lots:
                        if historical_start is not None and asset.history:
                            end_i = min(i, bought_i + item.deposit_term_months)
                            first_month = add_months(historical_start, bought_i).strftime("%Y-%m")
                            last_month = add_months(historical_start, end_i).strftime("%Y-%m")
                            factor = index_by_date[last_month] / index_by_date[first_month]
                            if end_i == i and i and fractions[i - 1] < 1:
                                prior_month = add_months(historical_start, i - 1).strftime("%Y-%m")
                                factor = (
                                    index_by_date[prior_month]
                                    / index_by_date[first_month]
                                    * (index_by_date[last_month] / index_by_date[prior_month])
                                    ** fractions[i - 1]
                                )
                        else:
                            rate = item.lower_return if case == "lower" else item.upper_return
                            factor = growth(
                                rate,
                                Decimal(
                                    (
                                        min(at, add_months(bought, item.deposit_term_months))
                                        - bought
                                    ).days
                                )
                                / Decimal("365.25"),
                            )
                        gross += principal * factor
                else:
                    if i:
                        if historical_start is not None and asset.history:
                            prior = add_months(historical_start, i - 1).strftime("%Y-%m")
                            current = add_months(historical_start, i).strftime("%Y-%m")
                            factor = (index_by_date[current] / index_by_date[prior]) ** fractions[
                                i - 1
                            ]
                        else:
                            rate = item.lower_return if case == "lower" else item.upper_return
                            factor = growth(
                                rate, Decimal((at - points[i - 1]).days) / Decimal("365.25")
                            )
                        balance *= factor
                    gross = balance
                if i and payments[i]:
                    contribution = allocation[item.key]
                    basis += contribution
                    if item.kind == "future_deposit":
                        lots.append((i, at, contribution))
                    balance += contribution
                    gross += contribution
                tax = max(ZERO, gross - basis) * asset.tax_rate if settings.include_taxes else ZERO
                totals[i] += gross - tax
        return totals

    evaluation_cost = months * sum(
        months if asset.investment.kind == "future_deposit" else 1 for asset in assets
    )
    if evaluation_cost > 2000000:
        raise ValueError("Scenario exceeds 2,000,000 asset-month evaluations; simplify the plan")
    manual_lower, manual_upper = path("lower"), path("upper")
    required = [asset for asset in assets if not asset.contract and asset.investment.kind != "cash"]
    historical_available = bool(required) and all(asset.history for asset in required)
    candidates: set[str] = set()
    if historical_available:
        for n, asset in enumerate(required):
            assert asset.history is not None
            eligible = {row["date"][:7] for row in asset.history[:-months]}
            candidates = eligible if n == 0 else candidates & eligible
    if len(candidates) * evaluation_cost > 2000000:
        raise ValueError(
            "Historical replay exceeds 2,000,000 asset-month evaluations; "
            "reduce the number of selected investments or the imported sample"
        )
    historical_paths = [
        (candidate, path("historical", candidate)) for candidate in sorted(candidates)
    ]
    if not historical_paths:
        warnings.append(
            "Historical comparison unavailable: all non-contract investments need synchronized "
            "history covering the full horizon. Today's deposit rate is not historical evidence."
        )
    historical_lower = (
        [min(values[i] for _, values in historical_paths) for i in range(len(points))]
        if historical_paths
        else None
    )
    historical_upper = (
        [max(values[i] for _, values in historical_paths) for i in range(len(points))]
        if historical_paths
        else None
    )

    def line(values: list[Decimal] | None) -> list[dict] | None:
        if values is None:
            return None
        return [
            {
                "date": at.isoformat(),
                "nominal_value": str(value),
                "real_value": str(
                    value
                    / growth(
                        settings.annual_inflation_rate,
                        Decimal((at - today).days) / Decimal("365.25"),
                    )
                ),
            }
            for at, value in zip(points, values, strict=True)
        ]

    endpoints = sorted(historical_paths, key=lambda row: row[1][-1])
    split_rates = []
    weighted = [asset for asset in assets if asset.investment.contribution_percentage > 0]
    if (
        candidates
        and sum((asset.investment.contribution_percentage for asset in weighted), ZERO) == 100
    ):
        for candidate in sorted(candidates):
            start_date = date.fromisoformat(candidate + "-01")
            split_factor = ZERO
            for asset in weighted:
                mapping = history_maps[asset.investment.key]
                final_month = (
                    min(months, asset.investment.deposit_term_months)
                    if asset.investment.kind == "future_deposit"
                    else months
                )
                first = mapping[candidate]
                prior = mapping[add_months(start_date, final_month - 1).strftime("%Y-%m")]
                last = mapping[add_months(start_date, final_month).strftime("%Y-%m")]
                fraction = fractions[-1] if final_month == months else ONE
                factor = prior / first * (last / prior) ** fraction
                split_factor += asset.investment.contribution_percentage / 100 * factor
            years = Decimal((settings.target_date - today).days) / Decimal("365.25")
            split_rates.append(float(split_factor ** (ONE / years) - ONE))
    return {
        "settings": settings.model_dump(mode="json"),
        "method": METHOD,
        "current_value": str(sum((asset.current for asset in assets), ZERO)),
        "contributions_paid": str(sum(payments, ZERO)),
        "lines": {
            "historical_lower": line(historical_lower),
            "historical_upper": line(historical_upper),
            "user_lower": line(manual_lower),
            "user_upper": line(manual_upper),
        },
        "historical_windows": len(historical_paths),
        "historical_min_start": endpoints[0][0] if endpoints else None,
        "historical_max_start": endpoints[-1][0] if endpoints else None,
        "suggestions": suggestions,
        "split_suggestion": {
            "available": bool(split_rates),
            "lower_return": min(split_rates) if split_rates else None,
            "upper_return": max(split_rates) if split_rates else None,
            "median_return": median(split_rates) if split_rates else None,
            "method": "Historical annualized return of a reference lump sum held using "
            "your future contribution percentages, without rebalancing, before tax. "
            "This reference is not the contribution-aware chart or a forecast.",
        },
        "warnings": warnings,
        "assumptions": [
            "Current linked asset shares are valued today; account cash is excluded.",
            "Future payments follow your split, never the existing portfolio weights. "
            "No trades or rebalancing are assumed.",
            "Monthly payments occur on each monthly plan anniversary; yearly payments on "
            "each yearly anniversary, after growth. A partial final period has no early payment.",
            "V_next = V_current × (1 + annual_return)^elapsed_years + payment.",
            "Purchasing power = nominal value / (1 + your annual inflation)^elapsed_years.",
            "Existing deposits follow their contractual compounding until maturity, then remain "
            "cash at 0% nominal growth. Future deposits are separate contracts for each payment, "
            "with your stated term and no automatic renewal.",
        ],
    }
