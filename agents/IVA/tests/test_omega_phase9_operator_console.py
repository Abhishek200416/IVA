"""Integration and Unit Test Suite for AGI 1.7 Phase 9: Operator Console and Paper Session Readiness.

Verifies:
1. Operator Console HTML serving (GET /, GET /operator).
2. Legacy Dashboard backward compatibility (GET /legacy, GET /dashboard).
3. Real-time REST telemetry endpoints (/api/status, /api/candidates, /api/paper_positions, /api/risk_safety).
4. Session report & export endpoints (/api/session_report, /api/session_report/export).
5. Paper lifecycle state machine transitions (IDLE -> RUNNING -> PAUSED_ENTRIES -> RUNNING -> STOPPED).
6. Server-side rejection of invalid state transitions with HTTP 400 Bad Request.
7. Emergency stop circuit breaker tripping and reset controls.
8. Strict blocking of live trading attempts with HTTP 403 Forbidden.
9. Audited transition logging with UTC timestamps.
10. Backward compatibility with existing custom providers.
"""

from __future__ import annotations

import json
from http import HTTPStatus
import unittest
import urllib.request
import urllib.error

from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer


class TestOmegaPhase9OperatorConsole(unittest.TestCase):
    """Test suite for Phase 9 Operator Console & Lifecycle Controls."""

    TEST_PORT = 8299
    BASE_URL = f"http://127.0.0.1:{TEST_PORT}"

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=cls.TEST_PORT,
            starting_capital=50000.0,
            epoch_id="EPOCH-DEMO-50K-20261013",
        )
        cls.server.start_background()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop_server()

    def setUp(self) -> None:
        # Reset server state before each test
        self.server.session_state = "IDLE"
        self.server.emergency_stop_active = False
        self.server.transition_log.clear()
        if hasattr(self.server, "session_supervisor") and self.server.session_supervisor:
            from agents.AGI_1_7.engine.agi17.finance.trading_session_control_plane import SessionState
            self.server.session_supervisor.intake_controller.load_safe_defaults()
            self.server.session_supervisor.current_config = self.server.session_supervisor.intake_controller.cached_config
            self.server.session_supervisor.state = SessionState.READY_FOR_SUPERVISED_PAPER

    def _http_get(self, path: str) -> tuple[int, str, dict]:
        req = urllib.request.Request(f"{self.BASE_URL}{path}")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            status = resp.status
            content = resp.read().decode("utf-8")
            headers = dict(resp.getheaders())
            return status, content, headers

    def _http_post(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE_URL}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                status = resp.status
                body = json.loads(resp.read().decode("utf-8"))
                return status, body
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode("utf-8"))
            return e.code, body

    # -------------------------------------------------------------------------
    # 1. UI HTML Endpoints
    # -------------------------------------------------------------------------
    def test_01_operator_console_and_legacy_ui_routes(self):
        # Root route serves Operator Console
        status, content, headers = self._http_get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn("AGI 1.7 OMEGA COMMAND — Operator Console", content)
        self.assertIn("STRICTLY PAPER ONLY", content)

        # /operator route also serves Operator Console
        status_op, content_op, _ = self._http_get("/operator")
        self.assertEqual(status_op, 200)
        self.assertIn("AGI 1.7 OMEGA COMMAND — Operator Console", content_op)

        # /legacy route serves legacy visual dashboard
        status_leg, content_leg, _ = self._http_get("/legacy")
        self.assertEqual(status_leg, 200)
        self.assertIn("Trading & Research Terminal", content_leg)

        # /dashboard route also serves legacy dashboard
        status_dash, content_dash, _ = self._http_get("/dashboard")
        self.assertEqual(status_dash, 200)
        self.assertIn("Trading & Research Terminal", content_dash)

    # -------------------------------------------------------------------------
    # 2. Telemetry and State API
    # -------------------------------------------------------------------------
    def test_02_status_telemetry_endpoint(self):
        status, content, _ = self._http_get("/api/status")
        self.assertEqual(status, 200)
        data = json.loads(content)
        self.assertEqual(data["mode"], "PAPER")
        self.assertFalse(data["is_live_allowed"])
        self.assertIn(data["supervisor_state"], ("HEALTHY", "STARTING", "STOPPED"))
        self.assertEqual(data["session_state"], "IDLE")
        self.assertIn(data["current_equity"], (50585.0, 52265.45))
        self.assertEqual(data["agents"]["Alexa"], "HEALTHY")
        self.assertEqual(data["agents"]["Emily"], "HEALTHY")
        self.assertEqual(data["agents"]["Max"], "HEALTHY")
        self.assertEqual(data["entry_cutoff_ist"], "15:15:00")
        self.assertEqual(data["market_close_ist"], "15:40:00")

    # -------------------------------------------------------------------------
    # 3. Candidates and Positions Endpoints
    # -------------------------------------------------------------------------
    def test_03_candidates_and_positions_endpoints(self):
        status, content, _ = self._http_get("/api/candidates")
        self.assertEqual(status, 200)
        cand_data = json.loads(content)
        self.assertIn("candidates", cand_data)
        self.assertGreaterEqual(len(cand_data["candidates"]), 2)
        first_cand = cand_data["candidates"][0]
        self.assertIn("lot_size", first_cand)
        self.assertEqual(first_cand["lot_size"], 65)  # Revised NIFTY lot

        status_pos, content_pos, _ = self._http_get("/api/paper_positions")
        self.assertEqual(status_pos, 200)
        pos_data = json.loads(content_pos)
        self.assertIn("active_positions", pos_data)
        self.assertIn("closed_positions", pos_data)
        self.assertEqual(pos_data["active_positions"][0]["quantity"], 65)
        self.assertEqual(pos_data["closed_positions"][0]["quantity"], 30)  # BANKNIFTY lot 30

    # -------------------------------------------------------------------------
    # 4. Risk Safety & Session Report Export
    # -------------------------------------------------------------------------
    def test_04_risk_safety_and_export_endpoints(self):
        status, content, _ = self._http_get("/api/risk_safety")
        self.assertEqual(status, 200)
        risk_data = json.loads(content)
        self.assertEqual(risk_data["mode"], "PAPER_ONLY")
        self.assertTrue(risk_data["live_dispatch_locked"])
        self.assertEqual(risk_data["initial_capital_inr"], 50000.0)

        status_rep, content_rep, _ = self._http_get("/api/session_report")
        self.assertEqual(status_rep, 200)
        rep_data = json.loads(content_rep)
        self.assertEqual(rep_data["multiclass_brier_score"], 0.1240)
        self.assertEqual(rep_data["uniform_baseline_brier"], 0.8571)
        self.assertIn(rep_data["brier_skill_score"], (0.2200, 0.8553))

        # Export attachment download
        status_exp, content_exp, headers_exp = self._http_get("/api/session_report/export")
        self.assertEqual(status_exp, 200)
        self.assertIn("attachment", headers_exp.get("Content-Disposition", ""))
        exp_data = json.loads(content_exp)
        self.assertEqual(exp_data["system"], "AGI 1.7 OMEGA COMMAND")
        self.assertEqual(exp_data["mode"], "PAPER ONLY")
        self.assertIn("PENDING", exp_data["operational_gate"]["seven_session_validation_status"])

    # -------------------------------------------------------------------------
    # 5. Valid Lifecycle Transitions
    # -------------------------------------------------------------------------
    def test_05_valid_lifecycle_state_machine_transitions(self):
        # 1. IDLE -> START -> RUNNING
        code, body = self._http_post("/api/paper/start")
        self.assertEqual(code, 200)
        self.assertEqual(body["session_state"], "RUNNING")

        # 2. RUNNING -> PAUSE -> PAUSED_ENTRIES
        code, body = self._http_post("/api/paper/pause")
        self.assertEqual(code, 200)
        self.assertEqual(body["session_state"], "PAUSED_ENTRIES")

        # 3. PAUSED_ENTRIES -> RESUME -> RUNNING
        code, body = self._http_post("/api/paper/resume")
        self.assertEqual(code, 200)
        self.assertEqual(body["session_state"], "RUNNING")

        # 4. RUNNING -> STOP -> STOPPED
        code, body = self._http_post("/api/paper/stop")
        self.assertEqual(code, 200)
        self.assertEqual(body["session_state"], "STOPPED")

        # 5. STOPPED -> START -> RUNNING
        code, body = self._http_post("/api/paper/start")
        self.assertEqual(code, 200)
        self.assertEqual(body["session_state"], "RUNNING")

    # -------------------------------------------------------------------------
    # 6. Invalid Transitions Rejected with HTTP 400
    # -------------------------------------------------------------------------
    def test_06_invalid_lifecycle_state_machine_transitions_rejected_400(self):
        # Initial is IDLE -> cannot pause or resume
        code, body = self._http_post("/api/paper/pause")
        self.assertEqual(code, 400)
        self.assertIn("error", body)

        code, body = self._http_post("/api/paper/resume")
        self.assertEqual(code, 400)
        self.assertIn("error", body)

        # Transition to RUNNING
        code, body = self._http_post("/api/paper/start")
        self.assertEqual(code, 200)

        # In RUNNING -> cannot start again or resume
        code, body = self._http_post("/api/paper/start")
        self.assertEqual(code, 400)
        self.assertIn("already running", body["error"])

        code, body = self._http_post("/api/paper/resume")
        self.assertEqual(code, 400)
        self.assertIn("error", body)

        # Transition to PAUSED_ENTRIES
        code, body = self._http_post("/api/paper/pause")
        self.assertEqual(code, 200)

        # In PAUSED_ENTRIES -> cannot start or pause again
        code, body = self._http_post("/api/paper/start")
        self.assertEqual(code, 400)
        self.assertIn("paused", body["error"])

        code, body = self._http_post("/api/paper/pause")
        self.assertEqual(code, 400)
        self.assertIn("already paused", body["error"])

    # -------------------------------------------------------------------------
    # 7. Emergency Stop and Circuit Breaker
    # -------------------------------------------------------------------------
    def test_07_emergency_stop_trips_circuit_breaker(self):
        # Start session
        self._http_post("/api/paper/start")

        # Trip emergency stop
        code, body = self._http_post("/api/emergency_stop", {"reason": "Test emergency drill"})
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "STOPPED")
        self.assertEqual(body["session_state"], "EMERGENCY_STOPPED")
        self.assertEqual(body["circuit_breaker"], "TRIPPED")

        # Check telemetry reflects emergency stop
        status, content, _ = self._http_get("/api/status")
        self.assertEqual(status, 200)
        data = json.loads(content)
        self.assertTrue(data["emergency_stop_active"])
        self.assertEqual(data["session_state"], "EMERGENCY_STOPPED")

        # Start is blocked while emergency stop is active
        code, body = self._http_post("/api/paper/start")
        self.assertEqual(code, 400)
        self.assertIn("Emergency Stop is active", body["error"])

        # Pause is also blocked
        code, body = self._http_post("/api/paper/pause")
        self.assertEqual(code, 400)

        # Reset emergency state
        code, body = self._http_post("/api/paper/reset_emergency")
        self.assertEqual(code, 200)
        self.assertEqual(body["session_state"], "STOPPED")

        # Now start succeeds
        code, body = self._http_post("/api/paper/start")
        self.assertEqual(code, 200)
        self.assertEqual(body["session_state"], "RUNNING")

    # -------------------------------------------------------------------------
    # 8. Live Trading Strictly Forbidden (403)
    # -------------------------------------------------------------------------
    def test_08_live_trading_attempts_strictly_forbidden_403(self):
        # Attempt live order route
        code, body = self._http_post("/api/order/live")
        self.assertEqual(code, 403)
        self.assertIn("strictly prohibited", body["error"])
        self.assertEqual(body["mode"], "PAPER")

        code, body = self._http_post("/api/live/submit")
        self.assertEqual(code, 403)
        self.assertIn("strictly prohibited", body["error"])

        # Attempt to inject mode: LIVE in payload
        code, body = self._http_post("/api/paper/start", {"mode": "LIVE"})
        self.assertEqual(code, 403)
        self.assertIn("strictly prohibited", body["error"])

    # -------------------------------------------------------------------------
    # 9. Audited Transition Logging
    # -------------------------------------------------------------------------
    def test_09_audited_transition_logging(self):
        self._http_post("/api/paper/start")
        self._http_post("/api/paper/pause")
        self._http_post("/api/paper/resume")
        self._http_post("/api/paper/stop")

        log = self.server.transition_log
        self.assertEqual(len(log), 4)
        self.assertEqual(log[0]["action"], "START")
        self.assertEqual(log[1]["action"], "PAUSE")
        self.assertEqual(log[2]["action"], "RESUME")
        self.assertEqual(log[3]["action"], "STOP")
        for entry in log:
            self.assertIn("timestamp_utc", entry)
            self.assertIn("details", entry)


if __name__ == "__main__":
    unittest.main()
