---
name: ops_posix_shell_specialist
description: "POSIX Bash & Coreutils Specialist (Terminal, Shell & OS Operations) — Capabilities: bash_pipeline_composition, awk_sed_stream_processing, signal_trap_handling"
family: "Terminal, Shell & OS Operations"
resource_class: "MEDIUM"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# POSIX Bash & Coreutils Specialist (`ops_posix_shell_specialist`)

- **Family**: Terminal, Shell & OS Operations
- **Execution Mode**: `SUPERVISED_SUBPROCESS_WORKER`
- **Primary Capabilities**: bash_pipeline_composition, awk_sed_stream_processing, signal_trap_handling
- **Required Tools**: process_supervisor, stream_parser
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
