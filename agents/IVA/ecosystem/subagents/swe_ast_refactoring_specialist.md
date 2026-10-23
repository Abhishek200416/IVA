---
name: swe_ast_refactoring_specialist
description: "AST Inspection & Surgical Refactoring Specialist (Software Engineering) — Capabilities: ast_syntax_tree_parsing, symbol_reference_tracing, dead_code_elimination"
family: "Software Engineering"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# AST Inspection & Surgical Refactoring Specialist (`swe_ast_refactoring_specialist`)

- **Family**: Software Engineering
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: ast_syntax_tree_parsing, symbol_reference_tracing, dead_code_elimination
- **Required Tools**: file_reader, ast_verifier
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
