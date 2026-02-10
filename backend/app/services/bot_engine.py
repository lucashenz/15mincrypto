from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.core.config import settings
from app.models.entities import (
    ApiMode,
    Asset,
    Direction,
    ExecutionConfigUpdate,
    ExecutionConfigView,
    ExecutionMode,
    MarketSnapshot,
    StrategyConfig,
)
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
        self.execution_mode = ExecutionMode.TEST
        self.wallet_secret = ""
        self.strategy_config = StrategyConfig(
            confidence_threshold=settings.confidence_threshold,
            entry_probability_threshold=settings.entry_probability_threshold,
            late_entry_seconds=settings.late_entry_seconds,
            stop_loss_pct=settings.stop_loss_pct,
        )

    def decide_api_mode(self, closes_at: datetime) -> ApiMode:
        remaining = int((closes_at - datetime.utcnow()).total_seconds())
        return ApiMode.GAMMA_API if remaining <= settings.switch_to_gamma_seconds else ApiMode.CLOB

    @property
    def wallet_configured(self) -> bool:
        return bool(self.wallet_secret.strip())

    @property
    def wallet_masked(self) -> str:
        secret = self.wallet_secret.strip()
        if not secret:
            return ""
        if len(secret) <= 10:
            return "*" * len(secret)
        return f"{secret[:6]}...{secret[-4:]}"

    def get_execution_config(self) -> ExecutionConfigView:
        return ExecutionConfigView(
            mode=self.execution_mode,
            wallet_configured=self.wallet_configured,
            wallet_masked=self.wallet_masked,
        )

    def update_execution_config(self, payload: ExecutionConfigUpdate) -> ExecutionConfigView:
        self.execution_mode = payload.mode
        self.wallet_secret = (payload.wallet_secret or "").strip()
        return self.get_execution_config()

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
        if not (0.5 <= payload.confidence_threshold <= 1.0):
            raise ValueError("confidence_threshold deve estar entre 0.5 e 1.0")
        if not (0.5 <= payload.entry_probability_threshold <= 1.0):
            raise ValueError("entry_probability_threshold deve estar entre 0.5 e 1.0")
        if not (30 <= payload.late_entry_seconds <= 900):
            raise ValueError("late_entry_seconds deve estar entre 30 e 900")
        if not (0.0 <= payload.stop_loss_pct <= 0.95):
            raise ValueError("stop_loss_pct deve estar entre 0 e 0.95")

        self.strategy_config = payload
        self.strategy_service.confidence_threshold = payload.confidence_threshold
        return self.strategy_config

    async def _loop(self) -> None:
        while self.running:
            await self.tick()
            await asyncio.sleep(settings.poll_interval_seconds)

    @staticmethod
    def _to_naive_utc(end_ts: int | None) -> datetime | None:
        if end_ts is None:
            return None
        return datetime.fromtimestamp(end_ts, tz=timezone.utc).replace(tzinfo=None)

    async def tick(self) -> None:
        assets = list(self.strategy_config.enabled_assets)
        price_by_asset = await self.price_service.fetch_spots(assets)

        for asset in assets:
            try:
                spot, change = price_by_asset.get(asset, (0.0, 0.0))
                self.indicator_service.warmup(asset, spot)
                self.indicator_service.push_price(asset, spot)

                market_data = await self.poly_service.fetch_market_data(self.market_map[asset])
                market_close = self._to_naive_utc(market_data.end_ts) or datetime.utcnow()
                remaining_seconds = max(0, int((market_close - datetime.utcnow()).total_seconds()))
                api_mode = self.decide_api_mode(market_close)

                snapshot = MarketSnapshot(
                    asset=asset,
                    spot_price=spot,
                    change_24h=change,
                    yes_odds=market_data.yes_odds,
                    no_odds=market_data.no_odds,
                    odds_source=f"{market_data.odds_source}::{market_data.resolver_source}",
                    odds_live=market_data.odds_live,
                    price_source=self.price_service.last_source_by_asset.get(asset, "UNKNOWN"),
                    price_age_seconds=self.price_service.last_price_age_seconds(asset),
                    market_id=market_data.market_id,
                    market_slug=market_data.market_slug,
                    market_end_ts=market_data.end_ts,
                    price_to_beat=market_data.price_to_beat,
                    final_price=market_data.final_price,
                )
                self.latest_snapshots[asset] = snapshot

                poly_bias = Direction.UP if snapshot.yes_odds >= snapshot.no_odds else Direction.DOWN
                signal, decision = self.strategy_service.generate_signal(
                    asset,
                    self.strategy_config.enabled_indicators,
                    poly_bias,
                )
                self.last_decision_by_asset[asset] = decision

                market_probability = snapshot.yes_odds if signal and signal.direction == Direction.UP else snapshot.no_odds
                late_window_ready = remaining_seconds <= self.strategy_config.late_entry_seconds
                probability_ready = signal is not None and market_probability >= self.strategy_config.entry_probability_threshold
                has_open_trade = any(t.asset == asset for t in self.trade_executor.open_trades.values())

                if self.execution_mode == ExecutionMode.REAL and not self.wallet_configured:
                    self.last_decision_by_asset[asset] = "REAL_MODE_NEEDS_WALLET"
                    continue

                if signal and not has_open_trade and late_window_ready and probability_ready:
                    trade = self.trade_executor.open_trade(
                        snapshot,
                        signal,
                        api_mode,
                        closes_at=market_close,
                        stop_loss_pct=self.strategy_config.stop_loss_pct,
                    )
                    if self.execution_mode == ExecutionMode.REAL:
                        ok, msg = await self.poly_service.place_clob_order(
                            market_data,
                            signal.direction,
                            amount_usd=20.0,
                            wallet_secret=self.wallet_secret,
                        )
                        self.last_decision_by_asset[asset] = f"ORDER::{msg}::{trade.id}"
                        if not ok:
                            trade.status = "ORDER_REJECTED"
                    else:
                        self.last_decision_by_asset[asset] = f"PAPER_ORDER::{trade.id}"
                elif signal and not has_open_trade:
                    self.last_decision_by_asset[asset] = (
                        f"WAIT_WINDOW_OR_PROB(rem={remaining_seconds}s prob={market_probability:.2f})::{decision}"
                    )
            except Exception as exc:  # noqa: BLE001
                self.last_decision_by_asset[asset] = f"ERROR::{exc.__class__.__name__}"

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
