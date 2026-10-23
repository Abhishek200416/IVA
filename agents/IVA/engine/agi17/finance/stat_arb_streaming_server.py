"""Real-Time Statistical Arbitrage & Microstructure Alpha Streaming Server.

Wave 38 Deliverable (TASK-BN-48):
Synthesized by Max & Emily (AGI 1.7 OMEGA COMMAND) for High-Frequency Pairs Trading:
1. Zero-Dependency Streaming Engine:
   - Standard library http.server and Server-Sent Events (SSE) streaming (/api/stat_arb/stream).
   - High-throughput asynchronous client fan-out using thread-safe subscriber queues.
   - Dynamic port binding (port=0 support for collision-free testing).
2. Institutional State & Microstructure Telemetry Pipeline:
   - Dynamic Spread Z-Score oscillator with entry/exit/stop bands.
   - Dynamic Kalman state-space hedge ratio beta(t), intercept, and Ornstein-Uhlenbeck half-life.
   - Live Legging Risk & Atomic Rollback alert badge (LEG_ONE_UNWIND).
   - Toxicity-Gated Kelly allocation multiplier and cross-asset co-toxicity/VPIN telemetry.
   - Strict Monotonic Decomposed P&L Waterfall (Gross Edge vs Market Impact vs Indian Statutory Costs).
3. Deterministic Synthetic Feed Replay:
   - Built-in multi-phase Bank Nifty vs Nifty 50 synthetic pairs generator.
   - Automated replay phases covering: stationary spread oscillation, entry divergence,
     mean-reversion convergence exit, Leg-2 failure rollback (LEG_ONE_UNWIND),
     and adverse selection co-toxicity spike (FROZEN_TOXIC).
   - Synchronous single-stepping (/api/stat_arb/step_replay) or asynchronous background looping.
4. REST Control Surface & UI Integration:
   - Endpoints: /health, /api/stat_arb/state, /api/stat_arb/stream, /api/stat_arb/tick,
     /api/stat_arb/start_replay, /api/stat_arb/stop_replay, /api/stat_arb/step_replay, /api/stat_arb/reset.
   - Seamless dashboard hosting for agents/AGI_1_7/ui/trading_dashboard.html.

Zero external dependencies outside standard Python 3.11 libraries.
"""

from __future__ import annotations

import json
import math
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

from .cross_asset_toxicity import CrossAssetToxicityEngine
from .kalman_spread_filter import KalmanSpreadFilter
from .statistical_arbitrage_orchestrator import (
    OrchestratorConfig,
    OrchestratorState,
    SpreadPosition,
    SpreadTradeSide,
    StatisticalArbitrageOrchestrator,
    TradeExitReason,
)


class SyntheticStatArbFeed:
    """Deterministic multi-phase tick generator for Bank Nifty & Nifty 50 pairs stat-arb."""

    def __init__(
        self,
        base_nifty: float = 24000.0,
        base_banknifty: float = 48000.0,
        base_beta: float = 2.0,
    ) -> None:
        self.base_nifty = float(base_nifty)
        self.base_banknifty = float(base_banknifty)
        self.base_beta = float(base_beta)
        self.tick_index = 0
        self.current_timestamp = 1700000000.0

    def reset(self) -> None:
        """Resets tick index and timestamp to baseline."""
        self.tick_index = 0
        self.current_timestamp = 1700000000.0

    def next_tick(self) -> Dict[str, Any]:
        """Generates the next individual sequential market tick (alternating NIFTY / BANKNIFTY).

        Tick Schedule:
        0 - 49 (25 pairs): Warm-up calibration. Alternates NIFTY50 and BANKNIFTY with stationary error ~ 0.
        50: Divergence tick - BANKNIFTY drops 20 pts (47980.0) -> triggers LONG_SPREAD entry (POSITION_OPEN)
        51: Mean-reversion tick - BANKNIFTY returns to 48000.0 -> triggers CONVERGENCE_EXIT (gross edge +300)
        52: Equilibrium hold - NIFTY50 tick at 24000.5
        53: Rollback test tick - BANKNIFTY drops 20 pts with simulate_leg2_failure=True -> triggers LEG_ONE_UNWIND
        54: Post-rollback equilibrium - BANKNIFTY returns to 48000.0
        55 - 58: Adverse volume shock - BANKNIFTY high volume ticks (v=500) -> triggers FROZEN_TOXIC
        59+: Stationary oscillation
        """
        i = self.tick_index
        self.tick_index += 1
        t = self.current_timestamp + (i * 0.5)

        if i < 50:
            pair_idx = i // 2
            is_nifty = (i % 2 == 0)
            if is_nifty:
                noise = 0.5 if pair_idx % 2 == 0 else -0.5
                return {
                    "asset": "NIFTY50",
                    "price": round(self.base_nifty + noise, 2),
                    "volume": 100.0,
                    "timestamp": t,
                    "simulate_leg2_failure": False,
                }
            else:
                noise = 1.0 if pair_idx % 2 == 0 else -1.0
                return {
                    "asset": "BANKNIFTY",
                    "price": round(self.base_banknifty + noise, 2),
                    "volume": 50.0,
                    "timestamp": t,
                    "simulate_leg2_failure": False,
                }
        elif i == 50:
            # Spread divergence entry
            return {
                "asset": "BANKNIFTY",
                "price": self.base_banknifty - 20.0,
                "volume": 50.0,
                "timestamp": t,
                "simulate_leg2_failure": False,
            }
        elif i == 51:
            # Mean reversion convergence exit
            return {
                "asset": "BANKNIFTY",
                "price": self.base_banknifty,
                "volume": 50.0,
                "timestamp": t,
                "simulate_leg2_failure": False,
            }
        elif i == 52:
            # Divergence with Leg 2 rejection -> triggers LEG_ONE_UNWIND
            return {
                "asset": "BANKNIFTY",
                "price": self.base_banknifty - 20.0,
                "volume": 50.0,
                "timestamp": t,
                "simulate_leg2_failure": True,
            }
        elif i == 53:
            # Post-rollback equilibrium
            return {
                "asset": "BANKNIFTY",
                "price": self.base_banknifty,
                "volume": 50.0,
                "timestamp": t,
                "simulate_leg2_failure": False,
            }
        elif 54 <= i <= 58:
            # Phase 5: Adverse volume shock
            return {
                "asset": "BANKNIFTY",
                "price": self.base_banknifty + (i - 53) * 10.0,
                "volume": 500.0,
                "timestamp": t,
                "simulate_leg2_failure": False,
            }
        else:
            cycle = (i - 59) % 20
            p = self.base_banknifty + math.sin(cycle * 0.3) * 6.0
            return {
                "asset": "BANKNIFTY",
                "price": round(p, 2),
                "volume": 50.0,
                "timestamp": t,
                "simulate_leg2_failure": False,
            }

    def next_tick_pair(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Convenience method returning a pair of consecutive ticks."""
        t1 = self.next_tick()
        t2 = self.next_tick()
        return t1, t2



class StatArbHTTPRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler supporting REST endpoints, SSE streams, and UI assets."""

    server_instance: StatArbStreamingServer

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default HTTP stderr logging for clean test execution."""
        return

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Cache-Control")

    def _send_json_response(self, status_code: int, data: Dict[str, Any]) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        """Handle CORS pre-flight requests."""
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path in ("/health", "/api/health"):
            self._send_json_response(200, {
                "status": "ok",
                "state": "IDLE_HEALTHY",
                "port": self.server_instance.bound_port,
                "subscribers_count": self.server_instance.subscriber_count,
            })
            return

        if path == "/api/stat_arb/state":
            snapshot = self.server_instance.get_state_snapshot()
            self._send_json_response(200, snapshot)
            return

        if path in ("/api/stat_arb/stream", "/stream", "/events"):
            self._handle_sse_stream()
            return

        if path in ("/", "/dashboard", "/ui"):
            self._serve_dashboard()
            return

        # 404 for unknown endpoints
        self._send_json_response(404, {"error": "Not Found", "path": path})

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        content_length = int(self.headers.get("Content-Length", 0))
        body_data = {}
        if content_length > 0:
            try:
                body_bytes = self.rfile.read(content_length)
                body_data = json.loads(body_bytes.decode("utf-8"))
            except Exception as e:
                self._send_json_response(400, {"error": "Invalid JSON payload", "details": str(e)})
                return

        if path == "/api/stat_arb/tick":
            try:
                asset = str(body_data["asset"])
                price = float(body_data["price"])
                volume = float(body_data.get("volume", 100.0))
                timestamp = float(body_data.get("timestamp", time.time()))
                sim_fail = bool(body_data.get("simulate_leg2_failure", False))

                snapshot = self.server_instance.process_tick(
                    asset=asset,
                    price=price,
                    volume=volume,
                    timestamp=timestamp,
                    simulate_leg2_failure=sim_fail,
                )
                self._send_json_response(200, snapshot)
            except KeyError as e:
                self._send_json_response(400, {"error": f"Missing required parameter: {e}"})
            return

        if path == "/api/stat_arb/start_replay":
            interval = float(body_data.get("interval_sec", 0.1))
            num_ticks = body_data.get("num_ticks")
            if num_ticks is not None:
                num_ticks = int(num_ticks)
            self.server_instance.start_replay(interval_sec=interval, max_ticks=num_ticks)
            self._send_json_response(200, {
                "status": "replay_started",
                "interval_sec": interval,
                "max_ticks": num_ticks,
            })
            return

        if path == "/api/stat_arb/stop_replay":
            self.server_instance.stop_replay()
            self._send_json_response(200, {"status": "replay_stopped"})
            return

        if path == "/api/stat_arb/step_replay":
            snapshot = self.server_instance.step_replay()
            self._send_json_response(200, snapshot)
            return

        if path == "/api/stat_arb/reset":
            self.server_instance.reset()
            self._send_json_response(200, {
                "status": "reset_complete",
                "snapshot": self.server_instance.get_state_snapshot(),
            })
            return

        self._send_json_response(404, {"error": "Endpoint Not Found", "path": path})

    def _handle_sse_stream(self) -> None:
        """Streams Server-Sent Events (SSE) to connected HTTP client."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._send_cors_headers()
        self.end_headers()

        client_queue: queue.Queue = queue.Queue(maxsize=100)
        self.server_instance.add_subscriber(client_queue)

        try:
            # 1. Send initial state snapshot immediately
            init_state = self.server_instance.get_state_snapshot()
            init_payload = f"data: {json.dumps(init_state)}\n\n"
            self.wfile.write(init_payload.encode("utf-8"))
            self.wfile.flush()

            # 2. Stream event updates from queue
            while self.server_instance.is_running:
                try:
                    payload = client_queue.get(timeout=0.5)
                    msg = f"data: {json.dumps(payload)}\n\n"
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # Send periodic keep-alive comment
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass
        finally:
            self.server_instance.remove_subscriber(client_queue)

    def _serve_dashboard(self) -> None:
        """Serves the trading terminal HTML file."""
        html_path = self.server_instance.dashboard_html_path
        if html_path and os.path.exists(html_path):
            with open(html_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
        else:
            fallback = b"<!DOCTYPE html><html><body><h1>AGI 1.7 Pairs Stat-Arb Server</h1><p>Terminal UI not found at path.</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(fallback)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(fallback)


class StatArbStreamingServer:
    """Multi-threaded Statistical Arbitrage WebSocket/SSE Streaming & REST Server."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8088,
        config: Optional[OrchestratorConfig] = None,
        orchestrator: Optional[StatisticalArbitrageOrchestrator] = None,
        dashboard_html_path: Optional[str] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.bound_port = port
        self.config = config or OrchestratorConfig(min_net_edge_hurdle_inr=-1000.0)
        self.orchestrator = orchestrator or StatisticalArbitrageOrchestrator(config=self.config)
        self.synthetic_feed = SyntheticStatArbFeed()

        # Dashboard UI path resolution
        if dashboard_html_path is not None:
            self.dashboard_html_path = dashboard_html_path
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.dashboard_html_path = os.path.normpath(
                os.path.join(current_dir, "..", "..", "..", "ui", "trading_dashboard.html")
            )

        # Thread synchronization & subscriber queues
        self.lock = threading.Lock()
        self.subscriber_lock = threading.Lock()
        self.subscribers: Set[queue.Queue] = set()

        # Server and replay lifecycle
        self.is_running = False
        self.replay_active = False
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.replay_thread: Optional[threading.Thread] = None

    @property
    def subscriber_count(self) -> int:
        with self.subscriber_lock:
            return len(self.subscribers)

    def add_subscriber(self, q: queue.Queue) -> None:
        with self.subscriber_lock:
            self.subscribers.add(q)

    def remove_subscriber(self, q: queue.Queue) -> None:
        with self.subscriber_lock:
            self.subscribers.discard(q)

    def broadcast(self, payload: Dict[str, Any]) -> None:
        """Pushes state updates to all active SSE client queues."""
        with self.subscriber_lock:
            dead_queues = []
            for q in list(self.subscribers):
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    pass
                except Exception:
                    dead_queues.append(q)
            for dq in dead_queues:
                self.subscribers.discard(dq)

    def get_state_snapshot(self) -> Dict[str, Any]:
        """Captures atomic state snapshot from the orchestrator and microstructure engines."""
        with self.lock:
            orch = self.orchestrator
            kalman = orch.kalman
            snap = kalman.last_snapshot

            tox_metrics = orch.toxicity_engine.compute_cotoxicity_metrics()
            vpin1 = tox_metrics.vpin_asset1 if tox_metrics else 0.0
            vpin2 = tox_metrics.vpin_asset2 if tox_metrics else 0.0
            rho_toxic = tox_metrics.rho_toxic_correlation if tox_metrics else 0.0

            # Active position details
            pos_data = None
            if orch.active_position:
                pos = orch.active_position
                pos_data = {
                    "position_id": pos.position_id,
                    "side": pos.side.value,
                    "entry_timestamp": pos.entry_timestamp,
                    "entry_z_score": round(pos.entry_z_score, 2),
                    "entry_beta": round(pos.entry_beta, 4),
                    "asset1_lots": pos.asset1_lots,
                    "asset2_lots": pos.asset2_lots,
                    "asset1_entry_price": pos.asset1_entry_price,
                    "asset2_entry_price": pos.asset2_entry_price,
                }

            # Last closed trade & attribution waterfall
            last_trade_data = None
            pnl_waterfall = {
                "gross_edge": 0.0,
                "market_impact_drag": 0.0,
                "statutory_costs": 0.0,
                "net_pnl": 0.0,
                "explained_ratio": 1.0,
            }
            if orch.completed_trades:
                last = orch.completed_trades[-1]
                if last.pnl_attribution:
                    decomp = last.pnl_attribution
                    last_trade_data = decomp.to_dict()
                    pnl_waterfall = {
                        "gross_edge": round(decomp.gross_edge_pnl, 2),
                        "market_impact_drag": round(decomp.market_impact_drag, 2),
                        "statutory_costs": round(decomp.statutory_fees_drag, 2),
                        "net_pnl": round(decomp.net_realized_pnl, 2),
                        "explained_ratio": round(decomp.explained_ratio, 4),
                    }

            kelly_kappa = orch.calculate_toxicity_gated_kelly(rho_toxic, max(vpin1, vpin2))

            p1 = orch.last_tick_asset1[0] if orch.last_tick_asset1 else 48000.0
            p2 = orch.last_tick_asset2[0] if orch.last_tick_asset2 else 24000.0

            half_life_val = 0.0
            try:
                hl = kalman.estimate_half_life()
                if hl and hl.is_mean_reverting and not math.isinf(hl.half_life_seconds):
                    half_life_val = hl.half_life_seconds
            except Exception:
                half_life_val = 0.0

            return {
                "type": "stat_arb_update",
                "timestamp": time.time(),
                "state": orch.state.value,
                "is_toxic_frozen": orch.state == OrchestratorState.FROZEN_TOXIC or kelly_kappa <= 0.0,
                "current_drawdown": round(orch.current_drawdown, 4),
                "total_realized_pnl": round(orch.total_realized_pnl, 2),
                "unwind_incidents": orch.unwind_incidents,
                "spread_z_score": round(snap.normalized_z_score, 2) if snap else 0.0,
                "entry_z": orch.config.entry_z,
                "exit_z": orch.config.exit_z,
                "stop_z": orch.config.stop_z,
                "kalman_beta": round(snap.hedge_ratio_beta, 4) if snap else 2.0,
                "kalman_intercept": round(snap.intercept_alpha, 2) if snap else 0.0,
                "spread_residual": round(snap.spread_error, 2) if snap else 0.0,
                "ou_half_life": round(half_life_val, 1),
                "vpin1": round(vpin1, 3),
                "vpin2": round(vpin2, 3),
                "co_toxicity": round(rho_toxic, 3),
                "kelly_fraction": round(kelly_kappa, 4),
                "asset1_price": round(p1, 2),
                "asset2_price": round(p2, 2),
                "active_position": pos_data,
                "last_closed_trade": last_trade_data,
                "pnl_waterfall": pnl_waterfall,
                "replay_active": self.replay_active,
                "tick_sequence": self.synthetic_feed.tick_index,
            }

    def process_tick(
        self,
        asset: str,
        price: float,
        volume: float,
        timestamp: float,
        simulate_leg2_failure: bool = False,
    ) -> Dict[str, Any]:
        """Ingests a single asset tick, drives the state machine, and broadcasts update."""
        with self.lock:
            self.orchestrator.on_tick(
                asset=asset,
                price=price,
                volume=volume,
                timestamp=timestamp,
                simulate_leg2_failure=simulate_leg2_failure,
            )
        snapshot = self.get_state_snapshot()
        self.broadcast(snapshot)
        return snapshot

    def process_tick_pair(
        self,
        tick_asset2: Dict[str, Any],
        tick_asset1: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Ingests a synchronized cross-asset pair tick and broadcasts update."""
        with self.lock:
            if hasattr(self.orchestrator, "on_tick_pair"):
                self.orchestrator.on_tick_pair(
                    asset1_price=tick_asset1["price"],
                    asset1_volume=tick_asset1["volume"],
                    asset2_price=tick_asset2["price"],
                    asset2_volume=tick_asset2["volume"],
                    timestamp=tick_asset1.get("timestamp", tick_asset2.get("timestamp", 0.0)),
                    simulate_leg2_failure=tick_asset1.get("simulate_leg2_failure", False) or tick_asset2.get("simulate_leg2_failure", False),
                )
            else:
                self.orchestrator.on_tick(
                    asset=tick_asset1["asset"],
                    price=tick_asset1["price"],
                    volume=tick_asset1["volume"],
                    timestamp=tick_asset1["timestamp"],
                    simulate_leg2_failure=tick_asset1.get("simulate_leg2_failure", False),
                )
                self.orchestrator.on_tick(
                    asset=tick_asset2["asset"],
                    price=tick_asset2["price"],
                    volume=tick_asset2["volume"],
                    timestamp=tick_asset2["timestamp"],
                    simulate_leg2_failure=tick_asset2.get("simulate_leg2_failure", False),
                )
        snapshot = self.get_state_snapshot()
        self.broadcast(snapshot)
        return snapshot

    def step_replay(self) -> Dict[str, Any]:
        """Steps forward 1 tick in the synthetic feed and updates state."""
        tick = self.synthetic_feed.next_tick()
        return self.process_tick(
            asset=tick["asset"],
            price=tick["price"],
            volume=tick["volume"],
            timestamp=tick["timestamp"],
            simulate_leg2_failure=tick.get("simulate_leg2_failure", False),
        )

    def _replay_worker(self, interval_sec: float, max_ticks: Optional[int]) -> None:
        """Background thread executing scheduled replay progression."""
        ticks_sent = 0
        while self.replay_active and self.is_running:
            self.step_replay()
            ticks_sent += 1
            if max_ticks is not None and ticks_sent >= max_ticks:
                self.replay_active = False
                break
            time.sleep(interval_sec)

    def start_replay(self, interval_sec: float = 0.1, max_ticks: Optional[int] = None) -> None:
        """Initiates background asynchronous synthetic tick streaming."""
        with self.lock:
            if self.replay_active:
                return
            self.replay_active = True
            self.replay_thread = threading.Thread(
                target=self._replay_worker,
                args=(interval_sec, max_ticks),
                daemon=True,
            )
            self.replay_thread.start()

    def stop_replay(self) -> None:
        """Stops background asynchronous synthetic replay."""
        self.replay_active = False
        if self.replay_thread and self.replay_thread.is_alive():
            self.replay_thread.join(timeout=1.0)
            self.replay_thread = None

    def reset(self) -> None:
        """Resets orchestrator, Kalman filter, toxicity engine, and replay generator."""
        with self.lock:
            self.stop_replay()
            self.synthetic_feed.reset()
            self.orchestrator = StatisticalArbitrageOrchestrator(config=self.config)
        snapshot = self.get_state_snapshot()
        self.broadcast(snapshot)

    def _create_handler_class(self):
        server_ref = self

        class BoundHandler(StatArbHTTPRequestHandler):
            server_instance = server_ref

        return BoundHandler

    def start(self, background: bool = True) -> int:
        """Starts HTTP server and binds to port (supports port=0 for dynamic OS allocation)."""
        self.is_running = True
        handler_cls = self._create_handler_class()
        self.httpd = ThreadingHTTPServer((self.host, self.port), handler_cls)
        self.bound_port = self.httpd.server_address[1]

        if background:
            self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.server_thread.start()
        else:
            self.httpd.serve_forever()

        return self.bound_port

    def stop(self) -> None:
        """Gracefully halts HTTP server and cleans up background threads."""
        self.is_running = False
        self.stop_replay()
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)
            self.server_thread = None
