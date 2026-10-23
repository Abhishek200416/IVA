"""Test suite for IVA Universal API Provider & Universal ModelAdapter Access.
================================================================================
Verifies that IVA can operate anywhere using direct cloud/on-prem API keys
(Google Gemini, OpenAI, DeepSeek, OpenRouter) via standard library urllib
without requiring Google Antigravity or any proprietary host executables.
================================================================================
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.IVA.engine.agi17.adapters.model_adapter import (
    ModelAdapter,
    ModelProviderConfig,
    ModelRequest,
    ModelResponse,
)
from agents.IVA.engine.agi17.adapters.universal_api_provider import (
    UniversalAPIProvider,
    load_repo_dotenv,
)


class TestUniversalAPIProvider(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="iva_api_test_"))
        self._orig_env = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._orig_env)
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_dotenv_loading_standard_library(self) -> None:
        env_file = self.temp_dir / ".env"
        env_file.write_text(
            "# Comment line\n"
            "GEMINI_API_KEY=AIzaSySyntheticTestKey1234567890\n"
            "OPENAI_MODEL='gpt-4o-mini'\n"
            "EMPTY_VAL=\n",
            encoding="utf-8",
        )
        # Clear target env vars
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("OPENAI_MODEL", None)

        with patch("pathlib.Path.cwd", return_value=self.temp_dir):
            loaded = load_repo_dotenv()
            self.assertEqual(os.environ.get("GEMINI_API_KEY"), "AIzaSySyntheticTestKey1234567890")
            self.assertEqual(os.environ.get("OPENAI_MODEL"), "gpt-4o-mini")

    def test_02_credential_detection(self) -> None:
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)

        with patch("agents.IVA.engine.agi17.adapters.universal_api_provider.load_repo_dotenv", return_value={}):
            self.assertFalse(UniversalAPIProvider.has_available_credentials())

            os.environ["GEMINI_API_KEY"] = "AIzaSySyntheticKey"
            self.assertTrue(UniversalAPIProvider.has_available_credentials())

    def test_03_gemini_rest_call_success(self) -> None:
        provider = UniversalAPIProvider(
            api_key="AIzaSySyntheticTestKey",
            provider_type="gemini",
            model_name="gemini-2.5-flash",
        )
        fake_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "{\"answer\": \"Synthetic Gemini Output\"}"}]
                    },
                    "finishReason": "STOP"
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 42,
                "candidatesTokenCount": 18,
                "totalTokenCount": 60
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_response).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        req = ModelRequest(
            task_id="TASK-GEMINI-01",
            prompt="Analyze architectural trade-off",
            agent_id="plan_systems_architect",
        )

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            res = provider.generate(req)
            self.assertEqual(res["status"], "SUCCEEDED")
            self.assertEqual(res["exit_code"], 0)
            self.assertIn("Synthetic Gemini Output", res["response_text"])
            self.assertEqual(res["parsed_json"], {"answer": "Synthetic Gemini Output"})
            self.assertEqual(res["provider_usage"]["input_tokens"], 42)
            self.assertEqual(res["provider_usage"]["output_tokens"], 18)
            self.assertFalse(res["is_mock"])

            # Verify request URL format
            called_req = mock_urlopen.call_args[0][0]
            self.assertIn("models/gemini-2.5-flash:generateContent?key=AIzaSySyntheticTestKey", called_req.full_url)

    def test_04_openai_rest_call_success(self) -> None:
        provider = UniversalAPIProvider(
            api_key="sk-synthetic-openai-key-12345678",
            provider_type="openai",
            model_name="gpt-4o-mini",
            base_url="https://api.openai.com/v1",
        )
        fake_response = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "{\"status\": \"OpenAI OK\"}"},
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 55,
                "completion_tokens": 25,
                "total_tokens": 80
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_response).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        req = ModelRequest(
            task_id="TASK-OPENAI-01",
            prompt="Refactor Python AST module",
            agent_id="swe_python_runtime_engineer",
        )

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            res = provider.generate(req)
            self.assertEqual(res["status"], "SUCCEEDED")
            self.assertEqual(res["exit_code"], 0)
            self.assertIn("OpenAI OK", res["response_text"])
            self.assertEqual(res["parsed_json"], {"status": "OpenAI OK"})
            self.assertEqual(res["provider_usage"]["input_tokens"], 55)
            self.assertEqual(res["provider_usage"]["output_tokens"], 25)

            called_req = mock_urlopen.call_args[0][0]
            self.assertEqual(called_req.full_url, "https://api.openai.com/v1/chat/completions")
            self.assertEqual(called_req.headers.get("Authorization"), "Bearer sk-synthetic-openai-key-12345678")

    def test_05_model_adapter_delegation_to_universal_api(self) -> None:
        fake_api_provider = MagicMock(spec=UniversalAPIProvider)
        fake_api_provider.generate.return_value = {
            "status": "SUCCEEDED",
            "exit_code": 0,
            "timed_out": False,
            "duration_sec": 0.12,
            "response_text": "{\"result\": \"Universal Edge Execution Verified\"}",
            "parsed_json": {"result": "Universal Edge Execution Verified"},
            "provider_usage": {"input_tokens": 80, "output_tokens": 40, "total_tokens": 120},
            "is_mock": False,
            "notification_id": "UNIV-001",
        }

        adapter = ModelAdapter(
            api_provider=fake_api_provider,
            config=ModelProviderConfig(model_name="gemini-3.8-flash-high"),
        )
        res = adapter.invoke(
            task_id="TASK-UNIV-01",
            prompt="Compute volatility surface",
            agent_id="quant_analyst",
        )

        self.assertEqual(res["status"], "SUCCEEDED")
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("Universal Edge Execution Verified", res["response_text"])
        self.assertEqual(res["parsed_json"]["result"], "Universal Edge Execution Verified")
        self.assertFalse(res["is_mock"])
        self.assertEqual(res["token_usage"]["accounting_mode"], "UNIVERSAL_API")

    def test_06_helpful_error_when_no_engine_available(self) -> None:
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)

        adapter = ModelAdapter(
            mock_provider=None,
            api_provider=None,
            agy_path=self.temp_dir / "nonexistent_agy.exe",
        )
        with self.assertRaises(RuntimeError) as ctx:
            adapter.invoke(task_id="TASK-NO-PROVIDER", prompt="Hello")

        self.assertIn("GEMINI_API_KEY", str(ctx.exception))
    def test_07_model_adapter_with_api_key_and_model(self) -> None:
        adapter = ModelAdapter(
            api_key="AIzaSyExplicitPassedKey",
            model_name="gemini-2.0-flash",
            mock_provider=None,
        )
        self.assertIsNotNone(adapter.api_provider)
        self.assertIsInstance(adapter.api_provider, UniversalAPIProvider)
        self.assertEqual(adapter.api_provider.api_key, "AIzaSyExplicitPassedKey")
        self.assertEqual(adapter.api_provider.model_name, "gemini-2.0-flash")

    def test_08_agi17_adapter_passes_api_key_and_model(self) -> None:
        from agents.IVA.engine.agi17.adapters.agi_17_adapter import AGI17Adapter
        adapter = AGI17Adapter(
            storage_root=self.temp_dir,
            api_key="AIzaSyAdapterTestKey",
            model="gemini-2.5-flash",
        )
        self.assertIsNotNone(adapter.model_adapter.api_provider)
        self.assertEqual(adapter.model_adapter.api_provider.api_key, "AIzaSyAdapterTestKey")
        self.assertEqual(adapter.model_adapter.api_provider.model_name, "gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()

