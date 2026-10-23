"""Unit Test Suite for Phase 17.15 Multi-Agent Council, Operations Reporting & URL Audit.

Verifies:
1. 5-Agent Council structure (Abhi, Max, Matt, Emily, Alexa).
2. Abhi manager decision authority over risk and financial approvals.
3. Daily Trading Report 6-part standardized schema (Parts A through F).
4. Strict separation between paper simulation and live accounts in daily reports.
5. URL audit logging and secret redaction (never logging OTPs, PINs, auth codes).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.finance.multi_agent_council import (
    AgentRole,
    MultiAgentCouncilCoordinator,
    TaskStatus,
)
from agents.AGI_1_7.engine.agi17.finance.daily_operations_reporter import (
    DailyOperationsReporter,
    DailyTradingReport,
)
from agents.AGI_1_7.engine.agi17.finance.source_and_url_audit import (
    OFFICIAL_SOURCE_REGISTRY,
    URLAuditService,
)


class TestMultiAgentAndReporting(unittest.TestCase):
    """Authoritative test cases for council governance, reporting, and URL security."""

    def test_multi_agent_council_delegation_and_abhi_approval(self) -> None:
        """Verify task routing and Abhi manager authority over financial decisions."""
        council = MultiAgentCouncilCoordinator()

        # Max creates a high-risk policy task requiring Abhi approval
        task = council.create_task(
            title="Approve Risk Ceiling Revision",
            assigned_agent=AgentRole.MATT_QUANT,
            created_by=AgentRole.MAX_ORCHESTRATOR,
            description="Proposing risk limit change for high-volatility session",
            acceptance_criteria=["Quant backtest passed", "Risk bounded"],
            requires_abhi_approval=True,
        )
        self.assertEqual(task.status, TaskStatus.AWAITING_ABHI_APPROVAL)

        # Abhi approves the task
        task_approved = council.record_manager_decision(task.task_id, decision="APPROVED", manager_notes="Proceed with 0.5% cap")
        self.assertEqual(task_approved.status, TaskStatus.IN_PROGRESS)

        # Matt completes the task with evidence
        completed = council.complete_task(task.task_id, evidence_path="agents/AGI_1_7/reports/evidence.json", tests_added=5)
        self.assertEqual(completed.status, TaskStatus.COMPLETED)

        summary = council.get_council_summary()
        self.assertEqual(summary["completed_tasks"], 1)
        self.assertEqual(summary["agent_performance"]["MATT_QUANT"]["tests_added"], 5)

    def test_daily_trading_report_schema_generation(self) -> None:
        """Verify DailyTradingReport renders all 6 required parts with strict paper/live separation."""
        report = DailyTradingReport(
            report_date_ist="2026-10-16",
            operating_mode="PAPER",
            auth_state="WAITING_FOR_OPERATOR_LOGIN",
            paper_epoch_id="epoch_10k",
            paper_starting_capital_inr=10000.0,
            paper_current_equity_inr=10000.0,
            paper_realized_pnl_inr=0.0,
            paper_unrealized_pnl_inr=0.0,
            paper_total_friction_inr=0.0,
            paper_accounting_discrepancy_inr=0.0,
            orders_proposed_count=0,
            orders_approved_count=0,
            orders_submitted_count=0,
            orders_confirmed_count=0,
            strategy_edge_status="NO_VALIDATED_EDGE",
            pending_abhi_decisions=["Review CA Tax Package for FY 2026-27"],
            next_scheduled_cycles=["Alexa Cycle #14: Post-market historical replay verification"],
        )

        md = report.to_markdown()

        # Verify all 6 mandatory parts are present
        self.assertIn("PART A: SYSTEM & MULTI-AGENT STATUS", md)
        self.assertIn("PART B: FINANCIAL PORTFOLIO STATUS (STRICT SEPARATION)", md)
        self.assertIn("PART C: TRADING ACTIVITY & EXECUTION SUMMARY", md)
        self.assertIn("PART D: QUANTITATIVE RESEARCH & MARKET FORECASTS", md)
        self.assertIn("PART E: RISK GOVERNANCE & TAX COMPLIANCE", md)
        self.assertIn("PART F: IMMEDIATE BLOCKERS & NEXT ACTIONS", md)

        # Verify strict invariants
        self.assertIn("epoch_10k", md)
        self.assertIn("NO_VALIDATED_EDGE", md)
        self.assertIn("₹0.00 (RECONCILED)", md)
        self.assertIn("Abhi (Manager & Final Authority)", md)
        self.assertIn("Review CA Tax Package", md)

    def test_url_audit_service_and_secret_redaction(self) -> None:
        """Verify URL audit service logs navigation and completely redacts tokens/passwords."""
        audit_service = URLAuditService()

        sensitive_url = (
            "https://developer.paytmmoney.com/open-api/v1/auth?code=SECRET_AUTH_CODE_12345"
            "&access_token=SENSITIVE_BEARER_TOKEN_999&password=MY_SECRET_PWD&otp=123456"
        )
        entry = audit_service.audit_navigation(sensitive_url, callback_status="RECEIVED")

        # Invariant checks: Plain secrets must NOT be in audit log
        self.assertNotIn("SECRET_AUTH_CODE_12345", entry.initiated_url)
        self.assertNotIn("SENSITIVE_BEARER_TOKEN_999", entry.initiated_url)
        self.assertNotIn("MY_SECRET_PWD", entry.initiated_url)
        self.assertNotIn("123456", entry.initiated_url)

        self.assertIn("[REDACTED_AUTH_CODE]", entry.initiated_url)
        self.assertIn("[REDACTED_ACCESS_TOKEN]", entry.initiated_url)
        self.assertTrue(entry.is_approved_hostname)
        self.assertEqual(entry.destination_hostname, "developer.paytmmoney.com")

        # Unapproved hostname rejection
        unapproved_entry = audit_service.audit_navigation("https://malicious-phishing-site.com/login")
        self.assertFalse(unapproved_entry.is_approved_hostname)
        self.assertIn("UNAPPROVED_HOSTNAME", unapproved_entry.failure_reason or "")


if __name__ == "__main__":
    unittest.main()
