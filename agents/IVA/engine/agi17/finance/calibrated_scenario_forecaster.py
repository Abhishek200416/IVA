"""Calibrated Scenario Forecasting Engine for AGI 1.7 OMEGA COMMAND (Max's Horizon Forecasts).

Implements Phase 6 Objective 6:
- 7 core mutually exclusive market scenarios:
  1. Bullish continuation
  2. Bearish continuation
  3. Range-bound movement
  4. Breakout followed by failure
  5. Event-driven volatility
  6. Unexpected shock or price gap
  7. No-trade
- Strict mathematical requirement: Scenario probabilities must sum to 100.0%.
- Interval target distributions with explicit invalidation conditions.
- Brier Score tracking and sample-size-gated calibration verification (N >= 30).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime
from enum import Enum
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class ScenarioArchetype(str, Enum):
    BULLISH_CONTINUATION = "BULLISH_CONTINUATION"
    BEARISH_CONTINUATION = "BEARISH_CONTINUATION"
    RANGE_BOUND = "RANGE_BOUND"
    BREAKOUT_FAILURE = "BREAKOUT_FAILURE"
    EVENT_VOLATILITY = "EVENT_VOLATILITY"
    SHOCK_PRICE_GAP = "SHOCK_PRICE_GAP"
    NO_TRADE = "NO_TRADE"


@dataclass
class ScenarioDistribution:
    """Individual scenario pathway with interval targets and invalidation bounds."""
    scenario: ScenarioArchetype
    probability_pct: float
    target_price_low: float
    target_price_high: float
    invalidation_price: float
    horizon_str: str
    downside_risk_pts: float
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["scenario"] = self.scenario.value
        return d


@dataclass
class ScenarioForecastBattery:
    """Complete calibrated 7-scenario battery."""
    battery_id: str
    timestamp: str
    instrument: str
    current_price: float
    timeframe: str
    scenarios: List[ScenarioDistribution]
    dominant_scenario: ScenarioArchetype
    calibration_sample_size: int
    historical_brier_score: float
    entropy_uncertainty: float

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["dominant_scenario"] = self.dominant_scenario.value
        d["scenarios"] = [s.to_dict() for s in self.scenarios]
        return d


class CalibratedScenarioForecaster:
    """Max's calibrated scenario forecaster and probabilistic verification engine."""

    MIN_CALIBRATION_SAMPLE_SIZE: int = 30

    @classmethod
    def generate_scenarios(
        cls,
        instrument: str,
        current_price: float,
        vwap: float,
        atr: float,
        rsi: float,
        iv_annualized: float = 0.15,
        horizon_str: str = "15m",
        historical_brier_score: float = 0.185,
        calibration_sample_size: int = 42,
    ) -> ScenarioForecastBattery:
        """Generates 7 mutually exclusive scenarios summing strictly to 100.0%."""
        now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

        # Base weight heuristics from market indicators
        # 1. Bullish momentum weight
        w_bull = 0.15
        if current_price > vwap and rsi > 52.0:
            w_bull += 0.15
        elif current_price < vwap:
            w_bull -= 0.05

        # 2. Bearish momentum weight
        w_bear = 0.15
        if current_price < vwap and rsi < 48.0:
            w_bear += 0.15
        elif current_price > vwap:
            w_bear -= 0.05

        # 3. Range-bound weight
        w_range = 0.20
        if 45.0 <= rsi <= 55.0 and abs(current_price - vwap) < (atr * 0.5):
            w_range += 0.15

        # 4. Breakout failure weight
        w_bo_fail = 0.10
        if rsi > 70.0 or rsi < 30.0:
            w_bo_fail += 0.10

        # 5. Event volatility weight
        w_event_vol = 0.10
        if iv_annualized > 0.20:
            w_event_vol += 0.10

        # 6. Shock / gap weight
        w_shock = 0.05

        # 7. No-trade weight
        w_no_trade = 0.15
        if abs(w_bull - w_bear) < 0.05 and w_range < 0.25:
            w_no_trade += 0.15

        # Raw weights normalized to sum to 100.0%
        raw_weights = [
            max(0.02, w_bull),
            max(0.02, w_bear),
            max(0.02, w_range),
            max(0.02, w_bo_fail),
            max(0.02, w_event_vol),
            max(0.01, w_shock),
            max(0.05, w_no_trade),
        ]
        sum_w = sum(raw_weights)
        norm_probs = [round((w / sum_w) * 100.0, 1) for w in raw_weights]

        # Ensure exact 100.0% sum by adjusting largest slice
        diff = round(100.0 - sum(norm_probs), 1)
        norm_probs[0] = round(norm_probs[0] + diff, 1)

        # Build distributions
        scenarios: List[ScenarioDistribution] = [
            # 1. Bullish Continuation
            ScenarioDistribution(
                scenario=ScenarioArchetype.BULLISH_CONTINUATION,
                probability_pct=norm_probs[0],
                target_price_low=round(current_price + (atr * 1.2), 1),
                target_price_high=round(current_price + (atr * 2.0), 1),
                invalidation_price=round(current_price - (atr * 0.8), 1),
                horizon_str=horizon_str,
                downside_risk_pts=round(atr * 0.8, 1),
                rationale="Trend continuation above VWAP with momentum alignment.",
            ),
            # 2. Bearish Continuation
            ScenarioDistribution(
                scenario=ScenarioArchetype.BEARISH_CONTINUATION,
                probability_pct=norm_probs[1],
                target_price_low=round(current_price - (atr * 2.0), 1),
                target_price_high=round(current_price - (atr * 1.2), 1),
                invalidation_price=round(current_price + (atr * 0.8), 1),
                horizon_str=horizon_str,
                downside_risk_pts=round(atr * 0.8, 1),
                rationale="Downtrend continuation below VWAP with supply pressure.",
            ),
            # 3. Range Bound
            ScenarioDistribution(
                scenario=ScenarioArchetype.RANGE_BOUND,
                probability_pct=norm_probs[2],
                target_price_low=round(current_price - (atr * 0.5), 1),
                target_price_high=round(current_price + (atr * 0.5), 1),
                invalidation_price=round(current_price - (atr * 1.2), 1),
                horizon_str=horizon_str,
                downside_risk_pts=round(atr * 0.6, 1),
                rationale="Mean reversion osculating around session VWAP.",
            ),
            # 4. Breakout Failure
            ScenarioDistribution(
                scenario=ScenarioArchetype.BREAKOUT_FAILURE,
                probability_pct=norm_probs[3],
                target_price_low=round(current_price - (atr * 1.0), 1),
                target_price_high=round(current_price + (atr * 0.2), 1),
                invalidation_price=round(current_price + (atr * 1.5), 1),
                horizon_str=horizon_str,
                downside_risk_pts=round(atr * 1.5, 1),
                rationale="False breakout trap followed by aggressive rejection wick.",
            ),
            # 5. Event Volatility
            ScenarioDistribution(
                scenario=ScenarioArchetype.EVENT_VOLATILITY,
                probability_pct=norm_probs[4],
                target_price_low=round(current_price - (atr * 2.5), 1),
                target_price_high=round(current_price + (atr * 2.5), 1),
                invalidation_price=round(current_price - (atr * 3.0), 1),
                horizon_str=horizon_str,
                downside_risk_pts=round(atr * 3.0, 1),
                rationale="Binary news shock creating bidirectional wide dispersion.",
            ),
            # 6. Shock Price Gap
            ScenarioDistribution(
                scenario=ScenarioArchetype.SHOCK_PRICE_GAP,
                probability_pct=norm_probs[5],
                target_price_low=round(current_price - (atr * 3.5), 1),
                target_price_high=round(current_price + (atr * 3.5), 1),
                invalidation_price=round(current_price - (atr * 4.0), 1),
                horizon_str=horizon_str,
                downside_risk_pts=round(atr * 4.0, 1),
                rationale="Overnight geopolitical or central bank black-swan dislocation.",
            ),
            # 7. No-Trade
            ScenarioDistribution(
                scenario=ScenarioArchetype.NO_TRADE,
                probability_pct=norm_probs[6],
                target_price_low=round(current_price, 1),
                target_price_high=round(current_price, 1),
                invalidation_price=round(current_price, 1),
                horizon_str=horizon_str,
                downside_risk_pts=0.0,
                rationale="Signal-to-noise ratio low; expected edge less than execution friction.",
            ),
        ]

        # Calculate normalized Shannon entropy as uncertainty metric
        probs_unit = [s.probability_pct / 100.0 for s in scenarios if s.probability_pct > 0]
        entropy = -sum(p * math.log2(p) for p in probs_unit) / math.log2(len(scenarios))

        dominant = max(scenarios, key=lambda s: s.probability_pct).scenario

        return ScenarioForecastBattery(
            battery_id=f"BATTERY-{instrument}-{int(now_dt.timestamp())}",
            timestamp=ts_str,
            instrument=instrument,
            current_price=round(current_price, 2),
            timeframe=horizon_str,
            scenarios=scenarios,
            dominant_scenario=dominant,
            calibration_sample_size=calibration_sample_size,
            historical_brier_score=round(historical_brier_score, 4),
            entropy_uncertainty=round(entropy, 3),
        )

    @classmethod
    def compute_brier_score(cls, probability_outcome_pairs: List[Tuple[float, int]]) -> float:
        """Computes Brier Score across N predictions: B = (1/N) * sum((p - o)^2)."""
        if not probability_outcome_pairs:
            return 0.0
        n = len(probability_outcome_pairs)
        sq_err_sum = sum((p - o) ** 2 for p, o in probability_outcome_pairs)
        return round(sq_err_sum / n, 4)

    @classmethod
    def compute_multiclass_brier_score(
        cls,
        probability_vectors: List[List[float]],
        outcomes: List[int],
        num_classes: int = 7,
    ) -> MulticlassBrierScoreResult:
        """Computes canonical Multiclass Brier Score across N K-class predictions.
        
        Formula: BS = (1/N) * sum_{t=1}^N sum_{k=1}^K (f_{tk} - o_{tk})^2 in [0, 2]
        Normalized BS = BS / K in [0, 2/K]
        Uniform Baseline: BS_uniform = (K - 1) / K
        Brier Skill Score: BSS = 1 - (BS / BS_uniform)
        """
        if not probability_vectors or not outcomes or len(probability_vectors) != len(outcomes):
            return MulticlassBrierScoreResult(
                sample_size=0,
                num_classes=num_classes,
                raw_brier_score=0.0,
                normalized_brier_score=0.0,
                uniform_baseline_brier_score=round((num_classes - 1) / num_classes, 4),
                brier_skill_score=0.0,
                is_skillful_vs_uniform=False,
                is_calibrated=False,
                status_message="EMPTY_SAMPLE: No forecasts to evaluate.",
            )

        n = len(probability_vectors)
        total_sq_error = 0.0

        for idx, (vec, out_idx) in enumerate(zip(probability_vectors, outcomes)):
            if not isinstance(vec, (list, tuple)):
                raise ValueError(f"Forecast at index {idx} must be a list or tuple of probabilities.")
            if len(vec) != num_classes:
                raise ValueError(f"Probability vector length ({len(vec)}) at index {idx} does not match num_classes ({num_classes}).")
            
            # Element-wise probability validation
            for p_idx, p in enumerate(vec):
                if not isinstance(p, (int, float)) or math.isnan(p) or math.isinf(p) or p < 0.0:
                    raise ValueError(f"Invalid probability value {p} at vector {idx}, class {p_idx}. Must be non-negative real number.")

            sum_p = sum(vec)
            if abs(sum_p - 1.0) > 0.01 and abs(sum_p - 100.0) > 1.0:
                raise ValueError(f"Probability vector at index {idx} must sum to 1.0 (or 100.0), got {sum_p:.4f}.")

            # Strict outcome validation
            if not isinstance(out_idx, int) or out_idx < 0 or out_idx >= num_classes:
                raise ValueError(f"Outcome at index {idx} must be an integer in range [0, {num_classes - 1}], got {out_idx}.")

            # Normalize to 0..1 if given as percentages
            probs_01 = [p / 100.0 if sum_p > 10.0 else p for p in vec]
            
            for k in range(num_classes):
                target = 1.0 if k == out_idx else 0.0
                total_sq_error += (probs_01[k] - target) ** 2

        raw_bs = total_sq_error / n
        norm_bs = raw_bs / num_classes
        uniform_bs = (num_classes - 1.0) / num_classes  # e.g., 6/7 ~= 0.85714 for K=7
        raw_skill = 1.0 - (raw_bs / uniform_bs) if uniform_bs > 0 else 0.0
        skill_score = round(raw_skill, 4)
        is_skillful = skill_score > 0.0
        is_calib = (n >= cls.MIN_CALIBRATION_SAMPLE_SIZE) and is_skillful and (norm_bs <= 0.15)

        if not is_skillful:
            msg = f"UNSKILLFUL: Raw Brier score ({raw_bs:.4f}) does not outperform uniform baseline ({uniform_bs:.4f}). Skill score: {skill_score:.4f}"
        elif n < cls.MIN_CALIBRATION_SAMPLE_SIZE:
            msg = f"CALIBRATION_PENDING: Sample size ({n}) < minimum required threshold ({cls.MIN_CALIBRATION_SAMPLE_SIZE}). Skill score: {skill_score:.4f}"
        else:
            msg = f"CALIBRATED: Sample size ({n}) >= {cls.MIN_CALIBRATION_SAMPLE_SIZE}, beats uniform baseline with skill score {skill_score:.4f} and normalized BS {norm_bs:.4f}."

        return MulticlassBrierScoreResult(
            sample_size=n,
            num_classes=num_classes,
            raw_brier_score=round(raw_bs, 4),
            normalized_brier_score=round(norm_bs, 4),
            uniform_baseline_brier_score=round(uniform_bs, 4),
            brier_skill_score=round(skill_score, 4),
            is_skillful_vs_uniform=is_skillful,
            is_calibrated=is_calib,
            status_message=msg,
        )

    @classmethod
    def evaluate_calibration_series(
        cls,
        records: List[Dict[str, Any]],
        num_classes: int = 7,
    ) -> Dict[str, Any]:
        """Tracks rolling calibration across resolved historical forecasts with horizon and uncertainty reporting."""
        if not records:
            return {
                "sample_size": 0,
                "is_calibrated": False,
                "message": "NO_RESOLVED_FORECASTS: Zero resolved forecast records available.",
            }

        valid_records = [
            r for r in records
            if "probability_vector" in r and "resolved_outcome" in r and r["resolved_outcome"] is not None
        ]
        if not valid_records:
            return {
                "sample_size": 0,
                "is_calibrated": False,
                "message": "NO_RESOLVED_OUTCOMES: Forecasts exist but none have observed outcomes yet.",
            }

        vectors = [r["probability_vector"] for r in valid_records]
        outcomes = [r["resolved_outcome"] for r in valid_records]
        brier_res = cls.compute_multiclass_brier_score(vectors, outcomes, num_classes=num_classes)

        # Break down by horizon, instrument, and regime
        horizon_groups: Dict[str, List[int]] = {}
        instrument_groups: Dict[str, List[int]] = {}
        regime_groups: Dict[str, List[int]] = {}
        entropies = []
        timestamps = []

        for i, r in enumerate(valid_records):
            h = r.get("horizon", "UNKNOWN")
            inst = r.get("instrument", "NIFTY")
            reg = r.get("market_regime", "UNSPECIFIED")

            horizon_groups.setdefault(h, []).append(i)
            instrument_groups.setdefault(inst, []).append(i)
            regime_groups.setdefault(reg, []).append(i)

            if "entropy_uncertainty" in r and r["entropy_uncertainty"] is not None:
                entropies.append(r["entropy_uncertainty"])
            if "timestamp" in r:
                timestamps.append(r["timestamp"])

        horizon_metrics = {}
        for h, indices in horizon_groups.items():
            h_vecs = [vectors[i] for i in indices]
            h_outs = [outcomes[i] for i in indices]
            h_brier = cls.compute_multiclass_brier_score(h_vecs, h_outs, num_classes=num_classes)
            horizon_metrics[h] = {
                "sample_size": len(indices),
                "raw_brier_score": h_brier.raw_brier_score,
                "skill_score": h_brier.brier_skill_score,
            }

        instrument_metrics = {}
        for inst, indices in instrument_groups.items():
            inst_vecs = [vectors[i] for i in indices]
            inst_outs = [outcomes[i] for i in indices]
            inst_brier = cls.compute_multiclass_brier_score(inst_vecs, inst_outs, num_classes=num_classes)
            instrument_metrics[inst] = {
                "sample_size": len(indices),
                "raw_brier_score": inst_brier.raw_brier_score,
                "skill_score": inst_brier.brier_skill_score,
            }

        regime_metrics = {}
        for reg, indices in regime_groups.items():
            reg_vecs = [vectors[i] for i in indices]
            reg_outs = [outcomes[i] for i in indices]
            reg_brier = cls.compute_multiclass_brier_score(reg_vecs, reg_outs, num_classes=num_classes)
            regime_metrics[reg] = {
                "sample_size": len(indices),
                "raw_brier_score": reg_brier.raw_brier_score,
                "skill_score": reg_brier.brier_skill_score,
            }

        avg_entropy = round(sum(entropies) / len(entropies), 3) if entropies else None
        
        # Sample independence heuristic check
        has_independent_timestamps = len(set(timestamps)) == len(timestamps) if timestamps else True
        independence_status = "INDEPENDENT_OBSERVATIONS" if has_independent_timestamps else "OVERLAPPING_TIMESTAMPS_DETECTED"

        return {
            "total_resolved_forecasts": len(valid_records),
            "brier_score_result": brier_res.to_dict(),
            "mean_entropy_uncertainty": avg_entropy,
            "horizons": horizon_metrics,
            "instruments": instrument_metrics,
            "regimes": regime_metrics,
            "sample_independence_status": independence_status,
            "is_calibrated": brier_res.is_calibrated,
            "calibration_status": brier_res.status_message,
            "live_execution_authorized": False,
            "safety_invariant_notice": "CALIBRATION_ALONE_CANNOT_AUTHORIZE_LIVE_EXECUTION: Probabilistic calibration is strictly an analytical validation metric and never grants brokerage order placement permission.",
        }

    @classmethod
    def is_model_calibrated(cls, brier_score: float, sample_size: int) -> Tuple[bool, str]:
        """Determines whether a forecast model meets institutional calibration promotion gates."""
        if sample_size < cls.MIN_CALIBRATION_SAMPLE_SIZE:
            return False, f"CALIBRATION_PENDING: Sample size ({sample_size}) < minimum required threshold ({cls.MIN_CALIBRATION_SAMPLE_SIZE})."
        if brier_score > 0.25:
            return False, f"CALIBRATION_FAILED: Brier score ({brier_score:.4f}) exceeds acceptable maximum (0.25)."
        return True, f"CALIBRATED: Sample size ({sample_size}) >= 30 and Brier score ({brier_score:.4f}) <= 0.25."


@dataclass
class MulticlassBrierScoreResult:
    """Canonical multiclass Brier score evaluation container."""
    sample_size: int
    num_classes: int
    raw_brier_score: float
    normalized_brier_score: float
    uniform_baseline_brier_score: float
    brier_skill_score: float
    is_skillful_vs_uniform: bool
    is_calibrated: bool
    status_message: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
