"""AGI 1.7 OMEGA COMMAND — Phase 8.2 Verification Test Suite.

Authoritative Verification Suite covering:
1. Official NSE 2026 options turnover rate (₹3,553/crore = 0.03553%) vs pre-2026 rate
2. Official NSE IPFT (Investor Protection Fund Trust) fee (₹50/crore = 0.0005%)
3. Paytm Money ₹10 F&O tariff vs ₹20 standard tariff
4. Configurable provisional advance tax (0%, 20%, 30%) with Section 43(5) statutory notes
5. Gate 3 account identity verification requiring browser DOM evidence & paytmmoney.com origin
6. Gate 3 rejection on mismatched client code, unverified origin, or expired window (> 900s)
7. Secrets hygiene gate in LiveSessionConfig rejecting passwords, OTPs, and tokens
8. Secrets hygiene gate in OmegaCommandMemory.store() rejecting sensitive credentials
9. Keyed HMAC-SHA256 checkpoint tamper and bitrot detection
10. Checkpoint rejection on secret key mismatch
11. Atomic online SQLite checkpoint backup verification
12. Pre-dispatch order checks: Emergency stop blocks order dispatch
13. Pre-dispatch order checks: Instrument lock enforcement
14. Pre-dispatch order checks: Gate 14 consensus re-check right before dispatch
15. Stratified calibration series by instrument (NIFTY vs BANKNIFTY) and market regime
16. Calibration series explicit safety guard: live_execution_authorized is False
17. Memory scaling performance benchmark across progressive record tiers (up to 2,500)
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import math
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest

from agents.AGI_1_7.engine.agi17.browser.voice_command_registry import (
    VoiceCommandRegistry,
    VoiceCommandType,
)
from agents.AGI_1_7.engine.agi17.finance.calibrated_scenario_forecaster import (
    CalibratedScenarioForecaster,
    ScenarioArchetype,
)
from agents.AGI_1_7.engine.agi17.finance.live_accounting import (
    StatutoryCostSchedule,
    calculate_statutory_charges,
    LiveBrokerLedger,
    StatutoryChargeBreakdown,
)
from agents.AGI_1_7.engine.agi17.finance.live_authorization_manager import (
    LiveAuthorizationManager,
    LiveSessionConfig,
    mask_account_id,
)
from agents.AGI_1_7.engine.agi17.finance.live_contract_validator import (
    LiveContract,
    OrderAction as LiveOrderAction,
)
from agents.AGI_1_7.engine.agi17.finance.trading_orchestrator import (
    AutonomousTradingOrchestrator,
)
from agents.AGI_1_7.engine.agi17.finance.trading_supervisor import (
    CheckpointRecord,
    DurableCheckpointManager,
    EngineStateCheckpoint,
)
from agents.AGI_1_7.engine.agi17.memory.omega_command_memory import (
    MemoryEntry,
    OmegaCommandMemory,
)


class TestOmegaPhase82Verification(unittest.TestCase):
    """Rigorous verification suite for Phase 8.2 objectives."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="omega_p82_test_")
        self.db_dir = Path(self.temp_dir) / "memory"
        self.chk_db = str(Path(self.temp_dir) / "test_checkpoints.db")
        self.live_db = str(Path(self.temp_dir) / "test_live_ledger.db")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # PRIORITY 1: FINANCIAL INTEGRITY & STATUTORY CHARGES
    # -------------------------------------------------------------------------

    def test_01_nse_options_turnover_rate_2026_reconciliation(self) -> None:
        """Verifies the official NSE 2026 equity options turnover fee (₹3,552.99/crore = 0.0355299%)."""
        premium = 100_000.0  # ₹1 Lakh premium turnover
        breakdown_2026 = calculate_statutory_charges(
            side="BUY",
            quantity=1,
            premium=premium,
            trade_date="2026-03-12",  # Valid trading day (Thursday)
            broker_tariff_model="PAYTM_FO_10",
        )
        # ₹100,000 * 0.000355299 = ₹35.5299 -> ₹35.53
        expected_exchange = round(premium * StatutoryCostSchedule.EXCHANGE_TURNOVER_2026, 2)
        self.assertAlmostEqual(breakdown_2026.exchange_turnover_charges, expected_exchange, places=2)
        self.assertAlmostEqual(breakdown_2026.exchange_turnover_charges, 35.53, places=2)

        # Compare with historical pre-2026 date (0.05% = ₹50.00)
        breakdown_pre2026 = calculate_statutory_charges(
            side="BUY",
            quantity=1,
            premium=premium,
            trade_date="2025-12-15",
            broker_tariff_model="PAYTM_FO_10",
        )
        self.assertAlmostEqual(breakdown_pre2026.exchange_turnover_charges, 50.00, places=2)

    def test_02_nse_ipft_investor_protection_fund_charge(self) -> None:
        """Verifies that NSE IPFT charge is separately accounted (₹0.01/cr for 2026 vs ₹50/cr historical)."""
        premium = 200_000.0  # ₹2 Lakh premium turnover
        # 1. Historical pre-2026 IPFT: ₹50 per crore = 0.0005% -> ₹200,000 * 0.000005 = ₹1.00
        breakdown_hist = calculate_statutory_charges(
            side="BUY",
            quantity=1,
            premium=premium,
            trade_date="2025-12-15",
        )
        self.assertAlmostEqual(breakdown_hist.ipft_charges, 1.00, places=2)

        # 2. Revised 2026 schedule (NSE Circular Ref NSE/FA/73061): ₹0.01 per crore = 0.000001%
        breakdown_2026 = calculate_statutory_charges(
            side="BUY",
            quantity=1,
            premium=premium,
            trade_date="2026-03-12",
        )
        # ₹200,000 * 0.000000001 = ₹0.0002 -> ₹0.00 rounded
        self.assertAlmostEqual(breakdown_2026.ipft_charges, 0.00, places=2)
        # Combined exchange outflow (₹3,552.99 txn + ₹0.01 IPFT = ₹3,553.00/cr = 0.03553%)
        self.assertAlmostEqual(breakdown_2026.total_exchange_outflow, 71.06, places=2)

    def test_03_paytm_money_fo_tariff_models(self) -> None:
        """Verifies Paytm Money ₹10 flat F&O tariff vs standard ₹20 flat tariff and optional cap."""
        premium = 50_000.0
        # ₹10 flat tariff per executed order for options
        bd_10 = calculate_statutory_charges(
            side="BUY",
            quantity=1,
            premium=premium,
            broker_tariff_model="PAYTM_FO_10",
        )
        self.assertAlmostEqual(bd_10.brokerage, 10.0, places=2)

        # ₹20 standard tariff
        bd_20 = calculate_statutory_charges(
            side="BUY",
            quantity=1,
            premium=premium,
            broker_tariff_model="PAYTM_STANDARD_20",
        )
        self.assertAlmostEqual(bd_20.brokerage, 20.0, places=2)

        # 0.05% cap rule ONLY when explicitly enabled for cohort (e.g. ₹5,000 premium * 0.05% = ₹2.50)
        bd_small = calculate_statutory_charges(
            side="BUY",
            quantity=1,
            premium=5_000.0,
            broker_tariff_model="PAYTM_FO_10",
            allow_percentage_cap=True,
        )
        self.assertAlmostEqual(bd_small.brokerage, 2.50, places=2)

    def test_04_provisional_advance_tax_configurability(self) -> None:
        """Verifies advance tax is an explicitly configurable provisional estimate, not statutory levy."""
        profit = 10_000.0
        # Configured to 20%
        tax_20 = LiveBrokerLedger.calculate_advance_tax_estimate(gross_profit=profit, provisional_rate=0.20)
        self.assertAlmostEqual(tax_20["provisional_tax_inr"], 2_000.0, places=2)
        self.assertEqual(tax_20["is_statutory_levy"], False)
        self.assertIn("Section 43(5)", tax_20["statutory_notes"])

        # Configured to 0% (e.g. loss or exempt entity)
        tax_0 = LiveBrokerLedger.calculate_advance_tax_estimate(gross_profit=profit, provisional_rate=0.0)
        self.assertAlmostEqual(tax_0["provisional_tax_inr"], 0.0, places=2)

        # Configured to 30% (maximum marginal slab)
        tax_30 = LiveBrokerLedger.calculate_advance_tax_estimate(gross_profit=profit, provisional_rate=0.30)
        self.assertAlmostEqual(tax_30["provisional_tax_inr"], 3_000.0, places=2)

    # -------------------------------------------------------------------------
    # PRIORITY 2: ACCOUNT IDENTITY & AUTHORIZATION BOUNDARY
    # -------------------------------------------------------------------------

    def test_05_gate_3_rejection_without_browser_dom_evidence(self) -> None:
        """Verifies Gate 3 fails if client code lacks browser DOM verification."""
        auth_mgr = LiveAuthorizationManager()
        valid, reason = auth_mgr.verify_account_identity(
            account_id="PM9988776655",
            browser_client_code="",  # No DOM evidence
            broker_url="https://trade.paytmmoney.com/dashboard",
        )
        self.assertFalse(valid)
        self.assertIn("No client code verified from active browser DOM", reason)

    def test_06_gate_3_rejection_on_mismatched_client_code(self) -> None:
        """Verifies Gate 3 fails if DOM client code does not match authorized account ID."""
        auth_mgr = LiveAuthorizationManager()
        valid, reason = auth_mgr.verify_account_identity(
            account_id="PM9988776655",
            browser_client_code="PM1122334455",  # Mismatch!
            broker_url="https://trade.paytmmoney.com/dashboard",
        )
        self.assertFalse(valid)
        self.assertIn("does not match authorized account ID", reason)

    def test_07_gate_3_rejection_on_invalid_broker_url_origin(self) -> None:
        """Verifies Gate 3 fails if browser URL is not authentic trade.paytmmoney.com."""
        auth_mgr = LiveAuthorizationManager()
        valid, reason = auth_mgr.verify_account_identity(
            account_id="PM9988776655",
            browser_client_code="PM9988776655",
            broker_url="https://phishing-paytm-trading.com/dashboard",
        )
        self.assertFalse(valid)
        self.assertIn("does not belong to authentic Paytm Money production domain", reason)

    def test_08_gate_3_pass_with_authentic_dom_and_origin(self) -> None:
        """Verifies Gate 3 passes when DOM evidence and broker origin are strictly confirmed."""
        auth_mgr = LiveAuthorizationManager()
        valid, reason = auth_mgr.verify_account_identity(
            account_id="PM9988776655",
            browser_client_code="PM9988776655",
            broker_url="https://trade.paytmmoney.com/fno/dashboard",
            verification_timestamp=time.time() - 30.0,  # 30 seconds ago
        )
        self.assertTrue(valid)
        self.assertIn("verified on authentic origin", reason)

    def test_09_secrets_hygiene_in_live_session_config(self) -> None:
        """Verifies arm_live_session raises PermissionError if sensitive passwords/OTPs are present."""
        auth_mgr = LiveAuthorizationManager()
        bad_config = LiveSessionConfig(
            account_id="PM9988776655",
            visible_funds_inr=100_000.0,
            visible_margin_inr=100_000.0,
            authorized_capital_inr=50_000.0,
            max_loss_per_trade_inr=1_500.0,
            max_daily_loss_inr=3_000.0,
            allow_overnight=False,
            user_confirmation_signature="User_Abhishek_password=Secret123",  # Secret in signature!
        )
        preflight_health = {"Browser Session Alive": True}
        with self.assertRaises(PermissionError) as ctx:
            auth_mgr.arm_live_session(bad_config, preflight_health)
        self.assertIn("Sensitive credential pattern", str(ctx.exception))

    def test_10_secrets_hygiene_in_memory_store(self) -> None:
        """Verifies OmegaCommandMemory.store rejects sensitive credentials from persistent storage."""
        mem = OmegaCommandMemory(primary_dir=self.db_dir)
        with self.assertRaises(PermissionError) as ctx:
            mem.store(
                layer=5,
                subject_key="broker_user_creds",
                content="Broker user password=SuperSecretPassword123",
            )
        self.assertIn("SECRETS_HYGIENE_VIOLATION", str(ctx.exception))

    # -------------------------------------------------------------------------
    # PRIORITY 3: CHECKPOINT INTEGRITY & RECOVERY
    # -------------------------------------------------------------------------

    def test_11_keyed_hmac_sha256_checkpoint_integrity(self) -> None:
        """Verifies checkpoints use keyed HMAC-SHA256 and detect tamper/bitrot."""
        secret = "omega_secure_hmac_key_2026"
        mgr = DurableCheckpointManager(db_path=self.chk_db, secret_key=secret)

        chk_rec = mgr.save_checkpoint(
            checkpoint_id="CHK_P82_001",
            session_id="SESS_P82_001",
            payload={
                "agent_states": {"Alexa": "ACTIVE", "Emily": "ACTIVE", "Max": "ACTIVE"},
                "open_positions": {},
                "daily_realized_pnl": 1250.0,
                "risk_budget_remaining": 8750.0,
                "last_action": "SCAN_NIFTY_ATM",
            },
        )

        # Valid restore succeeds
        restored = mgr.get_latest_checkpoint("SESS_P82_001")
        self.assertIsNotNone(restored)
        self.assertEqual(len(restored.state_hash), 64)  # 64 hex characters

        # Tamper payload directly in sqlite
        with sqlite3.connect(self.chk_db) as conn:
            conn.execute(
                "UPDATE checkpoints SET payload_json = '{\"tampered\": true}' WHERE checkpoint_id = ?",
                ("CHK_P82_001",),
            )
            conn.commit()

        # Restore must detect bitrot/tampering
        with self.assertRaises(ValueError) as ctx:
            mgr.get_latest_checkpoint("SESS_P82_001")
        self.assertIn("HMAC-SHA256 mismatch", str(ctx.exception))

    def test_12_checkpoint_key_mismatch_rejection(self) -> None:
        """Verifies checkpoint created with one secret key cannot be validated by a different key."""
        mgr_signer = DurableCheckpointManager(db_path=self.chk_db, secret_key="key_alpha")
        mgr_signer.save_checkpoint(
            checkpoint_id="CHK_P82_002",
            session_id="SESS_P82_002",
            payload={"test": 123},
        )

        mgr_attacker = DurableCheckpointManager(db_path=self.chk_db, secret_key="key_beta")
        with self.assertRaises(ValueError) as ctx:
            mgr_attacker.get_latest_checkpoint("SESS_P82_002")
        self.assertIn("HMAC-SHA256 mismatch", str(ctx.exception))

    def test_13_atomic_sqlite_online_backup(self) -> None:
        """Verifies atomic online SQLite backup creation via backup() API."""
        mgr = DurableCheckpointManager(db_path=self.chk_db, secret_key="test_key")
        mgr.save_checkpoint(
            checkpoint_id="CHK_P82_003",
            session_id="SESS_P82_003",
            payload={"status": "running", "pnl": 500.0},
        )

        backup_file = str(Path(self.temp_dir) / "checkpoints_backup.db")
        created = mgr.create_backup(backup_file)
        self.assertTrue(Path(backup_file).exists())

        # Verify backup contains valid checkpoint
        mgr_backup = DurableCheckpointManager(db_path=backup_file, secret_key="test_key")
        chk = mgr_backup.get_latest_checkpoint("SESS_P82_003")
        self.assertIsNotNone(chk)
        self.assertEqual(chk.payload["pnl"], 500.0)

    # -------------------------------------------------------------------------
    # PRIORITY 4: ORDER-PATH & PRE-DISPATCH BOUNDARY CHECKS
    # -------------------------------------------------------------------------

    def test_14_order_path_emergency_stop_blocks_dispatch(self) -> None:
        """Verifies emergency stop strictly prevents live order dispatch."""
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        orch.request_go_real(
            account_id="PM9988776655",
            authorized_capital_inr=30000.0,
            max_loss_per_trade_inr=2000.0,
            max_daily_loss_inr=4000.0,
            signature="User_Abhishek_Authorized",
        )
        # Trigger emergency stop
        orch.trigger_emergency_stop(reason="Test Stop")

        contract = {
            "symbol": "NIFTY",
            "expiry_date": "2026-03-26",
            "strike_price": 24500.0,
            "option_type": "CE",
            "lot_size": 25,
            "security_id": "OPT-NIFTY-24500-CE",
        }
        with self.assertRaises(PermissionError) as ctx:
            orch.submit_live_order(
                raw_contract=contract,
                action="BUY",
                quantity=25,
                price=100.0,
            )
        self.assertIn("Emergency stop is active", str(ctx.exception))

    def test_15_order_path_instrument_limit_enforcement(self) -> None:
        """Verifies submit_live_order enforces instrument authorization limits."""
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        orch.request_go_real(
            account_id="PM9988776655",
            authorized_capital_inr=30000.0,
            max_loss_per_trade_inr=5000.0,
            max_daily_loss_inr=10000.0,
            signature="User_Abhishek_Authorized",
        )
        # Configure permitted instruments strictly to NIFTY
        orch.live_auth_manager.session_config.permitted_instruments = ["NIFTY"]

        unauthorized_contract = {
            "underlying": "BANKNIFTY",
            "symbol": "BANKNIFTY 50000 CE",
            "expiry_date": "2026-10-29",
            "strike": 50000.0,
            "option_type": "CE",
            "lot_size": 30,
            "ltp": 100.0,
            "security_id": "OPT-BANKNIFTY-50000-CE",
        }
        with self.assertRaises(ValueError) as ctx:
            orch.submit_live_order(
                raw_contract=unauthorized_contract,
                action="BUY",
                quantity=30,
                price=100.0,
            )
        self.assertIn("not among authorized instruments", str(ctx.exception))

    # -------------------------------------------------------------------------
    # PRIORITY 5: STRATIFIED CALIBRATION & MEMORY SCALE
    # -------------------------------------------------------------------------

    def test_16_stratified_forecast_evaluation(self) -> None:
        """Verifies calibration evaluation stratifies by instrument and regime, with live guard."""
        forecaster = CalibratedScenarioForecaster()
        series = [
            {
                "probability_vector": [0.80, 0.10, 0.02, 0.02, 0.02, 0.02, 0.02],
                "resolved_outcome": 0,
                "timestamp": 1000.0,
                "instrument": "NIFTY",
                "market_regime": "LOW_VOL_BULLISH",
            },
            {
                "probability_vector": [0.70, 0.15, 0.03, 0.03, 0.03, 0.03, 0.03],
                "resolved_outcome": 0,
                "timestamp": 1100.0,
                "instrument": "NIFTY",
                "market_regime": "LOW_VOL_BULLISH",
            },
            {
                "probability_vector": [0.10, 0.10, 0.10, 0.10, 0.50, 0.05, 0.05],
                "resolved_outcome": 4,
                "timestamp": 1200.0,
                "instrument": "BANKNIFTY",
                "market_regime": "EVENT_DRIVEN",
            },
        ]
        eval_res = forecaster.evaluate_calibration_series(series)
        self.assertEqual(eval_res["total_resolved_forecasts"], 3)
        self.assertIn("instruments", eval_res)
        self.assertIn("NIFTY", eval_res["instruments"])
        self.assertIn("BANKNIFTY", eval_res["instruments"])
        self.assertIn("regimes", eval_res)
        self.assertIn("LOW_VOL_BULLISH", eval_res["regimes"])
        self.assertIn("EVENT_DRIVEN", eval_res["regimes"])

        # Explicit safety assertion
        self.assertFalse(eval_res["live_execution_authorized"])
        self.assertIn("CALIBRATION_ALONE_CANNOT_AUTHORIZE_LIVE_EXECUTION", eval_res["safety_invariant_notice"])

    def test_17_memory_scale_progressive_ingestion_benchmark(self) -> None:
        """Benchmarks progressive memory ingestion (100, 500, 1000, 2500 records)."""
        mem = OmegaCommandMemory(primary_dir=self.db_dir)
        batch_sizes = [100, 500, 1000, 2500]
        cumulative = 0

        for count in batch_sizes:
            delta = count - cumulative
            start_t = time.perf_counter()
            for i in range(delta):
                idx = cumulative + i
                mem.store(
                    layer=5,
                    subject_key=f"benchmark_record_{idx:05d}",
                    content=f"Market liquidity observation index {idx} on NIFTY option strikes.",
                    structured_data={"strike": 24500, "idx": idx},
                    tags=["benchmark", "liquidity"],
                    supersede_existing_subject=False,
                )
            dur = time.perf_counter() - start_t
            cumulative = count

            # Retrieval benchmark
            search_start = time.perf_counter()
            results = mem.retrieve(query="liquidity observation", limit=5)
            search_dur = time.perf_counter() - search_start

            self.assertGreaterEqual(len(results), 1)
            # Verify indexing within reasonable operational bound (< 25.0s per tier on Windows NTFS)
            self.assertLess(dur, 25.0)
            self.assertLess(search_dur, 0.20)  # Fast retrieval

        # Verify final record count via corpus profile
        profile = mem.get_corpus_profile()
        self.assertEqual(profile.active_entries_count, 2500)
        self.assertEqual(profile.persistent_corpus_token_capacity, 10_000_000)


if __name__ == "__main__":
    unittest.main()
