from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.models.entities import ApiMode


class PolymarketService:
    """Busca odds da Polymarket com resolução dinâmica de mercado 15m por timestamp."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=10)
        self._last_yes_by_market: dict[str, float] = {}
        self._resolved_market_cache: dict[str, tuple[str, float]] = {}

    async def fetch_odds(self, market_ref: str, api_mode: ApiMode) -> tuple[float, float, str, bool]:
        yes: float | None = None
        source = "FALLBACK"
        live = False

        resolved_ref, resolver_source = await self._resolve_market_ref(market_ref)

        if api_mode == ApiMode.CLOB:
            yes = await self._fetch_clob_yes(resolved_ref)
            source = "CLOB"
            live = yes is not None

        if yes is None:
            gamma_yes = await self._fetch_gamma_yes(resolved_ref)
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
        self._last_yes_by_market[resolved_ref] = yes
        return yes, 1 - yes, f"{source}::{resolver_source}", live

    async def _resolve_market_ref(self, market_ref: str) -> tuple[str, str]:
        """
        Resolve slug base (ex: btc-updown-15m) para o mercado ativo da janela atual.
        Estratégia:
        1) Se for ID e existir, usa direto.
        2) Busca por slug base + timestamp atual (epoch/minute/bin de 15m).
        3) Fallback para slug base original.
        """
        now = time.time()
        cached = self._resolved_market_cache.get(market_ref)
        if cached and now - cached[1] <= settings.market_resolution_ttl_seconds:
            return cached[0], "CACHE"

        direct = await self._fetch_gamma_market(market_ref)
        if direct:
            ref = str(direct.get("id") or direct.get("slug") or market_ref)
            self._resolved_market_cache[market_ref] = (ref, now)
            return ref, "DIRECT"

        query_terms = self._build_time_queries(market_ref)
        for term in query_terms:
            payload = await self._fetch_gamma_markets_query(term)
            candidate = self._pick_best_time_window_market(payload, market_ref)
            if candidate:
                ref = str(candidate.get("id") or candidate.get("slug") or market_ref)
                self._resolved_market_cache[market_ref] = (ref, now)
                return ref, "TIMESTAMP_SEARCH"

        self._resolved_market_cache[market_ref] = (market_ref, now)
        return market_ref, "RAW"

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

    async def _fetch_clob_yes(self, market_ref: str) -> float | None:
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
    def _pick_best_time_window_market(payload: object, base_ref: str) -> dict | None:
        if not isinstance(payload, list) or not payload:
            return None

        now = datetime.now(timezone.utc)
        now_ts = int(now.timestamp())
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

            # mercado ativo da janela: agora <= end <= agora+15m(+grace)
            if now_ts <= end_ts <= now_ts + 16 * 60:
                delta = abs(end_ts - (now_ts + 15 * 60))
                candidate = (delta, item)
                if best is None or candidate[0] < best[0]:
                    best = candidate

        return best[1] if best else None

    @staticmethod
    def _extract_market_end_ts(item: dict) -> int | None:
        for key in ("endDate", "endTime", "endTimestamp", "closingDate"):
            value = item.get(key)
            if value is None:
                continue
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                # iso -> ts
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
