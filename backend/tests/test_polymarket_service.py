import asyncio
from datetime import datetime, timedelta, timezone

from app.models.entities import ApiMode
from app.services.polymarket_service import PolymarketService


def test_fetch_odds_resolves_market_by_timestamp_search():
    svc = PolymarketService()

    async def fake_fetch_gamma_market(_market_ref):
        return None

    async def fake_fetch_gamma_markets_query(_term):
        end = datetime.now(timezone.utc) + timedelta(minutes=14)
        return [
            {
                "id": "resolved-market-id",
                "slug": "btc-updown-15m-some-window",
                "question": "Bitcoin Up or Down 15m",
                "endDate": end.isoformat(),
                "outcomePrices": ["0.63", "0.37"],
            }
        ]

    async def fake_fetch_clob_yes(_market_ref):
        return None

    async def fake_fetch_gamma_yes(market_ref):
        return 0.63 if market_ref == "resolved-market-id" else None

    svc._fetch_gamma_market = fake_fetch_gamma_market
    svc._fetch_gamma_markets_query = fake_fetch_gamma_markets_query
    svc._fetch_clob_yes = fake_fetch_clob_yes
    svc._fetch_gamma_yes = fake_fetch_gamma_yes

    yes, no, source, live = asyncio.run(svc.fetch_odds("btc-updown-15m", ApiMode.CLOB))

    assert yes == 0.63
    assert no == 0.37
    assert live is True
    assert "TIMESTAMP_SEARCH" in source

    asyncio.run(svc.close())


def test_pick_best_time_window_market_returns_none_for_stale_end_date():
    old_end = datetime.now(timezone.utc) - timedelta(minutes=5)
    payload = [
        {
            "id": "stale",
            "slug": "btc-updown-15m-old",
            "question": "Bitcoin Up or Down 15m",
            "endDate": old_end.isoformat(),
        }
    ]

    market = PolymarketService._pick_best_time_window_market(payload, "btc-updown-15m")
    assert market is None
