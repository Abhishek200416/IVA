# AGI 1.7 OMEGA COMMAND — Operations, Deployment & Incident Response Guide (Phase 8)

* **Primary Runtime Entrypoint:** [`agents/AGI_1_7/run_agi_17.py`](../run_agi_17.py)
* **Focused CI-Repair Agent:** [`agents/AGI_1_7/engine/agi17/orchestration/ci_repair_agent.py`](../engine/agi17/orchestration/ci_repair_agent.py)
* **Sandbox Security Engine:** [`agents/AGI_1_7/engine/agi17/process_supervision/sandbox_runner.py`](../engine/agi17/process_supervision/sandbox_runner.py)
* **Supported Platforms & Runtimes:** Linux (`ubuntu-latest`) and Windows (`windows-latest`), Python `>=3.10` (tested on Python `3.12` in GitHub Actions and Python `3.14` locally). Zero third-party PyPI runtime dependencies required.

---

## 1. Reproducible Installation & Readiness Verification

```bash
# 1. Clone repository and checkout the hardened release branch
git clone https://github.com/Abhishek200416/AGI-1.7V.git
cd AGI-1.7V
git checkout feat/production-hardening-sprint

# 2. Install in editable mode (PEP 621 pyproject.toml, 0 external PyPI packages required)
python -m pip install -e .

# 3. Pull the approved, digest-pinned Python 3.12 sandbox container image
docker pull python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

# 4. Run startup health, capability profile, and crash-reconciliation check (must exit 0)
python agents/AGI_1_7/run_agi_17.py --profile-only
```

---

## 2. Environment Variables & Configuration Defaults

| Parameter / CLI Flag | Default Value | Purpose & Security Boundary |
| :--- | :--- | :--- |
| `--storage-root` | `D:\AGI_Storage\AGI_1_7` (falls back to `agents/AGI_1_7/runtime_storage`) | SQLite WAL task database (`agi17_tasks.db`), append-only event log (`task_events.jsonl`), checkpoints, and 10-layer persistent memory (`omega_memory.db`). |
| `--ci-repair-dir` | `None` | Target workspace directory for `CIRepairAgent` reproduction, minimal patching, and sandboxed verification. |
| `--apply-approved-patch` | `False` (staged only) | When omitted, candidate patches are verified inside `DisposableSandboxRunner` and emitted as a unified diff without mutating the working tree. When passed, atomically writes the verified patch via `atomic_write_workspace_file()`. |
| `SandboxPolicy.production()` | `isolation_mode="docker"`, `require_container_isolation=True`, `require_pinned_image_digest=True` | Fail-closed container policy pinned to `python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1` (`--network none --user 65534:65534 --cap-drop ALL --security-opt no-new-privileges --read-only`). |
| `ModelProviderConfig` | `max_request_cost_usd=0.05`, `max_mission_cost_usd=0.25`, `max_retries=2` | Enforces per-call and cumulative mission USD cost ceilings across all specialists and retries (`ModelCostBudgetExceededError`). |

---

## 3. CLI Exit-Code Contract (`compute_cli_exit_code`)

[`run_agi_17.py`](../run_agi_17.py) enforces a deterministic, machine-verifiable exit-code contract across all 7 terminal outcomes:

| Terminal Outcome | Process Exit Code | Meaning |
| :--- | :---: | :--- |
| `SUCCEEDED_AND_VERIFIED` / `ALREADY_PASSING` / `PROFILE_ONLY_OK` | **`0`** | All unit tests and verification hooks passed in isolation with zero deterministic fallbacks. |
| `FAILED` | **`1`** | Execution or unit-test verification failed after bounded repair attempts. |
| `SUCCEEDED_UNVERIFIED` | **`2`** | Task completed text/analysis output without independent executable test verification (or used deterministic fallback). |
| `TIMED_OUT` | **`3`** | Subprocess or model call exceeded wall-clock or idle timeout ceiling. |
| `CANCELLED` | **`4`** | Mission cancelled via `CommandInbox` (`CANCEL_AND_REPLACE`) or user interruption. |
| `BUDGET_EXCEEDED` | **`5`** | Request or mission exceeded configured token or USD cost ceiling (`ModelCostBudgetExceededError`). |
| `BLOCKED_BY_POLICY` | **`6`** | Blocked by `SandboxIsolationUnavailableError`, `PathTraversalViolationError`, `UntrustedContentSecurityError`, `HighImpactActionBlockedError`, or `DirectiveZeroViolationError`. |

---

## 4. Crash Recovery, Backup, Rollback & Troubleshooting

1. **Automatic Crash & Restart Reconciliation (`reconcile_after_restart()`):**
   - On startup, [`DurableTaskManager.reconcile_after_restart()`](../engine/agi17/task_control/task_manager.py) inspects all tasks in `RUNNING` state, checks whether their OS PID is still alive, verifies the SHA-256 integrity of their latest checkpoint (`chk_<task_id>.json`), requeues intact tasks to `READY`, and quarantines tasks with corrupted/incomplete checkpoints as `MARKED_INTERRUPTED_CORRUPTED_CHECKPOINT`.
   - Reconciliation is strictly idempotent (`test_20_corrupted_checkpoint_and_repeated_reconcile_idempotency`).
2. **Database Backup & Recovery:**
   - SQLite databases (`agi17_tasks.db`, `omega_memory.db`) run in `WAL` mode (`PRAGMA journal_mode=WAL;`). Back up using `sqlite3 agi17_tasks.db ".backup 'agi17_tasks.backup.db'"` alongside `task_events.jsonl`.
3. **Rollback Procedure:**
   - Because `CIRepairAgent` stages patches in memory/diff output by default (`write_patch_to_workspace=False`), unapproved runs make zero modifications to the target repository.
   - To roll back an approved patch (`--apply-approved-patch`), run `git checkout -- <module_filename>` or `git revert <commit_sha>`.
4. **Security Incident Response & Credential Rotation:**
   - All model prompts, stdout/stderr logs, and JSON reports pass through [`redact_sensitive_text()`](../engine/agi17/adapters/model_adapter.py).
   - If a secret is ever suspected of exposure in a workspace, immediately revoke/rotate the credential at the provider, purge the local `runtime_storage/logs/` directory, and run `python -m unittest agents/AGI_1_7/tests/test_production_hardening_sprint.py -k test_01` to verify zero tracked leaks.
