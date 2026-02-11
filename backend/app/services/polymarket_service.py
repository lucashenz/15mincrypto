from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.models.entities import Direction


WINDOW_SECONDS = 900


@dataclass
class MarketData:
    asset: str
    window_ts: int
    market_id: str
    market_slug: str
    yes_odds: float
    no_odds: float
    odds_source: str
    odds_live: bool
    resolver_source: str
    end_ts: int | None = None
    price_to_beat: float | None = None
    final_price: float | None = None
    yes_token_id: str | None = None
    no_token_id: str | None = None
    retries: int = 0


class PolymarketService:
    """Gamma para dados de mercado + CLOB para execução."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=10)
        self._last_yes_by_asset: dict[str, float] = {}

    @staticmethod
    def get_current_window_ts(now_ts: int | None = None) -> int:
        base = int(now_ts or time.time())
        return (base // WINDOW_SECONDS) * WINDOW_SECONDS

    @staticmethod
    def get_next_window_ts(now_ts: int | None = None) -> int:
        return PolymarketService.get_current_window_ts(now_ts) + WINDOW_SECONDS

    @staticmethod
    def _asset_slug(asset: str) -> str:
        return asset.lower()

    @staticmethod
    def build_window_slug(asset: str, window_ts: int) -> str:
        return f"{PolymarketService._asset_slug(asset)}-updown-15m-{window_ts}"

    async def fetch_market_data(self, asset: str, now_ts: int | None = None) -> MarketData:
        now_val = int(now_ts or time.time())
        current_window = self.get_current_window_ts(now_val)
        for window_ts in (current_window, current_window + WINDOW_SECONDS):
            data = await self._fetch_window_market(asset, window_ts)
            if data is not None:
                return data

        last_yes = self._last_yes_by_asset.get(asset, 0.5)
        return MarketData(
            asset=asset,
            window_ts=current_window,
            market_id=f"{asset}-unknown",
            market_slug=self.build_window_slug(asset, current_window),
            yes_odds=last_yes,
            no_odds=1 - last_yes,
            odds_source="NO_PRICE",
            odds_live=False,
            resolver_source="FALLBACK",
        )

    async def _fetch_window_market(self, asset: str, window_ts: int) -> MarketData | None:
        slug = self.build_window_slug(asset, window_ts)
        retries = 5
        delay = 2

        for attempt in range(1, retries + 1):
            market = await self._fetch_gamma_event_by_slug(slug)
            if market is None:
                market = await self._fetch_gamma_market_by_slug(slug)
            if market is None:
                market = await self._search_gamma_market(asset, window_ts)

            if market:
                yes = self._extract_yes_from_gamma_payload(market)
                if yes is not None:
                    yes = min(max(yes, 0.01), 0.99)
                    self._last_yes_by_asset[asset] = yes
                    yes_token, no_token = self._extract_yes_no_tokens(market)
                    market_id = str(market.get("id") or slug)
                    return MarketData(
                        asset=asset,
                        window_ts=window_ts,
                        market_id=market_id,
                        market_slug=str(market.get("slug") or slug),
                        yes_odds=yes,
                        no_odds=1 - yes,
                        odds_source="GAMMA_API",
                        odds_live=True,
                        resolver_source=f"RETRY_{attempt}",
                        end_ts=self._extract_market_end_ts(market) or (window_ts + WINDOW_SECONDS),
                        price_to_beat=self._extract_float(market, ["priceToBeat", "strikePrice", "targetPrice"]),
                        final_price=self._extract_float(market, ["finalPrice", "outcomePrice", "settlementPrice"]),
                        yes_token_id=yes_token,
                        no_token_id=no_token,
                        retries=attempt - 1,
                    )

            if attempt < retries:
                await self._sleep(delay)
                delay *= 2

        return None


    async def fetch_market_result(self, market_id: str, market_slug: str) -> tuple[float | None, float | None, str]:
        market = await self._fetch_gamma_market_by_id(market_id)
        source = "GAMMA_ID"
        if market is None:
            market = await self._fetch_gamma_market_by_slug(market_slug)
            source = "GAMMA_SLUG"
        if market is None:
            return None, None, "NO_RESULT"
        final_price = self._extract_float(market, ["finalPrice", "outcomePrice", "settlementPrice"])
        price_to_beat = self._extract_float(market, ["priceToBeat", "strikePrice", "targetPrice"])
        return final_price, price_to_beat, source

    async def place_clob_order(
        self,
        market_data: MarketData,
        direction: Direction,
        amount_usd: float,
        wallet_secret: str,
    ) -> tuple[bool, str]:
        if not wallet_secret.strip():
            return False, "WALLET_NOT_CONFIGURED"

        token_id = market_data.yes_token_id if direction == Direction.UP else market_data.no_token_id
        if not token_id:
            return False, "TOKEN_ID_NOT_AVAILABLE"

        payload = {
            "token_id": token_id,
            "side": "BUY",
            "price": round(market_data.yes_odds if direction == Direction.UP else market_data.no_odds, 4),
            "size": round(max(amount_usd, 1.0), 2),
            "client_order_id": f"bot-{market_data.asset}-{market_data.window_ts}-{int(time.time()*1000)}",
            "order_type": "market",
        }

        try:
            response = await self._client.post("https://clob.polymarket.com/order", json=payload)
            if 200 <= response.status_code < 300:
                return True, "CLOB_ORDER_ACCEPTED"
            return False, f"CLOB_REJECTED_{response.status_code}"
        except Exception as exc:  # noqa: BLE001
            return False, f"CLOB_ERROR::{exc.__class__.__name__}"

    async def _fetch_gamma_event_by_slug(self, slug: str) -> dict | None:
        try:
            response = await self._client.get("https://gamma-api.polymarket.com/events", params={"slug": slug})
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list) and payload:
                event = payload[0]
                if isinstance(event, dict):
                    markets = event.get("markets")
                    if isinstance(markets, list) and markets:
                        first_market = markets[0]
                        if isinstance(first_market, dict):
                            return first_market
                    return event
            if isinstance(payload, dict):
                return payload
        except Exception:
            return None
        return None


    async def _fetch_gamma_market_by_id(self, market_id: str) -> dict | None:
        try:
            response = await self._client.get(f"https://gamma-api.polymarket.com/markets/{market_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        except Exception:
            return None
        return None

    async def _fetch_gamma_market_by_slug(self, slug: str) -> dict | None:
        try:
            response = await self._client.get("https://gamma-api.polymarket.com/markets", params={"slug": slug})
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list) and payload:
                first = payload[0]
                if isinstance(first, dict):
                    return first
        except Exception:
            return None
        return None

    async def _search_gamma_market(self, asset: str, window_ts: int) -> dict | None:
        query = f"{asset.lower()} up or down 15m {window_ts}"
        try:
            response = await self._client.get("https://gamma-api.polymarket.com/markets", params={"search": query, "limit": 20})
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("question") or item.get("slug") or "").lower()
                    if asset.lower() not in title:
                        continue
                    if "up" in title and "down" in title:
                        return item
        except Exception:
            return None
        return None

    @staticmethod
    async def _sleep(seconds: int) -> None:
        import asyncio

        await asyncio.sleep(seconds)

    @staticmethod
    def _extract_market_end_ts(item: dict) -> int | None:
        for key in ("endDate", "endTime", "endTimestamp", "closingDate"):
            value = item.get(key)
            if value is None:
                continue
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                try:
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return int(dt.timestamp())
                except Exception:
                    continue
        return None

    @staticmethod
    def _extract_yes_from_gamma_payload(payload: object) -> float | None:
        if isinstance(payload, list) and payload:
            payload = payload[0]
        if not isinstance(payload, dict):
            return None

        outcome_prices = payload.get("outcomePrices")
        if isinstance(outcome_prices, list) and outcome_prices:
            try:
                return float(outcome_prices[0])
            except (TypeError, ValueError):
                pass
        if isinstance(outcome_prices, str):
            try:
                parsed = json.loads(outcome_prices)
                if isinstance(parsed, list) and parsed:
                    return float(parsed[0])
            except Exception:
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

    @staticmethod
    def _extract_clob_token_ids(market: dict) -> list[str]:
        raw = market.get("clobTokenIds") or market.get("clob_token_ids")
        if raw is None:
            return []
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed if x is not None]
            except Exception:
                return [part.strip() for part in raw.split(",") if part.strip()] if "," in raw else [raw]
        if isinstance(raw, list):
            return [str(x) for x in raw if x is not None]
        return []

    @staticmethod
    def _extract_yes_no_tokens(market: dict) -> tuple[str | None, str | None]:
        token_ids = PolymarketService._extract_clob_token_ids(market)
        if len(token_ids) >= 2:
            return token_ids[0], token_ids[1]
        if len(token_ids) == 1:
            return token_ids[0], None
        return None, None

    @staticmethod
    def _extract_float(payload: dict, keys: list[str]) -> float | None:
        for key in keys:
            if key not in payload:
                continue
            value = payload.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    async def close(self) -> None:
        await self._client.aclose()
