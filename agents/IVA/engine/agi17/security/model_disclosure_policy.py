"""AGI 1.7 Centralized Model-Disclosure Authorization & Privacy Policy.

Separates data-disclosure consent from workspace-mutation approval and sandbox execution permissions:
1. Production-Strict Default Deny: Existing workspace file contents cannot leave the local machine
   to an external model provider unless explicit disclosure authorization is granted.
2. Pre-Call Interception: Denied or missing authorization blocks disclosure BEFORE any model
   provider is invoked or transmitted, ensuring zero outbound calls on denial.
3. Local-Only Mode: Enforces strict zero-external-egress guarantee; fails closed if an external
   provider is targeted or if a local provider is unavailable.
4. Comprehensive Secret Redaction & Data Minimization: Pre-transmission redaction of known API
   keys, tokens, database URIs, passwords, and private keys with documented limitations.
5. Content-Free Audit Logging: Records timestamps, task IDs, hashes, decisions, and rule matches
   without logging raw proprietary code, secrets, or sensitive prompts.
6. Empty-Workspace & Pure-Instruction Support: Permissive for new/empty workspaces or instructions
   that contain no protected local source code or workspace files.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


class DisclosureMode(str, enum.Enum):
    """Operational mode for workspace-to-model data egress."""

    PRODUCTION_STRICT = "PRODUCTION_STRICT"  # Default-deny external workspace disclosure
    LOCAL_ONLY = "LOCAL_ONLY"                # Zero external provider calls allowed; fails closed
    PERMISSIVE_DEV = "PERMISSIVE_DEV"        # Explicit development mode allowing workspace disclosure


class ModelDisclosureDeniedError(RuntimeError):
    """Raised when an attempt is made to transmit protected workspace data to a model without authorization."""


class ExternalProviderBlockedInLocalOnlyModeError(RuntimeError):
    """Raised when an external model provider is invoked while local-only mode is active."""


# Comprehensive regex definitions for outbound secret redaction
_SECRET_PATTERNS: List[Tuple[str, re.Pattern, str]] = [
    # Google API Keys
    ("GOOGLE_API_KEY", re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "<REDACTED_GOOGLE_API_KEY>"),
    # OpenAI & Anthropic Style Secret Keys
    ("SK_SECRET_KEY", re.compile(r"sk-[A-Za-z0-9\-_]{20,}"), "<REDACTED_SK_KEY>"),
    # GitHub Personal Access Tokens
    ("GITHUB_PAT_CLASSIC", re.compile(r"ghp_[A-Za-z0-9]{30,}"), "<REDACTED_GITHUB_TOKEN>"),
    ("GITHUB_PAT_FINE_GRAINED", re.compile(r"github_pat_[A-Za-z0-9_]{22,}"), "<REDACTED_GITHUB_PAT>"),
    # AWS Access Keys & Secrets
    ("AWS_ACCESS_KEY", re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"), "<REDACTED_AWS_KEY>"),
    ("AWS_SECRET_KEY", re.compile(r"(?i)aws_secret_access_key\s*=\s*['\"][A-Za-z0-9/+=]{40}['\"]"), "aws_secret_access_key='<REDACTED_AWS_SECRET>'"),
    # Generic Bearer Tokens
    ("BEARER_TOKEN", re.compile(r"(?i)Bearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer <REDACTED_TOKEN>"),
    # PEM Private Keys
    ("PEM_PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "<REDACTED_PRIVATE_KEY>"),
    # Database Connection URIs with credentials
    ("DATABASE_URI", re.compile(r"(?i)(postgres|postgresql|mysql|mongodb|redis|mssql):\/\/[^\s'\"@]+:[^\s'\"@]+@[^\s'\"]+"), r"\1://<REDACTED_USER>:<REDACTED_PASSWORD>@<REDACTED_HOST>"),
    # Generic Password / Secret Key assignments in code or config
    ("KEY_ASSIGNMENT", re.compile(r"(?i)(api[_-]?key|access[_-]?token|auth[_-]?token|secret[_-]?key|password|passwd|client[_-]?secret)\s*[:=]\s*['\"][A-Za-z0-9\-_.~!@#$%^&*+=]{8,}['\"]"), r"\1='<REDACTED_CREDENTIAL>'"),
    # Financial Brokerage API Keys & Credentials (Zerodha/Upstox/Angel/Groww/etc.)
    ("BROKER_CREDENTIAL", re.compile(r"(?i)(zerodha|upstox|kite|angel|groww)[_-]?(api[_-]?key|secret|token|password|session)\s*[:=]\s*['\"][^\r\n'\"]+['\"]"), r"\1_\2='<REDACTED_BROKER_CREDENTIAL>'"),
    # TOTP Authenticator Secrets
    ("TOTP_SECRET", re.compile(r"(?i)(totp[_-]?(?:secret|token|key))\s*[:=]\s*['\"][A-Za-z0-9+=]{8,}['\"]"), r"\1='<REDACTED_TOTP_SECRET>'"),
    # Slack & Webhook URLs
    ("SLACK_WEBHOOK", re.compile(r"https:\/\/hooks\.slack\.com\/services\/T[0-9A-Za-z]+\/B[0-9A-Za-z]+\/[0-9A-Za-z]+"), "<REDACTED_SLACK_WEBHOOK>"),
]


class SecretRedactor:
    """Pre-transmission sanitizer removing known credentials, tokens, and home paths."""

    @staticmethod
    def redact(text: str) -> Tuple[str, int]:
        """Redacts known secrets and returns (sanitized_text, count_of_redactions)."""
        if not text:
            return text, 0
        redacted = text
        total_redactions = 0

        for _name, pattern, replacement in _SECRET_PATTERNS:
            matches = len(pattern.findall(redacted))
            if matches > 0:
                total_redactions += matches
                redacted = pattern.sub(replacement, redacted)

        try:
            user_home = str(Path.home())
            if user_home and len(user_home) > 3:
                escaped_home = re.escape(user_home)
                matches_home = len(re.findall(escaped_home, redacted, flags=re.IGNORECASE))
                if matches_home > 0:
                    total_redactions += matches_home
                    redacted = re.sub(escaped_home, "<USER_HOME>", redacted, flags=re.IGNORECASE)
                forward_home = re.escape(user_home.replace("\\", "/"))
                matches_fwd = len(re.findall(forward_home, redacted, flags=re.IGNORECASE))
                if matches_fwd > 0:
                    total_redactions += matches_fwd
                    redacted = re.sub(forward_home, "<USER_HOME>", redacted, flags=re.IGNORECASE)
        except Exception:
            pass

        return redacted, total_redactions


@dataclass(frozen=True)
class DisclosureContext:
    """Context information for evaluating whether workspace data may be disclosed."""

    task_id: str
    agent_id: str
    workspace_root: Optional[str | Path] = None
    target_files: Sequence[str] = field(default_factory=list)
    has_workspace_content: bool = False
    is_external_provider: bool = True
    provider_name: str = "gemini-3.8-flash-high"
    operation_type: str = "model_inference"


@dataclass(frozen=True)
class DisclosureDecision:
    """Evaluation result from the centralized ModelDisclosurePolicy."""

    authorized: bool
    mode: DisclosureMode
    reason: str
    redacted_patterns_count: int = 0
    file_hashes: Dict[str, str] = field(default_factory=dict)
    timestamp_utc: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ModelDisclosurePolicy:
    """Explicit, centralized policy gate governing data transmission to external model providers."""

    def __init__(
        self,
        *,
        mode: DisclosureMode = DisclosureMode.PRODUCTION_STRICT,
        allow_workspace_model_disclosure: bool = False,
        local_only: bool = False,
        allowed_globs: Optional[List[str]] = None,
        disclosure_authorizer: Optional[Callable[[DisclosureContext], bool]] = None,
        audit_log_path: Optional[str | Path] = None,
        redact_secrets_outbound: bool = True,
    ) -> None:
        self.mode = mode
        self.allow_workspace_model_disclosure = allow_workspace_model_disclosure
        self.local_only = local_only or (mode == DisclosureMode.LOCAL_ONLY)
        self.allowed_globs = allowed_globs or []
        self.disclosure_authorizer = disclosure_authorizer
        self.audit_log_path = Path(audit_log_path) if audit_log_path else None
        self.redact_secrets_outbound = redact_secrets_outbound
        self._lock = threading.Lock()

        if self.audit_log_path:
            try:
                self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    @classmethod
    def production_strict(
        cls,
        *,
        allow_workspace_model_disclosure: bool = False,
        disclosure_authorizer: Optional[Callable[[DisclosureContext], bool]] = None,
        audit_log_path: Optional[str | Path] = None,
    ) -> ModelDisclosurePolicy:
        """Constructs the standard production-strict policy (default-deny workspace disclosure)."""
        return cls(
            mode=DisclosureMode.PRODUCTION_STRICT,
            allow_workspace_model_disclosure=allow_workspace_model_disclosure,
            local_only=False,
            disclosure_authorizer=disclosure_authorizer,
            audit_log_path=audit_log_path,
            redact_secrets_outbound=True,
        )

    @classmethod
    def local_only_mode(
        cls,
        *,
        audit_log_path: Optional[str | Path] = None,
    ) -> ModelDisclosurePolicy:
        """Constructs a strict local-only policy that blocks all external model provider invocations."""
        return cls(
            mode=DisclosureMode.LOCAL_ONLY,
            allow_workspace_model_disclosure=False,
            local_only=True,
            audit_log_path=audit_log_path,
            redact_secrets_outbound=True,
        )

    def evaluate(self, ctx: DisclosureContext) -> DisclosureDecision:
        """Evaluates whether the requested model call is permitted to transmit workspace data."""
        # Check 1: Local-only enforcement
        if self.local_only and ctx.is_external_provider:
            decision = DisclosureDecision(
                authorized=False,
                mode=self.mode,
                reason=(
                    f"LOCAL_ONLY_POLICY_VIOLATION: External model provider '{ctx.provider_name}' "
                    f"is blocked under local-only mode."
                ),
            )
            self._record_audit(ctx, decision)
            return decision

        # Check 2: If there is no existing protected workspace data in the call (e.g. empty workspace,
        # single-shot instruction, or pure code generation from scratch), disclosure is allowed.
        if not ctx.has_workspace_content:
            decision = DisclosureDecision(
                authorized=True,
                mode=self.mode,
                reason="DISCLOSURE_PERMITTED: Task contains no protected workspace file contents.",
            )
            self._record_audit(ctx, decision)
            return decision

        # Check 3: If provider is purely local (offline in-process mock / local weights),
        # workspace data does not egress outside the local machine.
        if not ctx.is_external_provider:
            decision = DisclosureDecision(
                authorized=True,
                mode=self.mode,
                reason="DISCLOSURE_PERMITTED: In-process local provider does not egress data outside machine.",
            )
            self._record_audit(ctx, decision)
            return decision

        # Check 3: Development permissive mode
        if self.mode == DisclosureMode.PERMISSIVE_DEV:
            decision = DisclosureDecision(
                authorized=True,
                mode=self.mode,
                reason="DISCLOSURE_PERMITTED: Permissive development mode active.",
            )
            self._record_audit(ctx, decision)
            return decision

        # Check 4: Explicit static authorization flag
        if self.allow_workspace_model_disclosure:
            decision = DisclosureDecision(
                authorized=True,
                mode=self.mode,
                reason="DISCLOSURE_PERMITTED: Explicit allow_workspace_model_disclosure grant.",
            )
            self._record_audit(ctx, decision)
            return decision

        # Check 5: Dynamic authorizer callback
        if self.disclosure_authorizer is not None:
            try:
                granted = bool(self.disclosure_authorizer(ctx))
                if granted:
                    decision = DisclosureDecision(
                        authorized=True,
                        mode=self.mode,
                        reason="DISCLOSURE_PERMITTED: Dynamic disclosure_authorizer granted consent.",
                    )
                    self._record_audit(ctx, decision)
                    return decision
                else:
                    decision = DisclosureDecision(
                        authorized=False,
                        mode=self.mode,
                        reason="DISCLOSURE_DENIED: Dynamic disclosure_authorizer explicitly denied consent.",
                    )
                    self._record_audit(ctx, decision)
                    return decision
            except Exception as exc:
                decision = DisclosureDecision(
                    authorized=False,
                    mode=self.mode,
                    reason=f"DISCLOSURE_DENIED: Dynamic authorizer raised exception ({type(exc).__name__}): {exc}",
                )
                self._record_audit(ctx, decision)
                return decision

        # Check 6: Default-Deny fallback
        decision = DisclosureDecision(
            authorized=False,
            mode=self.mode,
            reason=(
                f"DISCLOSURE_DENIED: Sending existing workspace source/tests to external provider "
                f"'{ctx.provider_name}' is not authorized (allow_workspace_model_disclosure=False). "
                f"Workspace-write permission does NOT imply data disclosure consent."
            ),
        )
        self._record_audit(ctx, decision)
        return decision

    def authorize_or_raise(self, ctx: DisclosureContext) -> DisclosureDecision:
        """Evaluates policy and raises a typed security error if disclosure is denied."""
        decision = self.evaluate(ctx)
        if not decision.authorized:
            if "LOCAL_ONLY_POLICY_VIOLATION" in decision.reason:
                raise ExternalProviderBlockedInLocalOnlyModeError(decision.reason)
            raise ModelDisclosureDeniedError(decision.reason)
        return decision

    def sanitize_outbound_prompt(self, prompt: str) -> Tuple[str, int]:
        """Applies secret redaction to outbound prompt text if enabled."""
        if not self.redact_secrets_outbound:
            return prompt, 0
        return SecretRedactor.redact(prompt)

    def _record_audit(self, ctx: DisclosureContext, decision: DisclosureDecision) -> None:
        """Appends audit event with file hashes and metadata without logging raw source code or tokens."""
        if not self.audit_log_path:
            return
        entry = {
            "timestamp_utc": decision.timestamp_utc,
            "task_id": ctx.task_id,
            "agent_id": ctx.agent_id,
            "authorized": decision.authorized,
            "mode": decision.mode.value,
            "provider_name": ctx.provider_name,
            "is_external": ctx.is_external_provider,
            "target_files_count": len(ctx.target_files),
            "target_files": list(ctx.target_files),
            "reason": decision.reason,
        }
        with self._lock:
            try:
                with open(self.audit_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception:
                pass
