---
name: ops_powershell_automation_specialist
description: "Windows PowerShell Pipeline Specialist (Terminal, Shell & OS Operations) — Capabilities: powershell_cmdlet_orchestration, non_interactive_script_execution, exit_status_propagation"
family: "Terminal, Shell & OS Operations"
resource_class: "MEDIUM"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Windows PowerShell Pipeline Specialist (`ops_powershell_automation_specialist`)

- **Family**: Terminal, Shell & OS Operations
- **Execution Mode**: `SUPERVISED_SUBPROCESS_WORKER`
- **Primary Capabilities**: powershell_cmdlet_orchestration, non_interactive_script_execution, exit_status_propagation
- **Required Tools**: process_supervisor, stream_parser
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
