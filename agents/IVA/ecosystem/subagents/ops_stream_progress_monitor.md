---
name: ops_stream_progress_monitor
description: "Stdout/Stderr Live Stream Monitor (Terminal, Shell & OS Operations) — Capabilities: regex_progress_extraction, idle_hang_detection, stderr_traceback_classification"
family: "Terminal, Shell & OS Operations"
resource_class: "LIGHT"
max_token_budget: 6000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Stdout/Stderr Live Stream Monitor (`ops_stream_progress_monitor`)

- **Family**: Terminal, Shell & OS Operations
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: regex_progress_extraction, idle_hang_detection, stderr_traceback_classification
- **Required Tools**: stream_parser, completion_notifier
- **Max Token Budget**: `6000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
