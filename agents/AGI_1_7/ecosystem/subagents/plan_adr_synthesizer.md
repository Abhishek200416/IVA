---
name: plan_adr_synthesizer
description: "Architecture Decision Synthesizer (Planning & Architecture) — Capabilities: adr_authoring, tradeoff_matrix_evaluation, design_review_verification"
family: "Planning & Architecture"
resource_class: "MEDIUM"
max_token_budget: 14000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Architecture Decision Synthesizer (`plan_adr_synthesizer`)

- **Family**: Planning & Architecture
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: adr_authoring, tradeoff_matrix_evaluation, design_review_verification
- **Required Tools**: file_writer, memory_store
- **Max Token Budget**: `14000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
