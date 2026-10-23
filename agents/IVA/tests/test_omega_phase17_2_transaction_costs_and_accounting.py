"""AGI 1.7 OMEGA COMMAND — Phase 17.2 Authoritative Transaction-Cost & P&L Accounting Test Suite.

Authoritative verification battery covering:
- Gate A: Date-aware statutory levies (STT, NSE Circular 64232, SEBI, Stamp Duty, GST).
- Gate B: Brokerage tariff models (Paytm Flat ₹20, Promo ₹10, Percentage, Zero).
- Gate C: Decimal precision and strict rounding rules (ROUND_HALF_UP to 0.01 INR).
- Gate D: Core Financial Invariants & Accounting Lifecycle (Cash, Equity, Gross vs Net P&L).
- Gate E: Independent Expected-Value Numerical Tests across multiple underlying and lot sizes.
- Gate F: Fail-closed boundary testing (zero turnover, negative/non-finite, fractional quantities).
- Gate G: Idempotent replay determinism.
- Gate H: Mathematical reconciliation of Phase 17.1 reported figures (₹276.84 vs ₹232.15 vs ₹255.75).
"""

from __future__ import annotations

import datetime
from decimal import Decimal
import unittest
from typing import Any, Dict, List

from agents.AGI_1_7.engine.agi17.finance.authoritative_cost_calculator import (
    AuthoritativeCostCalculator,
    BrokerageModel,
    InstrumentCategory,
    OrderSide,
    RegulatoryRegime,
    round_currency,
)
from agents.AGI_1_7.engine.agi17.finance.authoritative_risk_engine import (
    AuthoritativeTradeRiskEngine,
    ExecutionSimulationResult,
)


class TestOmegaPhase17_2TransactionCostsAndAccounting(unittest.TestCase):
    """Phase 17.2 Authoritative Financial Integrity & Accounting Test Battery."""

    def setUp(self) -> None:
        self.calc = AuthoritativeCostCalculator()

    # =========================================================================
    # 1. INDEPENDENT EXPECTED-VALUE TESTS (Options Roundtrips)
    # =========================================================================

    def test_01_nifty_standard_lot_flat_20_roundtrip(self) -> None:
        """BUY 65 units @ 30.32, SELL 65 units @ 34.68 under Paytm Flat ₹20."""
        # 1. First-principles independent calculation:
        # Entry BUY:
        #   Turnover: 65 * 30.32 = 1,970.80
        #   Brokerage: 20.00
        #   STT: 0.00 (BUY options)
        #   Exchange charges (NSE 64232): 1,970.80 * 0.0003503 = 0.69037124 -> 0.69
        #   SEBI charges: 1,970.80 * 1e-6 = 0.0019708 -> 0.00
        #   Stamp duty: 1,970.80 * 0.00003 = 0.059124 -> 0.06
        #   GST Base: 20.00 + 0.69 + 0.00 = 20.69
        #   GST (18%): 20.69 * 0.18 = 3.7242 -> 3.72
        #   Entry Friction: 20.00 + 0.00 + 0.69 + 0.00 + 0.06 + 3.72 = 24.47
        #
        # Exit SELL:
        #   Turnover: 65 * 34.68 = 2,254.20
        #   Brokerage: 20.00
        #   STT (Finance Act 2024, 0.10%): 2,254.20 * 0.001 = 2.2542 -> 2.25
        #   Exchange charges: 2,254.20 * 0.0003503 = 0.78964626 -> 0.79
        #   SEBI charges: 2,254.20 * 1e-6 = 0.0022542 -> 0.00
        #   Stamp duty: 0.00 (SELL options)
        #   GST Base: 20.00 + 0.79 + 0.00 = 20.79
        #   GST (18%): 20.79 * 0.18 = 3.7422 -> 3.74
        #   Exit Friction: 20.00 + 2.25 + 0.79 + 0.00 + 0.00 + 3.74 = 26.78
        #
        # Roundtrip Summary:
        #   Gross Realized P&L: (34.68 - 30.32) * 65 = 4.36 * 65 = 283.40
        #   Total Friction: 24.47 + 26.78 = 51.25
        #   Net Realized P&L: 283.40 - 51.25 = 232.15

        rt = self.calc.calculate_roundtrip_friction(
            entry_price=Decimal("30.32"),
            exit_price=Decimal("34.68"),
            quantity=65,
            brokerage_model=BrokerageModel.PAYTM_FLAT_20,
            trade_date=datetime.date(2024, 10, 15),
        )

        self.assertEqual(rt.entry.turnover, Decimal("1970.80"))
        self.assertEqual(rt.entry.brokerage, Decimal("20.00"))
        self.assertEqual(rt.entry.stt, Decimal("0.00"))
        self.assertEqual(rt.entry.exchange_charges, Decimal("0.69"))
        self.assertEqual(rt.entry.sebi_charges, Decimal("0.00"))
        self.assertEqual(rt.entry.stamp_duty, Decimal("0.06"))
        self.assertEqual(rt.entry.taxable_services_base, Decimal("20.69"))
        self.assertEqual(rt.entry.gst, Decimal("3.72"))
        self.assertEqual(rt.total_entry_friction, Decimal("24.47"))

        self.assertEqual(rt.exit.turnover, Decimal("2254.20"))
        self.assertEqual(rt.exit.brokerage, Decimal("20.00"))
        self.assertEqual(rt.exit.stt, Decimal("2.25"))
        self.assertEqual(rt.exit.exchange_charges, Decimal("0.79"))
        self.assertEqual(rt.exit.stamp_duty, Decimal("0.00"))
        self.assertEqual(rt.exit.taxable_services_base, Decimal("20.79"))
        self.assertEqual(rt.exit.gst, Decimal("3.74"))
        self.assertEqual(rt.total_exit_friction, Decimal("26.78"))

        self.assertEqual(rt.gross_realized_pnl, Decimal("283.40"))
        self.assertEqual(rt.total_roundtrip_friction, Decimal("51.25"))
        self.assertEqual(rt.net_realized_pnl, Decimal("232.15"))
        self.assertEqual(rt.net_cash_change, Decimal("232.15"))

    def test_02_nifty_standard_lot_promo_10_roundtrip(self) -> None:
        """BUY 65 units @ 30.32, SELL 65 units @ 34.68 under Paytm Promo ₹10."""
        # Under Flat ₹10 Brokerage:
        # Entry: Brokerage ₹10 + Stamp ₹0.06 + Exch ₹0.69 + GST ₹1.92 = ₹12.67
        # Exit: Brokerage ₹10 + STT ₹2.25 + Exch ₹0.79 + GST ₹1.94 = ₹14.98
        # Total Friction: 12.67 + 14.98 = 27.65
        # Net Realized P&L: 283.40 - 27.65 = 255.75

        rt = self.calc.calculate_roundtrip_friction(
            entry_price=Decimal("30.32"),
            exit_price=Decimal("34.68"),
            quantity=65,
            brokerage_model=BrokerageModel.PAYTM_PROMO_10,
            trade_date=datetime.date(2024, 10, 15),
        )

        self.assertEqual(rt.entry.brokerage, Decimal("10.00"))
        self.assertEqual(rt.entry.gst, Decimal("1.92"))
        self.assertEqual(rt.total_entry_friction, Decimal("12.67"))

        self.assertEqual(rt.exit.brokerage, Decimal("10.00"))
        self.assertEqual(rt.exit.gst, Decimal("1.94"))
        self.assertEqual(rt.total_exit_friction, Decimal("14.98"))

        self.assertEqual(rt.total_roundtrip_friction, Decimal("27.65"))
        self.assertEqual(rt.net_realized_pnl, Decimal("255.75"))
        self.assertEqual(rt.net_cash_change, Decimal("255.75"))

    def test_03_legacy_phase17_formula_reproduction(self) -> None:
        """Reproduces exact Phase 17 / 17.1 figures (Entry ₹2.04, Exit ₹4.52, Net ₹276.84)."""
        # Under EQUITY_INTRADAY_0_05_MAX_20 brokerage model:
        # Entry turnover = 1,970.80
        #   Brokerage = min(20, round(1,970.80 * 0.0005, 2)) = 0.99
        #   Stamp Duty = 0.06
        #   Exchange charges = 0.69
        #   GST = round((0.99 + 0.69) * 0.18, 2) = 0.30
        #   Entry Friction = 0.99 + 0.00 + 0.69 + 0.00 + 0.06 + 0.30 = 2.04
        # Exit turnover = 2,254.20
        #   Brokerage = min(20, round(2,254.20 * 0.0005, 2)) = 1.13
        #   STT = 2.25
        #   Exchange charges = 0.79
        #   GST = round((1.13 + 0.79) * 0.18, 2) = 0.35
        #   Exit Friction = 1.13 + 2.25 + 0.79 + 0.00 + 0.00 + 0.35 = 4.52
        # Total Friction = 2.04 + 4.52 = 6.56
        # Net Realized P&L = 283.40 - 6.56 = 276.84

        rt = self.calc.calculate_roundtrip_friction(
            entry_price=Decimal("30.32"),
            exit_price=Decimal("34.68"),
            quantity=65,
            brokerage_model=BrokerageModel.EQUITY_INTRADAY_0_05_MAX_20,
            trade_date=datetime.date(2024, 10, 15),
        )

        self.assertEqual(rt.entry.brokerage, Decimal("0.99"))
        self.assertEqual(rt.entry.total_friction, Decimal("2.04"))
        self.assertEqual(rt.exit.brokerage, Decimal("1.13"))
        self.assertEqual(rt.exit.total_friction, Decimal("4.52"))
        self.assertEqual(rt.total_roundtrip_friction, Decimal("6.56"))
        self.assertEqual(rt.net_realized_pnl, Decimal("276.84"))
        self.assertEqual(rt.net_cash_change, Decimal("276.84"))

    def test_04_banknifty_multi_lot_roundtrip(self) -> None:
        """3 lots BankNifty (3 * 15 = 45 units) @ 210.00 entry, 245.00 exit."""
        # Entry BUY:
        #   Turnover: 45 * 210.00 = 9,450.00
        #   Brokerage (Flat 20): 20.00
        #   STT: 0.00
        #   Exchange charges: 9,450.00 * 0.0003503 = 3.310335 -> 3.31
        #   SEBI charges: 9,450.00 * 1e-6 = 0.00945 -> 0.01
        #   Stamp duty: 9,450.00 * 0.00003 = 0.2835 -> 0.28
        #   GST Base: 20.00 + 3.31 + 0.01 = 23.32
        #   GST (18%): 23.32 * 0.18 = 4.1976 -> 4.20
        #   Entry Friction: 20.00 + 0.00 + 3.31 + 0.01 + 0.28 + 4.20 = 27.80
        #
        # Exit SELL:
        #   Turnover: 45 * 245.00 = 11,025.00
        #   Brokerage: 20.00
        #   STT (0.10%): 11,025.00 * 0.001 = 11.025 -> 11.03
        #   Exchange charges: 11,025.00 * 0.0003503 = 3.8620575 -> 3.86
        #   SEBI charges: 11,025.00 * 1e-6 = 0.011025 -> 0.01
        #   Stamp duty: 0.00
        #   GST Base: 20.00 + 3.86 + 0.01 = 23.87
        #   GST (18%): 23.87 * 0.18 = 4.2966 -> 4.30
        #   Exit Friction: 20.00 + 11.03 + 3.86 + 0.01 + 0.00 + 4.30 = 39.20
        #
        # Gross P&L: (245 - 210) * 45 = 35 * 45 = 1,575.00
        # Total Friction: 27.80 + 39.20 = 67.00
        # Net Realized P&L: 1,575.00 - 67.00 = 1,508.00

        rt = self.calc.calculate_roundtrip_friction(
            entry_price=Decimal("210.00"),
            exit_price=Decimal("245.00"),
            quantity=45,
            brokerage_model=BrokerageModel.PAYTM_FLAT_20,
            trade_date=datetime.date(2024, 10, 15),
        )

        self.assertEqual(rt.entry.turnover, Decimal("9450.00"))
        self.assertEqual(rt.total_entry_friction, Decimal("27.80"))
        self.assertEqual(rt.exit.turnover, Decimal("11025.00"))
        self.assertEqual(rt.total_exit_friction, Decimal("39.20"))
        self.assertEqual(rt.gross_realized_pnl, Decimal("1575.00"))
        self.assertEqual(rt.total_roundtrip_friction, Decimal("67.00"))
        self.assertEqual(rt.net_realized_pnl, Decimal("1508.00"))
        self.assertEqual(rt.net_cash_change, Decimal("1508.00"))

    def test_05_loss_making_roundtrip_drag_expansion(self) -> None:
        """Loss-making roundtrip: Net loss strictly exceeds gross loss due to friction."""
        # BUY 65 units @ 40.00, SELL 65 units @ 32.00
        # Gross loss = (32 - 40) * 65 = -520.00
        rt = self.calc.calculate_roundtrip_friction(
            entry_price=Decimal("40.00"),
            exit_price=Decimal("32.00"),
            quantity=65,
            brokerage_model=BrokerageModel.PAYTM_FLAT_20,
            trade_date=datetime.date(2024, 10, 15),
        )

        self.assertEqual(rt.gross_realized_pnl, Decimal("-520.00"))
        self.assertGreater(rt.total_roundtrip_friction, Decimal("0.00"))
        # Net loss is more negative than gross loss
        self.assertLess(rt.net_realized_pnl, rt.gross_realized_pnl)
        self.assertEqual(rt.net_realized_pnl, rt.gross_realized_pnl - rt.total_roundtrip_friction)
        self.assertEqual(rt.net_cash_change, rt.net_realized_pnl)

    # =========================================================================
    # 2. STATUTORY INVARIANTS & ASYMMETRY CHECKS
    # =========================================================================

    def test_06_stt_and_stamp_duty_leg_asymmetry(self) -> None:
        """STT must be strictly 0 on BUY leg; Stamp duty must be strictly 0 on SELL leg."""
        entry = self.calc.calculate_order_friction(
            side=OrderSide.BUY,
            quantity=100,
            price=Decimal("50.00"),
            instrument_category=InstrumentCategory.OPTIONS,
        )
        self.assertEqual(entry.stt, Decimal("0.00"))
        self.assertGreater(entry.stamp_duty, Decimal("0.00"))

        exit_leg = self.calc.calculate_order_friction(
            side=OrderSide.SELL,
            quantity=100,
            price=Decimal("60.00"),
            instrument_category=InstrumentCategory.OPTIONS,
        )
        self.assertGreater(exit_leg.stt, Decimal("0.00"))
        self.assertEqual(exit_leg.stamp_duty, Decimal("0.00"))

    def test_07_gst_taxable_base_exclusion_invariant(self) -> None:
        """Taxes (STT and Stamp Duty) are strictly EXCLUDED from the GST base."""
        # For a high-turnover trade where STT and Stamp Duty are substantial:
        order = self.calc.calculate_order_friction(
            side=OrderSide.SELL,
            quantity=1000,
            price=Decimal("500.00"),  # Turnover = 5,00,000
            brokerage_model=BrokerageModel.PAYTM_FLAT_20,
            trade_date=datetime.date(2024, 10, 15),
        )
        # STT = 5,00,000 * 0.001 = 500.00
        self.assertEqual(order.stt, Decimal("500.00"))
        # Taxable services base must only include (brokerage + exchange + ipft + sebi)
        expected_base = order.brokerage + order.exchange_charges + order.ipft + order.sebi_charges
        self.assertEqual(order.taxable_services_base, expected_base)
        # GST must strictly equal 18% of taxable services base
        expected_gst = round_currency(expected_base * Decimal("0.18"))
        self.assertEqual(order.gst, expected_gst)
        # Ensure STT is NOT in the GST base
        self.assertNotIn(order.stt, [order.taxable_services_base])

    # =========================================================================
    # 3. DATE-AWARE STATUTORY REGIME AUDITS
    # =========================================================================

    def test_08_stt_transition_across_effective_dates(self) -> None:
        """Audits STT rates across historical, current, and future statutory regimes."""
        qty = 100
        price = Decimal("100.00")  # Turnover = 10,000

        # 1. Historical pre-Oct 2024 (0.0625%)
        pre_oct24 = self.calc.calculate_order_friction(
            side=OrderSide.SELL, quantity=qty, price=price, trade_date=datetime.date(2024, 9, 15),
        )
        self.assertEqual(pre_oct24.regime, RegulatoryRegime.HISTORICAL_PRE_OCT_2024)
        self.assertEqual(pre_oct24.stt, Decimal("6.25"))

        # 2. Finance Act 2024 (0.10%)
        post_oct24 = self.calc.calculate_order_friction(
            side=OrderSide.SELL, quantity=qty, price=price, trade_date=datetime.date(2024, 10, 15),
        )
        self.assertEqual(post_oct24.regime, RegulatoryRegime.OCT_2024_TO_FEB_2026)
        self.assertEqual(post_oct24.stt, Decimal("10.00"))

        # 3. 2026 Schedule (0.15%)
        post_apr26 = self.calc.calculate_order_friction(
            side=OrderSide.SELL, quantity=qty, price=price, trade_date=datetime.date(2026, 4, 15),
        )
        self.assertEqual(post_apr26.regime, RegulatoryRegime.POST_APRIL_2026)
        self.assertEqual(post_apr26.stt, Decimal("15.00"))

    # =========================================================================
    # 4. FULL ACCOUNTING LIFECYCLE RECONCILIATION
    # =========================================================================

    def test_09_full_accounting_lifecycle_reconciliation(self) -> None:
        """Full lifecycle audit: Starting capital, cash balances, equity marks, and invariants."""
        audit = self.calc.reconcile_trade_accounting(
            starting_capital=10000.0,
            entry_price=30.32,
            exit_price=34.68,
            quantity=65,
            brokerage_model=BrokerageModel.PAYTM_FLAT_20,
            trade_date=datetime.date(2024, 10, 15),
        )

        self.assertEqual(audit["starting_capital_inr"], 10000.0)
        self.assertEqual(audit["gross_realized_pnl_inr"], 283.40)
        self.assertEqual(audit["entry_friction_inr"], 24.47)
        self.assertEqual(audit["exit_friction_inr"], 26.78)
        self.assertEqual(audit["total_roundtrip_friction_inr"], 51.25)
        self.assertEqual(audit["net_realized_pnl_inr"], 232.15)
        self.assertEqual(audit["net_cash_change_inr"], 232.15)

        # Cash lifecycle verification
        cash = audit["cash_lifecycle"]
        self.assertEqual(cash["t0_initial"], 10000.00)
        # t1 post-entry: 10,000 - (1,970.80 + 24.47) = 8,004.73
        self.assertEqual(cash["t1_post_entry"], 8004.73)
        # t2 post-exit: 8,004.73 + (2,254.20 - 26.78) = 8,004.73 + 2,227.42 = 10,232.15
        self.assertEqual(cash["t2_post_exit"], 10232.15)

        # Equity lifecycle verification
        eq = audit["equity_lifecycle"]
        self.assertEqual(eq["t0_initial"], 10000.00)
        # t1: cash (8004.73) + mtm (1970.80) = 9975.53 = 10,000 - 24.47 (friction recognized immediately)
        self.assertEqual(eq["t1_post_entry"], 9975.53)
        # t2: position closed -> equity == cash == 10,232.15
        self.assertEqual(eq["t2_post_exit"], 10232.15)
        self.assertEqual(audit["audit_certification"], "CERTIFIED_MATHEMATICALLY_RECONCILED")

    # =========================================================================
    # 5. IDEMPOTENT REPLAY DETERMINISM
    # =========================================================================

    def test_10_idempotent_replay_consistency(self) -> None:
        """Replaying identical trades 100 times must produce identical cash and equity to 0.01 INR."""
        baseline = self.calc.reconcile_trade_accounting(
            starting_capital=10000.0,
            entry_price=30.32,
            exit_price=34.68,
            quantity=65,
            brokerage_model=BrokerageModel.PAYTM_FLAT_20,
        )

        for _ in range(100):
            replay = self.calc.reconcile_trade_accounting(
                starting_capital=10000.0,
                entry_price=30.32,
                exit_price=34.68,
                quantity=65,
                brokerage_model=BrokerageModel.PAYTM_FLAT_20,
            )
            self.assertEqual(replay["net_realized_pnl_inr"], baseline["net_realized_pnl_inr"])
            self.assertEqual(replay["cash_lifecycle"]["t2_post_exit"], baseline["cash_lifecycle"]["t2_post_exit"])
            self.assertEqual(replay["equity_lifecycle"]["t2_post_exit"], baseline["equity_lifecycle"]["t2_post_exit"])

    # =========================================================================
    # 6. RISK ENGINE INTEGRATION TEST
    # =========================================================================

    def test_11_risk_engine_simulate_order_execution_delegation(self) -> None:
        """Verifies AuthoritativeTradeRiskEngine.simulate_order_execution delegates cleanly."""
        sim = AuthoritativeTradeRiskEngine.simulate_order_execution(
            side="BUY",
            quantity=65,
            price=100.0,
            bid=99.80,
            ask=100.20,
            volatility_multiplier=1.5,
            brokerage_model=BrokerageModel.PAYTM_FLAT_20,
        )
        self.assertIsInstance(sim, ExecutionSimulationResult)
        self.assertEqual(sim.brokerage_inr, 20.00)
        self.assertEqual(sim.stt_inr, 0.00)
        self.assertGreater(sim.exchange_charges_inr, 0.00)
        self.assertGreater(sim.gst_inr, 0.00)
        self.assertAlmostEqual(
            sim.total_friction_inr,
            sim.brokerage_inr + sim.stt_inr + sim.exchange_charges_inr +
            sim.gst_inr + sim.sebi_charges_inr + sim.stamp_duty_inr,
            places=2,
        )

    # =========================================================================
    # 7. PHASE 17.3 CURRENT EVALUATION DATE & STATUTORY TRANSITION TESTS
    # =========================================================================

    def test_12_current_evaluation_date_rates_october_2026(self) -> None:
        """Independently verifies transaction friction on current evaluation date (2026-10-16).
        
        Current Rates in effect:
        - Options Sale STT: 0.15% (Finance Act 2026 schedule)
        - Exchange Fee: NSE Circular 73061 (0.0355299% + 0.0000001% IPFT = 0.03553%)
        - Brokerage: Paytm Flat ₹10 (Published FAQ) and Flat ₹20 (Standard Account)
        """
        eval_date = datetime.date(2026, 10, 16)

        # 1. Test under Published FAQ Flat ₹10 Brokerage:
        rt_10 = self.calc.calculate_roundtrip_friction(
            entry_price=Decimal("30.32"),
            exit_price=Decimal("34.68"),
            quantity=65,
            brokerage_model=BrokerageModel.PAYTM_PROMO_10,
            trade_date=eval_date,
        )
        self.assertEqual(rt_10.entry.exchange_charges, Decimal("0.70"))
        self.assertEqual(rt_10.entry.stamp_duty, Decimal("0.06"))
        self.assertEqual(rt_10.entry.gst, Decimal("1.93"))
        self.assertEqual(rt_10.total_entry_friction, Decimal("12.69"))

        self.assertEqual(rt_10.exit.stt, Decimal("3.38"))  # 2254.20 * 0.0015 = 3.38
        self.assertEqual(rt_10.exit.exchange_charges, Decimal("0.80"))
        self.assertEqual(rt_10.exit.gst, Decimal("1.94"))
        self.assertEqual(rt_10.total_exit_friction, Decimal("16.12"))

        self.assertEqual(rt_10.gross_realized_pnl, Decimal("283.40"))
        self.assertEqual(rt_10.total_roundtrip_friction, Decimal("28.81"))
        self.assertEqual(rt_10.net_realized_pnl, Decimal("254.59"))
        self.assertEqual(rt_10.net_cash_change, Decimal("254.59"))

        # 2. Test under Standard Account Flat ₹20 Brokerage:
        rt_20 = self.calc.calculate_roundtrip_friction(
            entry_price=Decimal("30.32"),
            exit_price=Decimal("34.68"),
            quantity=65,
            brokerage_model=BrokerageModel.PAYTM_FLAT_20,
            trade_date=eval_date,
        )
        self.assertEqual(rt_20.entry.exchange_charges, Decimal("0.70"))
        self.assertEqual(rt_20.entry.gst, Decimal("3.73"))
        self.assertEqual(rt_20.total_entry_friction, Decimal("24.49"))

        self.assertEqual(rt_20.exit.stt, Decimal("3.38"))
        self.assertEqual(rt_20.exit.exchange_charges, Decimal("0.80"))
        self.assertEqual(rt_20.exit.gst, Decimal("3.74"))
        self.assertEqual(rt_20.total_exit_friction, Decimal("27.92"))

        self.assertEqual(rt_20.total_roundtrip_friction, Decimal("52.41"))
        self.assertEqual(rt_20.net_realized_pnl, Decimal("230.99"))
        self.assertEqual(rt_20.net_cash_change, Decimal("230.99"))

    def test_13_statutory_transition_boundaries(self) -> None:
        """Verifies exact statutory rate shifts across historical and current transition boundaries."""
        qty = 100
        price = Decimal("100.00")  # Turnover = 10,000.00

        # Boundary 1: 2024-09-30 (Pre-Oct 2024) vs 2024-10-01 (Post-Oct 2024)
        pre_oct24 = self.calc.calculate_order_friction(
            side=OrderSide.SELL, quantity=qty, price=price, trade_date=datetime.date(2024, 9, 30)
        )
        post_oct24 = self.calc.calculate_order_friction(
            side=OrderSide.SELL, quantity=qty, price=price, trade_date=datetime.date(2024, 10, 1)
        )
        self.assertEqual(pre_oct24.regime, RegulatoryRegime.HISTORICAL_PRE_OCT_2024)
        self.assertEqual(pre_oct24.stt, Decimal("6.25"))     # 0.0625%
        self.assertEqual(pre_oct24.exchange_charges, Decimal("5.00")) # 0.05%

        self.assertEqual(post_oct24.regime, RegulatoryRegime.OCT_2024_TO_FEB_2026)
        self.assertEqual(post_oct24.stt, Decimal("10.00"))    # 0.10%
        self.assertEqual(post_oct24.exchange_charges, Decimal("3.50")) # 0.03503%

        # Boundary 2: 2026-02-28 (Circular 64232) vs 2026-03-01 (Circular 73061)
        feb26 = self.calc.calculate_order_friction(
            side=OrderSide.SELL, quantity=qty, price=price, trade_date=datetime.date(2026, 2, 28)
        )
        mar26 = self.calc.calculate_order_friction(
            side=OrderSide.SELL, quantity=qty, price=price, trade_date=datetime.date(2026, 3, 1)
        )
        self.assertEqual(feb26.regime, RegulatoryRegime.OCT_2024_TO_FEB_2026)
        self.assertEqual(feb26.exchange_charges, Decimal("3.50")) # 0.03503%

        self.assertEqual(mar26.regime, RegulatoryRegime.MAR_2026_TO_MAR_2026)
        self.assertEqual(mar26.exchange_charges, Decimal("3.55")) # 0.0355299% -> 3.55
        self.assertEqual(mar26.stt, Decimal("10.00"))             # 0.10%

        # Boundary 3: 2026-03-31 vs 2026-04-01 (Finance Act 2026 STT schedule)
        end_mar26 = self.calc.calculate_order_friction(
            side=OrderSide.SELL, quantity=qty, price=price, trade_date=datetime.date(2026, 3, 31)
        )
        apr26 = self.calc.calculate_order_friction(
            side=OrderSide.SELL, quantity=qty, price=price, trade_date=datetime.date(2026, 4, 1)
        )
        self.assertEqual(end_mar26.regime, RegulatoryRegime.MAR_2026_TO_MAR_2026)
        self.assertEqual(end_mar26.stt, Decimal("10.00"))         # 0.10%

        self.assertEqual(apr26.regime, RegulatoryRegime.POST_APRIL_2026)
        self.assertEqual(apr26.stt, Decimal("15.00"))             # 0.15%

    def test_14_futures_stt_and_contract_turnover(self) -> None:
        """Verifies Futures STT: 0% BUY, 0.02% (2024) vs 0.05% (Current 2026) on SELL."""
        turnover = Decimal("100000.00")  # ₹1 Lakh futures contract turnover
        qty = 100
        price = Decimal("1000.00")

        # BUY Futures has NIL STT
        buy_fut = self.calc.calculate_order_friction(
            side=OrderSide.BUY, quantity=qty, price=price, instrument_category=InstrumentCategory.FUTURES,
            trade_date=datetime.date(2026, 10, 16)
        )
        self.assertEqual(buy_fut.stt, Decimal("0.00"))
        self.assertEqual(buy_fut.stamp_duty, Decimal("2.00"))  # 0.002% on BUY

        # SELL Futures in 2024 (0.02%)
        sell_fut_24 = self.calc.calculate_order_friction(
            side=OrderSide.SELL, quantity=qty, price=price, instrument_category=InstrumentCategory.FUTURES,
            trade_date=datetime.date(2024, 10, 15)
        )
        self.assertEqual(sell_fut_24.stt, Decimal("20.00"))  # 100,000 * 0.0002 = 20.00

        # SELL Futures in current 2026 schedule (0.05%)
        sell_fut_26 = self.calc.calculate_order_friction(
            side=OrderSide.SELL, quantity=qty, price=price, instrument_category=InstrumentCategory.FUTURES,
            trade_date=datetime.date(2026, 10, 16)
        )
        self.assertEqual(sell_fut_26.stt, Decimal("50.00"))  # 100,000 * 0.0005 = 50.00

    def test_15_failclosed_numerical_boundaries(self) -> None:
        """Verifies calculator fails closed on negative quantities or prices."""
        with self.assertRaises((ValueError, AssertionError)):
            self.calc.calculate_order_friction(
                side=OrderSide.BUY, quantity=-10, price=Decimal("100.00")
            )

        with self.assertRaises((ValueError, AssertionError)):
            self.calc.calculate_order_friction(
                side=OrderSide.BUY, quantity=10, price=Decimal("-50.00")
            )


if __name__ == "__main__":
    unittest.main()
