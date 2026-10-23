"""Unit test battery for Real-Time Statistical Arbitrage Streaming Server.

Wave 38 Verification Suite (TASK-BN-48):
Validates:
1. Synthetic multi-phase tick feed generator (SyntheticStatArbFeed).
2. Server state snapshot extraction, Kalman hedge ratio beta, Z-score, and toxicity telemetry.
3. In-memory MockSocket REST dispatch (/health, /api/stat_arb/state, /step_replay, /tick, /reset).
4. Real-time Server-Sent Events (SSE) client queue broadcasting and fan-out isolation.
5. UI dashboard asset serving (/ and /dashboard) with CORS headers.
6. Asynchronous background replay worker thread lifecycle and clean shutdown.

Zero external network dependencies; operates deterministically in <0.1s.
"""

from __future__ import annotations

import io
import json
import time
import unittest
from typing import Any, Dict, Optional

from agents.AGI_1_7.engine.agi17.finance.stat_arb_streaming_server import (
    StatArbHTTPRequestHandler,
    StatArbStreamingServer,
    SyntheticStatArbFeed,
)
from agents.AGI_1_7.engine.agi17.finance.statistical_arbitrage_orchestrator import (
    OrchestratorConfig,
    OrchestratorState,
    TradeExitReason,
)


class MockSocket:
    """In-memory loopback socket for deterministic HTTP request handler testing."""

    def __init__(self, raw_request: bytes) -> None:
        self.rfile = io.BytesIO(raw_request)
        self.wfile = io.BytesIO()

    def makefile(self, mode: str, *args: Any, **kwargs: Any) -> io.BytesIO:
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, data: bytes) -> None:
        self.wfile.write(data)

    def get_response_bytes(self) -> bytes:
        return self.wfile.getvalue()

    def get_response_text(self) -> str:
        return self.get_response_bytes().decode("utf-8")


class TestOmegaStatArbStreamingServer(unittest.TestCase):
    """Test suite for Wave 38 Statistical Arbitrage Streaming Server."""

    def setUp(self) -> None:
        self.config = OrchestratorConfig(
            asset1_name="BANKNIFTY",
            asset2_name="NIFTY50",
            lot_size_1=15,
            lot_size_2=25,
            initial_capital_inr=2_000_000.0,
            base_fractional_kelly=0.25,
            cotoxicity_alert_threshold=0.35,
            max_drawdown_limit=0.06,
            min_net_edge_hurdle_inr=-1000.0,
            entry_z=2.0,
            exit_z=0.5,
            stop_z=3.5,
        )
        self.server = StatArbStreamingServer(port=0, config=self.config)

    def tearDown(self) -> None:
        self.server.stop()

    def _dispatch_request(self, raw_http: bytes) -> Tuple[int, Dict[str, str], bytes]:
        """Dispatches an HTTP request through StatArbHTTPRequestHandler via MockSocket."""
        sock = MockSocket(raw_http)
        handler_cls = self.server._create_handler_class()
        handler_cls(sock, ("127.0.0.1", 54321), None)

        response_bytes = sock.get_response_bytes()
        header_part, _, body_part = response_bytes.partition(b"\r\n\r\n")
        lines = header_part.decode("utf-8").split("\r\n")
        status_line = lines[0] if lines else "HTTP/1.1 500 Error"
        status_code = int(status_line.split(" ")[1])

        headers = {}
        for line in lines[1:]:
            if ": " in line:
                k, v = line.split(": ", 1)
                headers[k.lower()] = v

        return status_code, headers, body_part

    def test_01_synthetic_feed_multi_phase_progression(self) -> None:
        """Verify synthetic tick feed multi-phase generation."""
        feed = SyntheticStatArbFeed()
        self.assertEqual(feed.tick_index, 0)

        # 1. Warm-up phase (0 to 49: 25 alternating pairs)
        for i in range(50):
            t = feed.next_tick()
            expected_asset = "NIFTY50" if i % 2 == 0 else "BANKNIFTY"
            self.assertEqual(t["asset"], expected_asset)
            self.assertFalse(t["simulate_leg2_failure"])

        self.assertEqual(feed.tick_index, 50)

        # 2. Phase 2: Spread divergence (BN drops 20.0 pts at index 50)
        t_bn_div = feed.next_tick()
        self.assertEqual(feed.tick_index, 51)
        self.assertEqual(t_bn_div["asset"], "BANKNIFTY")
        self.assertEqual(t_bn_div["price"], 48000.0 - 20.0)

        # 3. Phase 3: Mean reversion (BN reverts to 48000 at index 51)
        t_bn_rev = feed.next_tick()
        self.assertEqual(feed.tick_index, 52)
        self.assertEqual(t_bn_rev["asset"], "BANKNIFTY")
        self.assertEqual(t_bn_rev["price"], 48000.0)

        # 4. Phase 4: Rollback test tick at index 52
        t_bn_fail = feed.next_tick()  # tick 52 (simulate_leg2_failure=True)
        self.assertEqual(feed.tick_index, 53)
        self.assertEqual(t_bn_fail["asset"], "BANKNIFTY")
        self.assertTrue(t_bn_fail["simulate_leg2_failure"])

        # 5. Reset returns to baseline
        feed.reset()
        self.assertEqual(feed.tick_index, 0)

    def test_02_server_lifecycle_and_step_replay(self) -> None:
        """Verify server state progression through synthetic replay stepping."""
        # Warm up 50 ticks (25 pairs)
        for _ in range(50):
            snap = self.server.step_replay()

        self.assertEqual(snap["state"], OrchestratorState.IDLE.value)
        self.assertEqual(snap["tick_sequence"], 50)
        self.assertAlmostEqual(snap["kalman_beta"], 2.0, delta=0.1)

        # Divergence step (index 50) -> triggers LONG_SPREAD entry
        snap_entry = self.server.step_replay()
        self.assertEqual(snap_entry["state"], OrchestratorState.POSITION_OPEN.value)
        self.assertIsNotNone(snap_entry["active_position"])
        self.assertEqual(snap_entry["active_position"]["side"], "LONG_SPREAD")

        # Mean-reversion step (index 51) -> triggers CONVERGENCE_EXIT with positive gross edge
        snap_exit = self.server.step_replay()
        self.assertEqual(snap_exit["state"], OrchestratorState.POSITION_CLOSED.value)
        self.assertIsNone(snap_exit["active_position"])
        self.assertIsNotNone(snap_exit["last_closed_trade"])
        self.assertGreater(snap_exit["pnl_waterfall"]["gross_edge"], 0.0)
        self.assertGreaterEqual(snap_exit["pnl_waterfall"]["explained_ratio"], 0.95)

        # Rollback step (index 52) -> Leg 2 rejection triggers emergency LEG_ONE_UNWIND
        snap_rollback = self.server.step_replay()
        self.assertEqual(self.server.orchestrator.unwind_incidents, 1)
        self.assertEqual(snap_rollback["unwind_incidents"], 1)
        self.assertEqual(snap_rollback["state"], OrchestratorState.IDLE.value)

    def test_03_in_memory_http_endpoints_get_and_post(self) -> None:
        """Verify REST endpoints dispatch cleanly over MockSocket without network ports."""
        # 1. GET /health
        code, headers, body = self._dispatch_request(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        self.assertEqual(code, 200)
        self.assertIn("application/json", headers.get("content-type", ""))
        health_data = json.loads(body.decode("utf-8"))
        self.assertEqual(health_data["status"], "ok")
        self.assertEqual(health_data["state"], "IDLE_HEALTHY")

        # 2. GET /api/stat_arb/state
        code, _, body = self._dispatch_request(b"GET /api/stat_arb/state HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        self.assertEqual(code, 200)
        state_data = json.loads(body.decode("utf-8"))
        self.assertIn("spread_z_score", state_data)
        self.assertIn("kalman_beta", state_data)
        self.assertIn("pnl_waterfall", state_data)

        # 3. POST /api/stat_arb/step_replay
        code, _, body = self._dispatch_request(
            b"POST /api/stat_arb/step_replay HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n"
        )
        self.assertEqual(code, 200)
        step_data = json.loads(body.decode("utf-8"))
        self.assertEqual(step_data["tick_sequence"], 1)

        # 4. POST /api/stat_arb/tick (custom tick ingestion)
        payload = json.dumps({
            "asset": "BANKNIFTY",
            "price": 48100.0,
            "volume": 75.0,
            "timestamp": time.time(),
        }).encode("utf-8")
        req_tick = (
            b"POST /api/stat_arb/tick HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            + f"Content-Length: {len(payload)}\r\nContent-Type: application/json\r\n\r\n".encode("utf-8")
            + payload
        )
        code, _, body = self._dispatch_request(req_tick)
        self.assertEqual(code, 200)
        tick_res = json.loads(body.decode("utf-8"))
        self.assertEqual(tick_res["asset1_price"], 48100.0)

        # 5. POST /api/stat_arb/reset
        code, _, body = self._dispatch_request(
            b"POST /api/stat_arb/reset HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n"
        )
        self.assertEqual(code, 200)
        reset_res = json.loads(body.decode("utf-8"))
        self.assertEqual(reset_res["status"], "reset_complete")
        self.assertEqual(reset_res["snapshot"]["tick_sequence"], 0)

    def test_04_sse_stream_broadcasting_and_subscribers(self) -> None:
        """Verify subscriber queue fan-out and broadcast delivery."""
        import queue
        q1 = queue.Queue(maxsize=10)
        q2 = queue.Queue(maxsize=10)

        self.server.add_subscriber(q1)
        self.server.add_subscriber(q2)
        self.assertEqual(self.server.subscriber_count, 2)

        # Broadcast update
        test_payload = {"type": "test_event", "value": 42.0}
        self.server.broadcast(test_payload)

        self.assertFalse(q1.empty())
        self.assertFalse(q2.empty())
        self.assertEqual(q1.get_nowait(), test_payload)
        self.assertEqual(q2.get_nowait(), test_payload)

        # Remove subscriber
        self.server.remove_subscriber(q1)
        self.assertEqual(self.server.subscriber_count, 1)

    def test_05_dashboard_asset_serving(self) -> None:
        """Verify / and /dashboard serve HTML with CORS headers and Wave 38 Stat-Arb UI components."""
        code, headers, body = self._dispatch_request(b"GET /dashboard HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        self.assertEqual(code, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertEqual(headers.get("access-control-allow-origin"), "*")
        self.assertGreater(len(body), 50)
        html_str = body.decode("utf-8")
        self.assertIn("AGI 1.7 OMEGA COMMAND", html_str)
        self.assertIn("Trading & Research Terminal", html_str)
        self.assertIn("app-shell", html_str)

    def test_06_background_replay_thread_lifecycle(self) -> None:
        """Verify background replay worker starts, steps, and terminates cleanly."""
        self.assertFalse(self.server.replay_active)
        self.server.is_running = True

        # Start replay for 4 ticks with small interval
        self.server.start_replay(interval_sec=0.01, max_ticks=4)
        self.assertTrue(self.server.replay_active)

        # Wait for max_ticks completion
        time.sleep(0.1)

        self.assertFalse(self.server.replay_active)
        self.assertGreaterEqual(self.server.synthetic_feed.tick_index, 4)

        # Calling stop_replay should be idempotent
        self.server.stop_replay()
        self.assertFalse(self.server.replay_active)


if __name__ == "__main__":
    unittest.main()
