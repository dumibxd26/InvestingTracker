"""Capital-market assumptions and fixed parameters for the goal-based investing engine."""

from __future__ import annotations

from dataclasses import dataclass

ASSET_CLASSES: tuple[str, ...] = (
    "CASH_DEPOSIT",
    "SHORT_TERM_BOND",
    "INVESTMENT_BOND",
    "DIVIDEND_VALUE_ETF",
    "BROAD_EQUITY_ETF",
    "BLUE_CHIP_STOCK",
    "HIGH_BETA_SPEC",
)
MACRO_BUCKETS: tuple[str, ...] = ("CASH", "BONDS", "EQUITIES")
SINGLE_STOCK_CLASSES = frozenset({"BLUE_CHIP_STOCK", "HIGH_BETA_SPEC"})
RISK_PROFILES: tuple[str, ...] = ("CONSERVATIVE", "MODERATE", "AGGRESSIVE")
SUPPORTED_CURRENCIES: tuple[str, ...] = ("EUR", "USD", "RON")


@dataclass(frozen=True)
class CapitalMarketAssumption:
    asset_class: str
    macro_bucket: str
    expected_return: float
    dividend_yield: float
    volatility: float
    risk_score: int


def _cma(
    asset_class: str,
    macro_bucket: str,
    expected_return: float,
    dividend_yield: float,
    volatility: float,
    risk_score: int,
) -> CapitalMarketAssumption:
    return CapitalMarketAssumption(
        asset_class, macro_bucket, expected_return, dividend_yield, volatility, risk_score
    )


CMA_CONFIG: dict[str, CapitalMarketAssumption] = {
    "CASH_DEPOSIT": _cma("CASH_DEPOSIT", "CASH", 0.038, 0.038, 0.005, 1),
    "SHORT_TERM_BOND": _cma("SHORT_TERM_BOND", "CASH", 0.043, 0.041, 0.018, 1),
    "INVESTMENT_BOND": _cma("INVESTMENT_BOND", "BONDS", 0.050, 0.040, 0.060, 2),
    "DIVIDEND_VALUE_ETF": _cma("DIVIDEND_VALUE_ETF", "EQUITIES", 0.082, 0.034, 0.135, 3),
    "BROAD_EQUITY_ETF": _cma("BROAD_EQUITY_ETF", "EQUITIES", 0.090, 0.016, 0.160, 3),
    "BLUE_CHIP_STOCK": _cma("BLUE_CHIP_STOCK", "EQUITIES", 0.102, 0.008, 0.250, 4),
    "HIGH_BETA_SPEC": _cma("HIGH_BETA_SPEC", "EQUITIES", 0.125, 0.000, 0.480, 5),
}

BUCKET_CORRELATIONS: dict[str, dict[str, float]] = {
    "CASH": {"CASH": 1.00, "BONDS": 0.15, "EQUITIES": 0.00},
    "BONDS": {"CASH": 0.15, "BONDS": 1.00, "EQUITIES": 0.20},
    "EQUITIES": {"CASH": 0.00, "BONDS": 0.20, "EQUITIES": 1.00},
}

# Annual inflation parity used for PPP FX drift and target inflation.
CURRENCY_INFLATION_PARITY: dict[str, float] = {"EUR": 0.022, "USD": 0.025, "RON": 0.040}

MARKET_VOLATILITY = CMA_CONFIG["BROAD_EQUITY_ETF"].volatility
IDIOSYNCRATIC_VOLATILITY = 0.14
MAX_STOCK_VOLATILITY = 0.65
CONCENTRATION_VOLATILITY = 0.12
DRIFT_THRESHOLD = 0.05
SECTOR_CAP = 0.40
FX_VOLATILITY = 0.085
EQUITY_FX_CORRELATION = -0.15
BOND_FX_CORRELATION = 0.05
DEFAULT_SEED = 2026
HALF_PATHS = 1000
# Share of equity weight assumed unhedged in the optimized glide-path lever (spec default).
GLIDE_UNHEDGED_SHARE_OF_EQUITIES = 0.6
MAX_EXTENSION_MONTHS = 120


@dataclass(frozen=True)
class CatalogSecurity:
    ticker: str
    name: str
    asset_class: str
    macro_bucket: str
    sector: str
    trading_currency: str
    underlying_currency: str
    is_currency_hedged: bool
    expense_ratio: float
    min_horizon_years: float
    rationale_tag: str


DEFAULT_BENCHMARK_CATALOG: tuple[CatalogSecurity, ...] = (
    CatalogSecurity(
        "XEON.DE",
        "Xtrackers II EUR Overnight Rate Swap UCITS ETF",
        "SHORT_TERM_BOND",
        "CASH",
        "FIXED_INCOME",
        "EUR",
        "EUR",
        True,
        0.0010,
        0,
        "Zero-FX-risk EUR overnight rate preservation for short horizons",
    ),
    CatalogSecurity(
        "SGOV",
        "iShares 0-3 Month Treasury Bond ETF",
        "SHORT_TERM_BOND",
        "CASH",
        "FIXED_INCOME",
        "USD",
        "USD",
        False,
        0.0009,
        0,
        "Ultra-safe USD Treasury bill yield for USD-denominated goals",
    ),
    CatalogSecurity(
        "AGGH.DE",
        "iShares Core Global Aggregate Bond UCITS ETF (EUR Hedged)",
        "INVESTMENT_BOND",
        "BONDS",
        "FIXED_INCOME",
        "EUR",
        "EUR",
        True,
        0.0010,
        2,
        "EUR-hedged global investment-grade bonds to dampen equity volatility without FX risk",
    ),
    CatalogSecurity(
        "BND",
        "Vanguard Total Bond Market ETF",
        "INVESTMENT_BOND",
        "BONDS",
        "FIXED_INCOME",
        "USD",
        "USD",
        False,
        0.0003,
        2,
        "Core USD investment-grade bond ballast for medium-term goals",
    ),
    CatalogSecurity(
        "VWCE.DE",
        "Vanguard FTSE All-World UCITS ETF",
        "BROAD_EQUITY_ETF",
        "EQUITIES",
        "BROAD_MARKET",
        "EUR",
        "USD",
        False,
        0.0022,
        4,
        "Global diversification across 3,600+ companies in developed and emerging markets",
    ),
    CatalogSecurity(
        "VOO",
        "Vanguard S&P 500 ETF",
        "BROAD_EQUITY_ETF",
        "EQUITIES",
        "BROAD_MARKET",
        "USD",
        "USD",
        False,
        0.0003,
        4,
        "Low-cost core exposure to 500 leading U.S. large-cap companies",
    ),
    CatalogSecurity(
        "SCHD",
        "Schwab U.S. Dividend Equity ETF",
        "DIVIDEND_VALUE_ETF",
        "EQUITIES",
        "DIVIDEND_VALUE",
        "USD",
        "USD",
        False,
        0.0006,
        3,
        "Cash-flowing value equities to counterbalance tech-heavy concentration",
    ),
)
