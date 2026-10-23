# AGI 1.7.0 — OMEGA COMMAND
## Final Engineering Release Dossier & Cross-Generation Comparison (AGI 1.5 vs AGI 1.6 vs AGI 1.7)

**Release Version:** `1.7.0` (`OMEGA COMMAND`)  
**Release Date:** 2026-10-10  
**Repository Root:** `<REPO_ROOT>` (`agents/AGI_1_7/`)  
**External Persistent Storage Root:** `D:\AGI_Storage\AGI_1_7\`  
**External Evaluation & Manifest Root:** `D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\`  
**Sole Foundation Model (Directive 0):** `gemini-3.8-flash-high` via `<USER_HOME>\AppData\Local\agy\bin\agy.exe`  
**Immutable Baselines Preserved:** `agents/AGI_1_5/` (`0` modified files) and `agents/AGI_1_6/` (`0` modified files)

---

## 1. Executive Release Summary

**AGI 1.7.0 — OMEGA COMMAND** completes the transformation of the repository's agent runtime into a resource-aware, persistent, self-orchestrating multi-agent operating system. Every architectural requirement from Parts I–XIV of the specification has been implemented in production Python code under [`agents/AGI_1_7/`](file:///<REPO_ROOT>/agents/AGI_1_7/) and verified through **46 automated tests (`24/24` Unit Tests, `15/15` Integration Tests A–O, and `7/7` Live End-to-End Demonstrations A–G)** plus a live non-scored calibration canary (`CANARY-ISO-1791638034`) and raw ledger reconciliation across **GPQA Diamond Clean 1.2.2**, **Terminal-Bench 2.0**, and **OSWorld-V2.1**.

---

## 2. Comprehensive Cross-Generation Comparison (AGI 1.5 vs AGI 1.6 vs AGI 1.7)

| Engineering Dimension | AGI 1.5 (`OMEGA EVOLUTION`) | AGI 1.6 (`OMEGA NEXUS`) | AGI 1.7 (`OMEGA COMMAND` — Verified Release) |
|---|---|---|---|
| **Source Root & Immutability** | `agents/AGI_1_5/` (Preserved immutable) | `agents/AGI_1_6/` (Preserved immutable) | `agents/AGI_1_7/` (Isolated versioned release) |
| **External Storage Root (`D:\`)** | `D:\AGI_Storage\` & `D:\AGI_Evaluation\AGI_1_5_FULL_BENCHMARKS\` | `D:\AGI_Storage\AGI_1_6\` & `D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\` | `D:\AGI_Storage\AGI_1_7\` & `D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\` |
| **Foundation Model (Directive 0)** | `gemini-3.8-flash-high` | `gemini-3.8-flash-high` | `gemini-3.8-flash-high` (`ModelAdapter` blocks any model/effort deviation via `DirectiveZeroViolationError`) |
| **Specialist Registry & Contracts** | Monolithic adapter | 9 string roles in `ROLE_REGISTRY`; no contracts or router | **100 validated specialist contracts across 16 families** ([`registry.json`](file:///<REPO_ROOT>/agents/AGI_1_7/ecosystem/agent_registry/registry.json)), `CapabilityRouter`, `SpecialistFactory` (`100/100` smoke-tested) |
| **Logical Child Capacity vs Active Concurrency** | Single-process sequential / static script pool | Static keyword list (`2–3` mocked roles); `max_concurrency = 4` | **`MAX_LOGICAL_CHILD_TASKS = 100`** per root mission; **`MAX_ACTIVE_EXECUTIONS` dynamically governed (`1..4`)** by live Win32 RAM/CPU headroom |
| **Task State Machine & Persistence** | In-memory JSON checkpoints | In-memory `SchedulerNode` dict (`PENDING/RUNNING/COMPLETED/FAILED`) | **14-state `TaskStateMachine`** backed by transactional SQLite WAL (`agi17_tasks.db`) + append-only `task_events.jsonl` |
| **Mid-Run Live Instruction Handling** | None | None (ignored new instructions until completion) | **`CommandInbox`** persists mid-run instructions and applies `ADD_CHILD_TASK`, `PAUSE_CURRENT_AND_SWITCH`, `CANCEL_AND_REPLACE`, and `REPRIORITIZE` at wave checkpoints |
| **Long-Running Process Supervision** | Blocking `subprocess.run()` | Blocking `subprocess.run()` without callbacks or artifact checks | **`ProcessSupervisor` + `StreamParser` + `CompletionNotifier`** streaming `%`/`n/m` progress, idle-output timeout detection, immediate parent callback, and SHA-256 artifact verification |
| **Cross-Session Persistent Memory** | JSONL strata | 9-layer JSONL (`store()` called on write; `retrieve()` never called before planning) | **10-layer SQLite WAL `OmegaCommandMemory`** with mandatory `retrieve_before_planning()`, retrieval audit log, fact supersession history, and anchor-preserving `ACONCompressor` |
| **Token Accounting & Workspace Isolation** | Provider JSON output | `estimate_tokens = len(text)//4` + hardcoded `0.848` (`84.8%`) ratio; ran GPQA in repo CWD (`45.7k` mean input tokens) | **`AdaptiveTokenController`** separating `PROVIDER_REPORTED` vs `LOCAL_ESTIMATE`, cumulative-to-delta turn normalization, hard budget gates, and isolated benchmark CWD (`D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\isolated_cwd`) |
| **GPQA Diamond Clean 1.2.2 Evidence** | Historical baseline | `174 / 189` (`92.06%` strict, `175` valid, `1` wrong, `14` timeouts, `8,164,321` tokens, `127.61s` mean latency) | Raw JSONL 100% reconciled (`SHA-256: 7a11033a...`); live isolated-CWD canary (`CANARY-ISO-1791638034`) completed in **1 turn (`19.10s` model duration, `22,747` total tokens, `258` output tokens)** |
| **Terminal-Bench 2.0 Evidence** | **`1 / 1` (`100.0%` verified Harbor container trial `chess-best-move__STsoVgt`, `reward.txt = 1.0`)** | Harbor trial `2026-10-10__13-22-32` incomplete (`finished_at: null`); local `run_terminal_bench_2.py` bypassed Harbor (`570` hardcoded tokens) | `BenchmarkAuditor` + `EvidenceVerifier` quarantine non-Harbor local scripts (`LOCAL_MOCK_EXECUTION_NOT_HARBOR_GRADED`) and enforce official `reward.txt` + `result.json` grading |
| **OSWorld-V2.1 Evidence** | `108` tasks audited; VM pending | `run_osworld_v2.py` scanned 108 JSONs in `0.21s` and claimed `108/108` with `64,800` hardcoded tokens | All **`369` task JSONs (`10` domains, `110` evaluator types)** audited; host GUI actuation blocked (`host_gui_actuation_allowed = false`); background VM download (`PID 20556`, `PID 22884`) preserved undisturbed |
| **Automated Verification Suite** | Ad-hoc scripts | 7 unit test files | **`46 / 46` Automated Tests (`24` Unit + `15` Integration A–O + `7` Live E2E Demos A–G)** |

---

## 3. Complete Deliverables & File Inventory

### 3.1 Runtime & Control Plane (`agents/AGI_1_7/`)
- **Entrypoints & CLI:**
  - [`run_agi_17.py`](file:///<REPO_ROOT>/agents/AGI_1_7/run_agi_17.py)
  - [`run_agent.ps1`](file:///<REPO_ROOT>/agents/AGI_1_7/run_agent.ps1) & [`run_agent.bat`](file:///<REPO_ROOT>/agents/AGI_1_7/run_agent.bat)
  - [`scripts/agi17ctl.py`](file:///<REPO_ROOT>/agents/AGI_1_7/scripts/agi17ctl.py)
  - [`scripts/run_benchmark_verification.py`](file:///<REPO_ROOT>/agents/AGI_1_7/scripts/run_benchmark_verification.py)
- **Configuration Policies (`agents/AGI_1_7/config/agi17/`):**
  - [`runtime_profile.json`](file:///<REPO_ROOT>/agents/AGI_1_7/config/agi17/runtime_profile.json)
  - [`resource_policy.json`](file:///<REPO_ROOT>/agents/AGI_1_7/config/agi17/resource_policy.json)
  - [`token_budget_policy.json`](file:///<REPO_ROOT>/agents/AGI_1_7/config/agi17/token_budget_policy.json)
  - [`permissions_policy.json`](file:///<REPO_ROOT>/agents/AGI_1_7/config/agi17/permissions_policy.json)
  - [`benchmark_manifest.json`](file:///<REPO_ROOT>/agents/AGI_1_7/config/agi17/benchmark_manifest.json)
- **100-Specialist Ecosystem (`agents/AGI_1_7/ecosystem/agent_registry/`):**
  - [`agent_contract.py`](file:///<REPO_ROOT>/agents/AGI_1_7/ecosystem/agent_registry/agent_contract.py)
  - [`registry_validator.py`](file:///<REPO_ROOT>/agents/AGI_1_7/ecosystem/agent_registry/registry_validator.py)
  - [`capability_router.py`](file:///<REPO_ROOT>/agents/AGI_1_7/ecosystem/agent_registry/capability_router.py)
  - [`specialist_factory.py`](file:///<REPO_ROOT>/agents/AGI_1_7/ecosystem/agent_registry/specialist_factory.py)
  - [`registry.json`](file:///<REPO_ROOT>/agents/AGI_1_7/ecosystem/agent_registry/registry.json)
- **Core Engine (`agents/AGI_1_7/engine/agi17/`):**
  - Capabilities: [`resource_snapshot.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/capabilities/resource_snapshot.py), [`capability_profiler.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/capabilities/capability_profiler.py)
  - Task Control: [`task_state_machine.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/task_control/task_state_machine.py), [`task_store.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/task_control/task_store.py), [`checkpoint_manager.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/task_control/checkpoint_manager.py), [`dependency_manager.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/task_control/dependency_manager.py), [`task_manager.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/task_control/task_manager.py)
  - Process Supervision: [`stream_parser.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/process_supervision/stream_parser.py), [`completion_notifier.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/process_supervision/completion_notifier.py), [`recovery_manager.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/process_supervision/recovery_manager.py), [`process_supervisor.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/process_supervision/process_supervisor.py)
  - Persistent Memory: [`omega_command_memory.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/memory/omega_command_memory.py)
  - Orchestration & Resource Governance: [`resource_governor.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/orchestration/resource_governor.py), [`hierarchical_orchestrator.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/orchestration/hierarchical_orchestrator.py)
  - Telemetry & Token Economy: [`token_economy.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/telemetry/token_economy.py), [`progress_service.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/telemetry/progress_service.py)
  - Verification, Research, Evaluation & Adapters: [`evidence_verifier.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/verification/evidence_verifier.py), [`grounded_research.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/research/grounded_research.py), [`benchmark_auditor.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/evaluation/benchmark_auditor.py), [`model_adapter.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/adapters/model_adapter.py), [`agi_17_adapter.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/adapters/agi_17_adapter.py)

### 3.2 Engineering Reports & Specifications (`agents/AGI_1_7/reports/` & `docs/`)
1. [`AGI_1_7_BASELINE_AUDIT.md`](file:///<REPO_ROOT>/docs/AGI_1_7_BASELINE_AUDIT.md)
2. [`AGI_1_7_RESEARCH_REGISTER.md`](file:///<REPO_ROOT>/docs/AGI_1_7_RESEARCH_REGISTER.md)
3. [`AGI_1_7_FRAMEWORK_COMPARISON.md`](file:///<REPO_ROOT>/docs/AGI_1_7_FRAMEWORK_COMPARISON.md)
4. [`AGI_1_7_RESEARCH_TO_REQUIREMENTS.md`](file:///<REPO_ROOT>/docs/AGI_1_7_RESEARCH_TO_REQUIREMENTS.md)
5. [`AGI_1_7_ARCHITECTURE_SPEC.md`](file:///<REPO_ROOT>/agents/AGI_1_7/reports/AGI_1_7_ARCHITECTURE_SPEC.md)
6. [`AGI_1_7_PDR_AND_RESOURCE_PLAN.md`](file:///<REPO_ROOT>/agents/AGI_1_7/reports/AGI_1_7_PDR_AND_RESOURCE_PLAN.md)
7. [`AGI_1_7_CAPABILITY_PROFILE.md`](file:///<REPO_ROOT>/agents/AGI_1_7/reports/AGI_1_7_CAPABILITY_PROFILE.md)
8. [`AGI_1_7_PHASE2_STATE_RECONCILIATION.md`](file:///<REPO_ROOT>/agents/AGI_1_7/reports/AGI_1_7_PHASE2_STATE_RECONCILIATION.md)
9. [`AGI_1_7_PHASE2_TEST_REPORT.md`](file:///<REPO_ROOT>/agents/AGI_1_7/reports/AGI_1_7_PHASE2_TEST_REPORT.md)
10. [`AGI_1_7_GPQA_CLEAN_189_REPORT.md`](file:///<REPO_ROOT>/agents/AGI_1_7/reports/AGI_1_7_GPQA_CLEAN_189_REPORT.md)
11. [`AGI_1_7_TERMINAL_BENCH_2_REPORT.md`](file:///<REPO_ROOT>/agents/AGI_1_7/reports/AGI_1_7_TERMINAL_BENCH_2_REPORT.md)
12. [`AGI_1_7_OSWORLD_V2_1_REPORT.md`](file:///<REPO_ROOT>/agents/AGI_1_7/reports/AGI_1_7_OSWORLD_V2_1_REPORT.md)
13. [`AGI_1_7_VERIFICATION_MATRIX.md`](file:///<REPO_ROOT>/agents/AGI_1_7/reports/AGI_1_7_VERIFICATION_MATRIX.md)
14. [`AGI_1_7_FINAL_RELEASE_DOSSIER.md`](file:///<REPO_ROOT>/agents/AGI_1_7/reports/AGI_1_7_FINAL_RELEASE_DOSSIER.md)

### 3.3 Authoritative External Persistence Artifacts (`D:\`)
- [`latest_capability_profile.json`](file:///D:/AGI_Storage/AGI_1_7/telemetry/latest_capability_profile.json)
- [`agi17_tasks.db`](file:///D:/AGI_Storage/AGI_1_7/state/agi17_tasks.db) & [`task_events.jsonl`](file:///D:/AGI_Storage/AGI_1_7/state/task_events.jsonl)
- [`omega_memory.db`](file:///D:/AGI_Storage/AGI_1_7/memory/omega_memory.db)
- [`token_usage_ledger.jsonl`](file:///D:/AGI_Storage/AGI_1_7/token_ledger/token_usage_ledger.jsonl)
- [`live_telemetry.json`](file:///D:/AGI_Storage/AGI_1_7/telemetry/live_telemetry.json) & [`omega_command_dashboard.html`](file:///D:/AGI_Storage/AGI_1_7/telemetry/omega_command_dashboard.html)
- [`isolated_cwd_canary_result.json`](file:///D:/AGI_Evaluation/AGI_1_7_OMEGA_COMMAND/canary/isolated_cwd_canary_result.json)
- [`agi17_benchmark_reconciliation.json`](file:///D:/AGI_Evaluation/AGI_1_7_OMEGA_COMMAND/normalized_results/agi17_benchmark_reconciliation.json)
- [`e2e_demonstrations_summary.json`](file:///D:/AGI_Evaluation/AGI_1_7_OMEGA_COMMAND/reports/e2e_demonstrations_summary.json)
- [`MANIFEST-AGI17-1791638072.json`](file:///D:/AGI_Evaluation/AGI_1_7_OMEGA_COMMAND/manifests/MANIFEST-AGI17-1791638072.json)
