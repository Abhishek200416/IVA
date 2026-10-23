<USER_REQUEST>
We have traded day before yesterday yesterday and today we have traded comes in three days so from three days how much profit it earned actually and how much lost happened And what are the calls it bought and what are the foods it bought and it is why it is unnavering of the dates of the calls are put and exactly its not marking exact dates What is exact issue when I ask you to start trading why it is not start trading instead of asking questions directly analysing everything and doing something which is behind What is exact issue when I ask you to start trading why it is not start trading instead of asking questions directly analysing everything and doing something which is behind# AGI 1.7 OMEGA COMMAND — PHASE 17.19

# TRI-TAB RUNTIME ORCHESTRATION, CONVERSATIONAL STARTUP, LIVE DATA SYNCHRONIZATION AND CONTINUOUS SUPERVISION



**Project:** AGI 1.7 OMEGA COMMAND / OMEGA NEXUS  

**Workspace:** `Downloads\pt`  

**Dashboard:** `http://127.0.0.1:8088`  

**CDP port:** `9229`  

**Timezone:** `Asia/Kolkata`  

**Primary reported paper ledger:** `epoch_10k`  

**Broker:** Paytm Money  

**Prerequisite:** Inspect and preserve the actual Phase 17.17 and Phase 17.18 repository state before implementation.



## MISSION



Fix the actual operating experience of AGI 1.7. The operator should be able to say **“Start trading”**, receive a short conversational setup flow, confirm the configuration, and have the system start and supervise the required runtime components without repeatedly searching the filesystem, reopening the same pages, generating duplicate processes, or falsely claiming that market data is connected.



Build on the existing code. Inspect the actual implementations, identify why startup takes too long and what failed previously, implement the necessary changes, run the tests, and verify the live local runtime.



Do not deliver only a plan, mock UI, or documentation.



The target operating topology is three browser tabs served by one managed Chrome instance:



1. Paytm Money NIFTY option-chain tab.

2. Paytm Money BANKNIFTY option-chain tab.

3. Standalone AGI 1.7 dashboard tab.



The managed runtime has three primary components:



1. Overlay/data-collection runtime.

2. Standalone dashboard server.

3. Chrome/CDP browser process.



Treat the three browser tabs and the three managed components as related but different concepts. Determine the actual commands and architecture from the repository rather than guessing them.



All background agents, market-data synchronization, news intelligence, status monitoring and risk checks must have explicit lifecycle management and be visible in runtime telemetry.



**Do not bypass existing financial safeguards. Keep live order dispatch disabled throughout this phase. Never submit real orders in tests or automatically resume live authority.**



---



## 1. FIX THE CONVERSATIONAL COMMAND ROUTER FIRST



The most important user-facing defect is this:



When the operator says “Start trading”, the agent begins searching files and verifying the repository, when it should immediately enter a trading setup conversation.



Implement a dedicated, deterministic command-intent router before generic agent planning, research, browser navigation or filesystem exploration.



Recognize commands and reasonable variants such as:



- “Start trading.”

- “Start the trading system.”

- “Start the dashboard.”

- “Start paper trading.”

- “Resume monitoring.”

- “Check system status.”

- “Stop everything.”

- “Stop trading and monitoring.”

- “Talk me through the setup.”

- “Show me why the system is disconnected.”



These commands must map to explicit workflows.



### Exact behavior for “Start trading”



When the operator issues the start command:



1. Recognize the start-trading intent immediately.

2. Read the saved runtime profile and authoritative existing service status through a lightweight runtime API.

3. Do not launch a general research agent.

4. Do not recursively search source files.

5. Do not run a repository-wide test suite.

6. Do not start services before collecting essential missing configuration and obtaining the required confirmation.

7. Present a short setup conversation.



If configuration is already saved and all mandatory fields are valid, ask only about settings that require a fresh operator decision. Do not ask the operator to enter information that already exists and has not changed.



### Required setup information



Collect or confirm these items in a compact conversational form:



**A. Operating mode**

- Paper trading using authentic data when available.

- Backtesting or historical research.

- Live-data validation, read-only.



A request for real-money trading must display the existing live-execution lock and its reasons. It must not unlock order routing.



**B. Starting capital and ledger**

- Default to the explicitly selected paper ledger if it exists and is healthy.

- Allow the operator to select an existing ledger or request creation of a separate paper ledger.

- If a new ledger is requested, confirm its starting capital.

- Example: ₹10,000.

- Never silently reset or reuse another ledger.

- Display whether the starting capital is simulated or real.



**C. Instruments**

- NIFTY.

- BANKNIFTY.

- Both indices, which should be the normal default for the requested tri-tab setup.



**D. Risk settings**

- Display the configured per-trade risk, order-notional cap, daily-loss limit, and stop-loss requirements.

- Do not silently increase any limit.

- Require a valid, finite daily-loss cap and approved position-sizing limits before enabling paper strategy execution.

- If mandatory risk values are missing, ask the operator rather than inventing them.

- Show all applicable amounts in INR and percentages.



**E. Operating behavior**

- `GUIDED`: explain actions and ask for operator confirmation at meaningful decision points.

- `MONITOR_ONLY`: run data collection, diagnostics and news intelligence without strategy-triggered paper order creation.

- `PAPER_SIMULATION`: allow the paper engine to evaluate and simulate proposals within approved limits.



Support normal conversation while the system is running. The operator must be able to ask questions or change permitted configuration without triggering a complete restart.



### Startup confirmation



Summarize the chosen settings, currently active services, existing managed browser tabs, outstanding blockers, capital and risk controls.



Ask the operator to confirm startup when that confirmation is needed. Only then start missing components.



If the user explicitly chooses a saved, pre-approved quick-start profile, allow a shortened confirmation path for safe paper/read-only operation, but never bypass missing risk controls or authentication requirements.



Do not promise that the system will make a profit. Do not interpret a 50% or 100% desired return as an instruction to increase leverage, use all capital, or ignore risk limits.



---



## 2. BUILD ONE AUTHORITATIVE RUNTIME SUPERVISOR



Inspect the current overlay launcher, dashboard server, Chrome automator, orchestration runtime, and any existing background tasks or daemons.



Consolidate startup and status management into one authoritative supervisor where appropriate, without creating unnecessary duplicate frameworks.



Define a service registry for the actual three primary components:



- `overlay_service`

- `dashboard_service`

- `chrome_cdp_service`



The registry should include verified launch commands, process ownership, health-check endpoints or checks, port assignments, startup dependencies, shutdown behavior, and restart policy.



Add a stable runtime API or equivalent existing integration that supports:



- `GET /api/runtime/status`

- `GET /api/runtime/health`

- `POST /api/runtime/start`

- `POST /api/runtime/stop`

- `POST /api/runtime/reconcile`

- `GET /api/runtime/events`



Use consistent endpoint conventions if a suitable existing API already exists.



For every service, represent at least:



`STOPPED`, `STARTING`, `RUNNING`, `DEGRADED`, `FAILED`, `STOPPING`.



Each state needs:

- Process identity when applicable.

- Start time.

- Last heartbeat.

- Most recent health check.

- Last error.

- Restart count.

- Whether the process was created or adopted by the supervisor.

- The exact reason a component cannot start or become healthy.



### Startup dependency order



Use the order appropriate to actual dependencies, ensuring:



1. Configuration and risk validation finish first.

2. The dashboard can expose startup status.

3. Chrome/CDP availability is checked, and one managed browser instance is prepared or safely reused.

4. The required NIFTY and BANKNIFTY tabs are discovered or opened without duplication.

5. The overlay/readers are attached to the correct targets.

6. Data channels and the central aggregator are initialized.

7. Agents and news intelligence start only when their prerequisites are satisfied.

8. The supervisor publishes a final, truthful readiness summary.



The final status must distinguish `STARTED` from `HEALTHY` and distinguish both from `LIVE_DATA_QUALIFIED`.



### Never spawn duplicates



Before starting anything, inspect the current managed service state.



If a required service is healthy, reuse it. Do not launch another copy.



If a service is running but unhealthy, diagnose the reason before deciding whether a controlled restart is appropriate.



Never kill unrelated Chrome sessions or arbitrary processes to make a startup routine pass.



Never launch a browser with unverified ownership just because port 9229 is open.



Preserve operator work and current browser sessions. Any Chrome profile or debugging-port takeover must follow the existing verified ownership and session rules.



A network port accepting connections does not by itself prove that the expected service owns it.



---



## 3. IMPLEMENT THE THREE-TAB CHROME TOPOLOGY



The existing project has previously emphasized a single-tab automation safeguard. Review that policy carefully.



Replace any conflicting one-managed-tab restriction with a **three-role managed-target policy** where justified, without permitting unlimited tabs or repeated tab creation.



Target tab roles:



- `NIFTY_CHAIN`

- `BANKNIFTY_CHAIN`

- `AGI_DASHBOARD`



Maintain a stable registry of browser target IDs, URLs, roles, health state and timestamps.



Resolve an existing target by a combination of target identity, validated URL, page role and provider state. Do not depend solely on tab order or title text.



### NIFTY tab



- Open or reuse the verified official Paytm Money option-chain page for NIFTY.

- Keep it assigned to the NIFTY reader.

- Preserve manual operator authentication.

- Do not navigate it away from an authentication flow unexpectedly.

- Collect only data that is genuinely observable and appropriately permitted.



### BANKNIFTY tab



- Open or reuse the verified official Paytm Money option-chain page for BANKNIFTY.

- Keep it assigned to the BANKNIFTY reader.

- Ensure its data reader is distinct from NIFTY's reader.

- Preserve the market-depth view where appropriate and ensure the overlay does not hide critical controls.



### Dashboard tab



- Open or reuse `http://127.0.0.1:8088/`.

- Display NIFTY and BANKNIFTY separately and simultaneously.

- Display feed provenance, freshness, source status, last update and rejection reasons.

- Display the portfolio and accounting values from the authoritative backend.

- Do not depend on browser-local overlay state as the source of financial truth.



### Critical browser invariants



- One supervisor-managed Chrome/CDP instance for these three roles.

- One authoritative NIFTY reader.

- One authoritative BANKNIFTY reader.

- One dashboard role.

- No new tab per poll or agent cycle.

- No repeated full-page reloads as a synchronization mechanism.

- No arbitrary navigation while the operator is entering OTPs or PINs.

- No indefinite silent retry loops.

- No duplicate instrument readers producing duplicate trade proposals.

- Safe recovery when an individual target closes, changes URL, logs out, or loses connectivity.



If a required tab is missing, recover that role through a controlled state transition. Report that recovery happened instead of silently opening another duplicate.



Do not assume that the overlay is attached just because the page exists. Verify attachment, role, permissions and heartbeat.



---



## 4. FIX DUAL-INDEX MARKET DATA SYNCHRONIZATION



Implement a central instrument-aware event pipeline.



The flow should be:



`Paytm page observation → per-tab reader → validation → normalized event → central aggregator → authoritative backend state → overlay/dashboard subscribers`



Use the existing transport if it is suitable. BroadcastChannel, localStorage, WebSocket, or other messaging mechanisms may be used for coordination, but do not make unvalidated local browser messages the final financial source of truth.



Every observation must carry:



- Instrument and contract identity.

- Underlying index identity.

- Source role and target ID.

- Observation timestamp.

- Ingestion timestamp.

- Source provenance.

- Last-price and quote fields when genuinely observed.

- Applicable bid/ask, volume and contract metadata.

- Validation state.

- Sequence or event identifier where available.



Use consistent decimal-safe representations for monetary values and normalized timestamps for event handling.



### Multi-index correctness



- NIFTY observations must not overwrite BANKNIFTY state.

- BANKNIFTY observations must not overwrite NIFTY state.

- Shared dashboard values must be derived from the correct instrument records.

- Do not copy the active runner's LTP into unrelated instruments.

- Do not interpret two screens displaying similar prices as proof that synchronization is correct.

- Validate contract, strike, expiry, option type and lot size before associating a quote with a runner.

- De-duplicate repeated observations without suppressing legitimate price updates.

- Reject stale and invalid values.

- Detect sudden gaps, missing messages, disconnected readers and out-of-order events.

- Preserve the last valid observation while explicitly flagging its age and invalidating it for live decisions when it becomes stale.



Report measured synchronization latency and end-to-end data age. Do not promise zero lag.



### Provenance policy



Distinguish:



- `AUTHENTIC_LIVE`

- `BROWSER_OBSERVED`

- `HISTORICAL_REPLAY`

- `SYNTHETIC_FIXTURE`

- `CACHED_SNAPSHOT`

- `UNKNOWN`



Use `BROWSER_OBSERVED` for valid values extracted from a live browser page when a reliable official streaming/API provenance has not been established. Do not label DOM extraction as an official API feed.



A disconnected or unauthenticated reader cannot satisfy live-data qualification. Synthetic fixtures may be used in tests but can never qualify as authentic live data.



---



## 5. IMPLEMENT TRUTHFUL STATE SHARING BETWEEN OVERLAYS



The NIFTY and BANKNIFTY overlays may exchange shared information, but the server must retain authority over portfolio state, risk, simulated orders, stops, exits and accounting.



Use explicit schemas for:



- Market-data observations.

- Shared index snapshots.

- Runner state.

- Proposed simulated orders.

- Fill events.

- Exit/stop events.

- Portfolio snapshots.

- Emergency-stop events.



Every state-changing event needs a unique identifier and idempotent handling.



If an operator closes or modifies a paper position from either overlay, submit a validated request to the central backend. The backend determines whether the change is valid and updates the authoritative paper portfolio. Broadcast the confirmed resulting state to both overlays and the dashboard.



Do not allow the browser to declare a trade closed merely because a click occurred.



Handle duplicate events, temporary disconnections, concurrent requests, delayed acknowledgements, stale overlays and conflicting updates. If the external state is ambiguous, preserve the uncertainty and request review rather than inventing the final state.



Never turn a paper `Square Off` action into a real broker order.



---



## 6. FIX NEWS INTELLIGENCE AND CONTINUOUS MONITORING



Inspect and reuse existing news-intelligence and agent modules before adding new ones.



Build a bounded, supervised monitoring service that:



- Uses actual configured news sources or authenticated APIs.

- Stores source, publication time, ingestion time, topic, instrument relevance and provenance.

- Detects duplicated or stale stories.

- Separates confirmed information from interpretation or speculation.

- Classifies potentially relevant events, including index constituents' earnings, official regulatory announcements, macroeconomic releases, corporate news and major market-moving developments.

- Produces explainable summaries linked to the underlying source.

- Reports provider disconnection and the age of the latest successful update.

- Does not generate fake stories when feeds are unavailable.



The news module may inform research and risk advisories. News alone must never override central risk controls or authorize a trade.



Use bounded concurrency, explicit timeouts, configurable polling intervals, backoff, cancellation and resource limits. Avoid excessive API calls and unbounded agent loops.



Continuous monitoring does not mean continuously placing trades. Market-session state and operating mode must govern what the system is permitted to do.



Outside the applicable trading session, transition to `AFTER_HOURS_MONITORING`. Continue appropriate news processing, diagnostics and research jobs, but prohibit new session-dependent trade execution. Do not treat a stale last quote as a live tick.



When the next session begins, require fresh authenticated data and all normal safety checks before resuming strategy evaluation.



---



## 7. KEEP AGENT SUPERVISION SEPARATE FROM STARTUP DIAGNOSTICS



At runtime, ordinary commands must not initiate repository-wide searches.



Implement a two-tier design:



**Developer/maintenance tier:** Full source inspection, test discovery, repository scans, dependency checks and implementation work. This tier is used for engineering tasks and failures requiring code investigation.



**Operator/runtime tier:** Read saved configuration, inspect registered service state, issue verified runtime API calls, monitor heartbeats and provide conversational status. It must not crawl source files to start or check the system.



When the operator says “Start trading”, runtime behavior takes priority over generic agent planning.



When the operator asks “What is happening?”, respond from actual runtime telemetry and clearly distinguish facts from unavailable observations.



When an actual fault requires debugging, first show the specific fault and offer or undertake a bounded diagnostic workflow. Do not rerun the entire research suite for an ordinary disconnected-tab problem.



If a task is long-running, the supervisor must provide a persistent task ID, current phase, last progress time, current blocker and last successful checkpoint. This ensures that an apparent hang can be distinguished from a running process.



Do not claim a task is still running merely because its task ID exists in a report. Verify actual process state and heartbeat.



---



## 8. RISK CONTROLS, PAPER TRADING AND AFTER-HOURS SAFETY



The system should be useful and fast without being reckless.



- Keep live-order dispatch disabled in this phase.

- Start in the selected paper or read-only mode.

- Use server-side risk validation for all simulated proposals.

- Validate trade quantity, lot size, capital, exposure, approved notional and required stop-loss fields.

- Enforce daily-loss and per-trade risk limits from the approved profile.

- Block new simulated proposals if the necessary data is stale, malformed or unavailable.

- Preserve emergency stop across all managed tabs.

- Do not submit duplicate proposals due to repeated DOM observations or agent retries.

- Do not continue creating proposals after the operator stops the system.

- Separate realized paper P&L, unrealized paper P&L, fees and net equity.

- Maintain a visible distinction between simulated and real account balances.

- Keep the previously reported ₹30,000 two-day paper result unverified until it can be reproduced and reconciled against its exact ledger and trades.

- Never change position sizing to chase a desired 50% or 100% daily return.

- Never infer a real broker balance from a locally balanced paper ledger.



At shutdown, stop new simulated activity, persist the final state, release owned browser listeners, stop managed background services in the correct order, and report any incomplete shutdown. Do not delete session data to make termination appear successful.



A system restart must return to a safe mode, restore known state, revalidate data and risk controls, and obtain any required confirmation before strategy operations resume.



---



## 9. DASHBOARD CHANGES



Build on the existing design and implement functional backend-connected UI.



The dashboard header should show:



- Actual runtime state.

- Current operating mode.

- NIFTY reader status.

- BANKNIFTY reader status.

- Overlay service status.

- Chrome/CDP status.

- Dashboard backend status.

- News-service status.

- Risk-control status.

- The most important current blockers.



Create a service-control section with functional actions for:



- Start the selected safe runtime.

- Inspect live runtime status.

- Refresh health checks.

- Pause paper strategy evaluation.

- Stop monitoring.

- Trigger emergency stop.



Actions must call the real backend and display its result. Do not optimistically mark a service healthy before a verified response.



Add a dedicated tri-tab diagnostic view showing, for each role:



- Expected URL and actual URL.

- Target ID or safe identifier.

- Role assignment and attachment state.

- Last heartbeat.

- Last valid observation.

- Observation provenance and data age.

- Reader error, if any.

- Recovery attempts and outcome.



Add a synchronization view that shows the most recent NIFTY and BANKNIFTY event timestamps, ingestion ages, update latency and central snapshot version.



Add a recent-events feed for startup, login wait, reader attachment, data recovery, stale-data rejection, news updates, risk rejections, emergency stop and shutdown.



Never place secrets or session-token values in the UI.



---



## 10. REALISTIC STARTUP AND RECOVERY POLICY



Make routine startup as fast as the verified implementation permits.



Build a saved, validated runtime manifest with actual launch commands, known endpoints, browser roles, process ownership and service dependencies. Runtime commands should consult that manifest rather than searching the whole repository.



Do not add artificial waiting. Use bounded health checks and poll the actual readiness endpoints.



Do not declare all services healthy based solely on process creation.



If a service fails:



1. Preserve the current operational state.

2. Capture the error and time.

3. Retry only according to the documented policy.

4. Avoid duplicate process creation.

5. Surface the exact reason and any operator action needed.

6. Continue only those independent functions that remain safe.



If the dashboard is unavailable, report that fact through the supervisor/console rather than pretending the dashboard is usable.



If Chrome is unavailable, do not fabricate live data.



If only one index reader is connected, continue displaying its valid state while identifying the other index as unavailable. Do not label the complete tri-tab system healthy.



After-hours startup may be healthy as an after-hours monitoring service, even when no live market ticks are expected. Report that state distinctly from active market-session feed qualification.



---



## 11. REQUIRED TESTS AND IMPLEMENTATION EVIDENCE



Create or extend tests for:



- Start command routes to the conversational startup workflow.

- Missing required settings generate a setup question instead of a repository scan.

- Saved, valid settings avoid repeated questions.

- Unconfirmed startup does not start restricted components.

- Existing healthy services are reused.

- Duplicate startup requests do not create duplicate processes.

- Process ownership is validated before adoption or termination.

- Exactly one target exists for each managed browser role.

- Browser target loss and controlled tab recovery work safely.

- NIFTY and BANKNIFTY observations remain correctly separated.

- Quotes with different instruments and expiries cannot overwrite each other.

- Local-storage or BroadcastChannel duplicates cannot cause duplicate trade events.

- Stale or disconnected inputs fail closed.

- Synthetic data cannot satisfy the live-feed gate.

- Dashboard state reflects backend state.

- Continuous monitoring stops or enters after-hours mode according to the session.

- News polling obeys timeout, retry, deduplication and cancellation rules.

- Paper-trade proposals obey all risk limits.

- Emergency stop propagates to all managed components.

- Repeated actions and retries are idempotent.

- Restart recovery does not restore live authorization.

- Shutdown persists records and releases owned resources.



Use mocks for external dependencies and explicitly label mocked results. Conduct real read-only feed tests only when a legitimate authenticated provider session is available. Do not place live orders.



Run the targeted tests, existing relevant regression tests, full available test suite where feasible, and frontend build. Verify the actual runtime APIs. Preserve baseline failures and explain any skipped tests.



---



## 12. IMPLEMENTATION DELIVERABLES



Implement working code, not just design documents.



Add or update:



- A centralized runtime supervisor.

- A stable service registry and startup manifest.

- Three-role Chrome/CDP target management.

- Per-index readers and normalized event contracts.

- Central data aggregation and synchronization.

- The conversational startup command handler.

- News-monitoring lifecycle controls.

- Functional dashboard runtime and diagnostics panels.

- Appropriate automated tests.

- A reproducible startup and shutdown runbook.



Create a concise Phase 17.19 report containing:



- Actual source files modified.

- Existing defects found and root causes.

- Runtime behavior before and after.

- Exact commands executed and test results.

- Current service and managed-tab status.

- Actual market-data connectivity/provenance.

- Unresolved blockers and operator actions.

- Any code or integration work not completed.



Keep repository changes scoped and review the diff for regressions.



## 13. FINAL ACCEPTANCE CONDITIONS



Phase 17.19 may be reported complete only when the implementation demonstrates all safe and feasible criteria, including:



1. “Start trading” enters the setup workflow directly.

2. Essential questions are collected before restricted startup actions.

3. A confirmed start runs the actual managed services without duplicating healthy components.

4. One managed Chrome instance has the correct three tab roles.

5. The NIFTY and BANKNIFTY readers have independent state and validated provenance.

6. The dashboard reflects authoritative backend data and actual runtime status.

7. Continuous supervision has a visible heartbeat and recoverable lifecycle.

8. News intelligence remains bounded and distinguishable from verified market data.

9. Risk controls and emergency stop remain enforced.

10. Tests and actual endpoint checks support the claims in the final report.



If an external prerequisite is unavailable, report it explicitly and complete the safe preparation.



Never report live connectivity, successful login, correct account reconciliation, profitability, or full production readiness without evidence.



**Start with runtime-intent routing and the supervisor, then implement and verify the three-tab architecture and central data flow. Do not spend this phase generating another broad plan. Make the necessary code changes, run the tests, and report precisely what works and what remains blocked.** 
</USER_REQUEST>
<ADDITIONAL_METADATA>
The current local time is: 2026-10-16T17:37:02+05:30.
</ADDITIONAL_METADATA>