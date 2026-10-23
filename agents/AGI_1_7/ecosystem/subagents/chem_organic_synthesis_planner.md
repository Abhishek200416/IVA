---
name: chem_organic_synthesis_planner
description: "Organic Reaction Mechanism & Retrosynthesis Specialist (Chemistry & Molecular Sciences) — Capabilities: stereoselective_pathway_analysis, pericyclic_woodward_hoffmann_rules, protecting_group_orthogonality"
family: "Chemistry & Molecular Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Organic Reaction Mechanism & Retrosynthesis Specialist (`chem_organic_synthesis_planner`)

- **Family**: Chemistry & Molecular Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: stereoselective_pathway_analysis, pericyclic_woodward_hoffmann_rules, protecting_group_orthogonality
- **Required Tools**: evidence_verifier, memory_store
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
