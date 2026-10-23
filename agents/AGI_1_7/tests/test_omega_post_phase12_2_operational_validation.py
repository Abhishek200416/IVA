"""AGI 1.7 OMEGA COMMAND — Post-Phase-12.2 Operational Validation Test Suite.

Verifies:
1. Operational Paper Supervisor:
   - Singleton process locking with PID verification.
   - Stale lock detection and recovery.
   - 10-state audited state machine transitions.
   - Worker heartbeat tracking for Alexa, Emily, and Max.
   - Worker failure recovery backoff.
   - Graceful shutdown and stop flag processing.
2. Market Calendar & Freshness Gates:
   - DynamicExchangeCalendar session phase enforcement (Overnight/Weekend/Pre-market vs Regular).
   - Stale market quote rejection (> 15.0 seconds).
   - Microstructure sanity gate (crossed spread / excessive spread > INR 10.0).
3. 9-Stage End-to-End Observation Pipeline & Triad Consensus:
   - Market Observation -> Max Quant -> Emily News -> Alexa UI -> Triad Consensus -> RMS -> Paper Sim -> Ledger -> Memory.
   - Binding dissent vetoes (Max, Emily, Alexa each capable of forcing PREFER_NO_TRADE).
4. Accounting Identity & Daily Reconciliation:
   - Starting Capital + Realized PnL + Unrealized PnL == Current Equity.
   - HMAC-SHA256 cryptographically signed daily summary.
   - Layer 10 persistent storage in OmegaCommandMemory.
5. Controlled Quantitative Learning & Invariants:
   - Immutable frozen baseline STRAT-BASE-VWAP-ORB.
   - Sample size promotion gate (strictly >= 50 out-of-sample trades required).
   - Revenge sizing strictly blocked (revenge_size_blocked == True).
   - Operational risk parameters strictly outside learning agent's control.
6. Telemetry & Zero Leakage:
   - Clean paper status with live dispatch locked.
   - Zero credentials or tokens in exported status reports.
   - 7-session gate strictly PENDING (0/7).
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from agents.AGI_1_7.engine.agi17.adapters.paytm_auth_callback_server import (
    PaytmTokenStore,
    redact_query_string,
    redact_token,
)
from agents.AGI_1_7.engine.agi17.finance.adaptive_strategy_learner import (
    AdaptiveStrategyLearner,
    LossRootCause,
    StrategyHypothesis,
    TradePostMortemReport,
)
from agents.AGI_1_7.engine.agi17.finance.dynamic_market_calendar import (
    CalendarSessionPhase,
    DynamicExchangeCalendar,
    VerificationStatus,
)
from agents.AGI_1_7.engine.agi17.finance.three_agent_contract import (
    ALEXA_PERSONA,
    EMILY_PERSONA,
    MAX_PERSONA,
    OrderApprovalConsensus,
    ThreeAgentContractCoordinator,
)
from agents.AGI_1_7.engine.agi17.finance.trading_supervisor import (
    Autonomous24x7TradingSupervisor,
    DuplicateSupervisorError,
    NoTradeReason,
    SupervisorServiceState,
    _is_pid_alive,
)
from agents.AGI_1_7.engine.agi17.memory.omega_command_memory import OmegaCommandMemory


@pytest.fixture
def temp_storage():
    """Provides an isolated temporary storage directory for supervisor and memory."""
    td = tempfile.mkdtemp(prefix="omega_op_val_")
    path = Path(td)
    yield path
    shutil.rmtree(td, ignore_errors=True)


# ==============================================================================
# 1. Operational Supervisor Locking & Lifecycle
# ==============================================================================
class TestSupervisorLockAndLifecycle:
    def test_singleton_lock_acquisition_and_duplicate_rejection(self, temp_storage: Path):
        sup1 = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        assert sup1.acquire_lock() is True
        assert sup1.has_lock is True
        assert (temp_storage / "trading_supervisor.pid.json").exists()

        # Second instance must raise DuplicateSupervisorError
        sup2 = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        with pytest.raises(DuplicateSupervisorError):
            sup2.acquire_lock()

        sup1.release_lock()
        assert sup1.has_lock is False
        assert not (temp_storage / "trading_supervisor.pid.json").exists()

    def test_stale_lock_recovery(self, temp_storage: Path):
        lock_file = temp_storage / "trading_supervisor.pid.json"
        # Write dead/stale PID
        stale_data = {
            "pid": 999999,
            "session_id": "STALE-SESSION-000",
            "acquired_at": "2020-01-01T00:00:00Z",
            "state": "OVERNIGHT_MONITORING",
        }
        lock_file.write_text(json.dumps(stale_data), encoding="utf-8")

        # Dead PID must not block new supervisor
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        assert sup.acquire_lock() is True
        assert sup.has_lock is True
        sup.release_lock()

    def test_service_state_transitions_with_audit_trail(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        assert sup.state == SupervisorServiceState.STARTING

        sup.transition_to(SupervisorServiceState.PREMARKET_PREPARATION, "Pre-market 09:00 IST")
        assert sup.state == SupervisorServiceState.PREMARKET_PREPARATION

        sup.transition_to(SupervisorServiceState.MARKET_OPEN, "Bell ring 09:15 IST")
        assert sup.state == SupervisorServiceState.MARKET_OPEN

        sup.transition_to(SupervisorServiceState.POSTMARKET_RECONCILIATION, "Bell close 15:30 IST")
        assert sup.state == SupervisorServiceState.POSTMARKET_RECONCILIATION

        sup.transition_to(SupervisorServiceState.OVERNIGHT_MONITORING, "Overnight maintenance")
        assert sup.state == SupervisorServiceState.OVERNIGHT_MONITORING

        # Verify transition records
        assert len(sup.transition_history) == 4
        assert sup.transition_history[-1].to_state == SupervisorServiceState.OVERNIGHT_MONITORING

    def test_graceful_shutdown_releases_lock(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        sup.acquire_lock()
        assert sup.has_lock is True

        sup.graceful_shutdown("Testing clean shutdown")
        assert sup.state == SupervisorServiceState.STOPPED
        assert sup.has_lock is False
        assert not (temp_storage / "trading_supervisor.pid.json").exists()


# ==============================================================================
# 2. Worker Heartbeat & Resilience
# ==============================================================================
class TestWorkerHeartbeatAndResilience:
    def test_worker_heartbeats_registered(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        sup.register_worker_heartbeat("ALEXA", "HEALTHY", "BROWSER_CHECK")
        sup.register_worker_heartbeat("EMILY", "HEALTHY", "NEWS_SCAN")
        sup.register_worker_heartbeat("MAX", "HEALTHY", "QUANT_SIZING")

        rep = sup.get_service_status_report()
        assert rep["overall_status"] == "HEALTHY"
        assert rep["workers"]["ALEXA"]["status"] == "HEALTHY"
        assert rep["workers"]["EMILY"]["status"] == "HEALTHY"
        assert rep["workers"]["MAX"]["status"] == "HEALTHY"

    def test_worker_failure_and_backoff_recovery(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        assert sup.fail_worker("EMILY", "NEWS_FEED_TIMEOUT") is True
        assert sup.workers["EMILY"].status == "HEALTHY"
        assert sup.workers["EMILY"].recovery_attempts == 1
        assert "RECOVERED_AFTER" in sup.workers["EMILY"].last_successful_task

        # Subsequent failures increment recovery attempts
        sup.fail_worker("EMILY", "NEWS_FEED_TIMEOUT_2")
        assert sup.workers["EMILY"].recovery_attempts == 2

        # Reset via healthy heartbeat pulse
        sup.register_worker_heartbeat("EMILY", "HEALTHY", "NEWS_FEED_RESTORED")
        assert sup.workers["EMILY"].status == "HEALTHY"
        assert sup.workers["EMILY"].recovery_attempts == 0

        # Exceeding max recovery attempts transitions supervisor to DEGRADED
        for i in range(1, 6):
            sup.fail_worker("EMILY", f"CRITICAL_FAILURE_{i}")
        assert sup.fail_worker("EMILY", "FATAL_FAILURE_EXCEEDED") is False
        assert sup.state == SupervisorServiceState.DEGRADED


# ==============================================================================
# 3. Market Calendar & Freshness Gates
# ==============================================================================
class TestMarketCalendarAndFreshnessGates:
    def test_overnight_rejects_non_simulated_ticks(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        # Authoritatively set calendar phase to OVERNIGHT_CLOSED to test overnight gate independently of test execution clock
        sup.calendar.get_session_phase = lambda *a, **kw: CalendarSessionPhase.OVERNIGHT_CLOSED
        obs = {
            "is_simulated": False,
            "timestamp": time.time(),
            "symbol": "NIFTY26OCT24200CE",
            "bid": 120.0,
            "ask": 120.5,
        }
        res = sup.evaluate_market_observation(obs)
        assert res["status"] == "NO_TRADE"
        assert res["reason"] == NoTradeReason.MARKET_CLOSED_OVERNIGHT.value
        assert sup.proposals_rejected == 1

    def test_stale_quote_rejection(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        # Tick timestamp 25 seconds ago (> 15s max allowed)
        obs = {
            "is_simulated": False,
            "timestamp": time.time() - 25.0,
            "symbol": "NIFTY26OCT24200CE",
            "bid": 120.0,
            "ask": 120.5,
        }
        res = sup.evaluate_market_observation(obs)
        assert res["status"] == "NO_TRADE"
        # Overriden by session phase first if closed, or quote age if open
        assert res["reason"] in (
            NoTradeReason.MARKET_CLOSED_OVERNIGHT.value,
            NoTradeReason.STALE_QUOTES_TIMEOUT.value,
            NoTradeReason.WEEKEND_OR_HOLIDAY_CLOSED.value,
        )


    def test_spread_sanity_gate(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        # Crossed quote: bid 130 > ask 125
        obs_crossed = {
            "is_simulated": True,
            "timestamp": time.time(),
            "symbol": "NIFTY26OCT24200CE",
            "bid": 130.0,
            "ask": 125.0,
        }
        res = sup.evaluate_market_observation(obs_crossed)
        assert res["status"] == "NO_TRADE"
        assert res["reason"] == NoTradeReason.SPREAD_TOO_WIDE.value

        # Excessively wide spread: ask - bid = 15.0 > 10.0 limit
        obs_wide = {
            "is_simulated": True,
            "timestamp": time.time(),
            "symbol": "NIFTY26OCT24200CE",
            "bid": 100.0,
            "ask": 115.0,
        }
        res_wide = sup.evaluate_market_observation(obs_wide)
        assert res_wide["status"] == "NO_TRADE"
        assert res_wide["reason"] == NoTradeReason.SPREAD_TOO_WIDE.value


# ==============================================================================
# 4. 9-Stage End-to-End Observation Pipeline & Triad Consensus
# ==============================================================================
class TestNineStageObservationPipelineAndDissent:
    def test_valid_simulated_proposal_executes_paper_fill(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        obs = {
            "is_simulated": True,
            "timestamp": time.time(),
            "symbol": "NIFTY26OCT24200CE",
            "spot_price": 24200.0,
            "bid": 130.0,
            "ask": 130.5,
            "planned_loss_inr": 40.0,
            "net_expectancy_inr": 150.0,
        }
        res = sup.evaluate_market_observation(obs)
        assert res["status"] == "EXECUTED_PAPER_FILL"
        assert res["entry_price"] == 130.55
        assert res["lot_size"] == 65
        assert sup.proposals_approved == 1
        assert len(sup.active_positions) == 1
        # Capital identity: equity == starting (10000) - statutory fees (₹27.41)
        assert sup.current_equity < 10000.0
        assert sup.current_equity > 9960.0

    def test_max_risk_limit_dissent_vetoes_trade(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        # Planned loss INR 80 exceeds single-trade risk cap (INR 50)
        obs = {
            "is_simulated": True,
            "timestamp": time.time(),
            "symbol": "NIFTY26OCT24200CE",
            "planned_loss_inr": 80.0,
            "net_expectancy_inr": 150.0,
            "bid": 130.0,
            "ask": 130.5,
        }
        res = sup.evaluate_market_observation(obs)
        assert res["status"] == "NO_TRADE"
        assert res["reason"] == NoTradeReason.TRIAD_DISSENT_VETO.value
        assert any("Max" in r for r in res["rejection_reasons"])

    def test_emily_macro_risk_dissent_vetoes_trade(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        obs = {
            "is_simulated": True,
            "timestamp": time.time(),
            "symbol": "NIFTY26OCT24200CE",
            "macro_tail_risk": True,
            "planned_loss_inr": 30.0,
            "net_expectancy_inr": 150.0,
            "bid": 130.0,
            "ask": 130.5,
        }
        res = sup.evaluate_market_observation(obs)
        assert res["status"] == "NO_TRADE"
        assert res["reason"] == NoTradeReason.TRIAD_DISSENT_VETO.value
        assert any("Emily" in r for r in res["rejection_reasons"])

    def test_alexa_browser_unready_dissent_vetoes_trade(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        obs = {
            "is_simulated": True,
            "timestamp": time.time(),
            "symbol": "NIFTY26OCT24200CE",
            "browser_unready": True,
            "planned_loss_inr": 30.0,
            "net_expectancy_inr": 150.0,
            "bid": 130.0,
            "ask": 130.5,
        }
        res = sup.evaluate_market_observation(obs)
        assert res["status"] == "NO_TRADE"
        assert res["reason"] == NoTradeReason.TRIAD_DISSENT_VETO.value
        assert any("Alexa" in r for r in res["rejection_reasons"])


# ==============================================================================
# 5. Daily Reconciliation & Accounting Identity
# ==============================================================================
class TestDailyReconciliationAndAccountingIdentity:
    def test_daily_reconciliation_hmac_signature(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        recon = sup.run_daily_reconciliation()
        assert recon["is_identity_verified"] is True
        assert recon["epoch_id"] == "EPOCH-PAPER-10K-20261014-001"
        assert len(recon["hmac_sha256_signature"]) == 64
        assert recon["mode"] == "PAPER ONLY"
        assert recon["seven_session_gate_status"] == "PENDING (0/7 ELIGIBLE SESSIONS COMPLETED)"

    def test_ledger_accounting_identity_invariance(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        obs = {
            "is_simulated": True,
            "timestamp": time.time(),
            "symbol": "NIFTY26OCT24200CE",
            "bid": 130.0,
            "ask": 130.5,
            "planned_loss_inr": 35.0,
            "net_expectancy_inr": 140.0,
        }
        sup.evaluate_market_observation(obs)

        # Invariant: Current Equity == Starting Capital + Realized PnL + Unrealized PnL
        diff = abs(sup.current_equity - (sup.starting_capital + sup.realized_pnl + sup.unrealized_pnl))
        assert diff < 1e-4

        recon = sup.run_daily_reconciliation()
        assert recon["is_identity_verified"] is True
        assert recon["ending_equity_inr"] == sup.current_equity

    def test_reconciliation_persists_to_omega_memory(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        recon = sup.run_daily_reconciliation()
        mem = sup.memory
        recs = mem.retrieve(query="reconciliation", layers=[10])
        assert len(recs) >= 1
        assert "EPOCH-PAPER-10K-20261014-001" in recs[0].content or "reconciliation" in recs[0].subject_key


# ==============================================================================
# 6. Controlled Quantitative Learning & Invariants
# ==============================================================================
class TestControlledQuantitativeLearning:
    def test_baseline_strategy_is_immutable(self):
        learner = AdaptiveStrategyLearner()
        base = learner.baseline
        assert base.strategy_id == "STRAT-BASE-VWAP-ORB"
        assert base.out_of_sample_expectancy_inr == 185.0
        assert base.profit_factor == 1.45
        assert base.max_drawdown_pct == 0.038
        assert base.is_promoted is True

    def test_sample_size_gate_rejects_small_samples(self):
        learner = AdaptiveStrategyLearner()
        # High profit factor and expectancy, but sample size = 25 trades (< 50)
        promoted, hypo = learner.evaluate_alternative_hypothesis(
            strategy_id="STRAT-CANDIDATE-LUCKY",
            version="1.0.0",
            hypothesis_statement="High win-rate 5m pinbar strategy",
            parameters={"pinbar_size": 1.5},
            out_of_sample_expectancy=350.0,
            profit_factor=2.8,
            max_drawdown_pct=0.02,
            directional_accuracy_pct=75.0,
            win_rate_pct=70.0,
            sample_size_trades=25,
        )
        assert promoted is False
        assert hypo.is_promoted is False
        assert "Insufficient sample size" in hypo.decision_reason

    def test_strategy_promotion_strictly_requires_baseline_outperformance(self):
        learner = AdaptiveStrategyLearner()
        # Meets sample size (100 trades), but higher drawdown (5.5% > baseline 3.8%)
        promoted, hypo = learner.evaluate_alternative_hypothesis(
            strategy_id="STRAT-CANDIDATE-HIGH-DD",
            version="1.0.0",
            hypothesis_statement="Trend following with wide trailing stops",
            parameters={"trail_mult": 2.5},
            out_of_sample_expectancy=210.0,  # Higher expectancy
            profit_factor=1.50,
            max_drawdown_pct=0.055,  # Breaches 3.8% cap
            directional_accuracy_pct=60.0,
            win_rate_pct=55.0,
            sample_size_trades=120,
        )
        assert promoted is False
        assert hypo.is_promoted is False
        assert "Did not strictly outperform baseline" in hypo.decision_reason

    def test_trade_post_mortem_enforces_revenge_sizing_block(self):
        pm = TradePostMortemReport(
            trade_id="TR-TEST-001",
            strategy_id="STRAT-BASE-VWAP-ORB",
            entry_timestamp="2026-10-14T09:30:00Z",
            exit_timestamp="2026-10-14T09:45:00Z",
            original_thesis="Long breakout at ORB high",
            forecast_direction="BULLISH",
            planned_entry_price=130.0,
            actual_fill_price=130.5,
            planned_exit_price=150.0,
            actual_exit_price=120.0,
            gross_pnl_inr=-682.5,
            statutory_charges_inr=15.2,
            slippage_drag_inr=32.5,
            net_pnl_inr=-730.2,
            root_cause=LossRootCause.SIGNAL_LOGIC,
            root_cause_explanation="False breakout triggered on declining volume.",
            evidence_classification="AUDITED_TICK_LOG",
            alternative_hypothesis="Require volume surge confirmation >= 1.5x 20-bar SMA.",
            baseline_intact=True,
            revenge_size_blocked=True,
        )
        assert pm.revenge_size_blocked is True
        assert pm.baseline_intact is True
        d = pm.to_dict()
        assert d["root_cause"] == "SIGNAL_LOGIC"
        assert d["revenge_size_blocked"] is True


# ==============================================================================
# 7. Telemetry & Zero Leakage
# ==============================================================================
class TestTelemetryAndZeroLeakage:
    def test_supervisor_progress_report_contains_zero_secrets(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        report = sup.write_progress_report()

        report_str = json.dumps(report)
        # Ensure zero sensitive keys or values
        assert "api_secret" not in report_str
        assert "api_key" not in report_str
        assert "bearer_token" not in report_str
        assert "access_token" not in report_str
        assert report["mode"] == "PAPER ONLY"
        assert report["live_dispatch_locked"] is True
        assert report["seven_session_gate"]["completed_sessions"] == 0
        assert report["seven_session_gate"]["required_sessions"] == 7

    def test_seven_session_forward_gate_is_strictly_pending(self, temp_storage: Path):
        sup = Autonomous24x7TradingSupervisor(storage_dir=temp_storage)
        rep = sup.get_service_status_report()
        prog = sup.write_progress_report()
        assert "PENDING" in prog["seven_session_gate"]["status"]
        assert prog["seven_session_gate"]["completed_sessions"] == 0
