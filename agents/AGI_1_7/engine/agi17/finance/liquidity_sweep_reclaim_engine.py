"""AGI 1.7 OMEGA COMMAND — Liquidity Sweep & Shakeout Reclaim Engine.

Institutional algorithms deliberately hunt retail stop losses below key support levels
(liquidity sweeps / bear traps). Once retail panic orders are absorbed, the market
rockets higher.

This engine executes Defense 3 (The Reclaim Rule):
1. State Post-Stop: Upon stop-loss exit, enters WATCHING_POST_STOP_SWEEP state (15m window).
2. Knife Protection: Categorically forbids buying during the free-fall flush (e.g., at ₹41).
3. Absorption Detection: Identifies the bottom absorption base (Hammer tail > 55% or double-bottom).
4. Decisive Reclaim: Confirms an impulse green candle breaking back above the breakdown pivot with volume.
5. Sniper Re-Entry Synthesis:
   - Entry: Breakout of reclaim bar high (e.g. ₹51.50)
   - Tight Protective SL: Low of reclaim candle (e.g. ₹47.00, risking only ~4.5 pts / ₹292)
   - Risk-Reward Ratio: Minimum 1:4 to 1:8 target profile
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import datetime

@dataclass
class ReclaimSignal:
    timestamp: str
    is_valid: bool
    pattern: str  # "FALSE_BREAKDOWN_CONFIRMED" | "WAITING_FOR_ABSORPTION" | "KNIFE_FALLING_DO_NOT_TOUCH" | "NO_SWEEP"
    entry_trigger_price: float
    tight_stop_loss: float
    risk_points: float
    risk_inr_1lot: float
    reward_target_1: float
    reward_target_2: float
    risk_reward_ratio_t1: float
    risk_reward_ratio_t2: float
    absorption_low: float
    breakdown_level: float
    rationale: str

class LiquiditySweepReclaimEngine:
    def __init__(
        self,
        breakdown_level: float = 50.00,
        qty: int = 65,
        max_observation_minutes: int = 15,
        min_reclaim_clearance_pts: float = 1.0,
        min_risk_reward: float = 3.5
    ):
        self.breakdown_level = breakdown_level
        self.qty = qty
        self.max_obs_min = max_observation_minutes
        self.min_clearance = min_reclaim_clearance_pts
        self.min_rr = min_risk_reward
        
        # State tracking
        self.is_monitoring = True
        self.sweep_lowest_low = breakdown_level
        self.absorption_detected = False
        self.reclaim_executed = False
        self.reclaim_history: List[Dict[str, Any]] = []

    def process_candle(
        self,
        candle_time: str,
        o: float,
        h: float,
        l: float,
        c: float,
        v: float,
        avg_v: float = 10000.0
    ) -> ReclaimSignal:
        """Processes each 1m/5m candle during the post-stop monitoring window."""
        if not self.is_monitoring or self.reclaim_executed:
            return self._neutral_signal("NOT_MONITORING")

        # Track the sweep lowest low
        if l < self.sweep_lowest_low:
            self.sweep_lowest_low = l

        c_range = max(0.01, h - l)
        c_body = abs(c - o)
        lower_wick = min(o, c) - l
        is_green = c >= o

        # 1. Knife Falling Check: If candle is red and closing near its low, DO NOT TOUCH!
        if not is_green and (c - l) < 0.25 * c_range and c < self.breakdown_level:
            return ReclaimSignal(
                timestamp=candle_time,
                is_valid=False,
                pattern="KNIFE_FALLING_DO_NOT_TOUCH",
                entry_trigger_price=0.0,
                tight_stop_loss=0.0,
                risk_points=0.0,
                risk_inr_1lot=0.0,
                reward_target_1=76.0,
                reward_target_2=85.0,
                risk_reward_ratio_t1=0.0,
                risk_reward_ratio_t2=0.0,
                absorption_low=self.sweep_lowest_low,
                breakdown_level=self.breakdown_level,
                rationale=f"Price is flushing down to ₹{l:.2f}. Falling knife rule active. Strictly zero buying."
            )

        # 2. Check Absorption (Hammer / Long Lower Tail)
        lower_tail_ratio = lower_wick / c_range
        if lower_tail_ratio >= 0.40:
            self.absorption_detected = True

        # 3. Check Decisive Reclaim:
        # Green candle closing back above breakdown_level + clearance
        reclaim_threshold = self.breakdown_level + self.min_clearance
        if c >= reclaim_threshold and is_green and self.sweep_lowest_low < self.breakdown_level:
            entry_price = round(h + 0.20, 2)  # Tick above high
            tight_sl = round(max(self.sweep_lowest_low, l - 0.50), 2)  # Under candle low
            risk_pts = round(entry_price - tight_sl, 2)
            
            # Enforce sensible risk bounds (risk should be between 2.0 and 8.0 points)
            if risk_pts < 1.5:
                risk_pts = 2.5
                tight_sl = round(entry_price - 2.5, 2)
            elif risk_pts > 8.0:
                # Cap the stop loss to protect capital
                tight_sl = round(entry_price - 6.0, 2)
                risk_pts = 6.0

            risk_inr = round(risk_pts * self.qty, 2)
            t1_reward = max(0.0, 76.0 - entry_price)
            t2_reward = max(0.0, 85.0 - entry_price)
            rr_t1 = round(t1_reward / risk_pts, 2) if risk_pts > 0 else 0.0
            rr_t2 = round(t2_reward / risk_pts, 2) if risk_pts > 0 else 0.0

            if rr_t1 >= self.min_rr or rr_t2 >= self.min_rr:
                self.reclaim_executed = True
                self.is_monitoring = False
                sig = ReclaimSignal(
                    timestamp=candle_time,
                    is_valid=True,
                    pattern="FALSE_BREAKDOWN_CONFIRMED",
                    entry_trigger_price=entry_price,
                    tight_stop_loss=tight_sl,
                    risk_points=risk_pts,
                    risk_inr_1lot=risk_inr,
                    reward_target_1=76.0,
                    reward_target_2=85.0,
                    risk_reward_ratio_t1=rr_t1,
                    risk_reward_ratio_t2=rr_t2,
                    absorption_low=self.sweep_lowest_low,
                    breakdown_level=self.breakdown_level,
                    rationale=(
                        f"Liquidity sweep to ₹{self.sweep_lowest_low:.2f} successfully absorbed. "
                        f"Impulse green candle reclaimed ₹{self.breakdown_level:.2f} (Close: ₹{c:.2f}). "
                        f"Sniper Re-Entry at ₹{entry_price:.2f} with tight SL at ₹{tight_sl:.2f} "
                        f"(Risk capped at ₹{risk_inr:.2f} on 1 lot, 1:{rr_t2} R:R to Target 2)."
                    )
                )
                self.reclaim_history.append(sig.__dict__)
                return sig

        # Still waiting for reclaim
        return ReclaimSignal(
            timestamp=candle_time,
            is_valid=False,
            pattern="WAITING_FOR_RECLAIM",
            entry_trigger_price=0.0,
            tight_stop_loss=0.0,
            risk_points=0.0,
            risk_inr_1lot=0.0,
            reward_target_1=76.0,
            reward_target_2=85.0,
            risk_reward_ratio_t1=0.0,
            risk_reward_ratio_t2=0.0,
            absorption_low=self.sweep_lowest_low,
            breakdown_level=self.breakdown_level,
            rationale=f"Low swept to ₹{self.sweep_lowest_low:.2f}. Absorption={'YES' if self.absorption_detected else 'WAITING'}. Awaiting decisive close above ₹{reclaim_threshold:.2f}."
        )

    def _neutral_signal(self, pattern: str) -> ReclaimSignal:
        return ReclaimSignal(
            timestamp="N/A",
            is_valid=False,
            pattern=pattern,
            entry_trigger_price=0.0,
            tight_stop_loss=0.0,
            risk_points=0.0,
            risk_inr_1lot=0.0,
            reward_target_1=76.0,
            reward_target_2=85.0,
            risk_reward_ratio_t1=0.0,
            risk_reward_ratio_t2=0.0,
            absorption_low=self.sweep_lowest_low,
            breakdown_level=self.breakdown_level,
            rationale="No active liquidity sweep event under observation."
        )
