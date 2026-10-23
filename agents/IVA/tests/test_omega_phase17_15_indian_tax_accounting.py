"""Unit Test Suite for Phase 17.15 Indian Tax Accounting & CA Compliance Engine.

Verifies:
1. Financial Year calendar & law versioning (FY 2026-27 -> Income-tax Act 2025).
2. Four-way trade classification (F&O u/s 43(5)(d), Intraday u/s 43(5), STCG u/s 111A, LTCG u/s 112A).
3. ICAI Guidance Note turnover calculation (Abs PnL + Option Sell Premium).
4. Section 44AB Tax Audit threshold evaluation (₹10 Crore digital limit).
5. Section 211 Advance Tax installment schedule (15%, 45%, 75%, 100%).
6. Section 37 business expense deduction from F&O business income.
7. CA handoff package compilation and question verification.
"""

from __future__ import annotations

import datetime
import unittest

from agents.AGI_1_7.engine.agi17.finance.indian_tax_accounting import (
    FinancialYearInfo,
    GoverningTaxAct,
    IndianTaxAccountingEngine,
    NormalizedTradeEvent,
    TaxHead,
    get_financial_year,
)


class TestIndianTaxAccounting(unittest.TestCase):
    """Authoritative test cases for Indian tax accounting and regulatory compliance."""

    def test_financial_year_resolution_and_act_versioning(self) -> None:
        """Verify FY 2026-27 resolves to Income-tax Act 2025 with post-Budget 2024 rates."""
        fy_2026 = get_financial_year(datetime.date(2026, 10, 16))
        self.assertEqual(fy_2026.financial_year, "2026-27")
        self.assertEqual(fy_2026.assessment_year, "2027-28")
        self.assertEqual(fy_2026.governing_act, GoverningTaxAct.INCOME_TAX_ACT_2025)
        self.assertEqual(fy_2026.stcg_rate_pct, 20.0)
        self.assertEqual(fy_2026.ltcg_rate_pct, 12.5)
        self.assertEqual(fy_2026.ltcg_exemption_inr, 125000.0)
        self.assertEqual(fy_2026.tax_audit_turnover_limit_digital_inr, 100000000.0)

        # Historical FY 2024-25
        fy_2024 = get_financial_year(datetime.date(2024, 8, 15))
        self.assertEqual(fy_2024.financial_year, "2024-25")
        self.assertEqual(fy_2024.governing_act, GoverningTaxAct.INCOME_TAX_ACT_1961)

    def test_trade_tax_head_classification(self) -> None:
        """Verify legal classification of equity options, futures, intraday, and delivery."""
        engine = IndianTaxAccountingEngine()

        # Options -> F&O Non-speculative u/s 43(5)(d)
        head_opt = engine.classify_trade("OPTION", holding_days=0, is_intraday=True)
        self.assertEqual(head_opt, TaxHead.FNO_NON_SPECULATIVE_43_5_D)

        # Futures -> F&O Non-speculative u/s 43(5)(d)
        head_fut = engine.classify_trade("FUTURE", holding_days=5, is_intraday=False)
        self.assertEqual(head_fut, TaxHead.FNO_NON_SPECULATIVE_43_5_D)

        # Cash Equity Intraday -> Speculative u/s 43(5)
        head_intra = engine.classify_trade("EQUITY", holding_days=0, is_intraday=True)
        self.assertEqual(head_intra, TaxHead.INTRADAY_SPECULATIVE_43_5)

        # Cash Equity Delivery <= 365 days -> STCG u/s 111A
        head_stcg = engine.classify_trade("EQUITY", holding_days=100, is_intraday=False)
        self.assertEqual(head_stcg, TaxHead.EQUITY_STCG_111A)

        # Cash Equity Delivery > 365 days -> LTCG u/s 112A
        head_ltcg = engine.classify_trade("EQUITY", holding_days=400, is_intraday=False)
        self.assertEqual(head_ltcg, TaxHead.EQUITY_LTCG_112A)

    def test_icai_fno_turnover_calculation(self) -> None:
        """Verify ICAI Guidance Note turnover: Abs PnL + Option Sell Premium."""
        engine = IndianTaxAccountingEngine()

        # Trade 1: NIFTY Option Buy 15 @ ₹100, Sell @ ₹120. PnL = +₹300. Sell Premium = 15 * 120 = ₹1,800.
        t1 = NormalizedTradeEvent(
            trade_id="TR-001",
            trade_date=datetime.date(2026, 10, 16),
            symbol="NIFTY26OCT24500CE",
            instrument_type="OPTION",
            side="SELL",
            quantity=15,
            price=120.0,
            turnover=1800.0,
            brokerage_inr=20.0,
            stt_inr=2.70,
            exchange_charges_inr=0.64,
            gst_inr=3.72,
            sebi_charges_inr=0.01,
            stamp_duty_inr=0.0,
            total_charges_inr=27.07,
            realized_gross_pnl_inr=300.0,
            realized_net_pnl_inr=272.93,
            tax_head=TaxHead.FNO_NON_SPECULATIVE_43_5_D,
        )
        engine.record_trade(t1)

        # Trade 2: Losing F&O trade: Gross PnL = -₹500. Sell leg turnover = ₹1,500.
        t2 = NormalizedTradeEvent(
            trade_id="TR-002",
            trade_date=datetime.date(2026, 10, 16),
            symbol="BANKNIFTY26OCT52000PE",
            instrument_type="OPTION",
            side="SELL",
            quantity=15,
            price=100.0,
            turnover=1500.0,
            brokerage_inr=20.0,
            stt_inr=2.25,
            exchange_charges_inr=0.53,
            gst_inr=3.70,
            sebi_charges_inr=0.01,
            stamp_duty_inr=0.0,
            total_charges_inr=26.49,
            realized_gross_pnl_inr=-500.0,
            realized_net_pnl_inr=-526.49,
            tax_head=TaxHead.FNO_NON_SPECULATIVE_43_5_D,
        )
        engine.record_trade(t2)

        to = engine.calculate_icai_turnover()
        # F&O Turnover = Abs(300) + 1800 + Abs(-500) + 1500 = 300 + 1800 + 500 + 1500 = ₹4,100.00
        self.assertEqual(to["fno_turnover_inr"], 4100.0)
        self.assertEqual(to["total_turnover_inr"], 4100.0)

    def test_section_44ab_audit_threshold(self) -> None:
        """Verify Section 44AB threshold check against ₹10 Crore digital limit."""
        engine = IndianTaxAccountingEngine()
        res = engine.check_tax_audit_applicability()
        self.assertFalse(res["is_audit_mandatory"])
        self.assertEqual(res["audit_threshold_inr"], 100000000.0)
        self.assertIn("within Section 44AB digital ceiling", res["reason"])

    def test_advance_tax_schedule_generation(self) -> None:
        """Verify 15%, 45%, 75%, 100% advance tax installments under Section 211."""
        engine = IndianTaxAccountingEngine()
        # If estimated tax is ₹1,00,000
        schedule = engine.generate_advance_tax_schedule(100000.0)
        self.assertEqual(len(schedule), 4)

        self.assertEqual(schedule[0]["cumulative_pct_due"], 15.0)
        self.assertEqual(schedule[0]["cumulative_amount_due_inr"], 15000.0)

        self.assertEqual(schedule[1]["cumulative_pct_due"], 45.0)
        self.assertEqual(schedule[1]["cumulative_amount_due_inr"], 45000.0)

        self.assertEqual(schedule[2]["cumulative_pct_due"], 75.0)
        self.assertEqual(schedule[2]["cumulative_amount_due_inr"], 75000.0)

        self.assertEqual(schedule[3]["cumulative_pct_due"], 100.0)
        self.assertEqual(schedule[3]["cumulative_amount_due_inr"], 100000.0)

    def test_business_expenses_deduction_and_ca_package(self) -> None:
        """Verify Section 37 business expenses reduce F&O business income in CA handoff package."""
        engine = IndianTaxAccountingEngine()

        # Add F&O profitable trade: Gross +₹10,000, Total Charges ₹500
        t = NormalizedTradeEvent(
            trade_id="TR-100",
            trade_date=datetime.date(2026, 10, 16),
            symbol="NIFTY26OCT24500CE",
            instrument_type="OPTION",
            side="SELL",
            quantity=50,
            price=200.0,
            turnover=10000.0,
            brokerage_inr=20.0,
            stt_inr=15.0,
            exchange_charges_inr=3.55,
            gst_inr=4.24,
            sebi_charges_inr=0.01,
            stamp_duty_inr=0.0,
            total_charges_inr=42.80,
            realized_gross_pnl_inr=10000.0,
            realized_net_pnl_inr=9957.20,
            tax_head=TaxHead.FNO_NON_SPECULATIVE_43_5_D,
        )
        engine.record_trade(t)

        # Add business expenses
        engine.record_business_expense("Software", 2000.0, "Trading terminal subscription")
        engine.record_business_expense("Depreciation", 3000.0, "Trading laptop depreciation u/s 32")

        pkg = engine.generate_ca_handoff_package()
        self.assertEqual(pkg["financial_year"], "2026-27")
        self.assertEqual(pkg["pnl_summary"]["fno_gross_pnl_inr"], 10000.0)
        self.assertEqual(pkg["pnl_summary"]["fno_eligible_business_expenses_inr"], 5000.0)

        # Net business income = 10,000 - 42.80 - 5000 = 4,957.20
        self.assertAlmostEqual(pkg["pnl_summary"]["fno_net_business_income_inr"], 4957.20, places=2)
        self.assertIn("CHARTERED ACCOUNTANT TAX PREPARATION DOSSIER", pkg["markdown_dossier"])
        self.assertGreaterEqual(len(pkg["ca_review_questions"]), 5)


if __name__ == "__main__":
    unittest.main()
