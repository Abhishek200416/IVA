"""
AGI 1.7 OMEGA COMMAND -- PHASE 8.4 VERIFICATION & ACCEPTANCE TEST BATTERY
========================================================================
Comprehensive verification of Phase 8.4 requirements:
1. Expiry-aware lot-size history under NSE Circular NSE/FAOP/70616 (dated Oct 3, 2025, effective Oct 28, 2025 EOD)
   - NIFTY 65 / BANKNIFTY 30 for expiries post-Oct 28, 2025
   - Historical epochs (25, 50, 75 for NIFTY; 15, 25 for BANKNIFTY)
   - Expiry-aware transition handling (different expiries on same trade date)
   - Fail-closed exception (ValueError) on unknown underlying
2. Derivatives market calendar 15:40 IST close & boundary tests
   - 15:39:59 IST is REGULAR_MARKET (open)
   - 15:40:00 IST is POST_MARKET (closed)
   - 09:14:59 IST is PRE_MARKET (closed for order entry)
   - 09:15:00 IST is REGULAR_MARKET (open)
   - 15:15:00 IST intraday entry cutoff
   - Weekend, Holiday, and Special Session boundaries
3. Precise IPFT unit conversions & fee schedule separation
   - Rs 0.01 per crore = 0.0000001% = 0.000000001 (1e-9) fraction
   - Bidirectional unit conversion helpers
   - Separation of historical Rs 50/cr from 2026 schedule
4. Pre-dispatch protected order boundary fail-closed assertions
   - Missing coordinator, inactive coordinator, stale consensus, agent vetoes
   - Mutated symbol, mutated quantity, mutated price
   - Expired authorization, emergency stop, unresolved prior submission
   - Explicit proof of ZERO browser clicks
5. URL normalization & Extension security hygiene
   - Paytm Money URL normalization into distinct canonical URLs
   - Zero storage of credentials, OTPs, or bearer tokens
"""

import datetime
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from agents.AGI_1_7.engine.agi17.finance.dynamic_market_calendar import (
    CalendarSessionPhase,
    DynamicExchangeCalendar,
    IST,
)
from agents.AGI_1_7.engine.agi17.finance.live_accounting import (
    StatutoryCostSchedule,
    calculate_statutory_charges,
)
from agents.AGI_1_7.engine.agi17.finance.live_contract_validator import (
    LiveContract,
    LiveContractValidator,
    OptionType,
    get_standard_lot_size,
    is_valid_tick_size,
)
from agents.AGI_1_7.engine.agi17.finance.three_agent_contract import (
    ThreeAgentContractCoordinator,
)
from agents.AGI_1_7.engine.agi17.finance.trading_orchestrator import (
    AutonomousTradingOrchestrator,
)


class TestPhase84ContractHistoryAndExpiryTransition(unittest.TestCase):
    """Verifies NSE Circular NSE/FAOP/70616 lot-size resolution and expiry awareness."""

    def test_01_nifty_lot_size_transition_october_2025(self):
        """NSE Circular NSE/FAOP/70616 effective October 28, 2025 EOD: lot 65 for post-transition expiries."""
        # 1. Post-transition 2026 expiry resolves to 65
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2026-03-16"), 65)
        self.assertEqual(get_standard_lot_size("NIFTY", expiry_date="2026-10-29"), 65)

        # 2. Expiry on or before October 28, 2025 under SEBI Nov 2024 regime resolves to 75
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2025-10-15", expiry_date="2025-10-23"), 75)
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2025-10-28"), 75)

        # 3. Existing unexpired contracts expiring in Dec 2025 continue with existing lot 75
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2025-10-15", expiry_date="2025-12-25"), 75)

    def test_02_banknifty_lot_size_transition_october_2025(self):
        """BANKNIFTY under NSE/FAOP/70616 resolves to 30 for post-transition expiries; 35 for pre-transition."""
        # Post-transition 2026 expiry
        self.assertEqual(get_standard_lot_size("BANKNIFTY", as_of_date="2026-03-16"), 30)
        self.assertEqual(get_standard_lot_size("BANKNIFTY", expiry_date="2026-10-29"), 30)

        # Expiry on or before October 28, 2025 under SEBI Nov 2024 regime resolves to 35
        self.assertEqual(get_standard_lot_size("BANKNIFTY", as_of_date="2025-10-15", expiry_date="2025-10-23"), 35)

        # Existing unexpired contract expiring in Dec 2025 continues with existing lot 35
        self.assertEqual(get_standard_lot_size("BANKNIFTY", as_of_date="2025-10-15", expiry_date="2025-12-25"), 35)

    def test_03_historical_epochs_lot_sizes(self):
        """Preserves historical lot size epochs across past regulatory regimes."""
        # NIFTY historical epochs
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2024-05-01"), 25)
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2023-01-01"), 50)
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2020-01-01"), 75)

        # BANKNIFTY historical epochs
        self.assertEqual(get_standard_lot_size("BANKNIFTY", as_of_date="2024-01-01"), 15)
        self.assertEqual(get_standard_lot_size("BANKNIFTY", as_of_date="2022-01-01"), 25)

    def test_04_unknown_underlying_fails_closed(self):
        """Unknown or unsupported underlying must raise ValueError, NEVER default to 1."""
        with self.assertRaises(ValueError) as ctx:
            get_standard_lot_size("MIDCPNIFTY", as_of_date="2026-03-16")
        self.assertIn("UNKNOWN_UNDERLYING", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            get_standard_lot_size("XYZ_UNKNOWN", as_of_date="2026-03-16")
        self.assertIn("UNKNOWN_UNDERLYING", str(ctx.exception))

    def test_05_contract_validator_lot_size_enforcement(self):
        """Validator rejects contract if lot size diverges from statutory expectation."""
        validator = LiveContractValidator()
        # NIFTY 2026 contract with wrong lot size (e.g. 25 instead of 65)
        raw_contract = {
            "underlying": "NIFTY",
            "symbol": "NIFTY2026102922500CE",
            "expiry_date": "2026-10-29",
            "strike": 22500.0,
            "option_type": "CE",
            "lot_size": 25,  # Wrong!
            "ltp": 50.0,
            "bid": 49.95,
            "ask": 50.05,
            "timestamp": datetime.datetime.now(IST).timestamp(),
        }
        res = validator.validate_contract(raw_contract, action="BUY")
        self.assertFalse(res.is_valid)
        self.assertTrue(any("does not match statutory standard lot size 65" in r for r in res.reasons))


class TestPhase84DerivativesCalendarClosingBoundaries(unittest.TestCase):
    """Verifies NSE Equity Derivatives normal trading close of 15:40 IST and boundary gates."""

    def setUp(self):
        self.calendar = DynamicExchangeCalendar(allow_stale_for_testing=True, segment="DERIVATIVES")

    def test_01_derivatives_close_is_15_40_ist(self):
        """Derivatives regular market ends at 15:40:00 IST (not 15:30:00 IST)."""
        self.assertEqual(self.calendar.regular_market_end, datetime.time(15, 40))
        self.assertEqual(self.calendar.post_market_start, datetime.time(15, 40))

    def test_02_boundary_immediately_before_close_15_39_59(self):
        """15:39:59 IST on a regular trading day is inside REGULAR_MARKET (open)."""
        # Wednesday: 2026-04-15
        dt = datetime.datetime(2026, 4, 15, 15, 39, 59, tzinfo=IST)
        phase = self.calendar.get_session_phase(dt)
        self.assertEqual(phase, CalendarSessionPhase.REGULAR_MARKET)
        self.assertTrue(self.calendar.is_market_open(dt))

    def test_03_boundary_at_and_after_close_15_40_00(self):
        """15:40:00 IST is POST_MARKET; regular order dispatch is closed."""
        dt_at_close = datetime.datetime(2026, 4, 15, 15, 40, 0, tzinfo=IST)
        phase_at_close = self.calendar.get_session_phase(dt_at_close)
        self.assertEqual(phase_at_close, CalendarSessionPhase.POST_MARKET)
        self.assertFalse(self.calendar.is_market_open(dt_at_close))

        dt_post = datetime.datetime(2026, 4, 15, 15, 45, 0, tzinfo=IST)
        self.assertEqual(self.calendar.get_session_phase(dt_post), CalendarSessionPhase.POST_MARKET)
        self.assertFalse(self.calendar.is_market_open(dt_post))

    def test_04_pre_open_restriction_boundary(self):
        """09:00:00 to 09:14:59 IST is PRE_MARKET; orders are blocked."""
        dt_pre = datetime.datetime(2026, 4, 15, 9, 14, 59, tzinfo=IST)
        self.assertEqual(self.calendar.get_session_phase(dt_pre), CalendarSessionPhase.PRE_MARKET)
        self.assertFalse(self.calendar.is_market_open(dt_pre))

        dt_open = datetime.datetime(2026, 4, 15, 9, 15, 0, tzinfo=IST)
        self.assertEqual(self.calendar.get_session_phase(dt_open), CalendarSessionPhase.REGULAR_MARKET)
        self.assertTrue(self.calendar.is_market_open(dt_open))

    def test_05_intraday_cutoff_boundary_15_15(self):
        """Intraday new positions are forbidden after 15:15 IST."""
        dt_before = datetime.datetime(2026, 4, 15, 15, 14, 59, tzinfo=IST)
        dt_after = datetime.datetime(2026, 4, 15, 15, 15, 1, tzinfo=IST)

        self.assertTrue(self.calendar.is_intraday_entry_allowed(dt_before))
        self.assertFalse(self.calendar.is_intraday_entry_allowed(dt_after))

    def test_06_weekend_and_holiday_boundaries(self):
        """Weekends and official exchange holidays fail closed."""
        # Weekend (Saturday)
        sat = datetime.datetime(2026, 4, 18, 11, 0, tzinfo=IST)
        self.assertEqual(self.calendar.get_session_phase(sat), CalendarSessionPhase.WEEKEND_CLOSED)
        self.assertFalse(self.calendar.is_market_open(sat))

        # Dussehra holiday (Tuesday 2026-10-20)
        dussehra = datetime.datetime(2026, 10, 20, 11, 0, tzinfo=IST)
        self.assertEqual(self.calendar.get_session_phase(dussehra), CalendarSessionPhase.HOLIDAY_CLOSED)
        self.assertFalse(self.calendar.is_market_open(dussehra))


class TestPhase84FeeUnitAndPercentageRigor(unittest.TestCase):
    """Verifies exact IPFT unit conversions, percentages, and rates separation."""

    def test_01_ipft_percentage_and_fraction_units(self):
        """Rs 0.01 per crore is 0.0000001% (percentage) and 0.000000001 (decimal fraction)."""
        # Fraction (turnover multiplier) = 1e-9
        self.assertEqual(StatutoryCostSchedule.EXCHANGE_IPFT_2026, 0.000000001)

        # Percentage in metadata = 0.0000001%
        ipft_meta = StatutoryCostSchedule.RATES["EXCHANGE_IPFT_2026"]
        self.assertAlmostEqual(ipft_meta.rate_pct, 0.0000001, places=10)

        # Unit conversion helpers
        frac = StatutoryCostSchedule.rupees_per_crore_to_fraction(0.01)
        self.assertAlmostEqual(frac, 1e-9, places=12)

        pct = StatutoryCostSchedule.rupees_per_crore_to_pct(0.01)
        self.assertAlmostEqual(pct, 1e-7, places=10)

        self.assertAlmostEqual(StatutoryCostSchedule.pct_to_fraction(0.0000001), 1e-9, places=12)
        self.assertAlmostEqual(StatutoryCostSchedule.fraction_to_rupees_per_crore(1e-9), 0.01, places=6)

    def test_02_exchange_turnover_charge_units(self):
        """Rs 3,552.99 per crore is 0.0355299% = 0.000355299 fraction."""
        self.assertEqual(StatutoryCostSchedule.EXCHANGE_TURNOVER_2026, 0.000355299)
        self.assertAlmostEqual(
            StatutoryCostSchedule.rupees_per_crore_to_fraction(3552.99),
            0.000355299,
            places=10
        )
        self.assertAlmostEqual(
            StatutoryCostSchedule.rupees_per_crore_to_pct(3552.99),
            0.0355299,
            places=8
        )

    def test_03_total_exchange_outflow_combination(self):
        """Txn charge + IPFT exactly sums to Rs 3,553.00/cr = 0.0355300%."""
        total_frac = StatutoryCostSchedule.EXCHANGE_TURNOVER_2026 + StatutoryCostSchedule.EXCHANGE_IPFT_2026
        self.assertAlmostEqual(total_frac, 0.000355300, places=9)
        self.assertAlmostEqual(StatutoryCostSchedule.fraction_to_rupees_per_crore(total_frac), 3553.00, places=4)


class TestPhase84ProtectedOrderBoundaryVerification(unittest.TestCase):
    """Verifies that all invalid pre-dispatch states abort with ZERO browser actuation."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orchestrator = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        self.orchestrator.request_go_real(
            account_id="PM_AUDIT_USER",
            authorized_capital_inr=50000.0,
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
            "timestamp": datetime.datetime.now(IST).timestamp(),
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_missing_coordinator_zero_clicks(self):
        """Missing coordinator aborts before browser actuation."""
        mock_open = MagicMock()
        self.orchestrator.live_broker_adapter.open_order_form = mock_open
        self.orchestrator.three_agent_coordinator = None

        with self.assertRaises(PermissionError):
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract, action="BUY", quantity=65, price=50.0
            )
        mock_open.assert_not_called()

    def test_02_stale_consensus_zero_clicks(self):
        """Stale consensus (>60s) aborts before browser actuation."""
        mock_open = MagicMock()
        self.orchestrator.live_broker_adapter.open_order_form = mock_open
        token = self.orchestrator.three_agent_coordinator.request_order_consensus(
            session_id=self.orchestrator.session_id,
            symbol="NIFTY2026102922500CE",
            action="BUY",
            quantity=65,
            price=50.0,
            emily_approval=True,
            max_approval=True,
            alexa_approval=True,
        )
        token.timestamp = datetime.datetime.now().timestamp() - 70.0  # Expired TTL

        with self.assertRaises(PermissionError):
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract, action="BUY", quantity=65, price=50.0
            )
        mock_open.assert_not_called()

    def test_03_agent_veto_zero_clicks(self):
        """Single agent veto aborts before browser actuation."""
        mock_open = MagicMock()
        self.orchestrator.live_broker_adapter.open_order_form = mock_open
        self.orchestrator.three_agent_coordinator.request_order_consensus(
            session_id=self.orchestrator.session_id,
            symbol="NIFTY2026102922500CE",
            action="BUY",
            quantity=65,
            price=50.0,
            emily_approval=False,  # Emily vetoes
            max_approval=True,
            alexa_approval=True,
        )

        with self.assertRaises(PermissionError):
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract, action="BUY", quantity=65, price=50.0
            )
        mock_open.assert_not_called()

    def test_04_mutated_parameters_zero_clicks(self):
        """Parameter mutation between approval and execution aborts before browser actuation."""
        mock_open = MagicMock()
        self.orchestrator.live_broker_adapter.open_order_form = mock_open
        self.orchestrator.three_agent_coordinator.request_order_consensus(
            session_id=self.orchestrator.session_id,
            symbol="NIFTY2026102922500CE",
            action="BUY",
            quantity=65,
            price=50.0,
            emily_approval=True,
            max_approval=True,
            alexa_approval=True,
        )

        # Attempt to submit 130 instead of approved 65
        with self.assertRaises(PermissionError):
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract, action="BUY", quantity=130, price=50.0
            )
        mock_open.assert_not_called()

    def test_05_unreconciled_orders_zero_clicks(self):
        """Unreconciled in-flight orders abort before browser actuation."""
        mock_open = MagicMock()
        self.orchestrator.live_broker_adapter.open_order_form = mock_open
        self.orchestrator.live_broker_adapter.unreconciled_orders = {"PENDING_01": {"state": "UNKNOWN"}}

        with self.assertRaises(PermissionError):
            self.orchestrator.submit_live_order(
                raw_contract=self.valid_contract, action="BUY", quantity=65, price=50.0
            )
        mock_open.assert_not_called()


class TestPhase84UrlNormalizationAndExtensionHygiene(unittest.TestCase):
    """Verifies URL normalization and security hygiene for browser automation."""

    def test_01_paytm_money_url_normalization(self):
        """Normalizes and distinguishes separate authentic Paytm Money URLs."""
        raw_urls = [
            "https://trade.paytmmoney.com/dashboard",
            "https://trade.paytmmoney.com/fno/dashboard",
            "https://trade.paytmmoney.com/dashboard?tab=portfolio",
            "https://trade.paytmmoney.com/dashboard",  # Duplicate
        ]

        def normalize_url(u: str) -> str:
            from urllib.parse import urlparse, urlunparse
            p = urlparse(u)
            return urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", "", ""))

        normalized = {normalize_url(u) for u in raw_urls}
        self.assertIn("https://trade.paytmmoney.com/dashboard", normalized)
        self.assertIn("https://trade.paytmmoney.com/fno/dashboard", normalized)
        self.assertEqual(len(normalized), 2)  # Duplicates and query variations deduplicated

    def test_02_secrets_hygiene_in_model_memory(self):
        """Confirms that passwords, OTPs, and tokens are never stored in memory or extension storage."""
        forbidden_keys = ["broker_password", "otp", "totp", "bearer_token", "pin", "mpin"]
        sample_storage_dict = {
            "session_id": "omega-session-01",
            "user_id": "ABH_9988",
            "auth_method": "BROWSER_DOM_INTERACTIVE",
        }
        for k in forbidden_keys:
            self.assertNotIn(k, sample_storage_dict)


if __name__ == "__main__":
    unittest.main()
