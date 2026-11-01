"""Consumer-visible regressions for dated AAA national pricing."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock

from aiohttp import ClientError

from fuel_prices import FuelPrices, MAX_RESPONSE, PriceUnavailable, parse_aaa
from server import APIError, Service

UTC = timezone.utc
NOW = datetime(2026, 11, 1, 18, tzinfo=UTC)


def aaa(date="11/1/26", price="3.259"):
    return f"""<p>Price as of<br>{date}</p><table><tr><th></th><th>Regular</th>
        <th>Mid-Grade</th><th>Premium</th></tr><tr><td>Current Avg.</td>
        <td>${price}</td><td>$4.500</td><td>$5.000</td></tr>
        <tr><td>Yesterday Avg.</td><td>$1.000</td></tr></table>"""


class FuelParsingTest(unittest.TestCase):
    def test_current_regular_national_average(self):
        for date in ("11/1/26", "11/01/2026"):
            self.assertEqual(parse_aaa(aaa(date), NOW), {
                "price_per_gallon": 3.259, "date": "2026-11-01", "source": "aaa",
            })

    def test_unusable_prices_and_dates_are_rejected(self):
        documents = [aaa("10/31/26"), aaa("11/2/26"), aaa("2/30/26"),
            aaa().replace("Price as of", "Previous price"),
            aaa().replace("Regular", "Diesel"), aaa().replace("Current Avg.", "Yesterday Avg.")]
        documents += [aaa(price=value) for value in ("nan", "inf", "0", "-1", "1e3", "9" * 400)]
        for document in documents:
            with self.subTest(document=document), self.assertRaises(ValueError):
                parse_aaa(document, NOW)

    def test_hidden_prices_and_dates_are_not_used(self):
        with self.assertRaises(ValueError):
            parse_aaa("<script>Price as of 11/1/26</script>" + aaa("10/31/26"), NOW)


class FuelProviderTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = NOW
        self.provider = FuelPrices(None, clock=lambda: self.now)
        self.provider._fetch = AsyncMock(return_value=aaa())

    async def test_concurrent_consumers_share_current_quote(self):
        quotes = await asyncio.gather(*(self.provider.price() for _ in range(10)))
        expected = {"price_per_gallon": 3.259, "date": "2026-11-01", "source": "aaa",
            "valid_until": datetime(2026, 11, 2, 5, tzinfo=UTC).timestamp()}
        self.assertTrue(all(quote == expected for quote in quotes))
        self.assertEqual(self.provider._fetch.await_count, 1)
        quotes[0]["price_per_gallon"] = 99
        self.assertEqual(await self.provider.price(), expected)

    async def test_midnight_expires_quote_without_serving_stale_data(self):
        await self.provider.price()
        self.now = datetime(2026, 11, 2, 5, tzinfo=UTC)
        with self.assertRaises(PriceUnavailable):
            await self.provider.price()
        self.provider._fetch.return_value = aaa("11/2/26", "3.100")
        self.now += timedelta(seconds=60)
        quote = await self.provider.price()
        self.assertEqual(quote["date"], "2026-11-02")
        self.assertEqual(quote["price_per_gallon"], 3.1)

    async def test_fetch_crossing_midnight_uses_refreshed_date_and_expiry(self):
        self.now = datetime(2026, 11, 2, 4, 59, 59, tzinfo=UTC)

        async def fetch():
            self.now = datetime(2026, 11, 2, 5, tzinfo=UTC)
            return aaa("11/2/26")

        self.provider._fetch.side_effect = fetch
        quote = await self.provider.price()
        self.assertEqual(quote["date"], "2026-11-02")
        self.assertEqual(quote["valid_until"], datetime(2026, 11, 3, 5, tzinfo=UTC).timestamp())

    async def test_fetch_crossing_midnight_rejects_previous_days_response(self):
        self.now = datetime(2026, 11, 2, 4, 59, 59, tzinfo=UTC)

        async def fetch():
            self.now = datetime(2026, 11, 2, 5, tzinfo=UTC)
            return aaa()

        self.provider._fetch.side_effect = fetch
        with self.assertRaises(PriceUnavailable):
            await self.provider.price()

    async def test_eastern_daylight_saving_expiry(self):
        self.now = datetime(2026, 11, 1, 4, tzinfo=UTC)
        quote = await self.provider.price()
        self.assertEqual(quote["valid_until"] - self.now.timestamp(), 25 * 3600)
        self.now = datetime(2026, 3, 8, 5, tzinfo=UTC)
        self.provider = FuelPrices(None, clock=lambda: self.now)
        self.provider._fetch = AsyncMock(return_value=aaa("3/8/26"))
        quote = await self.provider.price()
        self.assertEqual(quote["valid_until"] - self.now.timestamp(), 23 * 3600)

    async def test_failures_are_shared_for_sixty_seconds_then_retried(self):
        for failure in (PriceUnavailable(), ClientError(), asyncio.TimeoutError(), ValueError()):
            with self.subTest(failure=type(failure).__name__):
                provider = FuelPrices(None, clock=lambda: self.now)
                provider._fetch = AsyncMock(side_effect=failure)
                results = await asyncio.gather(*(provider.price() for _ in range(10)), return_exceptions=True)
                self.assertTrue(all(isinstance(result, PriceUnavailable) for result in results))
                self.assertEqual(provider._fetch.await_count, 1)
                self.now += timedelta(seconds=59)
                with self.assertRaises(PriceUnavailable):
                    await provider.price()
                self.assertEqual(provider._fetch.await_count, 1)
                self.now += timedelta(seconds=1)
                provider._fetch.side_effect = None
                provider._fetch.return_value = aaa()
                self.assertEqual((await provider.price())["source"], "aaa")
                self.assertEqual(provider._fetch.await_count, 2)

    async def test_http_errors_oversized_and_invalid_documents_are_unavailable(self):
        for status, raw in ((503, b"unavailable"), (200, b"x" * (MAX_RESPONSE + 1)),
                (200, b"\xff"), (200, b"not a price")):
            with self.subTest(status=status, size=len(raw)):
                response = SimpleNamespace(status=status, content=SimpleNamespace(readexactly=AsyncMock()))
                if len(raw) > MAX_RESPONSE:
                    response.content.readexactly.return_value = raw
                else:
                    response.content.readexactly.side_effect = asyncio.IncompleteReadError(raw, MAX_RESPONSE + 1)
                http = MagicMock()
                http.request.return_value.__aenter__.return_value = response
                provider = FuelPrices(http, clock=lambda: NOW)
                with self.assertRaises(PriceUnavailable):
                    await provider.price()

    async def test_bounded_http_response_can_supply_a_quote(self):
        raw = aaa().encode()
        response = SimpleNamespace(status=200, content=SimpleNamespace(readexactly=AsyncMock(
            side_effect=asyncio.IncompleteReadError(raw, MAX_RESPONSE + 1))))
        http = MagicMock()
        http.request.return_value.__aenter__.return_value = response
        self.assertEqual((await FuelPrices(http, clock=lambda: NOW).price())["price_per_gallon"], 3.259)


class FuelEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_unavailability_is_service_unavailable(self):
        service = SimpleNamespace(rate_limit=MagicMock(), fuel_prices=SimpleNamespace(price=AsyncMock(side_effect=PriceUnavailable())))
        with self.assertRaises(APIError) as unavailable:
            await Service.fuel_price(service, {})
        self.assertEqual(unavailable.exception.status, 503)
