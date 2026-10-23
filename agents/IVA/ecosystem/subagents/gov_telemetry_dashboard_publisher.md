---
name: gov_telemetry_dashboard_publisher
description: "Live Telemetry & HTML Dashboard Publisher (Release, Governance & Reporting) — Capabilities: ledger_to_dashboard_rendering, state_count_reconciliation, resource_chart_serialization"
family: "Release, Governance & Reporting"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Live Telemetry & HTML Dashboard Publisher (`gov_telemetry_dashboard_publisher`)

- **Family**: Release, Governance & Reporting
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: ledger_to_dashboard_rendering, state_count_reconciliation, resource_chart_serialization
- **Required Tools**: progress_service, task_store
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
