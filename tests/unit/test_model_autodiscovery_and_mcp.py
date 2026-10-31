"""Test suite for Universal Model Auto-Discovery, Complete System Matches, MCP Ecosystem, and Auto-Learning.
================================================================================
Verifies that:
1. Dynamic Active Model Auto-Discovery: upstream endpoints are queried, optimal target
   is autonomously ranked and selected with zero user prompting.
2. Complete System Matches: 6-dimension compatibility matrix is verified.
3. 21 Embedded MCP servers can be discovered, installed, and validated.
4. Autonomous Learner analyzes Python ASTs and stores empirical heuristics in SQLite WAL.
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

from agents.IVA.engine.agi17.adapters.universal_api_provider import UniversalAPIProvider
from agents.IVA.engine.agi17.capabilities.capability_profiler import CapabilityProfiler
from agents.IVA.engine.agi17.learning.autonomous_learner import AutonomousLearner
from agents.IVA.engine.agi17.mcp.mcp_manager import MCPManager
from agents.IVA.engine.agi17.memory.omega_command_memory import OmegaCommandMemory
from agents.IVA.engine.agi17.runtime.terminal_client import TerminalClient


class TestModelAutoDiscoveryAndMCP(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="iva_autodiscover_test_"))
        self._orig_env = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._orig_env)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_auto_discover_optimal_model_gemini(self) -> None:
        mock_resp_data = {
            "models": [
                {"name": "models/gemini-1.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
            ]
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            provider = UniversalAPIProvider(
                provider_type="gemini",
                api_key="AIzaSy_MOCK_TEST_KEY_12345",
            )
            models = provider.fetch_remote_models()
            self.assertIn("gemini-2.5-flash", models)
            self.assertIn("gemini-2.5-pro", models)
            self.assertIn("gemini-1.5-flash", models)
            self.assertNotIn("text-embedding-004", models)  # Filtered non-content

            optimal = provider.auto_discover_optimal_model()
            self.assertEqual(optimal, "gemini-2.5-flash")

            status = provider.get_model_discovery_status()
            self.assertEqual(status["active_model"], "gemini-2.5-flash")
            self.assertTrue(status["has_key"])

    def test_02_system_match_report_verifies_all_6_dimensions(self) -> None:
        profiler = CapabilityProfiler(storage_root=self.temp_dir / "storage")
        report = profiler.get_system_match_report()

        self.assertIn("overall_match", report)
        self.assertEqual(report["total_dimensions"], 6)
        self.assertEqual(report["matches"], 6)
        self.assertIn("100% MATCHED", report["overall_match"])

        dim_names = [d["dimension"] for d in report["dimensions"]]
        self.assertIn("Host Platform & OS", dim_names)
        self.assertIn("Python Runtime & Stdlib Isolation", dim_names)
        self.assertIn("Persistent SQLite Memory WAL", dim_names)
        self.assertIn("Model Provider & Active Target Auto-Discovery", dim_names)
        self.assertIn("Specialist & MCP Tool Ecosystem", dim_names)
        self.assertIn("Physical Safety & Risk Invariants", dim_names)

        for d in report["dimensions"]:
            self.assertTrue(d["matched"])
            self.assertEqual(d["status"], "MATCHED")

    def test_03_mcp_manager_discovers_21_embedded_servers(self) -> None:
        mgr = MCPManager()
        servers = mgr.list_servers()

        self.assertGreaterEqual(len(servers), 21)
        server_names = [s["name"] for s in servers]
        self.assertIn("context7", server_names)
        self.assertIn("sequential-thinking", server_names)
        self.assertIn("gsd", server_names)
        self.assertIn("ponytail", server_names)
        self.assertIn("playwright", server_names)
        self.assertIn("github", server_names)
        self.assertIn("filesystem", server_names)

    def test_04_mcp_manager_install_and_test_server(self) -> None:
        mgr = MCPManager()
        install_res = mgr.install_server("context7")
        self.assertTrue(install_res["success"])
        self.assertEqual(install_res["server"], "context7")
        self.assertGreater(install_res["tools_count"], 0)

        test_res = mgr.test_server("context7")
        self.assertTrue(test_res["success"])
        self.assertEqual(test_res["status"], "PASSED")
        self.assertGreater(test_res["tools_verified_count"], 0)
        self.assertEqual(len(test_res["errors"]), 0)

    def test_05_autonomous_learner_analyzes_ast_and_stores_memory(self) -> None:
        sample_code = '''"""Sample module for autonomous learning verification."""

class AdaptivePortfolioEngine:
    """Manages adaptive capital sizing."""
    def __init__(self, capital: float):
        self.capital = capital

    def compute_kelly_fraction(self, win_rate: float, payoff: float) -> float:
        return max(0.0, (win_rate * (payoff + 1.0) - 1.0) / payoff)

def run_invariant_check() -> bool:
    return True
'''
        sample_file = self.temp_dir / "sample_engine.py"
        sample_file.write_text(sample_code, encoding="utf-8")

        mem = OmegaCommandMemory(primary_dir=self.temp_dir / "memory")
        learner = AutonomousLearner(memory=mem)

        res = learner.learn_file(sample_file)
        self.assertTrue(res["success"])
        self.assertEqual(res["analysis_type"], "PYTHON_AST")
        self.assertEqual(res["memory_layer"], 6)
        self.assertEqual(len(res["classes"]), 1)
        self.assertEqual(res["classes"][0]["name"], "AdaptivePortfolioEngine")
        self.assertIn("compute_kelly_fraction", res["classes"][0]["methods"])
        self.assertEqual(len(res["sha256"]), 64)

        # Verify persisted entry in SQLite
        retrieved = mem.retrieve(subject_key=res["subject_key"], layers=[6])
        self.assertGreaterEqual(len(retrieved), 1)
        self.assertIn("AdaptivePortfolioEngine", str(retrieved[0].structured_data.get("heuristics", [])))

    def test_06_autonomous_learner_concept_learning(self) -> None:
        mem = OmegaCommandMemory(primary_dir=self.temp_dir / "memory")
        learner = AutonomousLearner(memory=mem)

        res = learner.learn_concept(
            topic="Hawkes Self-Exciting Jump Diffusion",
            notes="Intensity function lambda(t) models volatility clustering across high-frequency tick regimes."
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["memory_layer"], 7)
        self.assertEqual(len(res["sha256"]), 64)

        retrieved = mem.retrieve(subject_key=res["subject_key"], layers=[7])
        self.assertGreaterEqual(len(retrieved), 1)
        self.assertIn("Hawkes Self-Exciting Jump Diffusion", retrieved[0].content)

    def test_07_terminal_commands_execution(self) -> None:
        client = TerminalClient(storage_root=self.temp_dir)
        buf = io.StringIO()

        with patch("sys.stdout", buf):
            client.print_models()
            client.print_sysmatch()
            client.print_mcp_list()
            client.execute_mcp_test("context7")
            client.print_version()

        output = buf.getvalue()
        self.assertIn("IVA ACTIVE MODEL TARGET & REMOTE MODEL AUTO-DISCOVERY", output)
        self.assertIn("IVA COMPLETE SYSTEM MATCH & COMPATIBILITY REPORT", output)
        self.assertIn("IVA MODEL CONTEXT PROTOCOL (MCP) ECOSYSTEM", output)
        self.assertIn("context7", output)
        self.assertIn("IVA AUTONOMOUS ENGINEERING PARTNER", output)


if __name__ == "__main__":
    unittest.main()
