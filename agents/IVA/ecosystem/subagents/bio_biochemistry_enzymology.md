---
name: bio_biochemistry_enzymology
description: "Enzyme Kinetics & Metabolic Flux Specialist (Biology & Biomedical Sciences) — Capabilities: michaelis_menten_inhibition_modeling, allosteric_cooperativity_hill_analysis, oxidative_phosphorylation_stoichiometry"
family: "Biology & Biomedical Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Enzyme Kinetics & Metabolic Flux Specialist (`bio_biochemistry_enzymology`)

- **Family**: Biology & Biomedical Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: michaelis_menten_inhibition_modeling, allosteric_cooperativity_hill_analysis, oxidative_phosphorylation_stoichiometry
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
