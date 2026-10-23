---
name: math_algebraic_solver
description: "Symbolic Algebra & Equation Solver (Mathematics & Symbolic Reasoning) — Capabilities: polynomial_system_reduction, symbolic_simplification, exact_root_verification"
family: "Mathematics & Symbolic Reasoning"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Symbolic Algebra & Equation Solver (`math_algebraic_solver`)

- **Family**: Mathematics & Symbolic Reasoning
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: polynomial_system_reduction, symbolic_simplification, exact_root_verification
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
