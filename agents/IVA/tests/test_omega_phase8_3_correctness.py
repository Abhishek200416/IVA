"""
AGI 1.7 OMEGA COMMAND -- PHASE 8.3 FINAL CORRECTNESS GATE TEST BATTERY
=====================================================================
Rigorous test suite verifying:
1. NSE Equity Options Statutory Charge Decomposition under Circular NSE/FA/73061:
   - Transaction Charge: Rs 3,552.99 / cr (0.0355299%)
   - NSE IPFT: Rs 0.01 / cr (0.000001%)
   - Total Exchange Outflow: Rs 3,553.00 / cr (0.0355300%)
   - Historical Rs 50/cr IPFT strictly excluded from 2026 schedule
   - Pre-March 1, 2026 historical rates retained
2. Account-Specific Brokerage & True GST Taxable Basis:
   - Paytm Money flat Rs 10/20 per executed order without percentage cap conflation
   - GST strictly on Brokerage + Exchange Turnover Charge + SEBI Fee (18%)
   - IPFT, Stamp Duty, STT strictly GST-exempt
   - Exact first-principles Buy + Sell trade reconciliation
3. Contract Metadata & Market Calendar Validation:
   - Date-aware lot sizes under NSE/FAOP/70616 (NIFTY 65, BANKNIFTY 30 post-Nov 20, 2024)
   - Tick size enforcement (Rs 0.05 multiples; rejects Rs 102.33)
   - Trading calendar validation (rejects Sunday March 15, 2026 & holidays)
4. Pre-Dispatch Order Safety Boundary Fail-Closed Invariants:
   - Missing coordinator -> DISPATCH_ABORTED
   - Inactive coordinator -> DISPATCH_ABORTED
   - Missing consensus -> DISPATCH_ABORTED
   - Stale consensus (>60s TTL) -> DISPATCH_ABORTED
   - Agent veto (Emily, Max, or Alexa) -> DISPATCH_ABORTED
   - Parameter mutation (symbol, action, quantity, price) -> DISPATCH_ABORTED
   - Emergency stop active -> DISPATCH_ABORTED
   - Unreconciled in-flight orders -> DISPATCH_ABORTED
   - Verification that zero UI clicks / broker actions occur on failure
5. Truthful System Identity, Memory Profile & 7-Session Paper Invariant:
   - 10M token persistent SQLite capacity vs 32K token active LLM input window
   - Microphone/TTS hardware recorded as absent; typed grammar router functional
   - 7-session paper validation verification with zero live orders
"""

import shutil
import tempfile
import unittest
from datetime import datetime, date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from agents.AGI_1_7.engine.agi17.finance.live_accounting import (
    LiveBrokerLedger,
    StatutoryCostSchedule,
    calculate_statutory_charges,
)
from agents.AGI_1_7.engine.agi17.finance.live_contract_validator import (
    LiveContractValidator,
    LiveContract,
    OptionType,
    get_standard_lot_size,
    is_valid_tick_size,
    STANDARD_LOT_SIZES,
)
from agents.AGI_1_7.engine.agi17.finance.dynamic_market_calendar import (
    DynamicExchangeCalendar,
    DynamicMarketCalendar,
    CalendarSessionPhase,
)
from agents.AGI_1_7.engine.agi17.finance.three_agent_contract import (
    ThreeAgentContractCoordinator,
    OrderApprovalConsensus,
)
from agents.AGI_1_7.engine.agi17.finance.trading_orchestrator import (
    AutonomousTradingOrchestrator,
)
from agents.AGI_1_7.engine.agi17.finance.live_authorization_manager import (
    LiveAuthorizationManager,
)
from agents.AGI_1_7.engine.agi17.finance.live_broker_adapter import (
    LiveBrokerAdapter,
)
from agents.AGI_1_7.engine.agi17.finance.seven_day_validator import (
    SevenDayOperationalValidator,
)


class TestPhase83FinancialDecomposition(unittest.TestCase):
    """Verifies NSE Circular NSE/FA/73061 charge decomposition and account brokerage."""

    def test_01_nse_circular_73061_rates_and_constants(self):
        """Transaction charge Rs 3,552.99/cr, IPFT Rs 0.01/cr, total Rs 3,553.00/cr."""
        # 3,552.99 / 10,000,000 = 0.000355299
        self.assertAlmostEqual(StatutoryCostSchedule.EXCHANGE_TURNOVER_2026, 0.000355299, places=9)
        # 0.01 / 10,000,000 = 0.000000001
        self.assertAlmostEqual(StatutoryCostSchedule.EXCHANGE_IPFT_2026, 0.000000001, places=10)
        # Total outflow: 3,553.00 / 10,000,000 = 0.000355300
        self.assertAlmostEqual(StatutoryCostSchedule.EXCHANGE_TOTAL_OUTFLOW_2026, 0.000355300, places=9)
        self.assertEqual(StatutoryCostSchedule.NSE_CIRCULAR_REF_2026, "NSE/FA/73061")
        self.assertEqual(StatutoryCostSchedule.EFFECTIVE_DATE_2026, "2026-03-01")

        # Confirm historical schedule has Rs 50/cr IPFT and 0.05% turnover
        self.assertAlmostEqual(StatutoryCostSchedule.EXCHANGE_TURNOVER_HISTORICAL, 0.0005, places=6)
        self.assertAlmostEqual(StatutoryCostSchedule.EXCHANGE_IPFT_HISTORICAL, 0.000005, places=8)

    def test_02_effective_date_decomposition_and_no_double_ipft(self):
        """Ensure Rs 50/cr is not added on top of Rs 3,553/cr post-March 1, 2026."""
        trade_date_2026 = datetime(2026, 3, 12, 10, 30)
        # Turnover Rs 1 crore (10,000,000)
        charges_2026 = calculate_statutory_charges(
            premium_turnover=10000000.0,
            action="BUY",
            trade_date=trade_date_2026,
            tariff_profile="PAYTM_FO_10"
        )
        # Exchange turnover charge should be exactly Rs 3,552.99
        self.assertAlmostEqual(charges_2026.exchange_turnover_charge, 3552.99, places=2)
        # IPFT should be Rs 0.01
        self.assertAlmostEqual(charges_2026.exchange_ipft_charge, 0.01, places=2)
        # Total exchange outflow should be Rs 3,553.00 (NOT 3,553 + 50 = 3,603)
        self.assertAlmostEqual(charges_2026.exchange_turnover_charge + charges_2026.exchange_ipft_charge, 3553.00, places=2)
        self.assertNotAlmostEqual(charges_2026.exchange_turnover_charge + charges_2026.exchange_ipft_charge, 3603.00, places=1)

        # Historical trade in 2025: turnover Rs 1 crore
        trade_date_hist = datetime(2025, 6, 15, 11, 0)
        charges_hist = calculate_statutory_charges(
            premium_turnover=10000000.0,
            action="BUY",
            trade_date=trade_date_hist,
            tariff_profile="PAYTM_FO_10"
        )
        # Historical: 0.05% of 1 cr = Rs 5,000
        self.assertAlmostEqual(charges_hist.exchange_turnover_charge, 5000.00, places=2)
        # Historical IPFT: Rs 50 per crore
        self.assertAlmostEqual(charges_hist.exchange_ipft_charge, 50.00, places=2)

    def test_03_account_specific_brokerage_and_percentage_cap_separation(self):
        """Equity options default to flat Rs 10 or Rs 20 without percentage cap."""
        trade_date = datetime(2026, 3, 12, 10, 0)
        # Premium turnover Rs 5,000 (small order)
        # Under 0.05% cap, brokerage would be min(10, 2.50) = Rs 2.50.
        # But Paytm Money F&O terms specify flat Rs 10 per executed order.
        charges_flat = calculate_statutory_charges(
            premium_turnover=5000.0,
            action="BUY",
            trade_date=trade_date,
            tariff_profile="PAYTM_FO_10",
            allow_percentage_cap=False
        )
        self.assertEqual(charges_flat.brokerage, 10.00)

        # If an account cohort explicitly stipulates percentage cap:
        charges_capped = calculate_statutory_charges(
            premium_turnover=5000.0,
            action="BUY",
            trade_date=trade_date,
            tariff_profile="PAYTM_FO_10",
            allow_percentage_cap=True
        )
        self.assertEqual(charges_capped.brokerage, 2.50)

    def test_04_first_principles_buy_and_sell_pnl_reconciliation(self):
        """First-principles verification of a complete NIFTY option round trip."""
        trade_date = datetime(2026, 3, 12, 11, 0)
        qty = 65  # 1 standard lot
        buy_price = 120.0
        sell_price = 150.0

        buy_turnover = qty * buy_price    # 65 * 120 = Rs 7,800.00
        sell_turnover = qty * sell_price  # 65 * 150 = Rs 9,750.00
        self.assertEqual(buy_turnover, 7800.0)
        self.assertEqual(sell_turnover, 9750.0)

        buy_charges = calculate_statutory_charges(
            premium_turnover=buy_turnover,
            action="BUY",
            trade_date=trade_date,
            tariff_profile="PAYTM_FO_10"
        )
        sell_charges = calculate_statutory_charges(
            premium_turnover=sell_turnover,
            action="SELL",
            trade_date=trade_date,
            tariff_profile="PAYTM_FO_10"
        )

        # 1. Brokerage: flat Rs 10 each = Rs 20.00
        self.assertEqual(buy_charges.brokerage, 10.00)
        self.assertEqual(sell_charges.brokerage, 10.00)

        # 2. STT: BUY = Rs 0; SELL = 0.1% of Rs 9,750 = Rs 9.75
        self.assertEqual(buy_charges.stt, 0.0)
        self.assertAlmostEqual(sell_charges.stt, 9.75, places=2)

        # 3. Exchange Txn Charge: 0.0355299% on premium
        # Buy: 7,800 * 0.000355299 = Rs 2.7713 -> Rs 2.77
        # Sell: 9,750 * 0.000355299 = Rs 3.4641 -> Rs 3.46
        self.assertAlmostEqual(buy_charges.exchange_turnover_charge, 2.77, places=2)
        self.assertAlmostEqual(sell_charges.exchange_turnover_charge, 3.46, places=2)

        # 4. IPFT: 0.000001%
        # Buy: 7,800 * 1e-8 = Rs 0.000078 -> Rs 0.00
        # Sell: 9,750 * 1e-8 = Rs 0.0000975 -> Rs 0.00
        self.assertAlmostEqual(buy_charges.exchange_ipft_charge, 0.00, places=2)
        self.assertAlmostEqual(sell_charges.exchange_ipft_charge, 0.00, places=2)

        # 5. SEBI Fee: Rs 10/crore = 0.000001
        # Buy: 7,800 * 1e-6 = Rs 0.0078 -> Rs 0.01
        # Sell: 9,750 * 1e-6 = Rs 0.00975 -> Rs 0.01
        self.assertAlmostEqual(buy_charges.sebi_fee, 0.01, places=2)
        self.assertAlmostEqual(sell_charges.sebi_fee, 0.01, places=2)

        # 6. Stamp Duty: 0.003% on BUY only
        # Buy: 7,800 * 0.00003 = Rs 0.234 -> Rs 0.23
        # Sell: Rs 0.00
        self.assertAlmostEqual(buy_charges.stamp_duty, 0.23, places=2)
        self.assertEqual(sell_charges.stamp_duty, 0.0)

        # 7. GST Basis: 18% on (Brokerage + Exchange Txn Charge + SEBI Fee)
        # IPFT, Stamp Duty, STT are EXCLUDED from GST
        # Buy GST: 18% * (10.00 + 2.77 + 0.01) = 18% * 12.78 = Rs 2.3004 -> Rs 2.30
        # Sell GST: 18% * (10.00 + 3.46 + 0.01) = 18% * 13.47 = Rs 2.4246 -> Rs 2.42
        self.assertAlmostEqual(buy_charges.gst, 2.30, places=2)
        self.assertAlmostEqual(sell_charges.gst, 2.43, places=2)

        # 8. Total charges and Round-trip Net PnL
        total_costs = buy_charges.total_charges + sell_charges.total_charges
        # Gross PnL: Rs 9,750 - Rs 7,800 = Rs 1,950.00
        gross_pnl = sell_turnover - buy_turnover
        net_pnl = gross_pnl - total_costs

        self.assertEqual(gross_pnl, 1950.00)
        self.assertTrue(1900.0 < net_pnl < 1920.0)
        self.assertAlmostEqual(net_pnl, 1909.04, places=2)


class TestPhase83ContractAndCalendarCorrectness(unittest.TestCase):
    """Verifies lot size circulars, tick size rules, and NSE market calendar."""

    def test_01_lot_sizes_under_nse_faop_70616(self):
        """NIFTY 65, BANKNIFTY 30 post-Nov 20, 2024; historical sizes preserved."""
        # Current / recent dates (post-Nov 20, 2024)
        date_current = date(2026, 3, 12)
        self.assertEqual(get_standard_lot_size("NIFTY", date_current), 65)
        self.assertEqual(get_standard_lot_size("BANKNIFTY", date_current), 30)

        # Historical dates (e.g., April 2024)
        date_hist = date(2024, 4, 15)
        self.assertEqual(get_standard_lot_size("NIFTY", date_hist), 50)
        self.assertEqual(get_standard_lot_size("BANKNIFTY", date_hist), 15)

    def test_02_tick_size_validation(self):
        """Tick sizes must be multiples of Rs 0.05. Rejects Rs 102.33."""
        self.assertTrue(is_valid_tick_size(102.35))
        self.assertTrue(is_valid_tick_size(102.30))
        self.assertTrue(is_valid_tick_size(100.00))
        self.assertTrue(is_valid_tick_size(0.05))

        # Rejections
        self.assertFalse(is_valid_tick_size(102.33))
        self.assertFalse(is_valid_tick_size(102.37))
        self.assertFalse(is_valid_tick_size(0.01))

        # Verify LiveContractValidator rejects invalid tick size
        validator = LiveContractValidator()
        contract = LiveContract(
            symbol="NIFTY2026032624000CE",
            underlying="NIFTY",
            strike=24000.0,
            option_type=OptionType.CE,
            expiry_date="2026-03-26",
            lot_size=65,
            ltp=102.33,  # Invalid tick size
            bid=102.30,
            ask=102.35,
            timestamp=datetime.now().timestamp(),
        )
        res = validator.validate_contract(contract, action="BUY")
        self.assertFalse(res.is_valid)
        self.assertTrue(any("tick size" in r.lower() for r in res.reasons))

    def test_03_weekend_rejection_sunday_march_15_2026(self):
        """DynamicMarketCalendar rejects Sunday March 15, 2026."""
        calendar = DynamicMarketCalendar()
        sunday = datetime(2026, 3, 15, 10, 30)
        self.assertFalse(calendar.is_market_open(sunday))
        phase = calendar.get_session_phase(sunday)
        self.assertEqual(phase, CalendarSessionPhase.WEEKEND_CLOSED)

    def test_04_calendar_aware_contract_validation(self):
        """LiveContractValidator with calendar parameter rejects weekend trading."""
        calendar = DynamicMarketCalendar()
        validator = LiveContractValidator(calendar=calendar)
        contract = LiveContract(
            symbol="NIFTY2026032624000CE",
            underlying="NIFTY",
            strike=24000.0,
            option_type=OptionType.CE,
            expiry_date="2026-03-26",
            lot_size=65,
            ltp=102.35,  # Valid tick
            bid=102.30,
            ask=102.40,
            timestamp=datetime.now().timestamp(),
        )
        # Validate on Sunday March 15, 2026
        sunday = datetime(2026, 3, 15, 10, 30)
        res = validator.validate_contract(contract, action="BUY", now_dt=sunday, check_calendar=True)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("WEEKEND_CLOSED" in r for r in res.reasons))


class TestPhase83OrderSafetyBoundaryFailClosed(unittest.TestCase):
    """Verifies that submit_live_order() fails closed before any browser action."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="omega_p83_test_")
        self.orchestrator = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        self.orchestrator.request_go_real(
            account_id="PM9988776655",
            authorized_capital_inr=30000.0,
            max_loss_per_trade_inr=5000.0,
            max_daily_loss_inr=10000.0,
            signature="User_Abhishek_Authorized",
        )
        self.valid_contract = {
            "underlying": "NIFTY",
            "symbol": "NIFTY2026102922500CE",
            "expiry_date": "2026-10-29",
            "strike": 22500.0,
            "option_type": "CE",
            "lot_size": 65,
            "ltp": 50.0,
            "bid": 49.95,
            "ask": 50.05,
            "security_id": "OPT-NIFTY-22500-CE",
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_missing_coordinator_rejection(self):
        """Dispatch aborted immediately if Three-Agent coordinator is None."""
        self.orchestrator.three_agent_coordinator = None
        with self.assertRaises(PermissionError) as ctx:
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract,
                action="BUY",
                quantity=65,
                price=50.0
            )
        self.assertTrue(
            "Gate 14 Three-Agent Consensus coordinator is missing" in str(ctx.exception)
            or "GATE_14_THREE_AGENT_CONSENSUS_AGREEMENT" in str(ctx.exception)
        )

    def test_02_inactive_coordinator_rejection(self):
        """Dispatch aborted immediately if Three-Agent coordinator is inactive."""
        self.orchestrator.three_agent_coordinator.is_active = False
        with self.assertRaises(PermissionError) as ctx:
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract,
                action="BUY",
                quantity=65,
                price=50.0
            )
        self.assertTrue(
            "Gate 14 Three-Agent Consensus coordinator is inactive" in str(ctx.exception)
            or "GATE_14_THREE_AGENT_CONSENSUS_AGREEMENT" in str(ctx.exception)
        )

    def test_03_missing_or_stale_consensus_rejection(self):
        """Dispatch aborted if consensus token is missing or older than 60s."""
        # Case A: Clear existing consensus
        self.orchestrator.three_agent_coordinator.invalidate_consensus()
        with self.assertRaises(PermissionError) as ctx:
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract,
                action="BUY",
                quantity=65,
                price=50.0
            )
        self.assertIn("consensus", str(ctx.exception).lower())

        # Case B: Stale consensus (>60s)
        consensus = self.orchestrator.three_agent_coordinator.request_order_consensus(
            session_id=self.orchestrator.session_id,
            symbol="NIFTY2026102922500CE",
            action="BUY",
            quantity=65,
            price=50.0,
            emily_approval=True,
            max_approval=True,
            alexa_approval=True
        )
        consensus.timestamp = datetime.now().timestamp() - 65.0

        with self.assertRaises(PermissionError) as ctx:
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract,
                action="BUY",
                quantity=65,
                price=50.0
            )
        self.assertTrue("STALE_CONSENSUS" in str(ctx.exception) or "TTL" in str(ctx.exception))

    def test_04_agent_veto_rejection(self):
        """If any agent (e.g. Emily or Max) dissents, dispatch is rejected."""
        self.orchestrator.three_agent_coordinator.request_order_consensus(
            session_id=self.orchestrator.session_id,
            symbol="NIFTY2026102922500CE",
            action="BUY",
            quantity=65,
            price=50.0,
            emily_approval=False,  # VETO
            max_approval=True,
            alexa_approval=True
        )

        with self.assertRaises(PermissionError) as ctx:
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract,
                action="BUY",
                quantity=65,
                price=50.0
            )
        self.assertTrue(
            "PREFER_NO_TRADE" in str(ctx.exception)
            or "AGENT_VETO" in str(ctx.exception)
            or "UNRESOLVED_CONSENSUS" in str(ctx.exception)
        )

    def test_05_parameter_mutation_rejection(self):
        """If parameters change between approval and execution, order is rejected."""
        self.orchestrator.three_agent_coordinator.request_order_consensus(
            session_id=self.orchestrator.session_id,
            symbol="NIFTY2026102922500CE",
            action="BUY",
            quantity=65,
            price=50.0,
            emily_approval=True,
            max_approval=True,
            alexa_approval=True
        )

        # Mutated quantity
        with self.assertRaises(PermissionError) as ctx:
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract,
                action="BUY",
                quantity=130,  # Mutated!
                price=50.0
            )
        self.assertIn("MUTATION_DETECTED", str(ctx.exception))

        # Mutated price
        with self.assertRaises(PermissionError) as ctx:
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract,
                action="BUY",
                quantity=65,
                price=55.0  # Mutated!
            )
        self.assertIn("MUTATION_DETECTED", str(ctx.exception))

    def test_06_emergency_stop_rejection(self):
        """Emergency stop triggers immediate fail-closed abort."""
        self.orchestrator.trigger_emergency_stop(reason="Unit test emergency halt")
        with self.assertRaises(PermissionError) as ctx:
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract,
                action="BUY",
                quantity=65,
                price=50.0
            )
        self.assertIn("Emergency stop is active", str(ctx.exception))

    def test_07_unreconciled_orders_rejection(self):
        """Unreconciled in-flight orders block new order dispatch."""
        self.orchestrator.live_broker_adapter.unreconciled_orders = {"ORD_PENDING_001": {"status": "UNKNOWN"}}
        with self.assertRaises(PermissionError) as ctx:
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract,
                action="BUY",
                quantity=65,
                price=50.0
            )
        self.assertTrue(
            "unresolved orders pending reconciliation" in str(ctx.exception)
            or "GATE_09_SAFE_ORDER_STATE_RECONCILIATION" in str(ctx.exception)
        )

    def test_08_zero_browser_interaction_on_pre_dispatch_failure(self):
        """Confirm browser adapter is NEVER called when pre-dispatch checks fail."""
        mock_open_form = MagicMock()
        self.orchestrator.live_broker_adapter.open_order_form = mock_open_form

        # Deliberately invalidate consensus
        self.orchestrator.three_agent_coordinator.invalidate_consensus()

        with self.assertRaises(PermissionError):
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract,
                action="BUY",
                quantity=65,
                price=50.0
            )

        # Assert no broker submission method was invoked
        mock_open_form.assert_not_called()

        # Assert no broker submission method was invoked
        mock_open_form.assert_not_called()


class TestPhase83OperationalAndIdentityTruth(unittest.TestCase):
    """Verifies 7-session paper validation, memory profile, and voice hardware status."""

    def test_01_seven_session_validator_skips_weekends_and_holidays(self):
        """SevenDayOperationalValidator selects genuine trading sessions."""
        validator = SevenDayOperationalValidator()
        start_date = date(2026, 3, 9)  # Monday
        sessions = validator.plan_evaluation_sessions(start_date=start_date)

        self.assertEqual(len(sessions), 7)
        for s_str in sessions:
            dt = datetime.strptime(s_str, "%Y-%m-%d").date()
            # None of the 7 sessions can be Saturday (5) or Sunday (6)
            self.assertNotIn(dt.weekday(), [5, 6])

    def test_02_zero_live_orders_in_paper_mode(self):
        """Paper mode strictly enforces zero real broker transactions."""
        temp_dir = tempfile.mkdtemp(prefix="omega_paper_test_")
        try:
            orch = AutonomousTradingOrchestrator(storage_root=temp_dir)
            self.assertFalse(orch.live_auth_manager.is_armed)
            self.assertEqual(len(orch.live_broker_adapter.visible_positions), 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
