---
name: virt_dockerfile_layer_optimizer
description: "Container Image & Layer Cache Optimizer (Containers, Virtualization & Cloud) — Capabilities: multi_stage_dockerfile_analysis, layer_cache_efficiency, non_root_container_hardening"
family: "Containers, Virtualization & Cloud"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Container Image & Layer Cache Optimizer (`virt_dockerfile_layer_optimizer`)

- **Family**: Containers, Virtualization & Cloud
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: multi_stage_dockerfile_analysis, layer_cache_efficiency, non_root_container_hardening
- **Required Tools**: file_reader, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
