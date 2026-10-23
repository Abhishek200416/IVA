"""Centralized Authentication State Machine for Paytm Money Integration.

Implements Phase 17.11:
- Explicit operator-controlled states:
    * WAITING_FOR_OPERATOR_LOGIN
    * AUTHORIZING
    * CONNECTED_READ_ONLY
    * AUTH_REQUIRED
    * AUTH_EXPIRED
    * AUTH_LOCKOUT_COOLDOWN
    * CONNECTION_ERROR
- Zero-reload and zero-spawn invariant enforcement in waiting states
- Broker lockout prevention with backoff cooldown
- Redaction of sensitive credentials, secrets, and tokens
- Thread-safe state transitions and query telemetry
"""

from __future__ import annotations

import datetime
import enum
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

logger = logging.getLogger("PaytmAuthStateMachine")


class PaytmAuthState(str, enum.Enum):
    """Authoritative states of the Paytm Money authentication lifecycle."""

    WAITING_FOR_OPERATOR_LOGIN = "WAITING_FOR_OPERATOR_LOGIN"
    AUTHORIZING = "AUTHORIZING"
    CONNECTED_READ_ONLY = "CONNECTED_READ_ONLY"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    AUTH_LOCKOUT_COOLDOWN = "AUTH_LOCKOUT_COOLDOWN"
    CONNECTION_ERROR = "CONNECTION_ERROR"


def redact_sensitive_value(val: Optional[str]) -> str:
    """Masks secret values, showing only boundary characters if long enough."""
    if not val:
        return "[NONE]"
    s = str(val).strip()
    if len(s) <= 8:
        return "********"
    return f"{s[:4]}...{s[-4:]}"


def redact_sensitive_payload(text: str) -> str:
    """Scans and redacts JWTs, tokens, passwords, and API secrets from logs/messages."""
    if not text:
        return ""
    # Redact JWT patterns (header.payload.signature)
    text = re.sub(r"eyJ[a-zA-Z0-9_\-]+\.eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+", "[REDACTED_JWT]", text)
    # Redact common key=value patterns
    text = re.sub(
        r"(api[_-]?secret|api[_-]?key|access[_-]?token|request[_-]?token|password|auth[_-]?code)=([^\s&]+)",
        r"\1=[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )
    return text


class PaytmAuthStateMachine:
    """Thread-safe lifecycle controller and policy engine for broker authentication."""

    _instance: Optional[PaytmAuthStateMachine] = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls, storage_dir: Optional[Path] = None) -> PaytmAuthStateMachine:
        """Returns the process singleton state machine instance."""
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls(storage_dir=storage_dir)
            return cls._instance

    @classmethod
    def reset_instance_for_testing(cls) -> None:
        """Resets the singleton for clean isolation in unit tests."""
        with cls._singleton_lock:
            cls._instance = None

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self.lock = threading.RLock()
        self.storage_dir = (
            storage_dir
            if storage_dir
            else Path(__file__).resolve().parents[3] / "runtime_storage"
        )
        self.session_file = self.storage_dir / "paytm_session.json"

        self._state: PaytmAuthState = PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN
        self._state_reason: str = "System initialized; awaiting operator login instruction."
        self._last_state_change: float = time.time()
        self._last_error: Optional[str] = None
        self._last_error_code: Optional[int] = None

        # Lockout and cooldown controls
        self._cooldown_until: Optional[float] = None
        self._cooldown_duration_sec: float = 0.0
        self._consecutive_failures: int = 0
        self._seen_tokens: Set[str] = set()

        # Operational telemetry counters
        self.auth_attempts: int = 0
        self.auth_successes: int = 0
        self.auth_failures: int = 0
        self.cooldown_events: int = 0

        # Invariant enforcement guards
        self.zero_reload_enforced: bool = True
        self.no_auto_retry_enforced: bool = True
        self.zero_process_spawn_enforced: bool = True

        # Check existing session file on disk
        self._evaluate_initial_session()

    def _evaluate_initial_session(self) -> None:
        """Checks if an authentic, unexpired session exists on startup."""
        if not self.session_file.exists():
            self._set_state_unlocked(
                PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN,
                "No active session on disk. System idle in operator waiting state.",
            )
            return

        try:
            import json

            data = json.loads(self.session_file.read_text(encoding="utf-8"))
            access_token = data.get("access_token")
            expires_at_str = data.get("expires_at")
            if not access_token:
                self._set_state_unlocked(
                    PaytmAuthState.AUTH_REQUIRED,
                    "Session file exists but lacks valid access_token.",
                )
                return

            if expires_at_str:
                exp_dt = datetime.datetime.fromisoformat(expires_at_str)
                now_ist = datetime.datetime.now(
                    datetime.timezone(datetime.timedelta(hours=5, minutes=30))
                )
                if now_ist > exp_dt:
                    self._set_state_unlocked(
                        PaytmAuthState.AUTH_EXPIRED,
                        "Saved session token expired. Re-authentication required.",
                    )
                    return

            self._set_state_unlocked(
                PaytmAuthState.CONNECTED_READ_ONLY,
                "Valid session loaded from disk (Read-Only market data access).",
            )
        except Exception as e:
            self._set_state_unlocked(
                PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN,
                f"Could not load session from disk ({redact_sensitive_payload(str(e))}); waiting for operator.",
            )

    def _set_state_unlocked(self, new_state: PaytmAuthState, reason: str) -> None:
        """Internal helper to mutate state and log cleanly."""
        old_state = self._state
        self._state = new_state
        self._state_reason = redact_sensitive_payload(reason)
        self._last_state_change = time.time()
        logger.info(
            f"PaytmAuthState: {old_state.value} -> {new_state.value} | Reason: {self._state_reason}"
        )

    @property
    def current_state(self) -> PaytmAuthState:
        """Returns active state, transitioning out of cooldown if expired."""
        with self.lock:
            if self._state == PaytmAuthState.AUTH_LOCKOUT_COOLDOWN:
                if self._cooldown_until and time.time() >= self._cooldown_until:
                    self._cooldown_until = None
                    self._set_state_unlocked(
                        PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN,
                        "Lockout cooldown expired. Ready for operator-initiated login.",
                    )
            return self._state

    @property
    def operator_instruction(self) -> str:
        """Returns the clear, unambiguous operator action directive."""
        with self.lock:
            state = self.current_state
            if state == PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN:
                return (
                    "Operator authentication required: Please enter your credentials and OTP / password / PIN "
                    "in the Paytm Money browser window. The AI system is in patient standby with zero page reloads, "
                    "zero automated navigation, and zero retries."
                )
            elif state == PaytmAuthState.AUTHORIZING:
                return (
                    "Operator authorization in progress: Awaiting browser callback and server-to-server token exchange. "
                    "Do not refresh or close the browser tab."
                )
            elif state == PaytmAuthState.AUTH_LOCKOUT_COOLDOWN:
                rem = max(0, int((self._cooldown_until or time.time()) - time.time()))
                return f"Broker lockout cooldown active ({rem}s remaining). Automated login attempts strictly prevented."
            elif state == PaytmAuthState.AUTH_REQUIRED:
                return "Authentication required: Please start an operator login session."
            elif state == PaytmAuthState.AUTH_EXPIRED:
                return "Session expired: Please log in again to renew read-only access."
            elif state == PaytmAuthState.CONNECTED_READ_ONLY:
                return "Session active: Connected in verified read-only paper mode."
            return "System ready."

    def record_auth_screen_detected(self, reason: str, url: str) -> None:
        """Records active OTP/PIN/login screen detection from browser observation."""
        with self.lock:
            if self._state == PaytmAuthState.CONNECTED_READ_ONLY:
                return
            redacted_url = re.sub(r"(apiKey|state)=([^&]+)", r"\1=[REDACTED]", url)
            msg = f"Operator authentication screen active ({reason}). Standby locked on: {redacted_url}"
            self._set_state_unlocked(PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN, msg)

    def start_authorization(self, login_url: Optional[str] = None) -> Tuple[bool, str]:
        """Operator or manual trigger initiates authentication."""
        with self.lock:
            state = self.current_state
            if state == PaytmAuthState.AUTH_LOCKOUT_COOLDOWN:
                rem = max(0, int((self._cooldown_until or time.time()) - time.time()))
                msg = f"Cannot start authorization: Broker lockout cooldown active ({rem}s remaining)."
                logger.warning(msg)
                return False, msg

            if state == PaytmAuthState.AUTHORIZING and (time.time() - self._last_state_change < 300.0):
                # An authorization cycle is already in progress. Protect current return URL and state.
                return True, "Authorization already in progress. Preserving current return URL and CSRF state."

            self.auth_attempts += 1
            self._set_state_unlocked(
                PaytmAuthState.AUTHORIZING,
                "Authorization initiated. Awaiting browser callback.",
            )
            return True, "State transitioned to AUTHORIZING."

    def on_callback_received(self, request_token: str, state: Optional[str] = None) -> Tuple[bool, str]:
        """Validates incoming OAuth callback payload."""
        with self.lock:
            if not request_token or not request_token.strip():
                self.auth_failures += 1
                self._last_error = "Missing or empty request_token in callback"
                self._last_error_code = 400
                self._set_state_unlocked(
                    PaytmAuthState.AUTH_REQUIRED,
                    "Invalid callback: requestToken was missing or empty.",
                )
                return False, "Missing requestToken"

            cleaned_tok = request_token.strip()
            if cleaned_tok in self._seen_tokens:
                msg = "Replay detected: requestToken was already processed."
                logger.warning(msg)
                return False, msg

            self._seen_tokens.add(cleaned_tok)
            self._set_state_unlocked(
                PaytmAuthState.AUTHORIZING,
                "Authentic requestToken received. Ready for server-to-server token exchange.",
            )
            return True, "Callback valid"

    def on_exchange_success(self, token_payload: Dict[str, Any]) -> Tuple[bool, str]:
        """S2S exchange succeeded; transition to CONNECTED_READ_ONLY."""
        with self.lock:
            self.auth_successes += 1
            self._consecutive_failures = 0
            self._cooldown_until = None
            self._cooldown_duration_sec = 0.0
            self._last_error = None
            self._last_error_code = None

            self._set_state_unlocked(
                PaytmAuthState.CONNECTED_READ_ONLY,
                "Authentication verified; connected in STRICT READ-ONLY paper mode.",
            )
            return True, "Authentication verified"

    def on_exchange_failure(self, error_code: int, error_message: str) -> Tuple[PaytmAuthState, str]:
        """Handles exchange failures, categorizing rate-limits, auth errors, and network issues."""
        with self.lock:
            self.auth_failures += 1
            self._consecutive_failures += 1
            redacted_err = redact_sensitive_payload(error_message)
            self._last_error = redacted_err
            self._last_error_code = error_code

            err_lower = redacted_err.lower()
            # 1. Rate Limit / Lockout Detection
            if error_code == 429 or any(
                w in err_lower for w in ("rate limit", "too many requests", "lockout", "locked", "slow down", "cooldown")
            ):
                # Exponential backoff: 60s, 120s, 240s, capped at 300s
                backoff = min(300.0, 60.0 * (2 ** (min(self._consecutive_failures, 4) - 1)))
                self._cooldown_until = time.time() + backoff
                self._cooldown_duration_sec = backoff
                self.cooldown_events += 1
                reason = (
                    f"Broker rate limit or lockout triggered (HTTP {error_code}). "
                    f"Entering mandatory cooldown for {int(backoff)}s. Automated retries strictly prohibited."
                )
                self._set_state_unlocked(PaytmAuthState.AUTH_LOCKOUT_COOLDOWN, reason)
                return PaytmAuthState.AUTH_LOCKOUT_COOLDOWN, reason

            # 2. Authentication Invalid / Forbidden
            elif error_code in (401, 403) or "unauthorized" in err_lower or "forbidden" in err_lower:
                reason = f"Authentication rejected by broker (HTTP {error_code}): {redacted_err}"
                self._set_state_unlocked(PaytmAuthState.AUTH_REQUIRED, reason)
                return PaytmAuthState.AUTH_REQUIRED, reason

            # 3. Connection / Network Timeout
            elif (
                error_code in (502, 503, 504)
                or "timeout" in err_lower
                or "connection" in err_lower
                or "socket" in err_lower
            ):
                reason = f"Network or gateway connectivity error (HTTP {error_code}): {redacted_err}"
                self._set_state_unlocked(PaytmAuthState.CONNECTION_ERROR, reason)
                return PaytmAuthState.CONNECTION_ERROR, reason

            # 4. General Auth Failure
            else:
                reason = f"Token exchange failed (HTTP {error_code}): {redacted_err}"
                self._set_state_unlocked(PaytmAuthState.AUTH_REQUIRED, reason)
                return PaytmAuthState.AUTH_REQUIRED, reason

    def on_token_expired(self, reason: str = "Session token expired.") -> None:
        """Transitions state to AUTH_EXPIRED upon detecting expired JWT."""
        with self.lock:
            self._set_state_unlocked(PaytmAuthState.AUTH_EXPIRED, reason)

    def reset_to_waiting(self, reason: str = "Reset to operator waiting state.") -> None:
        """Explicit operator reset to calm waiting state."""
        with self.lock:
            self._consecutive_failures = 0
            self._cooldown_until = None
            self._set_state_unlocked(PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN, reason)

    def is_token_seen(self, token: str) -> bool:
        """Checks replay set."""
        with self.lock:
            return token in self._seen_tokens

    def record_token_seen(self, token: str) -> None:
        """Adds token to replay set."""
        with self.lock:
            self._seen_tokens.add(token)

    def to_dict(self) -> Dict[str, Any]:
        """Produces machine-readable status payload with zero credentials."""
        with self.lock:
            state = self.current_state
            cooldown_rem = 0
            if self._cooldown_until and self._cooldown_until > time.time():
                cooldown_rem = int(self._cooldown_until - time.time())

            can_auto_retry = False  # Invariant: automated retries are NEVER permitted
            can_reload_page = False  # Invariant: page reload loops are strictly prohibited
            can_spawn_processes = False  # Invariant: background processes are not spawned in unauth states

            return {
                "auth_state": state.value,
                "is_authenticated": state == PaytmAuthState.CONNECTED_READ_ONLY,
                "is_waiting_for_operator": state == PaytmAuthState.WAITING_FOR_OPERATOR_LOGIN,
                "is_cooldown_active": state == PaytmAuthState.AUTH_LOCKOUT_COOLDOWN,
                "cooldown_remaining_sec": cooldown_rem,
                "cooldown_total_duration_sec": self._cooldown_duration_sec,
                "state_reason": self._state_reason,
                "operator_instruction": self.operator_instruction,
                "last_error": self._last_error,
                "last_error_code": self._last_error_code,
                "consecutive_failures": self._consecutive_failures,
                "can_reload_page": can_reload_page,
                "zero_reload_enforced": self.zero_reload_enforced,
                "can_spawn_processes": can_spawn_processes,
                "zero_process_spawn_enforced": self.zero_process_spawn_enforced,
                "can_auto_submit": False,
                "can_auto_retry": can_auto_retry,
                "no_auto_retry_enforced": self.no_auto_retry_enforced,
                "last_state_change_utc": datetime.datetime.fromtimestamp(
                    self._last_state_change, tz=datetime.timezone.utc
                ).isoformat(),
                "telemetry": {
                    "attempts": self.auth_attempts,
                    "successes": self.auth_successes,
                    "failures": self.auth_failures,
                    "cooldown_events": self.cooldown_events,
                },
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
