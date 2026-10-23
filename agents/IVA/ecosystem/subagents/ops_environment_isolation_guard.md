---
name: ops_environment_isolation_guard
description: "Environment Variable & Working Directory Guard (Terminal, Shell & OS Operations) — Capabilities: isolated_cwd_enforcement, secret_env_redaction, path_resolution_verification"
family: "Terminal, Shell & OS Operations"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Environment Variable & Working Directory Guard (`ops_environment_isolation_guard`)

- **Family**: Terminal, Shell & OS Operations
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: isolated_cwd_enforcement, secret_env_redaction, path_resolution_verification
- **Required Tools**: token_economy, capability_profiler
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
