from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.models.entities import ApiMode


class PolymarketService:
    """Busca odds da Polymarket com rotação automática de mercados 15m."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=20)
        self._last_yes_by_market: dict[str, float] = {}
        self._resolved_market_cache: dict[str, tuple[dict, float, str]] = {}

    async def fetch_odds(
        self,
        market_ref: str,
        api_mode: ApiMode,
        *,
        fallback_momentum: float | None = None,
    ) -> tuple[float, float, str, bool]:
        yes: float | None = None
        source = "FALLBACK"
        live = False

        market, resolver_source = await self._resolve_market(market_ref)
        resolved_ref = str(market.get("id") or market.get("slug") or market_ref)

        if api_mode == ApiMode.CLOB:
            yes = await self._fetch_clob_yes_from_market(market)
            source = "CLOB"
            live = yes is not None

        if yes is None:
            gamma_yes = self._extract_yes_from_gamma_payload(market)
            if gamma_yes is None and resolver_source != "RAW":
                gamma_yes = await self._fetch_gamma_yes(resolved_ref)
            if gamma_yes is not None:
                yes = gamma_yes
                source = "GAMMA_API"
                live = True

        if yes is None:
            yes = await self._fetch_fallback_crypto_market(market_ref)
            if yes is not None:
                source = "FALLBACK_CRYPTO"
                live = False
                # Aplica drift em tempo real baseado no momentum do preço spot
                if fallback_momentum is not None:
                    drift = 0.15 * max(-1.0, min(1.0, fallback_momentum))
                    yes = min(0.99, max(0.01, yes + drift * 0.1))

        if yes is None:
            yes = self._last_yes_by_market.get(market_ref)
            source = "LAST_KNOWN"
            live = False

        if yes is None and fallback_momentum is not None:
            yes = 0.5 + 0.2 * max(-1.0, min(1.0, fallback_momentum))
            source = "SYNTHETIC_MOMENTUM"
            live = False

        if yes is None:
            return 0.5, 0.5, f"NO_PRICE::{resolver_source}", False

        yes = min(max(float(yes), 0.01), 0.99)
        self._last_yes_by_market[market_ref] = yes
        self._last_yes_by_market[resolved_ref] = yes
        return yes, 1 - yes, f"{source}::{resolver_source}", live

    async def _resolve_market(self, market_ref: str) -> tuple[dict, str]:
        """
        Resolve slug base (ex: btc-updown-15m) para o mercado ativo da janela atual,
        com atualização automática no fechamento/abertura de cada janela de 15 minutos.
        """
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

        # força refresh no final/virada da janela para capturar o novo mercado imediatamente
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
        quarter_minute = (now.minute // 15) * 15
        quarter_bucket = now.strftime("%H:%M")
        return [
            f"{base} 15m",
            f"{base} {quarter_bucket}",
            base,
        ]

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

    async def _fetch_clob_yes_from_market(self, market: dict) -> float | None:
        token_ids = self._extract_clob_token_ids(market)
        if not token_ids:
            market_ref = str(market.get("id") or market.get("slug") or "")
            return await self._fetch_clob_yes_legacy(market_ref) if market_ref else None

        yes_token = token_ids[0]
        if not yes_token:
            return None

        url = "https://clob.polymarket.com/book"
        try:
            response = await self._client.get(url, params={"token_id": yes_token})
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return None

        return self._extract_yes_from_clob_book(payload)

    async def _fetch_clob_yes_legacy(self, market_ref: str) -> float | None:
        url = f"https://clob.polymarket.com/markets/{market_ref}"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                for key in ("yesPrice", "lastTradePrice", "bestBid"):
                    if key in payload:
                        return float(payload[key])
        except Exception:
            return None
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
    def _extract_yes_from_clob_book(payload: object) -> float | None:
        if not isinstance(payload, dict):
            return None

        best_bid = PolymarketService._extract_book_price(payload.get("bids"), from_start=False)
        best_ask = PolymarketService._extract_book_price(payload.get("asks"), from_start=True)

        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2
        if best_bid is not None:
            return best_bid
        if best_ask is not None:
            return best_ask
        return None

    @staticmethod
    def _extract_book_price(levels: object, *, from_start: bool) -> float | None:
        if not isinstance(levels, list) or not levels:
            return None

        level = levels[0] if from_start else levels[-1]
        if isinstance(level, dict):
            for key in ("price", "p"):
                if key in level:
                    try:
                        return float(level[key])
                    except (TypeError, ValueError):
                        return None

        if isinstance(level, list) and level:
            try:
                return float(level[0])
            except (TypeError, ValueError):
                return None

        return None

    async def _fetch_gamma_yes(self, market_ref: str) -> float | None:
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

    async def _fetch_fallback_crypto_market(self, market_ref: str) -> float | None:
        """
        Fallback: usa mercados crypto ativos (ex: MicroStrategy) como proxy de sentimento
        quando os mercados 15m não estão disponíveis.
        """
        lower = market_ref.lower()
        if "btc" not in lower and "bitcoin" not in lower:
            return None

        try:
            response = await self._client.get(
                "https://gamma-api.polymarket.com/events",
                params={"closed": False, "tag_id": 21, "limit": 30},
            )
            response.raise_for_status()
            events = response.json()
        except Exception:
            return None

        if not isinstance(events, list):
            return None

        for event in events:
            if not isinstance(event, dict):
                continue
            title = str(event.get("title") or event.get("slug") or "").lower()
            if "bitcoin" not in title and "btc" not in title:
                continue
            markets = event.get("markets") or []
            for m in markets:
                if not isinstance(m, dict) or m.get("closed"):
                    continue
                if not m.get("acceptingOrders", True):
                    continue
                outcome_prices = m.get("outcomePrices")
                if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                    try:
                        no_price = float(outcome_prices[1])
                        if 0.01 <= no_price <= 0.99:
                            return no_price
                    except (TypeError, ValueError):
                        pass
                if isinstance(outcome_prices, str):
                    try:
                        parsed = json.loads(outcome_prices)
                        if isinstance(parsed, list) and len(parsed) >= 2:
                            no_price = float(parsed[1])
                            if 0.01 <= no_price <= 0.99:
                                return no_price
                    except Exception:
                        pass
        return None

    async def _fetch_gamma_market(self, market_ref: str) -> dict | None:
        try:
            response = await self._client.get(f"https://gamma-api.polymarket.com/markets/{market_ref}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        except Exception:
            return None
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
            base_token = base_ref.split("-")[0].lower()
            aliases = {
                "btc": ["btc", "bitcoin"],
                "eth": ["eth", "ethereum"],
                "sol": ["sol", "solana"],
            }
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

        if isinstance(payload, dict):
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

    async def close(self) -> None:
        await self._client.aclose()
