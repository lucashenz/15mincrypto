from __future__ import annotations

import httpx

from app.models.entities import Asset

COINS = {
    Asset.BTC: "bitcoin",
    Asset.ETH: "ethereum",
    Asset.SOL: "solana",
}


class PriceService:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=10)

    async def fetch_spot(self, asset: Asset) -> tuple[float, float]:
        coin = COINS[asset]
        url = (
            "https://api.coingecko.com/api/v3/simple/price"
            f"?ids={coin}&vs_currencies=usd&include_24hr_change=true"
        )
        response = await self._client.get(url)
        response.raise_for_status()
        payload = response.json()[coin]
        return float(payload["usd"]), float(payload.get("usd_24h_change", 0.0))

    async def close(self) -> None:
        await self._client.aclose()
