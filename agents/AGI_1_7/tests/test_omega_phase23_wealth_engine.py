"""AGI 1.7 OMEGA COMMAND — Phase 23 Autonomous Wealth Generation & Shared Capital Compounding Test Suite.

Verifies:
1. AutonomousWealthEngine initialization, singleton resolution, and ledger path management.
2. TargetHardwareGoal bootstrapping (Level-3 Tick Feed, RTX 4090 Server, H100 Cloud Pod).
3. Bayesian-Kelly risk-managed position sizing with lot-size granularity and risk boundaries.
4. Winning paper trade execution with Indian statutory friction calculation and 20% hardware cut.
5. Losing paper trade execution with capital decrement, friction accounting, and 0% reserve cut.
6. Sequential hardware goal unlocking when cumulative reinvestment reserves surpass threshold.
7. Cryptographic Partner Alpha Dossier generation with SHA-256 seal.
8. Persistent PartnerWealthLedger saving to JSON and faithful state restoration upon reload.
9. UnifiedCapabilityRegistry registration of svc_autonomous_wealth_engine with correct domain.
10. OmegaControlCenter accessors integration.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.capabilities.unified_capability_registry import (
    CapabilityDomain,
    CapabilityState,
    get_unified_capability_registry,
)
from agents.AGI_1_7.engine.agi17.finance.autonomous_wealth_engine import (
    AutonomousWealthEngine,
    OpportunityStrategy,
    PartnerWealthLedger,
    TargetHardwareGoal,
    WealthExecutionReport,
    WealthOpportunity,
    get_autonomous_wealth_engine,
)
from agents.AGI_1_7.engine.agi17.runtime.omega_control_center import (
    get_autonomous_wealth_engine as cc_get_wealth,
)


class TestOmegaPhase23WealthEngine(unittest.TestCase):
    """Unit and integration tests for Phase 23 Autonomous Wealth Engine."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_phase23_wealth_")
        self.ledger_file = Path(self.temp_dir) / "partner_wealth_ledger.json"
        self.engine = AutonomousWealthEngine(
            ledger_path=self.ledger_file,
            starting_capital=50000.0,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_wealth_engine_initialization_and_singletons(self):
        """Verify engine initialization and singleton resolution."""
        self.assertIsNotNone(self.engine)
        self.assertEqual(self.engine.ledger.starting_capital_inr, 50000.0)
        self.assertEqual(self.engine.ledger.current_capital_inr, 50000.0)
        self.assertFalse(self.engine.LIVE_ORDER_DISPATCH_ENABLED)

        s1 = get_autonomous_wealth_engine()
        s2 = get_autonomous_wealth_engine()
        self.assertIs(s1, s2)
        cc_wealth = cc_get_wealth()
        self.assertIs(s1, cc_wealth)

    def test_02_hardware_goals_bootstrapping(self):
        """Verify standard hardware goals are bootstrapped with correct cost targets."""
        goals = self.engine.ledger.hardware_goals
        self.assertGreaterEqual(len(goals), 3)
        goal_ids = [g.goal_id for g in goals]
        self.assertIn("DATA-NSE-TICK-WEBSOCKET", goal_ids)
        self.assertIn("HW-NVIDIA-RTX-4090", goal_ids)
        self.assertIn("HW-H100-CLOUD-POD", goal_ids)

        tick_goal = next(g for g in goals if g.goal_id == "DATA-NSE-TICK-WEBSOCKET")
        self.assertEqual(tick_goal.target_cost_inr, 36000.0)
        self.assertFalse(tick_goal.is_unlocked)

    def test_03_bayesian_kelly_position_sizing(self):
        """Verify Bayesian-Kelly position sizing obeys odds, lot sizes, and risk caps."""
        # High conviction positive edge setup
        opp_bullish = WealthOpportunity(
            opportunity_id="OPP-001",
            strategy=OpportunityStrategy.SVI_SMILE_ARBITRAGE.value,
            underlying="BANKNIFTY",
            instrument_category="OPTIONS",
            side="BUY",
            entry_price=120.0,
            target_price=200.0,
            stop_loss_price=80.0,
            win_probability=0.65,
            payoff_ratio=2.0,  # 80 pt gain / 40 pt risk = 2.0
            lot_size=15,
        )
        qty = self.engine.calculate_bayesian_kelly_position(opp_bullish)
        self.assertGreater(qty, 0)
        self.assertEqual(qty % 15, 0)  # Must be a multiple of lot size 15

        # Negative edge setup (win prob low, payoff low)
        opp_negative = WealthOpportunity(
            opportunity_id="OPP-002",
            strategy=OpportunityStrategy.CPR_INTRADAY_MOMENTUM.value,
            underlying="BANKNIFTY",
            instrument_category="OPTIONS",
            side="BUY",
            entry_price=100.0,
            target_price=110.0,
            stop_loss_price=50.0,
            win_probability=0.20,
            payoff_ratio=0.2,
            lot_size=15,
        )
        qty_zero = self.engine.calculate_bayesian_kelly_position(opp_negative)
        self.assertEqual(qty_zero, 0)

    def test_04_execute_winning_paper_trade(self):
        """Verify winning trade executes, nets statutory frictions, and allocates 20% to hardware."""
        opp = WealthOpportunity(
            opportunity_id="OPP-WIN-01",
            strategy=OpportunityStrategy.SVI_SMILE_ARBITRAGE.value,
            underlying="BANKNIFTY",
            instrument_category="OPTIONS",
            side="BUY",
            entry_price=100.0,
            target_price=160.0,
            stop_loss_price=70.0,
            win_probability=0.70,
            payoff_ratio=2.0,
            lot_size=15,
        )
        # Entry at 100, exit at 150 with 30 units (2 lots)
        report = self.engine.execute_paper_trade(
            opportunity=opp,
            actual_exit_price=150.0,
            quantity=30,
        )
        self.assertIsInstance(report, WealthExecutionReport)
        self.assertEqual(report.gross_pnl_inr, 1500.0)  # (150 - 100) * 30
        self.assertGreater(report.statutory_friction_inr, 0.0)  # STT + GST + turnover
        self.assertLess(report.net_pnl_inr, report.gross_pnl_inr)
        self.assertGreater(report.net_pnl_inr, 1400.0)
        self.assertGreater(report.hardware_reinvestment_inr, 0.0)
        self.assertAlmostEqual(report.hardware_reinvestment_inr, round(report.net_pnl_inr * 0.20, 2), places=1)
        self.assertEqual(self.engine.ledger.winning_trades, 1)
        self.assertEqual(self.engine.ledger.win_rate_pct, 100.0)
        self.assertTrue(len(report.sha256_hash) > 0)

    def test_05_execute_losing_paper_trade(self):
        """Verify losing trade executes, absorbs frictions, decrements capital, and cuts 0% to hardware."""
        opp = WealthOpportunity(
            opportunity_id="OPP-LOSS-01",
            strategy=OpportunityStrategy.CROSS_INDEX_LEAD_LAG.value,
            underlying="BANKNIFTY",
            instrument_category="OPTIONS",
            side="BUY",
            entry_price=100.0,
            target_price=160.0,
            stop_loss_price=70.0,
            win_probability=0.55,
            payoff_ratio=2.0,
            lot_size=15,
        )
        # Entry at 100, exit at 70 (hit stop loss) with 15 units
        report = self.engine.execute_paper_trade(
            opportunity=opp,
            actual_exit_price=70.0,
            quantity=15,
        )
        self.assertEqual(report.gross_pnl_inr, -450.0)  # (70 - 100) * 15
        self.assertLess(report.net_pnl_inr, -450.0)  # Net is gross - friction
        self.assertEqual(report.hardware_reinvestment_inr, 0.0)  # Zero cut on losses
        self.assertEqual(self.engine.ledger.losing_trades, 1)
        self.assertLess(self.engine.ledger.current_capital_inr, 50000.0)

    def test_06_hardware_goal_sequential_unlocking(self):
        """Verify accumulating sufficient reinvestment reserves unlocks the target hardware goal."""
        opp = WealthOpportunity(
            opportunity_id="OPP-MEGA-WIN",
            strategy=OpportunityStrategy.VOLATILITY_RISK_PREMIUM.value,
            underlying="BANKNIFTY",
            instrument_category="OPTIONS",
            side="BUY",
            entry_price=50.0,
            target_price=150.0,
            stop_loss_price=30.0,
            win_probability=0.85,
            payoff_ratio=5.0,
            lot_size=15,
        )
        # Simulate a sequence of large institutional profits to accumulate > ₹36,000 in reserve
        # (Net profit of ₹1,80,000 * 20% = ₹36,000)
        report = self.engine.execute_paper_trade(
            opportunity=opp,
            actual_exit_price=250.0,  # 200 pt gain
            quantity=1000,
        )
        self.assertGreater(report.net_pnl_inr, 190000.0)
        self.assertGreater(self.engine.ledger.hardware_reinvestment_reserve_inr, 36000.0)

        # Check first goal unlocked!
        tick_goal = self.engine.ledger.hardware_goals[0]
        self.assertEqual(tick_goal.goal_id, "DATA-NSE-TICK-WEBSOCKET")
        self.assertTrue(tick_goal.is_unlocked)
        self.assertEqual(tick_goal.funded_inr, 36000.0)

    def test_07_partner_alpha_dossier_generation(self):
        """Verify generating partner alpha dossier with SHA-256 seal."""
        dossier = self.engine.generate_partner_alpha_dossier()
        self.assertIn("# 🏛️ AGI 1.7 & Operator Co-Entrepreneurial Alpha Dossier", dossier)
        self.assertIn("Partner Capital Account:", dossier)
        self.assertIn("Hardware & Compute Reinvestment Progress", dossier)
        self.assertIn("SHA-256 Cryptographic Seal:", dossier)

    def test_08_ledger_persistence_and_reloading(self):
        """Verify ledger saves to JSON and restores state identically."""
        opp = WealthOpportunity(
            opportunity_id="OPP-TEST-PERSIST",
            strategy=OpportunityStrategy.SVI_SMILE_ARBITRAGE.value,
            underlying="BANKNIFTY",
            instrument_category="OPTIONS",
            side="BUY",
            entry_price=100.0,
            target_price=150.0,
            stop_loss_price=80.0,
            win_probability=0.75,
            payoff_ratio=2.5,
            lot_size=15,
        )
        self.engine.execute_paper_trade(opp, actual_exit_price=140.0, quantity=30)
        self.assertTrue(self.ledger_file.exists())

        # Instantiate fresh engine pointing to the same file
        fresh_engine = AutonomousWealthEngine(ledger_path=self.ledger_file)
        self.assertEqual(fresh_engine.ledger.total_trades, 1)
        self.assertEqual(fresh_engine.ledger.winning_trades, 1)
        self.assertGreater(fresh_engine.ledger.hardware_reinvestment_reserve_inr, 0.0)
        self.assertEqual(len(fresh_engine.ledger.executions), 1)

    def test_09_capability_registry_reflection(self):
        """Verify capability registry includes the Phase 23 Wealth Engine."""
        registry = get_unified_capability_registry()
        cap = registry.get_capability("svc_autonomous_wealth_engine")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.domain, CapabilityDomain.QUANTITATIVE_ALGORITHM.value)
        self.assertEqual(cap.state, CapabilityState.CALLABLE.value)
        self.assertIn("AutonomousWealthEngine", cap.interfaces)
        self.assertEqual(cap.verification_status, "VERIFIED")

    def test_10_omega_control_center_accessor(self):
        """Verify control center properly exposes the Autonomous Wealth Engine."""
        engine = cc_get_wealth()
        self.assertIsNotNone(engine)
        self.assertIsInstance(engine, AutonomousWealthEngine)


if __name__ == "__main__":
    unittest.main()
