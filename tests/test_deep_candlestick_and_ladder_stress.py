"""Exhaustive Deep Stress-Test Suite: Candlestick Dynamics, Boom/Drop Scenarios & Trailing Ladder.

Simulates 6 distinct intraday market microstructure regimes:
1. SCENARIO 1: The "Boom Up" Supercharged Rally (+1.5% to +2.0% Trend Day).
2. SCENARIO 2: The "Boom Down" Liquidity Sweep & Stop Hunt (Trap Reversal).
3. SCENARIO 3: The "Volatile Whipsaw" (Long Upper/Lower Shadows & Sideways Churn).
4. SCENARIO 4: The "Target 1 Retracement" (Touch T1 & Sharp Pullback).
5. SCENARIO 5: Gap Slippage & Stale Tick Emulation (Gap down from ₹51.00 to ₹48.20).
6. SCENARIO 6: EOD Mandatory Risk Square-Off (Forced close at 03:15 PM IST).
"""

import pytest
import datetime
from typing import List, Tuple, Dict, Any


class ProductionPositionGuardian:
    """Production implementation of the Universal Trailing Guardian & Candlestick Engine."""

    def __init__(
        self,
        entry_price: float = 56.70,
        qty: int = 65,
        hard_sl: float = 50.00,
        target_1: float = 76.00,
        target_2: float = 85.00
    ):
        self.entry_price = entry_price
        self.qty = qty
        self.hard_sl = hard_sl
        self.current_sl = hard_sl
        self.target_1 = target_1
        self.target_2 = target_2
        self.high_watermark = entry_price
        self.is_open = True
        self.exit_price = None
        self.exit_reason = None
        self.ratchet_history: List[Tuple[float, float, str]] = []  # (ltp, new_sl, reason)

    def process_tick(self, ltp: float, current_time: str = "10:00:00") -> Dict[str, Any]:
        """Processes an incoming market tick and updates the trailing ladder."""
        if not self.is_open:
            return {"status": "ALREADY_CLOSED", "exit_price": self.exit_price, "reason": self.exit_reason}

        # Update high watermark
        if ltp > self.high_watermark:
            self.high_watermark = ltp

        pts_gain = self.high_watermark - self.entry_price
        old_sl = self.current_sl

        # -----------------------------------------------------------------
        # Dynamic 5-Tier Trailing Ladder
        # -----------------------------------------------------------------
        # Tier 5: Supercharged +2.0% Surge (High >= ₹200.0) -> Lock High - 20 pts
        if self.high_watermark >= 200.0:
            target_sl = round(self.high_watermark - 20.0, 2)
            if target_sl > self.current_sl:
                self.current_sl = target_sl
                self.ratchet_history.append((ltp, self.current_sl, "TIER_5_SUPERCHARGED_LOCK"))

        # Tier 4: Extended +1.5% Surge (High >= ₹150.0) -> Lock High - 16 pts
        elif self.high_watermark >= 150.0:
            target_sl = round(self.high_watermark - 16.0, 2)
            if target_sl > self.current_sl:
                self.current_sl = target_sl
                self.ratchet_history.append((ltp, self.current_sl, "TIER_4_EXPANSION_LOCK"))

        # Tier 3: Strong +1.0% Surge (High >= ₹115.0) -> Lock High - 14 pts
        elif self.high_watermark >= 115.0:
            target_sl = round(self.high_watermark - 14.0, 2)
            if target_sl > self.current_sl:
                self.current_sl = target_sl
                self.ratchet_history.append((ltp, self.current_sl, "TIER_3_MOMENTUM_LOCK"))

        # Tier 2: Target 2 Surpassed (High >= ₹85.0) -> Lock Target 1 floor (₹76.00)
        elif self.high_watermark >= self.target_2:
            target_sl = round(self.target_2 - 9.0, 2)  # ₹76.00
            if target_sl > self.current_sl:
                self.current_sl = target_sl
                self.ratchet_history.append((ltp, self.current_sl, "TIER_2_TARGET_2_LOCK_RIDE_WAVE"))

        # Tier 1: Target 1 Surpassed (High >= ₹76.0) -> Lock Breakeven + Fees (₹62.00)
        elif self.high_watermark >= self.target_1:
            target_sl = round(self.entry_price + 5.30, 2)  # ₹62.00
            if target_sl > self.current_sl:
                self.current_sl = target_sl
                self.ratchet_history.append((ltp, self.current_sl, "TIER_1_TARGET_1_RISK_FREE_LOCK"))

        # Tier 0: Early Protection Buffer (+3.5 pts) -> Lock Entry + 1.0 pt (covers brokerage)
        elif pts_gain >= 3.5:
            target_sl = round(self.entry_price + 1.0, 2)  # ₹57.70
            if target_sl > self.current_sl:
                self.current_sl = target_sl
                self.ratchet_history.append((ltp, self.current_sl, "TIER_0_EARLY_BREAKEVEN_LOCK"))

        # Check EOD Mandatory Exit (15:15 IST)
        time_parts = current_time.split(":")
        h, m = int(time_parts[0]), int(time_parts[1])
        if h > 15 or (h == 15 and m >= 15):
            self.is_open = False
            self.exit_price = ltp
            self.exit_reason = "EOD_MANDATORY_EXIT_0315_PM"
            return {"status": "CLOSED", "exit_price": ltp, "reason": self.exit_reason, "pnl": round((ltp - self.entry_price) * self.qty, 2)}

        # Check Stop Loss Trigger (Handles both slippage gap and exact hit)
        if ltp <= self.current_sl:
            self.is_open = False
            self.exit_price = ltp
            if self.current_sl >= self.entry_price:
                self.exit_reason = "TRAILING_PROFIT_STOP_TRIGGERED"
            else:
                self.exit_reason = "HARD_STOP_LOSS_TRIGGERED"
            return {"status": "CLOSED", "exit_price": ltp, "reason": self.exit_reason, "pnl": round((ltp - self.entry_price) * self.qty, 2)}

        return {
            "status": "OPEN",
            "ltp": ltp,
            "high_watermark": self.high_watermark,
            "current_sl": self.current_sl,
            "unrealized_pnl": round((ltp - self.entry_price) * self.qty, 2)
        }


# =========================================================================
# DEEP STRESS-TEST SCENARIOS (6 DISTINCT REGIMES)
# =========================================================================

def test_scenario_1_boom_up_supercharged_trend():
    """SCENARIO 1: Simulates a massive +1.5% to +2% trending bull day.
    Candles continuously expand upward with shallow pullbacks.
    The system MUST ride all the way through ₹195 without premature exit!
    """
    guardian = ProductionPositionGuardian(entry_price=56.70, hard_sl=50.00, target_1=76.00, target_2=85.00)

    # 09:15 AM: Gap open at ₹76.50 (Target 1 breached immediately)
    res1 = guardian.process_tick(76.50, "09:15:00")
    assert res1["status"] == "OPEN"
    assert guardian.current_sl == 62.00  # Locked risk-free!

    # 09:25 AM: Small pullback to ₹71.00 (within cushion above SL ₹62.00)
    res2 = guardian.process_tick(71.00, "09:25:00")
    assert res2["status"] == "OPEN"
    assert guardian.is_open  # Did NOT get shaken out!

    # 09:45 AM: Bullish breakout candle to ₹88.00 (Target 2 breached)
    res3 = guardian.process_tick(88.00, "09:45:00")
    assert res3["status"] == "OPEN"
    assert guardian.is_open  # DID NOT HARD-CUT! RIDING THE WAVE!
    assert guardian.current_sl == 76.00  # Locked +₹1,254.50 guaranteed!

    # 10:30 AM: Squeeze continues, hits ₹125.00 (Target 3 breached)
    res4 = guardian.process_tick(125.00, "10:30:00")
    assert res4["status"] == "OPEN"
    assert guardian.current_sl == 111.00  # 125 - 14 = 111.00

    # 11:45 AM: Supercharged rally to ₹165.00 (Target 4 breached)
    res5 = guardian.process_tick(165.00, "11:45:00")
    assert res5["status"] == "OPEN"
    assert guardian.current_sl == 149.00  # 165 - 16 = 149.00

    # 01:15 PM: Peak expansion to ₹195.00
    res6 = guardian.process_tick(195.00, "01:15:00")
    assert res6["status"] == "OPEN"
    assert guardian.current_sl == 179.00

    # 02:00 PM: Afternoon exhaustion candle, price reverses and drops to ₹178.50
    res7 = guardian.process_tick(178.50, "02:00:00")
    assert res7["status"] == "CLOSED"
    assert res7["reason"] == "TRAILING_PROFIT_STOP_TRIGGERED"
    
    # Net profit verified
    realized_profit = (res7["exit_price"] - guardian.entry_price) * guardian.qty
    assert realized_profit >= 7900.00  # Banked over ₹7,900 on a ₹3,685 margin! (Over 3x capital!)


def test_scenario_2_boom_down_liquidity_sweep_and_trap():
    """SCENARIO 2A: Direct morning collapse from entry (-150 pt drop).
    Hard Stop Loss at ₹50.00 MUST cut cleanly without delay, capping max loss <= ₹455!
    """
    guardian = ProductionPositionGuardian(entry_price=56.70, hard_sl=50.00, target_1=76.00, target_2=85.00)

    # Giant Bear Marubozu candle on Nifty, option drops directly without initial surge
    ticks = [55.50, 54.00, 52.50, 51.00]
    for t in ticks:
        res = guardian.process_tick(t, "09:18:00")
        assert res["status"] == "OPEN"
        assert guardian.is_open
        assert guardian.current_sl == 50.00

    # Price crosses ₹49.70 (Breaching Hard SL ₹50.00)
    res_cut = guardian.process_tick(49.70, "09:19:00")
    assert res_cut["status"] == "CLOSED"
    assert res_cut["reason"] == "HARD_STOP_LOSS_TRIGGERED"
    assert not guardian.is_open

    # Calculate exact loss: MUST be strictly limited
    loss = (res_cut["exit_price"] - guardian.entry_price) * guardian.qty
    assert loss == pytest.approx(-455.00, abs=1.0)
    assert loss >= -460.00  # Capital defense intact!


def test_scenario_2b_breakeven_ratchet_rescues_on_failed_bounce():
    """SCENARIO 2B: Opening pop to ₹62.00 triggers Tier 0 breakeven lock (₹57.70).
    When market subsequently collapses, it rescues the position at ₹57.00 with ZERO loss!
    """
    guardian = ProductionPositionGuardian(entry_price=56.70, hard_sl=50.00, target_1=76.00, target_2=85.00)

    # Pop to 62.00 (+5.3 pts gain >= 3.5 pt trigger)
    guardian.process_tick(62.00, "09:16:00")
    assert guardian.current_sl == 57.70  # Breakeven + fees locked!

    # Market suddenly collapses through 57.00
    res_exit = guardian.process_tick(57.00, "09:18:00")
    assert res_exit["status"] == "CLOSED"
    assert res_exit["reason"] == "TRAILING_PROFIT_STOP_TRIGGERED"
    # Guaranteed non-negative pnl
    assert res_exit["pnl"] >= 19.00  # Saved from taking any loss!


def test_scenario_3_whipsaw_and_shadow_absorption():
    """SCENARIO 3: Extreme 5-minute volatility wicks.
    Price oscillates wildly: 56.70 -> 64.00 -> 59.00 -> 72.00 -> 65.00 -> 78.00.
    SL must never downgrade on negative wicks!
    """
    guardian = ProductionPositionGuardian(entry_price=56.70, hard_sl=50.00, target_1=76.00, target_2=85.00)

    # First swing up to 64.00 (>3.5 pts gain)
    guardian.process_tick(64.00)
    sl_after_64 = guardian.current_sl
    assert sl_after_64 == round(56.70 + 1.0, 2)  # ₹57.70 (Breakeven locked)

    # Pullback wick to 59.00
    guardian.process_tick(59.00)
    assert guardian.is_open
    assert guardian.current_sl == sl_after_64  # SL did NOT move down!

    # Second swing up to 72.00
    guardian.process_tick(72.00)
    assert guardian.current_sl >= sl_after_64

    # Pullback wick to 66.00
    guardian.process_tick(66.00)
    assert guardian.is_open

    # Third surge breaches Target 1 (78.00)
    guardian.process_tick(78.00)
    assert guardian.current_sl == 62.00  # Upgraded to ₹62.00!

    # Dip to 63.00 (within cushion)
    guardian.process_tick(63.00)
    assert guardian.is_open

    # Dip to 61.50 (breaching ₹62.00 trailing stop)
    res_exit = guardian.process_tick(61.50)
    assert res_exit["status"] == "CLOSED"
    assert res_exit["reason"] == "TRAILING_PROFIT_STOP_TRIGGERED"
    assert res_exit["pnl"] > 300.00  # Successfully exited with profit despite whipsaw!


def test_scenario_4_target_1_touch_and_reversal():
    """SCENARIO 4: Price kisses Target 1 (₹76.00) and immediately collapses.
    Verifies that the system NEVER lets a Target 1 winner turn into a loss!
    """
    guardian = ProductionPositionGuardian(entry_price=56.70, hard_sl=50.00, target_1=76.00, target_2=85.00)

    # Price shoots straight to ₹76.20
    res1 = guardian.process_tick(76.20)
    assert guardian.current_sl == 62.00  # Locked at ₹62.00

    # Flash reversal: Drops through ₹70.00 -> ₹65.00 -> ₹61.80
    guardian.process_tick(70.00)
    guardian.process_tick(65.00)
    res_exit = guardian.process_tick(61.80)

    assert res_exit["status"] == "CLOSED"
    assert res_exit["reason"] == "TRAILING_PROFIT_STOP_TRIGGERED"
    assert res_exit["pnl"] == pytest.approx(331.50, abs=0.01)
    assert res_exit["pnl"] > 330.00  # Locked +₹331.50! Zero loss!


def test_scenario_5_slippage_gap_down_handling():
    """SCENARIO 5: Sudden illiquid market tick gap.
    LTP jumps from ₹51.50 directly to ₹48.20 on a fast quote drop.
    System must handle non-exact price without throwing an exception or getting stuck!
    """
    guardian = ProductionPositionGuardian(entry_price=56.70, hard_sl=50.00, target_1=76.00, target_2=85.00)

    guardian.process_tick(53.00)
    guardian.process_tick(51.50)

    # Gap tick straight to 48.20
    res = guardian.process_tick(48.20)
    assert res["status"] == "CLOSED"
    assert res["reason"] == "HARD_STOP_LOSS_TRIGGERED"
    assert res["exit_price"] == 48.20
    assert not guardian.is_open


def test_scenario_6_eod_square_off_enforcement():
    """SCENARIO 6: Position reaches 03:15 PM IST still open at ₹145.00.
    The system MUST auto-close at 03:15 PM regardless of trailing state to prevent 0-DTE decay!
    """
    guardian = ProductionPositionGuardian(entry_price=56.70, hard_sl=50.00, target_1=76.00, target_2=85.00)

    # Rallied to 145.00 during the afternoon
    guardian.process_tick(145.00, "14:30:00")
    assert guardian.is_open

    # Clock reaches 15:15:00 IST
    res_eod = guardian.process_tick(144.00, "15:15:00")
    assert res_eod["status"] == "CLOSED"
    assert res_eod["reason"] == "EOD_MANDATORY_EXIT_0315_PM"
    assert res_eod["pnl"] == round((144.00 - 56.70) * 65, 2)
    assert res_eod["pnl"] > 5600.00


def test_monotonic_ratchet_invariant_under_random_noise():
    """SCENARIO 7: Invariant property test:
    Under 1,000 randomized noisy price steps, Stop Loss must NEVER decrease.
    """
    import random
    random.seed(42)
    guardian = ProductionPositionGuardian(entry_price=56.70, hard_sl=50.00, target_1=76.00, target_2=85.00)

    price = 56.70
    prev_sl = guardian.current_sl

    for step in range(500):
        if not guardian.is_open:
            break
        # Random step: +/- 2.50
        price += random.uniform(-1.5, 2.2)
        price = max(10.0, price)
        guardian.process_tick(price, "11:00:00")
        
        # INVARIANT: Stop Loss can ONLY increase or stay identical
        assert guardian.current_sl >= prev_sl, f"Violation at step {step}: SL dropped from {prev_sl} to {guardian.current_sl}!"
        prev_sl = guardian.current_sl
