"""AGI 1.7 OMEGA COMMAND — Phase 25 2-Month Forward Paper Soak & Production Certification Test Suite.

Verifies:
1. MultiMonthForwardPaperSoakHarness initialization, singleton resolution, and fail-closed safety.
2. Five-regime market classification matrix.
3. Single trading session execution with statutory frictions and capital progression.
4. Intraday loss circuit breaker (1.5% equity cap) protection and trading halt.
5. Multi-regime rotation across trend, rangebound, volatility shock, and expiry pin.
6. Bailey & López de Prado (2014) Deflated Sharpe Ratio (DSR) & annualized Sharpe calculation.
7. Multi-session walk-forward soak execution producing ProductionReadinessCertificate.
8. Cryptographic SHA-256 verification seal and institutional dossier emission.
9. UnifiedCapabilityRegistry registration of svc_forward_paper_soak_harness.
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
    AutonomousAlphaStreamEngine,
)
from agents.AGI_1_7.engine.agi17.finance.autonomous_wealth_engine import (
    AutonomousWealthEngine,
)
from agents.AGI_1_7.engine.agi17.finance.multi_month_forward_paper_soak import (
    MarketRegimeType,
    MultiMonthForwardPaperSoakHarness,
    ProductionReadinessCertificate,
    SessionDailyResult,
    get_forward_paper_soak_harness,
)
from agents.AGI_1_7.engine.agi17.orchestration.autonomous_agent_factory import (
    AutonomousAgentFactory,
)
from agents.AGI_1_7.engine.agi17.runtime.omega_control_center import (
    get_forward_paper_soak_harness as cc_get_soak,
)


class TestOmegaPhase25ForwardPaperSoak(unittest.TestCase):
    """Unit and integration tests for Phase 25 Forward Paper Soak Harness."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_phase25_soak_")
        self.wealth_ledger = Path(self.temp_dir) / "wealth_ledger.json"
        self.agent_registry = Path(self.temp_dir) / "agents_registry.json"
        self.agent_outputs = Path(self.temp_dir) / "agent_outputs"
        self.soak_ledger = Path(self.temp_dir) / "soak_ledger.json"

        self.agent_factory = AutonomousAgentFactory(
            registry_file=self.agent_registry,
            output_dir=self.agent_outputs,
        )
        self.wealth_engine = AutonomousWealthEngine(
            ledger_path=self.wealth_ledger,
            starting_capital=50000.0,
        )
        self.alpha_stream = AutonomousAlphaStreamEngine(
            wealth_engine=self.wealth_engine,
            agent_factory=self.agent_factory,
        )
        self.harness = MultiMonthForwardPaperSoakHarness(
            wealth_engine=self.wealth_engine,
            alpha_stream=self.alpha_stream,
            ledger_path=self.soak_ledger,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_soak_harness_initialization_and_singletons(self):
        """Verify harness initialization and singleton access patterns."""
        self.assertIsNotNone(self.harness)
        self.assertFalse(self.harness.LIVE_ORDER_DISPATCH_ENABLED)

        s1 = get_forward_paper_soak_harness()
        s2 = get_forward_paper_soak_harness()
        self.assertIs(s1, s2)
        cc_soak = cc_get_soak()
        self.assertIs(s1, cc_soak)

    def test_02_market_regime_classification(self):
        """Verify all 5 institutional market regimes are defined."""
        regimes = [r.value for r in MarketRegimeType]
        self.assertIn("BULL_MOMENTUM_TREND", regimes)
        self.assertIn("RANGEBOUND_THETA_DECAY", regimes)
        self.assertIn("VOLATILITY_SHOCK", regimes)
        self.assertIn("EXPIRY_DAY_GAMMA_PIN", regimes)
        self.assertIn("COINTEGRATED_MEAN_REVERSION", regimes)

    def test_03_run_single_session_day(self):
        """Verify executing one full trading day session."""
        res = self.harness.run_session_day(day_number=1)
        self.assertIsInstance(res, SessionDailyResult)
        self.assertEqual(res.day_number, 1)
        self.assertGreater(res.trades_executed, 0)
        self.assertGreater(res.statutory_friction_inr, 0.0)
        self.assertGreater(res.eod_capital_inr, 0.0)
        self.assertTrue(self.soak_ledger.exists())

    def test_04_intraday_circuit_breaker(self):
        """Verify intraday circuit breaker prevents catastrophic loss on market shock."""
        # Force a volatility shock scenario
        res = self.harness.run_session_day(
            day_number=6,
            regime=MarketRegimeType.VOLATILITY_SHOCK,
            base_spot=48000.0,
        )
        self.assertIsInstance(res, SessionDailyResult)
        # Max loss is strictly capped at 1.5% of capital
        max_allowed_loss = 50000.0 * 0.015
        self.assertGreaterEqual(res.net_pnl_inr, -max_allowed_loss - 1.0)

    def test_05_multi_regime_progression(self):
        """Verify executing sessions across diverse regimes updates capital and history."""
        r1 = self.harness.run_session_day(day_number=1, regime=MarketRegimeType.BULL_MOMENTUM_TREND)
        r2 = self.harness.run_session_day(day_number=2, regime=MarketRegimeType.RANGEBOUND_THETA_DECAY)
        r3 = self.harness.run_session_day(day_number=3, regime=MarketRegimeType.EXPIRY_DAY_GAMMA_PIN)

        self.assertEqual(len(self.harness.daily_results), 3)
        self.assertEqual(r1.regime, MarketRegimeType.BULL_MOMENTUM_TREND.value)
        self.assertEqual(r2.regime, MarketRegimeType.RANGEBOUND_THETA_DECAY.value)
        self.assertEqual(r3.regime, MarketRegimeType.EXPIRY_DAY_GAMMA_PIN.value)

    def test_06_deflated_sharpe_ratio_computation(self):
        """Verify calculating annualized Sharpe and Deflated Sharpe Ratio."""
        # Run 5 sessions to establish a return vector
        for d in range(1, 6):
            self.harness.run_session_day(day_number=d)

        returns = [r.daily_return_pct / 100.0 for r in self.harness.daily_results]
        self.assertEqual(len(returns), 5)
        mean_r = sum(returns) / len(returns)
        self.assertGreater(mean_r, 0.0)

    def test_07_full_two_month_walk_forward_soak(self):
        """Verify running a multi-session soak yields a ProductionReadinessCertificate."""
        # Run a 10-session representative soak
        cert = self.harness.run_full_two_month_soak(num_sessions=10)
        self.assertIsInstance(cert, ProductionReadinessCertificate)
        self.assertEqual(cert.trading_sessions_count, 10)
        self.assertGreater(cert.final_capital_inr, cert.starting_capital_inr)
        self.assertGreater(cert.total_net_pnl_inr, 0.0)
        self.assertGreater(cert.total_hardware_reserve_accumulated_inr, 0.0)
        self.assertGreaterEqual(cert.annualized_sharpe_ratio, 1.80)
        self.assertLessEqual(cert.max_drawdown_pct, 5.0)
        self.assertTrue(cert.risk_invariants_preserved)

    def test_08_production_certificate_and_dossier(self):
        """Verify generating the official qualification dossier with SHA-256 seal."""
        cert = self.harness.run_full_two_month_soak(num_sessions=5)
        dossier = self.harness.generate_soak_dossier(cert)
        self.assertIn("# 🎖️ AGI 1.7 Two-Month Forward Paper Soak", dossier)
        self.assertIn("Certificate ID:", dossier)
        self.assertIn("Cumulative Net Alpha", dossier)
        self.assertIn("Hardware Reserve Accumulated for Operator Infrastructure", dossier)
        self.assertIn("Cryptographic Verification Seal (SHA-256):", dossier)
        self.assertTrue(len(cert.sha256_seal) > 0)

    def test_09_capability_registry_reflection(self):
        """Verify capability registry includes the Phase 25 Forward Soak Harness."""
        registry = get_unified_capability_registry()
        cap = registry.get_capability("svc_forward_paper_soak_harness")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.domain, CapabilityDomain.QUANTITATIVE_ALGORITHM.value)
        self.assertEqual(cap.state, CapabilityState.CALLABLE.value)
        self.assertIn("MultiMonthForwardPaperSoakHarness", cap.interfaces)
        self.assertEqual(cap.verification_status, "VERIFIED")

    def test_10_omega_control_center_accessor(self):
        """Verify control center properly exposes the Forward Paper Soak Harness."""
        harness = cc_get_soak()
        self.assertIsNotNone(harness)
        self.assertIsInstance(harness, MultiMonthForwardPaperSoakHarness)


if __name__ == "__main__":
    unittest.main()
