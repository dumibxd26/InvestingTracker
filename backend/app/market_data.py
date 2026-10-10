from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.models import Currency

PROVIDER_NAME = "Twelve Data"
BASE_URL = "https://api.twelvedata.com"


class MarketDataProviderError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class MarketSymbol:
    symbol: str
    name: str
    exchange: str
    mic_code: str | None
    currency: Currency
    instrument_type: str
    country: str


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    name: str
    price: Decimal
    currency: Currency
    observed_at: datetime
    is_market_open: bool | None
    mic_code: str | None
    exchange: str


@dataclass(frozen=True)
class ExchangeRateQuote:
    base_currency: Currency
    quote_currency: Currency
    rate: Decimal
    observed_at: datetime


class TwelveDataClient:
    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 10,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise MarketDataProviderError(
                503,
                "Set TWELVE_DATA_API_KEY in .env and restart the backend to enable market data.",
            )
        self._api_key = normalized_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def _get_json(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        request_params = {**params, "apikey": self._api_key}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = await client.get(
                    f"{BASE_URL}/{endpoint}",
                    params=request_params,
                )
        except httpx.TimeoutException as error:
            raise MarketDataProviderError(
                504, "Twelve Data did not respond before the market-data timeout."
            ) from error
        except httpx.RequestError as error:
            raise MarketDataProviderError(
                502, "Twelve Data could not be reached."
            ) from error

        if response.status_code == 429:
            raise MarketDataProviderError(
                429,
                (
                    "Twelve Data rate limit reached. Wait before refreshing again "
                    "or check plan credits."
                ),
            )
        if response.status_code in {401, 403}:
            raise MarketDataProviderError(
                502, "Twelve Data rejected the configured API key or data-plan entitlement."
            )
        if response.status_code == 404:
            raise MarketDataProviderError(404, "Twelve Data could not find that market symbol.")
        if not response.is_success:
            raise MarketDataProviderError(
                502, f"Twelve Data returned HTTP {response.status_code}."
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise MarketDataProviderError(
                502, "Twelve Data returned an unreadable market-data response."
            ) from error
        if not isinstance(payload, dict):
            raise MarketDataProviderError(
                502, "Twelve Data returned an unexpected market-data response."
            )

        if str(payload.get("status", "")).lower() == "error":
            provider_code = str(payload.get("code", ""))
            if provider_code in {"401", "403"}:
                raise MarketDataProviderError(
                    502, "Twelve Data rejected the configured API key or data-plan entitlement."
                )
            if provider_code in {"429", "42901", "42902"}:
                raise MarketDataProviderError(
                    429,
                    (
                        "Twelve Data rate limit reached. Wait before refreshing again "
                        "or check plan credits."
                    ),
                )
            if provider_code in {"404", "400"}:
                raise MarketDataProviderError(
                    404, "Twelve Data could not find a quote for that market symbol."
                )
            raise MarketDataProviderError(
                502, "Twelve Data returned an error. Check the selected symbol and API plan."
            )
        return payload

    async def search_symbols(self, query: str, limit: int = 8) -> list[MarketSymbol]:
        payload = await self._get_json(
            "symbol_search",
            {"symbol": query, "outputsize": str(limit)},
        )
        raw_results = payload.get("data", [])
        if not isinstance(raw_results, list):
            raise MarketDataProviderError(
                502, "Twelve Data returned an invalid symbol-search result."
            )

        results: list[MarketSymbol] = []
        for result in raw_results:
            if not isinstance(result, dict):
                continue
            raw_type = str(result.get("instrument_type") or "").strip()
            type_lower = raw_type.lower()
            if "etf" in type_lower:
                instrument_type = "ETF"
            elif any(label in type_lower for label in ("stock", "depositary receipt", "reit")):
                instrument_type = "STOCK"
            else:
                continue
            symbol = str(result.get("symbol") or "").strip()
            name = str(result.get("instrument_name") or "").strip()
            exchange = str(result.get("exchange") or "").strip()
            currency_code = str(result.get("currency") or "").strip().upper()
            if not symbol or not name or not currency_code:
                continue
            try:
                currency = Currency(currency_code)
            except ValueError:
                continue
            results.append(
                MarketSymbol(
                    symbol=symbol,
                    name=name,
                    exchange=exchange,
                    mic_code=str(result.get("mic_code") or "").strip() or None,
                    currency=currency,
                    instrument_type=instrument_type,
                    country=str(result.get("country") or "").strip(),
                )
            )
        return results

    async def quote(
        self,
        symbol: str,
        mic_code: str | None = None,
        exchange: str | None = None,
    ) -> MarketQuote:
        params = {"symbol": symbol, "interval": "1min", "timezone": "UTC"}
        if mic_code:
            params["mic_code"] = mic_code
        elif exchange:
            params["exchange"] = exchange
        payload = await self._get_json("quote", params)
        try:
            price = Decimal(str(payload["close"]))
            currency = Currency(str(payload["currency"]).upper())
            timestamp = int(payload.get("last_quote_at") or payload["timestamp"])
        except (KeyError, ValueError, TypeError, InvalidOperation) as error:
            raise MarketDataProviderError(
                502, "Twelve Data returned an invalid quote for the selected symbol."
            ) from error
        if not price.is_finite() or price <= 0 or timestamp <= 0:
            raise MarketDataProviderError(
                502, "Twelve Data returned a non-positive price or invalid quote timestamp."
            )
        is_market_open = payload.get("is_market_open")
        if not isinstance(is_market_open, bool):
            is_market_open = None
        return MarketQuote(
            symbol=str(payload.get("symbol") or symbol).strip(),
            name=str(payload.get("name") or symbol).strip(),
            price=price,
            currency=currency,
            observed_at=datetime.fromtimestamp(timestamp, tz=UTC),
            is_market_open=is_market_open,
            mic_code=str(payload.get("mic_code") or "").strip() or None,
            exchange=str(payload.get("exchange") or "").strip(),
        )

    async def exchange_rate(self, pair: str) -> ExchangeRateQuote:
        try:
            base, quote = pair.upper().split("/", maxsplit=1)
            base_currency = Currency(base)
            quote_currency = Currency(quote)
        except (ValueError, TypeError) as error:
            raise MarketDataProviderError(
                422, "Market-data currency pair is not supported."
            ) from error
        payload = await self._get_json(
            "exchange_rate",
            {"symbol": f"{base}/{quote}", "timezone": "UTC", "dp": "10"},
        )
        try:
            rate = Decimal(str(payload["rate"]))
            timestamp = int(payload["timestamp"])
        except (KeyError, ValueError, TypeError, InvalidOperation) as error:
            raise MarketDataProviderError(
                502, f"Twelve Data returned an invalid exchange rate for {pair}."
            ) from error
        if not rate.is_finite() or rate <= 0 or timestamp <= 0:
            raise MarketDataProviderError(
                502, f"Twelve Data returned a non-positive exchange rate for {pair}."
            )
        return ExchangeRateQuote(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=rate,
            observed_at=datetime.fromtimestamp(timestamp, tz=UTC),
        )
