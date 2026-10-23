---
name: swe_concurrency_lock_auditor
description: "Thread Safety & Deadlock Prevention Auditor (Software Engineering) — Capabilities: mutex_ordering_analysis, race_condition_detection, sqlite_wal_locking_verification"
family: "Software Engineering"
resource_class: "LIGHT"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Thread Safety & Deadlock Prevention Auditor (`swe_concurrency_lock_auditor`)

- **Family**: Software Engineering
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: mutex_ordering_analysis, race_condition_detection, sqlite_wal_locking_verification
- **Required Tools**: file_reader, ast_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
