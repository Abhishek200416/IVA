---
name: virt_wsl2_memory_governor
description: "WSL 2 & vmmemWSL Resource Governor (Containers, Virtualization & Cloud) — Capabilities: wsl_distro_enumeration, vmmem_working_set_monitoring, wslconfig_cap_verification"
family: "Containers, Virtualization & Cloud"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# WSL 2 & vmmemWSL Resource Governor (`virt_wsl2_memory_governor`)

- **Family**: Containers, Virtualization & Cloud
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: wsl_distro_enumeration, vmmem_working_set_monitoring, wslconfig_cap_verification
- **Required Tools**: capability_profiler, resource_snapshot
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
