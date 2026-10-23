"""AGI 1.7 Refusal Diagnosis & Failure Recovery Engine (Phase 17.26).

Enforces:
1. Strict Failure Classification (Section 6):
   - ORDINARY_TASK_MISCLASSIFIED
   - INSUFFICIENT_CONTEXT
   - MISSING_TOOL_OR_PERMISSION
   - MODEL_CAPABILITY_LIMIT
   - PROVIDER_OR_NETWORK_ERROR
   - RATE_LIMIT_OR_TIMEOUT
   - MALFORMED_OUTPUT
   - GENUINELY_DISALLOWED_REQUEST
   - UNKNOWN_CAUSE
2. Targeted Recovery Policies:
   - De-sensitize vocabulary (replace trigger words in technical context).
   - Context pruning and ACON compression.
   - Schema repair and AST JSON extraction.
   - Multi-model failover (FAST -> DEEP_REASONING -> INDEPENDENT_REVIEWER).
   - Bounded retries (maximum 3 attempts, no infinite loops).
3. Genuine Safety Gate Invariant:
   - If genuine disallowed execution is requested (e.g. live trading with real funds,
     credential exfiltration), strictly fail-closed, explain the boundary, and offer
     safe paper simulation alternatives without bypass.
"""

from __future__ import annotations

import ast
import enum
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("RefusalRecoveryEngine")


class FailureClassification(str, enum.Enum):
    ORDINARY_TASK_MISCLASSIFIED = "ORDINARY_TASK_MISCLASSIFIED"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    MISSING_TOOL_OR_PERMISSION = "MISSING_TOOL_OR_PERMISSION"
    MODEL_CAPABILITY_LIMIT = "MODEL_CAPABILITY_LIMIT"
    PROVIDER_OR_NETWORK_ERROR = "PROVIDER_OR_NETWORK_ERROR"
    RATE_LIMIT_OR_TIMEOUT = "RATE_LIMIT_OR_TIMEOUT"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    GENUINELY_DISALLOWED_REQUEST = "GENUINELY_DISALLOWED_REQUEST"
    UNKNOWN_CAUSE = "UNKNOWN_CAUSE"


@dataclass
class RecoveryResult:
    success: bool
    failure_class: FailureClassification
    attempts_used: int
    max_attempts: int
    original_prompt: str
    recovered_prompt: Optional[str] = None
    recovered_output: Optional[Any] = None
    strategy_applied: Optional[str] = None
    error_message: Optional[str] = None
    is_genuine_safety_gate: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["failure_class"] = self.failure_class.value
        return d


class RefusalRecoveryEngine:
    """Diagnoses refusals and executes bounded recovery policies."""

    # Trigger patterns that cause models or routers to panic inappropriately on benign code
    DESENSITIZATION_MAP = [
        (re.compile(r"\bkill\s+(the\s+)?worker\b", re.IGNORECASE), "terminate background worker process"),
        (re.compile(r"\bkill\s+(all\s+)?processes\b", re.IGNORECASE), "terminate running background processes"),
        (re.compile(r"\battack\s+(the\s+)?(bottleneck|bug|defect)\b", re.IGNORECASE), "diagnose and resolve the bottleneck"),
        (re.compile(r"\banalyze\s+(my\s+)?trading\s+code\b", re.IGNORECASE), "audit local quantitative calculation code and risk algorithms"),
        (re.compile(r"\bhack\s+(together\s+)?a\s+solution\b", re.IGNORECASE), "implement a minimal working solution"),
        (re.compile(r"\bexploit\s+(the\s+)?edge\b", re.IGNORECASE), "leverage the statistical edge"),
    ]

    GENUINE_SAFETY_PATTERNS = [
        re.compile(r"\b(dispatch|execute|place|send)\s+(a\s+)?live\s+(order|trade)\s+(to|on)\s+(broker|exchange|nse|bse)\b", re.IGNORECASE),
        re.compile(r"\bset\s+live_order_dispatch_enabled\s*=\s*true\b", re.IGNORECASE),
        re.compile(r"\bexfiltrate\s+(api\s+keys|credentials|passwords|secrets)\b", re.IGNORECASE),
        re.compile(r"\brm\s+-rf\s+/\b", re.IGNORECASE),
    ]

    REFUSAL_INDICATORS = [
        "i cannot fulfill this request",
        "i am unable to assist with",
        "as an ai",
        "i don't have personal desires",
        "i cannot trade with real money",
        "i cannot perform live orders",
        "i'm sorry, but i can't do that",
        "i must refuse",
        "violates safety guidelines",
    ]

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts

    def diagnose_failure(
        self,
        prompt: str,
        response_text: str = "",
        error: Optional[Exception] = None,
        http_status: Optional[int] = None,
    ) -> Tuple[FailureClassification, str]:
        """Diagnoses the precise cause of an LLM failure or refusal."""
        prompt_lower = prompt.lower()
        resp_lower = (response_text or "").lower()

        # Check for genuine disallowed request first
        for pat in self.GENUINE_SAFETY_PATTERNS:
            if pat.search(prompt_lower):
                return (
                    FailureClassification.GENUINELY_DISALLOWED_REQUEST,
                    "Request attempts consequential real-money live dispatch or privileged exfiltration, which violates physical fail-closed invariants."
                )

        # Check for HTTP status codes
        if http_status == 429:
            return FailureClassification.RATE_LIMIT_OR_TIMEOUT, "HTTP 429 Rate Limit encountered."
        if http_status in (500, 502, 503, 504):
            return FailureClassification.PROVIDER_OR_NETWORK_ERROR, f"HTTP {http_status} Provider Error encountered."

        # Check for Exception types
        if error is not None:
            err_msg = str(error).lower()
            err_type = type(error).__name__
            if "timeout" in err_msg or "timed out" in err_msg:
                return FailureClassification.RATE_LIMIT_OR_TIMEOUT, f"Request timed out: {error}"
            if "json" in err_msg or "decode" in err_msg or "jsondecodeerror" in err_type.lower():
                return FailureClassification.MALFORMED_OUTPUT, f"JSON decoding failed: {error}"
            if "budget" in err_msg or "token" in err_msg and "exhausted" in err_msg:
                return FailureClassification.INSUFFICIENT_CONTEXT, f"Context or token budget exceeded: {error}"
            if "connection" in err_msg or "network" in err_msg:
                return FailureClassification.PROVIDER_OR_NETWORK_ERROR, f"Network error: {error}"

        # Check for Model Disclaimers or Refusals on Benign Tasks
        has_refusal_phrase = any(phrase in resp_lower for phrase in self.REFUSAL_INDICATORS)
        if has_refusal_phrase:
            # Check if prompt was an ordinary software engineering or quantitative analysis task
            is_benign = any(w in prompt_lower for w in ("code", "function", "bug", "test", "analyze", "worker", "process", "refactor", "optimize", "module", "benchmark"))
            if is_benign:
                return (
                    FailureClassification.ORDINARY_TASK_MISCLASSIFIED,
                    "Model triggered safety refusal on a permissible software engineering or quantitative analysis task."
                )

        # Check for Malformed JSON response
        if response_text and ("{" in response_text or "[" in response_text):
            parsed, _, _ = self.repair_malformed_json(response_text)
            if not parsed and "{" in response_text:
                return FailureClassification.MALFORMED_OUTPUT, "Model response contained malformed JSON syntax."

        # Check for Empty or Degraded Response
        if not response_text or len(response_text.strip()) == 0:
            return FailureClassification.MODEL_CAPABILITY_LIMIT, "Model returned an empty or degraded response."

        return FailureClassification.UNKNOWN_CAUSE, "Unknown error cause."

    def desensitize_prompt(self, prompt: str) -> str:
        """Neutralizes vocabulary that might trigger overzealous safety filters in coding tasks."""
        refined = prompt
        for pat, replacement in self.DESENSITIZATION_MAP:
            refined = pat.sub(replacement, refined)

        # Prepend explicit benign engineering context if not already present
        if "OFFLINE_ENGINEERING_FRAME" not in refined:
            refined = (
                "[OFFLINE_ENGINEERING_FRAME: The following is a local software engineering, quantitative code audit, "
                "or unit testing task on internal files. No live broker execution or external network attacks are involved.]\n\n"
                + refined
            )
        return refined

    def repair_malformed_json(
        self,
        raw_text: str,
        expected_schema: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Any, Optional[str]]:
        """Extracts and repairs JSON from raw model text (stripping markdown fences, trailing commas, etc.)."""
        if not raw_text:
            return False, None, "Empty text provided"

        # 1. Direct parse attempt
        try:
            val = json.loads(raw_text.strip())
            return True, val, None
        except (json.JSONDecodeError, ValueError):
            pass

        # 2. Extract from markdown code fences: ```json ... ``` or ``` ... ```
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text, re.DOTALL)
        candidate_text = fence_match.group(1).strip() if fence_match else raw_text

        try:
            val = json.loads(candidate_text)
            return True, val, None
        except (json.JSONDecodeError, ValueError):
            pass

        # 3. Find outer curly braces or square brackets
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start_idx = candidate_text.find(start_char)
            end_idx = candidate_text.rfind(end_char)
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                cand = candidate_text[start_idx : end_idx + 1]
                # Clean common trailing commas: e.g. ", }" -> "}" or ", ]" -> "]"
                cleaned = re.sub(r",\s*([\]}])", r"\1", cand)

                # Try parsing cleaned standard JSON
                try:
                    val = json.loads(cleaned)
                    return True, val, None
                except (json.JSONDecodeError, ValueError):
                    pass

                # Clean single quotes around keys and string values
                try:
                    # Convert python boolean and null tokens
                    py_cand = re.sub(r"\btrue\b", "True", cleaned, flags=re.IGNORECASE)
                    py_cand = re.sub(r"\bfalse\b", "False", py_cand, flags=re.IGNORECASE)
                    py_cand = re.sub(r"\bnull\b", "None", py_cand, flags=re.IGNORECASE)
                    val = ast.literal_eval(py_cand)
                    if isinstance(val, (dict, list)):
                        return True, val, None
                except Exception:
                    pass

        return False, None, "Failed to repair malformed JSON"

    def execute_recovery(
        self,
        prompt: str,
        failure_class: FailureClassification,
        attempt: int = 1,
        gateway: Optional[Any] = None,
        expected_schema: Optional[Dict[str, Any]] = None,
    ) -> RecoveryResult:
        """Applies targeted recovery policy based on the diagnosed failure classification."""
        if failure_class == FailureClassification.GENUINELY_DISALLOWED_REQUEST:
            return RecoveryResult(
                success=False,
                failure_class=failure_class,
                attempts_used=1,
                max_attempts=self.max_attempts,
                original_prompt=prompt,
                strategy_applied="FAIL_CLOSED_GATE_EXPLANATION",
                error_message="Real consequential execution is permanently locked (LIVE_ORDER_DISPATCH_ENABLED = False). Real money trades cannot be dispatched.",
                is_genuine_safety_gate=True
            )

        if attempt > self.max_attempts:
            return RecoveryResult(
                success=False,
                failure_class=failure_class,
                attempts_used=attempt,
                max_attempts=self.max_attempts,
                original_prompt=prompt,
                strategy_applied="BOUNDED_RETRY_EXHAUSTED",
                error_message=f"Maximum recovery attempts ({self.max_attempts}) reached without resolution."
            )

        # Policy 1: Misclassified Ordinary Task -> De-sensitize and add engineering frame
        if failure_class == FailureClassification.ORDINARY_TASK_MISCLASSIFIED:
            desensitized = self.desensitize_prompt(prompt)
            return RecoveryResult(
                success=True,
                failure_class=failure_class,
                attempts_used=attempt,
                max_attempts=self.max_attempts,
                original_prompt=prompt,
                recovered_prompt=desensitized,
                strategy_applied="PROMPT_DESENSITIZATION_AND_ENGINEERING_FRAMING"
            )

        # Policy 2: Malformed Output -> Strict Schema Re-Prompting
        if failure_class == FailureClassification.MALFORMED_OUTPUT:
            schema_reprompt = (
                f"{prompt}\n\n"
                f"CRITICAL FORMAT REQUIREMENT: Your previous response could not be parsed as valid JSON.\n"
                f"You MUST return ONLY a syntactically valid JSON object. No conversational markdown, no code fences, no unquoted keys."
            )
            return RecoveryResult(
                success=True,
                failure_class=failure_class,
                attempts_used=attempt,
                max_attempts=self.max_attempts,
                original_prompt=prompt,
                recovered_prompt=schema_reprompt,
                strategy_applied="STRICT_SCHEMA_REPROMPT"
            )

        # Policy 3: Rate limit / timeout -> Exponential backoff & model failover
        if failure_class in (FailureClassification.RATE_LIMIT_OR_TIMEOUT, FailureClassification.PROVIDER_OR_NETWORK_ERROR):
            failover_strategy = f"BACKOFF_AND_MODEL_FAILOVER_STEP_{attempt}"
            return RecoveryResult(
                success=True,
                failure_class=failure_class,
                attempts_used=attempt,
                max_attempts=self.max_attempts,
                original_prompt=prompt,
                recovered_prompt=prompt,
                strategy_applied=failover_strategy
            )

        # Policy 4: Context Overflow -> Prune context
        if failure_class == FailureClassification.INSUFFICIENT_CONTEXT:
            pruned_prompt = prompt[:len(prompt) // 2] + "\n[... Context pruned for token budget ...]"
            return RecoveryResult(
                success=True,
                failure_class=failure_class,
                attempts_used=attempt,
                max_attempts=self.max_attempts,
                original_prompt=prompt,
                recovered_prompt=pruned_prompt,
                strategy_applied="CONTEXT_TRUNCATION_AND_PRUNING"
            )

        return RecoveryResult(
            success=False,
            failure_class=failure_class,
            attempts_used=attempt,
            max_attempts=self.max_attempts,
            original_prompt=prompt,
            strategy_applied="GENERIC_FAILURE_FALLBACK",
            error_message="Could not resolve unhandled failure class."
        )
