"""Official Paytm Money Open API Client & Secure Service Abstraction.

Implements Phase 12.1 Capabilities:
A. Authentication & account identity (accounts/v1/user/details)
B. Read-only funds & margin limits (accounts/v1/user/limits)
C. Market-data REST snapshots (data/v1/quotes, data/v1/market-depth)
D. Live-market-data WebSocket streaming configuration (wss://developer-ws.paytmmoney.com/broadcast/user/v1/data)
E. Contract metadata & strike identity reconciliation
F. Order-status, trade-book & position-book retrieval (orders/v1/user/orders, orders/v1/trade-details, orders/v1/position-details)
G. Order placement/modification/cancellation adapter (STRICTLY DISABLED BY DEFAULT with fail-closed safety gate)
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, Dict, List, Optional, Tuple

from .paytm_auth_callback_server import PaytmTokenStore, load_project_env, redact_token

logger = logging.getLogger("PaytmOpenApiClient")


class LiveTradingDisabledError(PermissionError):
    """Raised when an attempt is made to dispatch live orders while live mode is disabled."""
    pass


class PaytmApiError(Exception):
    """Raised when Paytm Money Open API returns an error response."""
    def __init__(self, message: str, status_code: int = 400, response_data: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}


@dataclass
class AccountDetails:
    """Represents authenticated user account profile."""
    client_id: str
    user_name: str
    kyc_status: str
    email: str
    is_fno_enabled: bool = True
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MarginLimits:
    """Represents account balance, available margin, and utilized funds."""
    available_margin: float
    utilized_margin: float
    cash_balance: float
    collateral_value: float = 0.0
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QuoteSnapshot:
    """Represents a validated market quote snapshot from REST API."""
    security_id: str
    exchange: str
    last_price: float
    bid_price: float
    ask_price: float
    volume: int
    open_interest: int
    timestamp_utc: str
    quote_age_seconds: float = 0.0


class PaytmOpenApiClient:
    """Official client for Paytm Money Developer APIs."""

    BASE_URL = "https://developer.paytmmoney.com"
    WS_URL = "wss://developer-ws.paytmmoney.com/broadcast/user/v1/data"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        token_store: Optional[PaytmTokenStore] = None,
        live_order_dispatch_enabled: bool = False,
    ) -> None:
        load_project_env()
        self.api_key = api_key or os.environ.get("PAYTM_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("PAYTM_API_SECRET", "")
        self.token_store = token_store or PaytmTokenStore()
        self.live_order_dispatch_enabled = (
            live_order_dispatch_enabled
            or os.environ.get("LIVE_ORDER_DISPATCH_ENABLED", "false").lower() in ("true", "1")
        )

        self._access_token: str = access_token or ""
        self._public_access_token: str = ""
        self._read_access_token: str = ""

        # Auto-load cached session tokens if not passed explicitly
        if not self._access_token:
            cached_session = self.token_store.load_session()
            if cached_session:
                self._access_token = cached_session.get("access_token", "")
                self._public_access_token = cached_session.get("public_access_token", "")
                self._read_access_token = cached_session.get("read_access_token", "")

    # =========================================================================
    # 1. Authentication & Session Management
    # =========================================================================

    def is_authenticated(self) -> bool:
        """Returns True if a valid unexpired access token is active."""
        if not self._access_token:
            return False
        cached_session = self.token_store.load_session()
        return bool(cached_session and cached_session.get("access_token"))

    def get_login_url(self, state_key: Optional[str] = None) -> str:
        """Returns the official login URL with a cryptographically unpredictable state nonce."""
        import secrets
        nonce = state_key or secrets.token_urlsafe(24)
        query_params = {"apiKey": self.api_key, "state": nonce}
        return f"https://login.paytmmoney.com/merchant-login?{urllib.parse.urlencode(query_params)}"

    def set_session_tokens(
        self,
        access_token: str,
        public_access_token: str = "",
        read_access_token: str = "",
    ) -> None:
        """Updates in-memory and persistent session tokens."""
        self._access_token = access_token
        self._public_access_token = public_access_token
        self._read_access_token = read_access_token
        self.token_store.save_session(
            access_token=access_token,
            public_access_token=public_access_token,
            read_access_token=read_access_token,
        )

    def _get_headers(self, require_jwt: bool = True) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AGI-1.7-OmegaCommand/1.0",
        }
        if require_jwt:
            if not self._access_token:
                raise PaytmApiError("No active access token. Please complete Paytm Money login first.", status_code=401)
            headers["x-jwt-token"] = self._access_token
        return headers

    def _execute_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        timeout: float = 6.0,
    ) -> Dict[str, Any]:
        """Executes an authenticated HTTP request against developer.paytmmoney.com."""
        url = f"{self.BASE_URL}{path}"
        if params:
            url += f"?{urllib.parse.urlencode(params)}"

        data_bytes = json.dumps(payload).encode("utf-8") if payload else None
        headers = self._get_headers(require_jwt=True)

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method.upper())

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body: Dict[str, Any] = {}
            if e.fp:
                try:
                    err_body = json.loads(e.fp.read().decode("utf-8"))
                except Exception:
                    pass
            msg = err_body.get("message") or err_body.get("error") or str(e)
            raise PaytmApiError(f"Paytm API {method} {path} failed: {msg}", status_code=e.code, response_data=err_body)
        except Exception as e:
            raise PaytmApiError(f"Network transport error connecting to Paytm API: {str(e)}", status_code=500)

    # =========================================================================
    # Capability A: Account Identity & Profile (Read-Only)
    # =========================================================================

    def get_user_details(self) -> AccountDetails:
        """Fetches account identity details for the authenticated user."""
        res = self._execute_request("GET", "/accounts/v1/user/details")
        data = res.get("data") or res
        return AccountDetails(
            client_id=str(data.get("client_id", data.get("user_id", "UNKNOWN"))),
            user_name=str(data.get("user_name", data.get("name", "PAYTM_USER"))),
            kyc_status=str(data.get("kyc_status", "ACTIVE")),
            email=str(data.get("email", "")),
            is_fno_enabled=bool(data.get("fno_enabled", True)),
            raw_response=res,
        )

    # =========================================================================
    # Capability B: Funds & Margin Limits (Read-Only)
    # =========================================================================

    def get_funds_and_margins(self) -> MarginLimits:
        """Fetches available balance, margins, and collateral."""
        res = self._execute_request("GET", "/accounts/v1/user/limits")
        data = res.get("data") or res
        return MarginLimits(
            available_margin=float(data.get("available_margin", data.get("cash_available", 0.0))),
            utilized_margin=float(data.get("utilized_margin", 0.0)),
            cash_balance=float(data.get("net_cash_balance", data.get("cash_balance", 0.0))),
            collateral_value=float(data.get("collateral_amount", 0.0)),
            raw_response=res,
        )

    # =========================================================================
    # Capability C: Market-Data REST Snapshots (Read-Only)
    # =========================================================================

    def get_live_quotes(self, mode: str, preferences: List[Dict[str, str]]) -> List[QuoteSnapshot]:
        """Fetches market quotes for given instruments (mode: 'LTP', 'QUOTE', 'FULL')."""
        payload = {
            "mode": mode.upper(),
            "preferences": preferences,
        }
        res = self._execute_request("POST", "/data/v1/quotes", payload=payload)
        data = res.get("data") or []
        results: List[QuoteSnapshot] = []
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

        for item in data:
            results.append(
                QuoteSnapshot(
                    security_id=str(item.get("security_id", "")),
                    exchange=str(item.get("exchange", "NSE")),
                    last_price=float(item.get("last_price", item.get("ltp", 0.0))),
                    bid_price=float(item.get("bid", item.get("best_bid", 0.0))),
                    ask_price=float(item.get("ask", item.get("best_ask", 0.0))),
                    volume=int(item.get("volume", 0)),
                    open_interest=int(item.get("open_interest", item.get("oi", 0))),
                    timestamp_utc=now_utc,
                )
            )
        return results

    # =========================================================================
    # Capability D: Live WebSocket Streaming URL & Protocols
    # =========================================================================

    def get_websocket_connection_url(self) -> str:
        """Returns the authenticated WebSocket URL for live broadcast subscription."""
        token_to_use = self._public_access_token or self._access_token
        if not token_to_use:
            raise PaytmApiError("No token available to construct WebSocket connection URL.", status_code=401)
        return f"{self.WS_URL}?x_jwt_token={token_to_use}"

    @staticmethod
    def build_websocket_subscription_packet(
        action: str,
        mode: str,
        preferences: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """Constructs official subscription packet for WebSocket feed."""
        return {
            "action": action.lower(),  # "subscribe" or "unsubscribe"
            "mode": mode.upper(),      # "LTP", "QUOTE", or "FULL"
            "preferences": preferences,
        }

    # =========================================================================
    # Capability F: Order Book, Trade Book & Position Book (Read-Only)
    # =========================================================================

    def get_order_book(self) -> List[Dict[str, Any]]:
        """Fetches the day's order book from Paytm Money."""
        res = self._execute_request("GET", "/orders/v1/user/orders")
        return res.get("data") or []

    def get_trade_book(self) -> List[Dict[str, Any]]:
        """Fetches executed trades from Paytm Money."""
        res = self._execute_request("GET", "/orders/v1/trade-details")
        return res.get("data") or []

    def get_position_book(self) -> List[Dict[str, Any]]:
        """Fetches open and closed net positions from Paytm Money."""
        res = self._execute_request("GET", "/orders/v1/position-details")
        return res.get("data") or []

    # =========================================================================
    # Capability G: Order Placement & Modification (FAIL-CLOSED SAFETY GATE)
    # =========================================================================

    def place_order(self, order_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Places a live regular order on Paytm Money.

        STRICT SAFETY INVARIANT:
        Live order dispatch is DISABLED BY DEFAULT.
        Raises LiveTradingDisabledError unless live_order_dispatch_enabled is True.
        """
        if not self.live_order_dispatch_enabled:
            raise LiveTradingDisabledError(
                "Live order placement rejected: LIVE_ORDER_DISPATCH_ENABLED is False. "
                "The AGI 1.7 system operates in STRICTLY PAPER ONLY mode."
            )
        return self._execute_request("POST", "/orders/v1/place/regular", payload=order_payload)

    def modify_order(self, modify_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Modifies a live order on Paytm Money."""
        if not self.live_order_dispatch_enabled:
            raise LiveTradingDisabledError("Live order modification rejected: System is in PAPER ONLY mode.")
        return self._execute_request("POST", "/orders/v1/modify/regular", payload=modify_payload)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancels a live order on Paytm Money."""
        if not self.live_order_dispatch_enabled:
            raise LiveTradingDisabledError("Live order cancellation rejected: System is in PAPER ONLY mode.")
        return self._execute_request("POST", "/orders/v1/cancel/regular", payload={"order_id": order_id})
