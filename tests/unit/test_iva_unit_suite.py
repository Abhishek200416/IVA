"""AGI 1.7.0 — OMEGA COMMAND Unit Test Suite (24 Mandatory Unit Tests).

Covers every required unit test from Section 26 of the AGI 1.7 specification:
  1. Task state transition validity
  2. Illegal task state transition rejection
  3. Parent-child task relationship creation
  4. DAG dependency cycle detection
  5. Checkpoint write, read, and hash verification
  6. Live instruction inbox persistence and prioritization
  7. Resource snapshot parsing and validation
  8. Concurrency reduction when free memory falls below floor
  9. Concurrency hysteresis preventing rapid oscillation
  10. Token budget ceiling enforcement
  11. Provider vs estimated token accounting separation
  12. Multi-turn cumulative token normalization
  13. Memory entry creation, retrieval, and expiration
  14. Memory conflict supersession preserving history
  15. Pre-planning memory query invocation
  16. Context compression preserving task IDs, file paths, exit codes, and hashes
  17. Specialist registry validation for all 100 entries
  18. Duplicate specialist ID or capability rejection
  19. Capability router matching task requirements to specialist roles
  20. Process output parser extracting progress and error markers
  21. Process completion notifier firing immediately on process exit
  22. Post-download file existence, size, and SHA-256 verification
  23. Claim-to-evidence verifier rejecting unsupported score claims
  24. SSRF protection for private, loopback, and link-local addresses
"""

from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
import time
import unittest
from pathlib import Path

def _find_repo_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / 'pyproject.toml').exists() or (p / '.git').exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent.parent

REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.IVA.ecosystem.agent_registry.registry_validator import (
    RegistryValidationError,
    RegistryValidator,
)
from agents.IVA.ecosystem.agent_registry.specialist_factory import (
    SpecialistFactory,
    build_default_contracts,
)
from agents.IVA.engine.agi17.capabilities.resource_snapshot import (
    LiveResourceMetrics,
    ResourceSnapshot,
)
from agents.IVA.engine.agi17.memory.omega_command_memory import (
    ACONCompressor,
    OmegaCommandMemory,
)
from agents.IVA.engine.agi17.orchestration.resource_governor import ResourceGovernor
from agents.IVA.engine.agi17.process_supervision.completion_notifier import (
    CompletionNotifier,
    ExpectedArtifactSpec,
)
from agents.IVA.engine.agi17.process_supervision.process_supervisor import (
    ProcessSupervisor,
)
from agents.IVA.engine.agi17.process_supervision.stream_parser import StreamParser
from agents.IVA.engine.agi17.research.grounded_research import (
    GroundedResearchEngine,
    SSRFBlockedError,
)
from agents.IVA.engine.agi17.task_control.checkpoint_manager import (
    CheckpointManager,
)
from agents.IVA.engine.agi17.task_control.dependency_manager import (
    DependencyCycleError,
    DependencyManager,
)
from agents.IVA.engine.agi17.task_control.task_manager import DurableTaskManager
from agents.IVA.engine.agi17.task_control.task_state_machine import (
    InvalidStateTransitionError,
    TaskState,
    TaskStateMachine,
)
from agents.IVA.engine.agi17.task_control.task_store import TaskStore
from agents.IVA.engine.agi17.telemetry.token_economy import (
    AdaptiveTokenController,
    TokenBudgetExceededError,
)
from agents.IVA.engine.agi17.verification.evidence_verifier import EvidenceVerifier


class TestAGI17UnitSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _make_task_manager(self) -> DurableTaskManager:
        return DurableTaskManager(
            db_path=self.tmp_path / "tasks.db",
            events_jsonl_path=self.tmp_path / "events.jsonl",
            checkpoints_dir=self.tmp_path / "checkpoints",
        )

    # 1. Task state transition validity
    def test_01_task_state_transition_validity(self) -> None:
        s = TaskState.CREATED
        s = TaskStateMachine.validate_transition(s, TaskState.PLANNED)
        s = TaskStateMachine.validate_transition(s, TaskState.QUEUED)
        s = TaskStateMachine.validate_transition(s, TaskState.READY)
        s = TaskStateMachine.validate_transition(s, TaskState.RUNNING)
        s = TaskStateMachine.validate_transition(s, TaskState.VERIFYING)
        s = TaskStateMachine.validate_transition(s, TaskState.SUCCEEDED)
        self.assertEqual(s, TaskState.SUCCEEDED)
        self.assertTrue(TaskStateMachine.is_terminal(s))

    # 2. Illegal task state transition rejection
    def test_02_illegal_task_state_transition_rejection(self) -> None:
        with self.assertRaises(InvalidStateTransitionError):
            TaskStateMachine.validate_transition(TaskState.CREATED, TaskState.SUCCEEDED)
        with self.assertRaises(InvalidStateTransitionError):
            TaskStateMachine.validate_transition(TaskState.SUCCEEDED, TaskState.RUNNING)

    # 3. Parent-child task relationship creation
    def test_03_parent_child_task_relationship_creation(self) -> None:
        mgr = self._make_task_manager()
        parent = mgr.create_task(title="Root Mission", task_id="ROOT-1")
        child = mgr.create_task(title="Child Subtask", parent_task_id="ROOT-1", task_id="CHILD-1")
        self.assertEqual(parent["delegation_depth"], 0)
        self.assertEqual(child["parent_task_id"], "ROOT-1")
        self.assertEqual(child["delegation_depth"], 1)
        children = mgr.store.list_tasks(parent_task_id="ROOT-1")
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]["task_id"], "CHILD-1")

    # 4. DAG dependency cycle detection
    def test_04_dag_dependency_cycle_detection(self) -> None:
        mgr = self._make_task_manager()
        mgr.create_task(title="Node A", task_id="NODE-A")
        mgr.create_task(title="Node B", task_id="NODE-B", depends_on=["NODE-A"])
        # Inject a cycle manually into store and verify DependencyManager raises DependencyCycleError
        mgr.store.update_task_fields("NODE-A", depends_on=["NODE-B"])
        with self.assertRaises(DependencyCycleError):
            mgr.dep_mgr.validate_dag()

    # 5. Checkpoint write, read, and hash verification
    def test_05_checkpoint_write_read_and_hash_verification(self) -> None:
        ckpt_mgr = CheckpointManager(checkpoints_dir=self.tmp_path / "ckpts")
        artifact_file = self.tmp_path / "output.txt"
        artifact_file.write_text("deterministic-side-effect", encoding="utf-8")

        meta = ckpt_mgr.write_checkpoint(
            task_id="TASK-CKPT-1",
            step_index=3,
            state_payload={"completed_steps": [1, 2, 3]},
            completed_side_effects=["step_1_write"],
            artifact_paths=[str(artifact_file)],
        )
        loaded = ckpt_mgr.load_and_verify(meta["checkpoint_path"])
        self.assertEqual(loaded["step_index"], 3)
        self.assertTrue(ckpt_mgr. verify_side_effect_artifacts(loaded))

    # 6. Live instruction inbox persistence and prioritization
    def test_06_live_instruction_inbox_persistence_and_prioritization(self) -> None:
        mgr = self._make_task_manager()
        c1 = mgr.inbox.submit(instruction_type="APPEND_TO_QUEUE", target_task_id="T1", payload={"note": "first"})
        c2 = mgr.inbox.submit(instruction_type="ADD_CHILD_TASK", target_task_id="T1", payload={"title": "Sub 2"})
        pending = mgr.store.get_pending_commands(target_task_id="T1")
        self.assertEqual([p["command_id"] for p in pending], [c1, c2])

    # 7. Resource snapshot parsing and validation
    def test_07_resource_snapshot_parsing_and_validation(self) -> None:
        snap = ResourceSnapshot.capture(sample_cpu_ms=20)
        self.assertGreater(snap.total_phys_mb, 1024.0)
        self.assertGreater(snap.avail_phys_mb, 0.0)
        self.assertGreaterEqual(snap.cpu_percent, 0.0)
        self.assertLessEqual(snap.cpu_percent, 100.0)
        if snap.d_drive_available:
            self.assertGreater(snap.d_drive_free_gb, 0.0)
        else:
            self.assertGreater(snap.c_drive_free_gb, 0.0)

    # 8. Concurrency reduction when free memory falls below floor
    def test_08_concurrency_reduction_below_memory_floor(self) -> None:
        gov = ResourceGovernor(min_free_phys_ram_mb=1400.0, min_free_commit_mb=2500.0)
        low_mem_snap = LiveResourceMetrics(
            timestamp=time.time(),
            cpu_percent=20.0,
            memory_load_pct=93,
            total_phys_mb=16000.0,
            avail_phys_mb=1100.0,  # Below 1400 MB floor
            total_pagefile_mb=28000.0,
            avail_pagefile_mb=4000.0,
            c_drive_free_gb=13.0,
            d_drive_free_gb=600.0,
            on_ac_power=True,
            battery_life_pct=100,
            active_agy_processes=1,
            protected_external_pids_alive=[20556],
        )
        decision = gov.check_admission(queue_type="model_call", snap=low_mem_snap)
        self.assertFalse(decision.admitted)
        self.assertEqual(decision.recommended_max_active_executions, 1)

    # 9. Concurrency hysteresis preventing rapid oscillation
    def test_09_concurrency_hysteresis_preventing_oscillation(self) -> None:
        gov = ResourceGovernor(min_free_phys_ram_mb=1400.0, hysteresis_window=3)
        high_mem_snap = LiveResourceMetrics(
            timestamp=time.time(),
            cpu_percent=15.0,
            memory_load_pct=60,
            total_phys_mb=16000.0,
            avail_phys_mb=5000.0,
            total_pagefile_mb=28000.0,
            avail_pagefile_mb=10000.0,
            c_drive_free_gb=13.0,
            d_drive_free_gb=600.0,
            on_ac_power=True,
            battery_life_pct=100,
            active_agy_processes=0,
            protected_external_pids_alive=[],
        )
        # Starts at 2; single high sample should NOT immediately jump to 4 due to hysteresis_window=3
        c1 = gov.compute_dynamic_active_cap(high_mem_snap)
        c2 = gov.compute_dynamic_active_cap(high_mem_snap)
        self.assertEqual(c1, 2)
        self.assertEqual(c2, 2)
        c3 = gov.compute_dynamic_active_cap(high_mem_snap)
        self.assertEqual(c3, 3)

    # 10. Token budget ceiling enforcement
    def test_10_token_budget_ceiling_enforcement(self) -> None:
        tc = AdaptiveTokenController(ledger_dir=self.tmp_path / "tok", isolated_benchmark_cwd=self.tmp_path / "iso")
        tc.allocate_budget(task_id="T-BUDGET", tier="SIMPLE", custom_task_budget=1000)
        tc.record_usage(
            task_id="T-BUDGET",
            agent_id="worker",
            provider_usage={"input_tokens": 700, "output_tokens": 200, "total_tokens": 900},
        )
        with self.assertRaises(TokenBudgetExceededError):
            tc.check_pre_call_admission(task_id="T-BUDGET", estimated_tokens=300, tier="SIMPLE")

    # 11. Provider vs estimated token accounting separation
    def test_11_provider_vs_estimated_token_accounting_separation(self) -> None:
        tc = AdaptiveTokenController(ledger_dir=self.tmp_path / "tok", isolated_benchmark_cwd=self.tmp_path / "iso")
        r1 = tc.record_usage(
            task_id="T-SEP",
            agent_id="w1",
            provider_usage={"input_tokens": 120, "output_tokens": 80, "total_tokens": 200},
        )
        r2 = tc.record_usage(
            task_id="T-SEP",
            agent_id="w2",
            prompt_text="abcd" * 25,
            response_text="efgh" * 25,
        )
        self.assertEqual(r1.accounting_mode, "PROVIDER_REPORTED")
        self.assertEqual(r2.accounting_mode, "LOCAL_ESTIMATE")
        summary = tc.get_summary(task_id="T-SEP")
        self.assertEqual(summary["tokens_by_accounting_mode"]["PROVIDER_REPORTED"], 200)
        self.assertGreater(summary["tokens_by_accounting_mode"]["LOCAL_ESTIMATE"], 0)

    # 12. Multi-turn cumulative token normalization
    def test_12_multi_turn_cumulative_token_normalization(self) -> None:
        tc = AdaptiveTokenController(ledger_dir=self.tmp_path / "tok", isolated_benchmark_cwd=self.tmp_path / "iso")
        t1 = tc.record_usage(
            task_id="T-CUM",
            agent_id="w1",
            turn_index=1,
            provider_usage={"input_tokens": 1000, "output_tokens": 200},
            conversation_key="conv-1",
            usage_is_cumulative=True,
        )
        t2 = tc.record_usage(
            task_id="T-CUM",
            agent_id="w1",
            turn_index=2,
            provider_usage={"input_tokens": 1500, "output_tokens": 350},
            conversation_key="conv-1",
            usage_is_cumulative=True,
        )
        self.assertEqual(t1.input_tokens, 1000)
        self.assertEqual(t2.input_tokens, 500)
        self.assertEqual(t2.output_tokens, 150)
        self.assertEqual(tc.get_summary(task_id="T-CUM")["total_tokens"], 1850)

    # 13. Memory entry creation, retrieval, and expiration
    def test_13_memory_entry_creation_retrieval_and_expiration(self) -> None:
        mem = OmegaCommandMemory(primary_dir=self.tmp_path / "mem")
        mem.store(layer=5, subject_key="pref:lang", content="Use Python 3.14 stdlib", tags=["python"])
        mem.store(layer=1, subject_key="temp:note", content="Expired scratch", ttl_seconds=-1.0)
        active = mem.retrieve(query="Python", layers=[1, 5])
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].subject_key, "pref:lang")

    # 14. Memory conflict supersession preserving history
    def test_14_memory_conflict_supersession_preserving_history(self) -> None:
        mem = OmegaCommandMemory(primary_dir=self.tmp_path / "mem")
        e1 = mem.store(layer=5, subject_key="policy:concurrency", content="Max workers = 4")
        e2 = mem.store(layer=5, subject_key="policy:concurrency", content="Max workers = 2 under RAM pressure")
        current = mem.retrieve(subject_key="policy:concurrency", layers=[5], active_only=True)
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].entry_id, e2.entry_id)
        self.assertEqual(current[0].supersedes_id, e1.entry_id)
        history = mem.get_fact_history("policy:concurrency", layer=5)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].superseded_by_id, e2.entry_id)

    # 15. Pre-planning memory query invocation
    def test_15_pre_planning_memory_query_invocation(self) -> None:
        mem = OmegaCommandMemory(primary_dir=self.tmp_path / "mem")
        mem.store(layer=5, subject_key="rule:storage", content="Persist artifacts to D:\\AGI_Storage\\AGI_1_7")
        res = mem.retrieve_before_planning(task_id="PLAN-1", task_description="Persist storage artifacts")
        self.assertGreaterEqual(len(res["retrieved_entry_ids"]), 1)
        audits = mem.get_retrieval_audits(task_id="PLAN-1")
        self.assertGreaterEqual(len(audits), 1)

    # 16. Context compression preserving task IDs, file paths, exit codes, and hashes
    def test_16_context_compression_preserving_critical_anchors(self) -> None:
        sha = "dde15ffe684a0d4c3e8677dbed56432788cc11da5cdc1ca6ff704f1a9ea2fadb"
        verbose = (
            "Starting job TASK-9901 on D:\\AGI_Storage\\AGI_1_7\\data.bin. "
            + ("filler log line with verbose progress output " * 40)
            + f" Completed with exit_code=0 and sha256={sha} after TimeoutExpired check."
        )
        comp = ACONCompressor.compress_observation(verbose, max_chars=320)
        self.assertLess(comp["compressed_chars"], comp["raw_chars"])
        text = comp["compressed_text"]
        self.assertIn("TASK-9901", text)
        self.assertIn(sha, text)
        self.assertIn("0", comp["preserved_anchors"]["exit_codes"])

    # 17. Specialist registry validation for all 100 entries
    def test_17_specialist_registry_validation_for_100_entries(self) -> None:
        factory = SpecialistFactory()
        self.assertEqual(len(factory.contracts), 100)
        self.assertTrue(factory.validation_summary["valid"])
        self.assertEqual(factory.validation_summary["unique_ids"], 100)

    # 18. Duplicate specialist ID or capability rejection
    def test_18_duplicate_specialist_id_or_capability_rejection(self) -> None:
        contracts = build_default_contracts()
        dup_contracts = copy.deepcopy(contracts)
        dup_contracts[1].agent_id = dup_contracts[0].agent_id
        with self.assertRaises(RegistryValidationError):
            RegistryValidator.validate_contracts(dup_contracts)

    # 19. Capability router matching task requirements to specialist roles
    def test_19_capability_router_matching_task_requirements(self) -> None:
        factory = SpecialistFactory()
        matches = factory.router.route(
            task_description="Verify SQLite WAL concurrency and schema indexes",
            required_capabilities=["sqlite_wal_pragma_tuning"],
            top_k=1,
        )
        self.assertEqual(matches[0]["agent_id"], "data_sqlite_wal_architect")

    # 20. Process output parser extracting progress and error markers
    def test_20_process_output_parser_extracting_progress_and_errors(self) -> None:
        parser = StreamParser()
        e1 = parser.parse_line("Downloading archive: 42.5% (17/40)")
        self.assertEqual(e1.event_type, "progress")
        self.assertAlmostEqual(e1.progress_percent or 0.0, 42.5)
        self.assertEqual(e1.completed_units, 17)
        self.assertEqual(e1.total_units, 40)

        e2 = parser.parse_line("FATAL: MemoryError while allocating buffer", stream="stderr")
        self.assertEqual(e2.event_type, "error")
        self.assertIsNotNone(e2.error_signature)

    # 21. Process completion notifier firing immediately on process exit
    def test_21_process_completion_notifier_firing_immediately(self) -> None:
        received = []
        notifier = CompletionNotifier(notifications_dir=self.tmp_path / "notifs")
        notifier.register_callback(lambda n: received.append(n))
        sup = ProcessSupervisor(notifier=notifier, logs_dir=self.tmp_path / "logs")
        notif = sup.run_supervised(
            task_id="PROC-UNIT-21",
            command=[sys.executable, "-c", "print('Progress: 100%')"],
            wall_timeout_sec=10.0,
        )
        self.assertEqual(notif.final_status, "SUCCEEDED")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].task_id, "PROC-UNIT-21")

    # 22. Post-download file existence, size, and SHA-256 verification
    def test_22_post_download_file_existence_size_and_sha256_verification(self) -> None:
        target = self.tmp_path / "downloaded.bin"
        payload = b"verified-binary-payload-agi-1-7"
        target.write_bytes(payload)
        expected_hash = hashlib.sha256(payload).hexdigest()

        ok_res = CompletionNotifier.verify_artifact(
            ExpectedArtifactSpec(path=str(target), min_size_bytes=10, expected_sha256=expected_hash)
        )
        self.assertTrue(ok_res.passed)

        bad_res = CompletionNotifier.verify_artifact(
            ExpectedArtifactSpec(path=str(target), min_size_bytes=10, expected_sha256="0" * 64)
        )
        self.assertFalse(bad_res.passed)

    # 23. Claim-to-evidence verifier rejecting unsupported score claims
    def test_23_claim_to_evidence_verifier_rejecting_unsupported_claims(self) -> None:
        gpqa_path = self.tmp_path / "gpqa.jsonl"
        import json
        gpqa_path.write_text("\n".join(json.dumps({"gpqa_correct": 174, "id": i}) for i in range(174)) + "\n", encoding="utf-8")
        chk_pass = EvidenceVerifier.verify_claim_against_ledger(
            claim_name="gpqa_correct",
            claimed_value=174,
            observed_value=174,
            evidence_path=gpqa_path,
        )
        self.assertTrue(chk_pass.passed)

        chk_fail = EvidenceVerifier.verify_claim_against_ledger(
            claim_name="gpqa_fabricated_score",
            claimed_value=189,
            observed_value=174,
            evidence_path=gpqa_path,
        )
        self.assertFalse(chk_fail.passed)

    # 24. SSRF protection for private, loopback, and link-local addresses
    def test_24_ssrf_protection_for_private_loopback_and_link_local(self) -> None:
        safe = GroundedResearchEngine.validate_url_ssrf_safe("https://arxiv.org/abs/2403.16971")
        self.assertTrue(safe["ssrf_safe"])

        for blocked_url in (
            "http://127.0.0.1:8080/admin",
            "http://localhost/secret",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.1/config",
            "http://10.0.0.1/internal",
            "file:///C:/Windows/System32/drivers/etc/hosts",
        ):
            with self.assertRaises(SSRFBlockedError):
                GroundedResearchEngine.validate_url_ssrf_safe(blocked_url)

    # 25. EcosystemCoordinator inventory & active railings (Ponytail, Context7, Sequential Thinking, CodeRabbit, GSD, Agency)
    def test_25_ecosystem_coordinator_inventory_and_railings(self) -> None:
        from agents.IVA.ecosystem.agent_registry.ecosystem_coordinator import EcosystemCoordinator

        coord = EcosystemCoordinator()
        inv = coord.get_inventory_summary()
        self.assertEqual(inv["embedded_specialists_count"], 100)
        self.assertGreaterEqual(inv["agency_profiles_bridged_count"], 76)
        self.assertEqual(inv["mcp_servers_count"], 21)
        self.assertEqual(inv["plugin_suites_count"], 11)
        self.assertEqual(inv["workflow_skills_count"], 74)
        for core_mcp in ("ponytail", "context7", "sequential-thinking", "gsd", "playwright"):
            self.assertIn(core_mcp, inv["mcp_servers"])

        factory = SpecialistFactory()
        arch_rail = coord.build_coordination_railings(factory.get_contract("plan_systems_architect"))
        self.assertEqual(arch_rail["agency_profile_matched"], "architect")
        self.assertIn("ponytail", arch_rail["mcp_servers_bound"])
        self.assertIn("sequential-thinking", arch_rail["mcp_servers_bound"])

        swe_rail = coord.build_coordination_railings(factory.get_contract("swe_python_runtime_engineer"))
        self.assertEqual(swe_rail["agency_profile_matched"], "backend-engineer")
        self.assertIn("context7", swe_rail["mcp_servers_bound"])

        repair_rail = coord.build_coordination_railings(factory.get_contract("swe_patch_minimizer"), is_repair=True)
        self.assertEqual(repair_rail["agency_profile_matched"], "debugging-engineer")
        self.assertIn("gsd-debug", repair_rail["skills_applied"])

    # 26. Strict surface-only GPQA answer extraction (zero thinking-transcript recovery by default)
    def test_26_gpqa_strict_surface_answer_extraction(self) -> None:
        from agents.IVA.scripts.run_gpqa_clean_189_agi17 import extract_choice

        ans_ok = extract_choice("Step-by-step derivation complete.\n<choice>C</choice>")
        self.assertEqual(ans_ok, "C")

        # Empty surface output MUST return None under strict surface grading
        ans_empty = extract_choice("")
        self.assertIsNone(ans_empty)


if __name__ == "__main__":
    unittest.main(verbosity=2)

