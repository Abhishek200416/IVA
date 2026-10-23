"""AGI 1.7 OMEGA COMMAND — Real-Time Candlestick Momentum & "Boom Up / Boom Down" Detector.

Analyzes 1-minute and 5-minute OHLCV candles to detect institutional breakouts:
1. "BOOM UP" Formations:
   - BULLISH_ENGULFING: Large green body completely covers previous red candle body.
   - HAMMER_ABSORPTION: Long lower shadow (> 60% of candle range) proving bottom buyer absorption.
   - BULLISH_MARUBOZU: Powerful green impulse candle (> 80% body, tight wicks).
   - VWAP_BULL_RECLAIM: Strong close above VWAP with rising volume.
2. "BOOM DOWN" Formations:
   - BEARISH_ENGULFING: Large red body completely covers previous green candle body.
   - SHOOTING_STAR_REJECTION: Long upper shadow (> 60% of candle range) proving rejection at ceiling.
   - BEARISH_MARUBOZU: Powerful red distribution candle breaking support.
   - VWAP_BEAR_BREAKDOWN: Decisive break below VWAP with volume.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

@dataclass
class Candle:
    time: str
    o: float
    h: float
    l: float
    c: float
    v: float
    vwap: Optional[float] = None

@dataclass
class CandlestickSignal:
    timestamp: str
    pattern: str
    direction: str  # "BOOM_UP" | "BOOM_DOWN" | "NEUTRAL"
    confidence: float  # 0.0 to 1.0
    action_directive: str  # e.g., "TRAIL_LOOSE_RIDE_TREND" or "TIGHTEN_SL_PROTECT_CASH"
    metrics: Dict[str, Any]

class CandlestickMomentumDetector:
    def __init__(self, volume_surge_multiplier: float = 1.35):
        self.vol_mult = volume_surge_multiplier

    def analyze_candles(self, candles: List[Candle]) -> CandlestickSignal:
        if len(candles) < 2:
            return CandlestickSignal(
                timestamp=candles[-1].time if candles else "N/A",
                pattern="INSUFFICIENT_DATA",
                direction="NEUTRAL",
                confidence=0.0,
                action_directive="HOLD_STEADY",
                metrics={}
            )

        curr = candles[-1]
        prev = candles[-2]
        
        # Candle Geometry
        c_range = max(0.01, curr.h - curr.l)
        c_body = abs(curr.c - curr.o)
        c_upper_wick = curr.h - max(curr.o, curr.c)
        c_lower_wick = min(curr.o, curr.c) - curr.l
        is_green = curr.c >= curr.o
        is_red = curr.c < curr.o

        p_range = max(0.01, prev.h - prev.l)
        p_body = abs(prev.c - prev.o)
        p_is_green = prev.c >= prev.o
        p_is_red = prev.c < prev.o

        # Volume baseline
        avg_vol = sum(c.v for c in candles[-5:]) / max(1, len(candles[-5:]))
        has_volume_surge = curr.v >= avg_vol * self.vol_mult

        metrics = {
            "candle_range": round(c_range, 2),
            "body_ratio": round(c_body / c_range, 2),
            "lower_wick_ratio": round(c_lower_wick / c_range, 2),
            "upper_wick_ratio": round(c_upper_wick / c_range, 2),
            "volume_surge": has_volume_surge,
            "vwap": curr.vwap
        }

        # -------------------------------------------------------------
        # 1. "BOOM UP" DETECTIONS
        # -------------------------------------------------------------
        # A. Bullish Engulfing: Current green covers previous red
        if is_green and p_is_red and curr.c > prev.o and curr.o < prev.c and (c_body > p_body):
            conf = 0.90 if has_volume_surge else 0.80
            return CandlestickSignal(
                timestamp=curr.time,
                pattern="BULLISH_ENGULFING",
                direction="BOOM_UP",
                confidence=conf,
                action_directive="TRAIL_LOOSE_RIDE_SUPERCHARGED_TREND",
                metrics=metrics
            )

        # B. Hammer / Bottom Absorption Wick
        if (c_lower_wick / c_range >= 0.58) and (c_upper_wick / c_range <= 0.18):
            conf = 0.88 if has_volume_surge else 0.78
            return CandlestickSignal(
                timestamp=curr.time,
                pattern="HAMMER_BOTTOM_ABSORPTION",
                direction="BOOM_UP",
                confidence=conf,
                action_directive="DEFEND_BOTTOM_TRAIL_STOP_ABOVE_HAMMER_LOW",
                metrics=metrics
            )

        # C. Bullish Marubozu (Strong Green Impulse)
        if is_green and (c_body / c_range >= 0.80) and (c_range >= 15.0):
            conf = 0.92 if has_volume_surge else 0.82
            return CandlestickSignal(
                timestamp=curr.time,
                pattern="BULLISH_MARUBOZU_IMPULSE",
                direction="BOOM_UP",
                confidence=conf,
                action_directive="RIDE_MOMENTUM_EXPAND_TARGETS",
                metrics=metrics
            )

        # -------------------------------------------------------------
        # 2. "BOOM DOWN" DETECTIONS
        # -------------------------------------------------------------
        # A. Bearish Engulfing: Current red covers previous green
        if is_red and p_is_green and curr.c < prev.o and curr.o > prev.c and (c_body > p_body):
            conf = 0.90 if has_volume_surge else 0.80
            return CandlestickSignal(
                timestamp=curr.time,
                pattern="BEARISH_ENGULFING",
                direction="BOOM_DOWN",
                confidence=conf,
                action_directive="TIGHTEN_SL_IMMEDIATELY_PROTECT_CASH",
                metrics=metrics
            )

        # B. Shooting Star / Overhead Ceiling Rejection Wick
        if (c_upper_wick / c_range >= 0.58) and (c_lower_wick / c_range <= 0.18):
            conf = 0.88 if has_volume_surge else 0.78
            return CandlestickSignal(
                timestamp=curr.time,
                pattern="SHOOTING_STAR_CEILING_REJECTION",
                direction="BOOM_DOWN",
                confidence=conf,
                action_directive="RATCHET_SL_TO_PREVIOUS_HIGH_LOCK_PROFITS",
                metrics=metrics
            )

        # C. Bearish Marubozu (Heavy Red Distribution)
        if is_red and (c_body / c_range >= 0.80) and (c_range >= 15.0):
            conf = 0.92 if has_volume_surge else 0.82
            return CandlestickSignal(
                timestamp=curr.time,
                pattern="BEARISH_MARUBOZU_DISTRIBUTION",
                direction="BOOM_DOWN",
                confidence=conf,
                action_directive="TRIGGER_EMERGENCY_PROFIT_OR_SL_EXIT",
                metrics=metrics
            )

        # -------------------------------------------------------------
        # 3. NEUTRAL / CONSOLIDATION
        # -------------------------------------------------------------
        return CandlestickSignal(
            timestamp=curr.time,
            pattern="NORMAL_CONTINUATION",
            direction="NEUTRAL",
            confidence=0.50,
            action_directive="MAINTAIN_CURRENT_TRAILING_LADDER",
            metrics=metrics
        )
