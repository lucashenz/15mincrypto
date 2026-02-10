from __future__ import annotations

import asyncio
from datetime import datetime

from app.core.config import settings
from app.models.entities import ApiMode, Asset, Direction, MarketSnapshot, StrategyConfig
from app.services.indicator_service import IndicatorService
from app.services.polymarket_service import PolymarketService
from app.services.price_service import PriceService
from app.services.strategy_service import StrategyService
from app.services.trade_executor import TradeExecutor


class BotEngine:
    def __init__(self) -> None:
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
        self.last_decision_by_asset: dict[str, str] = {}
        self.last_tick_at: datetime | None = None
        self.tick_count = 0
        self.running = False
        self._task: asyncio.Task | None = None
        self.strategy_config = StrategyConfig(confidence_threshold=settings.confidence_threshold)

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

    def update_strategy_config(self, payload: StrategyConfig) -> StrategyConfig:
        if not payload.enabled_assets:
            raise ValueError("enabled_assets não pode ser vazio")
        if not payload.enabled_indicators:
            raise ValueError("enabled_indicators não pode ser vazio")
        self.strategy_config = payload
        self.strategy_service.confidence_threshold = payload.confidence_threshold
        return self.strategy_config

    async def _loop(self) -> None:
        while self.running:
            await self.tick()
            await asyncio.sleep(settings.poll_interval_seconds)

    async def tick(self) -> None:
        for asset in self.strategy_config.enabled_assets:
            spot, change = await self.price_service.fetch_spot(asset)
            self.indicator_service.warmup(asset, spot)
            self.indicator_service.push_price(asset, spot)

            api_mode = ApiMode.CLOB
            yes, no, odds_source, odds_live = await self.poly_service.fetch_odds(self.market_map[asset], api_mode)
            snapshot = MarketSnapshot(
                asset=asset,
                spot_price=spot,
                change_24h=change,
                yes_odds=yes,
                no_odds=no,
                odds_source=odds_source,
                odds_live=odds_live,
            )
            self.latest_snapshots[asset] = snapshot

            poly_bias = Direction.UP if yes >= no else Direction.DOWN
            signal, decision = self.strategy_service.generate_signal(
                asset,
                self.strategy_config.enabled_indicators,
                poly_bias,
            )
            self.last_decision_by_asset[asset] = decision

            if signal and not any(t.asset == asset for t in self.trade_executor.open_trades.values()):
                self.trade_executor.open_trade(snapshot, signal, api_mode, settings.trade_duration_seconds)

        for trade in self.trade_executor.open_trades.values():
            trade.api_mode = self.decide_api_mode(trade.closes_at)

        self.trade_executor.settle_due_trades(self.latest_snapshots)
        self.last_tick_at = datetime.utcnow()
        self.tick_count += 1

    async def shutdown(self) -> None:
        await self.stop()
        await self.price_service.close()
        await self.poly_service.close()


engine = BotEngine()
