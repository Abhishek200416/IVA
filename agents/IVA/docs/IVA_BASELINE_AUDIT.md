# AGI 1.7 — OMEGA COMMAND: Source-Level Baseline Audit of AGI 1.6 & AGI 1.5

**Audit ID:** `AUDIT-AGI17-PHASE0-20261010`  
**Audit Timestamp:** `2026-10-10T18:14:30+05:30` (`2026-10-10T12:44:30Z`)  
**Repository Root:** `<REPO_ROOT>`  
**Git Remote:** `origin https://github.com/Abhishek200416/AGI-1.6V.git`  
**Active Branch & Commit:** `main` @ `06390fa` (`docs(agi16): add comprehensive flagship README detailing 76 subagents, 74 GSD skills, 11 plugins, 21 MCPs, comparisons, and capabilities`)  
**Tracked Modifications:** `0` modified tracked files (clean baseline preserved). Untracked root scratch files left untouched.  
**Active External Processes Preserved:**
- PID `20556` (`<REPO_ROOT>\.venv\Scripts\python.exe -u D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\OSWorld-V2\scripts\download_and_verify_vm.py`, 5.1 MB RAM, 0.0s CPU)
- PID `22884` (`<USER_HOME>\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\python.exe -u D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\OSWorld-V2\scripts\download_and_verify_vm.py`, 31.7 MB RAM, 0.66s CPU)
- Both processes are preserved without termination or interference and accounted for in host resource headroom.

---

## 1. Executive Summary of Baseline State

An exhaustive source-level inspection of `agents/AGI_1_6/`, `agents/AGI_1_5/`, `scripts/`, and `D:\AGI_Evaluation\` confirms that while AGI 1.6 OMEGA NEXUS established a clean directory structure, 9-layer memory schema, and a completed 189-question GPQA Diamond Clean 1.2.2 run (`174/189 = 92.06%`), **several core runtime subsystems in `agents/AGI_1_6/engine/agi/` rely on stubbed in-memory methods, hardcoded telemetry values, synchronous blocking subprocesses, and unintegrated memory retrieval**.

In accordance with Mission Rule 1, `agents/AGI_1_5/` and `agents/AGI_1_6/` (along with `D:\AGI_Storage\AGI_1_6\` and `D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\`) are preserved as immutable comparison baselines. All AGI 1.7 engineering is isolated under `agents/AGI_1_7/`, `D:\AGI_Storage\AGI_1_7\`, and `D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\`.

---

## 2. Source-Level Root-Cause Analysis (10 Confirmed Defects)

### Defect 1: Fails to create real child agents automatically for substantial tasks
- **Status:** **PROVEN DEFECT**
- **Source Locations:**
  - `agents/AGI_1_6/engine/agi/orchestration/omega_nexus_orchestrator.py` lines `127–207` (`WorkerInstance.execute`) and lines `281–366` (`OmegaNexusOrchestrator.plan_and_execute_task`)
  - `agents/AGI_1_6/engine/agi/adapters/agi_16_adapter.py` lines `102–130` (`AGI16OmegaNexusAgent.execute_mission`)
- **Root Cause:**
  1. `OmegaNexusOrchestrator.spawn_worker()` instantiates an in-memory `WorkerInstance` object whose `_run_planner()`, `_run_research()`, `_run_coding()`, `_run_terminal()`, and `_run_verifier()` methods (lines `174–206`) return **static hardcoded dictionaries** (e.g., `return {"file_modified": target_file, "diff_lines": 12, "ast_verified": True}`, `return {"command": cmd, "exit_code": 0, "stdout": "OK"}`) without invoking any LLM, CLI subprocess, or tool adapter.
  2. Although `select_embedded_specialists(goal)` (lines `246–271`) maps keywords to subagent names from `ecosystem/ecosystem_manifest.json`, `plan_and_execute_task()` **never calls `select_embedded_specialists()`** and never dispatches child tasks to a task store or execution adapter.

### Defect 2: Continues an earlier task or ignores live instructions when an additional instruction is supplied
- **Status:** **PROVEN DEFECT**
- **Source Locations:**
  - `agents/AGI_1_6/engine/agi/adapters/agi_16_adapter.py` lines `102–130`
  - `agents/AGI_1_6/engine/agi/orchestration/omega_nexus_orchestrator.py` lines `88–108` (`AgentMessageBus`)
- **Root Cause:**
  1. `AgentMessageBus` (lines `88–108`) is purely an in-memory Python list (`self.messages: List[AgentMessage] = []`) scoped to a single process invocation. It has zero persistence on disk/SQLite and zero external intake interface.
  2. There is no `CommandInbox` service, no CLI control endpoint (`agi17ctl`), and no checkpoint polling loop during long campaigns (`scripts/execute_benchmark_campaign.py` runs an uninterrupted `for b_start in range(...)` loop on lines `248–334` without checking any command inbox).

### Defect 3: Fails to recognize or incorporate a task that is a child of an existing job
- **Status:** **PROVEN DEFECT**
- **Source Locations:**
  - `agents/AGI_1_6/engine/agi/orchestration/adaptive_execution_scheduler.py` lines `23–43` (`TaskNode`) and `109–175` (`execute_dag`)
  - `agents/AGI_1_6/engine/agi/orchestration/omega_nexus_orchestrator.py` lines `40–47` (`TaskStatus`)
- **Root Cause:**
  1. `TaskNode` (lines `23–43`) has no `parent_job_id`, `parent_task_id`, `campaign_id`, or persistent state store. Once `execute_dag()` starts (line `109`), `task_nodes` is a fixed Python list in memory; dynamically arriving child tasks cannot be attached to a running parent job or persisted across restarts.

### Defect 4: Appears to finish a terminal command without returning the final outcome to its parent
- **Status:** **PROVEN DEFECT**
- **Source Locations:**
  - `agents/AGI_1_6/engine/agi/adapters/terminal_execution_adapter.py` lines `28–93` (`execute_command`)
  - `D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\campaigns\CAMPAIGN-20261010-1306\AGI_1_6\Terminal_Bench_2\jobs\2026-10-10__13-22-32\result.json` lines `1–20`
- **Root Cause:**
  1. `TerminalExecutionAdapter.execute_command()` uses blocking `subprocess.run(..., capture_output=True)` with no persistent process registry, no completion event emitter, and no parent callback.
  2. When a background job or Harbor trial (`jobs/2026-10-10__13-22-32/result.json`) is interrupted or finishes asynchronously, `"finished_at": null` and `"n_running_trials": 1` remain stale because no `ProcessSupervisor` reconciles live OS PIDs with the task ledger or publishes a terminal completion event to the parent.

### Defect 5: Makes manual status checks necessary after a long download or execution step
- **Status:** **PROVEN DEFECT**
- **Source Locations:**
  - `D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\OSWorld-V2\scripts\download_and_verify_vm.py` lines `67–163` and `227–371`
  - `agents/AGI_1_6/engine/agi/adapters/terminal_execution_adapter.py` lines `28–66`
- **Root Cause:**
  1. Long-running scripts (`download_and_verify_vm.py`, `execute_benchmark_campaign.py`) print progress lines only to their own stdout (`print(..., flush=True)`), without writing structured heartbeat events or completion notifications to a shared transactional task ledger (`SQLite` / `JSONL` event bus).
  2. Furthermore, `download_and_verify_vm.py` spawned two background instances (PIDs `20556` and `22884`) without an idempotency lock or parent completion notifier.

### Defect 6: Creates or writes memory without consistently using it in a fresh session
- **Status:** **PROVEN DEFECT**
- **Source Locations:**
  - `agents/AGI_1_6/engine/agi/adapters/agi_16_adapter.py` lines `96–100` and `102–130`
  - `agents/AGI_1_6/engine/agi/orchestration/omega_nexus_orchestrator.py` lines `281–366`
  - `agents/AGI_1_6/engine/agi/memory/omega_nexus_memory.py` lines `177–241`
- **Root Cause:**
  1. In `agi_16_adapter.py`, `self.memory.write_record()` is called once inside `__init__` (line `96`) and `self.memory.flush_to_disk()` is called at the end of `execute_mission()` (line `118`).
  2. **`self.memory.retrieve()` is never called anywhere in `agi_16_adapter.py` or `omega_nexus_orchestrator.py`!** Only the unit test (`tests/test_agi_16_core_suite.py` line `104`) ever calls `mem.retrieve()`.
  3. Additionally, `OmegaNexusMemory.write_record()` (lines `177–203`) blindly appends to `self.layers[layer.value]` without fact key indexing, version supersession (`supersedes_id`), or conflict detection.

### Defect 7: GPQA consumed 8,164,321 reported tokens and left 14 questions unanswered through timeouts
- **Status:** **PROVEN DEFECT (Reconciled against Raw Telemetry)**
- **Source Locations:**
  - `scripts/execute_benchmark_campaign.py` lines `23–30` and `116`
  - `agents/AGI_1_6/engine/agi/adapters/agi_agent_adapter.py` lines `66–125` (`call_model_gemini_38_flash_high`)
  - Raw telemetry: `D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\raw_results\gpqa_clean_189_task_results.jsonl` (189 records)
- **Root Cause (Verified Mathematically from Raw Records):**
  1. **Reconciliation of Raw GPQA Records:**
     - Total records in `gpqa_clean_189_task_results.jsonl`: **189 unique questions** (`c04c551a71da14d802841ec1a5dd3aa83fbcbe22e89b4cd6c6aef3c690c00e8d`).
     - Correct answers: **174 / 189 (92.06% strict accuracy)**.
     - Valid answered: **175 / 189 (99.43% answered accuracy)**; 1 incorrect (`recwW1A85nfyQpReG`, index 183); 14 timeouts (`error_category: "TIMEOUT"`).
     - Exact sum of `input_tokens`: **7,390,798**; `output_tokens`: **773,523**; `total_tokens`: **8,164,321** (`7,390,798 + 773,523 = 8,164,321`). `thinking_tokens`: **528,871** (already included inside `output_tokens`, not double-counted in `total_tokens`).
     - Mean latency: **127,609.3 ms (127.61s)**; Median (p50): **97,924 ms (97.92s)**; p95: **329,949 ms (329.95s)**; Sum of subprocess durations: **24,118.2s**.
  2. **Why Input Tokens Exploded to 7.39M (p50 = 30,626, p90 = 91,604, max = 219,095):**
     - In `scripts/run_gpqa_diamond_clean_189.py` (lines `21–22`), `os.environ["AGI_ISOLATED_CWD"] = r"D:\AGI_Evaluation\AGI_1_5_FULL_BENCHMARKS\preflight"` was set. For the **17 questions** evaluated under that isolated working directory, `input_tokens` was only **2,223 to 2,345 tokens** (e.g., item 4 `rec1zl5LvaatzGhFt` used `2,256` input tokens and finished in `29.4s`)!
     - However, when `scripts/execute_benchmark_campaign.py` was written (lines `23–30`), **`AGI_ISOLATED_CWD` was omitted!** Consequently, `cwd=os.environ.get("AGI_ISOLATED_CWD")` in `agi_agent_adapter.py:90` passed `cwd=None`, causing `agy.exe` to execute inside `<REPO_ROOT>`.
     - Running `agy.exe` inside the repository root caused the CLI to load the entire repository context, skills, rules, and MCP schemas (**~22,700 input tokens on Turn 1**).
     - Worse still, because `--dangerously-skip-permissions` was enabled without forbidding tool invocation in the prompt, `agy.exe` frequently executed multi-turn internal tool/thinking loops per question, where `usage.input_tokens` in `agy.exe --output-format json` accumulates across turns (`Turn 1: ~22.7k + Turn 2: ~25k + Turn 3: ~28k = ~75k–219k input tokens`!).
     - Moreover, failed timed-out subprocesses (`subprocess.TimeoutExpired` in `agi_agent_adapter.py:126–136`) recorded `tokens: 0` because `agy.exe` killed on timeout did not emit its final JSON object, even though those 14 timed-out runs consumed server-side tokens before timing out at 180s–360s.

### Defect 8: Parallel execution did not eliminate the long tail of CLI subprocess timeouts
- **Status:** **PROVEN DEFECT**
- **Source Locations:**
  - `scripts/execute_benchmark_campaign.py` lines `167` and `265` (`ThreadPoolExecutor(max_workers=5)`)
  - `agents/AGI_1_6/engine/agi/orchestration/adaptive_execution_scheduler.py` lines `80–107`
- **Root Cause:**
  1. `execute_benchmark_campaign.py` bypassed `AdaptiveExecutionScheduler` entirely and ran two bidirectional processes (`FORWARD` and `REVERSE`) each with `max_workers=5` (`10` simultaneous `agy.exe` Node/CLI processes), each loading 22k+ workspace tokens on a host with only ~2.3–2.9 GB free physical RAM.
  2. Even inside `AdaptiveExecutionScheduler.get_resource_headroom()` (line `96`), `"cpu_percent": 25.0` was **hardcoded**, and `max_configured_workers` defaulted to `16` regardless of CPU saturation, commit charge, or API rate limits.

### Defect 9: Advertises 76 specialist subagents without proving runtime invocation for all roles
- **Status:** **PROVEN DEFECT**
- **Source Locations:**
  - `agents/AGI_1_6/ecosystem/ecosystem_manifest.json` lines `1–89`
  - `agents/AGI_1_6/engine/agi/orchestration/omega_nexus_orchestrator.py` lines `28–38` and `225–271`
- **Root Cause:**
  1. `ecosystem_manifest.json` lists 76 subagent string names (`"accessibility-engineer"`, ..., `"web-research-agent"`), while `AgentRole` enum in `omega_nexus_orchestrator.py` (lines `28–38`) only defines 9 generic roles (`PLANNER`, `RESEARCH`, `EXECUTION`, `CODING`, `TERMINAL`, `COMPUTER_USE`, `MEMORY`, `VERIFIER`, `COORDINATOR`).
  2. None of the 76 names in `ecosystem_manifest.json` had operational contracts (input/output schemas, tool permissions, budgets, timeouts, verification policies) or an execution router binding them to callable worker templates.

### Defect 10: Dashboard and token-efficiency claims are hardcoded rather than derived from raw telemetry
- **Status:** **PROVEN DEFECT**
- **Source Locations:**
  - `agents/AGI_1_6/reports/AGI_1_6_BENCHMARK_DASHBOARD.html` lines `137`, `179`, `218`, `223`
  - `agents/AGI_1_6/engine/agi/orchestration/omega_nexus_orchestrator.py` lines `298`, `315`, `318`, `339`, `342`, `345`, `348`
  - `agents/AGI_1_6/scripts/run_terminal_bench_2.py` lines `48–56`
- **Root Cause:**
  1. `AGI_1_6_BENCHMARK_DASHBOARD.html` contains static literal arrays (`data: [4500, 12000, 48000, 570]`, `data: [500, 1650, 8200, 570]`, `-84.8%`) rather than reading from `token_ledger.jsonl` or `normalized_results/`.
  2. `OmegaNexusOrchestrator.plan_and_execute_task()` records synthetic token numbers (`350, 150`, `800, 300`, `1200, 400`) instead of real provider telemetry.
  3. `agents/AGI_1_6/scripts/run_terminal_bench_2.py` (line `48`) ran `python -c "print('d2d4')"` locally and recorded hardcoded `input_tokens=450, output_tokens=120` instead of reading the real Harbor job state (`D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\campaigns\CAMPAIGN-20261010-1306\AGI_1_6\Terminal_Bench_2\jobs\2026-10-10__13-22-32\result.json`).

---

## 3. Component Reuse vs. Replacement Plan for AGI 1.7

| Subsystem | AGI 1.6 Baseline State | AGI 1.7 OMEGA COMMAND Action |
|---|---|---|
| **Model Adapter (`agi_agent_adapter.py`)** | Invokes `agy.exe --model gemini-3.8-flash-high --output-format json`, scrubs secrets, parses usage | **REPAIR & UPGRADE:** Enforce mandatory isolated `cwd` (`D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\isolated_cwd`) for closed-book calls so workspace context is never leaked (~90% input token drop from 22.7k to ~2.2k), add `--output-format stream-json` streaming support, normalize cumulative vs per-call usage, and track failed-call elapsed resource burn. |
| **Capability Profiler (`device_discovery.py`)** | Basic OS/Drive/PnP inspection; hardcoded timestamp | **REPLACE with `CapabilityProfiler` & `ResourceSnapshot`:** Live Win32 `GlobalMemoryStatusEx`, CPU load sampling via `GetSystemTimes`, GPU VRAM (dedicated vs shared via WMI/DXGI), Disk I/O & D:\ checksum verification, Docker/WSL limits, active process accounting, and explicit `UNAVAILABLE`/`UNKNOWN` markers. |
| **Resource Governor (`adaptive_execution_scheduler.py`)** | Hardcoded `cpu_percent: 25.0`, single RAM threshold | **REPLACE with `ResourceGovernor` & `AdaptiveExecutionScheduler`:** Separate `MAX_AGENT_SPECIALIZATIONS=100`, `MAX_LOGICAL_CHILD_TASKS=100`, and dynamic `MAX_ACTIVE_EXECUTIONS`; multi-queue admission control (`current + new <= safe_capacity`), hysteresis, and backpressure. |
| **Task Control & Command Inbox** | Non-existent (in-memory list only) | **BUILD NEW (`engine/agi17/task_control/`):** SQLite WAL transactional task store + append-only JSONL event log, 14-state machine, durable `CommandInbox` + `agi17ctl` CLI/loopback control interface supporting live mid-run instructions. |
| **Process Supervision (`terminal_execution_adapter.py`)** | Blocking `subprocess.run` | **BUILD NEW (`engine/agi17/process_supervision/`):** Streaming `Popen` supervisor with live stdout/stderr capture, heartbeats, Windows Job/process-tree termination, artifact verification, and automatic parent completion notification. |
| **Persistent Memory (`omega_nexus_memory.py`)** | 9 layers, never called during planning, no fact supersession | **UPGRADE to 10-Layer SQLite+WAL Memory Service:** Mandatory `retrieve_before_planning()` hook in orchestrator, fact key supersession & conflict audit history, ACON compression preserving exact IDs/hashes/errors, and cross-session restart verification. |
| **Specialist Registry (`ecosystem_manifest.json`)** | 76 unvalidated names, 9 stubbed roles | **BUILD 100-Specialist Registry (`ecosystem/agent_registry/`):** 100 distinct specialist contracts across 16 families with schemas, tool permissions, budgets, and real callable execution templates. |
| **Observability & Dashboard** | Hardcoded static HTML numbers | **BUILD Result-Driven Progress Service & Dashboard:** Derives 100% of metrics from SQLite task ledger, raw benchmark JSONL files, and live resource snapshots; explicitly marks `UNAVAILABLE` metrics. |
