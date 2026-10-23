"""AGI 1.7 OMEGA COMMAND — Phase 4 Acceptance Test Battery.

Authoritative Acceptance Suite covering:
1. All 13 Phase 4 live readiness gates
2. Strict prohibition of inferred capital from paper trading
3. Explicit `GO REAL` session arming with masked account ID
4. Preflight health check verification
5. 15-state order lifecycle and transition recording
6. Internal Intent ID to Broker Order ID mapping
7. Unknown order status instrument locking and safe reconciliation
8. Authoritative contract validation (underlying, expiry, segment)
9. Strict prohibition of uncovered short options (Long CE/PE only)
10. Validated SELL exit of owned positions
11. Per-trade risk bounds vs minimum lot risk limits
12. Bid-ask spread and quote freshness tolerances
13. Emergency stop blocking new orders with honest exposure inventory
14. Isolated SQLite live accounting ledger (`live_broker_ledger.db`)
15. Exact Indian statutory charges (STT, GST, SEBI, Exchange fee, Stamp duty)
16. Honest reporting of unavailable values (no synthetic placeholders)
"""

from __future__ import annotations

import datetime
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.browser.browser_service import (
    BrowserHealthStatus,
    PersistentBrowserService,
)
from agents.AGI_1_7.engine.agi17.finance.live_accounting import LiveBrokerLedger
from agents.AGI_1_7.engine.agi17.finance.live_authorization_manager import (
    LiveAuthorizationManager,
    LiveSessionConfig,
    mask_account_id,
)
from agents.AGI_1_7.engine.agi17.finance.live_broker_adapter import (
    BrokerOrderRecord,
    LiveBrokerAdapter,
    LiveOrderState,
)
from agents.AGI_1_7.engine.agi17.finance.live_contract_validator import (
    LiveContract,
    LiveContractValidator,
    OptionType,
    OrderAction,
)
from agents.AGI_1_7.engine.agi17.finance.trading_orchestrator import (
    AutonomousTradingOrchestrator,
    run_go_real_command,
)


class TestOmegaPhase4Acceptance(unittest.TestCase):
    """Authoritative Phase 4 Acceptance Test Battery."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="omega_p4_test_"))
        (self.temp_dir / "finance").mkdir(parents=True, exist_ok=True)
        bs = PersistentBrowserService()
        if bs.session:
            bs.session.is_alive = True
            bs.session.health_status = BrowserHealthStatus.READY

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        bs = PersistentBrowserService()
        if bs.session:
            bs.session.is_alive = True
            bs.session.health_status = BrowserHealthStatus.READY

    # -------------------------------------------------------------------------
    # Criterion 1: All 13 Phase 4 Live Readiness Gates Evaluation
    # -------------------------------------------------------------------------
    def test_01_readiness_gates_initial_state_blocked(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        eval_res = orch.evaluate_phase4_readiness_gates()

        self.assertEqual(eval_res["total_count"], 13)
        # Initially Gate 1 (user authorized live capital) is un-armed
        self.assertFalse(eval_res["all_gates_passed"])
        self.assertFalse(eval_res["gates"]["GATE_01_USER_AUTHORIZED_CAPITAL_AND_RISK"]["passed"])
        self.assertTrue(eval_res["gates"]["GATE_06_CORRECT_CONTRACT_AND_EXPIRY_IDENTIFICATION"]["passed"])
        self.assertTrue(eval_res["gates"]["GATE_13_STRICT_SEPARATION_OF_PAPER_AND_LIVE"]["passed"])

    # -------------------------------------------------------------------------
    # Criterion 2: Strict Prohibition of Inferred Capital
    # -------------------------------------------------------------------------
    def test_02_strict_prohibition_of_inferred_capital(self):
        auth_mgr = LiveAuthorizationManager()
        preflight = {
            "Browser Session Alive": True,
            "Market Data Feed Online": True,
            "Dynamic Calendar Verified": True,
            "Zero Unreconciled Orders": True,
            "Emergency Stop Inactive": True,
        }

        # Attempting zero or negative capital must fail
        zero_cfg = LiveSessionConfig(
            account_id="PM12345678",
            visible_funds_inr=100000.0,
            visible_margin_inr=100000.0,
            authorized_capital_inr=0.0,  # Invalid!
            max_loss_per_trade_inr=2000.0,
            max_daily_loss_inr=5000.0,
            user_confirmation_signature="UserConfirmed_Auth",
        )
        with self.assertRaises(ValueError):
            auth_mgr.arm_live_session(zero_cfg, preflight)

        # Attempting capital exceeding broker visible funds must fail
        over_cfg = LiveSessionConfig(
            account_id="PM12345678",
            visible_funds_inr=50000.0,
            visible_margin_inr=50000.0,
            authorized_capital_inr=75000.0,  # Exceeds 50k funds!
            max_loss_per_trade_inr=2000.0,
            max_daily_loss_inr=5000.0,
            user_confirmation_signature="UserConfirmed_Auth",
        )
        with self.assertRaises(ValueError):
            auth_mgr.arm_live_session(over_cfg, preflight)

    # -------------------------------------------------------------------------
    # Criterion 3: GO REAL Session Arming & Masked Account ID
    # -------------------------------------------------------------------------
    def test_03_go_real_session_arming_and_masked_id(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        go_res = orch.request_go_real(
            account_id="PM9988776655",
            authorized_capital_inr=25000.0,
            max_loss_per_trade_inr=2000.0,
            max_daily_loss_inr=4000.0,
            signature="User_Abhishek_Authorized",
            visible_funds_inr=100000.0,
            visible_margin_inr=100000.0,
        )

        self.assertEqual(go_res["status"], "ARMED")
        self.assertIn("PM-******-6655", go_res["arming_screen"])
        self.assertTrue(orch.live_auth_manager.is_armed)

        # Now Gate 1 must pass
        gates = orch.evaluate_phase4_readiness_gates()
        self.assertTrue(gates["gates"]["GATE_01_USER_AUTHORIZED_CAPITAL_AND_RISK"]["passed"])
        self.assertTrue(gates["all_gates_passed"])

    # -------------------------------------------------------------------------
    # Criterion 4: Preflight Health Failures Block Arming
    # -------------------------------------------------------------------------
    def test_04_preflight_health_failure_blocks_arming(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        # Simulate browser disconnected
        orch.browser_service.session.is_alive = False

        with self.assertRaises(PermissionError):
            orch.request_go_real(
                account_id="PM9988776655",
                authorized_capital_inr=25000.0,
                max_loss_per_trade_inr=2000.0,
                max_daily_loss_inr=4000.0,
                signature="User_Abhishek_Authorized",
            )

    # -------------------------------------------------------------------------
    # Criterion 5: 15-State Order Lifecycle
    # -------------------------------------------------------------------------
    def test_05_fifteen_state_order_lifecycle(self):
        adapter = LiveBrokerAdapter()
        contract = LiveContract(
            underlying="NIFTY",
            strike=22500.0,
            option_type=OptionType.CE,
            expiry_date="2026-10-29",
            lot_size=25,
            ltp=120.0,
            bid=119.5,
            ask=120.5,
            timestamp=datetime.datetime.now(datetime.timezone.utc).timestamp(),
        )

        order = adapter.create_order_proposal(contract, OrderAction.BUY, 25, 120.0, is_live_armed=True)
        self.assertEqual(order.state, LiveOrderState.LIVE_SESSION_ARMED)

        adapter.open_order_form(order.intent_id)
        self.assertEqual(order.state, LiveOrderState.ORDER_FORM_OPEN)

        adapter.record_submission_attempt(order.intent_id)
        self.assertEqual(order.state, LiveOrderState.ORDER_SUBMISSION_ATTEMPTED)

        adapter.mark_broker_pending(order.intent_id, broker_order_id="PM-ORD-101")
        self.assertEqual(order.state, LiveOrderState.BROKER_ORDER_STATUS_PENDING)

        adapter.confirm_broker_order(order.intent_id, broker_order_id="PM-ORD-101")
        self.assertEqual(order.state, LiveOrderState.BROKER_ORDER_CONFIRMED)

        adapter.record_broker_fill(order.intent_id, filled_qty=25, avg_price=120.0, is_partial=False)
        self.assertEqual(order.state, LiveOrderState.FULLY_FILLED)
        self.assertIn(contract.symbol, adapter.visible_positions)

    # -------------------------------------------------------------------------
    # Criterion 6: Intent ID to Broker Order ID Mapping
    # -------------------------------------------------------------------------
    def test_06_intent_id_to_broker_order_id_mapping(self):
        adapter = LiveBrokerAdapter()
        contract = LiveContract(
            underlying="BANKNIFTY",
            strike=49500.0,
            option_type=OptionType.PE,
            expiry_date="2026-10-28",
            lot_size=15,
            ltp=150.0,
            bid=149.0,
            ask=151.0,
            timestamp=datetime.datetime.now(datetime.timezone.utc).timestamp(),
        )
        order = adapter.create_order_proposal(contract, OrderAction.BUY, 15, 150.0, is_live_armed=True)
        adapter.open_order_form(order.intent_id)
        adapter.record_submission_attempt(order.intent_id)
        adapter.confirm_broker_order(order.intent_id, broker_order_id="PAYTM-992211")

        self.assertIn("PAYTM-992211", adapter.orders_by_broker_id)
        self.assertEqual(adapter.orders_by_broker_id["PAYTM-992211"].intent_id, order.intent_id)

    # -------------------------------------------------------------------------
    # Criterion 7: Unknown Order Status Halts Instrument
    # -------------------------------------------------------------------------
    def test_07_unknown_order_status_halts_instrument(self):
        adapter = LiveBrokerAdapter()
        contract = LiveContract(
            underlying="NIFTY",
            strike=22600.0,
            option_type=OptionType.CE,
            expiry_date="2026-10-29",
            lot_size=25,
            ltp=85.0,
            bid=84.5,
            ask=85.5,
            timestamp=datetime.datetime.now(datetime.timezone.utc).timestamp(),
        )
        order = adapter.create_order_proposal(contract, OrderAction.BUY, 25, 85.0, is_live_armed=True)
        adapter.open_order_form(order.intent_id)
        adapter.record_submission_attempt(order.intent_id)

        # UI freezes during submission
        adapter.mark_unknown_requires_reconciliation(order.intent_id, "UI freeze on Submit button")
        self.assertEqual(order.state, LiveOrderState.UNKNOWN_REQUIRES_RECONCILIATION)

        # Subsequent order for NIFTY must be locked
        locked, reason = adapter.check_instrument_lock("NIFTY")
        self.assertTrue(locked)
        self.assertIn("LOCKED", reason)

        # Attempting to open form on new NIFTY order must raise PermissionError
        new_order = adapter.create_order_proposal(contract, OrderAction.BUY, 25, 85.0, is_live_armed=True)
        with self.assertRaises(PermissionError):
            adapter.open_order_form(new_order.intent_id)

    # -------------------------------------------------------------------------
    # Criterion 8: Reconciliation Process Unlocks Instrument
    # -------------------------------------------------------------------------
    def test_08_reconciliation_process_unlocks_instrument(self):
        adapter = LiveBrokerAdapter()
        contract = LiveContract(
            underlying="NIFTY",
            strike=22600.0,
            option_type=OptionType.CE,
            expiry_date="2026-10-29",
            lot_size=25,
            ltp=85.0,
            bid=84.5,
            ask=85.5,
            timestamp=datetime.datetime.now(datetime.timezone.utc).timestamp(),
        )
        order = adapter.create_order_proposal(contract, OrderAction.BUY, 25, 85.0, is_live_armed=True)
        adapter.open_order_form(order.intent_id)
        adapter.record_submission_attempt(order.intent_id)
        adapter.mark_unknown_requires_reconciliation(order.intent_id, "Network glitch during Submit")

        # Reconcile confirming it never reached order book
        rec_order = adapter.reconcile_unknown_order(order.intent_id, verified_broker_order=None)
        self.assertEqual(rec_order.state, LiveOrderState.REJECTED)

        # Instrument must now be unlocked
        locked, _ = adapter.check_instrument_lock("NIFTY")
        self.assertFalse(locked)

    # -------------------------------------------------------------------------
    # Criterion 9: Authoritative Contract Validation (Underlying, Expiry, Segment)
    # -------------------------------------------------------------------------
    def test_09_contract_validation_underlying_and_expiry(self):
        validator = LiveContractValidator()
        now_dt = datetime.datetime(2026, 10, 15, 11, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))

        # Invalid underlying (Equity stock)
        invalid_und = {
            "underlying": "RELIANCE",
            "strike": 2500.0,
            "option_type": "CE",
            "expiry_date": "2026-10-29",
            "lot_size": 250,
            "ltp": 45.0,
            "timestamp": now_dt.timestamp(),
        }
        res = validator.validate_contract(invalid_und, OrderAction.BUY, now_dt=now_dt)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("Unauthorized underlying" in r for r in res.reasons))

        # Expired contract
        expired_cand = {
            "underlying": "NIFTY",
            "strike": 22500.0,
            "option_type": "CE",
            "expiry_date": "2026-10-01",  # Past!
            "lot_size": 25,
            "ltp": 50.0,
            "timestamp": now_dt.timestamp(),
        }
        res_exp = validator.validate_contract(expired_cand, OrderAction.BUY, now_dt=now_dt)
        self.assertFalse(res_exp.is_valid)
        self.assertTrue(any("already expired" in r for r in res_exp.reasons))

    # -------------------------------------------------------------------------
    # Criterion 10: Strict Prohibition of Uncovered Short Options
    # -------------------------------------------------------------------------
    def test_10_prohibit_uncovered_short_options(self):
        validator = LiveContractValidator()
        now_dt = datetime.datetime(2026, 10, 15, 11, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        raw_c = {
            "underlying": "NIFTY",
            "strike": 22500.0,
            "option_type": "CE",
            "expiry_date": "2026-10-29",
            "lot_size": 25,
            "ltp": 110.0,
            "timestamp": now_dt.timestamp(),
        }

        # Attempting naked SELL entry
        res = validator.validate_contract(raw_c, action=OrderAction.SELL, is_exit=False, now_dt=now_dt)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("UNCOVERED SHORT OPTION REJECTED" in r for r in res.reasons))

    # -------------------------------------------------------------------------
    # Criterion 11: Validated SELL Exit of Owned Position
    # -------------------------------------------------------------------------
    def test_11_validated_sell_exit_of_owned_position(self):
        validator = LiveContractValidator()
        now_dt = datetime.datetime(2026, 10, 15, 11, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        raw_c = {
            "underlying": "NIFTY",
            "strike": 22500.0,
            "option_type": "CE",
            "expiry_date": "2026-10-29",
            "lot_size": 65,
            "ltp": 135.0,
            "timestamp": now_dt.timestamp(),
            "symbol": "NIFTY2026102922500CE",
        }
        owned_pos = {
            "symbol": "NIFTY2026102922500CE",
            "quantity": 65,
            "entry_price": 110.0,
        }

        # Validated exit should pass
        res = validator.validate_contract(
            raw_c,
            action=OrderAction.SELL,
            is_exit=True,
            owned_position=owned_pos,
            now_dt=now_dt,
        )
        self.assertTrue(res.is_valid)

        # Mismatched owned position must fail
        wrong_owned = {"symbol": "NIFTY2026102922600CE", "quantity": 25}
        res_mismatch = validator.validate_contract(
            raw_c,
            action=OrderAction.SELL,
            is_exit=True,
            owned_position=wrong_owned,
            now_dt=now_dt,
        )
        self.assertFalse(res_mismatch.is_valid)
        self.assertTrue(any("mismatch" in r for r in res_mismatch.reasons))

    # -------------------------------------------------------------------------
    # Criterion 12: Per-Trade Risk Bounds vs Minimum Lot Bounds
    # -------------------------------------------------------------------------
    def test_12_per_trade_risk_violates_min_lot_bounds(self):
        validator = LiveContractValidator()
        now_dt = datetime.datetime(2026, 10, 15, 11, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))

        # NIFTY lot 25 @ ₹400 LTP -> minimum risk = 25 * 400 = ₹10,000
        # If authorized per-trade max loss is ₹3,000, trade must be rejected
        expensive_contract = {
            "underlying": "NIFTY",
            "strike": 22000.0,
            "option_type": "CE",
            "expiry_date": "2026-10-29",
            "lot_size": 25,
            "ltp": 400.0,
            "timestamp": now_dt.timestamp(),
        }
        res = validator.validate_contract(
            expensive_contract,
            action=OrderAction.BUY,
            is_exit=False,
            max_loss_per_trade_inr=3000.0,
            now_dt=now_dt,
        )
        self.assertFalse(res.is_valid)
        self.assertTrue(any("Per-trade risk violation" in r for r in res.reasons))

    # -------------------------------------------------------------------------
    # Criterion 13: Bid-Ask Spread and Quote Freshness Tolerances
    # -------------------------------------------------------------------------
    def test_13_spread_and_quote_freshness_tolerances(self):
        validator = LiveContractValidator(max_spread_pct=0.08, max_quote_age_sec=5.0)
        now_dt = datetime.datetime(2026, 10, 15, 11, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))

        # Inverted book
        inv_book = {
            "underlying": "NIFTY",
            "strike": 22500.0,
            "option_type": "CE",
            "expiry_date": "2026-10-29",
            "lot_size": 25,
            "ltp": 100.0,
            "bid": 105.0,  # Bid > Ask!
            "ask": 100.0,
            "timestamp": now_dt.timestamp(),
        }
        res_inv = validator.validate_contract(inv_book, OrderAction.BUY, now_dt=now_dt)
        self.assertFalse(res_inv.is_valid)
        self.assertTrue(any("Inverted" in r for r in res_inv.reasons))

        # Stale quote (6 seconds old)
        stale_c = {
            "underlying": "NIFTY",
            "strike": 22500.0,
            "option_type": "CE",
            "expiry_date": "2026-10-29",
            "lot_size": 25,
            "ltp": 100.0,
            "bid": 99.0,
            "ask": 101.0,
            "timestamp": now_dt.timestamp() - 6.0,  # 6s old!
        }
        res_stale = validator.validate_contract(stale_c, OrderAction.BUY, now_dt=now_dt)
        self.assertFalse(res_stale.is_valid)
        self.assertTrue(any("stale" in r for r in res_stale.reasons))

    # -------------------------------------------------------------------------
    # Criterion 14: Emergency Stop Honest Exposure Cataloging
    # -------------------------------------------------------------------------
    def test_14_emergency_stop_honest_exposure_inventory(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        orch.request_go_real(
            account_id="PM11223344",
            authorized_capital_inr=30000.0,
            max_loss_per_trade_inr=2000.0,
            max_daily_loss_inr=5000.0,
            signature="User_Abhishek",
        )

        # Register an active position
        orch.live_broker_adapter.visible_positions["NIFTY22500CE"] = {
            "symbol": "NIFTY22500CE",
            "quantity": 25,
            "entry_price": 100.0,
            "current_price": 105.0,
            "unrealized_pnl": 125.0,
        }

        # Trigger emergency stop
        res = orch.trigger_emergency_stop(reason="Abrupt network degradation")
        self.assertEqual(res["status"], "EMERGENCY_STOP_ACTIVE")
        self.assertTrue(res["new_orders_blocked"])
        self.assertEqual(res["open_positions_count"], 1)
        self.assertEqual(res["open_exposure"][0]["symbol"], "NIFTY22500CE")
        self.assertFalse(orch.live_auth_manager.is_armed)

    # -------------------------------------------------------------------------
    # Criterion 15: Isolated SQLite Live Accounting Ledger & Zero Leakage
    # -------------------------------------------------------------------------
    def test_15_isolated_live_ledger_zero_paper_leakage(self):
        live_ledger = LiveBrokerLedger(self.temp_dir / "finance", initial_live_capital=50000.0)
        self.assertEqual(live_ledger.db_path.name, "live_broker_ledger.db")

        # Record a live order
        live_ledger.record_order_submission(
            intent_id="INTENT-NIFTY-1",
            symbol="NIFTY22500CE",
            action="BUY",
            quantity=25,
            price=100.0,
            status="ORDER_SUBMISSION_ATTEMPTED",
            broker_order_id="PM-1",
        )
        live_ledger.record_order_fill(
            intent_id="INTENT-NIFTY-1",
            filled_qty=25,
            avg_price=100.0,
            status="FULLY_FILLED",
            broker_order_id="PM-1",
        )

        summary = live_ledger.get_live_performance_summary(verified_funds=47500.0, verified_margin=0.0)
        self.assertEqual(summary["orders_submitted"], 1)
        self.assertEqual(summary["orders_filled"], 1)
        self.assertGreater(summary["total_statutory_charges_inr"], 0.0)

        # Multi-day paper ledger must remain untouched
        paper_db = self.temp_dir / "finance" / "multi_day_ledger.db"
        self.assertNotEqual(str(live_ledger.db_path), str(paper_db))

    # -------------------------------------------------------------------------
    # Criterion 16: Accurate Indian Statutory Charges Calculation
    # -------------------------------------------------------------------------
    def test_16_statutory_charges_calculation(self):
        # Buy: 25 quantity @ ₹100 = ₹2500 turnover
        # STT on buy = 0
        # Stamp duty = 2500 * 0.00003 = ₹0.075 -> ₹0.08
        # Brokerage = ₹20
        # Exchange fee = 2500 * 0.0005 = ₹1.25
        # SEBI fee = 2500 * 0.000001 = ₹0.0025 -> ₹0.00
        # GST = 18% on (20 + 1.25 + 0.00) = ₹3.825 -> ₹3.83
        charges_buy = LiveBrokerLedger.calculate_statutory_charges("BUY", 25, 100.0)
        self.assertEqual(charges_buy["stt_inr"], 0.0)
        self.assertEqual(charges_buy["brokerage_inr"], 20.0)
        self.assertGreater(charges_buy["total_charges_inr"], 20.0)

        # Sell: 25 quantity @ ₹120 = ₹3000 turnover
        # STT on sell = 3000 * 0.001 = ₹3.00
        charges_sell = LiveBrokerLedger.calculate_statutory_charges("SELL", 25, 120.0)
        self.assertEqual(charges_sell["stt_inr"], 3.0)

    # -------------------------------------------------------------------------
    # Criterion 17: Honest Reporting of Unavailable Values
    # -------------------------------------------------------------------------
    def test_17_honest_reporting_of_unavailable_values(self):
        live_ledger = LiveBrokerLedger(self.temp_dir / "finance", initial_live_capital=50000.0)
        # Without passing verified funds, summary must report UNAVAILABLE
        summary = live_ledger.get_live_performance_summary(verified_funds=None, verified_margin=None)
        self.assertEqual(summary["verified_funds_inr"], "UNAVAILABLE")
        self.assertEqual(summary["verified_margin_inr"], "UNAVAILABLE")
        self.assertEqual(summary["unrealized_pnl_inr"], "UNAVAILABLE")

    # -------------------------------------------------------------------------
    # Criterion 18: Full Live Order Submission Sequence
    # -------------------------------------------------------------------------
    def test_18_submit_live_order_full_workflow(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        orch.request_go_real(
            account_id="PM9988776655",
            authorized_capital_inr=30000.0,
            max_loss_per_trade_inr=2000.0,
            max_daily_loss_inr=4000.0,
            signature="User_Abhishek_Authorized",
        )

        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        valid_contract = {
            "underlying": "NIFTY",
            "strike": 22500.0,
            "option_type": "CE",
            "expiry_date": "2026-10-29",
            "lot_size": 65,
            "ltp": 50.0,
            "bid": 49.5,
            "ask": 50.5,
            "timestamp": now_ts,
        }

        order_record = orch.submit_live_order(
            raw_contract=valid_contract,
            action="BUY",
            quantity=65,
            price=50.0,
            stop_loss_pts=30.0,  # Risk: 65 * 30 = ₹1950 <= ₹2000 max
        )
        self.assertEqual(order_record.state, LiveOrderState.ORDER_SUBMISSION_ATTEMPTED)
        self.assertTrue(order_record.intent_id.startswith("INTENT-NIFTY"))

    # -------------------------------------------------------------------------
    # Criterion 19: Unarmed Order Submission Rejection
    # -------------------------------------------------------------------------
    def test_19_unarmed_order_submission_rejection(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        # Attempting submit_live_order without arming must fail immediately
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        valid_contract = {
            "underlying": "NIFTY",
            "strike": 22500.0,
            "option_type": "CE",
            "expiry_date": "2026-10-29",
            "lot_size": 25,
            "ltp": 50.0,
            "timestamp": now_ts,
        }
        with self.assertRaises(PermissionError):
            orch.submit_live_order(raw_contract=valid_contract, action="BUY", quantity=25, price=50.0)

    # -------------------------------------------------------------------------
    # Criterion 20: CLI GO REAL Command Execution
    # -------------------------------------------------------------------------
    def test_20_cli_go_real_command(self):
        exit_code = run_go_real_command()
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
