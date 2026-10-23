# AGI 1.7 OMEGA COMMAND — Phase 0 Baseline, Security & Credibility Audit

**Audit Date:** 2026-10-11  
**Target Branch:** `feat/production-hardening-sprint` (forked from `main` @ `5dc0e07`)  
**Repository:** `https://github.com/Abhishek200416/AGI-1.7V`

---

## 1. Current State Inventory

| Subsystem | Source Location | Verification Status | Real vs. Simulated Classification |
| :--- | :--- | :--- | :--- |
| **100-Specialist Registry & Ecosystem Coordinator** | `agents/AGI_1_7/ecosystem/agent_registry/` (`specialist_factory.py`, `capability_router.py`, `ecosystem_coordinator.py`) | Verified (Unit + Live E2E) | **Real**: 100 validated JSON specialist contracts across 16 families + 64 GSD skills + 6 Ponytail skills + 9 MCP bridges + 147 Agency profiles (326 total ecosystem capabilities). |
| **Hierarchical Orchestrator & Dynamic Concurrency** | `agents/AGI_1_7/engine/agi17/orchestration/` (`hierarchical_orchestrator.py`, `resource_governor.py`) | Verified (Unit + Live E2E) | **Real**: Topological DAG execution, context forwarding (`upstream_specialist_outputs`), disagreement detection (`DisagreementDetector`), and Win32 RAM/CPU headroom throttling (`MAX_ACTIVE_EXECUTIONS = 1..4`). |
| **14-State SQLite WAL Task Control & Live Inbox** | `agents/AGI_1_7/engine/agi17/task_control/` (`task_store.py`, `task_manager.py`, `command_inbox.py`, `checkpoint_manager.py`) | Verified (Unit + Crash Recovery) | **Real**: Durable SQLite WAL (`agi17_tasks.db`), append-only JSONL event log, SHA-256 checkpointing, and live mid-run command overrides (`ADD_CHILD_TASK`, `PAUSE_CURRENT_AND_SWITCH`, `CANCEL_AND_REPLACE`, `REPRIORITIZE`). |
| **Streaming Process Supervisor & Sandbox** | `agents/AGI_1_7/engine/agi17/process_supervision/` (`process_supervisor.py`, `completion_notifier.py`, `sandbox_runner.py`) | Hardened in Sprint | **Real**: Streaming stdout/stderr supervision, wall/idle timeout enforcement, SHA-256 artifact verification, and disposable Docker container sandbox (`--network none --cap-drop ALL --security-opt no-new-privileges`). |
| **10-Layer SQLite Memory & ACON Compression** | `agents/AGI_1_7/engine/agi17/memory/omega_command_memory.py` | Verified (Unit + E2E) | **Real**: SQLite WAL persistent memory with mandatory `retrieve_before_planning()`, deterministic fact supersession, and anchor-preserving `ACONCompressor`. |
| **Token Economy & Cost Controller** | `agents/AGI_1_7/engine/agi17/telemetry/token_economy.py` | Verified (Unit + Live E2E) | **Real**: Enforces per-call/child/task/campaign token ceilings, cumulative-to-delta normalization, isolated CWD execution, and explicit separation of `PROVIDER_REPORTED` vs `LOCAL_ESTIMATE` tokens. |
| **Model Integration (`ModelAdapter`)** | `agents/AGI_1_7/engine/agi17/adapters/model_adapter.py` | Hardened in Sprint | **Real + Explicit Offline Fallback**: Connects to `gemini-3.8-flash-high` (`effort=high`), enforces request/mission cost budgets, exponential backoff retries, rate limiting, and explicit `DETERMINISTIC_CONTRACT_FALLBACK` tagging when `live_model_enabled=False`. |
| **Focused Python CI-Repair Product** | `agents/AGI_1_7/engine/agi17/orchestration/ci_repair_agent.py` | Added in Sprint (Phase 7) | **Real**: End-to-end automated Python test-failure reproduction, minimal patch synthesis, sandboxed verification, quality checks, and human-approval PR payload generation. |

---

## 2. Security & Privacy Audit Findings

### 2.1 Secret & Credential Scan
- **Scope:** All `1,393` git-tracked files scanned against credential patterns (`AIza[0-9A-Za-z-_]{35}`, `sk-[A-Za-z0-9]{20,}`, `ghp_[A-Za-z0-9]{30,}`, `github_pat_`, `AKIA[0-9A-Z]{16}`, `BEGIN PRIVATE KEY`, `xox[baprs]-`).
- **Result:** **0 leaked secrets or API keys found.**
- **CLI Home Isolation Fix:** `ModelAdapter._ensure_minimal_cli_home()` was audited to ensure minimal CLI home configuration does not copy sensitive user credentials into committed workspace paths and redacts sensitive tokens from all stdout/stderr logs.

### 2.2 Local Filesystem Path & Username Redaction
- **Finding:** `7` Python files (`model_adapter.py`, `benchmark_auditor.py`, `completion_notifier.py`, `process_supervisor.py`, `progress_service.py`, `token_economy.py`, `evidence_verifier.py`) contained fallback paths referencing a local Windows user directory (`<USER_HOME>`), and `28` historical documentation/report files contained local absolute paths.
- **Remediation:**
  1. Replaced all hardcoded path defaults in the `7` Python modules with dynamic `Path(__file__).resolve().parents[...]` and `Path.home()` resolution.
  2. Redacted all local absolute paths across all `28` documentation and JSON report files (`<REPO_ROOT>` and `<USER_HOME>`).
  3. Added automated path & secret redaction (`redact_sensitive_text()`) to `ModelAdapter` and `DisposableSandboxRunner`.

### 2.3 Untrusted Code Execution & Prompt-Injection Defense
- **Finding:** Running model-generated code and tests directly via host `subprocess` exposes the host filesystem, environment variables, and network.
- **Remediation (Phase 3):** Implemented `DisposableSandboxRunner` (`sandbox_runner.py`), which executes generated Python code and `unittest` suites inside a disposable Docker container (`--rm --network none --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,exec,nosuid,size=64m --cpus 1.0 --memory 256m --pids-limit 64`) or an isolated restricted temporary directory with stripped environment variables (`PATH`, `SYSTEMROOT`, `PYTHONDONTWRITEBYTECODE` only), strict path-traversal rejection, prompt-injection/malicious-repo instruction scanning, and a `HighImpactApprovalGate` blocking destructive actions (`git push`, `rm -rf`, external network calls, secret access) without explicit human approval.

---

## 3. Credibility & Documentation Audit (Phase 1)

| Historical Claim / Issue | Audit Finding | Remediation Applied |
| :--- | :--- | :--- |
| Headline marketing claims (`99.93%` vs `99.64%`, `70/70 #1 Placements`) | Conflated internal deterministic architectural capability scores (`70` subsystem probes) with external academic benchmark pass rates. | Removed unsubstantiated superlatives from `README.md` and `TECHNICAL_ARCHITECTURE_AND_FAQ.md`; separated results into 5 explicit categories. |
| `189/189` GPQA Diamond Clean 1.2.2 claim | Historical `189/189` ledger relied on a pre-computed local verification table (`_SOLUTIONS` fallback) when offline, whereas cold-start strict surface-only live evaluation on `10` questions achieved `9/10` (`90.0%`). | Explicitly disclosed the cold-start live benchmark (`9/10 = 90.0%`, `163,054` provider-reported tokens) vs. historical cached/audited artifacts. |
| `-88.2%` Token Reduction headline | Measured specifically on single-shot isolated-CWD canary probe (`2,683` vs `22,728` input tokens by avoiding workspace prompt bloat), not across multi-turn coding loops where `AGI 1.7` uses more tokens than single-shot to repair failing code. | Qualified the `-88.2%` metric strictly as **per-call input context overhead reduction via `isolated_cwd`**, and explicitly reported that multi-agent test-and-repair consumes more total tokens than raw single-shot generation (`72,147` vs `32,126` tokens on the 3-task coding suite) in exchange for higher verified task completion (`66.67%` vs `0.0%`). |
| Missing Single-Agent Repair Baseline (`Config B`) | Previous coding benchmark only compared `Config A` (Raw Single-Shot) vs `Config C` (Full Multi-Agent Orchestration). | Added `Config B` (Single-Agent Code + Test + Repair Loop) to `run_heldout_coding_benchmark.py` so multi-agent orchestration overhead is measured against a fair single-agent repair baseline. |

---

## 4. Prioritized Remediation Roadmap (Phases 1–7)

1. **Phase 1 (Credibility, Claims & Licensing Cleanup):** Separate reporting into 5 transparent categories; publish `THIRD_PARTY_LICENSES_AND_PROVENANCE.md`.
2. **Phase 2 (Production Model Integration):** Typed `ModelRequest`/`ModelResponse`/`ModelProviderConfig`, `BaseModelProvider`, exponential backoff retries, rate limiting, cost ceilings (`max_cost_usd`), secret/path redaction, and deterministic mock provider for offline tests.
3. **Phase 3 (Secure Execution Sandbox):** `DisposableSandboxRunner` with Docker container isolation (`--network none`, `--cap-drop ALL`, `--read-only`, CPU/RAM/PID limits), path traversal guard, prompt-injection scanner, and `HighImpactApprovalGate`.
4. **Phase 4 (Reliable End-to-End Missions):** Wire `HierarchicalOrchestrator` code-verification loop through `DisposableSandboxRunner`, verify multi-agent disagreement detection and recovery.
5. **Phase 5 (Rigorous 3-Way Evaluation):** Evaluate `Config A` (Raw Single-Shot) vs `Config B` (Single-Agent Repair) vs `Config C` (Full Multi-Agent Orchestration) with pre-flight budget estimation and honest cost/latency/accuracy reporting.
6. **Phase 6 (Packaging, CI & Operations):** Add `pyproject.toml`, update `.github/workflows/agi17-ci.yml` (`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true`, separated offline vs live smoke suites), and publish `OPERATIONS_AND_DEPLOYMENT_GUIDE.md`.
7. **Phase 7 (Focused Product Workflow — Python CI-Repair Agent):** Ship `CIRepairAgent` (`ci_repair_agent.py`) + CLI support + `PRODUCT_SPEC_PYTHON_CI_REPAIR.md`.
