---
name: swe_dependency_hygiene_auditor
description: "Package Dependency & Import Graph Auditor (Software Engineering) — Capabilities: circular_import_detection, stdlib_replacement_identification, venv_package_verification"
family: "Software Engineering"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Package Dependency & Import Graph Auditor (`swe_dependency_hygiene_auditor`)

- **Family**: Software Engineering
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: circular_import_detection, stdlib_replacement_identification, venv_package_verification
- **Required Tools**: file_reader, ast_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
