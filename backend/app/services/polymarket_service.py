from __future__ import annotations

import httpx

from app.models.entities import ApiMode


class PolymarketService:
    """Busca odds da Polymarket com fallback estável (sem valores aleatórios)."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=10)
        self._last_yes_by_market: dict[str, float] = {}

    async def fetch_odds(self, market_ref: str, api_mode: ApiMode) -> tuple[float, float, str, bool]:
        yes: float | None = None
        source = "FALLBACK"
        live = False

        if api_mode == ApiMode.CLOB:
            yes = await self._fetch_clob_yes(market_ref)
            source = "CLOB"
            live = yes is not None

        if yes is None:
            gamma_yes = await self._fetch_gamma_yes(market_ref)
            if gamma_yes is not None:
                yes = gamma_yes
                source = "GAMMA_API"
                live = True

        if yes is None:
            yes = self._last_yes_by_market.get(market_ref, 0.5)
            source = "LAST_KNOWN"
            live = False

        yes = min(max(float(yes), 0.05), 0.95)
        self._last_yes_by_market[market_ref] = yes
        return yes, 1 - yes, source, live

    async def _fetch_clob_yes(self, market_ref: str) -> float | None:
        """
        market_ref aceita market id ou slug.
        Endpoint CLOB pode variar por mercado, então aqui só retornamos quando vier chave compatível.
        """
        url = f"https://clob.polymarket.com/markets/{market_ref}"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                if "yesPrice" in payload:
                    return float(payload["yesPrice"])
                if "bestBid" in payload:
                    return float(payload["bestBid"])
        except Exception:
            return None
        return None

    async def _fetch_gamma_yes(self, market_ref: str) -> float | None:
        """
        Tenta por ID direto e depois por slug/search.
        """
        urls = [
            f"https://gamma-api.polymarket.com/markets/{market_ref}",
            f"https://gamma-api.polymarket.com/markets?slug={market_ref}",
            f"https://gamma-api.polymarket.com/markets?search={market_ref}",
        ]
        for url in urls:
            try:
                response = await self._client.get(url)
                response.raise_for_status()
                payload = response.json()
                yes = self._extract_yes_from_gamma_payload(payload)
                if yes is not None:
                    return yes
            except Exception:
                continue
        return None

    @staticmethod
    def _extract_yes_from_gamma_payload(payload: object) -> float | None:
        if isinstance(payload, list) and payload:
            payload = payload[0]

        if isinstance(payload, dict):
            outcome_prices = payload.get("outcomePrices")
            if isinstance(outcome_prices, list) and outcome_prices:
                try:
                    return float(outcome_prices[0])
                except (TypeError, ValueError):
                    pass

            outcomes = payload.get("outcomes")
            if isinstance(outcomes, list) and outcomes:
                first = outcomes[0]
                if isinstance(first, dict):
                    for key in ("price", "lastPrice", "bestBid"):
                        if key in first:
                            try:
                                return float(first[key])
                            except (TypeError, ValueError):
                                continue
        return None

    async def close(self) -> None:
        await self._client.aclose()
