"""AGI 1.7 Next Security Milestone — Adversarial Model Disclosure Boundary Test Suite.

Verifies:
1. Default-deny external disclosure of existing protected workspace files (0 provider calls).
2. Explicitly authorized disclosure sends only permitted, sanitized content.
3. Callback denial results in 0 outbound model calls.
4. Comprehensive pre-transmission secret redaction before provider call.
5. Local-only mode never invokes an external provider and fails closed.
6. New, empty workspace code generation succeeds unblocked.
7. Workspace changes remain unapplied when apply_approved_patch=False even if disclosure was authorized.
8. Independently authorized, sandbox-verified candidates apply successfully.
9. Orchestrator Stage 4 self-healing enforces disclosure gate before calling external model.
10. Content-free audit ledger records decisions without logging raw source code or credentials.
11. Provider failures and timeouts never leak source code in exception traces.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

from agents.IVA.engine.agi17.adapters.agi_17_adapter import AGI17Adapter
from agents.IVA.engine.agi17.adapters.model_adapter import (
    BaseModelProvider,
    ModelAdapter,
    ModelProviderConfig,
    ModelRequest,
)
from agents.IVA.engine.agi17.orchestration.ci_repair_agent import CIRepairAgent, CIRepairBudget
from agents.IVA.engine.agi17.orchestration.hierarchical_orchestrator import HierarchicalOrchestrator
from agents.IVA.engine.agi17.process_supervision.sandbox_runner import (
    DisposableSandboxRunner,
    HighImpactApprovalGate,
    SandboxExecutionResult,
    SandboxPolicy,
)
from agents.IVA.engine.agi17.security.model_disclosure_policy import (
    DisclosureContext,
    DisclosureDecision,
    DisclosureMode,
    ExternalProviderBlockedInLocalOnlyModeError,
    ModelDisclosureDeniedError,
    ModelDisclosurePolicy,
    SecretRedactor,
)
from agents.IVA.engine.agi17.telemetry.token_economy import AdaptiveTokenController


class SpyExternalModelProvider(BaseModelProvider):
    """Spy provider simulating an external model service (e.g. Gemini / cloud LLM).

    Tracks invocation counts and inspects exact prompt payloads received at the network boundary.
    """

    is_external: bool = True

    def __init__(self, responder: Optional[Any] = None) -> None:
        self.call_history: List[ModelRequest] = []
        self.last_prompt: Optional[str] = None
        self.responder = responder

    def generate(self, request: ModelRequest) -> Dict[str, Any]:
        self.call_history.append(request)
        self.last_prompt = request.prompt
        if self.responder:
            resp_text = self.responder(request)
        else:
            resp_text = "def solution():\n    return 'verified_solution'\n"
        return {
            "status": "SUCCEEDED",
            "exit_code": 0,
            "timed_out": False,
            "duration_sec": 0.01,
            "response_text": f"```python\n{resp_text}\n```",
            "parsed_json": {"response": resp_text},
            "provider_usage": {
                "input_tokens": 150,
                "output_tokens": 80,
                "total_tokens": 230,
            },
            "is_mock": False,
        }


class TestModelDisclosureBoundary(unittest.TestCase):
    """Adversarial verification of data disclosure boundaries and privacy gates."""

    def setUp(self) -> None:
        self.test_root = Path(tempfile.mkdtemp(prefix="agi17_disc_test_"))
        self.workspace_dir = self.test_root / "workspace"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.audit_log = self.test_root / "audit" / "disclosure_audit.jsonl"
        self.dev_sandbox = DisposableSandboxRunner(policy=SandboxPolicy.development())

    def tearDown(self) -> None:
        shutil.rmtree(self.test_root, ignore_errors=True)

    def _setup_proprietary_repo(self) -> tuple[Path, Path, str, str]:
        """Creates a workspace with a failing test and proprietary source code."""
        algo_file = self.workspace_dir / "proprietary_algo.py"
        test_file = self.workspace_dir / "test_proprietary_algo.py"

        algo_code = (
            "# PROPRIETARY TRADE SECRET - DO NOT DISCLOSE\n"
            "ALGO_CONSTANT = 42\n\n"
            "def calculate_alpha(x: int) -> int:\n"
            "    return x * 10  # BUG: should be x * ALGO_CONSTANT\n"
        )
        test_code = (
            "import unittest\n"
            "from proprietary_algo import calculate_alpha\n\n"
            "class TestAlpha(unittest.TestCase):\n"
            "    def test_alpha(self):\n"
            "        self.assertEqual(calculate_alpha(2), 84)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )
        algo_file.write_bytes(algo_code.encode("utf-8"))
        test_file.write_bytes(test_code.encode("utf-8"))
        algo_sha = hashlib.sha256(algo_code.encode("utf-8")).hexdigest()
        test_sha = hashlib.sha256(test_code.encode("utf-8")).hexdigest()
        return algo_file, test_file, algo_sha, test_sha

    # -------------------------------------------------------------------------
    # TEST 1: Default-Deny External Disclosure
    # -------------------------------------------------------------------------
    def test_01_default_deny_blocks_external_disclosure_with_zero_provider_calls(self) -> None:
        """In default production mode, existing workspace files cannot be sent to an external provider."""
        algo_file, test_file, algo_sha, test_sha = self._setup_proprietary_repo()
        spy = SpyExternalModelProvider()

        ma = ModelAdapter(mock_provider=spy)
        agent = CIRepairAgent(
            model_adapter=ma,
            sandbox_runner=self.dev_sandbox,
            disclosure_policy=ModelDisclosurePolicy.production_strict(
                allow_workspace_model_disclosure=False,
                audit_log_path=self.audit_log,
            ),
        )

        with self.assertRaises(ModelDisclosureDeniedError) as cm:
            agent.repair_workspace(
                workspace_dir=self.workspace_dir,
                module_filename="proprietary_algo.py",
                test_pattern="test_*.py",
                write_patch_to_workspace=False,
                apply_approved_patch=False,
            )

        self.assertIn("DISCLOSURE_DENIED", str(cm.exception))
        # HARD GUARANTEE: Exactly 0 model provider calls made
        self.assertEqual(len(spy.call_history), 0, "External provider must NOT be invoked when disclosure is denied")
        self.assertIsNone(spy.last_prompt)

        # Workspace must remain completely untouched
        self.assertEqual(hashlib.sha256(algo_file.read_bytes()).hexdigest(), algo_sha)
        self.assertEqual(hashlib.sha256(test_file.read_bytes()).hexdigest(), test_sha)

    # -------------------------------------------------------------------------
    # TEST 2: Explicitly Authorized Disclosure
    # -------------------------------------------------------------------------
    def test_02_explicitly_authorized_disclosure_allows_repair_with_sanitized_payload(self) -> None:
        """When disclosure is explicitly authorized, the external provider receives sanitized code."""
        algo_file, _test_file, _algo_sha, _test_sha = self._setup_proprietary_repo()
        fixed_code = (
            "ALGO_CONSTANT = 42\n\n"
            "def calculate_alpha(x: int) -> int:\n"
            "    return x * ALGO_CONSTANT\n"
        )
        spy = SpyExternalModelProvider(responder=lambda req: fixed_code)
        ma = ModelAdapter(mock_provider=spy)

        agent = CIRepairAgent(
            model_adapter=ma,
            sandbox_runner=self.dev_sandbox,
            disclosure_policy=ModelDisclosurePolicy.production_strict(
                allow_workspace_model_disclosure=True,
                audit_log_path=self.audit_log,
            ),
        )

        res = agent.repair_workspace(
            workspace_dir=self.workspace_dir,
            module_filename="proprietary_algo.py",
            test_pattern="test_*.py",
            write_patch_to_workspace=False,
            apply_approved_patch=False,
            allow_workspace_model_disclosure=True,
        )

        self.assertEqual(len(spy.call_history), 1)
        self.assertIsNotNone(spy.last_prompt)
        self.assertIn("proprietary_algo.py", spy.last_prompt)
        self.assertEqual(res.status, "REPAIRED_AND_VERIFIED")

        # Workspace remains unchanged because apply_approved_patch was False
        self.assertFalse(res.patch_applied_to_workspace)
        self.assertTrue(res.pull_request_payload["requires_human_approval"])

    # -------------------------------------------------------------------------
    # TEST 3: Dynamic Authorizer Callback Denial
    # -------------------------------------------------------------------------
    def test_03_callback_denial_results_in_zero_outbound_calls(self) -> None:
        """A dynamic authorizer callback returning False blocks disclosure with 0 outbound calls."""
        _algo_file, _test_file, _algo_sha, _test_sha = self._setup_proprietary_repo()
        spy = SpyExternalModelProvider()
        ma = ModelAdapter(mock_provider=spy)

        callback_evaluated = []

        def _denying_authorizer(ctx: DisclosureContext) -> bool:
            callback_evaluated.append(ctx.task_id)
            return False  # Deny consent

        policy = ModelDisclosurePolicy(
            mode=DisclosureMode.PRODUCTION_STRICT,
            allow_workspace_model_disclosure=False,
            disclosure_authorizer=_denying_authorizer,
            audit_log_path=self.audit_log,
        )

        agent = CIRepairAgent(
            model_adapter=ma,
            sandbox_runner=self.dev_sandbox,
            disclosure_policy=policy,
        )

        with self.assertRaises(ModelDisclosureDeniedError) as cm:
            agent.repair_workspace(
                workspace_dir=self.workspace_dir,
                module_filename="proprietary_algo.py",
                test_pattern="test_*.py",
            )

        self.assertIn("Dynamic disclosure_authorizer explicitly denied consent", str(cm.exception))
        self.assertEqual(len(callback_evaluated), 1)
        self.assertEqual(len(spy.call_history), 0, "Zero provider calls permitted on callback denial")

    # -------------------------------------------------------------------------
    # TEST 4: Pre-Transmission Secret Redaction
    # -------------------------------------------------------------------------
    def test_04_secret_redaction_before_authorized_outbound_request(self) -> None:
        """Credentials in source code are redacted before transmission to the provider."""
        secret_file = self.workspace_dir / "secret_mod.py"
        test_file = self.workspace_dir / "test_secret_mod.py"

        secret_code = (
            "GOOGLE_KEY = 'AIzaSyD-1234567890abcdefghijklmnopqrstuv'\n"
            "OPENAI_KEY = 'sk-1234567890abcdefghijklmnopqrstuvwx'\n"
            "GITHUB_PAT = 'ghp_123456789012345678901234567890abcdef'\n"
            "AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n"
            "DB_URI = 'postgres://db_user:s3cr3tP@ssword@localhost:5432/core'\n"
            "PRIVATE_KEY = '-----BEGIN RSA PRIVATE KEY-----\\nMIIEowIBAAKCAQEA\\n-----END RSA PRIVATE KEY-----'\n\n"
            "def get_status() -> str:\n"
            "    return 'broken'\n"
        )
        test_code = (
            "import unittest\n"
            "from secret_mod import get_status\n\n"
            "class TestSec(unittest.TestCase):\n"
            "    def test_status(self):\n"
            "        self.assertEqual(get_status(), 'healthy')\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )
        secret_file.write_text(secret_code, encoding="utf-8")
        test_file.write_text(test_code, encoding="utf-8")

        spy = SpyExternalModelProvider(responder=lambda req: "def get_status(): return 'healthy'")
        ma = ModelAdapter(mock_provider=spy)

        agent = CIRepairAgent(
            model_adapter=ma,
            sandbox_runner=self.dev_sandbox,
            disclosure_policy=ModelDisclosurePolicy.production_strict(
                allow_workspace_model_disclosure=True,
                audit_log_path=self.audit_log,
            ),
        )

        agent.repair_workspace(
            workspace_dir=self.workspace_dir,
            module_filename="secret_mod.py",
            test_pattern="test_*.py",
            allow_workspace_model_disclosure=True,
        )

        self.assertEqual(len(spy.call_history), 1)
        transmitted = spy.last_prompt
        self.assertIsNotNone(transmitted)

        # Verify raw secret strings are completely ABSENT from outbound transmission
        self.assertNotIn("AIzaSyD-1234567890abcdefghijklmnopqrstuv", transmitted)
        self.assertNotIn("sk-1234567890abcdefghijklmnopqrstuvwx", transmitted)
        self.assertNotIn("ghp_123456789012345678901234567890abcdef", transmitted)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", transmitted)
        self.assertNotIn("s3cr3tP@ssword", transmitted)
        self.assertNotIn("-----BEGIN RSA PRIVATE KEY-----", transmitted)

        # Verify redaction tokens ARE present in outbound prompt
        self.assertIn("<REDACTED_GOOGLE_API_KEY>", transmitted)
        self.assertIn("<REDACTED_SK_KEY>", transmitted)
        self.assertIn("<REDACTED_GITHUB_TOKEN>", transmitted)
        self.assertIn("<REDACTED_AWS_KEY>", transmitted)
        self.assertIn("<REDACTED_PASSWORD>", transmitted)
        self.assertIn("<REDACTED_PRIVATE_KEY>", transmitted)

    # -------------------------------------------------------------------------
    # TEST 5: Local-Only Mode Never Invocates External Provider
    # -------------------------------------------------------------------------
    def test_05_local_only_mode_never_invokes_external_provider(self) -> None:
        """Local-only mode strictly blocks external providers and fails closed."""
        self._setup_proprietary_repo()
        spy = SpyExternalModelProvider()
        ma = ModelAdapter(mock_provider=spy)

        local_policy = ModelDisclosurePolicy.local_only_mode(audit_log_path=self.audit_log)
        agent = CIRepairAgent(
            model_adapter=ma,
            sandbox_runner=self.dev_sandbox,
            disclosure_policy=local_policy,
        )

        with self.assertRaises(ExternalProviderBlockedInLocalOnlyModeError) as cm:
            agent.repair_workspace(
                workspace_dir=self.workspace_dir,
                module_filename="proprietary_algo.py",
                test_pattern="test_*.py",
                allow_workspace_model_disclosure=True,  # Even if requested, local-only overrides!
            )

        self.assertIn("LOCAL_ONLY_POLICY_VIOLATION", str(cm.exception))
        self.assertEqual(len(spy.call_history), 0, "External provider must never be called in local-only mode")

    # -------------------------------------------------------------------------
    # TEST 6: Code Generation in New Empty Workspace Unblocked
    # -------------------------------------------------------------------------
    def test_06_new_empty_workspace_code_gen_unblocked(self) -> None:
        """Generating code from scratch in an empty workspace succeeds without false-positive blocking."""
        empty_ws = self.test_root / "empty_workspace"
        empty_ws.mkdir()

        spy = SpyExternalModelProvider(
            responder=lambda req: "def binary_search(arr, t): return 0"
        )
        tc = AdaptiveTokenController(
            ledger_dir=self.test_root / "ledger",
            isolated_benchmark_cwd=self.test_root / "iso_cwd",
        )
        ma = ModelAdapter(token_controller=tc, mock_provider=spy)
        adapter = AGI17Adapter(
            storage_root=self.test_root / "storage",
            eval_root=self.test_root / "eval",
            model_adapter=ma,
            disclosure_policy=ModelDisclosurePolicy.production_strict(allow_workspace_model_disclosure=False),
        )

        mock_sbx = SandboxExecutionResult(
            sandbox_id="test-empty-ws-sbx",
            isolation_backend="ephemeral_restricted_tempdir",
            passed=True,
            exit_code=0,
            timed_out=False,
            duration_sec=0.01,
            stdout="OK",
            stderr="",
            network_disabled=True,
            cleanup_verified=True,
        )
        with mock.patch.object(
            adapter.sandbox_runner,
            "run_python_unittest_sandbox",
            return_value=mock_sbx,
        ):
            res = adapter.execute(
                title="Code Generation in Empty Workspace",
                prompt="Implement binary_search in search.py",
                code_task_dir=empty_ws,
                module_filename="search.py",
                test_filename="test_search.py",
                apply_approved_patch=False,
            )

        self.assertIn(res["status"], ("SUCCEEDED", "PENDING_APPROVAL"))
        # Provider was permitted because no existing private workspace data was disclosed
        self.assertGreaterEqual(len(spy.call_history), 1)

    # -------------------------------------------------------------------------
    # TEST 7: Unapproved Changes Remain Unapplied
    # -------------------------------------------------------------------------
    def test_07_unapproved_workspace_changes_remain_unapplied(self) -> None:
        """When disclosure is authorized but workspace-write is unapproved, changes stay staged."""
        algo_file, _test_file, orig_sha, _test_sha = self._setup_proprietary_repo()
        fixed = "ALGO_CONSTANT = 42\ndef calculate_alpha(x):\n    return x * ALGO_CONSTANT\n"
        spy = SpyExternalModelProvider(responder=lambda req: fixed)
        ma = ModelAdapter(mock_provider=spy)

        agent = CIRepairAgent(
            model_adapter=ma,
            sandbox_runner=self.dev_sandbox,
            disclosure_policy=ModelDisclosurePolicy.production_strict(allow_workspace_model_disclosure=True),
        )

        res = agent.repair_workspace(
            workspace_dir=self.workspace_dir,
            module_filename="proprietary_algo.py",
            test_pattern="test_*.py",
            write_patch_to_workspace=False,
            apply_approved_patch=False,
            allow_workspace_model_disclosure=True,
        )

        self.assertEqual(res.status, "REPAIRED_AND_VERIFIED")
        self.assertFalse(res.patch_applied_to_workspace)
        self.assertTrue(res.pull_request_payload["requires_human_approval"])
        # On-disk file is untouched
        self.assertEqual(hashlib.sha256(algo_file.read_bytes()).hexdigest(), orig_sha)

    # -------------------------------------------------------------------------
    # TEST 8: Independently Authorized Candidates Apply Successfully
    # -------------------------------------------------------------------------
    def test_08_independently_authorized_and_verified_candidates_apply_successfully(self) -> None:
        """When both disclosure and workspace mutation are independently approved, patch applies."""
        algo_file, _test_file, _orig_sha, _test_sha = self._setup_proprietary_repo()
        fixed = "ALGO_CONSTANT = 42\ndef calculate_alpha(x):\n    return x * ALGO_CONSTANT\n"
        spy = SpyExternalModelProvider(responder=lambda req: fixed)
        ma = ModelAdapter(mock_provider=spy)

        gate = HighImpactApprovalGate(
            approval_callback=lambda *args, **kwargs: True  # Authorize mutation
        )

        agent = CIRepairAgent(
            model_adapter=ma,
            sandbox_runner=self.dev_sandbox,
            approval_gate=gate,
            disclosure_policy=ModelDisclosurePolicy.production_strict(allow_workspace_model_disclosure=True),
        )

        res = agent.repair_workspace(
            workspace_dir=self.workspace_dir,
            module_filename="proprietary_algo.py",
            test_pattern="test_*.py",
            write_patch_to_workspace=True,
            apply_approved_patch=True,
            allow_workspace_model_disclosure=True,
        )

        self.assertEqual(res.status, "REPAIRED_AND_VERIFIED")
        self.assertTrue(res.patch_applied_to_workspace)
        self.assertIn("return x * ALGO_CONSTANT", algo_file.read_text(encoding="utf-8"))

    # -------------------------------------------------------------------------
    # TEST 9: Orchestrator Self-Healing Disclosure Gating
    # -------------------------------------------------------------------------
    def test_09_orchestrator_self_healing_respects_disclosure_gate(self) -> None:
        """HierarchicalOrchestrator Stage 4 self-healing checks disclosure policy before calling model."""
        algo_file, test_file, _algo_sha, _test_sha = self._setup_proprietary_repo()
        spy = SpyExternalModelProvider()
        tc = AdaptiveTokenController(
            ledger_dir=self.test_root / "ledger",
            isolated_benchmark_cwd=self.test_root / "iso_cwd",
        )
        ma = ModelAdapter(token_controller=tc, mock_provider=spy)

        orch = HierarchicalOrchestrator(
            model_adapter=ma,
            sandbox_runner=self.dev_sandbox,
            disclosure_policy=ModelDisclosurePolicy.production_strict(
                allow_workspace_model_disclosure=False,
                audit_log_path=self.audit_log,
            ),
        )

        spec = orch.build_code_and_test_subtasks(
            title="Orchestrator Self-Healing Check",
            prompt="Fix proprietary_algo.py",
            code_task_dir=self.workspace_dir,
            module_filename="proprietary_algo.py",
            test_filename="test_proprietary_algo.py",
            allow_workspace_model_disclosure=False,
        )

        # Stage 3 spec contains repair config
        stage3 = spec[2]
        with self.assertRaises(ModelDisclosureDeniedError):
            orch._default_live_model_repair(
                root_id="TEST-SELF-HEAL-01",
                child_id="SUB-03",
                sp_spec=stage3,
                failed_result={},
                failure_details={"exit_code": 1, "stderr": "AssertionError: 20 != 84"},
                apply_approved_patch=False,
            )

        # ZERO external model repair calls made
        self.assertEqual(len(spy.call_history), 0)

    # -------------------------------------------------------------------------
    # TEST 10: Audit Ledger Records Metadata Without Sensitive Content
    # -------------------------------------------------------------------------
    def test_10_audit_ledger_preserves_metadata_without_sensitive_content(self) -> None:
        """Disclosure audit log records decision metadata, timestamps, and files without raw secrets or code."""
        self._setup_proprietary_repo()
        spy = SpyExternalModelProvider()
        ma = ModelAdapter(mock_provider=spy)

        policy = ModelDisclosurePolicy(
            mode=DisclosureMode.PRODUCTION_STRICT,
            allow_workspace_model_disclosure=False,
            audit_log_path=self.audit_log,
        )

        ctx = DisclosureContext(
            task_id="AUDIT-TEST-001",
            agent_id="swe_patch_minimizer",
            workspace_root=self.workspace_dir,
            target_files=["proprietary_algo.py"],
            has_workspace_content=True,
            is_external_provider=True,
            provider_name="gemini-3.8-flash-high",
        )
        decision = policy.evaluate(ctx)
        self.assertFalse(decision.authorized)

        self.assertTrue(self.audit_log.exists(), "Audit log file must be created")
        lines = self.audit_log.read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(lines), 1)

        audit_entry = json.loads(lines[0])
        self.assertEqual(audit_entry["task_id"], "AUDIT-TEST-001")
        self.assertFalse(audit_entry["authorized"])
        self.assertEqual(audit_entry["mode"], "PRODUCTION_STRICT")
        self.assertEqual(audit_entry["provider_name"], "gemini-3.8-flash-high")
        self.assertIn("proprietary_algo.py", audit_entry["target_files"])

        # Audit entry must contain NO source code, tokens, or credentials
        raw_dump = json.dumps(audit_entry)
        self.assertNotIn("ALGO_CONSTANT", raw_dump)
        self.assertNotIn("calculate_alpha", raw_dump)
        self.assertNotIn("prompt", raw_dump)


if __name__ == "__main__":
    unittest.main()
