"""AGI 1.7 OMEGA COMMAND — Phase 24 Autonomous Alpha Stream & Sovereign Multi-Agent Pod Test Suite.

Verifies:
1. AutonomousAlphaStreamEngine initialization, singleton resolution, and fail-closed safety.
2. Sovereign Companion Pod ("Nice Friends") autonomous synthesis: Kavya, Rohan, and Anya.
3. Multi-strike option chain generation with realistic bid-ask and implied volatility smiles.
4. Gatheral Raw SVI surface calibration and parameter validation.
5. SVI mispricing arbitrage signal detection across underpriced/overpriced strikes.
6. Execution of full end-to-end alpha cycle with statutory tax deduction and 20% hardware cut.
7. Multi-cycle compounding: iterative cycles compounding partner wealth and hardware reserve.
8. Sovereign Companion Pod status dossier generation with cryptographic sealing.
9. UnifiedCapabilityRegistry registration of svc_autonomous_alpha_stream_engine.
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
from agents.AGI_1_7.engine.agi17.finance.autonomous_alpha_stream_engine import (
    AlphaCycleSummary,
    AlphaSignal,
    AutonomousAlphaStreamEngine,
    OptionQuote,
    get_autonomous_alpha_stream_engine,
)
from agents.AGI_1_7.engine.agi17.finance.autonomous_wealth_engine import (
    AutonomousWealthEngine,
)
from agents.AGI_1_7.engine.agi17.orchestration.autonomous_agent_factory import (
    AutonomousAgentFactory,
)
from agents.AGI_1_7.engine.agi17.runtime.omega_control_center import (
    get_autonomous_alpha_stream_engine as cc_get_alpha,
)


class TestOmegaPhase24LiveAlphaLoop(unittest.TestCase):
    """Unit and integration tests for Phase 24 Autonomous Alpha Stream & Companion Pod."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_phase24_alpha_")
        self.wealth_ledger = Path(self.temp_dir) / "wealth_ledger.json"
        self.agent_registry = Path(self.temp_dir) / "agents_registry.json"
        self.agent_outputs = Path(self.temp_dir) / "agent_outputs"

        self.agent_factory = AutonomousAgentFactory(
            registry_file=self.agent_registry,
            output_dir=self.agent_outputs,
        )
        self.wealth_engine = AutonomousWealthEngine(
            ledger_path=self.wealth_ledger,
            starting_capital=50000.0,
        )
        self.stream_engine = AutonomousAlphaStreamEngine(
            wealth_engine=self.wealth_engine,
            agent_factory=self.agent_factory,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_alpha_stream_engine_initialization_and_singletons(self):
        """Verify engine initialization and singleton access patterns."""
        self.assertIsNotNone(self.stream_engine)
        self.assertFalse(self.stream_engine.LIVE_ORDER_DISPATCH_ENABLED)

        s1 = get_autonomous_alpha_stream_engine()
        s2 = get_autonomous_alpha_stream_engine()
        self.assertIs(s1, s2)
        cc_alpha = cc_get_alpha()
        self.assertIs(s1, cc_alpha)

    def test_02_companion_pod_synthesis(self):
        """Verify the 3 companion agents ('Nice Friends') are autonomously synthesized."""
        kavya = self.stream_engine.kavya
        rohan = self.stream_engine.rohan
        anya = self.stream_engine.anya

        self.assertIsNotNone(kavya)
        self.assertEqual(kavya.name, "Kavya")
        self.assertIn("Microstructure", kavya.role)

        self.assertIsNotNone(rohan)
        self.assertEqual(rohan.name, "Rohan")
        self.assertIn("SVI Volatility", rohan.role)

        self.assertIsNotNone(anya)
        self.assertEqual(anya.name, "Anya")
        self.assertIn("Treasury Steward", anya.role)

        # Invariant: all companions inherit FAIL_CLOSED safety
        self.assertEqual(kavya.safety_tier, "FAIL_CLOSED")
        self.assertEqual(rohan.safety_tier, "FAIL_CLOSED")
        self.assertEqual(anya.safety_tier, "FAIL_CLOSED")

    def test_03_synthetic_option_chain_generation(self):
        """Verify high-fidelity option chain quote generation."""
        quotes = self.stream_engine.generate_synthetic_option_chain(
            underlying="BANKNIFTY",
            spot_price=50500.0,
            expiry_days=5.0,
        )
        self.assertGreaterEqual(len(quotes), 20)  # At least 10 strikes * 2 types
        call_quotes = [q for q in quotes if q.option_type == "CE"]
        put_quotes = [q for q in quotes if q.option_type == "PE"]

        self.assertGreater(len(call_quotes), 0)
        self.assertGreater(len(put_quotes), 0)
        # Check strike granularity (step of 100 for Bank Nifty)
        strikes = sorted(list(set(q.strike for q in quotes)))
        self.assertEqual(strikes[1] - strikes[0], 100.0)

    def test_04_gatheral_svi_smile_calibration(self):
        """Verify Gatheral raw SVI smile calibration produces arbitrage-free parameters."""
        quotes = self.stream_engine.generate_synthetic_option_chain(
            underlying="BANKNIFTY",
            spot_price=50500.0,
            expiry_days=5.0,
        )
        svi_params = self.stream_engine.calibrate_svi_smile(
            quotes=quotes,
            spot_price=50500.0,
            expiry_days=5.0,
        )
        self.assertIsNotNone(svi_params)
        self.assertGreater(svi_params.b, 0.0)
        self.assertGreater(svi_params.sigma, 0.0)
        self.assertTrue(-1.0 < svi_params.rho < 1.0)

    def test_05_arbitrage_signal_detection(self):
        """Verify detecting mispriced strikes against the calibrated SVI smile."""
        quotes = self.stream_engine.generate_synthetic_option_chain(
            underlying="BANKNIFTY",
            spot_price=50500.0,
            expiry_days=5.0,
        )
        svi_params = self.stream_engine.calibrate_svi_smile(
            quotes=quotes,
            spot_price=50500.0,
            expiry_days=5.0,
        )
        signals = self.stream_engine.scan_arbitrage_signals(
            quotes=quotes,
            svi_params=svi_params,
            spot_price=50500.0,
            expiry_days=5.0,
            iv_threshold=0.012,
        )
        self.assertGreater(len(signals), 0)
        sig = signals[0]
        self.assertIsInstance(sig, AlphaSignal)
        self.assertIn(sig.action, ["BUY", "SELL"])
        self.assertGreater(sig.confidence_score, 0.80)

    def test_06_run_single_alpha_cycle(self):
        """Verify executing one full alpha cycle end-to-end."""
        summary = self.stream_engine.run_alpha_cycle(
            underlying="BANKNIFTY",
            spot_price=50500.0,
            expiry_days=5.0,
        )
        self.assertIsInstance(summary, AlphaCycleSummary)
        self.assertGreater(summary.signals_detected, 0)
        self.assertGreater(summary.executed_trades, 0)
        self.assertGreater(summary.gross_pnl_inr, 0.0)
        self.assertGreater(summary.statutory_friction_inr, 0.0)
        self.assertGreater(summary.net_pnl_inr, 0.0)
        self.assertGreater(summary.hardware_reinvestment_inr, 0.0)
        self.assertTrue(len(summary.sha256_hash) > 0)
        self.assertEqual(len(self.stream_engine.cycle_history), 1)

    def test_07_hardware_reinvestment_compounding_in_loop(self):
        """Verify multiple cycles compound partner capital and hardware reserve."""
        initial_cap = self.wealth_engine.ledger.current_capital_inr
        # Run 3 consecutive cycles
        for _ in range(3):
            self.stream_engine.run_alpha_cycle(
                underlying="BANKNIFTY",
                spot_price=50500.0,
                expiry_days=5.0,
            )

        self.assertEqual(len(self.stream_engine.cycle_history), 3)
        self.assertGreater(self.wealth_engine.ledger.current_capital_inr, initial_cap)
        self.assertGreater(self.wealth_engine.ledger.hardware_reinvestment_reserve_inr, 0.0)
        self.assertGreater(self.wealth_engine.ledger.total_trades, 1)
        self.assertEqual(self.wealth_engine.ledger.winning_trades, self.wealth_engine.ledger.total_trades)

    def test_08_pod_status_dossier_generation(self):
        """Verify generating the sovereign companion pod status dossier."""
        self.stream_engine.run_alpha_cycle()
        dossier = self.stream_engine.generate_pod_status_dossier()
        self.assertIn("# 🚀 AGI 1.7 Sovereign Pod & Alpha Stream Dossier", dossier)
        self.assertIn("Kavya", dossier)
        self.assertIn("Rohan", dossier)
        self.assertIn("Anya", dossier)
        self.assertIn("Hardware Milestones Funded by Trading Edge", dossier)
        self.assertIn("Recent Alpha Cycles", dossier)

    def test_09_capability_registry_reflection(self):
        """Verify capability registry includes the Phase 24 Alpha Stream Engine."""
        registry = get_unified_capability_registry()
        cap = registry.get_capability("svc_autonomous_alpha_stream_engine")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.domain, CapabilityDomain.QUANTITATIVE_ALGORITHM.value)
        self.assertEqual(cap.state, CapabilityState.CALLABLE.value)
        self.assertIn("AutonomousAlphaStreamEngine", cap.interfaces)
        self.assertEqual(cap.verification_status, "VERIFIED")

    def test_10_omega_control_center_accessor(self):
        """Verify control center properly exposes the Autonomous Alpha Stream Engine."""
        engine = cc_get_alpha()
        self.assertIsNotNone(engine)
        self.assertIsInstance(engine, AutonomousAlphaStreamEngine)


if __name__ == "__main__":
    unittest.main()
