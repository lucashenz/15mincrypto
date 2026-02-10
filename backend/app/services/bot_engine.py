from __future__ import annotations

import asyncio
from datetime import datetime

from app.core.config import settings
from app.models.entities import ApiMode, Asset, MarketSnapshot
from app.services.indicator_service import IndicatorService
from app.services.polymarket_service import PolymarketService
from app.services.price_service import PriceService
from app.services.strategy_service import StrategyService
from app.services.trade_executor import TradeExecutor


class BotEngine:
    def __init__(self) -> None:
        self.assets = [Asset.BTC, Asset.ETH, Asset.SOL]
        self.market_map = {
            Asset.BTC: settings.markets_btc,
            Asset.ETH: settings.markets_eth,
            Asset.SOL: settings.markets_sol,
        }
        self.price_service = PriceService()
        self.poly_service = PolymarketService()
        self.indicator_service = IndicatorService()
        self.strategy_service = StrategyService(self.indicator_service, settings.confidence_threshold)
        self.trade_executor = TradeExecutor()
        self.latest_snapshots: dict[str, MarketSnapshot] = {}
        self.running = False
        self._task: asyncio.Task | None = None

    def decide_api_mode(self, closes_at: datetime) -> ApiMode:
        remaining = int((closes_at - datetime.utcnow()).total_seconds())
        return ApiMode.GAMMA_API if remaining <= settings.switch_to_gamma_seconds else ApiMode.CLOB

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.running = False
        if self._task:
            await self._task

    async def _loop(self) -> None:
        while self.running:
            await self.tick()
            await asyncio.sleep(settings.poll_interval_seconds)

    async def tick(self) -> None:
        for asset in self.assets:
            spot, change = await self.price_service.fetch_spot(asset)
            self.indicator_service.push_price(asset, spot)

            api_mode = ApiMode.CLOB
            yes, no = await self.poly_service.fetch_odds(self.market_map[asset], api_mode)
            snapshot = MarketSnapshot(asset=asset, spot_price=spot, change_24h=change, yes_odds=yes, no_odds=no)
            self.latest_snapshots[asset] = snapshot

            signal = self.strategy_service.generate_signal(asset)
            if signal and not any(t.asset == asset for t in self.trade_executor.open_trades.values()):
                self.trade_executor.open_trade(snapshot, signal, api_mode, settings.trade_duration_seconds)

        for trade in self.trade_executor.open_trades.values():
            new_mode = self.decide_api_mode(trade.closes_at)
            trade.api_mode = new_mode

        self.trade_executor.settle_due_trades(self.latest_snapshots)

    async def shutdown(self) -> None:
        await self.stop()
        await self.price_service.close()
        await self.poly_service.close()


engine = BotEngine()
