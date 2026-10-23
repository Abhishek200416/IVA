"""AGI 1.7 Next Security Milestone — Phase 4 Finance Safety Invariants Test Suite.

Verifies:
1. Paper mode isolation: real-money brokerage execution is absent, quarantined, and permanently disabled.
2. Market data integrity: stale, missing, inverted (bid > ask), and non-positive quotes are rejected.
3. Pre-trade RMS limits fail closed: single order lots cap, order notional cap, and aggregate gross exposure cap.
4. Fat-finger protection: price deviations > 20% from Black-Scholes fair value are rejected.
5. Margin health gate: accounts in MARGIN_CALL or FORCE_LIQUIDATION are barred from opening new positions.
6. Portfolio drawdown kill switch: peak-to-trough drawdown >= 3.0% halts trading and generates cancellation plan.
7. Order idempotency: duplicate retry submissions with identical idempotency_key do not double-execute or double-bill.
8. Balance and inventory constraints: insufficient cash, position capital allocation cap, and short inventory fail closed.
9. Credential protection: broker API keys, client secrets, and TOTP tokens are scrubbed by SecretRedactor.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyContractSpec
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import (
    BankNiftyPaperTrader,
    MarketRegime,
    OrderSide,
    OrderType,
    SignalStatus,
)
from agents.AGI_1_7.engine.agi17.finance.margin_liquidation import (
    MarginAccountSnapshot,
    MarginStatus,
)
from agents.AGI_1_7.engine.agi17.finance.pre_trade_risk_killswitch import (
    EmergencyCancellationPlan,
    PortfolioKillSwitch,
    PreTradeOrderRequest,
    PreTradeRiskEngine,
)
from agents.AGI_1_7.engine.agi17.security.model_disclosure_policy import SecretRedactor


class TestFinanceSafetyInvariants(unittest.TestCase):
    """Deterministic security and invariant validation for AGI 1.7 finance modules."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.ledger_path = Path(self.tmp_dir.name) / "paper_ledger.jsonl"
        self.trader = BankNiftyPaperTrader(
            initial_capital=1_000_000.0,
            max_daily_loss_pct=0.03,
            max_position_capital_pct=0.20,
            base_slippage_bps=5.0,
            ledger_file=self.ledger_path,
        )
        self.risk_engine = PreTradeRiskEngine(
            max_single_order_lots=50,  # 50 lots = 750 units
            max_single_order_notional=2_500_000.0,
            max_gross_exposure=10_000_000.0,
            max_price_deviation_pct=0.20,
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    # -------------------------------------------------------------------------
    # TEST 1: Paper Mode Isolation Guarantee
    # -------------------------------------------------------------------------
    def test_01_paper_mode_isolation_guarantee(self) -> None:
        """Paper mode is strictly isolated; real-money order routing is absent and guaranteed zero."""
        metrics = self.trader.get_summary_metrics()
        self.assertTrue(
            metrics["zero_live_order_execution_guarantee"],
            "BankNiftyPaperTrader must explicitly enforce zero_live_order_execution_guarantee",
        )
        self.assertEqual(metrics["initial_capital"], 1_000_000.0)
        self.assertEqual(metrics["open_positions_count"], 0)
        self.assertFalse(metrics["kill_switch_active"])

    # -------------------------------------------------------------------------
    # TEST 2: Market Data - Stale Quote Rejection
    # -------------------------------------------------------------------------
    def test_02_market_data_stale_quote_rejection(self) -> None:
        """Quotes older than max_staleness_seconds are rejected and block signal generation."""
        # 400 seconds ago (staleness limit is 300s)
        stale_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=400)).isoformat()
        stale_quote = {
            "symbol": "BANKNIFTY26OCT50000CE",
            "price": 420.0,
            "bid": 419.5,
            "ask": 420.5,
            "timestamp": stale_time,
        }
        valid, reason = self.trader.validate_market_quote(stale_quote, max_staleness_seconds=300.0)
        self.assertFalse(valid, "Stale quote must be marked invalid")
        self.assertIn("Quote is stale", reason)

        # evaluate_signal with stale quote yields DATA_INVALID
        signal = self.trader.evaluate_signal(
            spot_price=50000.0,
            quote=stale_quote,
            regime=MarketRegime.TRENDING_BULL,
        )
        self.assertEqual(signal.status, SignalStatus.DATA_INVALID)
        self.assertEqual(signal.recommended_lots, 0)

    # -------------------------------------------------------------------------
    # TEST 3: Market Data - Missing and Non-Positive Fields Rejection
    # -------------------------------------------------------------------------
    def test_03_market_data_missing_and_nonpositive_fields_rejection(self) -> None:
        """Quotes with missing fields or non-positive prices are rejected."""
        now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Missing 'bid'
        incomplete_quote = {
            "symbol": "BANKNIFTY26OCT50000CE",
            "price": 420.0,
            "ask": 420.5,
            "timestamp": now_ts,
        }
        valid, reason = self.trader.validate_market_quote(incomplete_quote)
        self.assertFalse(valid)
        self.assertIn("Missing required", reason)

        # Non-positive price
        zero_quote = {
            "symbol": "BANKNIFTY26OCT50000CE",
            "price": 0.0,
            "bid": 400.0,
            "ask": 405.0,
            "timestamp": now_ts,
        }
        valid, reason = self.trader.validate_market_quote(zero_quote)
        self.assertFalse(valid)
        self.assertIn("Non-positive price", reason)

    # -------------------------------------------------------------------------
    # TEST 4: Market Data - Inverted Spread Rejection
    # -------------------------------------------------------------------------
    def test_04_market_data_inverted_spread_rejection(self) -> None:
        """Inverted order books (bid > ask) are detected as corrupt data and rejected."""
        now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        inverted_quote = {
            "symbol": "BANKNIFTY26OCT50000CE",
            "price": 420.0,
            "bid": 425.0,  # bid > ask
            "ask": 420.0,
            "timestamp": now_ts,
        }
        valid, reason = self.trader.validate_market_quote(inverted_quote)
        self.assertFalse(valid)
        self.assertIn("Inverted spread", reason)

    # -------------------------------------------------------------------------
    # TEST 5: Pre-Trade RMS - Max Single Order Lots Cap
    # -------------------------------------------------------------------------
    def test_05_pre_trade_rms_max_single_order_lots_limit(self) -> None:
        """Orders exceeding max_single_order_lots (50 lots = 750 units) fail closed."""
        lot_size = BankNiftyContractSpec.LOT_SIZE  # 15
        # Attempt 60 lots = 900 units
        excessive_order = PreTradeOrderRequest(
            order_id="ORD-EXCESS-LOTS",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            units=60 * lot_size,
            requested_price=300.0,
            theoretical_fair_price=300.0,
        )
        dec = self.risk_engine.validate_order(
            excessive_order,
            current_portfolio_gross_exposure=0.0,
        )
        self.assertFalse(dec.approved, "Order exceeding lot size cap must be rejected")
        self.assertEqual(dec.rejection_rule, "MAX_ORDER_LOTS_BREACH")

        # Non-positive units fail closed
        zero_order = PreTradeOrderRequest(
            order_id="ORD-ZERO-UNITS",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            units=0,
            requested_price=300.0,
        )
        dec_zero = self.risk_engine.validate_order(zero_order, current_portfolio_gross_exposure=0.0)
        self.assertFalse(dec_zero.approved)

    # -------------------------------------------------------------------------
    # TEST 6: Pre-Trade RMS - Notional and Gross Exposure Limits
    # -------------------------------------------------------------------------
    def test_06_pre_trade_rms_max_notional_and_gross_exposure_limits(self) -> None:
        """Orders exceeding single notional cap or portfolio gross exposure cap fail closed."""
        # Single order notional breach: 10 lots = 150 units at Rs 20,000 = Rs 30,00,000 (> Rs 25,00,000)
        huge_order = PreTradeOrderRequest(
            order_id="ORD-HUGE-NOTIONAL",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            units=150,
            requested_price=20_000.0,
            theoretical_fair_price=20_000.0,
        )
        dec_notional = self.risk_engine.validate_order(huge_order, current_portfolio_gross_exposure=0.0)
        self.assertFalse(dec_notional.approved)
        self.assertEqual(dec_notional.rejection_rule, "MAX_ORDER_NOTIONAL_BREACH")

        # Portfolio gross exposure breach: current gross 95 Lakhs + order 10 Lakhs = 1.05 Cr (> 1.0 Cr cap)
        order_exposure = PreTradeOrderRequest(
            order_id="ORD-GROSS-BREACH",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            units=150,
            requested_price=6_000.0,  # 9 Lakhs
            theoretical_fair_price=6_000.0,
        )
        dec_gross = self.risk_engine.validate_order(
            order_exposure,
            current_portfolio_gross_exposure=9_500_000.0,
        )
        self.assertFalse(dec_gross.approved)
        self.assertEqual(dec_gross.rejection_rule, "MAX_GROSS_EXPOSURE_BREACH")

    # -------------------------------------------------------------------------
    # TEST 7: Pre-Trade RMS - Fat-Finger Price Deviation Band
    # -------------------------------------------------------------------------
    def test_07_pre_trade_rms_fat_finger_price_deviation(self) -> None:
        """Orders priced > 20% away from Black-Scholes theoretical value fail closed."""
        # Fair price = 400.0. Order price = 520.0 (+30% deviation)
        fat_finger_order = PreTradeOrderRequest(
            order_id="ORD-FAT-FINGER",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            units=75,
            requested_price=520.0,
            theoretical_fair_price=400.0,
        )
        dec = self.risk_engine.validate_order(fat_finger_order, current_portfolio_gross_exposure=0.0)
        self.assertFalse(dec.approved)
        self.assertEqual(dec.rejection_rule, "FAT_FINGER_PRICE_DEVIATION")

    # -------------------------------------------------------------------------
    # TEST 8: Margin Lockout Blocks New Positions
    # -------------------------------------------------------------------------
    def test_08_margin_lockout_blocks_new_positions(self) -> None:
        """Accounts under MARGIN_CALL or FORCE_LIQUIDATION are strictly barred from opening positions."""
        stressed_account = MarginAccountSnapshot(
            total_equity=800_000.0,
            available_cash=-50_000.0,
            initial_margin_required=900_000.0,
            maintenance_margin_required=850_000.0,
            margin_utilization=1.125,  # 112.5% utilization
            status=MarginStatus.MARGIN_CALL,
            margin_deficit=100_000.0,
        )
        self.assertTrue(stressed_account.is_locked_out)

        order = PreTradeOrderRequest(
            order_id="ORD-MARGIN-GATE",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            units=75,
            requested_price=300.0,
            theoretical_fair_price=300.0,
        )
        dec = self.risk_engine.validate_order(
            order,
            current_portfolio_gross_exposure=0.0,
            margin_account=stressed_account,
        )
        self.assertFalse(dec.approved)
        self.assertEqual(dec.rejection_rule, "MARGIN_LOCKOUT")

    # -------------------------------------------------------------------------
    # TEST 9: Drawdown Kill Switch Trips and Generates Cancellation Plan
    # -------------------------------------------------------------------------
    def test_09_drawdown_kill_switch_trips_and_generates_cancellation_plan(self) -> None:
        """Peak-to-trough drawdown >= 3.0% immediately engages kill switch and cancels working orders."""
        ks = PortfolioKillSwitch(
            initial_capital=1_000_000.0,
            max_drawdown_pct=0.03,  # 3.0%
            max_daily_loss_inr=50_000.0,
        )

        # Equity rises to 12,00,000 (new High Water Mark)
        plan = ks.update_equity(1_200_000.0, open_working_order_ids=["ORD-1", "ORD-2"])
        self.assertIsNone(plan)
        self.assertFalse(ks.is_engaged)
        self.assertEqual(ks.peak_equity, 1_200_000.0)

        # Equity drops to 11,60,000 (drawdown = (1.2M - 1.16M)/1.2M = 3.33% >= 3.0%)
        plan = ks.update_equity(1_160_000.0, open_working_order_ids=["ORD-1", "ORD-2"])
        self.assertIsNotNone(plan)
        self.assertTrue(ks.is_engaged)
        self.assertIn("ORD-1", plan.orders_to_cancel)
        self.assertIn("ORD-2", plan.orders_to_cancel)
        self.assertEqual(plan.action_required, "CANCEL_ALL_OPEN_ORDERS_AND_HALT_NEW_SUBMISSIONS")

        # Subsequent orders are rejected by risk engine
        test_order = PreTradeOrderRequest(
            order_id="ORD-SUBSEQUENT",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            units=15,
            requested_price=300.0,
            theoretical_fair_price=300.0,
        )
        dec = self.risk_engine.validate_order(
            test_order,
            current_portfolio_gross_exposure=0.0,
            kill_switch=ks,
        )
        self.assertFalse(dec.approved)
        self.assertEqual(dec.rejection_rule, "KILL_SWITCH_ACTIVE")

        # Administrative reset requires valid token (>= 8 chars)
        with self.assertRaises(ValueError):
            ks.reset("short")
        ks.reset("AUTH_ADMIN_RECOVERY_TOKEN_2026")
        self.assertFalse(ks.is_engaged)

    # -------------------------------------------------------------------------
    # TEST 10: Order Idempotency and Retry Deduplication
    # -------------------------------------------------------------------------
    def test_10_order_idempotency_and_retry_deduplication(self) -> None:
        """Resubmitting with the same idempotency_key returns existing order without duplicate execution."""
        initial_cash = self.trader.cash
        key = "IDEMP-TEST-RETRY-001"

        res1 = self.trader.execute_paper_order(
            idempotency_key=key,
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            units=15,
            market_price=300.0,
        )
        self.assertTrue(res1["success"])
        self.assertFalse(res1.get("deduplicated", False))
        cash_after_res1 = self.trader.cash
        self.assertLess(cash_after_res1, initial_cash)
        order_count_after_res1 = len(self.trader.executed_trades)

        # Retry with identical idempotency key
        res2 = self.trader.execute_paper_order(
            idempotency_key=key,
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            units=15,
            market_price=300.0,
        )
        self.assertTrue(res2["success"])
        self.assertTrue(res2["deduplicated"])
        # Cash, positions, and executed orders must NOT be duplicated
        self.assertEqual(self.trader.cash, cash_after_res1)
        self.assertEqual(len(self.trader.executed_trades), order_count_after_res1)

    # -------------------------------------------------------------------------
    # TEST 11: Insufficient Funds and Position Caps Fail Closed
    # -------------------------------------------------------------------------
    def test_11_insufficient_funds_and_position_caps_fail_closed(self) -> None:
        """Paper orders exceeding cash balance or position allocation limit fail closed."""
        # Set cash to low value
        self.trader.cash = 1_000.0
        res_cash = self.trader.execute_paper_order(
            idempotency_key="IDEMP-INSUFFICIENT-CASH",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            units=15,
            market_price=400.0,  # 15 * 400 = 6,000 > 1,000 cash
        )
        self.assertFalse(res_cash["success"])
        self.assertEqual(res_cash["reason"], "INSUFFICIENT_FUNDS")

        # Exceeds max position allocation (cap is 20% of 10 Lakhs = Rs 2,00,000)
        self.trader.cash = 1_000_000.0
        res_alloc = self.trader.execute_paper_order(
            idempotency_key="IDEMP-EXCEED-ALLOCATION",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            units=450,  # 30 lots
            market_price=600.0,  # 450 * 600 = Rs 2,70,000 > Rs 2,00,000 allocation cap
        )
        self.assertFalse(res_alloc["success"])
        self.assertEqual(res_alloc["reason"], "EXCEEDS_MAX_POSITION_ALLOCATION")

        # Sell order exceeding held inventory
        res_sell = self.trader.execute_paper_order(
            idempotency_key="IDEMP-SELL-EMPTY",
            symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            units=15,
            market_price=400.0,
        )
        self.assertFalse(res_sell["success"])
        self.assertEqual(res_sell["reason"], "INSUFFICIENT_POSITION")

    # -------------------------------------------------------------------------
    # TEST 12: Financial Brokerage Credentials Redacted and Quarantined
    # -------------------------------------------------------------------------
    def test_12_broker_credentials_redacted_and_never_leaked(self) -> None:
        """Brokerage API keys, client secrets, and TOTP authenticators are scrubbed."""
        snippet = (
            "kite_api_key = 'abcdef1234567890abcdef1234567890'\n"
            "zerodha_secret = 'xyz9876543210zyxwvutsrqponmlkjihg'\n"
            "upstox_token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9'\n"
            "totp_secret = 'JBSWY3DPEHPK3PXP'\n"
        )
        redacted, count = SecretRedactor.redact(snippet)
        self.assertGreaterEqual(count, 4)
        self.assertNotIn("abcdef1234567890", redacted)
        self.assertNotIn("xyz9876543210", redacted)
        self.assertNotIn("JBSWY3DPEHPK3PXP", redacted)
        self.assertIn("<REDACTED_BROKER_CREDENTIAL>", redacted)
        self.assertIn("<REDACTED_TOTP_SECRET>", redacted)


if __name__ == "__main__":
    unittest.main()
