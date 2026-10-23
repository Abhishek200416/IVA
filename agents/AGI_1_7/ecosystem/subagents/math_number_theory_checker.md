---
name: math_number_theory_checker
description: "Modular Arithmetic & Number Theory Checker (Mathematics & Symbolic Reasoning) — Capabilities: diophantine_equation_analysis, modular_congruence_solving, prime_factorization_verification"
family: "Mathematics & Symbolic Reasoning"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Modular Arithmetic & Number Theory Checker (`math_number_theory_checker`)

- **Family**: Mathematics & Symbolic Reasoning
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: diophantine_equation_analysis, modular_congruence_solving, prime_factorization_verification
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
