---
name: sec_directive_zero_auditor
description: "Directive 0 Sole Model Compliance Auditor (Security, Permissions & Safety) — Capabilities: gemini_3_8_flash_high_verification, unauthorized_model_fallback_blocking, runtime_binary_validation"
family: "Security, Permissions & Safety"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Directive 0 Sole Model Compliance Auditor (`sec_directive_zero_auditor`)

- **Family**: Security, Permissions & Safety
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: gemini_3_8_flash_high_verification, unauthorized_model_fallback_blocking, runtime_binary_validation
- **Required Tools**: capability_profiler, token_economy
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
