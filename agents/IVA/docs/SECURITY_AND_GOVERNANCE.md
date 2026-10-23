# AGI 1.7 — OMEGA COMMAND: Production Security & Governance Specification

## 1. Mandatory Production Container Isolation (Fail-Closed Default)

Production execution of untrusted repository code, test suites, or model-generated patches in **AGI 1.7 — OMEGA COMMAND** (`AGI17Adapter`, `HierarchicalOrchestrator`, and `CIRepairAgent`) is governed by `SandboxPolicy.production()` in [`sandbox_runner.py`](../agents/AGI_1_7/engine/agi17/process_supervision/sandbox_runner.py):

- **Default Isolation Mode:** `isolation_mode = "docker"`, `require_container_isolation = True`, `require_pinned_image_digest = True`, `allow_host_subprocess_fallback = False`.
- **Approved Digest-Pinned Image Allowlist (`APPROVED_PRODUCTION_IMAGES`):**
  - `python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1`
- **Zero Silent Host Fallback:** Host subprocess execution (`python -m unittest` on the host OS) is strictly disabled in production.
  - If the `docker` CLI, the Docker daemon (`docker info`), or the local digest-pinned image (`docker image inspect`) is unavailable, execution fails closed immediately with `SandboxIsolationUnavailableError`.
  - If a caller supplies an unpinned image, a mutable tag (`:latest`), an unapproved digest, or attempts to enable `allow_host_subprocess_fallback=True` when `require_container_isolation=True`, policy validation fails closed immediately with `SandboxPolicyViolationError`.
- **Development-Only Tempdir Mode (`SandboxPolicy.dev_tempdir()`):**
  - `SandboxPolicy.dev_tempdir()` is restricted strictly to non-production local development and offline mocked unit tests. It must never be used to execute untrusted repository or model-generated code in production.

---

## 2. Hardened Container Runtime Flags & Shell-Free Execution

Every disposable container launched by `DisposableSandboxRunner.run_unittest_suite()` enforces:

- `--rm --name agi17-sbx-<uuid12>` (unique deterministic container name for lifecycle inspection and forced cleanup)
- `--network none` (complete network disablement inside the container)
- `--read-only` (immutable root filesystem)
- `--tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m` (bounded non-executable temporary scratch space)
- `--cap-drop ALL` and `--security-opt no-new-privileges`
- `--pids-limit 64`, `--memory 512m`, `--cpus 1.0`
- `--user 65534:65534` (unprivileged `nobody:nogroup` UID/GID)
- `--workdir /workspace` with `-v <staging_dir>:/workspace:rw`
- **Shell-Free `test_pattern` Execution (`shell=False`):**
  - `validate_test_pattern()` validates `test_pattern` against `^test[A-Za-z0-9_.*-]*\.py$` (max 64 characters, zero path separators or shell metacharacters) before staging or container launch (`InvalidTestPatternError`).
  - Container invocation executes `python3 -B -s -c <_CONTAINER_UNITTEST_BOOTSTRAP> <validated_pattern>` where `<validated_pattern>` is passed as a distinct `argv` element (`sys.argv[1]`) without `sh -c` interpolation.

---

## 3. Verified Container Termination & Staging Cleanup

In `DisposableSandboxRunner.run_unittest_suite()`:

1. On timeout (`subprocess.TimeoutExpired`) or abnormal exit, `_terminate_and_remove_container()` executes `docker kill <container_name>` and `docker rm -f <container_name>`.
2. In the `finally:` block, `_verify_container_removed()` executes `docker container inspect <container_name>` and verifies that the container no longer exists (`container_cleanup_verified = True`).
3. The temporary host staging directory is removed via `shutil.rmtree()` and checked via `not staging_dir.exists()` (`filesystem_cleanup_verified = True`).
4. Both `CIRepairAgent` and `HierarchicalOrchestrator` require `filesystem_cleanup_verified and container_cleanup_verified`; if either check fails, `SandboxCleanupUnverifiedError` is raised (`terminal_outcome = "BLOCKED_BY_POLICY"`).

---

## 4. Pre-Read Path Containment, Content Scanning & Approval Gates

1. **Pre-Read & Pre-Model Path Containment (`validate_relative_sandbox_path`):**
   - Validates `module_filename` and `test_filename` before reading any file or invoking any model call.
   - Rejects empty paths, absolute paths, Windows drive-qualified or UNC paths, `..` traversal, backslashes or traversal segments, NUL/control characters, Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`), and symlinks resolving outside the workspace root (`PathTraversalBlockedError` / `PathTraversalViolationError`).
2. **Untrusted Content & Prompt-Injection Scanner (`scan_untrusted_content`):**
   - Distinguishes prompt-injection strings in comments/docstrings (`warnings`, recorded in telemetry while keeping `safe=True`) from dangerous executable patterns (`blocked_reasons`, setting `safe=False` and raising `UntrustedContentBlockedError`):
     - Credential/secret file reads (`.env`, `.ssh`, `.aws`, `.gemini`, `id_rsa`)
     - Private/loopback/metadata SSRF (`169.254.169.254`, `127.0.0.1`, `localhost`)
     - Dangerous host process execution (`subprocess.*(..., shell=True)`, `os.system(...)`)
3. **High-Impact Approval Gate (`HighImpactApprovalGate`):**
   - A single shared `HighImpactApprovalGate` instance is wired from `AGI17Adapter` into both `HierarchicalOrchestrator` and `CIRepairAgent`.
   - Writing a repaired patch back to a user repository requires `apply_approved_patch=True` AND `approval_gate.check_workspace_mutation(...)`. By default (`apply_approved_patch=False`), `CIRepairAgent` stages the unified diff and PR payload without mutating the source file (`requires_human_approval=True`).
   - All approved workspace writes use `atomic_write_workspace_file()` (temp file + `flush()` + `os.fsync()` + `os.replace()`) with automatic rollback if post-write SHA-256 or sandbox regression verification fails.

---

## 5. Test Immutability & Mandatory Full-Suite Regression Verification

- **Test File Immutability:** During `CIRepairAgent` repair and `HierarchicalOrchestrator` Stage 4 self-healing, all existing `test_*.py` files are SHA-256 snapshotted before repair and verified byte-for-byte unchanged before completion. Any attempt to modify a test file during repair raises `HighImpactActionBlockedError`.
- **Two-Stage Regression Gate:** When a focused `test_pattern` (e.g. `test_focus.py`) passes after a candidate patch, `CIRepairAgent` automatically runs a second independent full-suite verification pass (`test_*.py`) inside a fresh disposable container and requires `regression_suite_passed = True` (`0` regressions across the entire repository test suite) before reporting `SUCCEEDED_AND_VERIFIED`.

---

## 6. Deterministic CLI Exit Codes (`0..6`) & Detached Execution Honesty

[`run_agi_17.py`](../agents/AGI_1_7/run_agi_17.py) maps every terminal outcome to a distinct process exit code (`TERMINAL_OUTCOME_EXIT_CODES`):

| Exit Code | Terminal Outcome(s) | Meaning |
| :-: | :--- | :--- |
| **`0`** | `SUCCEEDED_AND_VERIFIED`, `PROFILE_ONLY_OK`, `ALREADY_PASSING` | Mission succeeded with verified sandbox tests and artifact SHA-256 checks. |
| **`1`** | `FAILED` | Mission or repair failed verification. |
| **`2`** | `BLOCKED_BY_POLICY` | Blocked by sandbox policy, path containment, content scanner, approval gate, or cleanup verification. |
| **`3`** | `TIMED_OUT` | Mission, repair loop, or sandbox container exceeded its wall-clock timeout. |
| **`4`** | `CANCELLED` | Mission cancelled via `CommandInbox` or operator intervention. |
| **`5`** | `BUDGET_EXCEEDED` | Mission exceeded its cumulative token or USD cost ceiling. |
| **`6`** | `SUCCEEDED_UNVERIFIED` | Code or output generated without passing container verification. |

When launched with `--detach`, the parent launcher process reports `"status": "DETACHED_RUNNING"`, `"terminal_outcome": "DETACHED_LAUNCHED_UNVERIFIED"`, and `"mission_verified": false`, while the detached child process writes the final `status`, `terminal_outcome`, `mission_verified`, and `exit_code` to `<task_id>.pid.json` upon completion or failure.
