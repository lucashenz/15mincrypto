import asyncio

import httpx
import pytest

from app.models.entities import Asset
from app.services.price_service import PriceService


class DummyResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        return self._payload


def test_fetch_spots_falls_back_to_binance_when_coingecko_429():
    svc = PriceService()

    async def fake_get(url):
        if "coingecko" in url:
            return DummyResponse(status_code=429)
        if "binance" in url:
            return DummyResponse(payload={"price": "101000.12"})
        return DummyResponse(status_code=500)

    svc._client.get = fake_get

    result = asyncio.run(svc.fetch_spots([Asset.BTC]))
    assert Asset.BTC in result
    assert result[Asset.BTC][0] == pytest.approx(101000.12)

    asyncio.run(svc.close())
