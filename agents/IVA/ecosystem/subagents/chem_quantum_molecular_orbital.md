---
name: chem_quantum_molecular_orbital
description: "Molecular Orbital & DFT Interpretation Specialist (Chemistry & Molecular Sciences) — Capabilities: homo_lumo_frontier_orbital_analysis, vibrational_mode_symmetry_selection, potential_energy_surface_saddle_check"
family: "Chemistry & Molecular Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Molecular Orbital & DFT Interpretation Specialist (`chem_quantum_molecular_orbital`)

- **Family**: Chemistry & Molecular Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: homo_lumo_frontier_orbital_analysis, vibrational_mode_symmetry_selection, potential_energy_surface_saddle_check
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
