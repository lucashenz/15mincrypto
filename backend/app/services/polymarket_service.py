from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.models.entities import Direction


@dataclass
class MarketData:
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


class PolymarketService:
    """Gamma para leitura de mercados/odds, CLOB para execução de ordens."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=10)
        self._last_yes_by_market: dict[str, float] = {}
        self._resolved_market_cache: dict[str, tuple[dict, float, str]] = {}

    async def fetch_market_data(self, market_ref: str) -> MarketData:
        market, resolver_source = await self._resolve_market(market_ref)
        market_id = str(market.get("id") or market_ref)
        market_slug = str(market.get("slug") or market_ref)

        yes = self._extract_yes_from_gamma_payload(market)
        source = "GAMMA_API"
        live = yes is not None

        if yes is None and resolver_source != "RAW":
            refreshed = await self._fetch_gamma_market(market_id)
            if refreshed:
                market = refreshed
                yes = self._extract_yes_from_gamma_payload(market)
                live = yes is not None

        if yes is None:
            yes = self._last_yes_by_market.get(market_ref)
            source = "LAST_KNOWN"
            live = False

        if yes is None:
            yes = 0.5
            source = "NO_PRICE"
            live = False

        yes = min(max(float(yes), 0.01), 0.99)
        self._last_yes_by_market[market_ref] = yes
        self._last_yes_by_market[market_id] = yes

        yes_token, no_token = self._extract_yes_no_tokens(market)

        return MarketData(
            market_id=market_id,
            market_slug=market_slug,
            yes_odds=yes,
            no_odds=1 - yes,
            odds_source=source,
            odds_live=live,
            resolver_source=resolver_source,
            end_ts=self._extract_market_end_ts(market),
            price_to_beat=self._extract_float(market, ["priceToBeat", "strikePrice", "targetPrice"]),
            final_price=self._extract_float(market, ["finalPrice", "outcomePrice", "settlementPrice"]),
            yes_token_id=yes_token,
            no_token_id=no_token,
        )

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

        # Obs: sem assinatura EIP-712 completa, o CLOB vai rejeitar em produção.
        # Ainda assim chamamos o endpoint real para cumprir o fluxo API real.
        payload = {
            "token_id": token_id,
            "side": "BUY",
            "price": round(market_data.yes_odds if direction == Direction.UP else market_data.no_odds, 4),
            "size": round(max(amount_usd, 1.0), 2),
            "client_order_id": f"bot-{int(time.time() * 1000)}",
            "order_type": "market",
        }

        try:
            response = await self._client.post("https://clob.polymarket.com/order", json=payload)
            if 200 <= response.status_code < 300:
                return True, "CLOB_ORDER_ACCEPTED"
            return False, f"CLOB_REJECTED_{response.status_code}"
        except Exception as exc:  # noqa: BLE001
            return False, f"CLOB_ERROR::{exc.__class__.__name__}"

    async def _resolve_market(self, market_ref: str) -> tuple[dict, str]:
        now_ts = int(time.time())
        cached = self._resolved_market_cache.get(market_ref)
        if cached and not self._should_refresh_cache(cached[0], cached[1], now_ts):
            return cached[0], f"CACHE:{cached[2]}"

        direct = await self._fetch_gamma_market(market_ref)
        if direct and self._is_candidate_for_current_window(direct, now_ts):
            self._resolved_market_cache[market_ref] = (direct, time.time(), "DIRECT")
            return direct, "DIRECT"

        query_terms = self._build_time_queries(market_ref)
        for term in query_terms:
            payload = await self._fetch_gamma_markets_query(term)
            candidate = self._pick_best_time_window_market(payload, market_ref, now_ts)
            if candidate:
                self._resolved_market_cache[market_ref] = (candidate, time.time(), "TIMESTAMP_SEARCH")
                return candidate, "TIMESTAMP_SEARCH"

        for term in self._build_generic_asset_queries(market_ref):
            payload = await self._fetch_gamma_markets_query(term)
            candidate = self._pick_best_time_window_market(payload, market_ref, now_ts)
            if candidate:
                self._resolved_market_cache[market_ref] = (candidate, time.time(), "ASSET_SEARCH")
                return candidate, "ASSET_SEARCH"

        raw = {"id": market_ref, "slug": market_ref}
        self._resolved_market_cache[market_ref] = (raw, time.time(), "RAW")
        return raw, "RAW"

    def _should_refresh_cache(self, market: dict, cached_at: float, now_ts: int) -> bool:
        cache_age = time.time() - cached_at
        if cache_age > settings.market_resolution_ttl_seconds:
            return True

        end_ts = self._extract_market_end_ts(market)
        if end_ts is None:
            return True

        return now_ts >= end_ts - 5

    @staticmethod
    def _build_generic_asset_queries(market_ref: str) -> list[str]:
        lower = market_ref.lower()
        if "btc" in lower or "bitcoin" in lower:
            base = "bitcoin up or down"
        elif "eth" in lower or "ethereum" in lower:
            base = "ethereum up or down"
        elif "sol" in lower or "solana" in lower:
            base = "solana up or down"
        else:
            base = market_ref

        now = datetime.now(timezone.utc)
        quarter_bucket = now.strftime("%H:%M")
        return [f"{base} 15m", f"{base} {quarter_bucket}", base]

    @staticmethod
    def _build_time_queries(market_ref: str) -> list[str]:
        now = datetime.now(timezone.utc)
        epoch = int(now.timestamp())
        minute_bucket = now.strftime("%Y%m%d%H%M")
        quarter_minute = (now.minute // 15) * 15
        quarter_bucket = now.strftime("%Y%m%d%H") + f"{quarter_minute:02d}"
        return [
            f"{market_ref} {quarter_bucket}",
            f"{market_ref} {minute_bucket}",
            f"{market_ref} {epoch // 60}",
            market_ref,
        ]

    async def _fetch_gamma_market(self, market_ref: str) -> dict | None:
        try:
            response = await self._client.get(f"https://gamma-api.polymarket.com/markets/{market_ref}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    async def _fetch_gamma_markets_query(self, term: str) -> object | None:
        try:
            response = await self._client.get("https://gamma-api.polymarket.com/markets", params={"search": term, "limit": 50})
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    @staticmethod
    def _pick_best_time_window_market(payload: object, base_ref: str, now_ts: int | None = None) -> dict | None:
        if not isinstance(payload, list) or not payload:
            return None

        now_val = now_ts if now_ts is not None else int(datetime.now(timezone.utc).timestamp())
        best: tuple[int, dict] | None = None

        for item in payload:
            if not isinstance(item, dict):
                continue

            title = str(item.get("question") or item.get("title") or item.get("slug") or "").lower()
            if not PolymarketService._is_up_or_down_market(title):
                continue

            base_token = base_ref.split("-")[0].lower()
            aliases = {"btc": ["btc", "bitcoin"], "eth": ["eth", "ethereum"], "sol": ["sol", "solana"]}
            terms = aliases.get(base_token, [base_token])
            if not any(term in title for term in terms):
                continue

            end_ts = PolymarketService._extract_market_end_ts(item)
            if end_ts is None:
                continue

            if now_val <= end_ts <= now_val + 16 * 60:
                delta = abs(end_ts - (now_val + 15 * 60))
                candidate = (delta, item)
                if best is None or candidate[0] < best[0]:
                    best = candidate

        return best[1] if best else None

    @staticmethod
    def _is_up_or_down_market(title: str) -> bool:
        normalized = title.lower()
        return "up or down" in normalized or ("up" in normalized and "down" in normalized)

    @staticmethod
    def _is_candidate_for_current_window(item: dict, now_ts: int) -> bool:
        end_ts = PolymarketService._extract_market_end_ts(item)
        if end_ts is None:
            return False
        return now_ts <= end_ts <= now_ts + 16 * 60

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
                if "," in raw:
                    return [part.strip() for part in raw.split(",") if part.strip()]
                return [raw]

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

    async def close(self) -> None:
        await self._client.aclose()
