---
name: bio_bioinformatics_sequence_analyst
description: "Sequence Alignment & Phylogenetics Analyst (Biology & Biomedical Sciences) — Capabilities: codon_degeneracy_frame_translation, pam_blosum_scoring_evaluation, hardy_weinberg_allele_frequency_check"
family: "Biology & Biomedical Sciences"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Sequence Alignment & Phylogenetics Analyst (`bio_bioinformatics_sequence_analyst`)

- **Family**: Biology & Biomedical Sciences
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: codon_degeneracy_frame_translation, pam_blosum_scoring_evaluation, hardy_weinberg_allele_frequency_check
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
