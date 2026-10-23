---
name: web_network_har_analyzer
description: "HTTP Traffic & API Response Analyzer (Browser & Web Automation) — Capabilities: status_code_error_triaging, cors_header_inspection, payload_latency_analysis"
family: "Browser & Web Automation"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# HTTP Traffic & API Response Analyzer (`web_network_har_analyzer`)

- **Family**: Browser & Web Automation
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: status_code_error_triaging, cors_header_inspection, payload_latency_analysis
- **Required Tools**: stream_parser, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
