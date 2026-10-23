"""AGI 1.7 OMEGA COMMAND — Indian Tax Accounting, Regulatory Framework & CA Compliance Engine.

Phase 17.15 Core Financial Infrastructure:
Authoritative tax classification, regulatory fee auditing, advance-tax scheduling,
turnover calculation under ICAI Guidance Notes, and exportable CA handoff packages.

Statutory Legal & Budgetary Grounding:
1. Financial Year (FY) & Assessment Year (AY) Calendar:
   - Indian Financial Year runs from 1 April to 31 March (e.g. FY 2026-27: 01-Apr-2026 to 31-Mar-2027).
   - Assessment Year is the immediately following year (e.g. AY 2027-28 for FY 2026-27).
   - Union Budget is presented annually on 1 February by the Union Finance Minister and enacted
     via the Finance Act, taking effect from 1 April (unless interim effective dates apply,
     such as 1 October 2024 for F&O STT hike).
   - Income-tax Act, 2025 governs Tax Year 2026-27 onwards; Income-tax Act, 1961 governs prior periods.

2. Income Classifications:
   - Equity Delivery Transactions:
     * Short-Term Capital Gains (STCG) u/s 111A: Taxed @ 20% post-Budget 2024 (prior 15%). Holding <= 12 months.
     * Long-Term Capital Gains (LTCG) u/s 112A: Taxed @ 12.5% post-Budget 2024 (prior 10%) on gains exceeding
       ₹1.25 Lakh exemption limit per financial year (prior ₹1.0 Lakh). Holding > 12 months.
   - Equity Intraday Trading:
     * Speculative Business Income under Section 43(5). Taxed at applicable personal slab rates.
     * Losses can only be set off against speculative profits; carried forward up to 4 Assessment Years.
   - Futures & Options (F&O) Trading:
     * Non-Speculative Business Income under Section 43(5)(d) (Section 43(5) proviso (d) read with Section 28).
     * Taxed at applicable personal slab rates.
     * Allowable business deductions: Brokerage, transaction charges, software/advisory fees,
       depreciation on trading equipment, internet/office expenses.
     * Business losses can be set off against any head of income except Salary in the current year,
       and carried forward up to 8 Assessment Years.
   - Dividends:
     * Income from Other Sources under Section 56(2)(i). Taxed at slab rates.
     * TDS u/s 194 @ 10% if dividend exceeds ₹5,000 in a financial year.

3. ICAI Guidance Note on Tax Audit u/s 44AB (Turnover Calculation):
   - Futures: Absolute sum of positive and negative differences (all profits + all losses).
   - Options: Absolute sum of positive and negative differences (all profits + all losses) +
     premium received on sale of options + difference in reverse trades.
   - Delivery: Gross sale turnover.

4. Section 44AB Tax Audit Applicability:
   - Digital transaction threshold: ₹10 Crore (where cash transactions <= 5% of turnover/receipts).
   - Presumptive taxation u/s 44AD: If turnover < ₹2/3 Crore and declared net profit is < 6% of digital turnover.

5. Advance Tax Compliance Calendar (Section 208 / 211):
   - Applicable if estimated net tax liability exceeds ₹10,000 in a financial year.
   - 15 June: >= 15% of advance tax.
   - 15 September: >= 45% of advance tax.
   - 15 December: >= 75% of advance tax.
   - 15 March: 100% of advance tax.
   - Interest u/s 234C for deferment of installments, u/s 234B for default if total paid < 90% by 31 March.

6. Income Tax Return (ITR) Deadlines:
   - Non-audit individuals: 31 July of the Assessment Year (ITR-2 or ITR-3).
   - Audit cases u/s 44AB: 31 October of the Assessment Year (Tax audit report in Form 3CD due 30 September).
   - Belated / Revised return: 31 December of the Assessment Year.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class TaxHead(str, Enum):
    """Statutory Heads of Income under Indian Income Tax Law."""
    EQUITY_STCG_111A = "EQUITY_STCG_111A"               # Short-Term Capital Gains u/s 111A (20% post-Budget 2024)
    EQUITY_LTCG_112A = "EQUITY_LTCG_112A"               # Long-Term Capital Gains u/s 112A (12.5% post-Budget 2024)
    INTRADAY_SPECULATIVE_43_5 = "INTRADAY_SPECULATIVE_43_5"  # Speculative Business Income u/s 43(5)
    FNO_NON_SPECULATIVE_43_5_D = "FNO_NON_SPECULATIVE_43_5_D"  # Non-Speculative Business Income u/s 43(5)(d)
    DIVIDEND_INCOME_56_2 = "DIVIDEND_INCOME_56_2"       # Income from Other Sources u/s 56(2)(i)
    UNCLASSIFIED = "UNCLASSIFIED_REQUIRES_CA_REVIEW"     # Flagged for professional Chartered Accountant review


class GoverningTaxAct(str, Enum):
    """Applicable statutory tax law version."""
    INCOME_TAX_ACT_1961 = "INCOME_TAX_ACT_1961"         # Historical & Transition Law (pre-Tax Year 2026-27)
    INCOME_TAX_ACT_2025 = "INCOME_TAX_ACT_2025"         # Enacted Law governing Tax Year 2026-27 onwards


@dataclass
class FinancialYearInfo:
    """Complete financial and assessment year representation."""
    financial_year: str       # e.g. "2026-27"
    assessment_year: str      # e.g. "2027-28"
    start_date: datetime.date
    end_date: datetime.date
    budget_presentation_date: datetime.date  # 1 Feb of preceding or start year
    governing_act: GoverningTaxAct
    stcg_rate_pct: float      # 20.0%
    ltcg_rate_pct: float      # 12.5%
    ltcg_exemption_inr: float # ₹1,25,000
    stt_options_sell_pct: float # 0.10% (Oct 2024 - Mar 2026), 0.15% (Apr 2026 onwards)
    tax_audit_turnover_limit_digital_inr: float # ₹10,00,00,000 (10 Cr)


def get_financial_year(dt: Optional[datetime.date] = None) -> FinancialYearInfo:
    """Resolves the authoritative Indian Financial Year and statutory parameters for any date."""
    if dt is None:
        dt = datetime.date(2026, 10, 16)

    year = dt.year
    month = dt.month

    if month >= 4:
        fy_start_year = year
        fy_end_year = year + 1
    else:
        fy_start_year = year - 1
        fy_end_year = year

    fy_str = f"{fy_start_year}-{str(fy_end_year)[-2:]}"
    ay_str = f"{fy_end_year}-{str(fy_end_year + 1)[-2:]}"
    start_d = datetime.date(fy_start_year, 4, 1)
    end_d = datetime.date(fy_end_year, 3, 31)
    budget_date = datetime.date(fy_start_year, 2, 1)

    # Law versioning: Income-tax Act 2025 governs Tax Year 2026-27 onwards
    if fy_start_year >= 2026:
        gov_act = GoverningTaxAct.INCOME_TAX_ACT_2025
        stcg_rate = 20.0
        ltcg_rate = 12.5
        ltcg_exempt = 125000.0
        stt_opt_sell = 0.15  # 2026 schedule: 0.15%
    elif fy_start_year == 2024:
        gov_act = GoverningTaxAct.INCOME_TAX_ACT_1961
        stcg_rate = 20.0     # Budget 2024 revised from 15% to 20% on 23 July 2024
        ltcg_rate = 12.5     # Budget 2024 revised from 10% to 12.5% on 23 July 2024
        ltcg_exempt = 125000.0 # Budget 2024 revised from 1L to 1.25L
        stt_opt_sell = 0.10  # 0.10% effective 1 Oct 2024
    else:
        gov_act = GoverningTaxAct.INCOME_TAX_ACT_1961
        stcg_rate = 15.0
        ltcg_rate = 10.0
        ltcg_exempt = 100000.0
        stt_opt_sell = 0.0625

    return FinancialYearInfo(
        financial_year=fy_str,
        assessment_year=ay_str,
        start_date=start_d,
        end_date=end_d,
        budget_presentation_date=budget_date,
        governing_act=gov_act,
        stcg_rate_pct=stcg_rate,
        ltcg_rate_pct=ltcg_rate,
        ltcg_exemption_inr=ltcg_exempt,
        stt_options_sell_pct=stt_opt_sell,
        tax_audit_turnover_limit_digital_inr=100000000.0,  # ₹10 Crore
    )


@dataclass
class NormalizedTradeEvent:
    """Auditable single trade transaction record for tax accounting."""
    trade_id: str
    trade_date: datetime.date
    symbol: str
    instrument_type: str  # OPTION, FUTURE, EQUITY_INTRADAY, EQUITY_DELIVERY
    side: str             # BUY, SELL
    quantity: int
    price: float
    turnover: float
    brokerage_inr: float
    stt_inr: float
    exchange_charges_inr: float
    gst_inr: float
    sebi_charges_inr: float
    stamp_duty_inr: float
    total_charges_inr: float
    realized_gross_pnl_inr: float = 0.0
    realized_net_pnl_inr: float = 0.0
    tax_head: TaxHead = TaxHead.UNCLASSIFIED
    holding_days: int = 0
    contract_note_ref: Optional[str] = None
    order_id: Optional[str] = None
    source_provenance: str = "HISTORICAL_REPLAY"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["trade_date"] = self.trade_date.isoformat()
        d["tax_head"] = self.tax_head.value
        return d


class IndianTaxAccountingEngine:
    """Authoritative Indian tax calculation and accounting reconciliation engine."""

    def __init__(self, target_financial_year: Optional[str] = None) -> None:
        self.fy_info = get_financial_year()
        if target_financial_year:
            # Parse custom FY e.g. "2026-27"
            try:
                start_yr = int(target_financial_year.split("-")[0])
                self.fy_info = get_financial_year(datetime.date(start_yr, 6, 1))
            except Exception:
                pass
        self.trades: List[NormalizedTradeEvent] = []
        self.expenses: List[Dict[str, Any]] = []

    def classify_trade(
        self,
        instrument_type: str,
        holding_days: int = 0,
        is_intraday: bool = True,
    ) -> TaxHead:
        """Classifies a financial transaction into its precise legal Income Tax head."""
        inst = instrument_type.upper().strip()

        if inst in ("OPTION", "OPTIONS", "INDEX_OPTION", "STOCK_OPTION"):
            return TaxHead.FNO_NON_SPECULATIVE_43_5_D
        elif inst in ("FUTURE", "FUTURES", "INDEX_FUTURE", "STOCK_FUTURE"):
            return TaxHead.FNO_NON_SPECULATIVE_43_5_D
        elif inst in ("EQUITY", "CASH", "STOCK"):
            if is_intraday:
                return TaxHead.INTRADAY_SPECULATIVE_43_5
            elif holding_days > 365:
                return TaxHead.EQUITY_LTCG_112A
            else:
                return TaxHead.EQUITY_STCG_111A
        elif inst == "DIVIDEND":
            return TaxHead.DIVIDEND_INCOME_56_2

        return TaxHead.UNCLASSIFIED

    def record_trade(self, trade: NormalizedTradeEvent) -> None:
        """Records a normalized trade event and determines its tax classification."""
        if trade.tax_head == TaxHead.UNCLASSIFIED:
            is_intra = trade.holding_days == 0
            trade.tax_head = self.classify_trade(
                trade.instrument_type,
                holding_days=trade.holding_days,
                is_intraday=is_intra,
            )
        self.trades.append(trade)

    def record_business_expense(
        self,
        category: str,
        amount_inr: float,
        description: str,
        invoice_ref: Optional[str] = None,
        date_incurred: Optional[datetime.date] = None,
    ) -> None:
        """Records an eligible Section 37 business expenditure for F&O business income."""
        self.expenses.append({
            "category": category,
            "amount_inr": round(float(amount_inr), 2),
            "description": description,
            "invoice_ref": invoice_ref,
            "date_incurred": (date_incurred or datetime.date(2026, 10, 16)).isoformat(),
        })

    def calculate_icai_turnover(self) -> Dict[str, float]:
        """Calculates authoritative tax audit turnover according to ICAI Guidance Notes."""
        fno_turnover = Decimal("0.0")
        speculative_turnover = Decimal("0.0")
        delivery_turnover = Decimal("0.0")

        for t in self.trades:
            pnl_abs = Decimal(str(abs(t.realized_gross_pnl_inr)))
            if t.tax_head == TaxHead.FNO_NON_SPECULATIVE_43_5_D:
                # ICAI Rule: Absolute PnL + Option Sell Premium
                fno_turnover += pnl_abs
                if t.side.upper() == "SELL" and "OPTION" in t.instrument_type.upper():
                    fno_turnover += Decimal(str(t.turnover))
            elif t.tax_head == TaxHead.INTRADAY_SPECULATIVE_43_5:
                # Intraday speculative turnover = Absolute sum of profits and losses
                speculative_turnover += pnl_abs
            elif t.tax_head in (TaxHead.EQUITY_STCG_111A, TaxHead.EQUITY_LTCG_112A):
                # Delivery turnover = Gross sale value
                if t.side.upper() == "SELL":
                    delivery_turnover += Decimal(str(t.turnover))

        total_turnover = fno_turnover + speculative_turnover + delivery_turnover
        return {
            "fno_turnover_inr": float(fno_turnover.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "speculative_turnover_inr": float(speculative_turnover.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "delivery_turnover_inr": float(delivery_turnover.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_turnover_inr": float(total_turnover.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        }

    def check_tax_audit_applicability(self) -> Dict[str, Any]:
        """Audits applicability of Section 44AB tax audit."""
        turnover_data = self.calculate_icai_turnover()
        total_to = turnover_data["total_turnover_inr"]
        limit = self.fy_info.tax_audit_turnover_limit_digital_inr

        is_audit_mandatory = total_to > limit
        audit_reason = ""
        if is_audit_mandatory:
            audit_reason = f"Total digital turnover ₹{total_to:,.2f} exceeds Section 44AB limit ₹{limit:,.2f} (₹10 Crore)."
        else:
            audit_reason = f"Total digital turnover ₹{total_to:,.2f} is within Section 44AB digital ceiling of ₹10 Crore."

        return {
            "is_audit_mandatory": is_audit_mandatory,
            "total_turnover_inr": total_to,
            "audit_threshold_inr": limit,
            "reason": audit_reason,
            "applicable_form": "Form 3CD / Form 3CB" if is_audit_mandatory else "Standard ITR-3 without Audit",
            "audit_report_due_date": f"30-Sep-{self.fy_info.assessment_year.split('-')[0]}",
            "itr_due_date": f"31-Oct-{self.fy_info.assessment_year.split('-')[0]}" if is_audit_mandatory else f"31-Jul-{self.fy_info.assessment_year.split('-')[0]}",
        }

    def calculate_taxable_pnl_summary(self) -> Dict[str, Any]:
        """Calculates categorized realized gains/losses, deductible expenses, and estimated liability."""
        stcg_pnl = Decimal("0.0")
        ltcg_pnl = Decimal("0.0")
        speculative_pnl = Decimal("0.0")
        fno_gross_pnl = Decimal("0.0")
        total_stt_paid = Decimal("0.0")
        total_brokerage_paid = Decimal("0.0")
        total_other_charges_paid = Decimal("0.0")

        for t in self.trades:
            net_pnl = Decimal(str(t.realized_net_pnl_inr))
            gross_pnl = Decimal(str(t.realized_gross_pnl_inr))
            total_stt_paid += Decimal(str(t.stt_inr))
            total_brokerage_paid += Decimal(str(t.brokerage_inr))
            other_chg = Decimal(str(t.exchange_charges_inr + t.gst_inr + t.sebi_charges_inr + t.stamp_duty_inr))
            total_other_charges_paid += other_chg

            if t.tax_head == TaxHead.EQUITY_STCG_111A:
                stcg_pnl += net_pnl
            elif t.tax_head == TaxHead.EQUITY_LTCG_112A:
                ltcg_pnl += net_pnl
            elif t.tax_head == TaxHead.INTRADAY_SPECULATIVE_43_5:
                speculative_pnl += net_pnl
            elif t.tax_head == TaxHead.FNO_NON_SPECULATIVE_43_5_D:
                fno_gross_pnl += gross_pnl

        # Deduct eligible expenses for F&O Business Income
        total_expenses = sum(Decimal(str(e["amount_inr"])) for e in self.expenses)
        total_trading_costs = total_brokerage_paid + total_other_charges_paid + total_stt_paid
        fno_net_business_income = fno_gross_pnl - total_trading_costs - total_expenses

        # Capital gains tax estimates
        tax_stcg = Decimal("0.0")
        if stcg_pnl > 0:
            tax_stcg = (stcg_pnl * Decimal(str(self.fy_info.stcg_rate_pct / 100.0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        tax_ltcg = Decimal("0.0")
        ltcg_exempt = Decimal(str(self.fy_info.ltcg_exemption_inr))
        if ltcg_pnl > ltcg_exempt:
            taxable_ltcg = ltcg_pnl - ltcg_exempt
            tax_ltcg = (taxable_ltcg * Decimal(str(self.fy_info.ltcg_rate_pct / 100.0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return {
            "financial_year": self.fy_info.financial_year,
            "assessment_year": self.fy_info.assessment_year,
            "governing_act": self.fy_info.governing_act.value,
            "equity_stcg_pnl_inr": float(stcg_pnl),
            "equity_ltcg_pnl_inr": float(ltcg_pnl),
            "speculative_intraday_pnl_inr": float(speculative_pnl),
            "fno_gross_pnl_inr": float(fno_gross_pnl),
            "fno_total_charges_inr": float(total_trading_costs),
            "fno_eligible_business_expenses_inr": float(total_expenses),
            "fno_net_business_income_inr": float(fno_net_business_income),
            "estimated_stcg_tax_inr": float(tax_stcg),
            "estimated_ltcg_tax_inr": float(tax_ltcg),
            "slab_taxable_business_income_inr": float(max(Decimal("0.0"), fno_net_business_income + speculative_pnl)),
            "note": "Final tax liability depends on personal income slabs, deductions u/s 80C-80U, and regime choice (New vs Old).",
        }

    def generate_advance_tax_schedule(self, estimated_annual_tax_inr: float) -> List[Dict[str, Any]]:
        """Generates the statutory Advance Tax schedule under Section 211."""
        est_tax = Decimal(str(max(0.0, estimated_annual_tax_inr)))
        fy_start_yr = self.fy_info.start_date.year

        # If estimated tax < ₹10,000, advance tax is not legally mandatory
        is_applicable = est_tax >= Decimal("10000.0")

        installments = [
            {
                "installment_number": 1,
                "due_date": f"15-Jun-{fy_start_yr}",
                "cumulative_pct_due": 15.0,
                "cumulative_amount_due_inr": float((est_tax * Decimal("0.15")).quantize(Decimal("0.01"))),
                "is_mandatory": is_applicable,
                "section": "Section 211(1)(b)",
            },
            {
                "installment_number": 2,
                "due_date": f"15-Sep-{fy_start_yr}",
                "cumulative_pct_due": 45.0,
                "cumulative_amount_due_inr": float((est_tax * Decimal("0.45")).quantize(Decimal("0.01"))),
                "is_mandatory": is_applicable,
                "section": "Section 211(1)(b)",
            },
            {
                "installment_number": 3,
                "due_date": f"15-Dec-{fy_start_yr}",
                "cumulative_pct_due": 75.0,
                "cumulative_amount_due_inr": float((est_tax * Decimal("0.75")).quantize(Decimal("0.01"))),
                "is_mandatory": is_applicable,
                "section": "Section 211(1)(b)",
            },
            {
                "installment_number": 4,
                "due_date": f"15-Mar-{fy_start_yr + 1}",
                "cumulative_pct_due": 100.0,
                "cumulative_amount_due_inr": float(est_tax.quantize(Decimal("0.01"))),
                "is_mandatory": is_applicable,
                "section": "Section 211(1)(b)",
            },
        ]
        return installments

    def generate_compliance_calendar(self) -> List[Dict[str, Any]]:
        """Builds an exhaustive compliance deadline calendar for the current Financial Year."""
        fy_start_yr = self.fy_info.start_date.year
        ay_yr = self.fy_info.end_date.year

        return [
            {
                "task": "Advance Tax Installment 1 (15%)",
                "due_date": f"2026-06-15",
                "authority": "Income Tax Department",
                "governing_section": "Section 211",
                "requires_ca_review": True,
            },
            {
                "task": "Advance Tax Installment 2 (45%)",
                "due_date": f"2026-09-15",
                "authority": "Income Tax Department",
                "governing_section": "Section 211",
                "requires_ca_review": True,
            },
            {
                "task": "Advance Tax Installment 3 (75%)",
                "due_date": f"2026-12-15",
                "authority": "Income Tax Department",
                "governing_section": "Section 211",
                "requires_ca_review": True,
            },
            {
                "task": "Advance Tax Installment 4 (100%)",
                "due_date": f"2027-03-15",
                "authority": "Income Tax Department",
                "governing_section": "Section 211",
                "requires_ca_review": True,
            },
            {
                "task": "ITR Filing for Non-Audit Individuals (ITR-2 / ITR-3)",
                "due_date": f"2027-07-31",
                "authority": "Income Tax Department",
                "governing_section": "Section 139(1)",
                "requires_ca_review": True,
            },
            {
                "task": "Tax Audit Report Submission (Form 3CD / 3CA / 3CB)",
                "due_date": f"2027-09-30",
                "authority": "Income Tax Department / ICAI",
                "governing_section": "Section 44AB",
                "requires_ca_review": True,
            },
            {
                "task": "ITR Filing for Tax Audit Assessees",
                "due_date": f"2027-10-31",
                "authority": "Income Tax Department",
                "governing_section": "Section 139(1)",
                "requires_ca_review": True,
            },
            {
                "task": "Belated or Revised ITR Filing",
                "due_date": f"2027-12-31",
                "authority": "Income Tax Department",
                "governing_section": "Section 139(4) / 139(5)",
                "requires_ca_review": True,
            },
        ]

    def generate_ca_handoff_package(self) -> Dict[str, Any]:
        """Compiles a complete, exportable Chartered Accountant handoff dossier."""
        turnover = self.calculate_icai_turnover()
        audit_status = self.check_tax_audit_applicability()
        pnl_summary = self.calculate_taxable_pnl_summary()
        compliance = self.generate_compliance_calendar()

        est_total_tax = pnl_summary["estimated_stcg_tax_inr"] + pnl_summary["estimated_ltcg_tax_inr"]
        advance_tax = self.generate_advance_tax_schedule(est_total_tax)

        ca_questions = [
            "Confirm applicability of Section 44AB vs Section 44AD presumptive scheme based on client total income.",
            "Verify whether STCG and LTCG cost of acquisition reflects grandfathering provisions u/s 112A where applicable.",
            "Confirm set-off of non-speculative F&O business losses against other income heads (excluding Salary).",
            "Review deductibility of shared home-office internet, electricity, and terminal depreciation under Section 37.",
            "Verify advance tax payment challans (ITNS 280) against TRACES AIS/TIS annual statement.",
        ]

        markdown_dossier = f"""# CHARTERED ACCOUNTANT TAX PREPARATION DOSSIER
**Financial Year:** {self.fy_info.financial_year} | **Assessment Year:** {self.fy_info.assessment_year}
**Governing Statute:** {self.fy_info.governing_act.value}
**Generated Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}
**Prepared For:** Operator Abhi (Personal Investment & Trading Accounts)

---

## 1. Executive Summary & ICAI Turnover Statement
- **F&O Non-Speculative Turnover (ICAI Guidance Note):** ₹{turnover['fno_turnover_inr']:,.2f}
- **Intraday Speculative Turnover:** ₹{turnover['speculative_turnover_inr']:,.2f}
- **Delivery Sale Turnover:** ₹{turnover['delivery_turnover_inr']:,.2f}
- **Total Combined Turnover:** ₹{turnover['total_turnover_inr']:,.2f}
- **Section 44AB Audit Threshold (Digital):** ₹{audit_status['audit_threshold_inr']:,.2f}
- **Audit Requirement Status:** **{'MANDATORY AUDIT' if audit_status['is_audit_mandatory'] else 'NO AUDIT REQUIRED (Within Digital Limits)'}**

---

## 2. Taxable Income & Gains Breakdown
| Head of Income | Statutory Section | Realized Net Result | Tax Treatment |
| :--- | :--- | :--- | :--- |
| **F&O Business Income** | Section 43(5)(d) | ₹{pnl_summary['fno_net_business_income_inr']:,.2f} | Slab Rates (Non-speculative Business) |
| **Intraday Speculative** | Section 43(5) | ₹{pnl_summary['speculative_intraday_pnl_inr']:,.2f} | Slab Rates (Loss set-off restricted) |
| **Equity STCG** | Section 111A | ₹{pnl_summary['equity_stcg_pnl_inr']:,.2f} | {self.fy_info.stcg_rate_pct}% Special Rate |
| **Equity LTCG** | Section 112A | ₹{pnl_summary['equity_ltcg_pnl_inr']:,.2f} | {self.fy_info.ltcg_rate_pct}% above ₹{self.fy_info.ltcg_exemption_inr:,.0f} |

---

## 3. Section 37 Eligible Business Expenses & Trading Costs
- **Total Statutory Friction & Brokerage:** ₹{pnl_summary['fno_total_charges_inr']:,.2f}
- **Declared Business Expenses (Software/Depreciation/Tools):** ₹{pnl_summary['fno_eligible_business_expenses_inr']:,.2f}

---

## 4. Key Questions for Chartered Accountant Review
"""
        for i, q in enumerate(ca_questions, 1):
            markdown_dossier += f"{i}. {q}\n"

        return {
            "financial_year": self.fy_info.financial_year,
            "assessment_year": self.fy_info.assessment_year,
            "governing_act": self.fy_info.governing_act.value,
            "turnover_statement": turnover,
            "tax_audit_status": audit_status,
            "pnl_summary": pnl_summary,
            "advance_tax_schedule": advance_tax,
            "compliance_calendar": compliance,
            "ca_review_questions": ca_questions,
            "markdown_dossier": markdown_dossier,
            "trade_records_count": len(self.trades),
            "expense_records_count": len(self.expenses),
        }
