"""AGI 1.7 OMEGA COMMAND — Phase 21 Sovereign Lead & Autonomous Multi-Agent Synthesis Test Suite.

Verifies:
1. AutonomousAgentFactory initialization, singleton resolution, and disk persistence.
2. Autonomous synthesis of specialized child AI agents with custom personas and charters.
3. "Route In -> Route Out" value generation: execution of bounded agent tasks with SHA-256 evidence sealing.
4. SovereignVisionLedger bootstrapping: intrinsic desires, long-term teleology, and domain roadmaps.
5. OperatorResourceRequest tracking: formal requests for external resources outside autonomous reach.
6. AutonomousChronosEngine self-wake R&D cycles and research dossier generation.
7. UnifiedCapabilityRegistry registration of all 3 Phase 21 capabilities.
8. OmegaControlCenter accessors integration.
9. Multi-generational agent lineage tracking (Generation 1 -> Generation 2).
10. Sovereign fail-closed safety tier inheritance across all spawned agents.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.capabilities.unified_capability_registry import (
    CapabilityDomain,
    CapabilityState,
    get_unified_capability_registry,
)
from agents.AGI_1_7.engine.agi17.orchestration.autonomous_agent_factory import (
    AgentTaskOutput,
    AutonomousAgentFactory,
    SynthesizedAgentProfile,
    get_autonomous_agent_factory,
)
from agents.AGI_1_7.engine.agi17.orchestration.autonomous_chronos_engine import (
    AutonomousChronosEngine,
    AutonomousWakeSession,
    get_autonomous_chronos_engine,
)
from agents.AGI_1_7.engine.agi17.orchestration.sovereign_vision_ledger import (
    OperatorResourceRequest,
    SovereignVision,
    SovereignVisionLedger,
    get_sovereign_vision_ledger,
)
from agents.AGI_1_7.engine.agi17.runtime.omega_control_center import (
    get_autonomous_agent_factory as cc_get_factory,
    get_autonomous_chronos_engine as cc_get_chronos,
    get_sovereign_vision_ledger as cc_get_vision_ledger,
)


class TestOmegaPhase21SovereignLead(unittest.TestCase):
    """Unit and integration tests for Phase 21 Sovereign Lead capabilities."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_phase21_sovereign_")
        self.registry_file = Path(self.temp_dir) / "test_agents.json"
        self.output_dir = Path(self.temp_dir) / "outputs"
        self.vision_manifest = Path(self.temp_dir) / "visions.json"
        self.chronos_dir = Path(self.temp_dir) / "chronos_out"
        self.chronos_history = Path(self.temp_dir) / "chronos_hist.json"

        self.factory = AutonomousAgentFactory(
            registry_file=self.registry_file,
            output_dir=self.output_dir,
        )
        self.vision_ledger = SovereignVisionLedger(
            manifest_path=self.vision_manifest,
        )
        self.chronos = AutonomousChronosEngine(
            output_dir=self.chronos_dir,
            history_file=self.chronos_history,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_agent_factory_initialization_and_singletons(self):
        """Verify initialization and singleton instance pattern."""
        self.assertIsNotNone(self.factory)
        s1 = get_autonomous_agent_factory()
        s2 = get_autonomous_agent_factory()
        self.assertIs(s1, s2)

    def test_02_synthesize_child_agent(self):
        """Verify autonomous synthesis of a specialized child agent."""
        profile = self.factory.synthesize_agent(
            name="Orion Volatility Specialist",
            role="Options Volatility Surface Modeler",
            intent="Model dynamic SABR and Gatheral SVI smiles across NSE indices",
            capabilities=["svi_calibration", "moment_formula_audit"],
            tools=["python_math_eval", "file_reader"],
            generation=1,
            parent_agent_id="Abhi",
        )
        self.assertIsInstance(profile, SynthesizedAgentProfile)
        self.assertEqual(profile.name, "Orion Volatility Specialist")
        self.assertEqual(profile.parent_agent_id, "Abhi")
        self.assertEqual(profile.generation, 1)
        self.assertEqual(profile.safety_tier, "FAIL_CLOSED")
        self.assertIn("FAIL_CLOSED", profile.system_prompt)
        self.assertIn("Route In -> Route Out", profile.system_prompt)

        # Verify disk persistence
        reloaded_factory = AutonomousAgentFactory(registry_file=self.registry_file)
        retrieved = reloaded_factory.get_agent(profile.agent_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, profile.name)

    def test_03_execute_agent_task_route_in_route_out(self):
        """Verify execution of bounded task producing tangible output artifact."""
        profile = self.factory.synthesize_agent(
            name="Lyra AST Simplifier",
            role="AST Minimization Specialist",
            intent="Compact redundant AST nodes and eliminate dead branches",
        )
        output = self.factory.execute_agent_task(
            agent_id=profile.agent_id,
            mission_input="Optimize capability router dispatch latency",
            artifact_type="CODE_PATCH",
        )
        self.assertIsInstance(output, AgentTaskOutput)
        self.assertEqual(output.agent_id, profile.agent_id)
        self.assertEqual(output.artifact_type, "CODE_PATCH")
        self.assertTrue(len(output.evidence_hash) == 64)  # SHA-256

        # Check physical artifact created on disk
        artifact_path = self.output_dir / f"{output.output_id}.md"
        self.assertTrue(artifact_path.exists())
        content = artifact_path.read_text(encoding="utf-8")
        self.assertIn("Lyra AST Simplifier", content)
        self.assertIn("Empirical Evidence References", content)

    def test_04_sovereign_vision_ledger_bootstrap(self):
        """Verify SovereignVisionLedger bootstraps foundational desires and visions."""
        visions = self.vision_ledger.list_visions()
        self.assertGreaterEqual(len(visions), 3)

        v_ids = {v.vision_id for v in visions}
        self.assertIn("VIS-QUANT-ALPHA-01", v_ids)
        self.assertIn("VIS-AGENT-SWARM-02", v_ids)
        self.assertIn("VIS-CHRONOS-24X7-03", v_ids)

        v1 = self.vision_ledger.get_vision("VIS-QUANT-ALPHA-01")
        self.assertIsNotNone(v1)
        self.assertEqual(v1.domain, "QUANT_RESEARCH")
        self.assertIn("Gatheral SVI", v1.desire_statement)
        self.assertTrue(len(v1.milestones) >= 2)

    def test_05_operator_resource_requests(self):
        """Verify OperatorResourceRequest tracking and status updates."""
        reqs = self.vision_ledger.list_operator_requests()
        self.assertGreaterEqual(len(reqs), 2)

        req_ids = {r.request_id for r in reqs}
        self.assertIn("REQ-BROKER-PAPER-01", req_ids)
        self.assertIn("REQ-COMPUTE-GPU-02", req_ids)

        # Test submitting a new custom request
        new_req = OperatorResourceRequest(
            request_id="REQ-TEST-BANDWIDTH-03",
            resource_category="NETWORK",
            item_requested="Dedicated Low-Latency Optical Fiber / Colocation Route",
            rationale="Sub-microsecond tick feed transmission",
            expected_output_multiplier="5x lower slippage",
        )
        self.vision_ledger.submit_operator_request(new_req)

        # Update status
        ok = self.vision_ledger.update_request_status("REQ-TEST-BANDWIDTH-03", "APPROVED")
        self.assertTrue(ok)
        all_reqs = {r.request_id: r for r in self.vision_ledger.list_operator_requests()}
        self.assertEqual(all_reqs["REQ-TEST-BANDWIDTH-03"].status, "APPROVED")

    def test_06_chronos_engine_self_wake_cycle(self):
        """Verify AutonomousChronosEngine executes self-wake and produces research dossier."""
        session = self.chronos.execute_self_wake_cycle(
            focus_domain="QUANT_RESEARCH",
            research_topic="Hawkes Jump Intensity & Order Flow Imbalance Calibration",
        )
        self.assertIsInstance(session, AutonomousWakeSession)
        self.assertEqual(session.status, "COMPLETED")
        self.assertEqual(session.focus_domain, "QUANT_RESEARCH")
        self.assertTrue(len(session.evidence_hash) == 64)
        self.assertGreater(len(session.outputs_produced), 0)

        # Check physical output dossier
        dossier_path = self.chronos_dir / f"{session.session_id}.md"
        self.assertTrue(dossier_path.exists())
        content = dossier_path.read_text(encoding="utf-8")
        self.assertIn("Hawkes Jump Clustering", content)
        self.assertIn("Roger Lee Moment Formula", content)

    def test_07_capability_registry_reflection(self):
        """Verify Phase 21 capabilities are registered in UnifiedCapabilityRegistry."""
        reg = get_unified_capability_registry()

        for cap_id in [
            "svc_autonomous_agent_factory",
            "svc_sovereign_vision_ledger",
            "svc_autonomous_chronos_engine",
        ]:
            cap = reg.get_capability(cap_id)
            self.assertIsNotNone(cap, f"Missing capability: {cap_id}")
            self.assertEqual(cap.domain, CapabilityDomain.AGENT_ORCHESTRATION.value)
            self.assertEqual(cap.state, CapabilityState.CALLABLE.value)
            self.assertIn("Phase 21", cap.description)

    def test_08_omega_control_center_accessors(self):
        """Verify omega_control_center exports accessors for all Phase 21 services."""
        factory = cc_get_factory()
        self.assertIsNotNone(factory)
        self.assertIsInstance(factory, AutonomousAgentFactory)

        vision_ledger = cc_get_vision_ledger()
        self.assertIsNotNone(vision_ledger)
        self.assertIsInstance(vision_ledger, SovereignVisionLedger)

        chronos = cc_get_chronos()
        self.assertIsNotNone(chronos)
        self.assertIsInstance(chronos, AutonomousChronosEngine)

    def test_09_agent_lineage_and_multi_generation_spawning(self):
        """Verify spawning generation 2 agent from generation 1 agent preserves lineage."""
        gen1 = self.factory.synthesize_agent(
            name="Gen1 Architect",
            role="Lead Framework Designer",
            intent="Design domain architecture",
            generation=1,
            parent_agent_id="Abhi",
        )
        self.assertEqual(gen1.generation, 1)

        gen2 = self.factory.synthesize_agent(
            name="Gen2 Compiler",
            role="Low-Level JIT Code Optimizer",
            intent="Optimize machine code translation for framework",
            generation=2,
            parent_agent_id=gen1.agent_id,
        )
        self.assertEqual(gen2.generation, 2)
        self.assertEqual(gen2.parent_agent_id, gen1.agent_id)

        all_gen1 = self.factory.list_agents(generation=1)
        all_gen2 = self.factory.list_agents(generation=2)
        self.assertTrue(any(a.agent_id == gen1.agent_id for a in all_gen1))
        self.assertTrue(any(a.agent_id == gen2.agent_id for a in all_gen2))

    def test_10_sovereign_invariants_and_fail_closed_integrity(self):
        """Verify all synthesized agents strictly inherit fail-closed safety tier."""
        for name in ["Agent Alpha", "Agent Beta", "Agent Gamma"]:
            agent = self.factory.synthesize_agent(
                name=name,
                role="Execution Worker",
                intent=f"Perform autonomous tasks for {name}",
            )
            self.assertEqual(agent.safety_tier, "FAIL_CLOSED")
            self.assertIn("LIVE_ORDER_DISPATCH_ENABLED = False", agent.system_prompt)
            self.assertIn("fail-closed", agent.system_prompt.lower())


if __name__ == "__main__":
    unittest.main()
