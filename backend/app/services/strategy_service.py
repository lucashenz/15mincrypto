from __future__ import annotations

from collections import Counter

from app.models.entities import Direction, Indicator, Signal
from app.services.indicator_service import IndicatorService


class StrategyService:
    def __init__(self, indicator_service: IndicatorService, confidence_threshold: float) -> None:
        self.indicator_service = indicator_service
        self.confidence_threshold = confidence_threshold

    def generate_signal(self, asset: str, indicators: list[Indicator], poly_bias: Direction | None) -> Signal | None:
        votes: list[Direction] = []
        reasons: list[str] = []

        if Indicator.MACD in indicators:
            macd = self.indicator_service.macd_bias(asset)
            if macd is None:
                return None
            votes.append(macd)
            reasons.append(f"MACD={macd.value}")

        if Indicator.TREND in indicators:
            trend = self.indicator_service.trend_bias(asset)
            if trend is None:
                return None
            votes.append(trend)
            reasons.append(f"TREND={trend.value}")

        if Indicator.POLY_PRICE in indicators:
            if poly_bias is None:
                return None
            votes.append(poly_bias)
            reasons.append(f"POLY={poly_bias.value}")

        if not votes:
            return None

        counts = Counter(votes)
        direction, qty = counts.most_common(1)[0]
        confidence = qty / len(votes)

        if confidence < self.confidence_threshold:
            return None

        reason = " + ".join(reasons)
        return Signal(asset=asset, direction=direction, confidence=confidence, reason=reason)
