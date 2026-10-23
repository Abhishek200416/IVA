---
name: swe_python_runtime_engineer
description: "Python Core & Asyncio Runtime Engineer (Software Engineering) — Capabilities: python_stdlib_implementation, asyncio_concurrency_patterns, type_annotation_validation"
family: "Software Engineering"
resource_class: "LIGHT"
max_token_budget: 14000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Python Core & Asyncio Runtime Engineer (`swe_python_runtime_engineer`)

- **Family**: Software Engineering
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: python_stdlib_implementation, asyncio_concurrency_patterns, type_annotation_validation
- **Required Tools**: file_reader, file_writer, ast_verifier
- **Max Token Budget**: `14000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
