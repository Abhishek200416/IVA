"""AGI 1.7 OMEGA COMMAND — Unit Tests for LiquiditySweepReclaimEngine (Defense 3)."""

import pytest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agents" / "AGI_1_7" / "engine"))

from agi17.finance.liquidity_sweep_reclaim_engine import LiquiditySweepReclaimEngine

def test_1_falling_knife_strictly_blocks_buying_at_41():
    """Scenario 1: Price drops to ₹40-₹41 in free-fall; engine strictly refuses to buy."""
    engine = LiquiditySweepReclaimEngine(breakdown_level=50.00, qty=65)
    
    # Red candle dropping from 48.0 to 40.50
    sig = engine.process_candle(
        candle_time="09:22",
        o=48.00,
        h=48.20,
        l=40.20,
        c=40.50,
        v=25000
    )
    
    assert sig.is_valid is False
    assert sig.pattern == "KNIFE_FALLING_DO_NOT_TOUCH"
    assert sig.entry_trigger_price == 0.0
    assert "strictly zero buying" in sig.rationale.lower()


def test_2_absorption_hammer_bottom_detected():
    """Scenario 2: Price hits ₹39.50, but buyers absorb it creating a long lower tail (Hammer)."""
    engine = LiquiditySweepReclaimEngine(breakdown_level=50.00, qty=65)
    
    # 1. Flush down to 42
    engine.process_candle("09:22", o=48.0, h=48.0, l=42.0, c=42.5, v=20000)
    
    # 2. Hammer candle: opens at 43.0, flushes to 39.5, closes at 47.5 (lower tail = 43.0 - 39.5 = 3.5 / 8.5 range = 41% or long tail)
    sig = engine.process_candle(
        candle_time="09:23",
        o=43.00,
        h=48.00,
        l=39.50,
        c=47.50,
        v=45000
    )
    
    assert engine.sweep_lowest_low == 39.50
    assert engine.absorption_detected is True
    assert sig.is_valid is False  # Not yet reclaimed 50.00, so not entering yet!
    assert sig.pattern == "WAITING_FOR_RECLAIM"


def test_3_confirmed_reclaim_fires_sniper_entry():
    """Scenario 3: Next candle powers back ABOVE ₹50.00; fires sniper re-entry!"""
    engine = LiquiditySweepReclaimEngine(breakdown_level=50.00, qty=65)
    
    # Candle 1: Flush to 41.0
    engine.process_candle("09:22", o=48.0, h=48.0, l=41.0, c=41.5, v=20000)
    # Candle 2: Absorption Hammer
    engine.process_candle("09:23", o=42.0, h=47.0, l=39.5, c=46.8, v=35000)
    
    # Candle 3: Massive Green Reclaim: opens 47.0, hits 52.50, closes 52.00 (> 51.0 threshold!)
    sig = engine.process_candle(
        candle_time="09:24",
        o=47.00,
        h=52.50,
        l=46.50,
        c=52.00,
        v=60000
    )
    
    assert sig.is_valid is True
    assert sig.pattern == "FALSE_BREAKDOWN_CONFIRMED"
    assert sig.entry_trigger_price == 52.70  # h + 0.20
    assert sig.tight_stop_loss == 46.00   # l - 0.50 (46.50 - 0.50)
    assert sig.risk_points == 6.70
    assert sig.risk_inr_1lot == pytest.approx(435.50, abs=0.01)
    assert sig.risk_reward_ratio_t2 >= 4.5  # Reward to 85 is (85 - 52.7) = 32.3 / 6.7 = 4.82:1 R:R!


def test_4_risk_remains_strictly_below_500_cap():
    """Scenario 4: Maximum cash risk on 1 lot must never exceed ₹450 (well under ₹500 cap)."""
    engine = LiquiditySweepReclaimEngine(breakdown_level=50.00, qty=65)
    engine.process_candle("09:22", o=49.0, h=49.0, l=35.0, c=36.0, v=20000)
    sig = engine.process_candle("09:23", o=36.0, h=53.0, l=35.0, c=52.5, v=70000)
    
    assert sig.is_valid is True
    assert sig.risk_inr_1lot <= 450.00


def test_5_failed_reclaim_keeps_powder_dry():
    """Scenario 5: If price stays dead below ₹50 (chops at 42-45), zero trade is ever taken."""
    engine = LiquiditySweepReclaimEngine(breakdown_level=50.00, qty=65)
    for price in [45.0, 43.0, 44.5, 42.0, 43.8]:
        sig = engine.process_candle("09:25", o=price, h=price+0.5, l=price-0.5, c=price, v=5000)
        assert sig.is_valid is False
        assert sig.entry_trigger_price == 0.0

    assert engine.reclaim_executed is False
