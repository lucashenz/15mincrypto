from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.models.entities import (
    ApiMode,
    Asset,
    Direction,
    ExecutionConfigUpdate,
    ExecutionConfigView,
    ExecutionMode,
    MarketSnapshot,
    Signal,
    StrategyConfig,
)
from app.services.indicator_service import IndicatorService
from app.services.polymarket_service import PolymarketService
from app.services.price_service import PriceService
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
        self._asset_locks = {asset: asyncio.Lock() for asset in Asset}
        self._action_log_path = Path("backend/data/window_actions.log")
        self._action_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._handled_actions: set[str] = self._load_handled_actions()

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
        return ExecutionConfigView(mode=self.execution_mode, wallet_configured=self.wallet_configured, wallet_masked=self.wallet_masked)

    def update_execution_config(self, payload: ExecutionConfigUpdate) -> ExecutionConfigView:
        self.execution_mode = payload.mode
        self.wallet_secret = (payload.wallet_secret or "").strip()
        return self.get_execution_config()

    def _load_handled_actions(self) -> set[str]:
        if not self._action_log_path.exists():
            return set()
        entries: set[str] = set()
        for line in self._action_log_path.read_text().splitlines():
            parts = line.strip().split("|")
            if len(parts) >= 3:
                entries.add(f"{parts[1]}:{parts[2]}:{parts[0]}")
        return entries

    def _append_action(self, action: str, asset: Asset, window_ts: int, source: str) -> None:
        self._action_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._action_log_path.open("a", encoding="utf-8") as f:
            f.write(f"{action}|{asset.value}|{window_ts}|{source}|{datetime.utcnow().isoformat()}\n")
        self._handled_actions.add(f"{asset.value}:{window_ts}:{action}")

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
        if not (0.5 <= payload.entry_probability_threshold <= 1.0):
            raise ValueError("entry_probability_threshold deve estar entre 0.5 e 1.0")
        if not (30 <= payload.late_entry_seconds <= 900):
            raise ValueError("late_entry_seconds deve estar entre 30 e 900")
        if not (0.0 <= payload.stop_loss_pct <= 0.95):
            raise ValueError("stop_loss_pct deve estar entre 0 e 0.95")
        self.strategy_config = payload
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

    @staticmethod
    def _dominant_direction(up_odds: float, down_odds: float) -> tuple[Direction | None, float]:
        if up_odds > down_odds:
            return Direction.UP, up_odds
        if down_odds > up_odds:
            return Direction.DOWN, down_odds
        return None, up_odds

    async def _process_asset(self, asset: Asset, spot: float, change: float) -> None:
        async with self._asset_locks[asset]:
            market_data = await self.poly_service.fetch_market_data(asset.value)
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
                window_ts=market_data.window_ts,
                market_end_ts=market_data.end_ts,
                price_to_beat=market_data.price_to_beat,
                final_price=market_data.final_price,
            )
            self.latest_snapshots[asset] = snapshot

            dominant_direction, dominant_probability = self._dominant_direction(snapshot.yes_odds, snapshot.no_odds)
            late_window_ready = remaining_seconds <= self.strategy_config.late_entry_seconds
            probability_ready = dominant_probability >= self.strategy_config.entry_probability_threshold
            has_open_trade = any(t.asset == asset for t in self.trade_executor.open_trades.values())
            action_key = f"{asset.value}:{market_data.window_ts}:ENTRY"

            if self.execution_mode == ExecutionMode.REAL and not self.wallet_configured:
                self.last_decision_by_asset[asset] = "REAL_MODE_NEEDS_WALLET"
                return

            if dominant_direction is None:
                self.last_decision_by_asset[asset] = f"TIE_UP_DOWN(UP={snapshot.yes_odds:.2f} DOWN={snapshot.no_odds:.2f})"
                return

            if action_key in self._handled_actions:
                self.last_decision_by_asset[asset] = f"SKIP_DUPLICATE_WINDOW::{market_data.window_ts}"
                return

            if not has_open_trade and late_window_ready and probability_ready:
                signal = Signal(asset=asset, direction=dominant_direction, confidence=dominant_probability, reason=f"WINDOW_{market_data.window_ts}")
                trade = self.trade_executor.open_trade(snapshot, signal, api_mode, closes_at=market_close, stop_loss_pct=self.strategy_config.stop_loss_pct)
                if self.execution_mode == ExecutionMode.REAL:
                    ok, msg = await self.poly_service.place_clob_order(market_data, signal.direction, amount_usd=20.0, wallet_secret=self.wallet_secret)
                    self.last_decision_by_asset[asset] = f"ORDER::{msg}::{trade.id}"
                    if not ok:
                        trade.status = "ORDER_REJECTED"
                else:
                    self.last_decision_by_asset[asset] = f"PAPER_ORDER::{signal.direction.value}::{trade.id}"
                self._append_action("ENTRY", asset, market_data.window_ts, snapshot.odds_source)
            elif has_open_trade:
                self.last_decision_by_asset[asset] = "WAIT_OPEN_TRADE_TO_CLOSE"
            else:
                self.last_decision_by_asset[asset] = (
                    f"WAIT_WINDOW_OR_PROB(window={market_data.window_ts} rem={remaining_seconds}s max_prob={dominant_probability:.2f} dir={dominant_direction.value})"
                )

    async def tick(self) -> None:
        assets = list(self.strategy_config.enabled_assets)
        price_by_asset = await self.price_service.fetch_spots(assets)

        for asset in assets:
            try:
                spot, change = price_by_asset.get(asset, (0.0, 0.0))
                self.indicator_service.warmup(asset, spot)
                self.indicator_service.push_price(asset, spot)
                await self._process_asset(asset, spot, change)
            except Exception as exc:  # noqa: BLE001
                self.last_decision_by_asset[asset] = f"ERROR::{exc.__class__.__name__}"

        result_overrides: dict[str, tuple[float | None, float | None, str]] = {}
        now = datetime.utcnow()
        for trade in self.trade_executor.open_trades.values():
            trade.api_mode = self.decide_api_mode(trade.closes_at)
            if now >= trade.closes_at:
                final_price, price_to_beat, source = await self.poly_service.fetch_market_result(trade.market_id, self.market_map[trade.asset])
                result_overrides[trade.id] = (final_price, price_to_beat, source)

        self.trade_executor.settle_due_trades(self.latest_snapshots, result_overrides)
        self.last_tick_at = datetime.utcnow()
        self.tick_count += 1

    async def shutdown(self) -> None:
        await self.stop()
        await self.price_service.close()
        await self.poly_service.close()


engine = BotEngine()
