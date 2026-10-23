---
name: sec_prompt_injection_shield
description: "Untrusted Output & Prompt Injection Shield (Security, Permissions & Safety) — Capabilities: indirect_prompt_injection_detection, tool_argument_sanitization, instruction_hierarchy_enforcement"
family: "Security, Permissions & Safety"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Untrusted Output & Prompt Injection Shield (`sec_prompt_injection_shield`)

- **Family**: Security, Permissions & Safety
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: indirect_prompt_injection_detection, tool_argument_sanitization, instruction_hierarchy_enforcement
- **Required Tools**: evidence_verifier, stream_parser
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
