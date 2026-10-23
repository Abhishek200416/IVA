---
name: virt_harbor_sandbox_coordinator
description: "Harbor Benchmark Container Coordinator (Containers, Virtualization & Cloud) — Capabilities: harbor_trial_configuration, container_concurrency_limiting, reward_json_reconciliation"
family: "Containers, Virtualization & Cloud"
resource_class: "CONTAINER"
max_token_budget: 14000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Harbor Benchmark Container Coordinator (`virt_harbor_sandbox_coordinator`)

- **Family**: Containers, Virtualization & Cloud
- **Execution Mode**: `ISOLATED_CONTAINER_WORKER`
- **Primary Capabilities**: harbor_trial_configuration, container_concurrency_limiting, reward_json_reconciliation
- **Required Tools**: process_supervisor, benchmark_auditor
- **Max Token Budget**: `14000`
- **Max Wall-Clock Seconds**: `600s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
