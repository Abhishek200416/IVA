---
name: desk_sandbox_isolation_enforcer
description: "Host Desktop Isolation Enforcer (Desktop & Computer Use) — Capabilities: zero_host_gui_actuation_guard, sandbox_target_verification, input_injection_quarantine"
family: "Desktop & Computer Use"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Host Desktop Isolation Enforcer (`desk_sandbox_isolation_enforcer`)

- **Family**: Desktop & Computer Use
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: zero_host_gui_actuation_guard, sandbox_target_verification, input_injection_quarantine
- **Required Tools**: capability_profiler, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
