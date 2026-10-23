"""AGI 1.7.0 — OMEGA COMMAND Integration Test Suite (Tests A through O).

Covers all 15 mandatory integration scenarios from Section 27 of the specification:
  Test A: Simple task fast path
  Test B: Substantial task hierarchical delegation
  Test C: 100-specialist registry smoke test
  Test D: 100-logical-child task planning with bounded active concurrency
  Test E: Mid-run child task injection (ADD_CHILD_TASK)
  Test F: Mid-run pause and priority switch (PAUSE_CURRENT_AND_SWITCH)
  Test G: Mid-run cancel and replace (CANCEL_AND_REPLACE)
  Test H: Long-running command streaming and immediate completion push
  Test I: Post-download artifact verification failure when corrupt/truncated
  Test J: Cross-session memory persistence and retrieval across restarts
  Test K: D:\\ storage and local fallback verification
  Test L: Crash and checkpoint resume without repeating completed side effects
  Test M: Resource pressure adaptation
  Test N: Token budget enforcement
  Test O: Dashboard and ledger reconciliation
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.AGI_1_7.ecosystem.agent_registry.specialist_factory import SpecialistFactory
from agents.AGI_1_7.engine.agi17.capabilities.resource_snapshot import LiveResourceMetrics
from agents.AGI_1_7.engine.agi17.memory.omega_command_memory import OmegaCommandMemory
from agents.AGI_1_7.engine.agi17.orchestration.hierarchical_orchestrator import (
    HierarchicalOrchestrator,
    SubtaskSpec,
)
from agents.AGI_1_7.engine.agi17.orchestration.resource_governor import ResourceGovernor
from agents.AGI_1_7.engine.agi17.process_supervision.completion_notifier import (
    CompletionNotifier,
    ExpectedArtifactSpec,
)
from agents.AGI_1_7.engine.agi17.process_supervision.process_supervisor import (
    ProcessSupervisor,
)
from agents.AGI_1_7.engine.agi17.task_control.task_manager import DurableTaskManager
from agents.AGI_1_7.engine.agi17.task_control.task_state_machine import TaskState
from agents.AGI_1_7.engine.agi17.telemetry.progress_service import ProgressService
from agents.AGI_1_7.engine.agi17.telemetry.token_economy import (
    AdaptiveTokenController,
    TokenBudgetExceededError,
)
from agents.AGI_1_7.engine.agi17.verification.evidence_verifier import EvidenceVerifier


class TestAGI17IntegrationSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _build_env(self) -> tuple[DurableTaskManager, OmegaCommandMemory, ResourceGovernor, AdaptiveTokenController, SpecialistFactory, HierarchicalOrchestrator]:
        tm = DurableTaskManager(
            db_path=self.tmp_path / "tasks.db",
            events_jsonl_path=self.tmp_path / "events.jsonl",
            checkpoints_dir=self.tmp_path / "checkpoints",
        )
        mem = OmegaCommandMemory(primary_dir=self.tmp_path / "memory")
        gov = ResourceGovernor()
        tc = AdaptiveTokenController(
            ledger_dir=self.tmp_path / "token_ledger",
            isolated_benchmark_cwd=self.tmp_path / "isolated_cwd",
        )
        sf = SpecialistFactory()
        orch = HierarchicalOrchestrator(
            task_manager=tm,
            memory=mem,
            governor=gov,
            token_controller=tc,
            specialist_factory=sf,
        )
        return tm, mem, gov, tc, sf, orch

    # Test A — Simple task fast path
    def test_A_simple_task_fast_path(self) -> None:
        tm, mem, gov, tc, sf, orch = self._build_env()
        res = orch.execute_mission(
            title="Quick Check",
            prompt="Check Python AST syntax of a single module.",
            task_id="TEST-A-FAST",
        )
        self.assertEqual(res["execution_path"], "DIRECT_FAST_PATH")
        self.assertEqual(res["logical_children_created"], 0)
        self.assertEqual(res["final_state"], "SUCCEEDED")
        self.assertGreaterEqual(len(mem.get_retrieval_audits(task_id="TEST-A-FAST")), 1)

    # Test B — Substantial task hierarchical delegation
    def test_B_substantial_task_hierarchical_delegation(self) -> None:
        tm, mem, gov, tc, sf, orch = self._build_env()
        res = orch.execute_mission(
            title="Multi-Stage Engineering Mission",
            prompt="Decompose and orchestrate a multi-stage audit and implement verification across subsystems.",
            task_id="TEST-B-HIER",
        )
        self.assertEqual(res["execution_path"], "HIERARCHICAL_DAG")
        self.assertGreaterEqual(res["logical_children_created"], 4)
        self.assertEqual(res["succeeded_children"], res["logical_children_created"])
        self.assertEqual(res["final_state"], "SUCCEEDED")

    # Test C — 100-specialist registry smoke test
    def test_C_100_specialist_registry_smoke_test(self) -> None:
        sf = SpecialistFactory()
        summary = sf.run_all_smoke_tests()
        self.assertEqual(summary["total_tested"], 100)
        self.assertEqual(summary["passed"], 100)
        self.assertTrue(summary["all_passed"])
        self.assertEqual(len(summary["passed_by_family"]), 16)

    # Test D — 100-logical-child task planning with bounded active concurrency
    def test_D_100_logical_child_tasks_with_bounded_concurrency(self) -> None:
        tm, mem, gov, tc, sf, orch = self._build_env()
        subtasks = [
            SubtaskSpec(
                title=f"Logical Child {i + 1:03d}",
                description=f"Execute specialist capability check #{i + 1}",
                preferred_specialist_id=sf.contracts[i].agent_id,
                depends_on_indices=[i - 1] if i % 10 != 0 else [],
            )
            for i in range(100)
        ]
        res = orch.execute_mission(
            title="100-Child Bounded Concurrency Mission",
            prompt="Orchestrate 100 logical child tasks mapped across all 100 specialist contracts.",
            task_id="TEST-D-100",
            subtasks=subtasks,
            force_hierarchical=True,
        )
        self.assertEqual(res["logical_children_created"], 100)
        self.assertEqual(res["succeeded_children"], 100)
        self.assertLessEqual(res["max_concurrent_workers_used"], 4)
        self.assertEqual(res["final_state"], "SUCCEEDED")

    # Test E — Mid-run child task injection
    def test_E_mid_run_child_task_injection(self) -> None:
        tm, mem, gov, tc, sf, orch = self._build_env()
        injected = {"done": False}

        def _hook(completed_cid: str, _res: dict) -> None:
            if not injected["done"]:
                injected["done"] = True
                tm.inbox.submit(
                    instruction_type="ADD_CHILD_TASK",
                    target_task_id="TEST-E-ROOT",
                    payload={
                        "child_task_id": "TEST-E-INJECTED-CHILD",
                        "title": "Mid-Run Injected Verification Child",
                        "description": "Dynamically added child task while parent is running",
                        "specialist_role": "qa_claim_to_evidence_verifier",
                    },
                )

        subtasks = [
            SubtaskSpec(title="Step 1", description="First subtask", depends_on_indices=[]),
            SubtaskSpec(title="Step 2", description="Second subtask", depends_on_indices=[0]),
        ]
        res = orch.execute_mission(
            title="Mid-Run Injection Test",
            prompt="Run multi-stage workflow accepting mid-run child task.",
            task_id="TEST-E-ROOT",
            subtasks=subtasks,
            force_hierarchical=True,
            custom_subtask_hook=_hook,
        )
        self.assertEqual(res["logical_children_created"], 3)
        self.assertEqual(res["succeeded_children"], 3)
        injected_rec = tm.store.get_task("TEST-E-INJECTED-CHILD")
        self.assertIsNotNone(injected_rec)
        self.assertEqual(injected_rec["state"], "SUCCEEDED")

    # Test F — Mid-run pause and priority switch
    def test_F_mid_run_pause_and_priority_switch(self) -> None:
        tm, mem, gov, tc, sf, orch = self._build_env()
        paused = {"done": False}

        def _hook(_cid: str, _res: dict) -> None:
            if not paused["done"]:
                paused["done"] = True
                tm.inbox.submit(
                    instruction_type="PAUSE_CURRENT_AND_SWITCH",
                    target_task_id="TEST-F-ROOT",
                    payload={
                        "new_task_id": "TEST-F-URGENT",
                        "title": "Urgent Priority Switch Task",
                        "description": "Immediate priority task",
                        "priority": 100,
                    },
                )

        subtasks = [
            SubtaskSpec(title="Wave 1", description="First wave", depends_on_indices=[]),
            SubtaskSpec(title="Wave 2", description="Second wave", depends_on_indices=[0]),
        ]
        res = orch.execute_mission(
            title="Pause Switch Mission",
            prompt="Run multi-stage job and pause mid-run.",
            task_id="TEST-F-ROOT",
            subtasks=subtasks,
            force_hierarchical=True,
            custom_subtask_hook=_hook,
        )
        self.assertEqual(res["final_state"], "WAITING_FOR_INPUT")
        urgent = tm.store.get_task("TEST-F-URGENT")
        self.assertIsNotNone(urgent)
        self.assertEqual(urgent["state"], "READY")

    # Test G — Mid-run cancel and replace
    def test_G_mid_run_cancel_and_replace(self) -> None:
        tm, mem, gov, tc, sf, orch = self._build_env()

        def _hook(_cid: str, _res: dict) -> None:
            tm.inbox.submit(
                instruction_type="CANCEL_AND_REPLACE",
                target_task_id="TEST-G-ROOT",
                payload={
                    "replacement_task_id": "TEST-G-REPLACEMENT",
                    "title": "Replacement Task",
                    "description": "Replaced obsolete task",
                },
            )

        subtasks = [
            SubtaskSpec(title="Wave 1", description="First wave", depends_on_indices=[]),
            SubtaskSpec(title="Wave 2", description="Second wave", depends_on_indices=[0]),
        ]
        res = orch.execute_mission(
            title="Cancel Replace Mission",
            prompt="Run multi-stage job and cancel mid-run.",
            task_id="TEST-G-ROOT",
            subtasks=subtasks,
            force_hierarchical=True,
            custom_subtask_hook=_hook,
        )
        self.assertEqual(res["final_state"], "CANCELED")
        rep = tm.store.get_task("TEST-G-REPLACEMENT")
        self.assertIsNotNone(rep)
        self.assertEqual(rep["state"], "READY")

    # Test H — Long-running command streaming and completion push
    def test_H_long_running_command_streaming_and_completion_push(self) -> None:
        tm, mem, gov, tc, sf, orch = self._build_env()
        tm.create_task(title="Streaming Subprocess", task_id="TEST-H-PROC")
        progress_events = []
        completions = []

        sup = ProcessSupervisor(task_manager=tm, logs_dir=self.tmp_path / "logs")
        py_code = (
            "import time, sys\n"
            "for pct in (25, 50, 75, 100):\n"
            "    print(f'Progress: {pct}%', flush=True)\n"
            "    time.sleep(0.05)\n"
        )
        notif = sup.run_supervised(
            task_id="TEST-H-PROC",
            command=[sys.executable, "-c", py_code],
            on_progress=lambda e: progress_events.append(e),
            on_complete=lambda n: completions.append(n),
            wall_timeout_sec=15.0,
        )
        self.assertEqual(notif.final_status, "SUCCEEDED")
        self.assertEqual(notif.latest_progress_percent, 100.0)
        self.assertGreaterEqual(len(progress_events), 4)
        self.assertEqual(len(completions), 1)
        self.assertEqual(tm.store.get_task("TEST-H-PROC")["state"], "SUCCEEDED")

    # Test I — Post-download artifact verification failure on truncated/corrupt file
    def test_I_post_download_artifact_verification_failure(self) -> None:
        tm, mem, gov, tc, sf, orch = self._build_env()
        tm.create_task(title="Corrupt Download Test", task_id="TEST-I-DL")
        corrupt_file = self.tmp_path / "corrupt.bin"

        sup = ProcessSupervisor(task_manager=tm, logs_dir=self.tmp_path / "logs")
        py_code = f"from pathlib import Path; Path(r'{corrupt_file}').write_bytes(b'short')"
        notif = sup.run_supervised(
            task_id="TEST-I-DL",
            command=[sys.executable, "-c", py_code],
            expected_artifacts=[
                ExpectedArtifactSpec(
                    path=str(corrupt_file),
                    min_size_bytes=1024,  # Expects >= 1024 bytes, but only 5 bytes written
                    expected_sha256="a" * 64,
                )
            ],
        )
        # Even though process exited 0, artifact verification failed so task MUST be marked FAILED
        self.assertEqual(notif.exit_code, 0)
        self.assertFalse(notif.all_artifacts_verified)
        self.assertEqual(notif.final_status, "FAILED")
        self.assertEqual(tm.store.get_task("TEST-I-DL")["state"], "FAILED")

    # Test J — Cross-session memory persistence and retrieval
    def test_J_cross_session_memory_persistence_and_retrieval(self) -> None:
        mem_dir = self.tmp_path / "persistent_mem"
        session1 = OmegaCommandMemory(primary_dir=mem_dir, session_id="SESSION-1")
        e_old = session1.store(
            layer=5,
            subject_key="arch:isolated_cwd",
            content="Draft v1: use workspace directory",
            tags=["cwd", "gpqa"],
        )
        e_new = session1.store(
            layer=5,
            subject_key="arch:isolated_cwd",
            content="Verified v2: enforce D:\\AGI_Evaluation\\AGI_1_7_OMEGA_COMMAND\\isolated_cwd",
            tags=["cwd", "gpqa"],
        )
        del session1

        # Fresh session instance reading from same SQLite WAL DB
        session2 = OmegaCommandMemory(primary_dir=mem_dir, session_id="SESSION-2")
        preplan = session2.retrieve_before_planning(
            task_id="TEST-J-TASK",
            task_description="Configure gpqa isolated_cwd benchmark directory",
            tags=["gpqa"],
        )
        self.assertIn(e_new.entry_id, preplan["retrieved_entry_ids"])
        self.assertNotIn(e_old.entry_id, preplan["retrieved_entry_ids"])
        history = session2.get_fact_history("arch:isolated_cwd", layer=5)
        self.assertEqual(len(history), 2)

    # Test K — D:\ storage and local fallback verification
    def test_K_d_drive_storage_and_local_fallback_verification(self) -> None:
        import os as _os
        primary_target = Path(r"D:\AGI_Storage\AGI_1_7\memory") if (sys.platform == "win32" and _os.path.exists("D:\\")) else (self.tmp_path / "primary_mem")
        real_d_mem = OmegaCommandMemory(
            primary_dir=primary_target,
            fallback_dir=self.tmp_path / "fallback_mem",
            force_fallback=False,
        )
        self.assertFalse(real_d_mem.using_fallback)

        fallback_mem = OmegaCommandMemory(
            primary_dir=r"D:\AGI_Storage\AGI_1_7\memory",
            fallback_dir=self.tmp_path / "fallback_mem",
            force_fallback=True,
        )
        self.assertTrue(fallback_mem.using_fallback)
        entry = fallback_mem.store(layer=5, subject_key="fallback:test", content="Stored in fallback")
        self.assertTrue((self.tmp_path / "fallback_mem" / "omega_memory.db").exists())
        self.assertEqual(entry.subject_key, "fallback:test")

    # Test L — Crash and checkpoint resume without repeating completed side effects
    def test_L_crash_and_checkpoint_resume(self) -> None:
        tm, mem, gov, tc, sf, orch = self._build_env()
        side_effect_file = self.tmp_path / "step1_side_effect.txt"
        side_effect_file.write_text("completed-once", encoding="utf-8")

        tm.create_task(title="Crash Recovery Task", task_id="TEST-L-CRASH")
        tm.transition("TEST-L-CRASH", TaskState.PLANNED)
        tm.transition("TEST-L-CRASH", TaskState.QUEUED)
        tm.transition("TEST-L-CRASH", TaskState.READY)
        tm.transition("TEST-L-CRASH", TaskState.RUNNING)
        # Assign dead PID 99999999 and write verified checkpoint for step 1
        tm.store.update_task_fields("TEST-L-CRASH", worker_pid=99999999)
        tm.save_checkpoint(
            "TEST-L-CRASH",
            step_index=1,
            state_payload={"completed_steps": ["step_1"]},
            completed_side_effects=["step_1"],
            artifact_paths=[str(side_effect_file)],
        )

        # Simulate restart and reconcile
        actions = tm.reconcile_after_restart()
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "REQUEUED_FROM_CHECKPOINT")
        rec = tm.store.get_task("TEST-L-CRASH")
        self.assertEqual(rec["state"], "READY")

        ckpt = tm.ckpt_mgr.load_and_verify(rec["checkpoint_path"])
        self.assertIn("step_1", ckpt["completed_side_effects"])
        self.assertTrue(tm.ckpt_mgr.verify_side_effect_artifacts(ckpt))

    # Test M — Resource pressure adaptation
    def test_M_resource_pressure_adaptation(self) -> None:
        tm, mem, gov, tc, sf, orch = self._build_env()
        constrained_snap = LiveResourceMetrics(
            timestamp=time.time(),
            cpu_percent=78.0,
            memory_load_pct=88,
            total_phys_mb=16000.0,
            avail_phys_mb=1550.0,  # Only 150 MB above 1400 MB floor -> forces cap = 1
            total_pagefile_mb=28000.0,
            avail_pagefile_mb=2800.0,
            c_drive_free_gb=13.0,
            d_drive_free_gb=600.0,
            on_ac_power=True,
            battery_life_pct=100,
            active_agy_processes=2,
            protected_external_pids_alive=[20556, 22884],
        )
        subtasks = [
            SubtaskSpec(title=f"Parallel Task {i}", description="Independent task", depends_on_indices=[])
            for i in range(4)
        ]
        res = orch.execute_mission(
            title="Resource Constrained Mission",
            prompt="Execute 4 independent tasks under tight memory headroom.",
            task_id="TEST-M-PRESSURE",
            subtasks=subtasks,
            force_hierarchical=True,
            simulated_resource_snapshot=constrained_snap,
        )
        self.assertEqual(res["max_concurrent_workers_used"], 1)
        self.assertEqual(res["succeeded_children"], 4)

    # Test N — Token budget enforcement
    def test_N_token_budget_enforcement(self) -> None:
        tm, mem, gov, tc, sf, orch = self._build_env()
        tc.allocate_budget(task_id="TEST-N-TOK", tier="SIMPLE", custom_task_budget=500)
        tc.record_usage(
            task_id="TEST-N-TOK",
            agent_id="worker",
            provider_usage={"input_tokens": 400, "output_tokens": 90, "total_tokens": 490},
        )
        with self.assertRaises(TokenBudgetExceededError):
            tc.check_pre_call_admission(task_id="TEST-N-TOK", estimated_tokens=100, tier="SIMPLE")

    # Test O — Dashboard and ledger reconciliation
    def test_O_dashboard_and_ledger_reconciliation(self) -> None:
        tm, mem, gov, tc, sf, orch = self._build_env()
        orch.execute_mission(
            title="Reconciled Mission",
            prompt="Decompose and orchestrate a multi-stage verification mission.",
            task_id="TEST-O-DASH",
            force_hierarchical=True,
        )
        prog = ProgressService(task_store=tm.store, token_controller=tc, output_dir=self.tmp_path / "telemetry")
        dash_data = prog.build_live_telemetry()
        html_path = prog.render_html_dashboard()
        self.assertTrue(html_path.exists())

        chk_tasks = EvidenceVerifier.verify_claim_against_ledger(
            claim_name="dashboard_total_tasks",
            claimed_value=dash_data["task_counts"]["total_tasks"],
            observed_value=len(tm.store.list_tasks()),
            evidence_path=tm.store.db_path,
        )
        chk_tokens = EvidenceVerifier.verify_claim_against_ledger(
            claim_name="dashboard_total_tokens",
            claimed_value=dash_data["token_telemetry"]["total_tokens"],
            observed_value=tc.get_summary()["total_tokens"],
            evidence_path=tc.ledger_file,
        )
        self.assertTrue(chk_tasks.passed)
        self.assertTrue(chk_tokens.passed)

    # Test P — Normal execute_mission code_task_dir workflow & explicit fallback reporting
    def test_P_normal_execute_mission_code_task_dir_and_fallback_reporting(self) -> None:
        from agents.AGI_1_7.engine.agi17.process_supervision.sandbox_runner import (
            DisposableSandboxRunner,
            SandboxPolicy,
        )

        tm, mem, gov, tc, sf, orch = self._build_env()
        self.assertTrue(orch.sandbox_runner.policy.require_container_isolation)
        self.assertFalse(orch.sandbox_runner.policy.allow_host_subprocess_fallback)
        orch.sandbox_runner = DisposableSandboxRunner(policy=SandboxPolicy.development())
        code_dir = self.tmp_path / "code_ws"
        code_dir.mkdir(parents=True, exist_ok=True)
        # Build subtasks via build_code_and_test_subtasks and run with deterministic mocked model responses
        subtasks = orch.build_code_and_test_subtasks(
            title="Test P Code Workflow",
            prompt="Implement add_ints(a, b) in adder.py",
            code_task_dir=code_dir,
            module_filename="adder.py",
            test_filename="test_adder.py",
            inject_deliberate_test_failure=False,
            fallback_module_code="def add_ints(a: int, b: int) -> int:\n    return a + b\n",
            fallback_test_code=(
                "import unittest\nfrom adder import add_ints\n"
                "class TestAdder(unittest.TestCase):\n"
                "    def test_add(self):\n        self.assertEqual(add_ints(2, 3), 5)\n"
            ),
        )
        # Override use_live_model=False on stages 1 & 2, and write fallback files to test verification + fallback_summary structure
        (code_dir / "adder.py").write_text("def add_ints(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
        (code_dir / "test_adder.py").write_text(
            "import unittest\nfrom adder import add_ints\n"
            "class TestAdder(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add_ints(2, 3), 5)\n",
            encoding="utf-8",
        )
        for st in subtasks:
            st.use_live_model = False
        res = orch.execute_mission(
            title="Test P Code Workflow",
            prompt="Implement add_ints(a, b) in adder.py",
            task_id="TEST-P-CODE",
            subtasks=subtasks,
            force_hierarchical=True,
            use_live_model=False,
        )
        self.assertEqual(res["final_state"], "SUCCEEDED")
        self.assertIn("fallback_summary", res)
        self.assertFalse(res["fallback_summary"]["any_fallback_used"])
        self.assertIn("ecosystem_coordination_summary", res)
        self.assertEqual(res["ecosystem_coordination_summary"]["embedded_specialists_count"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)

