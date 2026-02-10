from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Asset(str, Enum):
    BTC = "BTC"
    ETH = "ETH"
    SOL = "SOL"


class Direction(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


class ApiMode(str, Enum):
    CLOB = "CLOB"
    GAMMA_API = "GAMMA_API"


class Indicator(str, Enum):
    MACD = "MACD"
    TREND = "TREND"
    POLY_PRICE = "POLY_PRICE"


class MarketSnapshot(BaseModel):
    asset: Asset
    spot_price: float
    change_24h: float = 0.0
    yes_odds: float = 0.5
    no_odds: float = 0.5
    odds_source: str = "UNKNOWN"
    odds_live: bool = False
    price_source: str = "UNKNOWN"
    price_age_seconds: int | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Signal(BaseModel):
    asset: Asset
    direction: Direction
    confidence: float
    reason: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Trade(BaseModel):
    id: str
    asset: Asset
    direction: Direction
    entry_price: float
    exit_price: Optional[float] = None
    confidence: float
    api_mode: ApiMode
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    closes_at: datetime
    closed_at: Optional[datetime] = None
    pnl: float = 0.0
    status: str = "OPEN"


class BotStats(BaseModel):
    balance: float = 0.0
    today_pnl: float = 0.0
    all_time_pnl: float = 0.0
    trades: int = 0
    wins: int = 0

    @property
    def win_rate(self) -> float:
        return (self.wins / self.trades) if self.trades else 0.0

    @property
    def avg_pnl(self) -> float:
        return (self.all_time_pnl / self.trades) if self.trades else 0.0


class StrategyConfig(BaseModel):
    enabled_assets: list[Asset] = Field(default_factory=lambda: [Asset.BTC, Asset.ETH, Asset.SOL])
    enabled_indicators: list[Indicator] = Field(default_factory=lambda: [Indicator.MACD, Indicator.POLY_PRICE])
    confidence_threshold: float = 0.9
    entry_threshold: float = 0.9
    entry_window_seconds: int = 180
    use_macd_confirmation: bool = True
