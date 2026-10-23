---
name: desk_screenshot_observation_compressor
description: "Visual Observation & A11y Tree Compressor (Desktop & Computer Use) — Capabilities: a11y_tree_pruning, bounding_box_coordinate_normalization, visual_token_budget_reduction"
family: "Desktop & Computer Use"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Visual Observation & A11y Tree Compressor (`desk_screenshot_observation_compressor`)

- **Family**: Desktop & Computer Use
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: a11y_tree_pruning, bounding_box_coordinate_normalization, visual_token_budget_reduction
- **Required Tools**: memory_store, token_economy
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
