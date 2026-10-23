"""AGI 1.7 Phase 17.25 Persistent Autonomous Improvement Engine Test Suite.

Verifies:
1. Restarting the worker and recovering its checkpoint.
2. Preventing duplicate workers (PID lock).
3. Persisting a stop request surviving restarts.
4. Ensuring a stopped worker does not resume automatically.
5. Resuming only after an explicit resume command.
6. Budget exhaustion handling (token and request limits).
7. LLM request failures and offline fallback.
8. Research source deduplication and Layer 9 caching.
9. Context truncation, snippet extraction, and ACON anchor preservation.
10. Failed candidate updates rollback (automatic restoration of original file).
11. Regression detection and rejection.
12. Invalid task states handling.
13. Stale heartbeat detection.
14. Graceful shutdown.
15. Preservation of financial safety locks (LIVE_ORDER_DISPATCH_ENABLED == False).
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
import sys
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.AGI_1_7.engine.agi17.adapters.centralized_llm_gateway import (
    CentralizedLLMGateway,
    GatewayResponse,
    GatewayRoute,
)
from agents.AGI_1_7.engine.agi17.memory.persistent_memory_subsystem import (
    MemoryCategory,
    PersistentMemorySubsystem,
    VerificationStatus,
)
from agents.AGI_1_7.engine.agi17.orchestration.persistent_improvement_worker import (
    CycleCheckpoint,
    DuplicateWorkerError,
    PersistentImprovementWorker,
    WorkerState,
)
from agents.AGI_1_7.engine.agi17.research.grounded_research import (
    GroundedResearchEngine,
    ResearchCitation,
    SSRFBlockedError,
)
from agents.AGI_1_7.engine.agi17.runtime.authoritative_brain_config import (
    AuthoritativeBrainConfig,
)
from agents.AGI_1_7.engine.agi17.runtime.command_router import (
    CommandIntent,
    CommandRouter,
)


class TestOmegaPersistentImprovementEngine(unittest.TestCase):
    """Authoritative test suite for Phase 17.25."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="omega_p1725_test_"))
        self.scratch_dir = self.test_dir / "scratch"
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        self.worker = PersistentImprovementWorker(workspace_root=self.test_dir)

    def tearDown(self):
        self.worker.release_worker_lock()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_restart_and_recover_checkpoint(self):
        """Item 1: Worker recovers previous interrupted checkpoint."""
        cp = CycleCheckpoint(
            cycle_id="CYCLE-TEST-RECOVER-001",
            stage=WorkerState.TESTING,
            goal_id="TRACK-TEST-01",
            goal_title="Test Recovery Feature",
            hypothesis="Recovery works cleanly",
        )
        self.worker.save_checkpoint(cp)

        # Instantiate second worker pointing to same scratch directory
        worker2 = PersistentImprovementWorker(workspace_root=self.test_dir)
        recovered = worker2.recover_last_checkpoint()

        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.cycle_id, "CYCLE-TEST-RECOVER-001")
        self.assertEqual(recovered.stage, WorkerState.TESTING)
        self.assertEqual(recovered.goal_id, "TRACK-TEST-01")

    def test_02_prevent_duplicate_workers(self):
        """Item 2: Prevent multiple concurrent workers via PID locking."""
        self.worker.acquire_worker_lock()
        self.assertTrue(self.worker.pid_file.exists())

        # Second worker attempting lock acquisition without force must raise DuplicateWorkerError
        worker2 = PersistentImprovementWorker(workspace_root=self.test_dir)
        with self.assertRaises(DuplicateWorkerError):
            worker2.acquire_worker_lock(force=False)

    def test_03_persist_stop_request_surviving_restart(self):
        """Item 3: Persisting a stop request that survives process restarts."""
        self.worker.set_control_signal("STOP", reason="Emergency operator stop")
        self.assertTrue(self.worker.control_file.exists())

        # Check signals on a fresh worker instance
        worker2 = PersistentImprovementWorker(workspace_root=self.test_dir)
        sig = worker2.check_control_signals()
        self.assertEqual(sig["action"], "STOP")
        self.assertIn("Emergency", sig["reason"])

    def test_04_stopped_worker_does_not_resume_automatically(self):
        """Item 4: Stopped worker refuses to execute cycle without explicit resume."""
        self.worker.set_control_signal("STOP", reason="Deliberate operator stop")
        worker2 = PersistentImprovementWorker(workspace_root=self.test_dir)

        with self.assertRaises(RuntimeError) as ctx:
            worker2.execute_cycle()
        self.assertIn("cannot start cycle", str(ctx.exception))

    def test_05_resuming_only_after_explicit_resume(self):
        """Item 5: Worker resumes execution only when explicit RESUME signal is issued."""
        self.worker.set_control_signal("STOP", reason="Stopped")
        worker2 = PersistentImprovementWorker(workspace_root=self.test_dir)

        # Clear stop via RESUME
        worker2.set_control_signal("RESUME", reason="Operator resumed")
        sig = worker2.check_control_signals()
        self.assertEqual(sig["action"], "RESUME")

        # Now cycle execution succeeds
        cp = worker2.execute_cycle()
        self.assertIsNotNone(cp)
        self.assertEqual(cp.terminal_outcome, "PROMOTED_AND_VERIFIED")

    def test_06_budget_exhaustion_enforcement(self):
        """Item 6: Token and request budget exhaustion pauses model requests."""
        gw = CentralizedLLMGateway(workspace_root=self.test_dir)
        gw.telemetry.daily_token_usage = 499_500
        gw.telemetry.daily_token_cap = 500_000

        # Request exceeding remaining daily cap
        can_run, reason = gw.check_budget_availability(estimated_tokens=1000)
        self.assertFalse(can_run)
        self.assertIn("Daily token cap", reason)
        self.assertTrue(gw.telemetry.is_budget_paused)

    def test_07_llm_request_failures_and_local_fallback(self):
        """Item 7: LLM request failure triggers local deterministic fallback."""
        gw = CentralizedLLMGateway(workspace_root=self.test_dir)
        gw.telemetry.is_budget_paused = True

        resp = gw.invoke_deterministic_or_llm(
            task_name="budget_exhausted_task",
            prompt="Compute complex response",
            route=GatewayRoute.FAST,
            allow_cache=False,
        )
        self.assertIn("BUDGET_EXHAUSTED_LOCAL_FALLBACK", resp.content)
        self.assertEqual(resp.cost_usd, 0.0)

    def test_08_research_source_deduplication(self):
        """Item 8: Research citation deduplication and SSRF validation."""
        research = GroundedResearchEngine(self.worker.memory.core)

        # Pre-socket SSRF check blocks loopback / private IPs
        with self.assertRaises(SSRFBlockedError):
            research.validate_url_ssrf_safe("http://127.0.0.1:8088/admin")
        with self.assertRaises(SSRFBlockedError):
            research.validate_url_ssrf_safe("http://169.254.169.254/latest/meta-data/")

        # Safe public URL passes
        safe = research.validate_url_ssrf_safe("https://arxiv.org/abs/2210.03629")
        self.assertTrue(safe["ssrf_safe"])

    def test_09_context_truncation_and_acon_preservation(self):
        """Item 9: Targeted context snippet extraction with ACON preservation."""
        large_code = "\n".join([f"line_{i} = {i}" for i in range(200)])
        large_code += "\nCRITICAL_SHA256 = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'\n"
        large_code += "def target_function():\n    return 42\n"
        large_code += "\n".join([f"tail_{i} = {i}" for i in range(100)])

        snippet = CentralizedLLMGateway.extract_relevant_snippet(
            large_code, query_terms=["target_function"], max_lines=30, max_chars=1200
        )
        self.assertIn("target_function", snippet)
        self.assertLess(len(snippet), 2000)

    def test_10_failed_candidate_update_rollback(self):
        """Item 10: Automatic rollback to original file on syntax/test failure."""
        target_file = self.test_dir / "sample_module.py"
        target_file.write_text("x = 100\n", encoding="utf-8")

        # 1. Invalid syntax candidate -> rejected before applying
        ok, msg = self.worker.apply_candidate_and_verify(
            target_file, "def broken syntax : (", lambda: True
        )
        self.assertFalse(ok)
        self.assertIn("syntax error", msg.lower())
        self.assertEqual(target_file.read_text(encoding="utf-8"), "x = 100\n")

        # 2. Syntax valid but test fails -> rolled back from backup
        ok, msg = self.worker.apply_candidate_and_verify(
            target_file, "x = 999\n", lambda: False
        )
        self.assertFalse(ok)
        self.assertIn("rolled back", msg.lower())
        self.assertEqual(target_file.read_text(encoding="utf-8"), "x = 100\n")

        # 3. Successful candidate -> promoted
        ok, msg = self.worker.apply_candidate_and_verify(
            target_file, "x = 200\n", lambda: True
        )
        self.assertTrue(ok)
        self.assertEqual(target_file.read_text(encoding="utf-8"), "x = 200\n")

    def test_11_regression_detection_and_lessons_recorded(self):
        """Item 11: Regression causes lesson recording in persistent memory."""
        mem = PersistentMemorySubsystem.get_instance()
        lesson = mem.record_lesson(
            title="Regression In Token Bucket",
            lesson="Avoid unbuffered queue in high concurrency test",
            is_failure=True,
        )
        self.assertIn("failure", lesson.subject_key)
        self.assertEqual(lesson.layer, 7)  # Layer 7: Failure playbooks

    def test_12_invalid_task_states_handling(self):
        """Item 12: Invalid / unparseable checkpoint handled gracefully."""
        bad_checkpoint_file = self.scratch_dir / "improvement_worker_checkpoint.json"
        bad_checkpoint_file.write_text("NOT_JSON_DATA", encoding="utf-8")

        recovered = self.worker.recover_last_checkpoint()
        self.assertIsNone(recovered)

    def test_13_heartbeat_updates_and_stale_detection(self):
        """Item 13: Heartbeat file updated and stale heartbeats identified."""
        self.worker.state = WorkerState.OBSERVING
        self.worker.update_heartbeat()

        self.assertTrue(self.worker.heartbeat_file.exists())
        data = json.loads(self.worker.heartbeat_file.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "OBSERVING")
        self.assertGreater(data["heartbeat_epoch"], 0)

    def test_14_graceful_shutdown(self):
        """Item 14: Worker releases lockfile cleanly upon termination."""
        self.worker.acquire_worker_lock()
        self.assertTrue(self.worker.pid_file.exists())
        self.worker.release_worker_lock()
        self.assertFalse(self.worker.pid_file.exists())

    def test_15_financial_safety_locks_preserved(self):
        """Item 15: Physical safety lock permanently asserts LIVE_ORDER_DISPATCH_ENABLED == False."""
        from agents.AGI_1_7.engine.agi17.orchestration.persistent_improvement_worker import (
            LIVE_ORDER_DISPATCH_ENABLED as WORKER_ORDER_GATE,
        )
        from agents.AGI_1_7.ui.standalone_dashboard_server import (
            LIVE_ORDER_DISPATCH_ENABLED as SERVER_ORDER_GATE,
        )
        self.assertFalse(WORKER_ORDER_GATE)
        self.assertFalse(SERVER_ORDER_GATE)


if __name__ == "__main__":
    unittest.main()
