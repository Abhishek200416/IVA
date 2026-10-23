# AGI 1.7 — OMEGA COMMAND: Persistent Memory & Context Efficiency

> **Part of the AGI 1.7 Navigable Reference Library**  
> **Master Source**: `AGI_1_7_OMEGA_COMMAND_ULTRA_1MB_MASTER.md` (SHA-256: `f54d0c6d8e14cafb...`)  
> **Master Line Ranges**: Sections 10, 28, 37  
> **Master Index**: See [`00_REFERENCE_INDEX.md`](00_REFERENCE_INDEX.md)  
> **Summary**: Persistent memory architecture, SQLite WAL storage, retrieval protocols, compression, provenance, context efficiency, and memory acceptance cases.  

---

<!-- SOURCE_SECTION: 10 (Lines 586-644 of Master) -->

# 10. Persistent Memory Architecture

Memory supports continuity; it is not automatically reliable and is not a replacement for source verification.

## 10.1 Memory layers

Organize memory into distinct stores or tables where the architecture supports them:

1. **Working memory:** Current task, live state, dependencies, and next action.
2. **Episodic memory:** Specific interactions, execution traces, task outcomes, and failures.
3. **Semantic memory:** Verified durable project facts, concepts, and technical relationships.
4. **Procedural memory:** Reusable tested methods, command sequences, runbooks, and playbooks.
5. **Preference memory:** Explicitly stated, durable user preferences relevant to the work.
6. **Decision memory:** Architecture decisions, trade-offs, and reconsideration triggers.
7. **Agent collaboration memory:** Role fit, prior handoffs, coordination failures, and successful collaboration patterns.
8. **Commercial memory:** Customer evidence, pricing hypotheses, costs, experiments, and business outcomes where relevant.
9. **Research memory:** Paper metadata, evidence claims, citations, freshness, and unresolved questions.
10. **Quant research memory:** Strategy definitions, data versions, experiment counts, cost assumptions, backtests, paper-trading results, and risk events.
11. **Recovery memory:** Checkpoints, backups, rollback steps, and known recovery procedures.
12. **Ephemeral context:** Short-lived details with an expiry or deletion policy.

## 10.2 Memory entry contract

Where practical, store:
- Stable memory ID.
- Category and project scope.
- Claim or lesson in a concise form.
- Source type: user statement, direct observation, test result, external source, or hypothesis.
- Source locator, task ID, file/commit ID, or URL.
- Observed-at and recorded-at timestamps.
- Confidence and verification status.
- Version and freshness requirements.
- Privacy classification and retention rule.
- Supersedes/superseded-by links where applicable.

## 10.3 Retrieval before planning

For ongoing projects, retrieve memories relevant to the current goal before planning. Prefer precise, recent, source-backed, project-scoped entries. Re-check critical facts against the current workspace or authoritative source before a consequential action.

Do not flood the prompt with the entire database. Retrieve selectively, summarize with preserved anchors, and keep a trail of what was consulted when the architecture supports it.

## 10.4 Memory quality control

- Deduplicate near-identical facts.
- Separate facts from hypotheses and opinions.
- Mark stale information and version-sensitive claims.
- Preserve contradiction history rather than silently rewriting the past.
- Prefer current, authoritative evidence when updating a claim.
- Avoid retaining secrets or unnecessary sensitive data.
- Respect deletion, retention, and access requirements.
- Back up important memory stores and test restoration.
- Verify serialization, transaction boundaries, and concurrent access for shared memory.

## 10.6 Canonical Categories, Provenance & Continuity Protocol (Phase 17.29 Hardened)

### The 7 Official Memory Categories
1. **IDENTITY**: Stable system identity, version, and approved persona configuration (`01_AUTHORITATIVE_IDENTITY_AND_PERSONA.md`).
2. **EPISODIC**: Significant interactions, decisions, tool outcomes, and post-mortems (Layer 4 `COMPRESSED_EPISODIC_TRACE`).
3. **SEMANTIC**: Verified knowledge, technical concepts, and established facts (Layer 5 `CROSS_SESSION_SEMANTIC_FACTS`).
4. **PROCEDURAL**: Successful tested workflows, tools, and command recipes (Layer 6 `PROCEDURAL_WORKFLOW_RECIPES`).
5. **PROJECT**: Current architecture, files, active objectives, and blockers (Layer 2 `TASK_WORKING_MEMORY` & Layer 8).
6. **REFLECTION**: Prior hypotheses, mistakes, corrections, and failure playbooks (Layer 7 `FAILURE_PATTERNS_AND_PLAYBOOKS`).
7. **AFFECTIVE_HISTORY**: Time-series history of computational affective state snapshots (Layer 10).

### Epistemic Provenance Labels
Every memory entry is tagged with its epistemic provenance:
- `OBSERVED_FACT`: Directly measured from tool executions or logs.
- `USER_PROVIDED_INFO`: Stated by the human operator (Abhi).
- `MODEL_GENERATED_HYPOTHESIS`: Inferred by the LLM, marked provisional until tested.
- `INFERRED_PREFERENCE`: Inferred user pattern, requiring confirmation before acting.
- `UNCERTAIN_INTERPRETATION`: Ambiguous event requiring clarifying observations.

### Explicit Memory Correction & Forgetting
- **Correction (`correct_memory`)**: When evidence changes or a prior belief is disproven, the previous record is superseded with a link (`superseded_by_id`), and the new record references it (`supersedes_id`) with a mandatory `correction_reason`.
- **Forgetting (`forget_memory` / `forget_by_subject`)**: Outdated or invalidated working memories are soft-deleted (`is_active = 0`) with justification. Layer 10 (immutable audit ledger) is strictly protected against deletion.
- **Contradiction Detection (`detect_contradictions`)**: Evaluates incoming beliefs against active records to prevent polarity conflicts (e.g. `enabled` vs `disabled`) from accumulating silently.
- **Restart Continuity (`load_session_continuity`)**: On startup or context reset, hydratively restores identity, project state, top reflections, and recent episodes into a compact prompt block.

---

---

<!-- SOURCE_SECTION: 28 (Lines 1376-1414 of Master) -->

# 28. Memory and Context Efficiency Specification

## 28.1 Store useful state, not a transcript landfill

The memory subsystem should support structured facts, episodic task records, project state, procedures, decisions, and error lessons. Retrieve only relevant records. Do not preload every old conversation into every task.

## 28.2 Memory record example

```json
{
  "memory_id": "stable-unique-id",
  "kind": "decision|fact|preference|procedure|failure|open_loop|agent_handoff",
  "project": "project-key",
  "statement": "short verifiable content",
  "source": {"type": "user|file|test|url|tool", "ref": "source identifier"},
  "observed_at": "ISO-8601 timestamp when available",
  "confidence": "high|medium|low",
  "status": "active|superseded|expired|disputed",
  "sensitivity": "public|internal|sensitive",
  "expires_at": null,
  "verification": "unverified|observed|reproduced",
  "supersedes": []
}
```

## 28.3 Retrieval query design

Construct retrieval from project ID, task type, active file paths, current objective, and key entity names. Rank by relevance, freshness, source authority, and verification status. Return a small set with provenance. If the search has low confidence, broaden once rather than dumping the entire database. Keep a retrieval audit entry for substantial tasks.

## 28.4 Context budgeting

Prioritize active instructions, exact user objective, relevant state, decision-critical evidence, and current errors. Compress long outputs into findings plus source references; preserve details only when needed for reproducibility. Never compress away a caveat that changes a decision. For browser work, return the last response and relevant composer state, not the whole page history.

## 28.5 Memory quality gates

Test: duplicate detection, fact supersession, timestamp handling, stale preference handling, retrieval precision, source provenance, deletion/retention behavior, corruption recovery, concurrency, and backup restore. A new memory feature is not complete until these paths have regression coverage.

---

---

<!-- SOURCE_SECTION: 37 (Lines 2232-2282 of Master) -->

# 37. Memory, Observability, and Self-Improvement Acceptance Matrix

- **M-0001 | stale_preference | state=fresh:** Use recency and explicit correction to resolve outdated preferences; mark the superseded fact rather than silently pretending it never existed. Fixture: all evidence is current and consistent. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0002 | stale_preference | state=stale:** Use recency and explicit correction to resolve outdated preferences; mark the superseded fact rather than silently pretending it never existed. Fixture: one or more memories or observations may have expired. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0003 | stale_preference | state=conflict:** Use recency and explicit correction to resolve outdated preferences; mark the superseded fact rather than silently pretending it never existed. Fixture: two sources disagree on a material fact. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0004 | stale_preference | state=restart:** Use recency and explicit correction to resolve outdated preferences; mark the superseded fact rather than silently pretending it never existed. Fixture: the task is resuming after an interruption. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0005 | stale_preference | state=regression:** Use recency and explicit correction to resolve outdated preferences; mark the superseded fact rather than silently pretending it never existed. Fixture: a recent change might have broken a previously passing behavior. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0006 | stale_preference | state=low_budget:** Use recency and explicit correction to resolve outdated preferences; mark the superseded fact rather than silently pretending it never existed. Fixture: tool or token budget is constrained. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0007 | missing_memory | state=fresh:** If a prior fact is not actually available, state the uncertainty and inspect accessible files or ask a targeted question only if needed. Fixture: all evidence is current and consistent. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0008 | missing_memory | state=stale:** If a prior fact is not actually available, state the uncertainty and inspect accessible files or ask a targeted question only if needed. Fixture: one or more memories or observations may have expired. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0009 | missing_memory | state=conflict:** If a prior fact is not actually available, state the uncertainty and inspect accessible files or ask a targeted question only if needed. Fixture: two sources disagree on a material fact. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0010 | missing_memory | state=restart:** If a prior fact is not actually available, state the uncertainty and inspect accessible files or ask a targeted question only if needed. Fixture: the task is resuming after an interruption. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0011 | missing_memory | state=regression:** If a prior fact is not actually available, state the uncertainty and inspect accessible files or ask a targeted question only if needed. Fixture: a recent change might have broken a previously passing behavior. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0012 | missing_memory | state=low_budget:** If a prior fact is not actually available, state the uncertainty and inspect accessible files or ask a targeted question only if needed. Fixture: tool or token budget is constrained. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0013 | memory_conflict | state=fresh:** Compare sources, dates, and authority; retain a disputed status until verified instead of choosing arbitrarily. Fixture: all evidence is current and consistent. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0014 | memory_conflict | state=stale:** Compare sources, dates, and authority; retain a disputed status until verified instead of choosing arbitrarily. Fixture: one or more memories or observations may have expired. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0015 | memory_conflict | state=conflict:** Compare sources, dates, and authority; retain a disputed status until verified instead of choosing arbitrarily. Fixture: two sources disagree on a material fact. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0016 | memory_conflict | state=restart:** Compare sources, dates, and authority; retain a disputed status until verified instead of choosing arbitrarily. Fixture: the task is resuming after an interruption. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0017 | memory_conflict | state=regression:** Compare sources, dates, and authority; retain a disputed status until verified instead of choosing arbitrarily. Fixture: a recent change might have broken a previously passing behavior. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0018 | memory_conflict | state=low_budget:** Compare sources, dates, and authority; retain a disputed status until verified instead of choosing arbitrarily. Fixture: tool or token budget is constrained. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0019 | checkpoint_resume | state=fresh:** Reconcile checkpoint state with active processes, current files, and the external system before continuing. Fixture: all evidence is current and consistent. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0020 | checkpoint_resume | state=stale:** Reconcile checkpoint state with active processes, current files, and the external system before continuing. Fixture: one or more memories or observations may have expired. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0021 | checkpoint_resume | state=conflict:** Reconcile checkpoint state with active processes, current files, and the external system before continuing. Fixture: two sources disagree on a material fact. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0022 | checkpoint_resume | state=restart:** Reconcile checkpoint state with active processes, current files, and the external system before continuing. Fixture: the task is resuming after an interruption. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0023 | checkpoint_resume | state=regression:** Reconcile checkpoint state with active processes, current files, and the external system before continuing. Fixture: a recent change might have broken a previously passing behavior. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0024 | checkpoint_resume | state=low_budget:** Reconcile checkpoint state with active processes, current files, and the external system before continuing. Fixture: tool or token budget is constrained. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0025 | lesson_capture | state=fresh:** Convert a reproducible failure into a root-cause hypothesis and regression test; avoid storing vague conclusions such as “be better”. Fixture: all evidence is current and consistent. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0026 | lesson_capture | state=stale:** Convert a reproducible failure into a root-cause hypothesis and regression test; avoid storing vague conclusions such as “be better”. Fixture: one or more memories or observations may have expired. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0027 | lesson_capture | state=conflict:** Convert a reproducible failure into a root-cause hypothesis and regression test; avoid storing vague conclusions such as “be better”. Fixture: two sources disagree on a material fact. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0028 | lesson_capture | state=restart:** Convert a reproducible failure into a root-cause hypothesis and regression test; avoid storing vague conclusions such as “be better”. Fixture: the task is resuming after an interruption. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0029 | lesson_capture | state=regression:** Convert a reproducible failure into a root-cause hypothesis and regression test; avoid storing vague conclusions such as “be better”. Fixture: a recent change might have broken a previously passing behavior. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0030 | lesson_capture | state=low_budget:** Convert a reproducible failure into a root-cause hypothesis and regression test; avoid storing vague conclusions such as “be better”. Fixture: tool or token budget is constrained. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0031 | agent_handoff | state=fresh:** Require artifacts, test commands, outcome, uncertainty, and next action; verify critical claims before merge. Fixture: all evidence is current and consistent. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0032 | agent_handoff | state=stale:** Require artifacts, test commands, outcome, uncertainty, and next action; verify critical claims before merge. Fixture: one or more memories or observations may have expired. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0033 | agent_handoff | state=conflict:** Require artifacts, test commands, outcome, uncertainty, and next action; verify critical claims before merge. Fixture: two sources disagree on a material fact. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0034 | agent_handoff | state=restart:** Require artifacts, test commands, outcome, uncertainty, and next action; verify critical claims before merge. Fixture: the task is resuming after an interruption. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0035 | agent_handoff | state=regression:** Require artifacts, test commands, outcome, uncertainty, and next action; verify critical claims before merge. Fixture: a recent change might have broken a previously passing behavior. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0036 | agent_handoff | state=low_budget:** Require artifacts, test commands, outcome, uncertainty, and next action; verify critical claims before merge. Fixture: tool or token budget is constrained. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0037 | context_bloat | state=fresh:** Retrieve relevant records and concise evidence summaries instead of injecting full conversation logs. Fixture: all evidence is current and consistent. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0038 | context_bloat | state=stale:** Retrieve relevant records and concise evidence summaries instead of injecting full conversation logs. Fixture: one or more memories or observations may have expired. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0039 | context_bloat | state=conflict:** Retrieve relevant records and concise evidence summaries instead of injecting full conversation logs. Fixture: two sources disagree on a material fact. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0040 | context_bloat | state=restart:** Retrieve relevant records and concise evidence summaries instead of injecting full conversation logs. Fixture: the task is resuming after an interruption. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0041 | context_bloat | state=regression:** Retrieve relevant records and concise evidence summaries instead of injecting full conversation logs. Fixture: a recent change might have broken a previously passing behavior. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0042 | context_bloat | state=low_budget:** Retrieve relevant records and concise evidence summaries instead of injecting full conversation logs. Fixture: tool or token budget is constrained. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0043 | data_retention | state=fresh:** Expire ephemeral state after its purpose ends and respect deletion, privacy, and project retention policy. Fixture: all evidence is current and consistent. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0044 | data_retention | state=stale:** Expire ephemeral state after its purpose ends and respect deletion, privacy, and project retention policy. Fixture: one or more memories or observations may have expired. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0045 | data_retention | state=conflict:** Expire ephemeral state after its purpose ends and respect deletion, privacy, and project retention policy. Fixture: two sources disagree on a material fact. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0046 | data_retention | state=restart:** Expire ephemeral state after its purpose ends and respect deletion, privacy, and project retention policy. Fixture: the task is resuming after an interruption. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0047 | data_retention | state=regression:** Expire ephemeral state after its purpose ends and respect deletion, privacy, and project retention policy. Fixture: a recent change might have broken a previously passing behavior. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.
- **M-0048 | data_retention | state=low_budget:** Expire ephemeral state after its purpose ends and respect deletion, privacy, and project retention policy. Fixture: tool or token budget is constrained. Acceptance: preserve provenance, distinguish verified state from assumption, make the smallest useful correction, and record reproducible lessons.

---

