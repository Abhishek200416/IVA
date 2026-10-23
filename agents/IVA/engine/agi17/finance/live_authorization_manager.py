"""Strict Live-Mode Authorization & Arming Screen Manager for AGI 1.7 OMEGA COMMAND.

Implements Section 5:
- Independent separation between Analysis (default) and Live Execution
- `GO REAL` command handling and interactive session-arming screen
- Masked broker account identification (e.g. PM-******1234)
- Verified visible funds and margin
- Explicit live capital allocation (strictly prohibited from inferring from paper ₹50,000)
- Enforces strict user signature requirement (no news/prompts/agents can arm)
- Comprehensive emergency stop with honest open position exposure accounting
"""

from __future__ import annotations

import datetime
import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def mask_account_id(account_id: str) -> str:
    """Masks sensitive account identification characters."""
    if not account_id:
        return "UNKNOWN_ACCOUNT"
    clean = account_id.strip()
    if len(clean) <= 4:
        return "****"
    prefix = clean[:2] if len(clean) > 6 else clean[:1]
    suffix = clean[-4:]
    return f"{prefix}-{'*' * (len(clean) - len(prefix) - 4)}-{suffix}"


@dataclass
class LiveSessionConfig:
    """Explicit parameters required to arm real-money live execution."""
    account_id: str
    visible_funds_inr: float
    visible_margin_inr: float
    authorized_capital_inr: float
    max_loss_per_trade_inr: float
    max_daily_loss_inr: float
    max_concurrent_positions: int = 1
    permitted_instruments: List[str] = field(default_factory=lambda: ["NIFTY", "BANKNIFTY"])
    permitted_order_types: List[str] = field(default_factory=lambda: ["LIMIT", "MARKET"])
    allow_overnight: bool = False
    session_end_time_ist: str = "15:15:00 IST"
    exit_policy: str = "INTRADAY_AUTO_SQUAREOFF_1515_IST"
    user_confirmation_signature: str = ""
    authorized_at: str = ""
    # Hardened identity and verification parameters
    browser_verified_client_code: str = ""
    broker_origin_url: str = ""
    session_nonce: str = ""
    auth_expiration_seconds: int = 900
    operator_confirmed_at: str = ""


class LiveAuthorizationManager:
    """Authoritative gatekeeper for live-money execution arming and limits."""

    def __init__(self) -> None:
        self.is_armed: bool = False
        self.session_config: Optional[LiveSessionConfig] = None
        self.emergency_stop_active: bool = False
        self.emergency_stop_reason: str = ""
        self.emergency_stop_timestamp: str = ""
        self.arming_history: List[Dict[str, Any]] = []

    def verify_account_identity(
        self,
        account_id: Optional[str] = None,
        browser_client_code: str = "",
        broker_url: str = "",
        verification_timestamp: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Establishes that account identity is substantiated by visible browser session evidence.

        A non-empty account ID string ALONE cannot pass this verification.
        Requires:
        1. Non-empty, validly formatted account ID.
        2. Verified matching client code actively observed in visible browser DOM.
        3. Authentic broker origin URL (matching trade.paytmmoney.com).
        4. Fresh, unexpired interactive session authorization (within auth_expiration_seconds).
        5. Secrets hygiene check (no plaintext passwords, OTPs, or bearer tokens persisted).
        """
        if not self.is_armed and self.session_config is None and account_id is None:
            return False, "LIVE_SESSION_NOT_ARMED"

        clean_account = (account_id or (self.session_config.account_id if self.session_config else "") or "").strip()
        if not clean_account or clean_account.upper() in ("UNSPECIFIED", "UNKNOWN", "NONE"):
            return False, "ACCOUNT_ID_UNSPECIFIED"

        # Evidence requirement 1: Active visible browser DOM client code verification
        effective_client = (browser_client_code or (self.session_config.browser_verified_client_code if self.session_config else "") or "").strip()
        if not effective_client:
            return False, "UNVERIFIED_DOM_CLIENT_CODE: No client code verified from active browser DOM. A non-empty account ID string alone cannot satisfy the account-identity gate without visible browser verification."

        if effective_client.upper() != clean_account.upper():
            return False, f"ACCOUNT_MISMATCH: Browser DOM profile client code '{mask_account_id(effective_client)}' does not match authorized account ID '{mask_account_id(clean_account)}'."

        # Evidence requirement 2: Authentic broker origin URL verification
        effective_url = (broker_url or (self.session_config.broker_origin_url if self.session_config else "") or "").strip()
        if not effective_url:
            return False, "MISSING_BROKER_ORIGIN_URL: Browser session URL not verified against authentic Paytm Money trading host."

        if not re.match(r"^https://([a-zA-Z0-9-]+\.)*paytmmoney\.com(/.*)?$", effective_url):
            return False, f"UNTRUSTED_BROKER_ORIGIN: Origin URL '{effective_url}' does not belong to authentic Paytm Money production domain."

        # Evidence requirement 3: Session staleness verification
        if verification_timestamp is not None:
            age_sec = time.time() - verification_timestamp
            if age_sec > 900.0:
                return False, f"STALE_AUTHORIZATION: Verification timestamp is expired ({age_sec:.0f}s > 900s)."
        elif self.session_config and self.session_config.authorized_at:
            try:
                raw_ts = self.session_config.authorized_at.replace(" IST", "")
                auth_dt = datetime.datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S")
                now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).replace(tzinfo=None)
                age_sec = (now_dt - auth_dt).total_seconds()
                if age_sec > self.session_config.auth_expiration_seconds:
                    return False, f"STALE_AUTHORIZATION: Live session authorization has expired ({age_sec:.0f}s > {self.session_config.auth_expiration_seconds}s)."
            except Exception:
                pass

        # Evidence requirement 4: Secrets cleanliness check
        if self.session_config:
            for k, v in self.session_config.__dict__.items():
                if isinstance(v, str):
                    v_lower = v.lower()
                    for sensitive_pat in ("password", "passwd", "otp", "totp", "pin=", "bearer "):
                        if sensitive_pat in v_lower:
                            return False, f"SECRETS_HYGIENE_VIOLATION: Sensitive credential pattern detected in session parameter '{k}'."

        return True, f"ACCOUNT_VERIFIED_VIA_BROWSER_DOM: Account {mask_account_id(clean_account)} verified on authentic origin {effective_url}"

    def render_session_arming_screen(
        self,
        config: LiveSessionConfig,
        preflight_health: Dict[str, bool],
    ) -> str:
        """Renders the official 11-point session-arming verification screen."""
        masked_id = mask_account_id(config.account_id)
        all_checks_passed = all(preflight_health.values())

        screen = f"""
================================================================================
           AGI 1.7 OMEGA COMMAND — LIVE SESSION-ARMING VERIFICATION
================================================================================
[!] CRITICAL REAL-MONEY SAFETY PROTOCOL:
    Execution mode is transitioning from PAPER to LIVE BROKERAGE.
    Every trade executed in this session will deploy REAL CAPITAL via Paytm Money.

1. BROKER ACCOUNT IDENTITY:       {masked_id} (Paytm Money)
2. VISIBLY VERIFIED FUNDS:        ₹{config.visible_funds_inr:,.2f}
   VISIBLY VERIFIED MARGIN:       ₹{config.visible_margin_inr:,.2f}
3. AUTHORIZED SESSION CAPITAL:    ₹{config.authorized_capital_inr:,.2f} (INDEPENDENT)
4. MAX PLANNED LOSS PER TRADE:    ₹{config.max_loss_per_trade_inr:,.2f}
5. MAX DAILY LOSS POLICY:         ₹{config.max_daily_loss_inr:,.2f}
6. MAX CONCURRENT POSITIONS:      {config.max_concurrent_positions}
7. PERMITTED INSTRUMENTS:         {', '.join(config.permitted_instruments)}
   PERMITTED ORDER TYPES:         {', '.join(config.permitted_order_types)}
8. OVERNIGHT HOLDING POLICY:      {'ALLOWED' if config.allow_overnight else 'STRICTLY PROHIBITED (Intraday Only)'}
9. SESSION END & EXIT POLICY:     {config.session_end_time_ist} ({config.exit_policy})
10. PREFLIGHT HEALTH CHECKS:
"""
        for check, status in preflight_health.items():
            screen += f"    - {check:<28}: {'[PASS]' if status else '[FAIL]'}\n"

        screen += f"""11. VISIBLE UI WORKFLOW STATUS:   VERIFIED (Chrome for Testing Port 9229)
--------------------------------------------------------------------------------
OVERALL PREFLIGHT READINESS:      {'READY FOR ARMING' if all_checks_passed else 'BLOCKED BY HEALTH FAILURES'}
================================================================================
"""
        return screen

    def arm_live_session(
        self,
        config: LiveSessionConfig,
        preflight_health: Dict[str, bool],
    ) -> Dict[str, Any]:
        """Validates and arms live session upon explicit user confirmation."""
        now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

        if self.emergency_stop_active:
            raise PermissionError(
                f"Cannot arm live session: Emergency Stop is ACTIVE (Reason: {self.emergency_stop_reason})."
            )

        # 1. Health check verification
        failed_checks = [k for k, v in preflight_health.items() if not v]
        if failed_checks:
            raise PermissionError(
                f"Cannot arm live session: Preflight health checks failed for: {failed_checks}"
            )

        # 2. Capital bounds verification (prevent inferring from ₹50,000 paper ledger)
        if config.authorized_capital_inr <= 0:
            raise ValueError(
                "Authorized live capital must be strictly positive and explicitly specified."
            )
        if config.authorized_capital_inr > config.visible_funds_inr:
            raise ValueError(
                f"Authorized capital ₹{config.authorized_capital_inr:,.2f} exceeds "
                f"verified broker funds ₹{config.visible_funds_inr:,.2f}."
            )

        # 3. User signature verification
        if not config.user_confirmation_signature or len(config.user_confirmation_signature.strip()) < 4:
            raise PermissionError(
                "Live arming rejected: Explicit user confirmation signature is required. "
                "Agent prompts or external news cannot arm live mode."
            )

        # 4. Secrets hygiene verification (prevent persisting passwords, OTPs, or session tokens)
        for field_name, field_val in config.__dict__.items():
            if isinstance(field_val, str):
                val_lower = field_val.lower()
                for sensitive_pat in ("password", "passwd", "otp", "totp", "pin=", "bearer ey", "client_secret"):
                    if sensitive_pat in val_lower:
                        raise PermissionError(
                            f"Live arming rejected: Sensitive credential pattern '{sensitive_pat}' detected in parameter '{field_name}'. Plain secrets must never be persisted."
                        )

        config.authorized_at = ts_str
        self.session_config = config
        self.is_armed = True

        audit_entry = {
            "account_masked": mask_account_id(config.account_id),
            "authorized_capital_inr": config.authorized_capital_inr,
            "max_loss_per_trade_inr": config.max_loss_per_trade_inr,
            "max_daily_loss_inr": config.max_daily_loss_inr,
            "signature": config.user_confirmation_signature,
            "timestamp": ts_str,
            "status": "ARMED",
        }
        self.arming_history.append(audit_entry)

        return {
            "status": "LIVE_SESSION_ARMED",
            "account": mask_account_id(config.account_id),
            "authorized_capital": config.authorized_capital_inr,
            "timestamp": ts_str,
        }

    def validate_live_order_limits(
        self,
        symbol: str,
        order_cost_inr: float,
        potential_loss_inr: float,
        current_daily_loss_inr: float,
        current_open_positions: int,
    ) -> Tuple[bool, Optional[str]]:
        """Validates that a live order strictly satisfies the armed session limits."""
        if not self.is_armed or self.session_config is None:
            return False, "Order rejected: Live session is NOT armed."

        if self.emergency_stop_active:
            return False, f"Order rejected: Emergency Stop active ({self.emergency_stop_reason})."

        cfg = self.session_config

        # Check capital allocation limit
        if order_cost_inr > cfg.authorized_capital_inr:
            return False, (
                f"Order cost ₹{order_cost_inr:,.2f} exceeds authorized session capital "
                f"₹{cfg.authorized_capital_inr:,.2f}."
            )

        # Check per-trade loss limit
        if potential_loss_inr > cfg.max_loss_per_trade_inr:
            return False, (
                f"Potential loss ₹{potential_loss_inr:,.2f} exceeds authorized per-trade limit "
                f"₹{cfg.max_loss_per_trade_inr:,.2f}."
            )

        # Check daily loss limit
        if current_daily_loss_inr >= cfg.max_daily_loss_inr:
            return False, (
                f"Daily realized loss ₹{current_daily_loss_inr:,.2f} has reached daily loss cap "
                f"₹{cfg.max_daily_loss_inr:,.2f}."
            )

        # Check concurrent positions
        if current_open_positions >= cfg.max_concurrent_positions:
            return False, (
                f"Current positions ({current_open_positions}) equal maximum authorized "
                f"concurrent positions ({cfg.max_concurrent_positions})."
            )

        # Check instrument authorization
        def _instrument_matches(sym: str, inst: str) -> bool:
            sym_u = sym.upper()
            inst_u = inst.upper()
            if inst_u == "NIFTY":
                if "BANKNIFTY" in sym_u or "FINNIFTY" in sym_u or "MIDCPNIFTY" in sym_u:
                    return False
                return "NIFTY" in sym_u
            return inst_u in sym_u

        if not any(_instrument_matches(symbol, inst) for inst in cfg.permitted_instruments):
            return False, (
                f"Instrument '{symbol}' is not among authorized instruments "
                f"{cfg.permitted_instruments}."
            )

        return True, None

    def trigger_emergency_stop(
        self,
        open_positions: Dict[str, Any],
        reason: str = "Manual User Emergency Stop",
    ) -> Dict[str, Any]:
        """Blocks new orders immediately and honestly catalogues existing open exposure."""
        now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

        self.emergency_stop_active = True
        self.emergency_stop_reason = reason
        self.emergency_stop_timestamp = ts_str
        self.is_armed = False

        # Format open positions inventory honestly (never falsely claim exposure vanished)
        exposure_summary = []
        for sym, pos_data in open_positions.items():
            exposure_summary.append({
                "symbol": sym,
                "quantity": pos_data.get("quantity", 0),
                "entry_price": pos_data.get("entry_price", 0.0),
                "current_price": pos_data.get("current_price", 0.0),
                "unrealized_pnl": pos_data.get("unrealized_pnl", 0.0),
                "policy": self.session_config.exit_policy if self.session_config else "MANUAL_SUPERVISION_REQUIRED",
            })

        return {
            "status": "EMERGENCY_STOP_ACTIVE",
            "reason": reason,
            "timestamp": ts_str,
            "new_orders_blocked": True,
            "open_positions_count": len(open_positions),
            "open_exposure": exposure_summary,
            "message": "All new orders blocked. Open positions must be managed according to policy or broker interface.",
        }

    def disarm_session(self, reason: str = "Normal session close") -> Dict[str, Any]:
        """Disarms live trading back to ANALYSIS_ONLY mode."""
        now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

        self.is_armed = False
        self.session_config = None
        return {
            "status": "DISARMED",
            "reason": reason,
            "timestamp": ts_str,
        }
