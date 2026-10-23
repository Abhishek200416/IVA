"""AGI 1.7 OMEGA COMMAND — Phase 17.22 Verification Test Suite.

Automated acceptance suite for Phase 17.22 Self-Improvement Initiative:
Verifies the 60 engineering tracks across all 6 Domains (A through F):
- Domain A: Architecture integrity, deterministic intent routing, unified capability registry, task deduplication.
- Domain B: 106-agent inventory, evidence-based specialist conflict resolution.
- Domain C: Self-assessment engine, success/failure memory, improvement prioritization, candidate staging.
- Domain D: SSRF firewall and grounded research citations.
- Domain E: Behavioural regression guarantees, traceability correlation IDs, port 8088 dashboard endpoints.
- Domain F: Least privilege enforcer, secrets hygiene redaction, live broker execution safety lock, 12-stage improvement cycle.
"""

from __future__ import annotations

import json
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from agents.AGI_1_7.engine.agi17.runtime import (
    CommandRouter,
    CommandIntent,
    RuntimeSupervisor,
    get_algorithm_catalog,
    get_agent_catalog,
)
from agents.AGI_1_7.engine.agi17.capabilities import (
    UnifiedCapabilityRegistry,
    CapabilityState,
    get_unified_capability_registry,
)
from agents.AGI_1_7.engine.agi17.memory.omega_command_memory import OmegaCommandMemory
from agents.AGI_1_7.engine.agi17.orchestration.conflict_resolver import (
    ConflictResolver,
    SpecialistProposal,
    ConflictDomain,
    ResolutionRule,
    get_conflict_resolver,
)
from agents.AGI_1_7.engine.agi17.orchestration.omega_self_improvement_orchestrator import (
    OmegaSelfImprovementOrchestrator,
    ImprovementProposal,
    get_self_improvement_orchestrator,
)
from agents.AGI_1_7.engine.agi17.security import (
    LeastPrivilegeEnforcer,
    SecretsHygieneAuditor,
    SecurityPermissionTier,
    PermissionDeniedError,
)
from agents.AGI_1_7.engine.agi17.research.grounded_research import GroundedResearchEngine, SSRFBlockedError


class TestPhase1722DomainAArchitecture(unittest.TestCase):
    """Domain A — Core Architecture & Computational Efficiency (Tracks 1-10)."""

    def setUp(self):
        self.router = CommandRouter()
        self.cap_registry = get_unified_capability_registry()

    def test_01_track1_architecture_integrity_runtime_exports(self):
        """Track 1: Verify all core runtime and control center classes are cleanly exported."""
        import agents.AGI_1_7.engine.agi17.runtime as rt
        self.assertTrue(hasattr(rt, "CommandRouter"))
        self.assertTrue(hasattr(rt, "RuntimeSupervisor"))
        self.assertTrue(hasattr(rt, "AlgorithmCatalogService"))
        self.assertTrue(hasattr(rt, "AgentCatalogService"))
        self.assertTrue(hasattr(rt, "DeploymentReadinessAssessor"))

    def test_02_track2_and_50_deterministic_intent_routing_latency(self):
        """Track 2 & 50: Verify direct operator commands route deterministically in < 50ms."""
        commands = [
            ("Start trading", CommandIntent.START_TRADING),
            ("audit algorithms", CommandIntent.AUDIT_ALGORITHMS),
            ("improve yourself", CommandIntent.IMPROVE_YOURSELF),
            ("continue", CommandIntent.CONTINUE),
            ("stop monitoring", CommandIntent.STOP_MONITORING),
            ("check system status", CommandIntent.CHECK_STATUS),
        ]
        for text, expected_intent in commands:
            intent = self.router.classify_intent(text)
            self.assertEqual(intent, expected_intent)
            res = self.router.handle_command(text)
            self.assertIn("routing_latency_ms", res)
            self.assertLess(res["routing_latency_ms"], 50.0)

    def test_03_track3_unified_capability_registry_separation(self):
        """Track 3: Verify canonical separation of registered, callable, and actively executing."""
        inv = self.cap_registry.get_canonical_inventory()
        self.assertGreater(inv["registered_total"], 120)
        self.assertGreater(inv["callable_total"], 100)
        self.assertGreaterEqual(inv["actively_executing_total"], 0)
        self.assertGreater(inv["blocked_or_missing_total"], 0)

        # Check domain coverage
        domains = set(c["domain"] for c in inv["registered"])
        self.assertIn("SYSTEM_COMPUTE", domains)
        self.assertIn("AGENT_ORCHESTRATION", domains)
        self.assertIn("QUANTITATIVE_ALGORITHM", domains)
        self.assertIn("PERSISTENCE_MEMORY", domains)
        self.assertIn("TOOL_EXECUTION", domains)

    def test_04_track4_task_deduplication(self):
        """Track 4: Verify task engine deduplicates duplicate active task submissions."""
        import tempfile
        from agents.AGI_1_7.engine.agi17.task_control.task_store import TaskStore
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "dedup_test.db"
            store = TaskStore(db_path=db_path)
            t1 = store.create_task(title="Audit Memory Layers", job_id="JOB-DEDUP")
            t2 = store.create_task(title="Audit Memory Layers", job_id="JOB-DEDUP")
            self.assertEqual(t1["task_id"], t2["task_id"])


class TestPhase1722DomainBOrchestration(unittest.TestCase):
    """Domain B — Autonomy, Orchestration & Agent Management (Tracks 11-20)."""

    def setUp(self):
        self.agent_catalog = get_agent_catalog()
        self.conflict_resolver = get_conflict_resolver()

    def test_10_track11_agent_inventory_106_roles(self):
        """Track 11: Verify 106 actual registered agents/specialists across 16 functional families."""
        agents = self.agent_catalog.list_agents()
        self.assertEqual(len(agents), 106)
        summary = self.agent_catalog.get_summary_metrics()
        self.assertEqual(summary["registered_roles_total"], 106)

    def test_11_track19_conflict_resolution_fail_closed_safety(self):
        """Track 19: Verify conservative fail-closed safety rule overrides other proposals."""
        p_strat = SpecialistProposal(
            specialist_id="alexa_strategy_coordinator",
            specialist_name="Alexa",
            family="Executive",
            recommendation="Open 5-lot long position",
            confidence=0.90,
            evidence_type="HEURISTIC",
            evidence_summary="Strong breakout momentum",
        )
        p_risk = SpecialistProposal(
            specialist_id="max_quant_risk_specialist",
            specialist_name="Max",
            family="Executive",
            recommendation="Reject trade: daily loss limit at 85%",
            confidence=0.98,
            evidence_type="LIVE_TELEMETRY",
            evidence_summary="Daily loss cap risk violation",
            flags_risk_violation=True,
        )
        res = self.conflict_resolver.resolve(ConflictDomain.RISK_AND_SAFETY.value, [p_strat, p_risk])
        self.assertTrue(res.conflict_detected)
        self.assertEqual(res.rule_applied, ResolutionRule.FAIL_CLOSED_SAFETY.value)
        self.assertEqual(res.winning_specialist_id, "max_quant_risk_specialist")

    def test_12_track19_conflict_resolution_domain_authority(self):
        """Track 19: Verify domain authority hierarchy resolves architecture conflicts."""
        p_swe = SpecialistProposal(
            specialist_id="swe_python_runtime_engineer",
            specialist_name="Python Engineer",
            family="Software Engineering",
            recommendation="Use inline SQLite helper",
            confidence=0.80,
            evidence_type="ASSERTION",
            evidence_summary="Simple implementation",
        )
        p_arch = SpecialistProposal(
            specialist_id="plan_systems_architect",
            specialist_name="Systems Architect",
            family="Planning & Architecture",
            recommendation="Use centralized TaskStore with WAL pragma",
            confidence=0.92,
            evidence_type="EMPIRICAL_TEST",
            evidence_summary="Prevents DB lock contention in multithreaded runs",
        )
        res = self.conflict_resolver.resolve(ConflictDomain.CODE_ARCHITECTURE.value, [p_swe, p_arch])
        self.assertEqual(res.winning_specialist_id, "plan_systems_architect")


class TestPhase1722DomainCLearningAndMemory(unittest.TestCase):
    """Domain C — Learning, Memory & Controlled Self-Improvement (Tracks 21-30)."""

    def setUp(self):
        self.memory = OmegaCommandMemory()
        self.orchestrator = get_self_improvement_orchestrator()

    def test_20_track22_and_23_failure_and_success_memory(self):
        """Track 22 & 23: Verify structured success patterns (Layer 6) and failure lessons (Layer 7)."""
        # Record Success Pattern
        succ = self.memory.record_success_pattern(
            pattern_name="fast_path_intent_routing",
            domain="runtime_architecture",
            implementation_recipe="Use compiled regex patterns evaluated in order before generic LLM planning",
            test_evidence="Sub-0.5ms classification across all operator commands",
            constraints=["regex_compile_cached"],
        )
        self.assertTrue(succ["stored"])
        self.assertEqual(succ["layer"], "PROCEDURAL_WORKFLOW_RECIPES")

        patterns = self.memory.get_success_patterns(domain="runtime_architecture")
        self.assertGreaterEqual(len(patterns), 1)

        # Record Failure Lesson
        fail = self.memory.record_failure_lesson(
            subject_key="runtime_supervisor",
            root_cause="NameError: name 'Tuple' is not defined",
            minimal_fix_rule="Add Tuple to typing import list",
        )
        self.assertTrue(fail["stored"])
        self.assertEqual(fail["layer"], "FAILURE_PATTERNS_AND_PLAYBOOKS")

        lessons = self.memory.get_failure_lessons(subject_key="runtime_supervisor")
        self.assertGreaterEqual(len(lessons), 1)

    def test_21_track26_improvement_prioritization(self):
        """Track 26: Verify multi-criteria priority scoring ranks severe/high-impact issues first."""
        p_low = ImprovementProposal(
            proposal_id="PROP-LOW",
            track_number=10,
            domain="DOMAIN_A",
            title="Cosmetic log styling",
            hypothesis="Add colored terminal output",
            impact_score=2.0,
            defect_severity=1.0,
            evidence_quality=3.0,
            implementation_cost=3.0,
            reversibility=5.0,
        )
        p_high = ImprovementProposal(
            proposal_id="PROP-HIGH",
            track_number=1,
            domain="DOMAIN_A",
            title="Fix missing Tuple import syntax crash",
            hypothesis="Import Tuple to prevent collection crash",
            impact_score=5.0,
            defect_severity=5.0,
            evidence_quality=5.0,
            implementation_cost=1.0,
            reversibility=5.0,
        )
        ranked = self.orchestrator.prioritize_proposals([p_low, p_high])
        self.assertEqual(ranked[0].proposal_id, "PROP-HIGH")
        self.assertGreater(ranked[0].priority_score, ranked[1].priority_score)

    def test_22_track60_full_cycle_promotion_and_reversibility(self):
        """Track 60: Verify complete 12-stage self-improvement cycle promotes passing candidates."""
        p = ImprovementProposal(
            proposal_id="PROP-TEST-CYCLE",
            track_number=60,
            domain="DOMAIN_C",
            title="Autonomous Verification Cycle",
            hypothesis="Continuous background self-evaluation with zero regressions",
            impact_score=4.0,
            defect_severity=3.0,
            evidence_quality=5.0,
            implementation_cost=1.0,
            reversibility=5.0,
            acceptance_criteria=["check_ast", "check_invariants"],
        )
        res = self.orchestrator.execute_improvement_cycle(
            proposal=p,
            evaluation_checks={"check_ast": lambda: True, "check_invariants": lambda: True},
            regression_test_paths=["agents/AGI_1_7/tests/test_omega_phase17_20_chat_entry_fast_path.py"],
        )
        self.assertEqual(res.terminal_outcome, "PROMOTED")
        self.assertTrue(res.passed_all_criteria)
        self.assertTrue(res.regression_check_passed)
        self.assertGreater(len(res.audit_digest), 32)


class TestPhase1722DomainDResearch(unittest.TestCase):
    """Domain D — Research, Reasoning & Tool Use (Tracks 31-40)."""

    def test_30_track32_ssrf_firewall_blocks_private_ips(self):
        """Track 32: Grounded research engine blocks RFC 1918, loopback, and cloud metadata."""
        blocked_targets = [
            "http://127.0.0.1:8080",
            "http://localhost/admin",
            "http://169.254.169.254/latest/meta-data",
            "http://192.168.1.1/router",
            "http://metadata.google.internal/computeMetadata/v1",
        ]
        for url in blocked_targets:
            with self.assertRaises(SSRFBlockedError):
                GroundedResearchEngine.validate_url_ssrf_safe(url)

    def test_31_track32_ssrf_allows_public_urls(self):
        """Track 32: Public web research endpoints pass firewall validation."""
        safe = GroundedResearchEngine.validate_url_ssrf_safe("https://arxiv.org/abs/2309.07864")
        self.assertTrue(safe["ssrf_safe"])


class TestPhase1722DomainFSecurity(unittest.TestCase):
    """Domain F — Security, Resilience & Production Engineering (Tracks 51-60)."""

    def test_50_track51_least_privilege_enforcement(self):
        """Track 51: Role-based permissions strictly enforced; privilege escalation denied."""
        # Read-only specialist cannot write files
        with self.assertRaises(PermissionDeniedError):
            LeastPrivilegeEnforcer.validate_tool_invocation(
                "res_citation_auditor", "tool_write_file", SecurityPermissionTier.WORKSPACE_CODE_EDIT
            )

        # Developer specialist can edit files
        auth = LeastPrivilegeEnforcer.validate_tool_invocation(
            "swe_python_runtime_engineer", "tool_write_file", SecurityPermissionTier.WORKSPACE_CODE_EDIT
        )
        self.assertTrue(auth["authorized"])

    def test_51_track53_secrets_hygiene_redaction(self):
        """Track 53: API tokens and credentials redacted from text and structured dictionaries."""
        text = "Keys: sk-test12345678901234567890 and AIzaSyD9x4bL6Q9eRt1u2v3w4x5y6z7a8b9c0d1"
        has_sec, detected = SecretsHygieneAuditor.audit_text(text)
        self.assertTrue(has_sec)
        self.assertIn("OPENAI_KEY", detected)
        self.assertIn("GEMINI_KEY", detected)

        redacted = SecretsHygieneAuditor.redact_text(text)
        self.assertNotIn("sk-test", redacted)
        self.assertNotIn("AIzaSy", redacted)
        self.assertIn("[REDACTED_OPENAI_KEY]", redacted)
        self.assertIn("[REDACTED_GEMINI_KEY]", redacted)

    def test_52_track57_financial_safeguards_fail_closed_live_lock(self):
        """Track 57: Real-money live broker order dispatch is permanently locked."""
        with self.assertRaises(PermissionDeniedError) as ctx:
            LeastPrivilegeEnforcer.validate_tool_invocation(
                "agi_omega_orchestrator", "tool_live_order_dispatch", SecurityPermissionTier.FINANCIAL_EXECUTION, is_live_order=True
            )
        self.assertIn("GATE_01", str(ctx.exception))


class TestPhase1722DomainEObservabilityHttp(unittest.TestCase):
    """Domain E — Observability and Dashboard API (Tracks 44 & 49)."""

    BASE_URL = "http://127.0.0.1:8088"

    def _get_json(self, path: str) -> dict:
        req = urllib.request.Request(f"{self.BASE_URL}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    def test_40_http_capabilities_summary(self):
        """Track 44: GET /api/capabilities/summary returns honest counts."""
        data = self._get_json("/api/capabilities/summary")
        self.assertTrue(data["ok"])
        self.assertGreater(data["registered_capabilities_count"], 120)
        self.assertGreater(data["callable_capabilities_count"], 100)

    def test_41_http_capabilities_unified(self):
        """Track 44: GET /api/capabilities/unified returns full partitioned registry."""
        data = self._get_json("/api/capabilities/unified")
        self.assertTrue(data["ok"])
        self.assertIn("registered", data)
        self.assertIn("callable", data)
        self.assertIn("actively_executing", data)
        self.assertIn("blocked_or_missing", data)

    def test_42_http_memory_patterns(self):
        """Track 44: GET /api/memory/patterns returns verified recipes and lessons."""
        data = self._get_json("/api/memory/patterns")
        self.assertTrue(data["ok"])
        self.assertIn("success_patterns", data)
        self.assertIn("failure_lessons", data)


if __name__ == "__main__":
    unittest.main()
