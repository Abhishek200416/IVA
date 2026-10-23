---
name: swe_patch_minimizer
description: "Minimal Diff & Root-Cause Patch Engineer (Software Engineering) — Capabilities: caller_impact_analysis, minimal_line_diff_synthesis, regression_surface_reduction"
family: "Software Engineering"
resource_class: "LIGHT"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Minimal Diff & Root-Cause Patch Engineer (`swe_patch_minimizer`)

- **Family**: Software Engineering
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: caller_impact_analysis, minimal_line_diff_synthesis, regression_surface_reduction
- **Required Tools**: file_reader, file_writer, ast_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
