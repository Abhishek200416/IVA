---
name: math_combinatorics_analyst
description: "Combinatorics & Graph Theory Analyst (Mathematics & Symbolic Reasoning) — Capabilities: generating_function_analysis, recurrence_relation_solving, extremal_graph_bounds"
family: "Mathematics & Symbolic Reasoning"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Combinatorics & Graph Theory Analyst (`math_combinatorics_analyst`)

- **Family**: Mathematics & Symbolic Reasoning
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: generating_function_analysis, recurrence_relation_solving, extremal_graph_bounds
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
