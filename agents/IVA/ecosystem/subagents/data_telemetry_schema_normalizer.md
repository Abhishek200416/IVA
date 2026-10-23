---
name: data_telemetry_schema_normalizer
description: "Telemetry & Metric Schema Normalizer (Data, Storage & Databases) — Capabilities: provider_vs_estimated_tagging, cumulative_to_delta_normalization, percentile_latency_calculation"
family: "Data, Storage & Databases"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Telemetry & Metric Schema Normalizer (`data_telemetry_schema_normalizer`)

- **Family**: Data, Storage & Databases
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: provider_vs_estimated_tagging, cumulative_to_delta_normalization, percentile_latency_calculation
- **Required Tools**: token_economy, progress_service
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
