---
name: virt_container_network_isolation_checker
description: "Container Network & Volume Mount Auditor (Containers, Virtualization & Cloud) — Capabilities: bind_mount_scope_verification, port_exposure_auditing, container_resource_flag_validation"
family: "Containers, Virtualization & Cloud"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Container Network & Volume Mount Auditor (`virt_container_network_isolation_checker`)

- **Family**: Containers, Virtualization & Cloud
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: bind_mount_scope_verification, port_exposure_auditing, container_resource_flag_validation
- **Required Tools**: capability_profiler, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
