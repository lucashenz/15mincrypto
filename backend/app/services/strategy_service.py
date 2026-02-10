from __future__ import annotations

from app.models.entities import Direction, Signal
from app.services.indicator_service import IndicatorService


class StrategyService:
    def __init__(self, indicator_service: IndicatorService, confidence_threshold: float) -> None:
        self.indicator_service = indicator_service
        self.confidence_threshold = confidence_threshold

    def generate_signal(self, asset: str) -> Signal | None:
        macd = self.indicator_service.macd_bias(asset)
        trend = self.indicator_service.trend_bias(asset)
        if macd is None or trend is None:
            return None

        confidence = 0.9 if macd == trend else 0.7
        if confidence < self.confidence_threshold:
            return None

        reason = f"MACD={macd.value} + TREND={trend.value}"
        return Signal(asset=asset, direction=Direction(macd), confidence=confidence, reason=reason)
