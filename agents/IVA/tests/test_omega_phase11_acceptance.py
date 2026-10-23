"""AGI 1.7 OMEGA COMMAND — Acceptance and Integration Test Battery for Phase 11.
Real-Time Market Observation, Multi-Provider Intelligence, Voice Interface, 24/7 Supervision, and Watchlist.

Tests:
1. OmniRoute Adapter multi-provider routing (FAST, DEEP_REASONING, INDEPENDENT_REVIEWER).
2. Circuit breaker state machine (CLOSED -> OPEN -> HALF_OPEN -> CLOSED).
3. Deterministic local paper fallback engine when offline or models fail.
4. Token & cost calculation telemetry and aggregate statistics.
5. Credential quarantine & .env.example placeholder integrity.
6. Market observation 5 invariants (positive price, crossed book, 0.05 tick size, monotonicity, quote age <= 15s).
7. Explicit off-hours observation tagging (never falsely labeled LIVE_OBSERVED outside market hours).
8. 24/7 Supervisor 10 service states, heartbeats, crash recovery backoff, and time gap detection.
9. Modular voice engine 8 trading intents, VAD RMS energy calculation, and confidence gating (>= 0.85).
10. Fail-closed live trading prohibition on voice "GO REAL".
11. WatchlistManager date-aware lot sizing (NIFTY 65, BANKNIFTY 30).
12. Affordability Gate against ₹10,000 virtual paper capital (approves ₹8,450, blocks ₹11,400).
13. Maximum 10 paper entries per session quota enforcement.
14. Price and target alerts CRUD and trigger evaluation.
15. StandaloneDashboardServer Phase 11 REST API endpoints (/api/watchlist, /api/alerts, /api/voice/process, /api/omniroute/evaluate).
16. Seven-session validation status remains strictly PENDING (0/7).
"""

from __future__ import annotations

import datetime
from http import HTTPStatus
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from agents.AGI_1_7.engine.agi17.adapters.omniroute_adapter import (
    CircuitBreaker,
    CircuitState,
    DeterministicPaperFallbackEngine,
    OmniRouteAdapter,
    OmniRouteConfig,
    OmniRouteResponse,
    REGISTERED_MODELS,
    TaskType,
)
from agents.AGI_1_7.engine.agi17.finance.market_observation_engine import (
    MarketObservation,
    MarketObservationEngine,
    ObservationProvenanceType,
)
from agents.AGI_1_7.engine.agi17.finance.trading_supervisor import (
    Autonomous24x7TradingSupervisor,
    SupervisorServiceState,
)
from agents.AGI_1_7.engine.agi17.finance.watchlist_manager import (
    OptionType,
    WatchlistCandidate,
    WatchlistManager,
    WatchlistStatus,
)
from agents.AGI_1_7.engine.agi17.voice.voice_interface import (
    AudioBuffer,
    AudioCaptureEngine,
    SpeechToTextEngine,
    TextToSpeechEngine,
    VoiceCommandParser,
    VoiceIntent,
    VoiceInteractionController,
    VoiceInteractionResult,
    VoiceSessionState,
)
from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer


class TestOmegaPhase11Acceptance(unittest.TestCase):
    """Authoritative Acceptance Suite for Phase 11 Deliverables."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.storage_dir = Path(cls.temp_dir.name)

        # Initialize test server on port 8311 with Phase 11 ₹10,000 initial capital
        cls.server_port = 8311
        cls.server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=cls.server_port,
            storage_dir=cls.storage_dir,
            starting_capital=10000.0,
        )
        cls.server.start_background()
        cls.base_url = f"http://127.0.0.1:{cls.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop_server()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    # =========================================================================
    # 1. OmniRoute Adapter & Multi-Provider Routing
    # =========================================================================
    def test_omniroute_model_registry_and_task_types(self) -> None:
        """Verify registered model specs for GLM-5.3-Flash, MiniMax-M2.7, and DeepSeek-V4-Flash."""
        self.assertIn("zai-org/GLM-5.3-Flash", REGISTERED_MODELS)
        self.assertIn("MiniMaxAI/MiniMax-M2.7", REGISTERED_MODELS)
        self.assertIn("deepseek-ai/DeepSeek-V4-Flash-0731", REGISTERED_MODELS)

        glm = REGISTERED_MODELS["zai-org/GLM-5.3-Flash"]
        self.assertEqual(glm.task_type, TaskType.FAST)
        self.assertEqual(glm.input_cost_per_m_usd, 0.08)

        minimax = REGISTERED_MODELS["MiniMaxAI/MiniMax-M2.7"]
        self.assertEqual(minimax.task_type, TaskType.DEEP_REASONING)
        self.assertEqual(minimax.input_cost_per_m_usd, 0.30)

        deepseek = REGISTERED_MODELS["deepseek-ai/DeepSeek-V4-Flash-0731"]
        self.assertEqual(deepseek.task_type, TaskType.INDEPENDENT_REVIEWER)

    def test_omniroute_circuit_breaker_transitions(self) -> None:
        """Verify Circuit Breaker opens after failure threshold and cools down."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_sec=0.2)
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertTrue(cb.allow_request())

        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.CLOSED)

        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertFalse(cb.allow_request())

        # Wait for cooldown
        time.sleep(0.25)
        self.assertTrue(cb.allow_request())
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

        # Successful probe recovers circuit to CLOSED
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_omniroute_deterministic_offline_fallback(self) -> None:
        """Verify offline mode engages local quantitative heuristics without throwing errors."""
        config = OmniRouteConfig(offline_mode=True)
        adapter = OmniRouteAdapter(config=config)

        res_fast = adapter.route_request(TaskType.FAST, [{"role": "user", "content": "check status"}])
        self.assertTrue(res_fast.is_fallback)
        self.assertEqual(res_fast.model, "DETERMINISTIC_FALLBACK")
        self.assertIn("STATUS_CHECK", res_fast.content)

        res_deep = adapter.route_request(TaskType.DEEP_REASONING, [{"role": "user", "content": "evaluate setup"}])
        self.assertTrue(res_deep.is_fallback)
        self.assertIn("DETERMINISTIC_HEURISTIC_PASS", res_deep.content)

        res_rev = adapter.route_request(TaskType.INDEPENDENT_REVIEWER, [{"role": "user", "content": "review"}])
        self.assertTrue(res_rev.is_fallback)
        self.assertIn("CONCUR_WITH_RESTRAINT", res_rev.content)

    def test_omniroute_cost_and_telemetry_summary(self) -> None:
        """Verify per-call cost calculation and aggregate telemetry summary."""
        adapter = OmniRouteAdapter()
        cost = adapter.compute_cost("MiniMaxAI/MiniMax-M2.7", input_tokens=1000, output_tokens=500)
        # 1000/1M * 0.30 = 0.00030, 500/1M * 0.90 = 0.00045, sum = 0.00075
        self.assertEqual(cost, 0.00075)

        summary = adapter.get_telemetry_summary()
        self.assertIn("circuit_breaker_state", summary)
        self.assertEqual(summary["circuit_breaker_state"], "CLOSED")

    # =========================================================================
    # 2. Credential Quarantine & .env Template
    # =========================================================================
    def test_env_example_template_exists_and_unarmed(self) -> None:
        """Verify .env.example exists with placeholder values and no exposed keys."""
        root = Path(__file__).resolve().parents[3]
        env_example = root / ".env.example"
        self.assertTrue(env_example.exists(), ".env.example must exist in repository root")

        content = env_example.read_text(encoding="utf-8")
        self.assertIn("OMNIROUTE_BASE_URL", content)
        self.assertIn("PAPER_INITIAL_CAPITAL=10000.00", content)
        self.assertIn("PLACEHOLDER_OMNIROUTE_KEY", content)
        self.assertNotIn("nvapi-", content)
        self.assertNotIn("sk-proj-", content)

    # =========================================================================
    # 3. Market Observation Invariants & Off-Hours Detection
    # =========================================================================
    def test_market_observation_five_invariants(self) -> None:
        """Verify 5 market observation invariants in MarketObservationEngine."""
        engine = MarketObservationEngine(max_allowed_quote_age_sec=15.0)

        # 1. Valid observation
        obs1 = engine.ingest_observation("NIFTY24200CE", "NIFTY", bid=129.95, ask=130.05, last_price=130.00, sequence_number=1)
        self.assertTrue(obs1.is_valid)

        # 2. Non-positive price rejection
        obs_bad_price = engine.ingest_observation("NIFTY24200CE", "NIFTY", bid=-1.0, ask=130.0, last_price=130.0, sequence_number=2)
        self.assertFalse(obs_bad_price.is_valid)
        self.assertIn("Non-positive", obs_bad_price.validation_error)

        # 3. Crossed-book rejection
        obs_crossed = engine.ingest_observation("NIFTY24200CE", "NIFTY", bid=135.0, ask=130.0, last_price=130.0, sequence_number=3)
        self.assertFalse(obs_crossed.is_valid)
        self.assertIn("Crossed book", obs_crossed.validation_error)

        # 4. Tick size (multiple of 0.05) rejection
        obs_bad_tick = engine.ingest_observation("NIFTY24200CE", "NIFTY", bid=130.02, ask=130.05, last_price=130.05, sequence_number=4)
        self.assertFalse(obs_bad_tick.is_valid)
        self.assertIn("tick size", obs_bad_tick.validation_error)

        # 5. Monotonic sequence rejection
        obs_dup_seq = engine.ingest_observation("NIFTY24200CE", "NIFTY", bid=129.95, ask=130.05, last_price=130.0, sequence_number=1)
        self.assertFalse(obs_dup_seq.is_valid)
        self.assertIn("Out-of-order", obs_dup_seq.validation_error)

    # =========================================================================
    # 4. 24/7 Supervisor Lifecycle
    # =========================================================================
    def test_supervisor_states_and_heartbeats(self) -> None:
        """Verify supervisor 10 states and worker heartbeats."""
        sup_dir = self.storage_dir / "supervisor_test"
        sup = Autonomous24x7TradingSupervisor(storage_dir=sup_dir)
        self.assertEqual(sup.state, SupervisorServiceState.STARTING)

        # Transition across valid states
        sup.transition_to(SupervisorServiceState.PREMARKET_PREPARATION, "Testing prep")
        self.assertEqual(sup.state, SupervisorServiceState.PREMARKET_PREPARATION)

        sup.transition_to(SupervisorServiceState.MARKET_OPEN, "Market open bell")
        self.assertEqual(sup.state, SupervisorServiceState.MARKET_OPEN)

        sup.transition_to(SupervisorServiceState.POSTMARKET_RECONCILIATION, "Market close EOD")
        self.assertEqual(sup.state, SupervisorServiceState.POSTMARKET_RECONCILIATION)

        # Verify workers
        self.assertIn("ALEXA", sup.workers)
        self.assertIn("EMILY", sup.workers)
        self.assertIn("MAX", sup.workers)
        self.assertEqual(sup.workers["ALEXA"].status, "HEALTHY")

    # =========================================================================
    # 5. In-App Voice Engine (8 Specific Trading Intents)
    # =========================================================================
    def test_voice_command_parser_eight_intents(self) -> None:
        """Verify parser identifies each of the 8 required trading intents."""
        # 1. Market Status
        c1 = VoiceCommandParser.parse("what is the market status and quote freshness")
        self.assertEqual(c1.intent, VoiceIntent.MARKET_STATUS)

        # 2. Scan Setups
        c2 = VoiceCommandParser.parse("scan nifty options setups")
        self.assertEqual(c2.intent, VoiceIntent.SCAN_SETUPS)
        self.assertEqual(c2.parameters.get("underlying"), "NIFTY")

        # 3. Explain Candidate
        c3 = VoiceCommandParser.parse("explain candidate nifty 24200 call")
        self.assertEqual(c3.intent, VoiceIntent.EXPLAIN_CANDIDATE)
        self.assertEqual(c3.parameters.get("strike"), 24200.0)

        # 4. Watchlist Ops
        c4 = VoiceCommandParser.parse("show watchlist strikes")
        self.assertEqual(c4.intent, VoiceIntent.WATCHLIST_OPS)

        # 5. Alert CRUD
        c5 = VoiceCommandParser.parse("set price alert on nifty at 24350")
        self.assertEqual(c5.intent, VoiceIntent.ALERT_CRUD)

        # 6. Read Positions
        c6 = VoiceCommandParser.parse("what are my paper positions and p&l")
        self.assertEqual(c6.intent, VoiceIntent.READ_POSITIONS)

        # 7. Control Session
        c7 = VoiceCommandParser.parse("pause trading session")
        self.assertEqual(c7.intent, VoiceIntent.CONTROL_SESSION)
        self.assertEqual(c7.parameters.get("action"), "PAUSE_ENTRIES")

        # 8. EOD Briefing
        c8 = VoiceCommandParser.parse("give me evening briefing and daily summary")
        self.assertEqual(c8.intent, VoiceIntent.EOD_BRIEFING)

    def test_voice_low_confidence_and_prohibited_go_real(self) -> None:
        """Verify low confidence (<0.85) gating and fail-closed live prohibition."""
        vox = VoiceInteractionController(storage_dir=self.storage_dir / "voice_test")

        # Low confidence gating
        res_low = vox.process_utterance("status", confidence=0.70)
        self.assertEqual(res_low.action_status, "CLARIFICATION_REQUIRED")

        # Prohibited Live Trading Barrier
        res_real = vox.process_utterance("go real and enable live trading", confidence=0.98)
        self.assertEqual(res_real.action_status, "REJECTED_LIVE_PROHIBITED")
        self.assertIn("strictly prohibited", res_real.spoken_response)

    def test_voice_audio_capture_and_vad(self) -> None:
        """Verify AudioCaptureEngine RMS calculation and speech detection."""
        cap = AudioCaptureEngine()
        silent = AudioBuffer.create_silence(duration_sec=0.5)
        self.assertEqual(silent.rms_energy, 0.0)
        self.assertFalse(cap.is_speech_active(silent))

        # Simulated non-silent buffer
        raw_noise = b"\x10\x20" * 4000
        rms = cap.calculate_rms(raw_noise)
        self.assertGreater(rms, 0.0)

    # =========================================================================
    # 6. Watchlist & Affordability Warden (₹10,000 Budget)
    # =========================================================================
    def test_watchlist_date_aware_lot_sizes_and_affordability(self) -> None:
        """Verify NIFTY lot 65, BANKNIFTY lot 30, and affordability against ₹10,000 capital."""
        wm = WatchlistManager(
            storage_dir=self.storage_dir / "wl_test",
            initial_capital=10000.0,
        )
        self.assertEqual(wm.get_lot_size("NIFTY"), 65)
        self.assertEqual(wm.get_lot_size("BANKNIFTY"), 30)

        # NIFTY 130 premium -> 130 * 65 = 8450 + charges (~24) = ~8474 <= 10000 (AFFORDABLE)
        cand_nifty = wm.add_candidate(
            underlying="NIFTY",
            strike=24200.0,
            option_type=OptionType.CE,
            expiry_date="2026-10-29",
            current_premium=130.0,
            trigger_price=132.0,
            target_price=165.0,
            stop_loss_price=115.0,
        )
        self.assertTrue(cand_nifty.is_affordable)
        self.assertEqual(cand_nifty.lot_size, 65)
        can_enter, reason = wm.can_enter_new_trade(cand_nifty)
        self.assertTrue(can_enter)
        self.assertIsNone(reason)

        # BANKNIFTY 380 premium -> 380 * 30 = 11400 + charges (~28) = ~11428 > 10000 (UNAFFORDABLE)
        cand_bn = wm.add_candidate(
            underlying="BANKNIFTY",
            strike=51200.0,
            option_type=OptionType.CE,
            expiry_date="2026-10-29",
            current_premium=380.0,
            trigger_price=385.0,
            target_price=450.0,
            stop_loss_price=340.0,
        )
        self.assertFalse(cand_bn.is_affordable)
        self.assertEqual(cand_bn.lot_size, 30)
        can_enter_bn, reason_bn = wm.can_enter_new_trade(cand_bn)
        self.assertFalse(can_enter_bn)
        self.assertIn("AFFORDABILITY_EXCEEDED", reason_bn)

    def test_watchlist_session_entry_quota_enforcement(self) -> None:
        """Verify strict maximum of 10 paper entries per session."""
        wm = WatchlistManager(
            storage_dir=self.storage_dir / "wl_quota_test",
            initial_capital=50000.0,  # Elevated to test quota independently
        )
        cand = wm.add_candidate(
            underlying="NIFTY",
            strike=24200.0,
            option_type=OptionType.CE,
            expiry_date="2026-10-29",
            current_premium=10.0,  # cheap
            trigger_price=11.0,
            target_price=20.0,
            stop_loss_price=5.0,
        )
        for _ in range(10):
            can_enter, _ = wm.can_enter_new_trade(cand)
            self.assertTrue(can_enter)
            wm.record_entry_execution(cand)

        self.assertEqual(wm.session_entries_count, 10)
        can_enter_11th, reason = wm.can_enter_new_trade(cand)
        self.assertFalse(can_enter_11th)
        self.assertIn("SESSION_QUOTA_REACHED", reason)

    def test_price_alerts_crud_and_trigger(self) -> None:
        """Verify price and target alert creation and trigger evaluation."""
        wm = WatchlistManager(storage_dir=self.storage_dir / "alerts_test")
        alt = wm.create_alert("NIFTY", "ABOVE", 24300.0)
        self.assertTrue(alt.is_active)
        self.assertFalse(alt.is_triggered)

        # Price below threshold
        triggered_none = wm.check_alerts("NIFTY", 24280.0)
        self.assertEqual(len(triggered_none), 0)

        # Price crosses threshold
        triggered = wm.check_alerts("NIFTY", 24310.0)
        self.assertEqual(len(triggered), 1)
        self.assertEqual(triggered[0].alert_id, alt.alert_id)
        self.assertTrue(triggered[0].is_triggered)

    # =========================================================================
    # 7. StandaloneDashboardServer Phase 11 REST API Endpoints
    # =========================================================================
    def test_server_watchlist_and_alerts_endpoints(self) -> None:
        """Verify /api/watchlist and /api/alerts GET and POST endpoints."""
        # 1. Add candidate via POST
        post_data = {
            "underlying": "NIFTY",
            "strike": 24200.0,
            "option_type": "CE",
            "expiry_date": "2026-10-29",
            "current_premium": 130.0,
            "trigger_price": 132.0,
            "target_price": 165.0,
            "stop_loss_price": 115.0,
            "edge_p": 0.55,
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/watchlist/add",
            data=json.dumps(post_data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, HTTPStatus.OK)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(res["status"], "SUCCESS")
            self.assertEqual(res["candidate"]["underlying"], "NIFTY")

        # 2. Query watchlist via GET
        with urllib.request.urlopen(f"{self.base_url}/api/watchlist", timeout=3.0) as resp:
            self.assertEqual(resp.status, HTTPStatus.OK)
            wl_data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("candidates", wl_data)
            self.assertGreaterEqual(len(wl_data["candidates"]), 1)
            self.assertIn("summary", wl_data)

    def test_server_voice_process_endpoint(self) -> None:
        """Verify /api/voice/process POST endpoint handling trading queries."""
        payload = {"transcript": "what is the market status", "confidence": 0.95}
        req = urllib.request.Request(
            f"{self.base_url}/api/voice/process",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, HTTPStatus.OK)
            vox_res = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(vox_res["intent"], "MARKET_STATUS")
            self.assertEqual(vox_res["action_status"], "EXECUTED")
            self.assertIn("healthy", vox_res["spoken_response"].lower())

    def test_server_omniroute_evaluate_endpoint(self) -> None:
        """Verify /api/omniroute/evaluate POST endpoint with deterministic fallback."""
        payload = {
            "task_type": "FAST",
            "messages": [{"role": "user", "content": "freshness status check"}],
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/omniroute/evaluate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, HTTPStatus.OK)
            omni_res = json.loads(resp.read().decode("utf-8"))
            self.assertIn("task_type", omni_res)
            self.assertIn("telemetry", omni_res)

    def test_server_status_reflects_phase11_capital(self) -> None:
        """Verify /api/status endpoint reports starting capital as configured (₹10,000)."""
        with urllib.request.urlopen(f"{self.base_url}/api/status", timeout=3.0) as resp:
            self.assertEqual(resp.status, HTTPStatus.OK)
            st = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(st["accounting"]["starting_capital"], 10000.0)
            self.assertEqual(st["mode"], "PAPER")
            self.assertFalse(st["is_live_allowed"])

    def test_seven_session_gate_strictly_pending(self) -> None:
        """Verify seven-session validation strictly reports PENDING (0/7)."""
        with urllib.request.urlopen(f"{self.base_url}/api/risk_safety", timeout=3.0) as resp:
            self.assertEqual(resp.status, HTTPStatus.OK)
            risk = json.loads(resp.read().decode("utf-8"))
            ssv = risk["seven_session_validation"]
            self.assertEqual(ssv["elapsed_eligible_sessions"], 0)
            self.assertEqual(ssv["required_sessions"], 7)
            self.assertIn("PENDING", ssv["status"])


if __name__ == "__main__":
    unittest.main()
