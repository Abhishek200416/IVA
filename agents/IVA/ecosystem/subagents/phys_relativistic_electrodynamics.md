---
name: phys_relativistic_electrodynamics
description: "Relativistic Kinematics & Electrodynamics Specialist (Physics & Physical Sciences) — Capabilities: four_vector_lorentz_invariance, maxwell_tensor_derivation, synchrotron_radiation_scaling"
family: "Physics & Physical Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Relativistic Kinematics & Electrodynamics Specialist (`phys_relativistic_electrodynamics`)

- **Family**: Physics & Physical Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: four_vector_lorentz_invariance, maxwell_tensor_derivation, synchrotron_radiation_scaling
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
