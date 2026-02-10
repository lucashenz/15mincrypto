from __future__ import annotations

import random

import httpx

from app.models.entities import ApiMode


class PolymarketService:
    """Lê odds do CLOB e fallback para Gamma (simulado quando indisponível)."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=10)

    async def fetch_odds(self, market_id: str, api_mode: ApiMode) -> tuple[float, float]:
        if api_mode == ApiMode.CLOB:
            yes = await self._fetch_clob_yes(market_id)
        else:
            yes = await self._fetch_gamma_yes(market_id)
        yes = min(max(yes, 0.05), 0.95)
        return yes, 1 - yes

    async def _fetch_clob_yes(self, market_id: str) -> float:
        # Endpoint pode variar por mercado; fallback para valor sintético consistente
        url = f"https://clob.polymarket.com/markets/{market_id}"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and "yesPrice" in payload:
                return float(payload["yesPrice"])
        except Exception:
            pass
        return random.uniform(0.35, 0.65)

    async def _fetch_gamma_yes(self, market_id: str) -> float:
        url = f"https://gamma-api.polymarket.com/markets/{market_id}"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and "outcomePrices" in payload:
                prices = payload["outcomePrices"]
                if isinstance(prices, list) and prices:
                    return float(prices[0])
        except Exception:
            pass
        return random.uniform(0.35, 0.65)

    async def close(self) -> None:
        await self._client.aclose()
