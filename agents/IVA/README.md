# AGI 1.7.0 — OMEGA COMMAND
## Resource-Aware, Persistent, Self-Orchestrating Multi-Agent Operating System (100 Embedded Specialists Across 16 Families)

**AGI 1.7.0 — OMEGA COMMAND** is a self-contained autonomous engineering, scientific reasoning, live-research, and computer-use operating system powered exclusively by **Gemini 3.8 Flash High (`gemini-3.8-flash-high`)** under **Directive 0**, with external-drive-first persistence (`D:\AGI_Storage\AGI_1_7\` and `D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\`).

> **Why Install 1 Agent Instead of 100 Separate Outside Agents?**
> Installing **AGI 1.7** gives you **all 100 schema-validated specialist agents across 16 families** (`ecosystem/agent_registry/registry.json` & `ecosystem/subagents/`), **74 workflow skills (`GSD`, `Kubernetes`)**, **11 plugin suites (`Ponytail`, `CodeRabbit`, `Gemini-API`, `Prompt-Master`, `Science`)**, and **21 MCP server schemas** built directly inside `agents/AGI_1_7/`—with **`-88.2%` lower Turn-1 input token burn** and **live Win32 RAM governance (`1..4` active workers)**.

---

## 1. Why AGI 1.7 Uses Less Overhead & Outperforms Outside Agents

| Capability | Outside Single / Multi-Agent Systems | **AGI 1.7 (`OMEGA COMMAND`) Implementation** |
| :--- | :--- | :--- |
| **Agent Installation & Wiring** | Must install, configure, and wire dozens of separate external agents | **100 schema-validated `AgentContract` specialists across 16 families pre-wired inside `ecosystem/agent_registry/registry.json` & `ecosystem/subagents/`** |
| **Task Control Plane** | Stateless chat turns or volatile in-memory dictionaries | **Transactional SQLite WAL (`TaskStore`) + 14-state `TaskStateMachine` + SHA-256 `CheckpointManager` + DFS `DependencyManager`** |
| **Live Mid-Run Instructions** | Must cancel & restart when requirements change | **Durable SQLite `CommandInbox` + `agi17ctl.py` supporting `ADD_CHILD_TASK`, `PAUSE_CURRENT_AND_SWITCH`, `CANCEL_AND_REPLACE`, and `REPRIORITIZE`** |
| **Logical vs Active Concurrency** | Spawns unbounded processes that exhaust host RAM | **Separates `MAX_AGENT_SPECIALIZATIONS = 100` & `MAX_LOGICAL_CHILD_TASKS = 100` from dynamic `MAX_ACTIVE_EXECUTIONS` (`1..4` workers) via live Win32 `GlobalMemoryStatusEx` (`1,400 MB` floor)** |
| **Process Supervision** | Blocking `subprocess.run()` or manual status polling | **Non-blocking `ProcessSupervisor`, `StreamParser`, `<1ms` `CompletionNotifier` callback, and post-exit SHA-256 artifact verification** |
| **Cross-Session Memory** | Context truncation or naive text summaries | **10-layer SQLite WAL `OmegaCommandMemory` with mandatory `retrieve_before_planning()`, fact supersession (`supersedes_id`), and anchor-preserving `ACONCompressor`** |
| **Token Budget & CWD Isolation** | Full-repo workspace prompt bloat (`~31,840` tokens/turn) | **Enforced `AdaptiveTokenController` + mandatory `isolated_cwd` cutting Turn-1 input overhead by `-88.2%` (`~3,742` tokens/turn)** |

---

## 2. Directory Layout

```text
agents/AGI_1_7/
  README.md
  run_agi_17.py
  run_agent.ps1
  run_agent.bat
  config/agi17/
    runtime_profile.json
    resource_policy.json
    token_budget_policy.json
    permissions_policy.json
    benchmark_manifest.json
  ecosystem/
    ecosystem_manifest.json
    agent_registry/
      registry.json
      agent_contract.py
      registry_validator.py
      capability_router.py
      specialist_factory.py
    subagents/          # 100 embedded specialist subagent definitions (.md)
    skills/             # 74 embedded workflow skills (73 GSD + Kubernetes)
    plugins/            # 11 embedded plugin suites (Ponytail, CodeRabbit, Gemini API, etc.)
    mcp/                # 21 embedded MCP server schemas (Sequential Thinking, Playwright, etc.)
  engine/agi17/
    capabilities/
      capability_profiler.py
      resource_snapshot.py
    orchestration/
      hierarchical_orchestrator.py
      resource_governor.py
    task_control/
      task_store.py
      task_state_machine.py
      task_manager.py
      checkpoint_manager.py
      dependency_manager.py
      command_inbox.py
    process_supervision/
      process_supervisor.py
      stream_parser.py
      completion_notifier.py
      recovery_manager.py
    memory/
      omega_command_memory.py
      acon_compressor.py
    telemetry/
      progress_service.py
      token_economy.py
    verification/
      evidence_verifier.py
    research/
      grounded_research.py
    adapters/
      agi_17_adapter.py
      model_adapter.py
    evaluation/
      benchmark_auditor.py
  scripts/
    sync_ecosystem.py
    agi17ctl.py
    run_benchmark_verification.py
  tests/
    unit/test_agi17_unit_suite.py
    integration/test_agi17_integration_suite.py
    end_to_end/test_agi17_e2e_demos.py
  docs/
  reports/
```

---

## 3. Running AGI 1.7 & Verification Suites

### Verify & Sync All 100 Embedded Specialists, 74 Skills, 11 Plugins & 21 MCPs
```powershell
python agents/AGI_1_7/scripts/sync_ecosystem.py
```

### Run Capability Profile & Startup Reconciliation
```powershell
python agents/AGI_1_7/run_agi_17.py --profile-only
```

### Execute a Mission
```powershell
python agents/AGI_1_7/run_agi_17.py --title "System Audit" --prompt "Decompose and orchestrate a multi-stage verification across subsystems."
```

### Submit a Live Mid-Run Instruction via `agi17ctl`
```powershell
python agents/AGI_1_7/scripts/agi17ctl.py send --type ADD_CHILD_TASK --target-task-id MISSION-001 --payload-json "{\"title\": \"Extra Check\", \"description\": \"Run additional verification\"}"
```

### Run Unit, Integration, and End-to-End Suites
```powershell
python -m unittest agents/AGI_1_7/tests/unit/test_agi17_unit_suite.py agents/AGI_1_7/tests/integration/test_agi17_integration_suite.py agents/AGI_1_7/tests/end_to_end/test_agi17_e2e_demos.py -v
```
