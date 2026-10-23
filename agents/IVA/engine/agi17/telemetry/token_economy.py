"""AGI 1.7 Enforced Adaptive Token Economy & Usage Ledger.

Enforces hard token budgets across per-call, per-child, per-task, and
per-campaign scopes; distinguishes PROVIDER_REPORTED vs LOCAL_ESTIMATE vs
UNAVAILABLE usage; normalizes multi-turn cumulative conversation counters
into per-turn deltas; and enforces an isolated benchmark working directory
to eliminate the 22.7k workspace context injection leak discovered in AGI 1.6.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class TokenBudgetExceededError(RuntimeError):
    """Raised when a call, child agent, task, or campaign exceeds its hard token limit."""


@dataclass
class TokenUsageRecord:
    record_id: str
    timestamp: float
    campaign_id: Optional[str]
    task_id: str
    child_task_id: Optional[str]
    agent_id: str
    turn_index: int
    model: str
    effort_level: str
    accounting_mode: str  # "PROVIDER_REPORTED" | "LOCAL_ESTIMATE" | "UNAVAILABLE"
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    cached_tokens: int
    total_tokens: int
    cumulative_input_tokens: int
    cumulative_output_tokens: int
    isolated_cwd_enforced: bool
    cwd_used: str
    compressed_context_applied: bool = False
    early_stopped: bool = False


class AdaptiveTokenController:
    """Enforces real token budgets and writes an append-only token usage ledger."""

    TIER_LIMITS: Dict[str, Dict[str, int]] = {
        "SIMPLE": {
            "max_call_tokens": 4_000,
            "max_child_tokens": 6_000,
            "max_task_tokens": 12_000,
            "max_turns": 2,
        },
        "STANDARD": {
            "max_call_tokens": 8_000,
            "max_child_tokens": 16_000,
            "max_task_tokens": 40_000,
            "max_turns": 4,
        },
        "COMPLEX": {
            "max_call_tokens": 16_000,
            "max_child_tokens": 32_000,
            "max_task_tokens": 120_000,
            "max_turns": 8,
        },
        "BENCHMARK_ITEM": {
            "max_call_tokens": 8_000,
            "max_child_tokens": 8_000,
            "max_task_tokens": 12_000,
            "max_turns": 1,
        },
        "CAMPAIGN": {
            "max_call_tokens": 16_000,
            "max_child_tokens": 32_000,
            "max_task_tokens": 1_500_000,
            "max_turns": 250,
        },
    }

    MAX_DAILY_UTC_TOKENS: int = 1_000_000
    SOFT_BUDGET_THRESHOLD: int = 800_000

    def __init__(
        self,
        ledger_dir: str | Path = r"D:\AGI_Storage\AGI_1_7\token_ledger",
        isolated_benchmark_cwd: str | Path = r"D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\isolated_cwd",
        default_campaign_budget: int = 1_500_000,
    ) -> None:
        self.ledger_dir = Path(ledger_dir)
        try:
            self.ledger_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.ledger_dir = Path(__file__).resolve().parents[3] / "state_fallback" / "token_ledger"
            self.ledger_dir.mkdir(parents=True, exist_ok=True)

        self.isolated_benchmark_cwd = Path(isolated_benchmark_cwd)
        try:
            self.isolated_benchmark_cwd.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.isolated_benchmark_cwd = self.ledger_dir / "isolated_cwd"
            self.isolated_benchmark_cwd.mkdir(parents=True, exist_ok=True)

        self.ledger_file = self.ledger_dir / "token_usage_ledger.jsonl"
        self.default_campaign_budget = default_campaign_budget
        self._lock = threading.RLock()

        self._task_budgets: Dict[str, int] = {}
        self._child_budgets: Dict[str, int] = {}
        self._campaign_budgets: Dict[str, int] = {}

        self._task_consumed: Dict[str, int] = {}
        self._child_consumed: Dict[str, int] = {}
        self._campaign_consumed: Dict[str, int] = {}
        self._session_prev_cumulative: Dict[str, tuple[int, int]] = {}
        self._records: List[TokenUsageRecord] = []

    def classify_tier(self, prompt: str, is_benchmark_item: bool = False) -> str:
        if is_benchmark_item:
            return "BENCHMARK_ITEM"
        length = len(prompt)
        lower = prompt.lower()
        if length < 300 and not any(k in lower for k in ("architect", "campaign", "multi-stage", "orchestrate", "benchmark")):
            return "SIMPLE"
        if length > 1500 or any(k in lower for k in ("campaign", "multi-agent", "end-to-end", "comprehensive", "hierarchy")):
            return "COMPLEX"
        return "STANDARD"

    def allocate_budget(
        self,
        *,
        task_id: str,
        tier: str = "STANDARD",
        custom_task_budget: Optional[int] = None,
        child_task_id: Optional[str] = None,
        custom_child_budget: Optional[int] = None,
        campaign_id: Optional[str] = None,
        custom_campaign_budget: Optional[int] = None,
    ) -> Dict[str, int]:
        spec = self.TIER_LIMITS.get(tier, self.TIER_LIMITS["STANDARD"])
        with self._lock:
            if custom_task_budget is not None or task_id not in self._task_budgets:
                t_budget = custom_task_budget if custom_task_budget is not None else spec["max_task_tokens"]
                self._task_budgets[task_id] = t_budget
            else:
                t_budget = self._task_budgets[task_id]
            self._task_consumed.setdefault(task_id, 0)
            if child_task_id:
                c_budget = custom_child_budget if custom_child_budget is not None else spec["max_child_tokens"]
                self._child_budgets[child_task_id] = c_budget
                self._child_consumed.setdefault(child_task_id, 0)
            if campaign_id:
                camp_budget = custom_campaign_budget if custom_campaign_budget is not None else self.default_campaign_budget
                self._campaign_budgets[campaign_id] = camp_budget
                self._campaign_consumed.setdefault(campaign_id, 0)

            return {
                "max_call_tokens": spec["max_call_tokens"],
                "max_child_tokens": self._child_budgets.get(child_task_id or "", spec["max_child_tokens"]),
                "max_task_tokens": t_budget,
                "max_turns": spec["max_turns"],
                "phase_allocations": {
                    "planning_10pct": int(t_budget * 0.10),
                    "execution_60pct": int(t_budget * 0.60),
                    "verification_20pct": int(t_budget * 0.20),
                    "recovery_10pct": int(t_budget * 0.10),
                },
            }

    def get_daily_utc_usage(self, utc_date_str: Optional[str] = None) -> int:
        """Calculates total tokens consumed on the given UTC date across all providers."""
        target_date = utc_date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        total = 0
        with self._lock:
            # Check persisted ledger
            if self.ledger_file.exists():
                try:
                    with open(self.ledger_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            rec = json.loads(line)
                            ts = rec.get("timestamp")
                            if ts:
                                dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                                if dt == target_date:
                                    total += int(rec.get("total_tokens", 0))
                except Exception:
                    pass
        return total

    def is_daily_budget_exhausted(self) -> bool:
        """Returns True if the global 1,000,000 UTC token budget has been exhausted."""
        return self.get_daily_utc_usage() >= self.MAX_DAILY_UTC_TOKENS

    def check_pre_call_admission(
        self,
        *,
        task_id: str,
        estimated_tokens: int,
        child_task_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        tier: str = "STANDARD",
    ) -> Dict[str, Any]:
        """Verifies that a model call will not breach daily, call, child, task, or campaign budgets."""
        with self._lock:
            now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            daily_used = self.get_daily_utc_usage(now_utc)
            if daily_used + estimated_tokens > self.MAX_DAILY_UTC_TOKENS:
                raise TokenBudgetExceededError(
                    f"Global daily UTC token budget cap ({self.MAX_DAILY_UTC_TOKENS}) exceeded: "
                    f"used={daily_used} + est={estimated_tokens} > limit={self.MAX_DAILY_UTC_TOKENS} "
                    f"(UTC date: {now_utc}). Transition to BUDGET_PAUSED."
                )

            spec = self.TIER_LIMITS.get(tier, self.TIER_LIMITS["STANDARD"])
            call_limit = spec["max_call_tokens"]
            if estimated_tokens > call_limit:
                raise TokenBudgetExceededError(
                    f"Estimated call tokens ({estimated_tokens}) exceed tier {tier} call limit ({call_limit})"
                )

            task_used = self._task_consumed.get(task_id, 0)
            task_limit = self._task_budgets.get(task_id, spec["max_task_tokens"])
            if task_used + estimated_tokens > task_limit:
                raise TokenBudgetExceededError(
                    f"Task {task_id} token budget exceeded: used={task_used} + est={estimated_tokens} > limit={task_limit}"
                )

            if child_task_id:
                child_used = self._child_consumed.get(child_task_id, 0)
                child_limit = self._child_budgets.get(child_task_id, spec["max_child_tokens"])
                if child_used + estimated_tokens > child_limit:
                    raise TokenBudgetExceededError(
                        f"Child task {child_task_id} token budget exceeded: used={child_used} + est={estimated_tokens} > limit={child_limit}"
                    )

            if campaign_id:
                camp_used = self._campaign_consumed.get(campaign_id, 0)
                camp_limit = self._campaign_budgets.get(campaign_id, self.default_campaign_budget)
                if camp_used + estimated_tokens > camp_limit:
                    raise TokenBudgetExceededError(
                        f"Campaign {campaign_id} token budget exceeded: used={camp_used} + est={estimated_tokens} > limit={camp_limit}"
                    )

            remaining_task_ratio = 1.0 - ((task_used + estimated_tokens) / max(1, task_limit))
            return {
                "admitted": True,
                "task_used": task_used,
                "task_limit": task_limit,
                "remaining_task_tokens": task_limit - task_used,
                "daily_utc_tokens_used": daily_used,
                "daily_utc_cap": self.MAX_DAILY_UTC_TOKENS,
                "daily_budget_remaining": max(0, self.MAX_DAILY_UTC_TOKENS - daily_used),
                "soft_budget_alert": daily_used >= self.SOFT_BUDGET_THRESHOLD,
                "compress_context_recommended": remaining_task_ratio < 0.35,
                "downgrade_effort_recommended": remaining_task_ratio < 0.20,
            }

    def get_execution_cwd(self, *, is_benchmark_or_single_shot: bool, requested_cwd: Optional[str | Path] = None) -> str:
        """Returns the isolated empty directory for benchmark/single-shot calls to prevent 22.7k workspace context leakage."""
        if is_benchmark_or_single_shot:
            return str(self.isolated_benchmark_cwd)
        return str(requested_cwd or os.getcwd())

    def record_usage(
        self,
        *,
        task_id: str,
        agent_id: str,
        turn_index: int = 1,
        model: str = "gemini-3.8-flash-high",
        effort_level: str = "high",
        provider_usage: Optional[Dict[str, Any]] = None,
        prompt_text: str = "",
        response_text: str = "",
        child_task_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        conversation_key: Optional[str] = None,
        usage_is_cumulative: bool = False,
        cwd_used: Optional[str] = None,
        compressed_context_applied: bool = False,
        early_stopped: bool = False,
    ) -> TokenUsageRecord:
        """Records token consumption from provider telemetry or explicit local estimation."""
        with self._lock:
            now = time.time()
            actual_cwd = str(cwd_used or os.getcwd())
            isolated_flag = Path(actual_cwd).resolve() == self.isolated_benchmark_cwd.resolve()

            if provider_usage and ("input_tokens" in provider_usage or "prompt_tokens" in provider_usage):
                accounting_mode = "PROVIDER_REPORTED"
                raw_in = int(provider_usage.get("input_tokens", provider_usage.get("prompt_tokens", 0)))
                raw_out = int(provider_usage.get("output_tokens", provider_usage.get("completion_tokens", 0)))
                thinking = int(provider_usage.get("thinking_tokens", provider_usage.get("thoughts_token_count", 0)))
                cached = int(provider_usage.get("cached_tokens", provider_usage.get("cached_content_token_count", 0)))

                if usage_is_cumulative and conversation_key:
                    prev_in, prev_out = self._session_prev_cumulative.get(conversation_key, (0, 0))
                    delta_in = max(0, raw_in - prev_in)
                    delta_out = max(0, raw_out - prev_out)
                    self._session_prev_cumulative[conversation_key] = (raw_in, raw_out)
                    in_tok, out_tok = delta_in, delta_out
                    cum_in, cum_out = raw_in, raw_out
                else:
                    in_tok, out_tok = raw_in, raw_out
                    if conversation_key:
                        prev_in, prev_out = self._session_prev_cumulative.get(conversation_key, (0, 0))
                        cum_in, cum_out = prev_in + in_tok, prev_out + out_tok
                        self._session_prev_cumulative[conversation_key] = (cum_in, cum_out)
                    else:
                        cum_in, cum_out = in_tok, out_tok
            elif prompt_text or response_text:
                accounting_mode = "LOCAL_ESTIMATE"
                in_tok = max(1, len(prompt_text) // 4) if prompt_text else 0
                out_tok = max(1, len(response_text) // 4) if response_text else 0
                thinking = 0
                cached = 0
                cum_in, cum_out = in_tok, out_tok
            else:
                accounting_mode = "UNAVAILABLE"
                in_tok = 0
                out_tok = 0
                thinking = 0
                cached = 0
                cum_in, cum_out = 0, 0

            # Note: In Gemini / Antigravity CLI telemetry, thinking_tokens is a subset of output_tokens
            # when total_tokens == input_tokens + output_tokens.
            if provider_usage and "total_tokens" in provider_usage and not usage_is_cumulative:
                tot_tok = int(provider_usage["total_tokens"])
            else:
                tot_tok = in_tok + out_tok

            self._task_consumed[task_id] = self._task_consumed.get(task_id, 0) + tot_tok
            if child_task_id:
                self._child_consumed[child_task_id] = self._child_consumed.get(child_task_id, 0) + tot_tok
            if campaign_id:
                self._campaign_consumed[campaign_id] = self._campaign_consumed.get(campaign_id, 0) + tot_tok

            rec = TokenUsageRecord(
                record_id=f"TOK-{int(now * 1000)}-{uuid.uuid4().hex[:6]}",
                timestamp=now,
                campaign_id=campaign_id,
                task_id=task_id,
                child_task_id=child_task_id,
                agent_id=agent_id,
                turn_index=turn_index,
                model=model,
                effort_level=effort_level,
                accounting_mode=accounting_mode,
                input_tokens=in_tok,
                output_tokens=out_tok,
                thinking_tokens=thinking,
                cached_tokens=cached,
                total_tokens=tot_tok,
                cumulative_input_tokens=cum_in,
                cumulative_output_tokens=cum_out,
                isolated_cwd_enforced=isolated_flag,
                cwd_used=actual_cwd,
                compressed_context_applied=compressed_context_applied,
                early_stopped=early_stopped,
            )
            self._records.append(rec)
            with open(self.ledger_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
            return rec

    def get_summary(self, task_id: Optional[str] = None, campaign_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            filtered = [
                r
                for r in self._records
                if (task_id is None or r.task_id == task_id)
                and (campaign_id is None or r.campaign_id == campaign_id)
            ]
            by_mode: Dict[str, int] = {"PROVIDER_REPORTED": 0, "LOCAL_ESTIMATE": 0, "UNAVAILABLE": 0}
            total_in = 0
            total_out = 0
            total_think = 0
            total_cached = 0
            total_tok = 0
            for r in filtered:
                by_mode[r.accounting_mode] = by_mode.get(r.accounting_mode, 0) + r.total_tokens
                total_in += r.input_tokens
                total_out += r.output_tokens
                total_think += r.thinking_tokens
                total_cached += r.cached_tokens
                total_tok += r.total_tokens

            return {
                "record_count": len(filtered),
                "input_tokens": total_in,
                "output_tokens": total_out,
                "thinking_tokens": total_think,
                "cached_tokens": total_cached,
                "total_tokens": total_tok,
                "tokens_by_accounting_mode": by_mode,
                "isolated_cwd_calls": sum(1 for r in filtered if r.isolated_cwd_enforced),
                "compressed_calls": sum(1 for r in filtered if r.compressed_context_applied),
            }
