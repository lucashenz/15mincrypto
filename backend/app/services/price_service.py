from __future__ import annotations

from datetime import datetime, timedelta

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
        self._last_spot: dict[Asset, tuple[float, float]] = {}
        self._coingecko_blocked_until: datetime | None = None

    async def fetch_spot(self, asset: Asset) -> tuple[float, float]:
        prices = await self.fetch_spots([asset])
        return prices[asset]

    async def fetch_spots(self, assets: list[Asset]) -> dict[Asset, tuple[float, float]]:
        unique_assets = list(dict.fromkeys(assets))
        prices = await self._fetch_coingecko_batch(unique_assets)
        missing = [asset for asset in unique_assets if asset not in prices]

        for asset in missing:
            binance_spot = await self._fetch_binance_spot(asset)
            if binance_spot is not None:
                prices[asset] = (binance_spot, 0.0)
                self._last_spot[asset] = prices[asset]
                continue

            if asset in self._last_spot:
                prices[asset] = self._last_spot[asset]
            else:
                # fallback deterministico para não quebrar fluxo em cold start sem API
                prices[asset] = (0.0, 0.0)

        return prices

    async def _fetch_coingecko_batch(self, assets: list[Asset]) -> dict[Asset, tuple[float, float]]:
        now = datetime.utcnow()
        if self._coingecko_blocked_until and now < self._coingecko_blocked_until:
            return {}

        ids = ",".join(COINS[asset] for asset in assets)
        url = (
            "https://api.coingecko.com/api/v3/simple/price"
            f"?ids={ids}&vs_currencies=usd&include_24hr_change=true"
        )
        try:
            response = await self._client.get(url)
            if response.status_code == 429:
                self._coingecko_blocked_until = now + timedelta(seconds=45)
                return {}
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError:
            return {}

        result: dict[Asset, tuple[float, float]] = {}
        for asset in assets:
            coin = COINS[asset]
            info = payload.get(coin)
            if not isinstance(info, dict):
                continue
            spot = float(info.get("usd", 0.0))
            change = float(info.get("usd_24h_change", 0.0))
            result[asset] = (spot, change)
            self._last_spot[asset] = (spot, change)
        return result

    async def _fetch_binance_spot(self, asset: Asset) -> float | None:
        symbol = f"{asset.value}USDT"
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            payload = response.json()
            return float(payload["price"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None

    async def close(self) -> None:
        await self._client.aclose()
