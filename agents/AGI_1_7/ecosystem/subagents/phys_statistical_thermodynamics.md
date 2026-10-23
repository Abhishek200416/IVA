---
name: phys_statistical_thermodynamics
description: "Statistical Mechanics & Partition Function Specialist (Physics & Physical Sciences) — Capabilities: canonical_ensemble_derivation, phase_transition_critical_exponents, boltzmann_transport_analysis"
family: "Physics & Physical Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Statistical Mechanics & Partition Function Specialist (`phys_statistical_thermodynamics`)

- **Family**: Physics & Physical Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: canonical_ensemble_derivation, phase_transition_critical_exponents, boltzmann_transport_analysis
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
