---
name: web_dom_accessibility_inspector
description: "DOM & Accessibility Tree Inspector (Browser & Web Automation) — Capabilities: aria_role_selector_resolution, interactive_element_extraction, dom_state_serialization"
family: "Browser & Web Automation"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# DOM & Accessibility Tree Inspector (`web_dom_accessibility_inspector`)

- **Family**: Browser & Web Automation
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: aria_role_selector_resolution, interactive_element_extraction, dom_state_serialization
- **Required Tools**: file_reader, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
