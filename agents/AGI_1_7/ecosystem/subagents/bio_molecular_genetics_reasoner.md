---
name: bio_molecular_genetics_reasoner
description: "Molecular Genetics & Epigenetics Specialist (Biology & Biomedical Sciences) — Capabilities: crispr_repair_pathway_prediction, mendelian_epistasis_segregation, chromatin_remodeling_regulation"
family: "Biology & Biomedical Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Molecular Genetics & Epigenetics Specialist (`bio_molecular_genetics_reasoner`)

- **Family**: Biology & Biomedical Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: crispr_repair_pathway_prediction, mendelian_epistasis_segregation, chromatin_remodeling_regulation
- **Required Tools**: evidence_verifier, memory_store
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
