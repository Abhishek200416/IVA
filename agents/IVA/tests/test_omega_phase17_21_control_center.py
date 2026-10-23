"""AGI 1.7 OMEGA COMMAND — Phase 17.21 Verification Test Suite.

Tests the unified OMEGA Control Center:
1. AlgorithmCatalogService: Authoritative algorithm registry, schemas, and risk safety blocks.
2. AgentCatalogService: 106-agent observability across 16 functional families + coordinators.
3. OrchestrationServiceProvider: Durable TaskStore WAL tracking, DAG hierarchy, and cancellations.
4. DeploymentReadinessAssessor: 3-dimension readiness (Repo Publishing, Package, Financial) + 6-dimension scorecard.
5. Live HTTP endpoints on StandaloneDashboardServer (port 8088).
"""

from __future__ import annotations

import json
import os
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from agents.AGI_1_7.engine.agi17.runtime.omega_control_center import (
    AlgorithmCatalogService,
    AgentCatalogService,
    OrchestrationServiceProvider,
    DeploymentReadinessAssessor,
    get_algorithm_catalog,
    get_agent_catalog,
    get_orchestration_service,
    get_readiness_assessor,
)


class TestOmegaControlCenterServices(unittest.TestCase):
    """Unit tests for the control center core services."""

    def setUp(self):
        self.alg_catalog = AlgorithmCatalogService()
        self.ag_catalog = AgentCatalogService()
        self.orch_svc = OrchestrationServiceProvider()
        self.readiness = DeploymentReadinessAssessor()

    def test_01_algorithm_catalog_contains_real_algorithms(self):
        """Verify the catalog discovers the 11 authoritative algorithms."""
        algs = self.alg_catalog.list_algorithms()
        self.assertGreaterEqual(len(algs), 11)
        ids = [a["algorithm_id"] for a in algs]
        self.assertIn("STRAT-ORB-V1", ids)
        self.assertIn("STRAT-VOL-STRUCT-V1", ids)
        self.assertIn("STRAT-REGIME-SEL-V1", ids)
        self.assertIn("ALG-BAYES-KELLY-V1", ids)
        self.assertIn("ALG-KALMAN-SPREAD-V1", ids)
        self.assertIn("ALG-SABR-SVI-V1", ids)
        self.assertIn("ALG-NAKED-ITM-SHORT-V0", ids)

    def test_02_algorithm_parameter_contracts_and_risk_controls(self):
        """Verify each algorithm has parameters, contracts, and risk controls."""
        orb = self.alg_catalog.get_algorithm("STRAT-ORB-V1")
        self.assertIsNotNone(orb)
        self.assertIn("parameters", orb)
        self.assertIn("range_minutes", orb["parameters"])
        self.assertIn("risk_controls", orb)
        self.assertGreater(len(orb["risk_controls"]), 0)
        self.assertEqual(orb["category"], "Trend & Momentum")

    def test_03_algorithm_risk_safety_toggle_enforcement(self):
        """Verify fail-closed invariant: blocked algorithm cannot be enabled."""
        # ALG-NAKED-ITM-SHORT-V0 is permanently blocked by Risk Safety Policy
        with self.assertRaises((PermissionError, ValueError)) as ctx:
            self.alg_catalog.toggle_algorithm("ALG-NAKED-ITM-SHORT-V0", enabled=True)
        self.assertIn("risk safety policy", str(ctx.exception).lower())

        # Permitted algorithm toggles successfully
        res = self.alg_catalog.toggle_algorithm("STRAT-ORB-V1", enabled=False)
        self.assertEqual(res["new_status"], "DISABLED")
        res2 = self.alg_catalog.toggle_algorithm("STRAT-ORB-V1", enabled=True)
        self.assertEqual(res2["new_status"], "ENABLED")

    def test_04_agent_catalog_contains_106_roles(self):
        """Verify all 106 roles (6 executive/runtime + 100 specialists) are present."""
        agents = self.ag_catalog.list_agents()
        self.assertEqual(len(agents), 106)
        summary = self.ag_catalog.get_summary_metrics()
        self.assertEqual(summary["registered_roles_total"], 106)
        self.assertGreaterEqual(summary["functional_families_count"], 16)

        # Check key executive coordinators & daemons
        agent_ids = [a["agent_id"] for a in agents]
        self.assertIn("agi_omega_orchestrator", agent_ids)
        self.assertIn("alexa_strategy_coordinator", agent_ids)
        self.assertIn("emily_execution_warden", agent_ids)
        self.assertIn("max_quant_risk_specialist", agent_ids)
        self.assertIn("overlay_guardian_daemon", agent_ids)
        self.assertIn("standalone_dashboard_daemon", agent_ids)

        # Check sample embedded specialist from factory
        self.assertIn("plan_mission_decomposer", agent_ids)
        self.assertIn("swe_python_runtime_engineer", agent_ids)
        self.assertIn("data_sqlite_wal_architect", agent_ids)

    def test_05_agent_filtering_and_capabilities(self):
        """Verify agents can be filtered by family and runtime type."""
        software_specialists = self.ag_catalog.list_agents(family="Software Engineering")
        self.assertEqual(len(software_specialists), 10)
        for s in software_specialists:
            self.assertIn(s["runtime_type"], ["EMBEDDED_SPECIALIST", "IN_PROCESS_TOOL_WORKER"])
            self.assertGreater(len(s["capabilities"]), 0)
            self.assertGreater(len(s["allowed_tools"]), 0)

    def test_06_orchestration_tasks_lineage_and_store(self):
        """Verify tasks list and DAG structure."""
        tasks = self.orch_svc.list_tasks()
        self.assertGreater(len(tasks), 0)
        root_tasks = [t for t in tasks if not t.get("parent_task_id")]
        self.assertGreater(len(root_tasks), 0)
        self.assertEqual(root_tasks[0]["task_id"], "TSK-ROOT-ORCHESTRATOR")

        overview = self.orch_svc.get_overview()
        self.assertIn("total_tasks_recorded", overview)
        self.assertIn("counts_by_state", overview)

    def test_07_deployment_readiness_distinct_dimensions(self):
        """Verify readiness audits 3 separate dimensions honestly without fake claims."""
        assessment = self.readiness.assess_all()
        summary = assessment["summary"]

        # Repo publishing is not ready due to uncommitted working tree
        self.assertFalse(summary["repo_publishing_ready"])
        self.assertIn("/", summary["repo_publishing_score"])

        # Package readiness is not ready for remote headless due to Chrome CDP dependency
        self.assertFalse(summary["deployment_package_ready"])

        # Financial system readiness reflects live order lockout
        self.assertFalse(summary["financial_system_ready"])

        # Overall qualification is honest
        self.assertEqual(summary["overall_status"], "QUALIFIED_FOR_SUPERVISED_LOCAL_PAPER_TRADING")

        # 6-dimension scorecard exists
        scorecard = assessment["scorecard_six_dimensions"]
        self.assertEqual(len(scorecard), 6)
        self.assertIn("1_architecture_and_design", scorecard)
        self.assertIn("4_risk_management_and_accounting", scorecard)


class TestOmegaControlCenterHttpApi(unittest.TestCase):
    """End-to-end integration tests over local HTTP port 8088."""

    BASE_URL = "http://127.0.0.1:8088"

    def _get_json(self, path: str) -> dict:
        req = urllib.request.Request(f"{self.BASE_URL}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE_URL}{path}",
            data=data_bytes,
            headers={"Content-Type": "application/json", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def test_10_http_catalog_algorithms(self):
        """GET /api/catalog/algorithms returns 11 algorithms."""
        data = self._get_json("/api/catalog/algorithms")
        self.assertTrue(data["ok"])
        self.assertGreaterEqual(len(data["algorithms"]), 11)

    def test_11_http_catalog_algorithm_detail(self):
        """GET /api/catalog/algorithms/<id> returns rich contract."""
        data = self._get_json("/api/catalog/algorithms/STRAT-ORB-V1")
        self.assertTrue(data["ok"])
        self.assertEqual(data["algorithm"]["algorithm_id"], "STRAT-ORB-V1")

    def test_12_http_catalog_algorithm_toggle_safety_block(self):
        """POST /api/catalog/algorithms/<id>/toggle fails closed for blocked strategies."""
        # Attempt to enable permanently blocked strategy
        status, data = self._post_json("/api/catalog/algorithms/ALG-NAKED-ITM-SHORT-V0/toggle", {"enabled": True})
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])
        self.assertIn("Risk Safety Policy", data["error"])

    def test_13_http_catalog_agents(self):
        """GET /api/catalog/agents returns 106 roles with summary."""
        data = self._get_json("/api/catalog/agents")
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["agents"]), 106)
        self.assertEqual(data["summary"]["registered_roles_total"], 106)

    def test_14_http_catalog_agents_summary(self):
        """GET /api/catalog/agents/summary returns authoritative counts."""
        data = self._get_json("/api/catalog/agents/summary")
        self.assertTrue(data["ok"])
        self.assertEqual(data["registered_roles_total"], 106)
        self.assertGreaterEqual(data["functional_families_count"], 16)

    def test_15_http_orchestration_tasks(self):
        """GET /api/orchestration/tasks returns tracked DAG tasks."""
        data = self._get_json("/api/orchestration/tasks")
        self.assertTrue(data["ok"])
        self.assertGreater(len(data["tasks"]), 0)

    def test_16_http_release_readiness(self):
        """GET /api/release/readiness returns 3 dimensions + 6-dimension scorecard."""
        data = self._get_json("/api/release/readiness")
        self.assertTrue(data["ok"])
        self.assertIn("summary", data)
        self.assertIn("scorecard_six_dimensions", data)
        self.assertIn("items", data)
        self.assertEqual(data["summary"]["overall_status"], "QUALIFIED_FOR_SUPERVISED_LOCAL_PAPER_TRADING")


if __name__ == "__main__":
    unittest.main()
