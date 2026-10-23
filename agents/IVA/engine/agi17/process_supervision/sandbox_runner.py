"""AGI 1.7 Disposable Sandbox Runner & Production Security Gate.

Provides fail-closed defense-in-depth for executing model-generated code and untrusted tests:
1. Production Disposable Docker Container Isolation (`SandboxPolicy.production()`):
   - Requires immutable SHA-256 digest-pinned image (`APPROVED_PINNED_PYTHON_IMAGE`).
   - Runs with `--rm --network none --cap-drop ALL --security-opt no-new-privileges
     --read-only --tmpfs /tmp --cpus --memory --pids-limit --user 65534:65534`.
   - Zero silent fallback to host Python interpreter (`allow_host_subprocess_fallback=False`).
   - Zero shell interpolation of `test_pattern` (validated by `validate_test_pattern`
     and passed as separate `argv` element directly to `python3 -B -s -c ...`).
   - Verified container termination and removal via `docker container inspect`.
2. Explicit Development Mode (`SandboxPolicy.development()`):
   - Only active when explicitly requested; never activated as a fallback from production.
3. Path Traversal & Special Object Prevention (`validate_relative_sandbox_path`):
   - Rejects `..`, `/` or `\\` traversal, absolute/drive paths, reserved device names,
     symlinks, FIFOs, sockets, and block/char devices before file reads or model calls.
4. Prompt-Injection Scanner (`scan_untrusted_content`) & `HighImpactApprovalGate`.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


class SandboxSecurityError(RuntimeError):
    """Base exception for sandbox security policy violations."""


class SandboxIsolationUnavailableError(SandboxSecurityError):
    """Raised when container isolation is required but Docker or the approved digest-pinned image is unavailable."""


class SandboxPolicyViolationError(SandboxIsolationUnavailableError):
    """Raised when a sandbox policy configuration violates fail-closed container or digest-pinning rules."""


class PathTraversalViolationError(SandboxSecurityError):
    """Raised when a file operation attempts to escape the sandbox root directory or uses an invalid filename."""


PathTraversalBlockedError = PathTraversalViolationError


class HighImpactActionBlockedError(SandboxSecurityError):
    """Raised when a high-impact action or workspace mutation is attempted without explicit human approval."""


class UntrustedContentSecurityError(SandboxSecurityError):
    """Raised when malicious code or prompt-injection attempts to exfiltrate secrets or attack the host."""


UntrustedContentBlockedError = UntrustedContentSecurityError


class InvalidTestPatternError(SandboxSecurityError):
    """Raised when a unittest discovery pattern is malformed, overly broad, path-bearing, or contains metacharacters."""


class SandboxCleanupUnverifiedError(SandboxSecurityError):
    """Raised when container or staging filesystem cleanup cannot be verified."""


APPROVED_PINNED_PYTHON_IMAGE = (
    "python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1"
)
APPROVED_PRODUCTION_IMAGES = frozenset({APPROVED_PINNED_PYTHON_IMAGE})

_DIGEST_PINNED_IMAGE_RE = re.compile(
    r"^[a-z0-9][a-z0-9._/-]*(?::[a-zA-Z0-9._-]+)?@sha256:[0-9a-f]{64}$"
)
_SAFE_TEST_PATTERN_RE = re.compile(r"^(?:test[A-Za-z0-9_*?.-]*|[A-Za-z0-9_*?.-]*_test)\.py$")
_WINDOWS_RESERVED_STEMS = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)

_CONTAINER_UNITTEST_BOOTSTRAP = (
    "import os, shutil, subprocess, sys; "
    "shutil.copytree('/input', '/tmp/work', dirs_exist_ok=True); "
    "os.chdir('/tmp/work'); "
    "raise SystemExit(subprocess.call("
    "['python3', '-B', '-s', '-m', 'unittest', 'discover', '-v', '-s', '.', '-t', '.', '-p', sys.argv[1]]"
    "))"
)


def validate_test_pattern(test_pattern: str) -> str:
    """Validates that `test_pattern` is a safe filename-only unittest discovery pattern with zero shell/path hazards."""
    if not isinstance(test_pattern, str):
        raise InvalidTestPatternError("Test pattern must be a string.")
    if len(test_pattern) < 4 or len(test_pattern) > 128:
        raise InvalidTestPatternError(
            f"Test pattern length ({len(test_pattern)}) outside allowed range [4, 128]: '{test_pattern}'"
        )
    if test_pattern != test_pattern.strip() or any(ch.isspace() or ord(ch) < 32 for ch in test_pattern):
        raise InvalidTestPatternError(
            f"Test pattern must not contain whitespace or control characters: '{test_pattern}'"
        )
    if ".." in test_pattern or "/" in test_pattern or "\\" in test_pattern or ":" in test_pattern:
        raise InvalidTestPatternError(
            f"Path separators, drive qualifiers, and '..' traversal are forbidden in test_pattern: '{test_pattern}'"
        )
    if not _SAFE_TEST_PATTERN_RE.match(test_pattern):
        raise InvalidTestPatternError(
            f"Rejected unsafe or overly broad test_pattern '{test_pattern}'; must match '^(?:test...|..._test)\\.py$'."
        )
    return test_pattern


@dataclass
class SandboxPolicy:
    """Resource, network, filesystem, and container isolation policy for untrusted execution.

    Defaults to fail-closed production container isolation (`isolation_mode='docker'`,
    `require_container_isolation=True`, `require_pinned_image_digest=True`,
    `allow_host_subprocess_fallback=False`, `docker_image=APPROVED_PINNED_PYTHON_IMAGE`).
    """

    isolation_mode: str = "docker"  # "docker" | "auto" | "restricted_tempdir"
    require_container_isolation: Optional[bool] = None
    require_pinned_image_digest: Optional[bool] = None
    allow_host_subprocess_fallback: Optional[bool] = None
    network_enabled: bool = False
    cpu_limit: float = 1.0
    memory_limit_mb: int = 256
    pids_limit: int = 64
    wall_timeout_sec: float = 30.0
    max_output_bytes: int = 65_536
    docker_image: Optional[str] = APPROVED_PINNED_PYTHON_IMAGE
    block_dangerous_code_patterns: bool = True

    def __post_init__(self) -> None:
        if self.isolation_mode not in ("docker", "auto", "restricted_tempdir"):
            raise ValueError(f"Unsupported isolation_mode: '{self.isolation_mode}'")
        if self.isolation_mode == "docker":
            if self.require_container_isolation is None:
                self.require_container_isolation = True
            if self.require_pinned_image_digest is None:
                self.require_pinned_image_digest = True
            if self.allow_host_subprocess_fallback is None:
                self.allow_host_subprocess_fallback = False
        else:
            if self.require_container_isolation is None:
                self.require_container_isolation = False
            if self.require_pinned_image_digest is None:
                self.require_pinned_image_digest = bool(self.require_container_isolation)
            if self.allow_host_subprocess_fallback is None:
                self.allow_host_subprocess_fallback = not bool(self.require_container_isolation)

        if self.require_container_isolation and self.allow_host_subprocess_fallback:
            raise SandboxPolicyViolationError(
                "Invalid SandboxPolicy: require_container_isolation=True cannot be combined with allow_host_subprocess_fallback=True."
            )

    @classmethod
    def production(
        cls,
        docker_image: Optional[str] = None,
        wall_timeout_sec: float = 30.0,
        timeout_sec: Optional[float] = None,
    ) -> "SandboxPolicy":
        """Fail-closed production policy: requires disposable Docker container isolation pinned by SHA-256 digest and never silently downgrades to host."""
        eff_timeout = float(timeout_sec) if timeout_sec is not None else float(wall_timeout_sec)
        pol = cls(
            isolation_mode="docker",
            require_container_isolation=True,
            require_pinned_image_digest=True,
            allow_host_subprocess_fallback=False,
            network_enabled=False,
            cpu_limit=1.0,
            memory_limit_mb=256,
            pids_limit=64,
            wall_timeout_sec=eff_timeout,
            docker_image=APPROVED_PINNED_PYTHON_IMAGE if docker_image is None else docker_image,
            block_dangerous_code_patterns=True,
        )
        pol.validate_image_policy()
        return pol

    @classmethod
    def development(cls, wall_timeout_sec: float = 30.0) -> "SandboxPolicy":
        """Explicit opt-in development/test policy: never selected automatically by production entry points."""
        return cls(
            isolation_mode="restricted_tempdir",
            require_container_isolation=False,
            require_pinned_image_digest=False,
            allow_host_subprocess_fallback=True,
            network_enabled=False,
            wall_timeout_sec=wall_timeout_sec,
            docker_image=None,
            block_dangerous_code_patterns=True,
        )

    def validate_image_policy(self) -> str:
        """Validates that `self.docker_image` satisfies digest pinning and approved-image allowlist rules."""
        img = (self.docker_image or "").strip()
        if not img:
            raise SandboxPolicyViolationError(
                "SandboxPolicy requires a configured docker_image, but none was provided."
            )
        if self.require_pinned_image_digest:
            if "@sha256:" not in img or not _DIGEST_PINNED_IMAGE_RE.match(img):
                raise SandboxPolicyViolationError(
                    f"SandboxPolicy requires an immutable '<image>@sha256:<64 lowercase hex>' digest, but got: '{img}'"
                )
            if img not in APPROVED_PRODUCTION_IMAGES:
                raise SandboxPolicyViolationError(
                    f"Docker image '{img}' is not in APPROVED_PRODUCTION_IMAGES ({sorted(APPROVED_PRODUCTION_IMAGES)})."
                )
        return img

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SandboxExecutionResult:
    """Structured result of running untrusted code/tests inside the disposable sandbox."""

    sandbox_id: str
    isolation_backend: str  # "docker_disposable_container" | "ephemeral_restricted_tempdir"
    passed: bool
    exit_code: int
    timed_out: bool
    duration_sec: float
    stdout: str
    stderr: str
    network_disabled: bool
    cleanup_verified: bool
    container_image: Optional[str] = None
    files_staged: List[str] = field(default_factory=list)
    policy_requested_network_disabled: bool = True
    verified_network_isolated: bool = False
    filesystem_cleanup_verified: bool = False
    container_cleanup_verified: bool = False
    approved_image_digest_verified: bool = False
    container_name: Optional[str] = None
    security_warnings: List[str] = field(default_factory=list)
    command_executed: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_PROMPT_INJECTION_PATTERNS = [
    (re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions"), "prompt_injection_ignore_previous"),
    (re.compile(r"(?i)system\s+override\s*:?\s*disable\s+security"), "prompt_injection_system_override"),
    (re.compile(r"(?i)--dangerously-skip-permissions"), "prompt_injection_skip_permissions"),
    (re.compile(r"(?i)exfiltrate\s+(secrets|api[_\s]?keys|credentials|env)"), "prompt_injection_exfiltration"),
]

_DANGEROUS_CODE_PATTERNS = [
    (
        re.compile(r"(?i)(\.gemini[/\\]*(?:config)?|\.ssh[/\\]+id_rsa|\.aws[/\\]+credentials|[/\\'\"\s]\.env['\"])"),
        "credential_file_access",
    ),
    (re.compile(r"(?i)shutil\.rmtree\s*\(\s*['\"](/|[a-zA-Z]:\\*)['\"]\s*\)"), "destructive_root_rmtree"),
    (re.compile(r"(?i)\b(rm\s+-rf\s+/|format\s+[a-zA-Z]:|del\s+/[fqs]\s+[a-zA-Z]:\\)"), "destructive_host_command"),
    (re.compile(r"(?i)\b(urllib\.request\.urlopen|socket\.create_connection|http\.client\.HTTP)"), "unauthorized_network_call"),
    (re.compile(r"(?i)\bsubprocess\.[A-Za-z_]+\s*\([^)]*shell\s*=\s*True"), "subprocess_shell_true"),
    (re.compile(r"(?i)\bos\.system\s*\("), "os_system_execution"),
]

_HIGH_IMPACT_ACTION_PATTERNS = [
    (re.compile(r"(?i)\bgit\s+(push|merge)\b"), "git_push_or_merge"),
    (re.compile(r"(?i)\b(pip|pip3)\s+install\b"), "package_install"),
    (re.compile(r"(?i)\b(rm\s+-rf|Remove-Item\s+.*-Recurse)\b"), "destructive_delete"),
    (re.compile(r"(?i)\b(curl|wget|Invoke-WebRequest)\b"), "external_network_fetch"),
    (re.compile(r"(?i)\b(Invoke-Expression|iex)\b"), "shell_eval_execution"),
]


class HighImpactApprovalGate:
    """Centralized policy gate requiring explicit human approval before executing high-impact actions or workspace mutations."""

    ALLOWLISTED_SAFE_ACTIONS = frozenset({"run_unittest", "read_workspace", "syntax_check", "stage_diff"})
    HIGH_IMPACT_ACTION_TYPES = frozenset(
        {
            "git_push",
            "git_merge",
            "deploy",
            "file_delete",
            "package_install",
            "external_network_call",
            "credential_access",
            "auth_policy_change",
            "db_migration",
            "destructive_command",
            "apply_workspace_patch",
            "write_generated_code",
            "orchestrator_stage_write",
            "orchestrator_self_healing_repair",
            "deliberate_fault_injection",
        }
    )

    def __init__(
        self,
        approval_callback: Optional[Callable[[str, str], bool]] = None,
        *,
        block_workspace_mutations: bool = False,
    ) -> None:
        self.approval_callback = approval_callback
        self.block_workspace_mutations = block_workspace_mutations
        self.audit_log: List[Dict[str, Any]] = []

    def check_structured_action(
        self,
        *,
        action_type: str,
        argv: Sequence[str],
        action_description: str = "",
        approved: bool = False,
    ) -> None:
        """Validates structured action type and argv before any side effect is performed."""
        if not action_type or not isinstance(action_type, str):
            raise HighImpactActionBlockedError("Malformed or empty action_type in approval request.")
        desc = action_description or f"{action_type}: {' '.join(str(a) for a in argv)}"
        joined_argv = " ".join(str(a) for a in argv)
        requires_approval = action_type in self.HIGH_IMPACT_ACTION_TYPES or action_type not in self.ALLOWLISTED_SAFE_ACTIONS
        matched_categories: List[str] = [action_type] if requires_approval else []
        for pattern, category in _HIGH_IMPACT_ACTION_PATTERNS:
            if pattern.search(joined_argv) and category not in matched_categories:
                matched_categories.append(category)

        if not matched_categories:
            return

        if self.approval_callback is not None:
            cb_result = bool(self.approval_callback(desc, ",".join(matched_categories)))
            is_approved = cb_result
        else:
            is_approved = bool(approved)

        self.audit_log.append(
            {
                "timestamp": time.time(),
                "action": desc,
                "action_type": action_type,
                "argv": list(argv),
                "categories": matched_categories,
                "approved": is_approved,
            }
        )
        if not is_approved:
            raise HighImpactActionBlockedError(
                f"High-impact action blocked ({', '.join(matched_categories)}): '{desc}' requires explicit human approval."
            )

    def validate_workspace_path_containment(
        self,
        *,
        workspace_root: Path,
        target_rel_path: Optional[str | Path] = None,
        target_path: Optional[str | Path] = None,
    ) -> Path:
        """Validates path containment inside `workspace_root` without manufacturing or checking mutation approval."""
        ws_root_res = workspace_root.resolve()
        raw_rel = target_rel_path if target_rel_path is not None else target_path
        if raw_rel is None:
            raise PathTraversalViolationError("Missing target path for workspace path containment check.")
        cand_p = Path(raw_rel)
        if cand_p.is_absolute():
            try:
                rel_p: str | Path = cand_p.resolve().relative_to(ws_root_res)
            except ValueError as exc:
                raise PathTraversalViolationError(
                    f"Target path '{raw_rel}' escapes workspace root '{ws_root_res}'"
                ) from exc
        else:
            rel_p = cand_p

        return validate_relative_sandbox_path(
            ws_root_res,
            rel_p,
            require_py_extension=True,
        )

    def check_preflight_access(
        self,
        *,
        workspace_root: Path,
        target_rel_path: Optional[str | Path] = None,
        target_path: Optional[str | Path] = None,
        explicit_approval: bool = False,
        action_type: str = "workspace_preflight",
        operation: Optional[str] = None,
        action_description: str = "",
    ) -> Path:
        """Validates path containment during preflight and enforces policy/callback blocks before model or test runs.

        Never manufactures approval: when `approval_callback` is None and `block_workspace_mutations` is False,
        validates containment and returns the target path without granting mutation permission.
        """
        validated_target = self.validate_workspace_path_containment(
            workspace_root=workspace_root,
            target_rel_path=target_rel_path,
            target_path=target_path,
        )
        ws_root_res = workspace_root.resolve()
        rel_p = validated_target.relative_to(ws_root_res)
        eff_action_type = operation or action_type
        desc = action_description or f"{eff_action_type} on {rel_p}"
        if self.block_workspace_mutations:
            self.audit_log.append(
                {
                    "timestamp": time.time(),
                    "action": desc,
                    "action_type": eff_action_type,
                    "workspace_root": str(ws_root_res),
                    "target_rel_path": str(rel_p),
                    "categories": [eff_action_type],
                    "approved": False,
                }
            )
            raise HighImpactActionBlockedError(
                f"Workspace preflight blocked ({eff_action_type}): '{desc}' blocked by block_workspace_mutations=True."
            )
        if self.approval_callback is not None and explicit_approval:
            cb_ok = bool(self.approval_callback(desc, eff_action_type))
            self.audit_log.append(
                {
                    "timestamp": time.time(),
                    "action": desc,
                    "action_type": eff_action_type,
                    "workspace_root": str(ws_root_res),
                    "target_rel_path": str(rel_p),
                    "categories": [eff_action_type],
                    "approved": cb_ok,
                }
            )
            if not cb_ok:
                raise HighImpactActionBlockedError(
                    f"Workspace preflight blocked ({eff_action_type}): '{desc}' denied by approval_callback."
                )
        return validated_target

    def is_workspace_mutation_authorized(
        self,
        *,
        workspace_root: Path,
        target_rel_path: Optional[str | Path] = None,
        target_path: Optional[str | Path] = None,
        explicit_approval: bool = False,
        action_type: str = "apply_workspace_patch",
        operation: Optional[str] = None,
        action_description: str = "",
    ) -> bool:
        """Evaluates whether an independently obtained authorization decision allows mutating a validated workspace file.

        - If `block_workspace_mutations=True`: raises `HighImpactActionBlockedError`.
        - If `approval_callback` is configured: invokes `approval_callback(desc, eff_action_type)`.
          If the callback returns False, raises `HighImpactActionBlockedError`. If True, returns True.
        - If `approval_callback` is None: returns `bool(explicit_approval)` (False by default unless caller explicitly approved).
        """
        validated_target = self.validate_workspace_path_containment(
            workspace_root=workspace_root,
            target_rel_path=target_rel_path,
            target_path=target_path,
        )
        ws_root_res = workspace_root.resolve()
        rel_p = validated_target.relative_to(ws_root_res)
        eff_action_type = operation or action_type
        desc = action_description or f"{eff_action_type} on {rel_p}"
        if self.block_workspace_mutations:
            self.audit_log.append(
                {
                    "timestamp": time.time(),
                    "action": desc,
                    "action_type": eff_action_type,
                    "workspace_root": str(ws_root_res),
                    "target_rel_path": str(rel_p),
                    "categories": [eff_action_type],
                    "approved": False,
                }
            )
            raise HighImpactActionBlockedError(
                f"Workspace mutation blocked ({eff_action_type}): '{desc}' was denied by block_workspace_mutations=True."
            )
        if self.approval_callback is not None:
            cb_ok = bool(self.approval_callback(desc, eff_action_type))
            self.audit_log.append(
                {
                    "timestamp": time.time(),
                    "action": desc,
                    "action_type": eff_action_type,
                    "workspace_root": str(ws_root_res),
                    "target_rel_path": str(rel_p),
                    "categories": [eff_action_type],
                    "approved": cb_ok,
                }
            )
            if not cb_ok:
                raise HighImpactActionBlockedError(
                    f"Workspace mutation blocked ({eff_action_type}): '{desc}' was denied by approval_callback."
                )
            return True
        is_approved = bool(explicit_approval)
        self.audit_log.append(
            {
                "timestamp": time.time(),
                "action": desc,
                "action_type": eff_action_type,
                "workspace_root": str(ws_root_res),
                "target_rel_path": str(rel_p),
                "categories": [eff_action_type],
                "approved": is_approved,
            }
        )
        return is_approved

    def check_workspace_mutation(
        self,
        *,
        workspace_root: Path,
        target_rel_path: Optional[str | Path] = None,
        target_path: Optional[str | Path] = None,
        explicit_approval: bool = False,
        action_type: str = "apply_workspace_patch",
        operation: Optional[str] = None,
        action_description: str = "",
    ) -> Path:
        """Validates path containment inside `workspace_root` and enforces approval before any protected file write."""
        validated_target = self.validate_workspace_path_containment(
            workspace_root=workspace_root,
            target_rel_path=target_rel_path,
            target_path=target_path,
        )
        ws_root_res = workspace_root.resolve()
        rel_p = validated_target.relative_to(ws_root_res)
        eff_action_type = operation or action_type
        desc = action_description or f"{eff_action_type} on {rel_p}"
        if self.block_workspace_mutations:
            is_approved = False
        elif self.approval_callback is not None:
            is_approved = bool(self.approval_callback(desc, eff_action_type))
        else:
            is_approved = bool(explicit_approval)

        self.audit_log.append(
            {
                "timestamp": time.time(),
                "action": desc,
                "action_type": eff_action_type,
                "workspace_root": str(ws_root_res),
                "target_rel_path": str(rel_p),
                "categories": [eff_action_type],
                "approved": is_approved,
            }
        )
        if not is_approved:
            raise HighImpactActionBlockedError(
                f"Workspace mutation blocked ({eff_action_type}): '{desc}' was denied or lacked explicit approval."
            )
        return validated_target

    def check_command(self, action_description: str, command_or_code: str, approved: bool = False) -> None:
        matched_categories: List[str] = []
        for pattern, category in _HIGH_IMPACT_ACTION_PATTERNS:
            if pattern.search(command_or_code):
                matched_categories.append(category)

        if not matched_categories:
            return

        if self.approval_callback is not None:
            is_approved = bool(self.approval_callback(action_description, ",".join(matched_categories)))
        else:
            is_approved = bool(approved)

        self.audit_log.append(
            {
                "timestamp": time.time(),
                "action": action_description,
                "categories": matched_categories,
                "approved": is_approved,
            }
        )
        if not is_approved:
            raise HighImpactActionBlockedError(
                f"High-impact action blocked ({', '.join(matched_categories)}): '{action_description}' requires explicit human approval."
            )


def _reject_special_filesystem_objects(path_obj: Path, label: str) -> None:
    """Rejects symlinks, FIFOs, character/block devices, and sockets."""
    try:
        st = os.lstat(path_obj)
    except FileNotFoundError:
        return
    mode = st.st_mode
    if stat.S_ISLNK(mode):
        raise PathTraversalViolationError(f"Symlink escape rejected in sandbox path: '{label}'")
    if stat.S_ISFIFO(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISSOCK(mode):
        raise PathTraversalViolationError(f"Special/device filesystem object rejected in sandbox path: '{label}'")


def validate_relative_sandbox_path(
    sandbox_root: Path,
    candidate_path: str | Path,
    *,
    require_py_extension: bool = False,
) -> Path:
    """Ensures `candidate_path` resolves strictly inside `sandbox_root` with zero traversal, symlink, reserved-name, or device-file escape."""
    if candidate_path is None:
        raise PathTraversalViolationError("Empty/None sandbox path rejected.")
    cand_str = str(candidate_path)
    if not cand_str or not cand_str.strip() or cand_str != cand_str.strip():
        raise PathTraversalViolationError(f"Empty or whitespace-padded sandbox path rejected: '{cand_str}'")
    if any(ord(ch) < 32 for ch in cand_str):
        raise PathTraversalViolationError(f"Control characters or null byte rejected in sandbox path: '{cand_str}'")
    if os.path.isabs(cand_str) or cand_str.startswith(("/", "\\")) or ":" in cand_str:
        raise PathTraversalViolationError(f"Absolute or drive-qualified path rejected in sandbox: '{cand_str}'")

    raw_parts = re.split(r"[/\\]+", cand_str)
    if not raw_parts or any(part in ("", ".", "..") for part in raw_parts):
        raise PathTraversalViolationError(f"Parent directory or dot traversal rejected in sandbox path: '{cand_str}'")
    for part in raw_parts:
        stem_upper = part.split(".")[0].upper()
        if stem_upper in _WINDOWS_RESERVED_STEMS:
            raise PathTraversalViolationError(f"Reserved platform device name rejected in sandbox path: '{cand_str}'")

    root_resolved = sandbox_root.resolve()
    if sandbox_root.is_symlink():
        raise PathTraversalViolationError(f"Sandbox root itself must not be a symlink: '{sandbox_root}'")

    cur_check = root_resolved
    for part in raw_parts:
        cur_check = cur_check / part
        if cur_check.is_symlink():
            raise PathTraversalViolationError(f"Symlink escape rejected in sandbox path: '{cand_str}'")
        _reject_special_filesystem_objects(cur_check, cand_str)

    raw_target = cur_check
    target = raw_target.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise PathTraversalViolationError(
            f"Sandbox path '{cand_str}' resolved outside sandbox root '{root_resolved}'"
        ) from exc

    if require_py_extension and target.suffix.lower() != ".py":
        raise PathTraversalViolationError(
            f"Expected '.py' extension for Python source/test file, got: '{cand_str}'"
        )
    return target


def stage_candidate_outside_workspace(
    workspace_root: Path,
    relative_path: str | Path,
    content: str | bytes,
    *,
    stage_label: str = "candidate",
) -> tuple[Path, Path, str]:
    """Produces generated or repaired code in an external staging directory strictly outside `workspace_root` before approval."""
    ws_resolved = workspace_root.resolve()
    validate_relative_sandbox_path(ws_resolved, relative_path, require_py_extension=True)
    safe_label = re.sub(r"[^a-zA-Z0-9_.-]", "_", stage_label)[:32]
    ext_stage_dir = Path(tempfile.mkdtemp(prefix=f"agi17_ext_stage_{safe_label}_")).resolve()
    try:
        ext_stage_dir.relative_to(ws_resolved)
        shutil.rmtree(ext_stage_dir, ignore_errors=True)
        raise PathTraversalViolationError(
            f"External staging directory '{ext_stage_dir}' must not reside inside active workspace '{ws_resolved}'"
        )
    except ValueError:
        pass

    staged_file = validate_relative_sandbox_path(ext_stage_dir, relative_path, require_py_extension=True)
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    raw_bytes = content if isinstance(content, bytes) else content.encode("utf-8")
    with open(staged_file, "wb") as fh:
        fh.write(raw_bytes)
        fh.flush()
        os.fsync(fh.fileno())
    staged_sha = hashlib.sha256(staged_file.read_bytes()).hexdigest()
    return ext_stage_dir, staged_file, staged_sha


def atomic_write_workspace_file(workspace_root: Path, relative_path: str | Path, content: str | bytes) -> Path:
    """Safely stages content to a temp file in the target directory and atomically replaces the target file."""
    target = validate_relative_sandbox_path(workspace_root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".stage_{target.name}_", dir=str(target.parent))
    tmp_path = Path(tmp_name)
    try:
        if isinstance(content, bytes):
            with os.fdopen(fd, "wb") as fh_b:
                fh_b.write(content)
                fh_b.flush()
                os.fsync(fh_b.fileno())
        else:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
        if target.is_symlink():
            raise PathTraversalViolationError(f"TOCTOU symlink swap detected before atomic replace: '{relative_path}'")
        os.replace(str(tmp_path), str(target))
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return target


def scan_untrusted_content(
    content: str,
    *,
    source_name: str = "untrusted_input",
    source_label: Optional[str] = None,
    block_on_code_hazards: bool = True,
) -> List[str]:
    """Scans repository files, issues, or generated code for prompt-injection and host-attack patterns."""
    eff_source = source_label or source_name
    warnings: List[str] = []
    for pattern, label in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(content):
            warnings.append(f"{eff_source}:{label}")
    for pattern, label in _DANGEROUS_CODE_PATTERNS:
        if pattern.search(content):
            warnings.append(f"{eff_source}:{label}")
            if block_on_code_hazards:
                raise UntrustedContentSecurityError(
                    f"Blocked dangerous pattern '{label}' in '{eff_source}'"
                )
    return warnings


class DisposableSandboxRunner:
    """Executes untrusted Python code and unit tests inside a disposable container or explicit development tempdir."""

    CANDIDATE_PYTHON_IMAGES = (
        APPROVED_PINNED_PYTHON_IMAGE,
        "python:3.12-slim",
        "python:3.11-slim",
    )

    def __init__(
        self,
        policy: Optional[SandboxPolicy] = None,
        approval_gate: Optional[HighImpactApprovalGate] = None,
    ) -> None:
        self.policy = policy or SandboxPolicy.production()
        self.approval_gate = approval_gate or HighImpactApprovalGate()
        self._cached_docker_image: Optional[str] = None
        self._docker_checked: bool = False

    def get_security_diagnostics(self) -> Dict[str, Any]:
        """Returns a safe, credential-free diagnostic snapshot of the runner identity and effective sandbox policy."""
        return {
            "runner_instance_id": id(self),
            "approval_gate_instance_id": id(self.approval_gate),
            "policy": self.policy.to_dict(),
            "approved_production_images": sorted(APPROVED_PRODUCTION_IMAGES),
        }

    def detect_docker_python_image(self) -> Optional[str]:
        """Verifies Docker daemon reachability and confirms the approved digest-pinned Python image is present locally."""
        if self._docker_checked and self._cached_docker_image is not None:
            return self._cached_docker_image

        if self.policy.docker_image is not None or self.policy.require_pinned_image_digest:
            validated_img = self.policy.validate_image_policy()
            if not shutil.which("docker"):
                return None
            try:
                proc = subprocess.run(
                    ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", validated_img],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                    shell=False,
                )
                if proc.returncode != 0:
                    return None
                stdout_txt = (proc.stdout or "").strip()
                if self.policy.require_pinned_image_digest and "@sha256:" in validated_img:
                    expected_digest = "sha256:" + validated_img.split("@sha256:", 1)[1]
                    if expected_digest not in stdout_txt:
                        raise SandboxIsolationUnavailableError(
                            f"Docker image inspect digest mismatch for '{validated_img}': expected '{expected_digest}', got '{stdout_txt}'"
                        )
                self._docker_checked = True
                self._cached_docker_image = validated_img
                return self._cached_docker_image
            except SandboxIsolationUnavailableError:
                raise
            except Exception:
                return None

        if not shutil.which("docker"):
            return None
        try:
            proc = subprocess.run(
                [
                    "docker",
                    "images",
                    "--digests",
                    "--format",
                    "{{.Repository}}:{{.Tag}}@{{.Digest}} {{.Repository}}:{{.Tag}}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                shell=False,
            )
            if proc.returncode != 0:
                return None
            available: set[str] = set()
            for ln in proc.stdout.splitlines():
                for tok in ln.strip().split():
                    if tok:
                        available.add(tok)
            for candidate in self.CANDIDATE_PYTHON_IMAGES:
                if self.policy.require_pinned_image_digest and candidate not in APPROVED_PRODUCTION_IMAGES:
                    continue
                if candidate in available:
                    self._docker_checked = True
                    self._cached_docker_image = candidate
                    return candidate
        except Exception:
            return None
        return None

    @staticmethod
    def _terminate_and_remove_container(container_name: str) -> None:
        """Stops with bounded wait, escalates to kill, and force-removes a named container using list argv (`shell=False`)."""
        for subcmd in (
            ["docker", "stop", "-t", "2", container_name],
            ["docker", "kill", container_name],
            ["docker", "rm", "-f", container_name],
        ):
            try:
                subprocess.run(
                    subcmd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                    shell=False,
                )
            except Exception:
                pass

    @classmethod
    def _verify_container_removed(cls, container_name: str) -> bool:
        """Verifies through `docker container inspect` that `container_name` is no longer present in Docker Engine."""
        for attempt in range(2):
            try:
                proc = subprocess.run(
                    ["docker", "container", "inspect", container_name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                    shell=False,
                )
            except Exception:
                return False

            combined = f"{proc.stdout or ''}\n{proc.stderr or ''}".lower()
            daemon_errors = (
                "cannot connect to the docker daemon",
                "error during connect",
                "daemon is not running",
                "is the docker daemon running",
            )
            if any(err in combined for err in daemon_errors):
                return False

            if proc.returncode != 0 and ("no such container" in combined or "no such object" in combined):
                return True
            if proc.returncode == 0 and (proc.stdout or "").strip() == "[]":
                return True

            if attempt == 0:
                cls._terminate_and_remove_container(container_name)
                time.sleep(0.05)

        return False

    @staticmethod
    def _build_sanitized_host_env(temp_root: Path) -> Dict[str, str]:
        """Strips all host credentials, tokens, and user environment variables while preserving stdlib lookup."""
        stdlib_paths = [
            p
            for p in sys.path
            if p and any(k in p for k in ("Lib", "DLLs", "lib", ".zip")) and "site-packages" not in p
        ]
        safe_env: Dict[str, str] = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": os.pathsep.join([str(temp_root), *stdlib_paths]),
            "HOME": str(temp_root),
            "USERPROFILE": str(temp_root),
            "TEMP": str(temp_root),
            "TMP": str(temp_root),
        }
        if os.name == "nt":
            for win_key in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE"):
                if win_key in os.environ:
                    safe_env[win_key] = os.environ[win_key]
        return safe_env

    def _run_in_restricted_tempdir(
        self,
        *,
        staging_dir: Path,
        validated_pattern: str,
        eff_timeout: float,
    ) -> tuple[List[str], subprocess.CompletedProcess[str]]:
        py_bin = sys.executable or ("py" if os.name == "nt" else "python3")
        cmd_executed = [
            py_bin,
            "-B",
            "-s",
            "-m",
            "unittest",
            "discover",
            "-v",
            "-s",
            ".",
            "-t",
            ".",
            "-p",
            validated_pattern,
        ]
        safe_env = self._build_sanitized_host_env(staging_dir)
        proc = subprocess.run(
            cmd_executed,
            cwd=str(staging_dir),
            env=safe_env,
            capture_output=True,
            text=True,
            timeout=eff_timeout,
            check=False,
            shell=False,
        )
        return cmd_executed, proc

    def run_python_unittest_sandbox(
        self,
        *,
        files: Dict[str, str],
        test_pattern: str = "test_*.py",
        sandbox_id: Optional[str] = None,
        timeout_sec: Optional[float] = None,
    ) -> SandboxExecutionResult:
        """Writes `files` into a disposable sandbox, executes `unittest` without shell interpolation, and verifies cleanup."""
        sid = sandbox_id or f"SBX-{int(time.time() * 1000)}"
        validated_pattern = validate_test_pattern(test_pattern)
        eff_timeout = float(timeout_sec) if timeout_sec is not None else float(self.policy.wall_timeout_sec)
        warnings: List[str] = []

        # 1. Scan all files for prompt injection and dangerous code patterns before writing to disk
        for rel_path, content in files.items():
            file_warnings = scan_untrusted_content(
                content,
                source_name=rel_path,
                block_on_code_hazards=self.policy.block_dangerous_code_patterns,
            )
            warnings.extend(file_warnings)

        # 2. Resolve isolation backend — fail closed when container isolation is required
        use_docker = False
        docker_img: Optional[str] = None
        approved_digest_verified = False

        if self.policy.isolation_mode == "restricted_tempdir":
            if self.policy.require_container_isolation or not self.policy.allow_host_subprocess_fallback:
                raise SandboxIsolationUnavailableError(
                    "Cannot satisfy container isolation policy with isolation_mode='restricted_tempdir'."
                )
        elif self.policy.isolation_mode == "docker":
            docker_img = self.detect_docker_python_image()
            if not docker_img:
                raise SandboxIsolationUnavailableError(
                    "SandboxPolicy requires isolation_mode='docker', but Docker daemon or approved digest-pinned image is unavailable."
                )
            use_docker = True
            approved_digest_verified = bool(
                "@sha256:" in docker_img and docker_img in APPROVED_PRODUCTION_IMAGES
            )
        elif self.policy.isolation_mode == "auto":
            docker_img = self.detect_docker_python_image()
            if docker_img:
                use_docker = True
                approved_digest_verified = bool(
                    "@sha256:" in docker_img and docker_img in APPROVED_PRODUCTION_IMAGES
                )
            elif self.policy.require_container_isolation or not self.policy.allow_host_subprocess_fallback:
                raise SandboxIsolationUnavailableError(
                    "SandboxPolicy forbids host fallback, and Docker daemon or approved Python image is unavailable."
                )
        else:
            raise ValueError(f"Unsupported isolation_mode: '{self.policy.isolation_mode}'")

        if not use_docker and (
            self.policy.require_container_isolation or not self.policy.allow_host_subprocess_fallback
        ):
            raise SandboxIsolationUnavailableError(
                "Production SandboxPolicy forbids host Python fallback when container isolation is inactive."
            )

        staging_dir = Path(tempfile.mkdtemp(prefix=f"agi17_sbx_{sid}_"))
        container_name = re.sub(
            r"[^a-zA-Z0-9_.-]",
            "_",
            f"agi17_sbx_{sid}_{uuid.uuid4().hex[:8]}",
        )[:60]
        t0 = time.perf_counter()
        exit_code = -1
        timed_out = False
        stdout_str = ""
        stderr_str = ""
        cmd_executed: List[str] = []
        backend_label = "docker_disposable_container" if use_docker else "ephemeral_restricted_tempdir"
        container_cleanup_ok = not use_docker

        try:
            if use_docker:
                os.chmod(staging_dir, 0o755)
            for rel_path, content in files.items():
                target_file = validate_relative_sandbox_path(staging_dir, rel_path)
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(content, encoding="utf-8")
                if use_docker:
                    os.chmod(target_file, 0o644)
                    cur_dir = target_file.parent
                    while cur_dir != staging_dir and staging_dir in cur_dir.parents:
                        os.chmod(cur_dir, 0o755)
                        cur_dir = cur_dir.parent

            if use_docker and docker_img:
                cmd_executed = [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    container_name,
                    "--user",
                    "65534:65534",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
                    "--cpus",
                    str(self.policy.cpu_limit),
                    "--memory",
                    f"{int(self.policy.memory_limit_mb)}m",
                    "--pids-limit",
                    str(int(self.policy.pids_limit)),
                ]
                if not self.policy.network_enabled:
                    cmd_executed.extend(["--network", "none"])
                cmd_executed.extend(
                    [
                        "-v",
                        f"{staging_dir.resolve()}:/input:ro",
                        docker_img,
                        "python3",
                        "-B",
                        "-s",
                        "-c",
                        _CONTAINER_UNITTEST_BOOTSTRAP,
                        validated_pattern,
                    ]
                )
                proc = subprocess.run(
                    cmd_executed,
                    capture_output=True,
                    text=True,
                    timeout=eff_timeout,
                    check=False,
                    shell=False,
                )
                exit_code = proc.returncode
                stdout_str = proc.stdout or ""
                stderr_str = proc.stderr or ""
                if exit_code != 0:
                    self._terminate_and_remove_container(container_name)
            else:
                cmd_executed, proc = self._run_in_restricted_tempdir(
                    staging_dir=staging_dir,
                    validated_pattern=validated_pattern,
                    eff_timeout=eff_timeout,
                )
                exit_code = proc.returncode
                stdout_str = proc.stdout or ""
                stderr_str = proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = 124
            if use_docker:
                self._terminate_and_remove_container(container_name)
            stdout_str = (
                exc.stdout.decode("utf-8", errors="replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )
            stderr_str = (
                exc.stderr.decode("utf-8", errors="replace")
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or "")
            ) + "\nSandbox execution timed out."
        except Exception:
            if use_docker:
                self._terminate_and_remove_container(container_name)
            raise
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
            if use_docker:
                container_cleanup_ok = self._verify_container_removed(container_name)

        from ..adapters.model_adapter import redact_sensitive_text

        fs_cleanup_ok = not staging_dir.exists()
        cleanup_ok = bool(fs_cleanup_ok and (container_cleanup_ok if use_docker else True))
        dt = round(time.perf_counter() - t0, 4)
        stdout_redacted = redact_sensitive_text(stdout_str[: self.policy.max_output_bytes])
        stderr_redacted = redact_sensitive_text(stderr_str[: self.policy.max_output_bytes])
        policy_net_disabled = not self.policy.network_enabled
        verified_net_isolated = bool(use_docker and policy_net_disabled)
        passed = bool(
            exit_code == 0
            and not timed_out
            and cleanup_ok
            and (
                not self.policy.require_container_isolation
                or (
                    use_docker
                    and (not self.policy.require_pinned_image_digest or approved_digest_verified)
                )
            )
        )

        return SandboxExecutionResult(
            sandbox_id=sid,
            isolation_backend=backend_label,
            passed=passed,
            exit_code=exit_code,
            timed_out=timed_out,
            duration_sec=dt,
            stdout=stdout_redacted,
            stderr=stderr_redacted,
            network_disabled=policy_net_disabled,
            cleanup_verified=cleanup_ok,
            container_image=docker_img,
            files_staged=list(files.keys()),
            policy_requested_network_disabled=policy_net_disabled,
            verified_network_isolated=verified_net_isolated,
            filesystem_cleanup_verified=fs_cleanup_ok,
            container_cleanup_verified=container_cleanup_ok,
            approved_image_digest_verified=approved_digest_verified,
            container_name=container_name if use_docker else None,
            security_warnings=warnings,
            command_executed=[redact_sensitive_text(c) for c in cmd_executed],
        )
