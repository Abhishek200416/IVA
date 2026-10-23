---
name: virt_docker_engine_inspector
description: "Docker Engine & Container Lifecycle Inspector (Containers, Virtualization & Cloud) — Capabilities: docker_daemon_health_check, container_stats_collection, dangling_container_detection"
family: "Containers, Virtualization & Cloud"
resource_class: "MEDIUM"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Docker Engine & Container Lifecycle Inspector (`virt_docker_engine_inspector`)

- **Family**: Containers, Virtualization & Cloud
- **Execution Mode**: `SUPERVISED_SUBPROCESS_WORKER`
- **Primary Capabilities**: docker_daemon_health_check, container_stats_collection, dangling_container_detection
- **Required Tools**: capability_profiler, process_supervisor
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
