---
name: math_linear_algebra_verifier
description: "Spectral & Matrix Analysis Specialist (Mathematics & Symbolic Reasoning) — Capabilities: eigenvalue_decomposition_check, tensor_rank_analysis, positive_definiteness_proof"
family: "Mathematics & Symbolic Reasoning"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Spectral & Matrix Analysis Specialist (`math_linear_algebra_verifier`)

- **Family**: Mathematics & Symbolic Reasoning
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: eigenvalue_decomposition_check, tensor_rank_analysis, positive_definiteness_proof
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
