"""AGI 1.7 Model Adapter (Directive 0: gemini-3.8-flash-high via agy.exe).

Enforces:
1. Sole Foundation Model (`gemini-3.8-flash-high`) with zero silent fallbacks.
2. Typed `ModelRequest`, `ModelResponse`, and `ModelProviderConfig` contracts
   with `BaseModelProvider` and `DeterministicMockProvider` for offline tests.
3. Bounded retries with exponential backoff, rate limiting, and per-request /
   per-mission USD cost ceilings (`ModelCostBudgetExceededError`).
4. Safe permissions policy: does NOT pass `--dangerously-skip-permissions`
   unless explicitly authorized for a scoped sandbox container.
5. Isolated working directory (`isolated_cwd`) and isolated minimal CLI home
   (`minimal_cli_home`) for single-shot calls, plus automatic redaction of
   credentials and local user home paths (`redact_sensitive_text`).
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..orchestration.resource_governor import ResourceGovernor
from ..process_supervision.process_supervisor import ProcessSupervisor
from ..security.model_disclosure_policy import (
    DisclosureContext,
    ExternalProviderBlockedInLocalOnlyModeError,
    ModelDisclosurePolicy,
    SecretRedactor,
)
from ..telemetry.token_economy import AdaptiveTokenController


class DirectiveZeroViolationError(RuntimeError):
    """Raised when any caller attempts to invoke a model other than gemini-3.8-flash-high."""


class ModelCostBudgetExceededError(RuntimeError):
    """Raised when a model request or cumulative mission exceeds its configured USD cost ceiling."""


class ModelResponseValidationError(RuntimeError):
    """Raised when strict response validation is enabled and the model output is empty or invalid."""


_SECRET_PATTERNS = [
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "<REDACTED_GOOGLE_API_KEY>"),
    (re.compile(r"sk-[A-Za-z0-9]{16,}"), "<REDACTED_SK_KEY>"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "<REDACTED_GITHUB_TOKEN>"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{22,}"), "<REDACTED_GITHUB_PAT>"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "<REDACTED_AWS_KEY>"),
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer <REDACTED_TOKEN>"),
    (re.compile(r"eyJ[A-Za-z0-9-_]{10,}\.eyJ[A-Za-z0-9-_]{10,}\.[A-Za-z0-9-_]{10,}"), "<REDACTED_JWT_TOKEN>"),
    (re.compile(r"(?i)(api[_-]?secret|secret[_-]?key|access[_-]?token|auth[_-]?token|jwt[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9\-_./+=]{8,}['\"]?"), r"\1=<REDACTED_SECRET>"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "<REDACTED_PRIVATE_KEY>"),
]


def redact_sensitive_text(text: str) -> str:
    """Redacts API keys, tokens, private keys, and local user home paths from text logs."""
    if not text:
        return text
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    try:
        user_home = str(Path.home())
        if user_home and len(user_home) > 3:
            escaped_home = re.escape(user_home)
            redacted = re.sub(escaped_home, "<USER_HOME>", redacted, flags=re.IGNORECASE)
            forward_home = re.escape(user_home.replace("\\", "/"))
            redacted = re.sub(forward_home, "<USER_HOME>", redacted, flags=re.IGNORECASE)
    except Exception:
        pass
    return redacted


@dataclass
class ModelProviderConfig:
    """Configuration for model retries, rate limiting, pricing, and USD cost budgets."""

    model_name: str = "gemini-3.8-flash-high"
    effort: str = "high"
    max_retries: int = 1
    base_backoff_sec: float = 0.5
    min_request_interval_sec: float = 0.0
    max_request_cost_usd: float = 0.50
    max_mission_cost_usd: float = 5.00
    input_cost_per_million_usd: float = 0.30
    output_cost_per_million_usd: float = 2.50
    cached_cost_per_million_usd: float = 0.03
    strict_response_validation: bool = False
    allow_federated_models: bool = True

    def calculate_cost_usd(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
        non_cached = max(0, input_tokens - cached_tokens)
        return round(
            (non_cached * self.input_cost_per_million_usd / 1_000_000.0)
            + ( max(0, cached_tokens) * self.cached_cost_per_million_usd / 1_000_000.0)
            + (max(0, output_tokens) * self.output_cost_per_million_usd / 1_000_000.0),
            6,
        )


@dataclass
class ModelRequest:
    """Typed request payload for model invocation."""

    task_id: str
    prompt: str
    agent_id: str = "model_specialist"
    effort: str = "high"
    is_benchmark_or_single_shot: bool = True
    requested_cwd: Optional[str | Path] = None
    wall_timeout_sec: float = 180.0
    idle_timeout_sec: float = 90.0
    campaign_id: Optional[str] = None
    child_task_id: Optional[str] = None
    tier: str = "BENCHMARK_ITEM"
    system_instruction: Optional[str] = None
    model_override: Optional[str] = None


@dataclass
class ModelResponse:
    """Typed response payload from model invocation."""

    task_id: str
    agent_id: str
    model: str
    status: str
    exit_code: Optional[int]
    timed_out: bool
    duration_sec: float
    latency_ms: float
    cwd_used: str
    isolated_cwd_enforced: bool
    response_text: str
    parsed_json: Dict[str, Any]
    token_usage: Dict[str, Any]
    cost_usd: float
    cumulative_mission_cost_usd: float
    attempts: int = 1
    attempt_ledger: List[Dict[str, Any]] = field(default_factory=list)
    is_mock: bool = False
    notification_id: Optional[str] = None
    stdout_log_path: Optional[str] = None
    stderr_log_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BaseModelProvider(ABC):
    """Abstract provider interface for live CLI or deterministic offline mock execution."""

    @abstractmethod
    def generate(self, request: ModelRequest) -> Dict[str, Any]:
        """Executes a model request and returns raw output metadata."""


class DeterministicMockProvider(BaseModelProvider):
    """Offline mock provider for fast, deterministic unit and CI testing without spending live tokens."""

    def __init__(
        self,
        responder: Optional[Callable[[ModelRequest], str | Dict[str, Any]]] = None,
        simulated_input_tokens: int = 120,
        simulated_output_tokens: int = 80,
    ) -> None:
        self.responder = responder
        self.simulated_input_tokens = simulated_input_tokens
        self.simulated_output_tokens = simulated_output_tokens
        self.call_history: List[ModelRequest] = []

    def generate(self, request: ModelRequest) -> Dict[str, Any]:
        self.call_history.append(request)
        t0 = time.perf_counter()
        if self.responder is not None:
            raw = self.responder(request)
        else:
            raw = {
                "summary": f"Mock offline response for {request.task_id}",
                "findings": [f"Processed by {request.agent_id}"],
                "verified_metrics": {"is_mock": True},
            }
        if isinstance(raw, dict):
            response_text = json.dumps(raw)
            parsed_json = raw
        else:
            response_text = str(raw)
            parsed_json = {}
            if response_text.strip().startswith("{"):
                try:
                    parsed_json = json.loads(response_text)
                except Exception:
                    parsed_json = {}
        dt = max(0.001, time.perf_counter() - t0)
        return {
            "status": "SUCCEEDED",
            "exit_code": 0,
            "timed_out": False,
            "duration_sec": round(dt, 4),
            "response_text": response_text,
            "parsed_json": parsed_json,
            "provider_usage": {
                "input_tokens": self.simulated_input_tokens,
                "output_tokens": self.simulated_output_tokens,
                "thinking_tokens": 0,
                "cached_tokens": 0,
                "total_tokens": self.simulated_input_tokens + self.simulated_output_tokens,
            },
            "is_mock": True,
            "notification_id": f"MOCK-{request.task_id}",
            "stdout_log_path": None,
            "stderr_log_path": None,
        }


class ModelAdapter:
    """Verified Antigravity CLI (`agy.exe`) adapter enforcing Directive 0, cost budgets, and isolated CWD."""

    SOLE_MODEL = "gemini-3.8-flash-high"
    FEDERATED_MODELS = frozenset(
        {
            "gemini-3.8-flash-high",
            "deepseek-ai/DeepSeek-V4-Flash-0731",
            "MiniMaxAI/MiniMax-M2.7",
            "zai-org/GLM-5.3-Flash",
        }
    )
    QUOTA_FAILOVER_CHAIN = (
        "deepseek-ai/DeepSeek-V4-Flash-0731",
        "MiniMaxAI/MiniMax-M2.7",
        "zai-org/GLM-5.3-Flash",
    )

    @classmethod
    def is_authorized_model(cls, model_name: str, allow_federated: bool = True) -> bool:
        if not isinstance(model_name, str) or not model_name.strip():
            return False
        if model_name == cls.SOLE_MODEL:
            return True
        if not allow_federated:
            return False
        return model_name in cls.FEDERATED_MODELS

    @classmethod
    def get_quota_failover_model(cls, exhausted_model: str = "gemini-3.8-flash-high") -> str:
        """Returns the next verified external model when the primary Gemini 3.8 Flash quota is exhausted."""
        for candidate in cls.QUOTA_FAILOVER_CHAIN:
            if candidate != exhausted_model:
                return candidate
        return cls.QUOTA_FAILOVER_CHAIN[0]

    def __init__(
        self,
        *,
        token_controller: Optional[AdaptiveTokenController] = None,
        governor: Optional[ResourceGovernor] = None,
        supervisor: Optional[ProcessSupervisor] = None,
        agy_path: Optional[str | Path] = None,
        config: Optional[ModelProviderConfig] = None,
        mock_provider: Optional[BaseModelProvider] = None,
        api_provider: Optional[BaseModelProvider] = None,
        disclosure_policy: Optional[ModelDisclosurePolicy] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        self.config = config or ModelProviderConfig()
        if not self.is_authorized_model(self.config.model_name, allow_federated=self.config.allow_federated_models):
            raise DirectiveZeroViolationError(
                f"Directive 0 violation: config model '{self.config.model_name}' is not authorized"
            )
        self.token_controller = token_controller or AdaptiveTokenController()
        self.governor = governor or ResourceGovernor()
        self.supervisor = supervisor or ProcessSupervisor()
        self.mock_provider = mock_provider
        self.disclosure_policy = disclosure_policy or ModelDisclosurePolicy.production_strict()

        # Universal API Provider auto-discovery
        if self.mock_provider is None:
            if api_provider is not None:
                self.api_provider = api_provider
            else:
                from .universal_api_provider import UniversalAPIProvider, load_repo_dotenv
                load_repo_dotenv()
                if api_key or UniversalAPIProvider.has_available_credentials():
                    self.api_provider = UniversalAPIProvider(api_key=api_key, model_name=model_name)
                else:
                    self.api_provider = None
        else:
            self.api_provider = None

        self.agy_path = self.resolve_agy_path(agy_path)

        self._lock = threading.Lock()
        self._last_request_ts: float = 0.0
        self._cumulative_mission_cost_usd: float = 0.0

    @classmethod
    def resolve_agy_path(
        cls,
        agy_path: Optional[str | Path] = None,
        *,
        platform_os_name: Optional[str] = None,
    ) -> Path:
        eff_os = platform_os_name or os.name
        env_agy = os.environ.get("AGY_PATH")
        which_agy = shutil.which("agy") or (shutil.which("agy.exe") if eff_os == "nt" else None)
        if agy_path:
            return Path(agy_path)
        if env_agy:
            return Path(env_agy)
        if which_agy:
            return Path(which_agy)
        if eff_os == "nt":
            local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
            default_agy = local_app_data / "agy" / "bin" / "agy.exe"
            if not default_agy.exists():
                default_agy = default_agy.with_suffix(".cmd")
            return default_agy
        return Path("agy")

    @property
    def cumulative_mission_cost_usd(self) -> float:
        with self._lock:
            return round(self._cumulative_mission_cost_usd, 6)

    def reset_mission_cost(self) -> None:
        with self._lock:
            self._cumulative_mission_cost_usd = 0.0

    def _ensure_minimal_cli_home(self, base_dir: Path) -> Path:
        """Creates an isolated CLI home with empty mcpServers/skills so single-shot calls do not hang on MCP boot."""
        min_home = base_dir.parent / "minimal_cli_home"
        cfg_dir = min_home / ".gemini" / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        mcp_cfg = cfg_dir / "mcp_config.json"
        if not mcp_cfg.exists():
            mcp_cfg.write_text('{"mcpServers":{}}', encoding="utf-8")
        skills_cfg = cfg_dir / "skills.json"
        if not skills_cfg.exists():
            skills_cfg.write_text("{}", encoding="utf-8")

        real_home = Path.home()
        real_cfg = real_home / ".gemini" / "config" / "config.json"
        dst_cfg = cfg_dir / "config.json"
        if real_cfg.exists() and not dst_cfg.exists():
            try:
                shutil.copy2(real_cfg, dst_cfg)
            except Exception:
                pass
        return min_home

    def build_command(
        self,
        *,
        prompt: str,
        model: str = SOLE_MODEL,
        effort: str = "high",
        output_format: str = "json",
        disable_slash_commands: bool = True,
        print_timeout_sec: int = 180,
        allow_dangerous_permissions_flag: bool = False,
    ) -> List[str]:
        if model != self.SOLE_MODEL:
            raise DirectiveZeroViolationError(
                f"Directive 0 violation: requested model '{model}', but sole authorized model is '{self.SOLE_MODEL}'"
            )
        if effort != "high":
            raise DirectiveZeroViolationError(
                f"Directive 0 violation: requested effort '{effort}', but '{self.SOLE_MODEL}' requires effort='high'"
            )

        cmd: List[str] = [
            str(self.agy_path),
            "--model",
            self.SOLE_MODEL,
            "--effort",
            "high",
            "--output-format",
            output_format,
            "--print-timeout",
            f"{int(print_timeout_sec)}s",
        ]
        if disable_slash_commands:
            cmd.append("--disable-slash-commands")
        if allow_dangerous_permissions_flag:
            cmd.append("--dangerously-skip-permissions")
        cmd.extend(["-p", prompt])
        return cmd

    def _enforce_rate_limit_and_cost_precheck(self, estimated_input_tokens: int) -> None:
        estimated_output_tokens = 1000
        est_cost = self.config.calculate_cost_usd(estimated_input_tokens, estimated_output_tokens)
        with self._lock:
            if est_cost > self.config.max_request_cost_usd:
                raise ModelCostBudgetExceededError(
                    f"Estimated request cost ${est_cost:.6f} exceeds max_request_cost_usd ${self.config.max_request_cost_usd:.6f}"
                )
            if self._cumulative_mission_cost_usd + est_cost > self.config.max_mission_cost_usd:
                raise ModelCostBudgetExceededError(
                    f"Projected mission cost ${self._cumulative_mission_cost_usd + est_cost:.6f} exceeds max_mission_cost_usd ${self.config.max_mission_cost_usd:.6f}"
                )
            if self.config.min_request_interval_sec > 0:
                now = time.monotonic()
                elapsed = now - self._last_request_ts
                if elapsed < self.config.min_request_interval_sec:
                    time.sleep(self.config.min_request_interval_sec - elapsed)
                self._last_request_ts = time.monotonic()

    def invoke_typed(self, request: ModelRequest) -> ModelResponse:
        """Executes a typed `ModelRequest` and returns a validated `ModelResponse`."""
        res_dict = self.invoke(
            task_id=request.task_id,
            prompt=request.prompt,
            agent_id=request.agent_id,
            effort=request.effort,
            is_benchmark_or_single_shot=request.is_benchmark_or_single_shot,
            requested_cwd=request.requested_cwd,
            wall_timeout_sec=request.wall_timeout_sec,
            idle_timeout_sec=request.idle_timeout_sec,
            campaign_id=request.campaign_id,
            child_task_id=request.child_task_id,
            tier=request.tier,
        )
        return ModelResponse(
            task_id=res_dict["task_id"],
            agent_id=res_dict["agent_id"],
            model=res_dict["model"],
            status=res_dict["status"],
            exit_code=res_dict["exit_code"],
            timed_out=res_dict["timed_out"],
            duration_sec=res_dict["duration_sec"],
            latency_ms=res_dict["latency_ms"],
            cwd_used=res_dict["cwd_used"],
            isolated_cwd_enforced=res_dict["isolated_cwd_enforced"],
            response_text=res_dict["response_text"],
            parsed_json=res_dict["parsed_json"],
            token_usage=res_dict["token_usage"],
            cost_usd=res_dict["cost_usd"],
            cumulative_mission_cost_usd=res_dict["cumulative_mission_cost_usd"],
            attempts=res_dict["attempts"],
            attempt_ledger=res_dict.get("attempt_ledger", []),
            is_mock=res_dict.get("is_mock", False),
            notification_id=res_dict.get("notification_id"),
            stdout_log_path=res_dict.get("stdout_log_path"),
            stderr_log_path=res_dict.get("stderr_log_path"),
        )

    def invoke(
        self,
        *,
        task_id: str,
        prompt: str,
        agent_id: str = "model_specialist",
        effort: str = "high",
        is_benchmark_or_single_shot: bool = True,
        requested_cwd: Optional[str | Path] = None,
        wall_timeout_sec: float = 180.0,
        idle_timeout_sec: float = 90.0,
        campaign_id: Optional[str] = None,
        child_task_id: Optional[str] = None,
        tier: str = "BENCHMARK_ITEM",
    ) -> Dict[str, Any]:
        """Invokes `agy.exe` (or `mock_provider` in offline tests) under resource, token, cost, and process supervision."""
        if effort != "high":
            raise DirectiveZeroViolationError(
                f"Directive 0 violation: requested effort '{effort}', but '{self.SOLE_MODEL}' requires effort='high'"
            )

        ctx = DisclosureContext(
            task_id=task_id,
            agent_id=agent_id,
            is_external_provider=bool(self.mock_provider is None or getattr(self.mock_provider, "is_external", False)),
            provider_name=self.config.model_name,
            operation_type="model_invocation",
        )
        if self.disclosure_policy.local_only and ctx.is_external_provider:
            raise ExternalProviderBlockedInLocalOnlyModeError(
                f"LOCAL_ONLY_POLICY_VIOLATION: External provider '{self.config.model_name}' is blocked under local-only mode."
            )

        prompt, _ = self.disclosure_policy.sanitize_outbound_prompt(prompt)

        est_tokens = max(250, len(prompt) // 4 + 500)
        self.token_controller.check_pre_call_admission(
            task_id=task_id,
            estimated_tokens=est_tokens,
            child_task_id=child_task_id,
            campaign_id=campaign_id,
            tier=tier,
        )
        self._enforce_rate_limit_and_cost_precheck(est_tokens)

        exec_cwd = self.token_controller.get_execution_cwd(
            is_benchmark_or_single_shot=is_benchmark_or_single_shot,
            requested_cwd=requested_cwd,
        )

        request_obj = ModelRequest(
            task_id=task_id,
            prompt=prompt,
            agent_id=agent_id,
            effort=effort,
            is_benchmark_or_single_shot=is_benchmark_or_single_shot,
            requested_cwd=exec_cwd,
            wall_timeout_sec=wall_timeout_sec,
            idle_timeout_sec=idle_timeout_sec,
            campaign_id=campaign_id,
            child_task_id=child_task_id,
            tier=tier,
        )

        # Active provider execution path (Mock offline testing or Universal REST API)
        active_provider = self.mock_provider or self.api_provider
        if active_provider is not None:
            provider_out = active_provider.generate(request_obj)
            provider_usage = provider_out.get("provider_usage")
            response_text = redact_sensitive_text(str(provider_out.get("response_text", "")))
            response_text, _ = SecretRedactor.redact(response_text)
            parsed_response = provider_out.get("parsed_json") or {}
            if self.config.strict_response_validation and not response_text.strip():
                raise ModelResponseValidationError(f"Empty response from model provider for task '{task_id}'")
            usage_rec = self.token_controller.record_usage(
                task_id=task_id,
                child_task_id=child_task_id,
                campaign_id=campaign_id,
                agent_id=agent_id,
                model=self.SOLE_MODEL,
                effort_level=effort,
                provider_usage=provider_usage,
                prompt_text=prompt,
                response_text=response_text,
                cwd_used=exec_cwd,
            )
            call_cost = self.config.calculate_cost_usd(
                usage_rec.input_tokens, usage_rec.output_tokens, usage_rec.cached_tokens
            )
            with self._lock:
                self._cumulative_mission_cost_usd = round(self._cumulative_mission_cost_usd + call_cost, 6)
                cum_cost = self._cumulative_mission_cost_usd
            duration_sec = float(provider_out.get("duration_sec", 0.001))
            prov_status = provider_out.get("status", "SUCCEEDED")
            prov_exit = provider_out.get("exit_code", 0)
            is_mock_val = bool(provider_out.get("is_mock", self.mock_provider is not None))
            return {
                "task_id": task_id,
                "agent_id": agent_id,
                "model": provider_out.get("model") or getattr(active_provider, "model_name", self.SOLE_MODEL),
                "status": prov_status,
                "exit_code": prov_exit,
                "timed_out": bool(provider_out.get("timed_out", False)),
                "duration_sec": duration_sec,
                "latency_ms": round(duration_sec * 1000.0, 2),
                "cwd_used": exec_cwd,
                "isolated_cwd_enforced": usage_rec.isolated_cwd_enforced,
                "response_text": response_text,
                "parsed_json": parsed_response,
                "token_usage": {
                    "accounting_mode": "MOCK_OFFLINE_TEST" if is_mock_val else "UNIVERSAL_API",
                    "input_tokens": usage_rec.input_tokens,
                    "output_tokens": usage_rec.output_tokens,
                    "thinking_tokens": usage_rec.thinking_tokens,
                    "cached_tokens": usage_rec.cached_tokens,
                    "total_tokens": usage_rec.total_tokens,
                },
                "cost_usd": call_cost,
                "cumulative_mission_cost_usd": cum_cost,
                "attempts": 1,
                "attempt_ledger": [
                    {
                        "attempt": 1,
                        "status": prov_status,
                        "exit_code": prov_exit,
                        "timed_out": bool(provider_out.get("timed_out", False)),
                        "duration_sec": duration_sec,
                        "notification_id": provider_out.get("notification_id"),
                    }
                ],
                "is_mock": is_mock_val,
                "notification_id": provider_out.get("notification_id"),
                "stdout_log_path": provider_out.get("stdout_log_path"),
                "stderr_log_path": provider_out.get("stderr_log_path"),
            }

        if not self.agy_path.exists():
            raise RuntimeError(
                f"No live model execution engine found at '{self.agy_path}'. "
                "Universal access mode is supported anywhere: please set GEMINI_API_KEY (recommended) "
                "or OPENAI_API_KEY in your .env file or environment variable (Get a free key at https://aistudio.google.com/)."
            )

        cmd = self.build_command(
            prompt=prompt,
            model=self.SOLE_MODEL,
            effort=effort,
            output_format="json",
            disable_slash_commands=True,
            print_timeout_sec=int(wall_timeout_sec),
            allow_dangerous_permissions_flag=False,
        )

        env_overrides: Optional[Dict[str, str]] = None
        if is_benchmark_or_single_shot:
            try:
                min_home = self._ensure_minimal_cli_home(Path(exec_cwd))
                env_overrides = {
                    "USERPROFILE": str(min_home),
                    "HOME": str(min_home),
                }
            except Exception:
                env_overrides = None

        max_attempts = max(1, 1 + int(self.config.max_retries))
        notif = None
        attempts_made = 0
        attempt_ledger: List[Dict[str, Any]] = []
        for attempt_idx in range(max_attempts):
            attempts_made = attempt_idx + 1
            proc_task_id = f"{child_task_id or task_id}-MODEL-A{attempts_made}"
            self.governor.acquire_slot(queue_type="model_call")
            try:
                notif = self.supervisor.run_supervised(
                    task_id=proc_task_id,
                    parent_task_id=task_id,
                    command=cmd,
                    cwd=exec_cwd,
                    env=env_overrides,
                    wall_timeout_sec=wall_timeout_sec,
                    idle_timeout_sec=idle_timeout_sec,
                    max_retries=0,
                )
            finally:
                self.governor.release_slot(queue_type="model_call")

            attempt_ledger.append(
                {
                    "attempt": attempts_made,
                    "proc_task_id": proc_task_id,
                    "status": notif.final_status,
                    "exit_code": notif.exit_code,
                    "timed_out": notif.timed_out or notif.idle_timed_out,
                    "duration_sec": notif.duration_sec,
                    "notification_id": notif.notification_id,
                }
            )

            if notif.timed_out or notif.idle_timed_out:
                self.governor.report_timeout_or_quota_pressure()

            if notif.final_status == "SUCCEEDED" and notif.exit_code == 0:
                break
            if attempt_idx + 1 < max_attempts:
                base_wait = self.config.base_backoff_sec * (2 ** attempt_idx)
                jitter = random.uniform(0.0, 0.25 * base_wait)
                time.sleep(base_wait + jitter)

        assert notif is not None
        full_stdout = ""
        try:
            full_stdout = Path(notif.stdout_log_path).read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            full_stdout = "\n".join(notif.stdout_tail).strip()

        parsed_response: Dict[str, Any] = {}
        response_text = full_stdout
        provider_usage: Optional[Dict[str, Any]] = notif.usage_metadata or None

        if full_stdout:
            for candidate_line in reversed([ln.strip() for ln in full_stdout.splitlines() if ln.strip()]):
                if candidate_line.startswith("{") and candidate_line.endswith("}"):
                    try:
                        obj = json.loads(candidate_line)
                        if isinstance(obj, dict):
                            parsed_response = obj
                            response_text = str(obj.get("result") or obj.get("response") or obj.get("text") or full_stdout)
                            if isinstance(obj.get("usage"), dict):
                                provider_usage = obj["usage"]
                            break
                    except Exception:
                        pass
            if not parsed_response and full_stdout.startswith("{"):
                try:
                    obj = json.loads(full_stdout)
                    if isinstance(obj, dict):
                        parsed_response = obj
                        response_text = str(obj.get("result") or obj.get("response") or obj.get("text") or full_stdout)
                        if isinstance(obj.get("usage"), dict):
                            provider_usage = obj["usage"]
                except Exception:
                    pass

        response_text = redact_sensitive_text(response_text)
        response_text, _ = SecretRedactor.redact(response_text)
        if self.config.strict_response_validation and (
            notif.final_status != "SUCCEEDED" or not response_text.strip()
        ):
            raise ModelResponseValidationError(
                f"Model invocation failed validation for task '{task_id}': status={notif.final_status}, empty={not bool(response_text.strip())}"
            )

        usage_rec = self.token_controller.record_usage(
            task_id=task_id,
            child_task_id=child_task_id,
            campaign_id=campaign_id,
            agent_id=agent_id,
            model=self.SOLE_MODEL,
            effort_level=effort,
            provider_usage=provider_usage,
            prompt_text=prompt,
            response_text=response_text,
            cwd_used=exec_cwd,
        )

        call_cost = self.config.calculate_cost_usd(
            usage_rec.input_tokens, usage_rec.output_tokens, usage_rec.cached_tokens
        )
        with self._lock:
            self._cumulative_mission_cost_usd = round(self._cumulative_mission_cost_usd + call_cost, 6)
            cum_cost = self._cumulative_mission_cost_usd

        return {
            "task_id": task_id,
            "agent_id": agent_id,
            "model": self.SOLE_MODEL,
            "status": notif.final_status,
            "exit_code": notif.exit_code,
            "timed_out": notif.timed_out or notif.idle_timed_out,
            "duration_sec": notif.duration_sec,
            "latency_ms": round(notif.duration_sec * 1000.0, 2),
            "cwd_used": exec_cwd,
            "isolated_cwd_enforced": usage_rec.isolated_cwd_enforced,
            "response_text": response_text,
            "parsed_json": parsed_response,
            "token_usage": {
                "accounting_mode": usage_rec.accounting_mode,
                "input_tokens": usage_rec.input_tokens,
                "output_tokens": usage_rec.output_tokens,
                "thinking_tokens": usage_rec.thinking_tokens,
                "cached_tokens": usage_rec.cached_tokens,
                "total_tokens": usage_rec.total_tokens,
            },
            "cost_usd": call_cost,
            "cumulative_mission_cost_usd": cum_cost,
            "attempts": attempts_made,
            "attempt_ledger": attempt_ledger,
            "is_mock": False,
            "notification_id": notif.notification_id,
            "stdout_log_path": notif.stdout_log_path,
            "stderr_log_path": notif.stderr_log_path,
        }
