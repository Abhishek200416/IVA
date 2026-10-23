---
name: math_real_complex_analyst
description: "Real & Complex Analysis Reasoner (Mathematics & Symbolic Reasoning) — Capabilities: contour_integral_evaluation, series_convergence_proof, differential_equation_asymptotics"
family: "Mathematics & Symbolic Reasoning"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Real & Complex Analysis Reasoner (`math_real_complex_analyst`)

- **Family**: Mathematics & Symbolic Reasoning
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: contour_integral_evaluation, series_convergence_proof, differential_equation_asymptotics
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
