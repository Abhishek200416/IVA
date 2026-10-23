"""AGI 1.7 OMEGA COMMAND — Source Registry, Data Provenance & URL Redirect Audit Service.

Phase 17.15 Core Intelligence & Security Infrastructure:
Implements Sections 3 & 4:
- Official External Source Registry (Paytm Money API, NSE India, SEBI, Income Tax Dept).
- Formal 7-Tier Data Provenance Labeling.
- Auditable Non-Sensitive URL & Redirect Tracking.
- Strict Secrets Redaction (never logging OTPs, PINs, access tokens, or session cookies).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime
from enum import Enum
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional


class DataProvenance(str, Enum):
    AUTHENTIC_FORWARD_PROVIDER_DATA = "AUTHENTIC_FORWARD_PROVIDER_DATA"
    HISTORICAL_MARKET_DATA = "HISTORICAL_MARKET_DATA"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    SYNTHETIC_TEST_DATA = "SYNTHETIC_TEST_DATA"
    MOCK_DATA = "MOCK_DATA"
    MODEL_OUTPUT = "MODEL_OUTPUT"
    UNKNOWN_PROVENANCE = "UNKNOWN_PROVENANCE"


@dataclass
class SourceRegistryEntry:
    source_name: str
    official_url: str
    purpose: str
    allowed_hostnames: List[str]
    allowed_paths: List[str]
    authentication_method: str
    required_permissions: List[str]
    rate_limits: str
    verification_status: str                   # VERIFIED, CONFIGURED_ONLY, PROHIBITED
    data_provenance_type: DataProvenance


OFFICIAL_SOURCE_REGISTRY: Dict[str, SourceRegistryEntry] = {
    "PAYTM_MONEY_OPEN_API": SourceRegistryEntry(
        source_name="Paytm Money Open API",
        official_url="https://developer.paytmmoney.com/",
        purpose="Brokerage portfolio read-only retrieval, quote streaming, and order interfaces",
        allowed_hostnames=["developer.paytmmoney.com", "login.paytmmoney.com", "trade.paytmmoney.com", "accounts.paytm.com"],
        allowed_paths=["/open-api/v1/*", "/orders/v1/*", "/data/v1/*"],
        authentication_method="OAuth 2.0 with API Key/Secret + User 2FA PIN/OTP",
        required_permissions=["read_portfolio", "read_orders", "place_orders_conditional"],
        rate_limits="10 requests/sec API, WebSocket 1 connection/account",
        verification_status="CONFIGURED_ONLY",
        data_provenance_type=DataProvenance.AUTHENTIC_FORWARD_PROVIDER_DATA,
    ),
    "NSE_INDIA": SourceRegistryEntry(
        source_name="National Stock Exchange of India",
        official_url="https://www.nseindia.com/",
        purpose="Market calendar, Bhavcopy historical data, and circulars",
        allowed_hostnames=["www.nseindia.com", "archives.nseindia.com"],
        allowed_paths=["/api/*", "/content/*"],
        authentication_method="Public Web / Session Cookies",
        required_permissions=["public_market_data"],
        rate_limits="Modest non-automated polling only",
        verification_status="VERIFIED",
        data_provenance_type=DataProvenance.HISTORICAL_MARKET_DATA,
    ),
    "INCOME_TAX_DEPARTMENT_INDIA": SourceRegistryEntry(
        source_name="Income Tax Department (Govt of India)",
        official_url="https://www.incometax.gov.in/",
        purpose="Statutory tax forms, Finance Act circulars, and tax calendar rules",
        allowed_hostnames=["www.incometax.gov.in", "incometaxindia.gov.in"],
        allowed_paths=["/iec/foportal/*"],
        authentication_method="Public Regulatory Reference",
        required_permissions=["public_legal_rules"],
        rate_limits="Static reference",
        verification_status="VERIFIED",
        data_provenance_type=DataProvenance.HISTORICAL_MARKET_DATA,
    ),
}


@dataclass
class URLAuditLogEntry:
    timestamp_ist: str
    initiated_url: str
    destination_hostname: str
    is_approved_hostname: bool
    redirect_sequence: List[str]
    callback_arrival_status: str               # RECEIVED, PENDING, FAILED, NOT_APPLICABLE
    token_exchange_status: str                 # SUCCESS, FAILED, NOT_ATTEMPTED
    read_only_verification: str                # VERIFIED, UNVERIFIED
    failure_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class URLAuditService:
    """Monitors and audits all external HTTP and browser navigation destinations."""

    def __init__(self, log_path: Optional[Path | str] = None) -> None:
        self.log_path = Path(log_path) if log_path else None
        self.audit_trail: List[URLAuditLogEntry] = []

    @staticmethod
    def redact_secrets_from_url(url: str) -> str:
        """Sanitizes sensitive tokens, auth codes, and credentials from URLs."""
        clean = re.sub(r"([?&]code=)[^&]+", r"\1[REDACTED_AUTH_CODE]", url, flags=re.IGNORECASE)
        clean = re.sub(r"([?&]access_token=)[^&]+", r"\1[REDACTED_ACCESS_TOKEN]", clean, flags=re.IGNORECASE)
        clean = re.sub(r"([?&]refresh_token=)[^&]+", r"\1[REDACTED_REFRESH_TOKEN]", clean, flags=re.IGNORECASE)
        clean = re.sub(r"([?&]password=)[^&]+", r"\1[REDACTED_PASSWORD]", clean, flags=re.IGNORECASE)
        clean = re.sub(r"([?&]otp=)[^&]+", r"\1[REDACTED_OTP]", clean, flags=re.IGNORECASE)
        clean = re.sub(r"([?&]pin=)[^&]+", r"\1[REDACTED_PIN]", clean, flags=re.IGNORECASE)
        return clean

    def audit_navigation(
        self,
        url: str,
        redirect_hops: Optional[List[str]] = None,
        callback_status: str = "NOT_APPLICABLE",
        token_exchange_status: str = "NOT_ATTEMPTED",
        read_only_verified: str = "UNVERIFIED",
    ) -> URLAuditLogEntry:
        """Evaluates whether destination matches approved source registry and logs event."""
        sanitized_url = self.redact_secrets_from_url(url)
        sanitized_hops = [self.redact_secrets_from_url(h) for h in (redirect_hops or [])]

        # Extract hostname
        hostname = ""
        m = re.match(r"^https?://([^/:]+)", url)
        if m:
            hostname = m.group(1).lower()

        # Check against source registry approved hostnames
        approved_hosts = set()
        for s in OFFICIAL_SOURCE_REGISTRY.values():
            approved_hosts.update(s.allowed_hostnames)
        approved_hosts.add("127.0.0.1")
        approved_hosts.add("localhost")

        is_approved = hostname in approved_hosts
        failure_msg = None
        if not is_approved:
            failure_msg = f"UNAPPROVED_HOSTNAME: Destination host '{hostname}' is not registered in official source catalog."

        entry = URLAuditLogEntry(
            timestamp_ist=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
            initiated_url=sanitized_url,
            destination_hostname=hostname,
            is_approved_hostname=is_approved,
            redirect_sequence=sanitized_hops,
            callback_arrival_status=callback_status,
            token_exchange_status=token_exchange_status,
            read_only_verification=read_only_verified,
            failure_reason=failure_msg,
        )

        self.audit_trail.append(entry)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")

        return entry
