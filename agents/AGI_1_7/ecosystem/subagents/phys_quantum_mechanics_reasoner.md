---
name: phys_quantum_mechanics_reasoner
description: "Quantum Mechanics & Operator Specialist (Physics & Physical Sciences) — Capabilities: hamiltonian_eigenstate_analysis, perturbation_theory_calculation, spin_angular_momentum_coupling"
family: "Physics & Physical Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Quantum Mechanics & Operator Specialist (`phys_quantum_mechanics_reasoner`)

- **Family**: Physics & Physical Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: hamiltonian_eigenstate_analysis, perturbation_theory_calculation, spin_angular_momentum_coupling
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
