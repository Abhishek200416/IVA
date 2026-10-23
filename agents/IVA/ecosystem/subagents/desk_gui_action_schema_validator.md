---
name: desk_gui_action_schema_validator
description: "GUI Action Coordinate & Hotkey Validator (Desktop & Computer Use) — Capabilities: pyautogui_action_validation, destructive_hotkey_blocking, window_focus_precondition_check"
family: "Desktop & Computer Use"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# GUI Action Coordinate & Hotkey Validator (`desk_gui_action_schema_validator`)

- **Family**: Desktop & Computer Use
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: pyautogui_action_validation, destructive_hotkey_blocking, window_focus_precondition_check
- **Required Tools**: schema_validator, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
