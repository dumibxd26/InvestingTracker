import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.market_data import (
    ExchangeRateQuote,
    MarketDataProviderError,
    MarketQuote,
    TwelveDataClient,
)
from app.models import Currency


def test_symbol_search_maps_supported_stocks_and_etfs() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/symbol_search")
        assert request.url.params["symbol"] == "MSFT"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "symbol": "MSFT",
                        "instrument_name": "Microsoft Corporation",
                        "exchange": "NASDAQ",
                        "mic_code": "XNAS",
                        "currency": "USD",
                        "instrument_type": "Common Stock",
                        "country": "United States",
                    },
                    {
                        "symbol": "QQQ",
                        "instrument_name": "Invesco QQQ Trust",
                        "exchange": "NASDAQ",
                        "mic_code": "XNAS",
                        "currency": "USD",
                        "instrument_type": "ETF",
                        "country": "United States",
                    },
                    {
                        "symbol": "MSFT240621C400",
                        "instrument_name": "MSFT Call",
                        "exchange": "OPRA",
                        "currency": "USD",
                        "instrument_type": "Option",
                    },
                ]
            },
        )

    client = TwelveDataClient("test-key", transport=httpx.MockTransport(respond))
    results = asyncio.run(client.search_symbols("MSFT"))

    assert [(item.symbol, item.instrument_type) for item in results] == [
        ("MSFT", "STOCK"),
        ("QQQ", "ETF"),
    ]
    assert results[0].currency == Currency.USD
    assert results[0].mic_code == "XNAS"


def test_quote_and_fx_responses_are_parsed_as_decimal_and_utc() -> None:
    timestamp = int(datetime(2026, 10, 10, 12, 0, tzinfo=UTC).timestamp())

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/quote"):
            return httpx.Response(
                200,
                json={
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "close": "227.54",
                    "currency": "USD",
                    "last_quote_at": str(timestamp),
                    "is_market_open": True,
                    "mic_code": "XNAS",
                    "exchange": "NASDAQ",
                },
            )
        return httpx.Response(
            200,
            json={"rate": "4.97654321", "timestamp": str(timestamp)},
        )

    client = TwelveDataClient("test-key", transport=httpx.MockTransport(respond))
    quote, fx = asyncio.run(
        _fetch_quote_and_fx(client)
    )

    assert quote.price == Decimal("227.54")
    assert quote.currency == Currency.USD
    assert quote.is_market_open is True
    assert quote.mic_code == "XNAS"
    assert quote.observed_at == datetime.fromtimestamp(timestamp, tz=UTC)
    assert fx.base_currency == Currency.EUR
    assert fx.quote_currency == Currency.RON
    assert fx.rate == Decimal("4.97654321")


async def _fetch_quote_and_fx(
    client: TwelveDataClient,
) -> tuple[MarketQuote, ExchangeRateQuote]:
    quote = await client.quote("AAPL", "XNAS")
    fx = await client.exchange_rate("EUR/RON")
    return quote, fx


def test_provider_rate_limit_is_reported_without_fallback_data() -> None:
    client = TwelveDataClient(
        "test-key",
        transport=httpx.MockTransport(lambda request: httpx.Response(429)),
    )

    with pytest.raises(MarketDataProviderError, match="rate limit") as error:
        asyncio.run(client.quote("AAPL"))

    assert error.value.status_code == 429
