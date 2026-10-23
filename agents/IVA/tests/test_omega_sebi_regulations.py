"""AGI 1.7 Acceptance Tests for SEBI Derivatives Regulatory Framework (Circular 2024/132).

Covers:
1. Contract notional threshold validation (₹15 Lakhs floor).
2. 100% upfront premium collection for option buyers.
3. Additional 2% Extreme Loss Margin (ELM) on short options on expiry day.
4. Elimination of calendar spread margin benefit on expiry day.
5. Pre-trade compliance gating & deficit calculation.
"""

from __future__ import annotations

import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OrderSide
from agents.AGI_1_7.engine.agi17.finance.sebi_regulations import (
    SebiDerivativeRegulatoryEngine,
    SebiMarginRequirement,
)


class TestOmegaSebiRegulations(unittest.TestCase):
    """Test suite for SEBI derivative regulatory compliance engine."""

    def test_01_contract_notional_validation(self) -> None:
        """Verifies contract notional evaluation against ₹15 Lakhs minimum."""
        # Spot 50,000, Lot 15 -> Notional = 7.5 Lakhs (< 15 Lakhs, recommends Lot 30)
        res_legacy = SebiDerivativeRegulatoryEngine.validate_contract_notional(spot_price=50000.0, lot_size=15)
        self.assertEqual(res_legacy["contract_notional_inr"], 750000.0)
        self.assertFalse(res_legacy["meets_minimum_15_lakhs"])
        self.assertEqual(res_legacy["recommended_lot_size"], 30)

        # Spot 50,000, Lot 30 -> Notional = 15.0 Lakhs (Meets minimum)
        res_revised = SebiDerivativeRegulatoryEngine.validate_contract_notional(spot_price=50000.0, lot_size=30)
        self.assertEqual(res_revised["contract_notional_inr"], 1500000.0)
        self.assertTrue(res_revised["meets_minimum_15_lakhs"])
        self.assertEqual(res_revised["recommended_lot_size"], 30)

    def test_02_buyer_100_percent_upfront_premium(self) -> None:
        """Verifies option buyers are charged 100% upfront premium without leverage."""
        req = SebiDerivativeRegulatoryEngine.calculate_order_margins(
            contract_symbol="BANKNIFTY26OCT52000CE",
            side=OrderSide.BUY,
            units=30,
            premium=250.0,
            spot_price=51800.0,
            is_expiry_day=False,
        )
        self.assertIsInstance(req, SebiMarginRequirement)
        self.assertEqual(req.upfront_premium_required_inr, 7500.0)
        self.assertEqual(req.base_span_margin_inr, 0.0)
        self.assertEqual(req.extreme_loss_margin_inr, 0.0)
        self.assertEqual(req.total_margin_required_inr, 7500.0)
        self.assertFalse(req.calendar_spread_benefit_allowed)

    def test_03_seller_additional_elm_on_expiry_day(self) -> None:
        """Verifies sellers pay additional 2% ELM on expiry day."""
        units = 30
        spot = 50000.0
        notional = units * spot  # 15,00,000 INR

        # 1. Non-expiry day: Base SPAN 10% (1,50,000) + ELM 3.5% (52,500) = 2,02,500 INR
        req_normal = SebiDerivativeRegulatoryEngine.calculate_order_margins(
            contract_symbol="BANKNIFTY26OCT50000PE",
            side=OrderSide.SELL,
            units=units,
            premium=300.0,
            spot_price=spot,
            is_expiry_day=False,
        )
        self.assertEqual(req_normal.extreme_loss_margin_inr, 52500.0)
        self.assertEqual(req_normal.total_margin_required_inr, 202500.0)

        # 2. Expiry day: Base SPAN 10% (1,50,000) + ELM 5.5% (82,500) = 2,32,500 INR
        req_expiry = SebiDerivativeRegulatoryEngine.calculate_order_margins(
            contract_symbol="BANKNIFTY26OCT50000PE",
            side=OrderSide.SELL,
            units=units,
            premium=300.0,
            spot_price=spot,
            is_expiry_day=True,
        )
        self.assertEqual(req_expiry.extreme_loss_margin_inr, 82500.0)
        self.assertEqual(req_expiry.total_margin_required_inr, 232500.0)
        # Difference is exactly 2% of notional (30,000 INR)
        diff = req_expiry.total_margin_required_inr - req_normal.total_margin_required_inr
        self.assertEqual(diff, 30000.0)

    def test_04_calendar_spread_benefit_disallowed_on_expiry(self) -> None:
        """Verifies calendar spread offset is disallowed on expiry day."""
        req_normal = SebiDerivativeRegulatoryEngine.calculate_order_margins(
            contract_symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.SELL,
            units=30,
            premium=200.0,
            spot_price=50000.0,
            is_expiry_day=False,
            is_calendar_spread=True,
        )
        self.assertTrue(req_normal.calendar_spread_benefit_allowed)

        req_expiry = SebiDerivativeRegulatoryEngine.calculate_order_margins(
            contract_symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.SELL,
            units=30,
            premium=200.0,
            spot_price=50000.0,
            is_expiry_day=True,
            is_calendar_spread=True,
        )
        self.assertFalse(req_expiry.calendar_spread_benefit_allowed)

    def test_05_pre_trade_compliance_and_deficit_gate(self) -> None:
        """Verifies pre-trade gateway enforces capital requirement and returns exact deficit."""
        req = SebiDerivativeRegulatoryEngine.calculate_order_margins(
            contract_symbol="BANKNIFTY26OCT50000CE",
            side=OrderSide.BUY,
            units=30,
            premium=200.0,
            spot_price=50000.0,
        )
        # Required is 6000 INR

        # Available 10,000 INR -> COMPLIANT
        compliant, msg1 = SebiDerivativeRegulatoryEngine.check_pre_trade_compliance(10000.0, req)
        self.assertTrue(compliant)
        self.assertEqual(msg1, "COMPLIANT")

        # Available 4,000 INR -> SHORTFALL of 2000 INR
        non_compliant, msg2 = SebiDerivativeRegulatoryEngine.check_pre_trade_compliance(4000.0, req)
        self.assertFalse(non_compliant)
        self.assertIn("shortfall", msg2.lower())
        self.assertIn("2000.00", msg2)


if __name__ == "__main__":
    unittest.main()
