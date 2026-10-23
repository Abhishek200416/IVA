"""Paytm Money Authentication Local Callback Server.

Implements Phase 12.1:
- Secure loopback HTTP listener bound strictly to 127.0.0.1 (default port 8765)
- Callback route: GET /paytm/callback
- Parameter validation: captures requestToken / request_token and state
- CSRF state nonce generation and verification
- Replay and duplicate submission protection
- Secret and token redaction across all logs
- Official server-to-server token exchange: POST https://developer.paytmmoney.com/accounts/v2/gettoken
- Token persistence in protected local runtime storage
- Health and readiness endpoints (/health, /ready)
- Minimal credential-safe HTML response
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set, Tuple

from .paytm_auth_state_machine import (
    PaytmAuthStateMachine,
    PaytmAuthState,
    redact_sensitive_payload,
)

logger = logging.getLogger("PaytmAuthCallbackServer")


def load_project_env(env_path: Optional[Path] = None) -> Dict[str, str]:
    """Loads environment variables from .env file into os.environ without external dependencies."""
    loaded: Dict[str, str] = {}
    if env_path is None:
        curr = Path(__file__).resolve().parent
        for _ in range(7):
            candidate = curr / ".env"
            if candidate.exists() and candidate.is_file():
                env_path = candidate
                break
            curr = curr.parent
        if env_path is None:
            cwd_cand = Path.cwd() / ".env"
            if cwd_cand.exists() and cwd_cand.is_file():
                env_path = cwd_cand

    if env_path and env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key:
                        os.environ[key] = val
                        loaded[key] = val
        except Exception as e:
            logger.warning(f"Could not load .env file from {env_path}: {e}")
    return loaded


# Eagerly load repo .env into process environment
load_project_env()


def redact_token(tok: Optional[str]) -> str:
    """Masks sensitive tokens, displaying only boundary characters."""
    if not tok:
        return "[NONE]"
    if len(tok) <= 8:
        return "********"
    return f"{tok[:4]}...{tok[-4:]}"


def redact_query_string(query_str: str) -> str:
    """Sanitizes sensitive parameters from query strings for logging."""
    if not query_str:
        return ""
    params = urllib.parse.parse_qs(query_str)
    sanitized: Dict[str, Any] = {}
    for k, v in params.items():
        if any(secret_term in k.lower() for secret_term in ("token", "secret", "key", "auth", "pwd")):
            sanitized[k] = [redact_token(item) for item in v]
        else:
            sanitized[k] = v
    return urllib.parse.urlencode(sanitized, doseq=True)


class PaytmTokenStore:
    """Secure local storage and session persistence for Paytm Money tokens."""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        if storage_path is None:
            self.storage_path = (
                Path(__file__).resolve().parents[3]
                / "runtime_storage"
                / "paytm_session.json"
            )
        else:
            self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def save_session(
        self,
        access_token: str,
        public_access_token: str = "",
        read_access_token: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Saves session tokens safely to local disk."""
        now_ist = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        )
        payload = {
            "access_token": access_token,
            "public_access_token": public_access_token,
            "read_access_token": read_access_token,
            "generated_at": now_ist.isoformat(),
            "expires_at": now_ist.replace(hour=23, minute=59, second=59).isoformat(),
            "metadata": metadata or {},
        }
        with self.lock:
            temp_file = self.storage_path.with_suffix(".tmp")
            temp_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temp_file.replace(self.storage_path)

    def load_session(self) -> Optional[Dict[str, Any]]:
        """Loads active session tokens if available and unexpired."""
        with self.lock:
            if not self.storage_path.exists():
                return None
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                expires_at_str = data.get("expires_at")
                if expires_at_str:
                    exp_dt = datetime.datetime.fromisoformat(expires_at_str)
                    now_ist = datetime.datetime.now(
                        datetime.timezone(datetime.timedelta(hours=5, minutes=30))
                    )
                    if now_ist > exp_dt:
                        logger.warning("Paytm session token has expired.")
                        return None
                return data
            except Exception as e:
                logger.error(f"Failed to read Paytm session file: {e}")
                return None

    def clear_session(self) -> None:
        """Removes local session tokens upon logout or revocation."""
        with self.lock:
            if self.storage_path.exists():
                self.storage_path.unlink()


class PaytmCallbackRequestHandler(BaseHTTPRequestHandler):
    """Handles incoming callback requests on the local loopback server."""

    server: PaytmAuthCallbackServer  # Type annotation

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress standard BaseHTTPRequestHandler logging to prevent token leakage
        pass

    def _send_html_response(
        self,
        status: HTTPStatus,
        title: str,
        headline: str,
        message: str,
        is_error: bool = False,
    ) -> None:
        accent_color = "#ef4444" if is_error else "#10b981"
        badge_text = "AUTHENTICATION FAILED" if is_error else "AUTHENTICATION VERIFIED"
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            background-color: #080c14;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
            padding: 20px;
            box-sizing: border-box;
        }}
        .card {{
            background-color: #0e1626;
            border: 1px solid #1e2c4a;
            border-radius: 12px;
            padding: 32px;
            max-width: 520px;
            width: 100%;
            text-align: center;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        }}
        .badge {{
            display: inline-block;
            background: rgba(255, 255, 255, 0.05);
            color: {accent_color};
            border: 1px solid {accent_color};
            font-size: 11px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 20px;
            margin-bottom: 16px;
            letter-spacing: 0.8px;
        }}
        h1 {{
            font-size: 20px;
            font-weight: 800;
            margin: 0 0 12px 0;
            color: #ffffff;
        }}
        p {{
            font-size: 13px;
            line-height: 1.6;
            color: #94a3b8;
            margin: 0 0 24px 0;
        }}
        .instruction {{
            background: #121c30;
            border: 1px solid #1e2c4a;
            padding: 12px;
            border-radius: 6px;
            font-size: 12px;
            color: #06b6d4;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="badge">{badge_text}</div>
        <h1>{headline}</h1>
        <p>{message}</p>
        <div class="instruction">
            You may now safely close this window and return to the <strong>AGI 1.7 Operator Console</strong>.
        </div>
    </div>
</body>
</html>"""
        content = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(content)

    def _send_json_response(self, status: HTTPStatus, payload: Dict[str, Any]) -> None:
        content = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)

        # 1. Health Endpoint
        if path == "/health":
            session = self.server.token_store.load_session()
            self._send_json_response(
                HTTPStatus.OK,
                {
                    "status": "HEALTHY",
                    "service": "PaytmAuthCallbackServer",
                    "port": self.server.server_port,
                    "session_active": bool(session and session.get("access_token")),
                    "auth_state": self.server.state_machine.to_dict(),
                    "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                },
            )
            return

        # 2. Readiness Endpoint
        if path == "/ready":
            self._send_json_response(
                HTTPStatus.OK,
                {
                    "ready": True,
                    "listening_on": f"http://{self.server.server_address[0]}:{self.server.server_port}",
                    "callback_path": self.server.callback_path,
                    "supported_paths": [self.server.callback_path, "/callback", "/paytm/callback"],
                },
            )
            return

        # 2b. Auth Status Endpoint
        if path in ("/api/auth/status", "/auth/status"):
            self._send_json_response(
                HTTPStatus.OK,
                self.server.state_machine.to_dict(),
            )
            return

        # 3. Callback Routes: registered callback_path, /callback, or /paytm/callback
        if path in (self.server.callback_path, "/callback", "/paytm/callback"):
            logger.info(f"Received callback request at path: {path}")

            # Parameter extraction: support both 'requestToken' and 'request_token'
            request_token = ""
            for param_key in ("requestToken", "request_token", "code"):
                if param_key in query_params and query_params[param_key]:
                    request_token = query_params[param_key][0]
                    break

            # State nonce extraction
            state = ""
            for state_param in ("state", "state_key"):
                if state_param in query_params and query_params[state_param]:
                    state = query_params[state_param][0]
                    break

            if not request_token:
                logger.warning("Callback received without requestToken parameter.")
                self.server.state_machine.on_callback_received("", state)
                self._send_html_response(
                    status=HTTPStatus.BAD_REQUEST,
                    title="Paytm Auth Error — Missing Token",
                    headline="Invalid Callback Payload",
                    message="The callback request was received without a valid requestToken parameter.",
                    is_error=True,
                )
                return

            # CSRF / State verification
            if self.server.enforce_state_check and state:
                if not self.server.verify_state(state):
                    logger.warning("Callback state parameter failed validation (CSRF guard).")
                    self._send_html_response(
                        status=HTTPStatus.FORBIDDEN,
                        title="Paytm Auth Error — CSRF Validation Failed",
                        headline="Security Validation Failed",
                        message="The authentication state token is invalid, expired, or was already consumed.",
                        is_error=True,
                    )
                    return

            # Replay protection: check if request token was already consumed
            if self.server.is_token_seen(request_token):
                logger.warning(
                    f"Replay detected: request token {redact_token(request_token)} already processed."
                )
                self._send_html_response(
                    status=HTTPStatus.CONFLICT,
                    title="Paytm Auth Warning — Replay Detected",
                    headline="Token Already Consumed",
                    message="This request token has already been processed and cannot be replayed.",
                    is_error=True,
                )
                return

            # Notify state machine of callback reception
            valid_cb, _ = self.server.state_machine.on_callback_received(request_token, state)
            if not valid_cb:
                self._send_html_response(
                    status=HTTPStatus.CONFLICT,
                    title="Paytm Auth Warning — Replay Detected",
                    headline="Token Already Consumed",
                    message="This request token has already been processed and cannot be replayed.",
                    is_error=True,
                )
                return

            logger.info(
                f"Processing authentic request token: {redact_token(request_token)}"
            )

            # S2S Token Exchange
            success, err_msg = self.server.handle_token_exchange(request_token, state)
            if success:
                self.server.record_token_seen(request_token)
                logger.info("Successfully completed Paytm Money S2S token exchange.")
                self._send_html_response(
                    status=HTTPStatus.OK,
                    title="Paytm Money Authentication Successful",
                    headline="Authentication Complete",
                    message="Your Paytm Money trading session has been successfully authorized and securely persisted.",
                    is_error=False,
                )
            else:
                logger.error(f"S2S token exchange failed: {err_msg}")
                self._send_html_response(
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    title="Paytm Money Token Exchange Failed",
                    headline="Token Exchange Failed",
                    message=f"Could not exchange request token with Paytm Money developer gateway: {err_msg}",
                    is_error=True,
                )
            return

        # 4. Unknown Path
        self._send_html_response(
            status=HTTPStatus.NOT_FOUND,
            title="404 Not Found",
            headline="Endpoint Not Found",
            message=f"The path '{path}' is not recognized by the Paytm Auth Callback Server.",
            is_error=True,
        )


class PaytmAuthCallbackServer(ThreadingHTTPServer):
    """Dedicated loopback HTTP server for Paytm Money OAuth/redirect callbacks."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        callback_path: str = "/paytm/callback",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        token_store: Optional[PaytmTokenStore] = None,
        enforce_state_check: bool = False,
        token_exchange_handler: Optional[
            Callable[[str, str], Tuple[bool, str]]
        ] = None,
        state_machine: Optional[PaytmAuthStateMachine] = None,
    ) -> None:
        super().__init__((host, port), PaytmCallbackRequestHandler)
        load_project_env()
        self.server_port = self.server_address[1]
        self.callback_path = callback_path
        self.api_key = api_key or os.environ.get("PAYTM_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("PAYTM_API_SECRET", "")
        self.token_store = token_store or PaytmTokenStore()
        self.enforce_state_check = enforce_state_check
        self.custom_exchange_handler = token_exchange_handler
        self.state_machine = state_machine or PaytmAuthStateMachine.get_instance(
            storage_dir=self.token_store.storage_path.parent
        )

        self.active_states: Dict[str, float] = {}  # state -> expiry_timestamp
        self.seen_tokens: Set[str] = set()
        self.state_lock = threading.Lock()
        self.daemon_thread: Optional[threading.Thread] = None

    def generate_login_url(self, api_key: Optional[str] = None) -> Tuple[str, str]:
        """Generates a secure login URL with a cryptographically secure CSRF state token."""
        key = api_key or self.api_key
        state = secrets.token_urlsafe(24)
        expires_at = time.time() + 900.0  # 15 minutes TTL

        with self.state_lock:
            # Clean expired states
            now = time.time()
            self.active_states = {
                s: exp for s, exp in self.active_states.items() if exp > now
            }
            self.active_states[state] = expires_at

        login_url = (
            f"https://login.paytmmoney.com/merchant-login?"
            f"apiKey={urllib.parse.quote(key)}&state={urllib.parse.quote(state)}"
        )
        self.state_machine.start_authorization(login_url)
        return login_url, state

    def verify_state(self, state: str) -> bool:
        """Verifies and consumes a CSRF state token."""
        with self.state_lock:
            now = time.time()
            exp = self.active_states.get(state)
            if exp and exp > now:
                del self.active_states[state]
                return True
            return False

    def is_token_seen(self, token: str) -> bool:
        """Checks if a request token has already been seen."""
        with self.state_lock:
            return token in self.seen_tokens

    def record_token_seen(self, token: str) -> None:
        """Records a request token to prevent replay attacks."""
        with self.state_lock:
            self.seen_tokens.add(token)

    def handle_token_exchange(self, request_token: str, state: str) -> Tuple[bool, str]:
        """Exchanges request token for JWT access token via S2S API."""
        if self.custom_exchange_handler:
            res, err = self.custom_exchange_handler(request_token, state)
            if res:
                self.state_machine.on_exchange_success({"state": state})
            else:
                self.state_machine.on_exchange_failure(500, err)
            return res, err

        # Refresh project env in case credentials were updated on disk while daemon is active
        load_project_env()
        api_key = self.api_key or os.environ.get("PAYTM_API_KEY", "")
        if api_key == "ROTATION_REQUIRED_SEE_PORTAL":
            api_key = os.environ.get("PAYTM_API_KEY", "")
        api_secret = self.api_secret or os.environ.get("PAYTM_API_SECRET", "")
        if api_secret == "ROTATION_REQUIRED_SEE_PORTAL":
            api_secret = os.environ.get("PAYTM_API_SECRET", "")

        if not api_key or not api_secret or api_key == "ROTATION_REQUIRED_SEE_PORTAL" or api_secret == "ROTATION_REQUIRED_SEE_PORTAL":
            err = "API Key or API Secret not configured in environment or server instance (placeholder detected)."
            logger.error(err)
            self.state_machine.on_exchange_failure(401, err)
            return False, err

        self.api_key = api_key
        self.api_secret = api_secret

        # Official S2S Token Exchange Endpoint
        endpoint = "https://developer.paytmmoney.com/accounts/v2/gettoken"
        payload = {
            "api_key": self.api_key,
            "api_secret_key": self.api_secret,
            "request_token": request_token,
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            endpoint,
            data=body_bytes,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AGI-1.7-OmegaCommand/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                status_code = resp.status
                resp_data = json.loads(resp.read().decode("utf-8"))

                if status_code in (HTTPStatus.OK, HTTPStatus.CREATED):
                    # Data payload extraction
                    data_obj = resp_data.get("data") or resp_data
                    access_token = data_obj.get("access_token", "")
                    public_token = data_obj.get("public_access_token", "")
                    read_token = data_obj.get("read_access_token", "")

                    if not access_token:
                        err_msg = "Access token missing from Paytm response payload."
                        self.state_machine.on_exchange_failure(500, err_msg)
                        return False, err_msg

                    self.token_store.save_session(
                        access_token=access_token,
                        public_access_token=public_token,
                        read_access_token=read_token,
                        metadata={
                            "state": state,
                            "request_token_redacted": redact_token(request_token),
                        },
                    )
                    self.state_machine.on_exchange_success({"state": state})
                    return True, ""
                else:
                    err_msg = f"Paytm API returned unexpected status {status_code}"
                    self.state_machine.on_exchange_failure(status_code, err_msg)
                    return False, err_msg

        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                err_msg = err_body.get("message") or err_body.get("error") or str(err_body)
            except Exception:
                err_msg = str(e)
            self.state_machine.on_exchange_failure(e.code, err_msg)
            return False, f"HTTP Error {e.code}: {err_msg}"
        except Exception as e:
            err_msg = str(e)
            self.state_machine.on_exchange_failure(500, err_msg)
            return False, f"Network or connection error during token exchange: {err_msg}"

    def start_background(self) -> None:
        """Starts the callback server on a background daemon thread."""
        self.daemon_thread = threading.Thread(
            target=self.serve_forever,
            daemon=True,
            name="PaytmAuthCallbackServerThread",
        )
        self.daemon_thread.start()
        logger.info(
            f"PaytmAuthCallbackServer started on http://{self.server_address[0]}:{self.server_port}"
        )

    def stop_server(self) -> None:
        """Stops the server gracefully and closes network sockets."""
        self.shutdown()
        self.server_close()
        logger.info("PaytmAuthCallbackServer stopped.")


def main() -> None:
    """Entry point for running the callback server from the terminal."""
    load_project_env()
    parser = argparse.ArgumentParser(description="AGI 1.7 Paytm Money Auth Callback Server")
    parser.add_argument("--host", default="127.0.0.1", help="Loopback host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    parser.add_argument("--path", default="/paytm/callback", help="Callback route path (default: /paytm/callback)")
    parser.add_argument("--api-key", default=None, help="Paytm Money API key (default: from .env)")
    parser.add_argument("--api-secret", default=None, help="Paytm Money API secret (default: from .env)")
    parser.add_argument("--enforce-state", action="store_true", default=False, help="Strictly enforce CSRF state nonce match")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    server = PaytmAuthCallbackServer(
        host=args.host,
        port=args.port,
        callback_path=args.path,
        api_key=args.api_key,
        api_secret=args.api_secret,
        enforce_state_check=args.enforce_state,
    )
    login_url, state = server.generate_login_url()

    print("=" * 72)
    print("AGI 1.7 OMEGA COMMAND — PAYTM MONEY AUTH CALLBACK SERVER")
    print("=" * 72)
    print(f"Listening on: http://{args.host}:{args.port}")
    print(f"Callback URL: http://{args.host}:{args.port}{args.path}")
    print(f"Health check: http://{args.host}:{args.port}/health")
    print(f"API Key:      {redact_token(server.api_key)}")
    print(f"API Secret:   {redact_token(server.api_secret)}")
    masked_login_url = f"https://login.paytmmoney.com/merchant-login?apiKey={redact_token(server.api_key)}&state={state}"
    print(f"Direct Login URL (Redacted for Security):\nhttps://login.paytmmoney.com/merchant-login?apiKey={redact_token(server.api_key)}")
    print(f"State Nonce Login URL (Redacted for Security):\n{masked_login_url}")
    print("=" * 72)
    print("Ready to receive authentication callbacks. Press Ctrl+C to terminate.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down callback server...")
        server.stop_server()


if __name__ == "__main__":
    main()
