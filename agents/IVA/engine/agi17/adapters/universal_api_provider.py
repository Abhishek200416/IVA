"""IVA Universal API Provider — Universal Direct Cloud & On-Premises API Execution.
================================================================================
Enables IVA to operate ANYWHERE across any cloud, local, or server environment
using standard API keys (Google Gemini, OpenAI, DeepSeek, Groq, OpenRouter, Ollama)
without requiring Google Antigravity or any proprietary host executables.

Requires ZERO external PyPI dependencies (100% Python standard library: urllib.request).
================================================================================
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .model_adapter import (
    BaseModelProvider,
    ModelCostBudgetExceededError,
    ModelProviderConfig,
    ModelRequest,
    ModelResponseValidationError,
    redact_sensitive_text,
)

logger = logging.getLogger("UniversalAPIProvider")


def load_repo_dotenv() -> Dict[str, str]:
    """Loads variables from the repository's `.env` file into `os.environ` if not already set.
    
    Uses 100% standard library Python line parsing (no external dotenv dependency needed).
    """
    loaded = {}
    current = Path(__file__).resolve()
    # Ascend up to repository root
    repo_root = current.parents[5] if len(current.parents) >= 6 else Path.cwd()
    candidates = [
        repo_root / ".env",
        Path.cwd() / ".env",
    ]
    for env_file in candidates:
        if env_file.is_file():
            try:
                for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
                        loaded[key] = val
                if loaded:
                    break
            except Exception as exc:
                logger.debug("Failed reading .env from %s: %s", env_file, exc)
    return loaded


# Automatically load local .env if present upon import
load_repo_dotenv()


class UniversalAPIProvider(BaseModelProvider):
    """Production standard library provider supporting direct Google Gemini and OpenAI-compatible endpoints."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        provider_type: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_sec: float = 60.0,
        max_retries: int = 3,
        backoff_sec: float = 1.0,
    ) -> None:
        load_repo_dotenv()
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.backoff_sec = backoff_sec

        # Resolve credentials and provider type
        gemini_key = api_key if (provider_type == "gemini") else (api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        anthropic_key = api_key if (provider_type == "anthropic") else (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY"))
        openai_key = api_key if (provider_type == "openai") else os.environ.get("OPENAI_API_KEY")
        groq_key = os.environ.get("GROQ_API_KEY")
        deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        custom_base = base_url or os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL")

        if provider_type:
            self.provider_type = provider_type.lower()
        elif anthropic_key:
            self.provider_type = "anthropic"
        elif gemini_key:
            self.provider_type = "gemini"
        elif groq_key:
            self.provider_type = "groq"
        elif deepseek_key:
            self.provider_type = "deepseek"
        elif openrouter_key:
            self.provider_type = "openrouter"
        elif openai_key or custom_base:
            self.provider_type = "openai"
        else:
            self.provider_type = "gemini"  # Default fallback

        if self.provider_type == "gemini":
            self.api_key = gemini_key or api_key or ""
            # Default to gemini-2.5-flash or gemini-2.0-flash (fast, reliable, free tiers available)
            self.model_name = (
                model_name
                or os.environ.get("GEMINI_MODEL")
                or os.environ.get("IVA_MODEL")
                or "gemini-2.5-flash"
            )
            self.base_url = (
                base_url
                or os.environ.get("GEMINI_BASE_URL")
                or "https://generativelanguage.googleapis.com/v1beta"
            ).rstrip("/")
        elif self.provider_type == "anthropic":
            self.api_key = anthropic_key or api_key or ""
            self.model_name = (
                model_name
                or os.environ.get("ANTHROPIC_MODEL")
                or os.environ.get("IVA_MODEL")
                or "claude-3-5-sonnet-20241022"
            )
            self.base_url = (
                base_url
                or os.environ.get("ANTHROPIC_BASE_URL")
                or "https://api.anthropic.com/v1"
            ).rstrip("/")
        elif self.provider_type == "groq":
            self.api_key = groq_key or api_key or ""
            self.model_name = (
                model_name
                or os.environ.get("GROQ_MODEL")
                or os.environ.get("IVA_MODEL")
                or "llama-3.3-70b-versatile"
            )
            self.base_url = (
                base_url
                or os.environ.get("GROQ_BASE_URL")
                or "https://api.groq.com/openai/v1"
            ).rstrip("/")
            self.provider_type = "openai"
        elif self.provider_type == "deepseek":
            self.api_key = deepseek_key or api_key or ""
            self.model_name = (
                model_name
                or os.environ.get("DEEPSEEK_MODEL")
                or os.environ.get("IVA_MODEL")
                or "deepseek-chat"
            )
            self.base_url = (
                base_url
                or os.environ.get("DEEPSEEK_BASE_URL")
                or "https://api.deepseek.com/v1"
            ).rstrip("/")
            self.provider_type = "openai"
        elif self.provider_type == "openrouter":
            self.api_key = openrouter_key or api_key or ""
            self.model_name = (
                model_name
                or os.environ.get("OPENROUTER_MODEL")
                or os.environ.get("IVA_MODEL")
                or "anthropic/claude-3.5-sonnet"
            )
            self.base_url = (
                base_url
                or os.environ.get("OPENROUTER_BASE_URL")
                or "https://openrouter.ai/api/v1"
            ).rstrip("/")
            self.provider_type = "openai"
        else:
            self.api_key = openai_key or api_key or ""
            self.model_name = (
                model_name
                or os.environ.get("OPENAI_MODEL")
                or os.environ.get("IVA_MODEL")
                or "gpt-4o-mini"
            )
            self.base_url = (
                base_url
                or os.environ.get("OPENAI_BASE_URL")
                or "https://api.openai.com/v1"
            ).rstrip("/")
        self.call_history: List[ModelRequest] = []
        self.available_models: List[str] = []
        self.auto_discovered: bool = False
        self.auto_discovery_attempted: bool = False

        # If user did not specify an explicit model override, autonomously fetch and select from API key
        explicit_model = model_name or os.environ.get("IVA_MODEL") or os.environ.get(f"{self.provider_type.upper()}_MODEL")
        if not explicit_model and self.api_key:
            try:
                discovered = self.auto_discover_optimal_model()
                if discovered:
                    self.model_name = discovered
                    self.auto_discovered = True
            except Exception as exc:
                logger.debug("Auto-discovery of optimal model deferred: %s", exc)

    def fetch_remote_models(self) -> List[str]:
        """Queries the upstream provider REST endpoint using the active API key to fetch available models.
        
        Uses 100% Python standard library urllib.request without external dependencies.
        Returns a list of model identifier strings.
        """
        if not self.api_key and not (self.base_url and ("localhost" in self.base_url or "127.0.0.1" in self.base_url)):
            return []

        ctx = ssl.create_default_context()
        try:
            if self.provider_type == "gemini":
                endpoint = f"{self.base_url}/models?key={self.api_key}"
                req = urllib.request.Request(
                    endpoint,
                    headers={"User-Agent": "IVA-Autonomous-Partner/1.7.29"},
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=4.0, context=ctx) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = []
                    for m in data.get("models", []):
                        m_name = m.get("name", "")
                        if m_name.startswith("models/"):
                            m_name = m_name[len("models/"):]
                        methods = m.get("supportedGenerationMethods", [])
                        if not methods or "generateContent" in methods:
                            models.append(m_name)
                    self.available_models = models
                    return models
            elif self.provider_type == "anthropic":
                endpoint = f"{self.base_url}/models"
                req = urllib.request.Request(
                    endpoint,
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "User-Agent": "IVA-Autonomous-Partner/1.7.29",
                    },
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=4.0, context=ctx) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("id") for m in data.get("data", []) if m.get("id")]
                    self.available_models = models
                    return models
            else:
                endpoint = f"{self.base_url}/models"
                req = urllib.request.Request(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "User-Agent": "IVA-Autonomous-Partner/1.7.29",
                    },
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=4.0, context=ctx) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("id") for m in data.get("data", []) if m.get("id")]
                    self.available_models = models
                    return models
        except Exception as exc:
            logger.debug("Automatic remote model fetching for %s skipped/failed: %s", self.provider_type, exc)
            return []

    def auto_discover_optimal_model(self) -> str:
        """Autonomously inspects available remote models from the active API key and selects the best model.
        
        Zero user prompting: dynamically ranks and picks the optimal model target.
        Falls back to proven defaults if offline or rate-limited.
        """
        self.auto_discovery_attempted = True
        candidates = self.fetch_remote_models()
        if not candidates:
            defaults = {
                "gemini": "gemini-2.5-flash",
                "anthropic": "claude-3-5-sonnet-20241022",
                "groq": "llama-3.3-70b-versatile",
                "deepseek": "deepseek-chat",
                "openrouter": "anthropic/claude-3.5-sonnet",
                "openai": "gpt-4o-mini",
            }
            return defaults.get(self.provider_type, "gemini-2.5-flash")

        preferences = {
            "gemini": [
                "gemini-2.5-flash",
                "gemini-2.5-pro",
                "gemini-2.0-flash",
                "gemini-2.0-flash-exp",
                "gemini-1.5-pro",
                "gemini-1.5-flash",
                "gemini-1.5-flash-8b",
            ],
            "openai": [
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-4-turbo",
                "gpt-4",
                "o1-preview",
                "o1-mini",
                "gpt-3.5-turbo",
            ],
            "anthropic": [
                "claude-3-5-sonnet-20241022",
                "claude-3-5-sonnet-latest",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ],
            "groq": [
                "llama-3.3-70b-versatile",
                "llama-3.1-70b-versatile",
                "llama-3.1-8b-instant",
                "mixtral-8x7b-32768",
            ],
            "deepseek": [
                "deepseek-chat",
                "deepseek-coder",
            ],
            "openrouter": [
                "anthropic/claude-3.5-sonnet",
                "google/gemini-2.5-flash",
                "openai/gpt-4o",
                "meta-llama/llama-3.3-70b-instruct",
            ],
        }

        pref_list = preferences.get(self.provider_type, preferences.get("openai", []))
        for pref in pref_list:
            if pref in candidates:
                logger.info("Auto-discovered and selected optimal model: %s", pref)
                return pref
            for c in candidates:
                if c.startswith(pref):
                    logger.info("Auto-discovered and selected optimal model (matched): %s", c)
                    return c

        return candidates[0]

    def get_model_discovery_status(self) -> Dict[str, Any]:
        """Returns structured metadata about model auto-discovery."""
        return {
            "provider_type": self.provider_type,
            "active_model": self.model_name,
            "auto_discovered": getattr(self, "auto_discovered", False),
            "available_models_count": len(getattr(self, "available_models", [])),
            "available_models": getattr(self, "available_models", []),
            "base_url": self.base_url,
            "has_key": bool(self.api_key),
        }

    @classmethod
    def has_available_credentials(cls) -> bool:
        """Returns True if valid API credentials are present in environment or .env file."""
        load_repo_dotenv()
        return bool(
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("CLAUDE_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("GROQ_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("OPENAI_API_BASE")
        )

    def generate(self, request: ModelRequest) -> Dict[str, Any]:
        """Executes a model request via direct REST API and returns structured execution metadata."""
        self.call_history.append(request)
        t0 = time.perf_counter()

        if not self.api_key and not (self.base_url and ("localhost" in self.base_url or "127.0.0.1" in self.base_url)):
            raise RuntimeError(
                "UniversalAPIProvider requires an API key. Please set GEMINI_API_KEY (Google Gemini), "
                "ANTHROPIC_API_KEY (Anthropic Claude), OPENAI_API_KEY (OpenAI), GROQ_API_KEY (Groq), "
                "or DEEPSEEK_API_KEY in your local .env file or environment variable."
            )

        if self.provider_type == "gemini":
            return self._call_gemini_rest(request, t0)
        elif self.provider_type == "anthropic":
            return self._call_anthropic_rest(request, t0)
        else:
            return self._call_openai_rest(request, t0)

    def _call_gemini_rest(self, request: ModelRequest, start_time: float) -> Dict[str, Any]:
        """Calls Google Gemini GenerateContent REST API using Python standard library urllib."""
        eff_model = getattr(request, "model_override", None) or self.model_name
        # Sanitize model name for Google API path
        if eff_model.startswith("models/"):
            eff_model = eff_model[len("models/"):]
        endpoint = f"{self.base_url}/models/{eff_model}:generateContent?key={self.api_key}"

        payload: Dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": request.prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192,
            }
        }
        sys_inst = getattr(request, "system_instruction", None)
        if sys_inst:
            payload["systemInstruction"] = {
                "parts": [{"text": str(sys_inst)}]
            }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "IVA-Autonomous-Partner/1.7.29",
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(endpoint, data=data_bytes, headers=headers, method="POST")
            try:
                # SSL context with default verification
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(req, timeout=self.timeout_sec, context=ctx) as resp:
                    resp_bytes = resp.read()
                    data = json.loads(resp_bytes.decode("utf-8"))
                    dt = max(0.001, time.perf_counter() - start_time)

                    # Extract candidate text
                    candidates = data.get("candidates", [])
                    response_text = ""
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            response_text = parts[0].get("text", "")

                    parsed_json = {}
                    if response_text.strip().startswith("{") or response_text.strip().startswith("["):
                        try:
                            parsed_json = json.loads(response_text.strip())
                        except Exception:
                            parsed_json = {}

                    usage_meta = data.get("usageMetadata", {})
                    input_toks = usage_meta.get("promptTokenCount", max(1, len(request.prompt) // 4))
                    output_toks = usage_meta.get("candidatesTokenCount", max(1, len(response_text) // 4))
                    cached_toks = usage_meta.get("cachedContentTokenCount", 0)

                    return {
                        "status": "SUCCEEDED",
                        "model": eff_model,
                        "exit_code": 0,
                        "timed_out": False,
                        "duration_sec": round(dt, 4),
                        "response_text": response_text,
                        "parsed_json": parsed_json,
                        "provider_usage": {
                            "input_tokens": input_toks,
                            "output_tokens": output_toks,
                            "thinking_tokens": 0,
                            "cached_tokens": cached_toks,
                            "total_tokens": input_toks + output_toks,
                        },
                        "is_mock": False,
                        "notification_id": f"GEMINI-API-{request.task_id}",
                        "stdout_log_path": None,
                        "stderr_log_path": None,
                    }
            except urllib.error.HTTPError as he:
                error_body = ""
                try:
                    error_body = he.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                last_error = f"HTTP {he.code}: {he.reason} - {error_body[:200]}"
                logger.warning("Gemini API call attempt %d failed: %s", attempt, last_error)
                if he.code in (429, 500, 503):
                    time.sleep(self.backoff_sec * (2 ** (attempt - 1)))
                else:
                    break
            except urllib.error.URLError as ue:
                last_error = f"URLError: {ue.reason}"
                logger.warning("Gemini network error attempt %d: %s", attempt, last_error)
                time.sleep(self.backoff_sec * attempt)
            except Exception as e:
                last_error = f"Unexpected error: {str(e)}"
                logger.error("Gemini unexpected error attempt %d: %s", attempt, last_error)
                time.sleep(self.backoff_sec)

        dt = max(0.001, time.perf_counter() - start_time)
        return {
            "status": "FAILED",
            "model": eff_model,
            "exit_code": 1,
            "timed_out": False,
            "duration_sec": round(dt, 4),
            "response_text": "",
            "parsed_json": {},
            "provider_usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "thinking_tokens": 0,
                "cached_tokens": 0,
                "total_tokens": 0,
            },
            "error_message": redact_sensitive_text(str(last_error or "Unknown error")),
            "is_mock": False,
            "notification_id": f"GEMINI-FAILED-{request.task_id}",
            "stdout_log_path": None,
            "stderr_log_path": None,
        }

    def _call_openai_rest(self, request: ModelRequest, start_time: float) -> Dict[str, Any]:
        """Calls OpenAI-compatible /chat/completions endpoint using standard library urllib."""
        eff_model = getattr(request, "model_override", None) or self.model_name
        endpoint = f"{self.base_url}/chat/completions"

        messages = []
        sys_inst = getattr(request, "system_instruction", None)
        if sys_inst:
            messages.append({"role": "system", "content": str(sys_inst)})
        messages.append({"role": "user", "content": request.prompt})

        payload: Dict[str, Any] = {
            "model": eff_model,
            "messages": messages,
            "temperature": 0.2,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "IVA-Autonomous-Partner/1.7.29",
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(endpoint, data=data_bytes, headers=headers, method="POST")
            try:
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(req, timeout=self.timeout_sec, context=ctx) as resp:
                    resp_bytes = resp.read()
                    data = json.loads(resp_bytes.decode("utf-8"))
                    dt = max(0.001, time.perf_counter() - start_time)

                    choices = data.get("choices", [])
                    response_text = ""
                    if choices:
                        msg = choices[0].get("message", {})
                        response_text = msg.get("content", "")

                    parsed_json = {}
                    if response_text.strip().startswith("{") or response_text.strip().startswith("["):
                        try:
                            parsed_json = json.loads(response_text.strip())
                        except Exception:
                            parsed_json = {}

                    usage = data.get("usage", {})
                    input_toks = usage.get("prompt_tokens", max(1, len(request.prompt) // 4))
                    output_toks = usage.get("completion_tokens", max(1, len(response_text) // 4))

                    return {
                        "status": "SUCCEEDED",
                        "model": eff_model,
                        "exit_code": 0,
                        "timed_out": False,
                        "duration_sec": round(dt, 4),
                        "response_text": response_text,
                        "parsed_json": parsed_json,
                        "provider_usage": {
                            "input_tokens": input_toks,
                            "output_tokens": output_toks,
                            "thinking_tokens": 0,
                            "cached_tokens": 0,
                            "total_tokens": input_toks + output_toks,
                        },
                        "is_mock": False,
                        "notification_id": f"OPENAI-API-{request.task_id}",
                        "stdout_log_path": None,
                        "stderr_log_path": None,
                    }
            except urllib.error.HTTPError as he:
                error_body = ""
                try:
                    error_body = he.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                last_error = f"HTTP {he.code}: {he.reason} - {error_body[:200]}"
                logger.warning("OpenAI API call attempt %d failed: %s", attempt, last_error)
                if he.code in (429, 500, 503):
                    time.sleep(self.backoff_sec * (2 ** (attempt - 1)))
                else:
                    break
            except urllib.error.URLError as ue:
                last_error = f"URLError: {ue.reason}"
                logger.warning("OpenAI network error attempt %d: %s", attempt, last_error)
                time.sleep(self.backoff_sec * attempt)
            except Exception as e:
                last_error = f"Unexpected error: {str(e)}"
                logger.error("OpenAI unexpected error attempt %d: %s", attempt, last_error)
                time.sleep(self.backoff_sec)

        dt = max(0.001, time.perf_counter() - start_time)
        return {
            "status": "FAILED",
            "model": eff_model,
            "exit_code": 1,
            "timed_out": False,
            "duration_sec": round(dt, 4),
            "response_text": "",
            "parsed_json": {},
            "provider_usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "thinking_tokens": 0,
                "cached_tokens": 0,
                "total_tokens": 0,
            },
            "error_message": redact_sensitive_text(str(last_error or "Unknown error")),
            "is_mock": False,
            "notification_id": f"OPENAI-FAILED-{request.task_id}",
            "stdout_log_path": None,
            "stderr_log_path": None,
        }

    def _call_anthropic_rest(self, request: ModelRequest, start_time: float) -> Dict[str, Any]:
        """Calls Anthropic Messages API using standard library urllib."""
        eff_model = getattr(request, "model_override", None) or self.model_name
        endpoint = f"{self.base_url}/messages"

        payload: Dict[str, Any] = {
            "model": eff_model,
            "max_tokens": 8192,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        sys_inst = getattr(request, "system_instruction", None)
        if sys_inst:
            payload["system"] = str(sys_inst)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": "IVA-Autonomous-Partner/1.7.29",
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(endpoint, data=data_bytes, headers=headers, method="POST")
            try:
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(req, timeout=self.timeout_sec, context=ctx) as resp:
                    resp_bytes = resp.read()
                    parsed = json.loads(resp_bytes.decode("utf-8"))
                    dt = max(0.001, time.perf_counter() - start_time)

                    resp_text = ""
                    for block in parsed.get("content", []):
                        if block.get("type") == "text":
                            resp_text += block.get("text", "")

                    usage = parsed.get("usage", {})
                    in_toks = int(usage.get("input_tokens", 0))
                    out_toks = int(usage.get("output_tokens", 0))

                    return {
                        "status": "SUCCEEDED",
                        "model": parsed.get("model", eff_model),
                        "exit_code": 0,
                        "timed_out": False,
                        "duration_sec": round(dt, 4),
                        "response_text": resp_text,
                        "parsed_json": {},
                        "provider_usage": {
                            "input_tokens": in_toks,
                            "output_tokens": out_toks,
                            "thinking_tokens": 0,
                            "cached_tokens": 0,
                            "total_tokens": in_toks + out_toks,
                        },
                        "is_mock": False,
                        "notification_id": f"ANTHROPIC-SUCCEEDED-{request.task_id}",
                        "stdout_log_path": None,
                        "stderr_log_path": None,
                    }
            except urllib.error.HTTPError as he:
                err_body = ""
                try:
                    err_body = he.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                last_error = f"HTTP {he.code}: {he.reason} - {err_body[:200]}"
                logger.warning("Anthropic HTTPError %d on attempt %d: %s", he.code, attempt, last_error)
                if he.code in (401, 403):
                    break
                time.sleep(self.backoff_sec * attempt)
            except urllib.error.URLError as ue:
                last_error = f"URLError: {ue.reason}"
                logger.warning("Anthropic URLError on attempt %d: %s", attempt, last_error)
                time.sleep(self.backoff_sec * attempt)
            except Exception as e:
                last_error = f"Unexpected error: {str(e)}"
                logger.error("Anthropic unexpected error attempt %d: %s", attempt, last_error)
                time.sleep(self.backoff_sec)

        dt = max(0.001, time.perf_counter() - start_time)
        return {
            "status": "FAILED",
            "model": eff_model,
            "exit_code": 1,
            "timed_out": False,
            "duration_sec": round(dt, 4),
            "response_text": "",
            "parsed_json": {},
            "provider_usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "thinking_tokens": 0,
                "cached_tokens": 0,
                "total_tokens": 0,
            },
            "error_message": redact_sensitive_text(str(last_error or "Unknown error")),
            "is_mock": False,
            "notification_id": f"ANTHROPIC-FAILED-{request.task_id}",
            "stdout_log_path": None,
            "stderr_log_path": None,
        }
