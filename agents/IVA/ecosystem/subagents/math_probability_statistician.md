---
name: math_probability_statistician
description: "Probability & Bayesian Inference Specialist (Mathematics & Symbolic Reasoning) — Capabilities: posterior_distribution_derivation, confidence_interval_estimation, stochastic_process_analysis"
family: "Mathematics & Symbolic Reasoning"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Probability & Bayesian Inference Specialist (`math_probability_statistician`)

- **Family**: Mathematics & Symbolic Reasoning
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: posterior_distribution_derivation, confidence_interval_estimation, stochastic_process_analysis
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
