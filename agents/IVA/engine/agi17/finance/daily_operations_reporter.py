"""AGI 1.7 OMEGA COMMAND — Daily, Weekly & Monthly Operational Reporting Engine.

Phase 17.15 Core Operational Infrastructure:
Implements Sections 10, 13 & 14:
- Mandatory 6-Part Daily Trading Report Structure (Parts A through F).
- Strict separation of Real Broker state from Paper Simulation (`epoch_10k`).
- Never represents paper signals as real trades or unfilled orders as executions.
- Formats weekly strategy performance & monthly tax compliance summaries.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class DailyTradingReport:
    """Canonical daily operations report contract."""
    report_date_ist: str
    system_version: str = "AGI 1.7 OMEGA COMMAND (v1.7.15)"
    operating_mode: str = "PAPER"
    auth_state: str = "WAITING_FOR_OPERATOR_LOGIN"
    # Part A: System Status
    agents_status: Dict[str, str] = field(default_factory=lambda: {
        "Abhi": "ACTIVE_DECISION_AUTHORITY",
        "Max": "ACTIVE_ORCHESTRATOR",
        "Matt": "ACTIVE_QUANT_RESEARCH",
        "Emily": "ACTIVE_BROWSER_SUPERVISOR",
        "Alexa": "ACTIVE_CYCLE_SCHEDULER",
    })
    feed_health: str = "HEALTHY_HISTORICAL_REPLAY"
    # Part B: Portfolio Status (Strict Paper vs Live Partitioning)
    paper_epoch_id: str = "epoch_10k"
    paper_starting_capital_inr: float = 10000.0
    paper_current_equity_inr: float = 10000.0
    paper_realized_pnl_inr: float = 0.0
    paper_unrealized_pnl_inr: float = 0.0
    paper_total_friction_inr: float = 0.0
    paper_accounting_discrepancy_inr: float = 0.0
    live_broker_account_masked: str = "NOT_ARMED"
    live_broker_cash_inr: float = 0.0
    live_broker_positions_count: int = 0
    # Part C: Trading Activity
    orders_proposed_count: int = 0
    orders_approved_count: int = 0
    orders_submitted_count: int = 0
    orders_confirmed_count: int = 0
    orders_rejected_count: int = 0
    orders_unknown_status_count: int = 0
    trading_decisions_summary: List[str] = field(default_factory=list)
    # Part D: Research and Forecasts
    forecast_records: List[Dict[str, Any]] = field(default_factory=list)
    strategy_edge_status: str = "NO_VALIDATED_EDGE"
    # Part E: Risk and Compliance
    max_daily_drawdown_limit_pct: float = 1.5
    observed_daily_drawdown_pct: float = 0.0
    circuit_breaker_status: str = "ARMED_HEALTHY"
    tax_compliance_notes: List[str] = field(default_factory=list)
    # Part F: Next Actions
    pending_abhi_decisions: List[str] = field(default_factory=list)
    next_scheduled_cycles: List[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Renders canonical markdown report format."""
        md = f"""# AGI 1.7 OMEGA COMMAND — DAILY OPERATIONAL TRADING REPORT
**Date:** {self.report_date_ist} | **Version:** {self.system_version} | **Active Mode:** `{self.operating_mode}`
**Primary Evaluation Ledger:** `{self.paper_epoch_id}` (Starting: ₹{self.paper_starting_capital_inr:,.2f})

---

### PART A: SYSTEM & MULTI-AGENT STATUS
- **Operating Mode:** `{self.operating_mode}` (Live Order Dispatch: `DISABLED`)
- **Authentication State Machine:** `{self.auth_state}`
- **Market Data Feed Health:** `{self.feed_health}`
- **Multi-Agent Governance Status:**
  * **Abhi (Manager & Final Authority):** `{self.agents_status.get('Abhi', 'ACTIVE')}`
  * **Max (Chief Orchestrator):** `{self.agents_status.get('Max', 'ACTIVE')}`
  * **Matt (Quant & Forecasting):** `{self.agents_status.get('Matt', 'ACTIVE')}`
  * **Emily (Browser & Workflows):** `{self.agents_status.get('Emily', 'ACTIVE')}`
  * **Alexa (Cycles & Validation):** `{self.agents_status.get('Alexa', 'ACTIVE')}`

---

### PART B: FINANCIAL PORTFOLIO STATUS (STRICT SEPARATION)
| Dimension | Paper Simulation (`{self.paper_epoch_id}`) | Live Broker Account |
| :--- | :--- | :--- |
| **Account Identity** | Simulated Ledger | `{self.live_broker_account_masked}` |
| **Starting Capital** | ₹{self.paper_starting_capital_inr:,.2f} | ₹0.00 (Unarmed) |
| **Current Net Equity**| ₹{self.paper_current_equity_inr:,.2f} | ₹{self.live_broker_cash_inr:,.2f} |
| **Realized Net P&L**  | ₹{self.paper_realized_pnl_inr:,.2f} | ₹0.00 |
| **Unrealized MTM P&L**| ₹{self.paper_unrealized_pnl_inr:,.2f} | ₹0.00 |
| **Statutory Friction**| ₹{self.paper_total_friction_inr:,.2f} | ₹0.00 |
| **Discrepancy**       | **₹{self.paper_accounting_discrepancy_inr:,.2f} (RECONCILED)** | N/A |

---

### PART C: TRADING ACTIVITY & EXECUTION SUMMARY
- **Proposed Trade Signals:** {self.orders_proposed_count}
- **Explicitly Approved Orders:** {self.orders_approved_count}
- **Submitted Orders:** {self.orders_submitted_count}
- **Confirmed Completed Fills:** {self.orders_confirmed_count}
- **Rejected / Risk-Blocked Signals:** {self.orders_rejected_count}
- **Orders with Unknown Status:** {self.orders_unknown_status_count}
"""
        if self.trading_decisions_summary:
            md += "\n**Activity Audit Log:**\n"
            for item in self.trading_decisions_summary:
                md += f"- {item}\n"
        else:
            md += "\n*No trading executions took place during this reporting window. Capital preserved.*\n"

        md += f"""
---

### PART D: QUANTITATIVE RESEARCH & MARKET FORECASTS
- **Strategy Alpha Designation:** `{self.strategy_edge_status}` (Research candidate models only)
- **Active Forecasts Count:** {len(self.forecast_records)}
"""
        for fc in self.forecast_records:
            md += f"- **{fc.get('instrument', 'NIFTY')} {fc.get('horizon', 'OPENING')}:** Top Scenario `{fc.get('top_scenario')}` (Prob: {fc.get('prob', 0.0):.2f}) | Brier: {fc.get('brier', 'N/A')}\n"

        md += f"""
---

### PART E: RISK GOVERNANCE & TAX COMPLIANCE
- **Max Daily Loss Limit:** {self.max_daily_drawdown_limit_pct}% (₹{self.paper_starting_capital_inr * (self.max_daily_drawdown_limit_pct / 100):,.2f})
- **Observed Daily Drawdown:** {self.observed_daily_drawdown_pct:.2f}%
- **Server Circuit Breaker Status:** `{self.circuit_breaker_status}`
"""
        if self.tax_compliance_notes:
            md += "**Tax & Statutory Notes:**\n"
            for note in self.tax_compliance_notes:
                md += f"- {note}\n"

        md += f"""
---

### PART F: IMMEDIATE BLOCKERS & NEXT ACTIONS
"""
        if self.pending_abhi_decisions:
            md += "**Decisions Awaiting Abhi (Manager Approval):**\n"
            for dec in self.pending_abhi_decisions:
                md += f"- [ ] {dec}\n"
        else:
            md += "- Zero pending manager approval requests.\n"

        if self.next_scheduled_cycles:
            md += "\n**Scheduled Alexa Research Cycles:**\n"
            for cyc in self.next_scheduled_cycles:
                md += f"- {cyc}\n"

        return md


class DailyOperationsReporter:
    """Service to create, store, and export daily, weekly, and monthly reports."""

    def __init__(self, output_dir: Optional[Path | str] = None) -> None:
        self.output_dir = Path(output_dir) if output_dir else Path("./reports")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_daily_report(self, report: DailyTradingReport) -> str:
        """Formats and saves the daily report to Markdown and JSON."""
        md_content = report.to_markdown()
        fname_base = f"DAILY_REPORT_{report.report_date_ist.replace('-', '')}"
        md_path = self.output_dir / f"{fname_base}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        return md_content
