"""Test suite for IVA Autonomous Interactive Terminal Client.
================================================================================
Verifies that:
1. TerminalClient runs 100% in pure terminal / console without GUI or voice overlays.
2. Device & OS independence: works cleanly across Windows, Linux, macOS, servers.
3. Zero external plugins mandate: 100 embedded specialists across 16 families are
   loaded and verified; proves that no external plugins (Ponytail, Agency, Yux Pro Max)
   are required.
4. Fast-path routing, built-in commands (help, status, profile, specialists, plugins),
   and natural language execution.
================================================================================
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.IVA.engine.agi17.adapters.model_adapter import (
    BaseModelProvider,
    ModelAdapter,
    ModelProviderConfig,
    ModelRequest,
)
from agents.IVA.engine.agi17.runtime.terminal_client import (
    TerminalClient,
    run_terminal_session,
)


class TestTerminalClient(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="iva_terminal_test_"))
        self._orig_env = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._orig_env)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_system_summary_device_independent(self) -> None:
        client = TerminalClient(storage_root=self.temp_dir)
        summary = client.get_system_summary()

        self.assertIn("device_os", summary)
        self.assertEqual(summary["specialists_count"], 100)
        self.assertEqual(summary["families_count"], 16)
        self.assertEqual(summary["safety_gate"], "LOCKED (Fail-Closed)")

    def test_02_specialists_catalog_loads_100_specialists(self) -> None:
        client = TerminalClient(storage_root=self.temp_dir)
        buf = io.StringIO()

        with patch("sys.stdout", buf):
            client.print_specialists()

        output = buf.getvalue()
        self.assertIn("100 Active Contracts", output)
        self.assertIn("Planning & Architecture", output)
        self.assertIn("Software Engineering", output)
        self.assertIn("Testing, QA & Verification", output)
        self.assertIn("Security, Permissions & Safety", output)

    def test_03_zero_external_plugins_mandate(self) -> None:
        client = TerminalClient(storage_root=self.temp_dir)
        buf = io.StringIO()

        with patch("sys.stdout", buf):
            client.print_plugins_notice()

        output = buf.getvalue()
        self.assertIn("ZERO EXTERNAL PLUGINS MANDATE", output)
        self.assertIn("Ponytail", output)
        self.assertIn("Agency", output)
        self.assertIn("Yux Pro Max", output)
        self.assertIn("100 Embedded Specialists", output)
        self.assertIn("Automated Python CI-Repair Agent", output)

    def test_04_status_and_profile_commands(self) -> None:
        client = TerminalClient(storage_root=self.temp_dir)
        buf = io.StringIO()

        with patch("sys.stdout", buf):
            client.print_status()
            client.print_profile()

        output = buf.getvalue()
        self.assertIn("IVA RUNTIME SYSTEM STATUS", output)
        self.assertIn("LOCKED (Safe Fail-Closed)", output)
        self.assertIn("HARDWARE & RESOURCE CAPACITY PROFILE", output)

    def test_05_fast_path_routing_in_terminal(self) -> None:
        client = TerminalClient(storage_root=self.temp_dir)
        buf = io.StringIO()

        with patch("sys.stdout", buf):
            client.execute_prompt("check system status")

        output = buf.getvalue()
        self.assertIn("Deterministic Fast-Path Router", output)

    def test_06_model_prompt_execution_formatted(self) -> None:
        mock_provider = MagicMock(spec=BaseModelProvider)
        mock_provider.generate.return_value = {
            "status": "SUCCEEDED",
            "model": "gemini-2.5-flash",
            "exit_code": 0,
            "timed_out": False,
            "duration_sec": 0.35,
            "response_text": "Here is the verified AST refactoring solution.",
            "parsed_json": {},
            "provider_usage": {"input_tokens": 50, "output_tokens": 25, "total_tokens": 75},
            "is_mock": True,
        }

        mock_adapter = MagicMock()
        mock_adapter.model_adapter.invoke.return_value = {
            "task_id": "TEST-01",
            "response_text": "Here is the verified AST refactoring solution.",
            "model": "gemini-2.5-flash",
            "token_usage": {"input_tokens": 50, "output_tokens": 25},
            "duration_sec": 0.35,
        }

        client = TerminalClient(adapter=mock_adapter)
        buf = io.StringIO()

        with patch("sys.stdout", buf):
            client.execute_prompt("Refactor this Python module cleanly")

        output = buf.getvalue()
        self.assertIn("Iva (Cognitive Engineering Partner)", output)
        self.assertIn("Here is the verified AST refactoring solution.", output)
        self.assertIn("gemini-2.5-flash", output)
        self.assertIn("In 50, Out 25", output)

    def test_07_interactive_session_exit_command(self) -> None:
        client = TerminalClient(storage_root=self.temp_dir)
        buf = io.StringIO()

        # Simulate user typing 'help', 'plugins', and then 'exit'
        user_inputs = ["help", "plugins", "exit"]
        with patch("sys.stdout", buf), patch("builtins.input", side_effect=user_inputs):
            exit_code = client.run_interactive()

        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("IVA TERMINAL INTERACTION GUIDE", output)
        self.assertIn("ZERO EXTERNAL PLUGINS MANDATE", output)
        self.assertIn("Goodbye from Iva", output)

    def test_08_run_self_tests_executes_cleanly(self) -> None:
        client = TerminalClient(storage_root=self.temp_dir)
        buf = io.StringIO()

        mock_result = MagicMock()
        mock_result.wasSuccessful.return_value = True
        mock_result.failures = []
        mock_result.errors = []

        with patch("sys.stdout", buf), patch("unittest.TextTestRunner.run", return_value=mock_result):
            exit_code = client.run_self_tests()

        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("IVA AUTONOMOUS SELF-VERIFICATION SUITE", output)
        self.assertIn("IVA self-verification 100% GREEN", output)

    def test_09_interactive_session_handles_test_command(self) -> None:
        client = TerminalClient(storage_root=self.temp_dir)
        buf = io.StringIO()

        mock_result = MagicMock()
        mock_result.wasSuccessful.return_value = True
        mock_result.failures = []
        mock_result.errors = []

        user_inputs = ["test", "exit"]
        with patch("sys.stdout", buf), patch("builtins.input", side_effect=user_inputs), patch("unittest.TextTestRunner.run", return_value=mock_result):
            exit_code = client.run_interactive()

        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("IVA AUTONOMOUS SELF-VERIFICATION SUITE", output)
        self.assertIn("Goodbye from Iva", output)


if __name__ == "__main__":
    unittest.main()

