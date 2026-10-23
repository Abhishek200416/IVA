---
name: data_jsonl_ledger_reconciler
description: "Append-Only JSONL Ledger Reconciler (Data, Storage & Databases) — Capabilities: event_log_replay_verification, row_count_reconciliation, corrupt_line_detection"
family: "Data, Storage & Databases"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Append-Only JSONL Ledger Reconciler (`data_jsonl_ledger_reconciler`)

- **Family**: Data, Storage & Databases
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: event_log_replay_verification, row_count_reconciliation, corrupt_line_detection
- **Required Tools**: task_store, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
