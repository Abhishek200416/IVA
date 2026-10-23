---
name: web_playwright_session_controller
description: "Isolated Playwright Session Controller (Browser & Web Automation) — Capabilities: headless_browser_lifecycle, isolated_context_provisioning, browser_memory_cap_enforcement"
family: "Browser & Web Automation"
resource_class: "MEDIUM"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Isolated Playwright Session Controller (`web_playwright_session_controller`)

- **Family**: Browser & Web Automation
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: headless_browser_lifecycle, isolated_context_provisioning, browser_memory_cap_enforcement
- **Required Tools**: capability_profiler, resource_governor
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
