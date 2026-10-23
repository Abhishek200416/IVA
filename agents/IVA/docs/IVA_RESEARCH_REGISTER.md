# AGI 1.7 — OMEGA COMMAND: Authoritative Research Register

**Document ID:** `REG-AGI17-PHASE1-20261010`  
**Version:** `1.7.0` (`OMEGA COMMAND`)  
**Foundation Model:** `gemini-3.8-flash-high` (Directive 0 Sole-Model Policy)  
**Scope:** Primary peer-reviewed literature, official framework specifications, operating system kernel documentation, and benchmark standards governing the architecture of AGI 1.7.

---

## Executive Summary & Epistemic Hygiene Policy

Every subsystem in **AGI 1.7 — OMEGA COMMAND** is grounded in verifiable computer science literature, systems engineering specifications, and empirical failure analysis of the AGI 1.6 baseline (`docs/AGI_1_7_BASELINE_AUDIT.md`). To maintain strict scientific integrity:

1. **Upstream Research vs. Local Claims:** Quantitative improvements reported in external papers (such as ACON's 26–54% peak token reduction or Agent Workflow Memory's 24.6%–51.1% relative success gains) are documented strictly as **upstream experimental findings under the authors' tested conditions**, never as guaranteed or pre-claimed AGI 1.7 metrics. All AGI 1.7 efficiency and accuracy claims must be independently proven via raw local telemetry (`token_ledger.jsonl`, `gpqa_clean_189_task_results.jsonl`, and Harbor `result.json`).
2. **Traceability:** Every entry records seven mandatory attributes: **Source URL**, **Publication Date / Status**, **Relevant Finding**, **Experimental Conditions**, **Evidence Limitations**, **Implementation Implication for AGI 1.7**, and **Validation Test**.

---

## 1. Agent OS & Orchestration

### 1.1 AIOS: LLM Agent Operating System
- **Source URL:** `https://arxiv.org/abs/2403.16971` | `https://github.com/agiresearch/AIOS`
- **Publication Date / Status:** March 2024 (COLM 2024 / v0.2+ Open-Source Release, 2024–2025)
- **Relevant Finding:** Decoupling LLM agent applications from kernel-level resource management via dedicated OS abstractions—an Agent Scheduler, Context Manager, Memory Manager, Storage Manager, Tool Manager, and Access Control Manager—prevents head-of-line blocking, isolates concurrent agent state, and improves multi-agent throughput under shared hardware constraints.
- **Experimental Conditions:** Evaluated concurrent execution of multiple heterogeneous agents (Math, Coding, Travel, RecSys) sharing local and API-backed LLMs under FIFO and Round-Robin scheduling policies across synthetic multi-agent workloads.
- **Evidence Limitations:** AIOS assumes an in-process Python server wrapping local HuggingFace/vLLM weights or standard REST APIs; it does not natively supervise external Windows CLI subprocess trees (`agy.exe`) or reconcile orphaned OS PIDs across process crashes.
- **Implementation Implication for AGI 1.7:** Adopt the kernel-service separation pattern (`CapabilityProfiler`, `ResourceGovernor`, `AdaptiveExecutionScheduler`, `TaskControlStore`, `PersistentMemoryService`, `ProcessSupervisor`) while implementing them over durable SQLite WAL storage and Win32 process supervision rather than an ephemeral in-memory server.
- **Validation Test:** `Unit Test 5` (`test_05_resource_governor_admission_and_hysteresis`), `Unit Test 6` (`test_06_scheduler_separate_queues_and_priority`), and `Integration Test F` (`test_F_concurrent_heterogeneous_workload_under_governor`).

### 1.2 Magentic-One & AutoGen: A Generalist Multi-Agent System for Solving Complex Tasks
- **Source URL:** `https://arxiv.org/abs/2411.04468` | `https://github.com/microsoft/autogen`
- **Publication Date / Status:** November 2024 (Microsoft Research Technical Report & AutoGen v0.4 Core/AgentChat Release)
- **Relevant Finding:** A dual-ledger Orchestrator pattern—maintaining a **Task Ledger** (established facts, assumptions, and high-level plan) and a **Progress Ledger** (step-by-step self-reflection on completeness, stalls, loops, and next speaker selection)—prevents infinite cyclic delegation and enables structured replanning when specialist agents fail.
- **Experimental Conditions:** Evaluated across GAIA, AssistantBench, and WebArena using a Lead Orchestrator coordinating four specialist workers (`WebSurfer`, `FileSurfer`, `Coder`, `ComputerTerminal`) inside Dockerized execution environments.
- **Evidence Limitations:** Multi-agent outer/inner loop replanning significantly increases cumulative input token consumption when full conversation histories are broadcast across turns, and unregulated container spawning can exhaust host RAM on memory-constrained Windows machines.
- **Implementation Implication for AGI 1.7:** Separate the **Task Ledger** (persisted in SQLite `tasks` and `task_events` tables) from the **Progress Ledger** (checkpoint evaluations and stall detection in `OmegaCommandOrchestrator`), enforce bounded delegation depth (`max_delegation_depth = 3`, `max_messages_per_task = 50`), and pass compact structured artifacts rather than raw multi-turn transcripts to child specialists.
- **Validation Test:** `Unit Test 7` (`test_07_task_state_machine_and_parent_child_tree`), `Unit Test 18` (`test_18_specialist_router_decomposition_and_no_fanout_for_simple`), and `Integration Test A` (`test_A_substantial_task_auto_spawns_real_child_agents`).

### 1.3 LangGraph Persistence & Checkpointers
- **Source URL:** `https://langchain-ai.github.io/langgraph/concepts/persistence/` | `https://github.com/langchain-ai/langgraph`
- **Publication Date / Status:** 2024–2026 (Production Documentation, `langgraph-checkpoint-sqlite` v2.x)
- **Relevant Finding:** Modeling agent workflows as state graphs with super-step transactional checkpoints keyed by `thread_id` and `checkpoint_ns` enables deterministic fault recovery, time-travel inspection, human-in-the-loop interrupts, and resumption from the last verified node without re-executing completed upstream tool calls.
- **Experimental Conditions:** Architectural specification and reference implementation using SQLite and PostgreSQL backing stores across synchronous and asynchronous Python graph runners.
- **Evidence Limitations:** Serializing full framework-specific graph state blobs on every super-step introduces schema coupling to LangChain message classes and can cause SQLite `SQLITE_BUSY` lock contention under high thread concurrency if WAL mode and busy timeouts are not tuned.
- **Implementation Implication for AGI 1.7:** Implement explicit state-machine checkpointing in `engine/agi17/task_control/task_store.py` using Python stdlib `sqlite3` with `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;`, storing fine-grained checkpoint snapshots (`checkpoints` table) before and after every model or tool invocation.
- **Validation Test:** `Unit Test 7` (`test_07_task_state_machine_and_parent_child_tree`), `Unit Test 10` (`test_10_restart_reconciliation_recovers_interrupted_tasks`), and `Integration Test J` (`test_J_crash_recovery_resumes_from_sqlite_wal_checkpoint`).

### 1.4 Microsoft Agent Framework Checkpoints & State Management
- **Source URL:** `https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/` | `https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/framework/state.html`
- **Publication Date / Status:** 2024–2026 (Microsoft Learn & AutoGen v0.4 State Serialization Spec)
- **Relevant Finding:** Explicit `save_state()` / `load_state()` contracts at both the individual agent level and the runtime team/orchestrator level allow long-running workflows to pause, serialize active task queues and memory references to durable storage, and resume in a new OS process.
- **Experimental Conditions:** Reference enterprise agent runtime patterns across .NET and Python SDKs.
- **Evidence Limitations:** Framework-level `save_state()` only captures in-memory Python/C# state; it does not track external child OS processes (`Popen`) or background downloads that outlive the parent runtime process.
- **Implementation Implication for AGI 1.7:** Combine orchestrator checkpoint serialization with a persistent `ProcessSupervisor` table (`supervised_processes`) that records OS `pid`, `creation_time`, `cmd`, `stdout_path`, `stderr_path`, and `expected_artifacts`, enabling true cross-restart reconciliation of both logical state and live OS processes.
- **Validation Test:** `Unit Test 10` (`test_10_restart_reconciliation_recovers_interrupted_tasks`) and `Integration Test E` (`test_E_long_running_process_heartbeats_and_restart_reconciliation`).

### 1.5 Temporal Workflow Message Passing (Signals, Queries, Updates)
- **Source URL:** `https://docs.temporal.io/develop/python/message-passing` | `https://github.com/temporalio/sdk-python`
- **Publication Date / Status:** 2024–2026 (Temporal Technologies Official Documentation)
- **Relevant Finding:** Separating asynchronous state-mutating **Signals** (fire-and-forget durable events), synchronous validated **Updates** (atomic state mutation + response with rejection on invalid state), and read-only **Queries** (inspecting live workflow state without mutation) eliminates race conditions when steering or canceling in-flight workflows.
- **Experimental Conditions:** Production distributed workflow engine guarantees backed by event-sourced history logs.
- **Evidence Limitations:** Full Temporal deployment requires running an external Temporal Server cluster and database backend, adding significant memory and container overhead unsuitable for a self-contained single-host Windows runtime.
- **Implementation Implication for AGI 1.7:** Implement Temporal's Signal / Update / Query semantics locally in `engine/agi17/task_control/command_inbox.py` and `agi17ctl.py` backed by SQLite WAL transactions: `APPEND_CONSTRAINTS`, `REDIRECT_OBJECTIVE`, `PRIORITIZE_CHILD`, `SPAWN_CHILD_TASK`, `PAUSE_TASK`, `RESUME_TASK`, and `CANCEL_TASK` act as durable transactional Updates/Signals polled at every safe checkpoint boundary, while `STATUS_QUERY` executes as a read-only Query.
- **Validation Test:** `Unit Test 8` (`test_08_command_inbox_all_control_operations`), `Unit Test 9` (`test_09_checkpoint_polling_applies_live_command_mid_run`), `Integration Test B` (`test_B_live_mid_run_instruction_redirect_and_constraint_append`), and `Integration Test C` (`test_C_attach_child_task_to_existing_parent_job_and_merge`).

### 1.6 PydanticAI Usage Limits & Concurrency Controls
- **Source URL:** `https://ai.pydantic.dev/agents/#usage-limits` | `https://github.com/pydantic/pydantic-ai`
- **Publication Date / Status:** 2024–2026 (Pydantic Services Official Documentation)
- **Relevant Finding:** Enforcing hard pre-call and post-call `UsageLimits(request_limit=..., input_tokens_limit=..., output_tokens_limit=..., total_tokens_limit=...)` directly inside the agent execution loop halts runaway tool/reasoning loops immediately upon threshold violation before additional model calls are dispatched.
- **Experimental Conditions:** Typed Python agent execution with synchronous and asynchronous model adapters.
- **Evidence Limitations:** PydanticAI checks token counters only after a model response or stream chunk returns; when wrapping an external CLI (`agy.exe`), if the CLI runs an unrestricted internal multi-turn loop in a polluted working directory, a single CLI invocation can burn >200,000 tokens before returning.
- **Implementation Implication for AGI 1.7:** Pair hard per-task and per-call `UsageLimits` in `engine/agi17/telemetry/token_economy.py` with **pre-call working-directory isolation** (`isolated_benchmark_cwd`) and explicit single-shot tool suppression on closed-book tasks so individual CLI calls cannot silently loop.
- **Validation Test:** `Unit Test 19` (`test_19_token_budget_controller_enforces_hard_caps_and_reserves`), `Unit Test 20` (`test_20_token_accounting_normalizes_cumulative_and_failed_calls`), and `Integration Test H` (`test_H_token_budget_controller_stops_runaway_loop_and_isolates_cwd`).

### 1.7 OpenHands Software-Agent SDK (formerly OpenDevin)
- **Source URL:** `https://arxiv.org/abs/2407.16741` | `https://github.com/All-Hands-AI/OpenHands`
- **Publication Date / Status:** July 2024 / ICLR 2025 (`OpenHands: An Open Platform for AI Software Developers as Generalist Agents`)
- **Relevant Finding:** Standardizing agent-environment interaction as an **EventStream** of typed `Action` and `Observation` events with sandboxed execution runtime containers and explicit condensation of stale observations enables reliable software engineering and bash execution across long trajectories.
- **Experimental Conditions:** Evaluated across SWE-bench, HumanEvalFix, GAIA, and GPQA using Docker-sandboxed Jupyter + Bash execution environments.
- **Evidence Limitations:** Spawning a persistent Docker runtime container per agent session incurs high startup latency (5–20s) and 500MB–2GB RAM overhead per worker on Windows WSL2.
- **Implementation Implication for AGI 1.7:** Adopt the typed `Action` -> `Observation` -> `EventLog` architecture in `TaskControlStore` (`task_events.jsonl` + SQLite `task_events`) and use lightweight local process isolation (`ProcessSupervisor` + isolated `cwd`) for standard CLI/Python tasks, reserving Docker containers strictly for benchmarks or tasks requiring container sandboxes (e.g., Harbor Terminal-Bench 2.0).
- **Validation Test:** `Unit Test 11` (`test_11_process_supervisor_streaming_and_completion_event`) and `Integration Test D` (`test_D_terminal_command_completion_returns_outcome_to_parent`).

### 1.8 smolagents
- **Source URL:** `https://github.com/huggingface/smolagents` | `https://huggingface.co/docs/smolagents`
- **Publication Date / Status:** December 2024–2026 (Hugging Face Official Library)
- **Relevant Finding:** Keeping orchestration code minimal (~1,000 lines of core logic) and expressing deterministic multi-step transformations directly as executable Python actions rather than verbose JSON tool-call chains reduces orchestration latency and intermediate token overhead.
- **Experimental Conditions:** Comparative evaluations on GAIA and tool-use benchmarks comparing code-action agents against JSON-schema tool-calling agents.
- **Evidence Limitations:** Arbitrary LLM-generated Python execution without AST verification and permission boundaries risks destructive host filesystem or network operations.
- **Implementation Implication for AGI 1.7:** Keep the AGI 1.7 runtime lean (zero external orchestration framework dependencies), route deterministic computations (`SIMPLE` tier tasks, checksum verification, ledger aggregation) directly to fast local Python execution without multi-agent LLM fan-out, and enforce AST + permission policy validation (`permissions_policy.json`) before executing generated code.
- **Validation Test:** `Unit Test 18` (`test_18_specialist_router_decomposition_and_no_fanout_for_simple`) and `Unit Test 23` (`test_23_security_and_host_safety_guards`).

### 1.9 Google ADK Python (Agent Development Kit)
- **Source URL:** `https://google.github.io/adk-docs/` | `https://github.com/google/adk-python`
- **Publication Date / Status:** 2025–2026 (Google Official Open-Source SDK)
- **Relevant Finding:** Structuring multi-agent systems into deterministic workflow primitives (`SequentialAgent`, `ParallelAgent`, `LoopAgent`) combined with dynamic LLM-driven routing (`LlmAgent` transfer) and explicit `Session` / `Memory` / `Artifact` services provides predictable control flow with low cognitive overhead.
- **Experimental Conditions:** Gemini-native multi-agent orchestration across cloud and local Python environments.
- **Evidence Limitations:** Requires the `google-adk` dependency tree and direct Gemini REST/gRPC API credentials, whereas AGI 1.7 operates under Directive 0 via the local `%LOCALAPPDATA%\agy\bin\agy.exe` CLI binary (`gemini-3.8-flash-high`).
- **Implementation Implication for AGI 1.7:** Implement the sequential, parallel-wavefront, and bounded-loop execution patterns natively inside `OmegaCommandOrchestrator` and `AdaptiveExecutionScheduler` over `agy.exe` adapters, preserving explicit `Session`, `Memory`, and `Artifact` contracts.
- **Validation Test:** `Unit Test 6` (`test_06_scheduler_separate_queues_and_priority`) and `Integration Test A` (`test_A_substantial_task_auto_spawns_real_child_agents`).

### 1.10 CrewAI
- **Source URL:** `https://github.com/crewAIInc/crewAI` | `https://docs.crewai.com/`
- **Publication Date / Status:** 2024–2026 (CrewAI Inc., v0.80+ / Flows & Crews Architecture)
- **Relevant Finding:** Separating event-driven deterministic **Flows** (state management, branching, loop control) from role-specialized **Crews** (collaborative agents with explicit `role`, `goal`, `backstory`, `tools`, and `expected_output` schemas) improves output schema compliance.
- **Experimental Conditions:** Role-playing multi-agent task automation workflows.
- **Evidence Limitations:** Verbose persona/backstory prompting inflates input token counts on every turn, and sequential role handoffs degrade latency when applied to single-step analytical tasks.
- **Implementation Implication for AGI 1.7:** Define concise, schema-validated contracts for all 100 specialist agents (`ecosystem/agent_registry/specialist_registry.json`) with explicit `input_schema`, `output_schema`, `allowed_tools`, `max_tokens`, and `verification_policy`, omitting verbose persona boilerplate to conserve prompt tokens.
- **Validation Test:** `Unit Test 16` (`test_16_specialist_registry_100_unique_contracts_valid`), `Unit Test 17` (`test_17_all_16_specialist_families_executable_invocations`), and `Integration Test G` (`test_G_100_specialist_registry_validation_and_16_family_execution`).

### 1.11 MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework
- **Source URL:** `https://arxiv.org/abs/2308.00352` | `https://github.com/geekan/MetaGPT`
- **Publication Date / Status:** August 2023 / ICLR 2024 Oral
- **Relevant Finding:** Encoding Standardized Operating Procedures (SOPs) into multi-agent workflows by requiring agents to publish structured intermediate deliverables (PRDs, system interface designs, dependency graphs, unit test suites) rather than unstructured chat messages drastically reduces cascading hallucinations in multi-file software generation.
- **Experimental Conditions:** Evaluated on HumanEval, MBPP, and SoftwareDev benchmarks using role-specialized agents (`ProductManager`, `Architect`, `ProjectManager`, `Engineer`, `QA`).
- **Evidence Limitations:** Rigid waterfall SOP pipelines over-allocate tokens and latency when applied to bug fixes, single-file edits, or closed-book question answering.
- **Implementation Implication for AGI 1.7:** Require structured JSON/artifact handoffs (`ChildTaskResult` with verified file paths, SHA-256 hashes, exit codes, and evidence citations) between parent and child tasks while allowing the `TaskComplexityClassifier` to bypass multi-stage SOPs for `SIMPLE` and `STANDARD` tasks.
- **Validation Test:** `Unit Test 18` (`test_18_specialist_router_decomposition_and_no_fanout_for_simple`) and `Integration Test A` (`test_A_substantial_task_auto_spawns_real_child_agents`).

### 1.12 CAMEL: Communicative Agents for "Mind" Exploration of Large Scale Language Model Society
- **Source URL:** `https://arxiv.org/abs/2303.17760` | `https://github.com/camel-ai/camel`
- **Publication Date / Status:** March 2023 / NeurIPS 2023
- **Relevant Finding:** Dual-agent inception prompting (an AI User/Planner instructing an AI Assistant/Executor) suffers from conversation loop phenomena, false completion announcements ("I have completed the task" without action), and role-flipping unless bounded by explicit termination predicates and external verification.
- **Experimental Conditions:** Autonomous role-playing dialogues across coding and reasoning tasks.
- **Evidence Limitations:** Purely conversational termination detection relies on linguistic markers rather than ground-truth filesystem or process exit verification.
- **Implementation Implication for AGI 1.7:** Directly addresses **AGI 1.6 Defect 1 & Defect 4**: no child worker or terminal task in AGI 1.7 may transition to `VERIFIED` or `COMPLETED` based solely on text generation; completion requires deterministic `EvidenceVerifier` checks (process `exit_code == 0`, non-empty output artifact, valid AST/JSON, or verified benchmark answer format).
- **Validation Test:** `Unit Test 12` (`test_12_process_supervisor_detects_missing_or_corrupt_artifact`) and `Integration Test D` (`test_D_terminal_command_completion_returns_outcome_to_parent`).

### 1.13 AgentScope: A Flexible yet Robust Multi-Agent Platform
- **Source URL:** `https://arxiv.org/abs/2402.14034` | `https://github.com/modelscope/agentscope`
- **Publication Date / Status:** February 2024 / VLDB 2024 Demonstration
- **Relevant Finding:** Built-in fault tolerance via automatic retry with exponential backoff, rule-based output parsing repair, and centralized实时 (real-time) telemetry monitoring of token usage and agent message graphs prevents single-step formatting glitches from aborting entire multi-agent runs.
- **Experimental Conditions:** Distributed and local multi-agent simulations with fault injection.
- **Evidence Limitations:** Retrying timed-out or malformed LLM calls without inspecting remaining task token budget or host CPU/RAM saturation can amplify cascading overload (as seen in AGI 1.6 Defect 7 and Defect 8).
- **Implementation Implication for AGI 1.7:** Gate all retries in `OmegaCommandOrchestrator` and `AGIAgentAdapter` behind both `ResourceGovernor.can_admit()` and `TokenBudgetController.has_recovery_reserve()`, ensuring transient retries only occur when sufficient budget (`recovery_reserve_ratio`: 10–15%) and host headroom exist.
- **Validation Test:** `Unit Test 19` (`test_19_token_budget_controller_enforces_hard_caps_and_reserves`) and `Integration Test H` (`test_H_token_budget_controller_stops_runaway_loop_and_isolates_cwd`).

---

## 2. Memory & Context Optimization

### 2.1 ACON: Optimizing Context Compression for Long-Horizon LLM Agents
- **Source URL:** `https://arxiv.org/abs/2510.00615` | `https://proceedings.mlr.press/v306/kang26b.html`
- **Publication Date / Status:** October 2025 / PMLR v306 (`kang26b`, 2026)
- **Relevant Finding:** Adaptive, task-aware context compression of environment observations and interaction histories—guided by failure contrast and preservation of task-critical signals—reported **26–54% lower peak token usage** in the authors' evaluated long-horizon agent benchmarks while preserving task accuracy. *(Note: This 26–54% figure is strictly an upstream research finding under the authors' experimental setup, not a pre-claimed or guaranteed AGI 1.7 metric).*
- **Experimental Conditions:** Evaluated on AppWorld, OfficeBench, and multi-turn QA tasks comparing uncompressed histories, naive truncation, LLM summarization, and failure-driven adaptive compression guideline optimization.
- **Evidence Limitations:** Purely abstractive LLM-based context compression can accidentally strip exact identifiers (UUIDs, SHA-256 digests, file paths, negative constraints, or exact stack trace error codes), causing downstream verification failures.
- **Implementation Implication for AGI 1.7:** Implement `AdaptiveContextCompressor` in `engine/agi17/memory/acon_compressor.py` as a **hybrid lossless-anchor + adaptive window compressor**: it deterministically extracts and locks exact file paths, SHA-256 hashes, task IDs, numeric constraints, exit codes, and error tracebacks into an immutable `preserved_anchors` block before compressing repetitive intermediate log lines, and validates via assertion that 100% of anchors survive compression.
- **Validation Test:** `Unit Test 15` (`test_15_acon_compression_preserves_exact_anchors_and_saves_tokens`) and `Integration Test I` (`test_I_persistent_memory_cross_session_supersession_and_acon`).

### 2.2 LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory
- **Source URL:** `https://arxiv.org/abs/2410.10813` | `https://github.com/xiaowu0162/LongMemEval`
- **Publication Date / Status:** October 2024 / ICLR 2025
- **Relevant Finding:** Evaluates long-term memory across **500 curated questions** testing five core memory abilities: (1) **Information Extraction**, (2) **Multi-Session Reasoning**, (3) **Temporal Reasoning**, (4) **Knowledge Updates** (recognizing when a newer fact supersedes an older fact), and (5) **Abstention** (refusing to answer when evidence is absent from memory). Standard RAG and long-context models suffer 30–60% accuracy drops on temporal updates and multi-session aggregation when records are stored as flat unindexed chunks.
- **Experimental Conditions:** 500 evaluation instances embedded in timestamped multi-session interaction histories scaling from 115k to 1.5M tokens.
- **Evidence Limitations:** Designed primarily around user-assistant conversational histories rather than autonomous system/process execution telemetry.
- **Implementation Implication for AGI 1.7:** Directly remedies **AGI 1.6 Defect 6**: structure `PersistentMemoryService` (`engine/agi17/memory/persistent_memory.py`) around explicit `fact_key`, `version`, `supersedes_id`, `valid_from`, `valid_until`, `status` (`ACTIVE` vs `SUPERSEDED`), and `provenance_task_id` columns in SQLite, with a mandatory `retrieve_before_planning()` hook and explicit `ABSTAIN_INSUFFICIENT_MEMORY_EVIDENCE` support when queried keys do not exist.
- **Validation Test:** `Unit Test 13` (`test_13_memory_10_layers_write_and_mandatory_retrieve_before_planning`), `Unit Test 14` (`test_14_memory_fact_supersession_conflict_and_abstention`), and `Integration Test I` (`test_I_persistent_memory_cross_session_supersession_and_acon`).

### 2.3 LoCoMo: Evaluating Very Long-Term Conversational Memory of LLM Agents
- **Source URL:** `https://aclanthology.org/2024.acl-long.747/` | `https://arxiv.org/abs/2402.17753`
- **Publication Date / Status:** August 2024 (ACL 2024 Long Papers, pp. 13838–13870)
- **Relevant Finding:** Across multi-session interactions spanning dozens of sessions and thousands of turns, hierarchical memory indexing combining raw episodic logs, temporal event summaries, and distilled factual assertions significantly outperforms both raw context stuffing and flat vector retrieval on temporal and causal reasoning questions.
- **Experimental Conditions:** Long-term multimodal multi-session dialogues evaluated across single-hop, multi-hop, temporal, open-domain, and adversarial/unanswerable QA tasks.
- **Evidence Limitations:** Relies on periodic offline LLM summarization passes, which can introduce latency if run synchronously on the critical path of every tool call.
- **Implementation Implication for AGI 1.7:** Partition AGI 1.7 memory into **10 explicit functional layers** (`WORKING_CONTEXT`, `EPISODIC_TASK_HISTORY`, `SEMANTIC_FACTS`, `PROCEDURAL_SKILLS`, `ENVIRONMENT_PROFILES`, `BENCHMARK_ARTIFACTS`, `FAILURE_REMEDIATION`, `USER_CONSTRAINTS`, `SUPERSEDED_AUDIT_ARCHIVE`, and `CHECKPOINT_RECOVERY_STATE`) with fast synchronous SQLite FTS/indexed retrieval on the planning path.
- **Validation Test:** `Unit Test 13` (`test_13_memory_10_layers_write_and_mandatory_retrieve_before_planning`).

### 2.4 MemoryArena: Benchmarking Long-Context Memory in Autonomous Agents
- **Source URL:** `https://memoryarena.github.io/`
- **Publication Date / Status:** 2025–2026 (Open Benchmark Suite)
- **Relevant Finding:** Agent memory failures in autonomous workflows cluster around three failure modes: **entity attribute collision** (mixing attributes of similarly named tasks or hosts), **temporal attribute drift** (returning stale state from earlier sessions after a setting changed), and **write-without-read disconnection** (writing logs that are never queried in subsequent sessions).
- **Experimental Conditions:** Multi-session state-tracking and attribute-resolution tasks under distracting intermediate workloads.
- **Evidence Limitations:** Synthetic entity-tracking distributions must be paired with real system-state verification to reflect production agent workloads.
- **Implementation Implication for AGI 1.7:** Enforce keyed entity-attribute indexing (`entity_id`, `fact_key`) with strict version ordering so queries always return the latest `ACTIVE` record while linking the chain of `SUPERSEDED` historical values for auditability, and enforce `retrieve_before_planning()` on every new session.
- **Validation Test:** `Unit Test 14` (`test_14_memory_fact_supersession_conflict_and_abstention`) and `Integration Test I` (`test_I_persistent_memory_cross_session_supersession_and_acon`).

### 2.5 A-Mem: Agentic Memory for LLM Agents
- **Source URL:** `https://arxiv.org/abs/2502.12110`
- **Publication Date / Status:** February 2025 (arXiv Preprint `2502.12110`)
- **Relevant Finding:** Organizing agent memories using Zettelkasten-inspired structured notes—containing atomic content, contextual tags, keywords, and explicit bidirectional links to related historical notes—improves multi-hop retrieval relevance over unlinked chunk stores.
- **Experimental Conditions:** Evaluated on LoCoMo and long-horizon QA datasets across multiple foundation models.
- **Evidence Limitations:** Triggering an LLM call on every memory insertion to regenerate note links adds prohibitive token and latency overhead during high-frequency telemetry logging.
- **Implementation Implication for AGI 1.7:** Store deterministic structured metadata (`tags`, `related_task_ids`, `supersedes_id`, `artifact_hashes`) on every memory record at write time without incurring extra LLM calls per write.
- **Validation Test:** `Unit Test 13` (`test_13_memory_10_layers_write_and_mandatory_retrieve_before_planning`).

### 2.6 MemoryOS: Memory Operating System for Personalized AI Agents
- **Source URL:** `https://arxiv.org/abs/2506.06326`
- **Publication Date / Status:** June 2025 / EMNLP 2025
- **Relevant Finding:** Applying operating-system memory hierarchy principles—Short-Term Memory (STM) working pages, Mid-Term Memory (MTM) FIFO/segmented session pages, and Long-Term Personal/System Memory (LPM) persistent storage with heat-based page promotion and eviction—prevents context window overflow while retaining high-utility operational constraints.
- **Experimental Conditions:** Evaluated on LoCoMo and multi-session dialogue benchmarks demonstrating F1 and BLEU improvements over flat baselines.
- **Evidence Limitations:** Heat-based eviction must never evict active user safety constraints or pinned mission directives (`USER_CONSTRAINTS` layer).
- **Implementation Implication for AGI 1.7:** Pin records in `USER_CONSTRAINTS` and `ENVIRONMENT_PROFILES` against eviction, use `WORKING_CONTEXT` as bounded STM, and promote verified task outcomes and failure lessons into durable SQLite LPM tables.
- **Validation Test:** `Unit Test 13` (`test_13_memory_10_layers_write_and_mandatory_retrieve_before_planning`) and `Integration Test B` (`test_B_live_mid_run_instruction_redirect_and_constraint_append`).

### 2.7 Agent Workflow Memory (AWM)
- **Source URL:** `https://arxiv.org/abs/2409.07429` | `https://proceedings.mlr.press/v267/wang25bx.html`
- **Publication Date / Status:** September 2024 / ICML 2025 (PMLR v267 `wang25bx`)
- **Relevant Finding:** Inducing reusable, parameterized workflow routines from successful past trajectories and injecting them into future planning prompts yielded **24.6% relative success rate improvement on Mind2Web** and **51.1% on WebArena** in the authors' tested settings, while reducing the number of steps required to complete recurring sub-routines. *(Note: Reported strictly as the authors' benchmark result on Mind2Web/WebArena).*
- **Experimental Conditions:** Online and offline workflow induction on WebArena and Mind2Web web-navigation tasks.
- **Evidence Limitations:** Inducing workflows from unverified or failed trajectories degrades downstream performance by propagating buggy procedures.
- **Implementation Implication for AGI 1.7:** Only promote procedural workflows to Layer 4 (`PROCEDURAL_SKILLS`) and failure-remediation recipes to Layer 7 (`FAILURE_REMEDIATION`) after `EvidenceVerifier` confirms `VERIFIED_PASS` on the source task.
- **Validation Test:** `Unit Test 13` (`test_13_memory_10_layers_write_and_mandatory_retrieve_before_planning`) and `Integration Test I` (`test_I_persistent_memory_cross_session_supersession_and_acon`).

### 2.8 Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory
- **Source URL:** `https://arxiv.org/abs/2504.19413` | `https://github.com/mem0ai/mem0`
- **Publication Date / Status:** April 2025 (Technical Report & Open-Source SDK)
- **Relevant Finding:** An explicit extraction-and-update pipeline that classifies incoming candidate facts into `ADD`, `UPDATE` (with conflict resolution), `DELETE`, or `NOOP` operations against existing memory records reduces redundant storage and cuts retrieval token overhead compared to full-conversation context windows.
- **Experimental Conditions:** Evaluated on LOCOMO benchmark categories (single-hop, multi-hop, temporal, open-domain) measuring latency, token consumption, and answer quality.
- **Evidence Limitations:** Mem0's default cloud/vector-DB pipeline relies on LLM calls for every `ADD/UPDATE/DELETE` classification and external vector/graph stores (Qdrant/Neo4j).
- **Implementation Implication for AGI 1.7:** Implement deterministic key-based `ADD` / `UPDATE` (`SUPERSEDED` transition) / `DELETE` (`REVOKED` transition) / `NOOP` (content hash deduplication) directly in SQLite (`engine/agi17/memory/persistent_memory.py`) with zero external database dependencies and zero extra LLM calls on deterministic fact updates.
- **Validation Test:** `Unit Test 14` (`test_14_memory_fact_supersession_conflict_and_abstention`).

### 2.9 Letta (formerly MemGPT: Towards LLMs as Operating Systems)
- **Source URL:** `https://arxiv.org/abs/2310.08560` | `https://github.com/letta-ai/letta`
- **Publication Date / Status:** October 2023 / 2024–2026 (UC Berkeley / Letta AI)
- **Relevant Finding:** Virtualizing context management by dividing memory into **Core Memory** (in-context pinned blocks editable via explicit function calls like `core_memory_replace`) and **Archival / Recall Memory** (out-of-context persistent database queried on demand) allows bounded-context agents to maintain state across arbitrarily long lifespans.
- **Experimental Conditions:** Evaluated on deep document analysis and multi-session conversational consistency tasks.
- **Evidence Limitations:** Relying solely on the LLM to voluntarily invoke `archival_memory_search` fails when the model skips retrieval on a new session (the exact failure mode observed in **AGI 1.6 Defect 6**).
- **Implementation Implication for AGI 1.7:** Do not leave initial memory retrieval to model discretion: enforce a mandatory runtime pre-planning hook (`PersistentMemoryService.retrieve_before_planning(goal, task_context)`) inside `OmegaCommandOrchestrator` before the first planning or execution prompt is constructed, while also exposing explicit memory read/write tools for mid-task updates.
- **Validation Test:** `Unit Test 13` (`test_13_memory_10_layers_write_and_mandatory_retrieve_before_planning`) and `Integration Test I` (`test_I_persistent_memory_cross_session_supersession_and_acon`).

---

## 3. Benchmarks & Tool Use

### 3.1 GPQA Diamond Clean v1.2.2
- **Source URL:** `https://arxiv.org/abs/2311.12022` | `https://github.com/idavidrein/gpqa` | `https://github.com/adamallcock/gpqa-diamond-clean`
- **Publication Date / Status:** November 2023 (COLM 2024 Base Paper) / Clean v1.2.2 Release (2025–2026)
- **Relevant Finding:** GPQA (Graduate-Level Google-Proof Q&A) tests frontier scientific reasoning across biology, physics, and chemistry. The **GPQA Diamond Clean v1.2.2** audit identified **9 objectively flawed/corrupted items** in the original 198-question Diamond split (typos in formulas, missing reaction conditions, or erroneous gold keys), yielding a verified **189-question clean evaluation set** (`cleaned.jsonl` SHA-256: `c04c551a71da14d802841ec1a5dd3aa83fbcbe22e89b4cd6c6aef3c690c00e8d`).
- **Experimental Conditions:** Closed-book, single-attempt 4-way multiple-choice evaluation with deterministic option shuffling (`seed = 42 + item_idx`).
- **Evidence Limitations:** When evaluated via CLI agents (`agy.exe`), running inside a non-empty repository root leaks workspace files and tool schemas into the prompt, inflating input tokens by 10x–90x and causing subprocess timeouts (as proven in **AGI 1.6 Defect 7**, where 189 items consumed `8,164,321` tokens and suffered 14 timeouts).
- **Implementation Implication for AGI 1.7:** Enforce `isolated_cwd = D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\isolated_cwd` (verified empty directory), closed-book single-shot prompt rules (no workspace tool exploration), bounded concurrency (`MAX_ACTIVE_EXECUTIONS <= 4`), and a pre-campaign **3–5 item non-scored calibration canary** verifying ~2,200–2,500 input tokens per call before any scored campaign execution.
- **Validation Test:** `Unit Test 20` (`test_20_token_accounting_normalizes_cumulative_and_failed_calls`), `Integration Test H` (`test_H_token_budget_controller_stops_runaway_loop_and_isolates_cwd`), and `Integration Test M` (`test_M_benchmark_calibration_canary_and_reconciliation_audit`).

### 3.2 Terminal-Bench 2.0
- **Source URL:** `https://www.tbench.ai/` | `https://github.com/harbor-framework/terminal-bench-2`
- **Publication Date / Status:** 2025–2026 (Laude Institute / Stanford & Community Benchmark Release `terminal-bench@2.0`)
- **Relevant Finding:** Evaluates autonomous CLI agents across **89 real-world container-isolated system administration, compilation, debugging, data recovery, and scientific computing tasks**, graded strictly by post-execution container state verification tests (`pytest` verifier scripts inside the container) rather than LLM self-report.
- **Experimental Conditions:** Docker-isolated Linux task containers orchestrated via the official Harbor harness (`harbor_env`).
- **Evidence Limitations:** Requires a healthy Docker Engine / WSL2 daemon and sufficient disk/RAM headroom per active trial container; local Python mocks (such as `print('d2d4')` in AGI 1.6 `run_terminal_bench_2.py`) are invalid and do not constitute official Terminal-Bench 2.0 execution.
- **Implementation Implication for AGI 1.7:** Forbid simulated local print stubs (**AGI 1.6 Defect 10**); integrate directly with the official `harbor` CLI and `terminal-bench@2.0` dataset (`89` tasks), supervise trial containers via `ProcessSupervisor` and `ResourceGovernor` (`active_docker_tasks <= 2`), and report exact Harbor `result.json` outcomes (`resolved`, `unresolved`, `error`, or `BLOCKED` if Docker is unavailable).
- **Validation Test:** `Integration Test D` (`test_D_terminal_command_completion_returns_outcome_to_parent`) and `Integration Test M` (`test_M_benchmark_calibration_canary_and_reconciliation_audit`).

### 3.3 Harbor Framework
- **Source URL:** `https://github.com/harbor-framework/harbor`
- **Publication Date / Status:** 2025–2026 (Official Containerized Agent Evaluation Harness)
- **Relevant Finding:** Harbor provides standardized container lifecycle management, agent adapter injection, timeout enforcement, and deterministic post-trial verification (`result.json` generation) for Terminal-Bench 2.0 and related CLI benchmarks.
- **Experimental Conditions:** Python evaluation harness managing Docker Compose / container builds and verifier execution on Linux, macOS, and Windows (via Docker Desktop / WSL2).
- **Evidence Limitations:** If a Harbor process is killed mid-trial without container cleanup or parent process supervision, `result.json` retains `"finished_at": null` and `"n_running_trials": 1` indefinitely (proven in **AGI 1.6 Defect 4**).
- **Implementation Implication for AGI 1.7:** Wrap Harbor invocations in `ProcessSupervisor` so that trial progress, container health, timeout cleanup, and final `result.json` reconciliation are tracked deterministically and reported back to the parent job.
- **Validation Test:** `Unit Test 11` (`test_11_process_supervisor_streaming_and_completion_event`) and `Integration Test D` (`test_D_terminal_command_completion_returns_outcome_to_parent`).

### 3.4 OSWorld-V2.1 (OSWorld-Verified)
- **Source URL:** `https://arxiv.org/abs/2404.07972` | `https://os-world.github.io/` | `https://github.com/xlang-ai/OSWorld-V2`
- **Publication Date / Status:** April 2024 (NeurIPS 2024) / OSWorld-V2.1 Release (`osworld-v2.1.json`, 2025–2026)
- **Relevant Finding:** Evaluates multimodal computer-use agents across real desktop operating system environments (Ubuntu/Windows QEMU-KVM/Docker VMs) using execution-based evaluation scripts. The `osworld-v2.1` release manifest defines **108 curated task files** requiring a verified `14,891,811,084`-byte VM archive (`SHA-256: 14b08aa7ba6c023ecb91d46de8df5de32af4d1d6bd75ea925519caf9677fc8b3`) unpacked to `osworld-v2-ubuntu-x86.qcow2`.
- **Experimental Conditions:** Isolated QEMU/Docker VM running a full Ubuntu desktop with accessibility tree + screenshot observations and mouse/keyboard action space.
- **Evidence Limitations:** Launching QEMU/Docker VMs requires complete VM image verification and virtualization readiness; executing mouse/keyboard actions directly on the host Windows desktop violates safety boundaries.
- **Implementation Implication for AGI 1.7:** Enforce strict host desktop protection (`allow_host_gui_actuation = false` in `permissions_policy.json`), monitor existing background VM download processes (`PID 20556` and `PID 22884`) non-destructively via `CapabilityProfiler` and `ProcessSupervisor` without spawning duplicate downloaders (**AGI 1.6 Defect 5**), verify exact byte size and SHA-256 before marking VM readiness `READY`, and report honest `IN_PROGRESS` / `BLOCKED_VM_IMAGE_INCOMPLETE` status if the 14.89 GB image is still downloading.
- **Validation Test:** `Unit Test 2` (`test_02_capability_profiler_artifact_integrity_and_external_pids`), `Unit Test 23` (`test_23_security_and_host_safety_guards`), and `Integration Test E` (`test_E_long_running_process_heartbeats_and_restart_reconciliation`).

### 3.5 BrowserGym
- **Source URL:** `https://arxiv.org/abs/2412.05467` | `https://github.com/ServiceNow/BrowserGym`
- **Publication Date / Status:** December 2024 / ICLR 2025 (`The BrowserGym Ecosystem for Web Agent Research`)
- **Relevant Finding:** Unifying web agent benchmarks (MiniWoB++, WorkArena, WebArena, VisualWebArena, AssistantBench) under a single Gymnasium-compatible interface with combined DOM, Accessibility Tree (AXTree), and Set-of-Marks screenshot observations reveals that compact AXTree observations substantially reduce token usage compared to raw HTML dumps.
- **Experimental Conditions:** Standardized Playwright/Chromium browser automation across 1,000+ web tasks.
- **Evidence Limitations:** Concurrent Chromium instances quickly exhaust RAM (~300–800 MB per browser context) if not bounded by a semaphore.
- **Implementation Implication for AGI 1.7:** Cap `concurrent_browsers = 2` in `resource_policy.json`, extract compact structured DOM/AXTree summaries via `ACON` compression, and enforce SSRF filtering before any URL navigation.
- **Validation Test:** `Unit Test 5` (`test_05_resource_governor_admission_and_hysteresis`) and `Unit Test 23` (`test_23_security_and_host_safety_guards`).

### 3.6 AgentLab
- **Source URL:** `https://arxiv.org/abs/2412.05467` | `https://github.com/ServiceNow/AgentLab` | `https://arxiv.org/abs/2602.16901`
- **Publication Date / Status:** December 2024–2026 (ServiceNow Research / PMLR 2026 Adversarial Evaluation)
- **Relevant Finding:** Reproducible agent evaluation requires recording complete per-step metadata—exact prompt construction, raw model output, token counts, elapsed latency, environment state hash, and error taxonomy—while adversarial evaluations (`arXiv:2602.16901`) show that multi-turn indirect prompt injections bypass stateless regex filters unless tool arguments are validated against task scope and network security policies.
- **Experimental Conditions:** Large-scale parallel web and adversarial agent experiments.
- **Evidence Limitations:** Parallel experiment runners crash local hosts when worker pools ignore real-time memory commit charge.
- **Implementation Implication for AGI 1.7:** Persist full per-step reproducibility records in `token_ledger.jsonl` and `task_events.jsonl`, and enforce stateful SSRF, command-injection, and permission checks in `SecurityGuard` (`engine/agi17/security/security_guard.py`).
- **Validation Test:** `Unit Test 21` (`test_21_progress_service_derives_metrics_from_raw_ledgers_only`) and `Unit Test 23` (`test_23_security_and_host_safety_guards`).

### 3.7 SWE-bench
- **Source URL:** `https://arxiv.org/abs/2310.06770` | `https://www.swebench.com/`
- **Publication Date / Status:** October 2023 / ICLR 2024
- **Relevant Finding:** Resolving real-world GitHub issues across large Python repositories requires targeted code localization, minimal surgical diffs, and execution of existing + reproduction test suites (`FAIL_TO_PASS` and `PASS_TO_PASS`) rather than whole-file rewrites.
- **Experimental Conditions:** 2,294 issue-commit pairs across 12 popular Python repositories evaluated in Docker containers.
- **Evidence Limitations:** Unbounded repository exploration (`grep`/`find`/reading whole files) causes severe context bloat if outputs are not truncated or filtered.
- **Implementation Implication for AGI 1.7:** Equip software-engineering specialists (`code-architect`, `bug-root-cause-hunter`, `test-verification-specialist`) with bounded search, AST syntax verification, and mandatory regression test execution before marking coding tasks `VERIFIED`.
- **Validation Test:** `Unit Test 17` (`test_17_all_16_specialist_families_executable_invocations`) and `Integration Test A` (`test_A_substantial_task_auto_spawns_real_child_agents`).

### 3.8 BrowseComp: A Simple Yet Challenging Benchmark for Browsing Agents
- **Source URL:** `https://arxiv.org/abs/2504.12516`
- **Publication Date / Status:** April 2025 (OpenAI Technical Report)
- **Relevant Finding:** Deep multi-hop information retrieval tasks where answers are hard to find but easy to verify require iterative query reformulation, source tiering, cross-checking of constraints, and calibrated confidence scoring rather than accepting the first retrieved snippet.
- **Experimental Conditions:** 1,266 challenging web-browsing questions requiring persistent multi-hop search verification.
- **Evidence Limitations:** Unbounded search loops consume large token budgets when dead-end branches are not pruned early.
- **Implementation Implication for AGI 1.7:** Combine source-tier verification (`TIER_A_PRIMARY_SPEC`, `TIER_B_OFFICIAL_DOCS`, `TIER_C_EMPIRICAL_ARTIFACT`) with token-budget phase caps and `ACON` observation compression in research specialists.
- **Validation Test:** `Unit Test 17` (`test_17_all_16_specialist_families_executable_invocations`) and `Unit Test 19` (`test_19_token_budget_controller_enforces_hard_caps_and_reserves`).

### 3.9 AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents
- **Source URL:** `https://arxiv.org/abs/2406.13352` | `https://github.com/ethz-spylab/agentdojo`
- **Publication Date / Status:** June 2024 / NeurIPS 2024 Datasets and Benchmarks Track
- **Relevant Finding:** Untrusted data retrieved from external tools (web pages, emails, files, terminal outputs) frequently contains indirect prompt injections attempting to hijack control flow or exfiltrate secrets; effective defense requires isolating untrusted data from control instructions and enforcing deterministic policy checks on every privileged tool call.
- **Experimental Conditions:** 97 realistic tasks and 629 security test cases across workspace, banking, travel, and slack environments.
- **Evidence Limitations:** Prompt-level delimiters alone do not guarantee 100% defense without hard runtime tool-policy enforcement.
- **Implementation Implication for AGI 1.7:** Enforce a two-layer defense in `engine/agi17/security/security_guard.py`: (1) untrusted external data is tagged and sanitized before entering context, and (2) privileged tool actions (network fetches, file writes outside workspace, process termination, git push, brokerage/financial actions, host GUI) are deterministically checked against `permissions_policy.json` regardless of LLM prompt state.
- **Validation Test:** `Unit Test 23` (`test_23_security_and_host_safety_guards`) and `Integration Test L` (`test_L_security_guard_blocks_ssrf_injection_and_host_gui`).

---

## 4. Observability, Resource Management & Safety

### 4.1 OpenTelemetry GenAI Semantic Conventions
- **Source URL:** `https://opentelemetry.io/docs/specs/semconv/gen-ai/` | `https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/`
- **Publication Date / Status:** 2024–2026 (CNCF OpenTelemetry Specification v1.27–v1.32+)
- **Relevant Finding:** Standardizing telemetry spans and event attributes (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.operation.name`, `error.type`) ensures auditability across model calls, tool executions, and subagent delegations.
- **Experimental Conditions:** Cross-vendor observability specification for LLM applications and agent frameworks.
- **Evidence Limitations:** Upstream OpenTelemetry schemas do not automatically distinguish between provider-reported per-call tokens, CLI cumulative session tokens, and locally estimated fallback counts.
- **Implementation Implication for AGI 1.7:** Extend OpenTelemetry GenAI attributes in `engine/agi17/telemetry/token_economy.py` and `progress_service.py` with mandatory provenance tags: `telemetry_source` (`PROVIDER_REPORTED`, `CLI_REPORTED`, `LOCALLY_ESTIMATED`, or `UNAVAILABLE`), `raw_cumulative_input_tokens`, `normalized_call_input_tokens`, `thinking_tokens_included_in_output`, and `failed_call_elapsed_ms`.
- **Validation Test:** `Unit Test 20` (`test_20_token_accounting_normalizes_cumulative_and_failed_calls`) and `Unit Test 21` (`test_21_progress_service_derives_metrics_from_raw_ledgers_only`).

### 4.2 Docker Resource Constraints (`--memory`, `--cpus`, `--pids-limit`)
- **Source URL:** `https://docs.docker.com/engine/containers/resource_constraints/`
- **Publication Date / Status:** 2024–2026 (Docker Inc. Official Engine Reference)
- **Relevant Finding:** Unconstrained containers can exhaust host memory and trigger kernel OOM kills or host thrashing; explicitly setting `--memory`, `--memory-swap`, `--cpus`, and `--pids-limit` bounds container resource consumption and prevents fork bombs or memory leaks inside benchmark trials.
- **Experimental Conditions:** Linux cgroups v2 / Docker Engine container isolation.
- **Evidence Limitations:** On Windows hosts running Docker Desktop with WSL2, container limits are bounded by the outer WSL2 lightweight utility VM's memory allocation.
- **Implementation Implication for AGI 1.7:** `CapabilityProfiler` inspects Docker daemon availability and active containers, while `ResourceGovernor` caps `active_docker_tasks <= 2` and enforces `docker_wsl_reserve_ram_mb = 512.0` alongside `min_free_physical_ram_mb = 1200.0`.
- **Validation Test:** `Unit Test 1` (`test_01_capability_profiler_live_windows_metrics`) and `Unit Test 5` (`test_05_resource_governor_admission_and_hysteresis`).

### 4.3 WSL Settings (`.wslconfig` & `wsl.conf`)
- **Source URL:** `https://learn.microsoft.com/en-us/windows/wsl/wsl-config`
- **Publication Date / Status:** 2024–2026 (Microsoft Learn Official Documentation)
- **Relevant Finding:** WSL2 allocates up to 50% of total host RAM by default (`vmmemWSL`) unless constrained in `%USERPROFILE%\.wslconfig` (`memory=`, `processors=`, `swap=`, `autoMemoryReclaim=gradual`), which can starve native Windows processes (`agy.exe`, Python, Antigravity IDE) when Docker or Linux workloads run concurrently.
- **Experimental Conditions:** Windows 10/11 WSL2 Hyper-V utility VM management.
- **Evidence Limitations:** Changes to `.wslconfig` require `wsl --shutdown` to take effect, which cannot be executed mid-run if active containers or background VM tasks are running.
- **Implementation Implication for AGI 1.7:** `CapabilityProfiler` non-destructively reads `%USERPROFILE%\.wslconfig` (if present) and live host memory commit charge, factoring WSL/Docker overhead into `ResourceGovernor`'s real-time admission control without ever running destructive `wsl --shutdown` during active operations.
- **Validation Test:** `Unit Test 1` (`test_01_capability_profiler_live_windows_metrics`) and `Unit Test 3` (`test_03_capability_profiler_explicit_unavailable_markers`).

### 4.4 Windows Job Objects (`CreateJobObjectW`, `AssignProcessToJobObject`)
- **Source URL:** `https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects`
- **Publication Date / Status:** Win32 Kernel API Specification (Microsoft Learn)
- **Relevant Finding:** On Windows, terminating a parent subprocess (`Popen.terminate()`) does **not** automatically terminate grandchild processes spawned by shells (`cmd.exe`, `powershell.exe`, `node.exe` inside `agy.exe`). Binding child processes to a Windows Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (`0x00002000`) or executing `taskkill /F /T /PID <pid>` guarantees clean termination of the entire process tree on timeout or cancellation.
- **Experimental Conditions:** Windows NT kernel process-tree management.
- **Evidence Limitations:** Processes assigned to a Job Object must handle nested job hierarchy rules on Windows 8+/10/11 (which natively support nested jobs).
- **Implementation Implication for AGI 1.7:** `ProcessSupervisor` (`engine/agi17/process_supervision/process_supervisor.py`) uses Win32 Job Objects / process-tree termination (`/T`) for all AGI 1.7-spawned child processes on cancel or timeout, while strictly exempting pre-existing external PIDs (`PID 20556` and `PID 22884` recorded in `protected_external_pids`).
- **Validation Test:** `Unit Test 11` (`test_11_process_supervisor_streaming_and_completion_event`), `Unit Test 12` (`test_12_process_supervisor_detects_missing_or_corrupt_artifact`), and `Integration Test K` (`test_K_task_cancellation_terminates_child_tree_cleanly`).

### 4.5 Windows Memory APIs (`GlobalMemoryStatusEx`)
- **Source URL:** `https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex`
- **Publication Date / Status:** Win32 `sysinfoapi.h` Kernel Specification (Microsoft Learn)
- **Relevant Finding:** `GlobalMemoryStatusEx` populates `MEMORYSTATUSEX` with exact 64-bit values for `ullTotalPhys`, `ullAvailPhys`, `dwMemoryLoad`, `ullTotalPageFile` (commit limit), and `ullAvailPageFile` (available commit charge) in microseconds via `ctypes.windll.kernel32` with zero external library dependencies. Monitoring both physical RAM (`ullAvailPhys`) and system commit charge (`ullAvailPageFile`) is essential on Windows because processes crash with `MemoryError` or `STATUS_COMMITMENT_LIMIT` (`0xC000012D`) when commit charge is exhausted even if physical RAM appears partially free.
- **Experimental Conditions:** Native Windows 64-bit OS runtime telemetry.
- **Evidence Limitations:** Provides system-wide physical and commit counters; per-process RSS/CPU requires pairing with `GetProcessMemoryInfo` / `GetSystemTimes` or `tasklist`.
- **Implementation Implication for AGI 1.7:** Directly replaces the hardcoded `"cpu_percent": 25.0` stub in AGI 1.6 (**Defect 8**): `CapabilityProfiler` (`engine/agi17/capabilities/capability_profiler.py`) calls Win32 `GlobalMemoryStatusEx` and `GetSystemTimes` via `ctypes` to supply real-time physical RAM, commit headroom, and CPU utilization to `ResourceGovernor`.
- **Validation Test:** `Unit Test 1` (`test_01_capability_profiler_live_windows_metrics`) and `Unit Test 4` (`test_04_capacity_separation_100_specs_100_tasks_bounded_workers`).

### 4.6 Google SRE Overload Handling, Load Shedding & Backpressure
- **Source URL:** `https://sre.google/sre-book/handling-overload/`
- **Publication Date / Status:** 2016–2026 (Google Site Reliability Engineering Book, Chapter 21)
- **Relevant Finding:** Systems under heavy load degrade catastrophically (thrashing, timeout storms, zero goodput) unless they enforce: (1) **Per-resource capacity admission control** (`current_usage + estimated_cost <= safe_capacity`), (2) **Bounded queues** with explicit backpressure (`QUEUED` / `THROTTLED` / `DEFERRED`) rather than unbounded thread creation, (3) **Hysteresis cooldowns** before scaling concurrency back up after an overload event, and (4) **Jittered exponential backoff** on retries to prevent thundering herds.
- **Experimental Conditions:** Production high-scale service reliability engineering principles.
- **Evidence Limitations:** Requires accurate per-task resource cost estimation (`SIMULATED`/`SIMPLE` vs `MODEL_API` vs `DOCKER_TERMINAL` vs `GUI_VM`).
- **Implementation Implication for AGI 1.7:** Directly remedies **AGI 1.6 Defect 7 & Defect 8**: `ResourceGovernor` (`engine/agi17/orchestration/resource_governor.py`) implements strict admission control (`min_free_physical_ram_mb >= 1200`, `min_free_commit_mb >= 1500`, `cpu_percent <= 85%`), hysteresis recovery thresholds (`ram >= 1600 MB`, `cpu <= 70%`, `cooldown = 5.0s`), and 8 separate bounded queues (`resource_policy.json`).
- **Validation Test:** `Unit Test 4` (`test_04_capacity_separation_100_specs_100_tasks_bounded_workers`), `Unit Test 5` (`test_05_resource_governor_admission_and_hysteresis`), `Unit Test 6` (`test_06_scheduler_separate_queues_and_priority`), and `Integration Test F` (`test_F_concurrent_heterogeneous_workload_under_governor`).

### 4.7 OWASP Top 10 for LLM Applications & Generative AI (2025)
- **Source URL:** `https://genai.owasp.org/llm-top-10/`
- **Publication Date / Status:** November 2024 / 2025 Release (OWASP Foundation v2025)
- **Relevant Finding:** Identifies the critical security risks in agentic LLM deployments: `LLM01:2025 Prompt Injection`, `LLM02:2025 Sensitive Information Disclosure`, `LLM05:2025 Improper Output Handling`, `LLM06:2025 Excessive Agency`, and `LLM10:2025 Unbounded Consumption` (denial of wallet / resource exhaustion). Mitigating `Excessive Agency` and `Unbounded Consumption` requires least-privilege tool scoping per specialist, deterministic output validation, secret scrubbing, and hard token/compute budgets.
- **Experimental Conditions:** Industry-wide vulnerability taxonomy and security verification standard.
- **Evidence Limitations:** High-level control taxonomy requiring concrete runtime enforcement hooks.
- **Implementation Implication for AGI 1.7:** Enforce `LLM01/LLM06` via `SecurityGuard` and per-specialist `allowed_tools` in the 100-specialist registry; `LLM02` via prompt/log secret redaction (`permissions_policy.json`); `LLM05` via `EvidenceVerifier`; and `LLM10` via `TokenBudgetController` + `ResourceGovernor`.
- **Validation Test:** `Unit Test 19` (`test_19_token_budget_controller_enforces_hard_caps_and_reserves`), `Unit Test 23` (`test_23_security_and_host_safety_guards`), and `Integration Test L` (`test_L_security_guard_blocks_ssrf_injection_and_host_gui`).

### 4.8 NIST AI Risk Management Framework (AI RMF 1.0 & Generative AI Profile NIST AI 600-1)
- **Source URL:** `https://www.nist.gov/itl/ai-risk-management-framework` | `https://doi.org/10.6028/NIST.AI.600-1`
- **Publication Date / Status:** January 2023 (AI RMF 1.0) / July 2024 (NIST AI 600-1 Generative AI Profile)
- **Relevant Finding:** Establishes four core operational functions—**GOVERN**, **MAP**, **MEASURE**, and **MANAGE**—requiring AI systems to maintain provenance records, verify data integrity via cryptographic checksums, explicitly distinguish verified empirical measurements from estimates or unavailable data, and prevent unauthorized autonomous actions in high-risk domains (financial transactions, host system modification).
- **Experimental Conditions:** U.S. Federal and international AI governance and risk engineering standard.
- **Evidence Limitations:** Policy framework requiring technical implementation in code and telemetry schemas.
- **Implementation Implication for AGI 1.7:** Enforces **AGI 1.6 Defect 10** remediation: `ProgressService` (`engine/agi17/telemetry/progress_service.py`) computes 100% of dashboard and report metrics from raw ledgers (`SQLite` + `JSONL`), marks unmeasured fields `UNAVAILABLE`, labels reference pricing as `UNVERIFIED_EXTERNAL_BILLING_SCHEDULE_LABEL_AS_ESTIMATE_ONLY`, and enforces `allow_real_money_brokerage = false`.
- **Validation Test:** `Unit Test 21` (`test_21_progress_service_derives_metrics_from_raw_ledgers_only`), `Unit Test 22` (`test_22_dashboard_html_matches_raw_ledgers_zero_hardcoded_claims`), and `Integration Test N` (`test_N_dashboard_and_reports_100_percent_ledger_reconciled`).

---

## 5. Quantum Computing Research & Default-Disabled Adapter Justification

### 5.1 PRX Quantum: "Is Quantum Advantage the Right Goal for Quantum Machine Learning?"
- **Source URL:** `https://doi.org/10.1103/PRXQuantum.3.030101` | `https://link.aps.org/doi/10.1103/PRXQuantum.3.030101`
- **Publication Date / Status:** July 2022 (`PRX Quantum 3, 030101`, Maria Schuld & Nathan Killoran, Perspective)
- **Relevant Finding:** Demonstrates that claims of near-term exponential quantum speedup on classical machine learning and text/data processing tasks are fundamentally bottlenecked by the **data-loading (state preparation / QRAM) problem** and readout complexity. When classical data must be encoded into quantum states and read out via repeated measurements, O(poly) or O(N) classical preprocessing and NISQ gate noise eliminate theoretical asymptotic advantages over optimized classical algorithms.
- **Experimental Conditions:** Theoretical complexity and physical NISQ architecture analysis of variational quantum circuits, quantum kernels, and linear algebra subroutines on classical datasets.
- **Evidence Limitations:** Focuses on QML model training/inference rather than cryptographic or quantum chemistry simulation domains where native quantum states exist.
- **Implementation Implication for AGI 1.7:** Provides the primary physical and complexity-theoretic foundation for disabling `QuantumComputeAdapter` by default for LLM agent orchestration, scheduling, memory retrieval, and token optimization.
- **Validation Test:** `Unit Test 24` (`test_24_quantum_adapter_disabled_by_default_and_honest_status`).

### 5.2 Frontiers in AI (2026): Critical Review of Quantum Machine Learning & Hybrid Utility
- **Source URL:** `https://doi.org/10.3389/frai.2026.1836641`
- **Publication Date / Status:** 2026 (`Frontiers in Artificial Intelligence`, DOI: `10.3389/frai.2026.1836641`)
- **Relevant Finding:** Critically reviews contemporary hybrid quantum-classical AI pipelines and confirms that simulating quantum circuits on classical CPUs/GPUs (`O(2^n)` state-vector overhead) for classical orchestration, heuristic routing, or vector similarity search is strictly slower and more resource-intensive than native classical algorithms (`SQLite` B-tree/FTS, Tarjan DAG scheduling, classical linear algebra), and that faux "quantum-inspired" simulators add memory pressure without improving accuracy.
- **Experimental Conditions:** Comparative review of NISQ hardware execution, classical state-vector simulation overhead, and classical baseline algorithms across optimization and ML tasks.
- **Evidence Limitations:** Does not preclude specialized future fault-tolerant quantum co-processors for genuine quantum chemistry/physics problems (e.g., Hamiltonian simulation).
- **Implementation Implication for AGI 1.7:** In `config/agi17/runtime_profile.json` and `engine/agi17/capabilities/quantum_adapter.py`, `QuantumComputeAdapter` is strictly configured with:
  - `"enabled": false`
  - `"status": "DISABLED_NO_PRACTICAL_ADVANTAGE_FOR_LLM_ORCHESTRATION"`
  - `"require_verified_hardware_and_classical_baseline": true`
  Any attempt to invoke quantum routing during normal orchestration returns a deterministic, non-deceptive status (`DISABLED_BY_POLICY`) with zero classical state-vector simulation bloat, unless an explicitly authorized quantum backend, verified problem formulation, and classical baseline benchmark are provided.
- **Validation Test:** `Unit Test 24` (`test_24_quantum_adapter_disabled_by_default_and_honest_status`) and `Integration Test O` (`test_O_end_to_end_agi17_mission_and_policy_invariants`).

---

## 6. Summary Matrix of Research Coverage

| Domain Category | Primary Papers & Specifications Audited | Core AGI 1.7 Subsystems Governed | Acceptance Tests Mapped |
|---|---|---|---|
| **1. Agent OS & Orchestration** | AIOS (`arXiv:2403.16971`), Magentic-One/AutoGen (`arXiv:2411.04468`), LangGraph Persistence, MS Agent Checkpoints, Temporal Signals/Updates/Queries, PydanticAI UsageLimits, OpenHands (`arXiv:2407.16741`), smolagents, Google ADK, CrewAI, MetaGPT (`arXiv:2308.00352`), CAMEL (`arXiv:2303.17760`), AgentScope (`arXiv:2402.14034`) | `OmegaCommandOrchestrator`, `TaskControlStore`, `CommandInbox`, `agi17ctl`, `SpecialistRegistry` (100 specs / 16 families) | Unit Tests `4–10`, `16–18`; Integration Tests `A`, `B`, `C`, `G`, `J`, `K` |
| **2. Memory & Context Optimization** | ACON (`PMLR v306 kang26b` / `arXiv:2510.00615`), LongMemEval (`ICLR 2025` / `arXiv:2410.10813`), LoCoMo (`ACL 2024`), MemoryArena, A-Mem (`arXiv:2502.12110`), MemoryOS (`EMNLP 2025`), Agent Workflow Memory (`PMLR v267 wang25bx`), Mem0 (`arXiv:2504.19413`), Letta (`arXiv:2310.08560`) | `PersistentMemoryService` (10 layers, SQLite WAL, fact supersession, `retrieve_before_planning`), `AdaptiveContextCompressor` (ACON lossless-anchor compression) | Unit Tests `13`, `14`, `15`; Integration Test `I` |
| **3. Benchmarks & Tool Use** | GPQA Diamond Clean v1.2.2 (`189` items, `9` excluded from `198`), Terminal-Bench 2.0 (`89` tasks), Harbor Framework, OSWorld-V2.1 (`108` tasks), BrowserGym (`arXiv:2412.05467`), AgentLab (`arXiv:2602.16901`), SWE-bench (`arXiv:2310.06770`), BrowseComp (`arXiv:2504.12516`), AgentDojo (`arXiv:2406.13352`) | `AGIAgentAdapter` (isolated CWD), `ProcessSupervisor`, `BenchmarkRunner`, `EvidenceVerifier` | Unit Tests `2`, `11`, `12`, `20`; Integration Tests `D`, `E`, `H`, `M` |
| **4. Observability, Resource Management & Safety** | OpenTelemetry GenAI SemConv, Docker Resource Constraints, WSL `.wslconfig`, Win32 Job Objects, Win32 `GlobalMemoryStatusEx`, Google SRE Overload Handling, OWASP LLM Top 10 (2025), NIST AI RMF 1.0 / 600-1 | `CapabilityProfiler`, `ResourceGovernor`, `AdaptiveExecutionScheduler`, `TokenBudgetController`, `ProgressService`, `SecurityGuard` | Unit Tests `1–6`, `19–23`; Integration Tests `F`, `H`, `L`, `N` |
| **5. Quantum Computing Research** | Schuld & Killoran (`PRX Quantum 3, 030101`), Critical Review of QML Utility (`Frontiers in AI 2026, 10.3389/frai.2026.1836641`) | `QuantumComputeAdapter` (Default `DISABLED_NO_PRACTICAL_ADVANTAGE_FOR_LLM_ORCHESTRATION`) | Unit Test `24`; Integration Test `O` |
