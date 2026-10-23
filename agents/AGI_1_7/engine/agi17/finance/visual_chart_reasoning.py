"""Visual Chart Perception, Technical Structure & Projection Layer for AGI 1.7 OMEGA COMMAND.

Implements Phase 6 Objective 4:
- Identifies swing highs/lows, support & resistance clusters, trendlines, and price gaps.
- Volatility expansion/contraction and Volume/VWAP relationship tracking.
- Strict 5-layer visual separation:
  1. Observed Historical Levels (Blue/Solid)
  2. Current Calculated Indicators (Green/Dashed)
  3. Forecast Paths (Cyan/Dotted Arrow)
  4. Scenario-Dependent Target Zones (Amber/Shaded)
  5. Invalidation Points (Red/Crosshair)
- Enforces strict no-future-leakage invariant during historical analysis.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime
from enum import Enum
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class VisualAnnotationType(str, Enum):
    OBSERVED_HISTORICAL_LEVEL = "OBSERVED_HISTORICAL_LEVEL"
    CURRENT_CALCULATED_INDICATOR = "CURRENT_CALCULATED_INDICATOR"
    FORECAST_PATH = "FORECAST_PATH"
    SCENARIO_TARGET_ZONE = "SCENARIO_TARGET_ZONE"
    INVALIDATION_POINT = "INVALIDATION_POINT"


@dataclass
class VisualChartAnnotation:
    """Formal chart visual element with distinct projection vs observation semantics."""
    annotation_id: str
    layer_type: VisualAnnotationType
    instrument: str
    timeframe: str
    label: str  # Must explicitly prefix [OBSERVED], [CALCULATED], or [PROJECTION]
    start_timestamp: str
    end_timestamp: Optional[str]
    start_price: float
    end_price: Optional[float]
    color_hex: str
    line_style: str  # solid, dashed, dotted
    invalidation_condition: Optional[str] = None
    forecast_horizon: Optional[str] = None
    calibrated_probability: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["layer_type"] = self.layer_type.value
        return d


@dataclass
class VisualChartSnapshot:
    """Complete visual interpretation of an instrument's displayed chart."""
    snapshot_id: str
    instrument: str
    timeframe: str
    visible_interval: str
    chart_scale: str
    observation_timestamp: str
    current_price: float
    swing_highs: List[Dict[str, Any]]
    swing_lows: List[Dict[str, Any]]
    support_resistance_zones: List[Dict[str, Any]]
    trendlines: List[Dict[str, Any]]
    breakout_levels: List[Dict[str, Any]]
    price_gaps: List[Dict[str, Any]]
    volatility_regime: str  # EXPANSION, CONTRACTION, NORMAL
    volume_vwap_relationship: str
    annotations: List[VisualChartAnnotation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["annotations"] = [a.to_dict() for a in self.annotations]
        return d


class VisualChartReasoningEngine:
    """Alexa and Max's visual chart reasoning engine."""

    @classmethod
    def analyze_chart(
        cls,
        instrument: str,
        timeframe: str,
        candles: List[Dict[str, Any]],  # List of {timestamp, open, high, low, close, volume}
        observation_timestamp: Optional[str] = None,
    ) -> VisualChartSnapshot:
        """Analyzes price action structure and generates verifiable multi-layer annotations."""
        if not candles:
            raise ValueError("CANNOT_ANALYZE_EMPTY_CANDLES: At least 5 candles required for chart analysis.")

        now_str = observation_timestamp or datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ).strftime("%Y-%m-%d %H:%M:%S IST")

        current_price = candles[-1]["close"]
        visible_interval = f"{candles[0]['timestamp']} -> {candles[-1]['timestamp']}"

        # 1. Swing Highs and Swing Lows (3-candle fractal pattern)
        swing_highs = []
        swing_lows = []
        for i in range(1, len(candles) - 1):
            c_prev = candles[i - 1]
            c_curr = candles[i]
            c_next = candles[i + 1]

            if c_curr["high"] > c_prev["high"] and c_curr["high"] > c_next["high"]:
                swing_highs.append({
                    "timestamp": c_curr["timestamp"],
                    "price": round(c_curr["high"], 2),
                    "type": "SWING_HIGH",
                })
            if c_curr["low"] < c_prev["low"] and c_curr["low"] < c_next["low"]:
                swing_lows.append({
                    "timestamp": c_curr["low"],
                    "price": round(c_curr["low"], 2),
                    "type": "SWING_LOW",
                })

        # 2. Support and Resistance Clustering
        all_extrema = [s["price"] for s in swing_highs + swing_lows]
        sr_zones = []
        if all_extrema:
            # Cluster around nearest round levels
            resistance = max([s["price"] for s in swing_highs]) if swing_highs else current_price * 1.005
            support = min([s["price"] for s in swing_lows]) if swing_lows else current_price * 0.995
            sr_zones.append({
                "type": "RESISTANCE",
                "price": round(resistance, 2),
                "strength": "CONFIRMED" if len(swing_highs) >= 2 else "PROVISIONAL",
            })
            sr_zones.append({
                "type": "SUPPORT",
                "price": round(support, 2),
                "strength": "CONFIRMED" if len(swing_lows) >= 2 else "PROVISIONAL",
            })
        else:
            resistance = round(current_price * 1.005, 2)
            support = round(current_price * 0.995, 2)
            sr_zones.append({"type": "RESISTANCE", "price": resistance, "strength": "ESTIMATED"})
            sr_zones.append({"type": "SUPPORT", "price": support, "strength": "ESTIMATED"})

        # 3. Trendline Hypotheses
        trendlines = []
        if len(swing_lows) >= 2:
            p1 = swing_lows[0]["price"]
            p2 = swing_lows[-1]["price"]
            slope = (p2 - p1) / max(1, len(candles))
            trendlines.append({
                "type": "SUPPORT_TRENDLINE",
                "status": "CONFIRMED" if len(swing_lows) >= 3 else "PROVISIONAL",
                "slope": round(slope, 4),
                "start_price": p1,
                "end_price": p2,
            })

        # 4. Volatility Expansion / Contraction Check
        ranges = [c["high"] - c["low"] for c in candles[-10:]]
        avg_range = sum(ranges) / len(ranges) if ranges else 1.0
        latest_range = candles[-1]["high"] - candles[-1]["low"]
        if latest_range > avg_range * 1.5:
            vol_regime = "EXPANSION"
        elif latest_range < avg_range * 0.6:
            vol_regime = "CONTRACTION"
        else:
            vol_regime = "NORMAL"

        # 5. Volume / VWAP Check
        vol_sum = sum(c.get("volume", 100) for c in candles)
        vp_sum = sum(c["close"] * c.get("volume", 100) for c in candles)
        vwap = vp_sum / max(1, vol_sum)
        rel_pos = "ABOVE_VWAP" if current_price >= vwap else "BELOW_VWAP"
        vwap_rel = f"{rel_pos} (VWAP={vwap:.1f}, Spread={current_price - vwap:+.1f} pts)"

        # 6. Price Gaps (between candle 0 open and previous reference if available)
        gaps = []
        if len(candles) >= 2:
            prev_close = candles[-2]["close"]
            curr_open = candles[-1]["open"]
            gap_size = curr_open - prev_close
            if abs(gap_size) > current_price * 0.002:  # > 0.2% gap
                gaps.append({
                    "timestamp": candles[-1]["timestamp"],
                    "gap_size_pts": round(gap_size, 2),
                    "type": "UPWARD_GAP" if gap_size > 0 else "DOWNWARD_GAP",
                })

        # 7. Construct Visual Annotations
        annotations: List[VisualChartAnnotation] = []

        # Layer 1: Observed Historical S/R
        for sr in sr_zones:
            annotations.append(VisualChartAnnotation(
                annotation_id=f"ANN-OBS-{sr['type']}-{int(candles[-1].get('high', 0))}",
                layer_type=VisualAnnotationType.OBSERVED_HISTORICAL_LEVEL,
                instrument=instrument,
                timeframe=timeframe,
                label=f"[OBSERVED] {sr['type']}: ₹{sr['price']:.1f} ({sr['strength']})",
                start_timestamp=candles[0]["timestamp"],
                end_timestamp=candles[-1]["timestamp"],
                start_price=sr["price"],
                end_price=sr["price"],
                color_hex="#2962FF",  # Solid Blue
                line_style="solid",
            ))

        # Layer 2: Current Calculated Indicator (VWAP)
        annotations.append(VisualChartAnnotation(
            annotation_id="ANN-CALC-VWAP",
            layer_type=VisualAnnotationType.CURRENT_CALCULATED_INDICATOR,
            instrument=instrument,
            timeframe=timeframe,
            label=f"[CALCULATED] Session VWAP: ₹{vwap:.1f}",
            start_timestamp=candles[0]["timestamp"],
            end_timestamp=candles[-1]["timestamp"],
            start_price=round(vwap, 2),
            end_price=round(vwap, 2),
            color_hex="#00E676",  # Dashed Green
            line_style="dashed",
        ))

        snapshot = VisualChartSnapshot(
            snapshot_id=f"SNAP-{instrument}-{timeframe}-{int(candles[-1].get('close', 0))}",
            instrument=instrument,
            timeframe=timeframe,
            visible_interval=visible_interval,
            chart_scale=f"Linear, Range={min(c['low'] for c in candles):.1f}-{max(c['high'] for c in candles):.1f}",
            observation_timestamp=now_str,
            current_price=round(current_price, 2),
            swing_highs=swing_highs,
            swing_lows=swing_lows,
            support_resistance_zones=sr_zones,
            trendlines=trendlines,
            breakout_levels=[{"level": round(resistance, 2), "direction": "UPWARD"}],
            price_gaps=gaps,
            volatility_regime=vol_regime,
            volume_vwap_relationship=vwap_rel,
            annotations=annotations,
        )
        return snapshot

    @classmethod
    def attach_scenario_projection(
        cls,
        snapshot: VisualChartSnapshot,
        scenario_name: str,
        target_price: float,
        invalidation_price: float,
        horizon: str,
        calibrated_probability: float,
    ) -> Tuple[VisualChartAnnotation, VisualChartAnnotation]:
        """Attaches Layer 3 (Forecast Path) and Layer 5 (Invalidation Point) to a snapshot.

        Enforces visual distinction:
        - Must include [PROJECTION] prefix.
        - Must include calibrated probability.
        - Must include explicit invalidation criteria.
        """
        # Layer 3 / 4: Target Path
        target_ann = VisualChartAnnotation(
            annotation_id=f"ANN-PROJ-{scenario_name.upper()}",
            layer_type=VisualAnnotationType.SCENARIO_TARGET_ZONE,
            instrument=snapshot.instrument,
            timeframe=snapshot.timeframe,
            label=f"[PROJECTION] {scenario_name} (P={calibrated_probability:.0%}, Target: ₹{target_price:.1f})",
            start_timestamp=snapshot.observation_timestamp,
            end_timestamp=f"{snapshot.observation_timestamp} + {horizon}",
            start_price=snapshot.current_price,
            end_price=round(target_price, 2),
            color_hex="#00B0FF",  # Cyan
            line_style="dotted",
            forecast_horizon=horizon,
            calibrated_probability=calibrated_probability,
            invalidation_condition=f"Price breaches invalidation level ₹{invalidation_price:.1f}",
        )

        # Layer 5: Invalidation Point
        inval_ann = VisualChartAnnotation(
            annotation_id=f"ANN-INVAL-{scenario_name.upper()}",
            layer_type=VisualAnnotationType.INVALIDATION_POINT,
            instrument=snapshot.instrument,
            timeframe=snapshot.timeframe,
            label=f"[PROJECTION INVALIDATION] Stop Level: ₹{invalidation_price:.1f}",
            start_timestamp=snapshot.observation_timestamp,
            end_timestamp=f"{snapshot.observation_timestamp} + {horizon}",
            start_price=round(invalidation_price, 2),
            end_price=round(invalidation_price, 2),
            color_hex="#FF1744",  # Red
            line_style="dashed",
            invalidation_condition="Immediate thesis abort on touch",
        )

        snapshot.annotations.append(target_ann)
        snapshot.annotations.append(inval_ann)
        return target_ann, inval_ann

    @classmethod
    def verify_no_future_leakage(
        cls,
        historical_cutoff_timestamp: str,
        snapshot: VisualChartSnapshot,
    ) -> bool:
        """Verifies that no annotation, visible interval, or detected swing references data after historical cutoff."""
        for ann in snapshot.annotations:
            # Observed levels must not start or extend after cutoff
            if ann.layer_type in (
                VisualAnnotationType.OBSERVED_HISTORICAL_LEVEL,
                VisualAnnotationType.CURRENT_CALCULATED_INDICATOR,
            ):
                if ann.start_timestamp > historical_cutoff_timestamp:
                    return False
                if ann.end_timestamp and ann.end_timestamp > historical_cutoff_timestamp:
                    return False
        for sh in snapshot.swing_highs:
            if sh["timestamp"] > historical_cutoff_timestamp:
                return False
        for sl in snapshot.swing_lows:
            if sl["timestamp"] > historical_cutoff_timestamp:
                return False
        if " -> " in snapshot.visible_interval:
            interval_end = snapshot.visible_interval.split(" -> ")[1].strip()
            if interval_end > historical_cutoff_timestamp:
                return False
        return True
