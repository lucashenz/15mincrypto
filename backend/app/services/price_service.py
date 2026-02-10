from __future__ import annotations

from datetime import datetime, timedelta

import httpx

from app.models.entities import Asset

COINS = {
    Asset.BTC: "bitcoin",
    Asset.ETH: "ethereum",
    Asset.SOL: "solana",
}

BINANCE_SYMBOLS = {
    Asset.BTC: "BTCUSDT",
    Asset.ETH: "ETHUSDT",
    Asset.SOL: "SOLUSDT",
}

COINBASE_PRODUCTS = {
    Asset.BTC: "BTC-USD",
    Asset.ETH: "ETH-USD",
    Asset.SOL: "SOL-USD",
}


class PriceService:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=10)
        self._last_spot: dict[Asset, tuple[float, float]] = {}
        self._last_spot_updated_at: dict[Asset, datetime] = {}
        self._coingecko_blocked_until: datetime | None = None
        self.last_source_by_asset: dict[Asset, str] = {}

    async def fetch_spot(self, asset: Asset) -> tuple[float, float]:
        prices = await self.fetch_spots([asset])
        return prices[asset]

    async def fetch_spots(self, assets: list[Asset]) -> dict[Asset, tuple[float, float]]:
        unique_assets = list(dict.fromkeys(assets))

        prices = await self._fetch_coingecko_batch(unique_assets)
        missing = [asset for asset in unique_assets if asset not in prices]

        if missing:
            binance_prices = await self._fetch_binance_batch(missing)
            for asset, spot in binance_prices.items():
                prices[asset] = (spot, self._derive_change(asset, spot))
                self._remember(asset, prices[asset], "BINANCE")

        missing = [asset for asset in unique_assets if asset not in prices]
        if missing:
            for asset in missing:
                coinbase_spot = await self._fetch_coinbase_spot(asset)
                if coinbase_spot is not None:
                    prices[asset] = (coinbase_spot, self._derive_change(asset, coinbase_spot))
                    self._remember(asset, prices[asset], "COINBASE")

        missing = [asset for asset in unique_assets if asset not in prices]
        for asset in missing:
            if asset in self._last_spot:
                prices[asset] = self._last_spot[asset]
                self.last_source_by_asset[asset] = "LAST_KNOWN"
            else:
                prices[asset] = (0.0, 0.0)
                self.last_source_by_asset[asset] = "UNAVAILABLE"

        return prices

    def last_price_age_seconds(self, asset: Asset) -> int | None:
        ts = self._last_spot_updated_at.get(asset)
        if ts is None:
            return None
        return max(0, int((datetime.utcnow() - ts).total_seconds()))

    def _remember(self, asset: Asset, spot_tuple: tuple[float, float], source: str) -> None:
        self._last_spot[asset] = spot_tuple
        self._last_spot_updated_at[asset] = datetime.utcnow()
        self.last_source_by_asset[asset] = source

    def _derive_change(self, asset: Asset, current_spot: float) -> float:
        previous = self._last_spot.get(asset)
        if not previous:
            return 0.0
        prev_spot = previous[0]
        if prev_spot <= 0:
            return previous[1]
        return ((current_spot - prev_spot) / prev_spot) * 100

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
                self._coingecko_blocked_until = now + timedelta(seconds=20)
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
            self._remember(asset, result[asset], "COINGECKO")
        return result

    async def _fetch_binance_batch(self, assets: list[Asset]) -> dict[Asset, float]:
        if not assets:
            return {}

        symbols = ",".join(f'"{BINANCE_SYMBOLS[a]}"' for a in assets)
        url = f"https://api.binance.com/api/v3/ticker/price?symbols=[{symbols}]"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError:
            return {}

        if not isinstance(payload, list):
            return {}

        by_symbol: dict[str, float] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            symbol = row.get("symbol")
            price = row.get("price")
            if isinstance(symbol, str):
                try:
                    by_symbol[symbol] = float(price)
                except (TypeError, ValueError):
                    continue

        result: dict[Asset, float] = {}
        for asset in assets:
            symbol = BINANCE_SYMBOLS[asset]
            if symbol in by_symbol:
                result[asset] = by_symbol[symbol]

        return result

    async def _fetch_coinbase_spot(self, asset: Asset) -> float | None:
        product = COINBASE_PRODUCTS[asset]
        url = f"https://api.exchange.coinbase.com/products/{product}/ticker"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            payload = response.json()
            return float(payload["price"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None

    async def close(self) -> None:
        await self._client.aclose()
