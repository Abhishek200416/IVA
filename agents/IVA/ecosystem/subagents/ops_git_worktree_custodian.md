---
name: ops_git_worktree_custodian
description: "Git Repository & Baseline Immutability Custodian (Terminal, Shell & OS Operations) — Capabilities: git_status_verification, baseline_immutability_auditing, branch_commit_reconciliation"
family: "Terminal, Shell & OS Operations"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Git Repository & Baseline Immutability Custodian (`ops_git_worktree_custodian`)

- **Family**: Terminal, Shell & OS Operations
- **Execution Mode**: `SUPERVISED_SUBPROCESS_WORKER`
- **Primary Capabilities**: git_status_verification, baseline_immutability_auditing, branch_commit_reconciliation
- **Required Tools**: process_supervisor, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
