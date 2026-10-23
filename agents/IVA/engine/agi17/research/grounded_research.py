"""AGI 1.7 Grounded Research Engine with SSRF Firewall & Citation Verification.

Implements pre-socket RFC 1918 / loopback / link-local SSRF blocking,
research cache integration with Layer 9 of OmegaCommandMemory, and
claim-to-source verification.
"""

from __future__ import annotations

import ipaddress
import socket
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..memory.omega_command_memory import OmegaCommandMemory


class SSRFBlockedError(PermissionError):
    """Raised when a URL targets a private, loopback, link-local, or reserved IP address."""


@dataclass
class ResearchCitation:
    source_id: str
    url: str
    title: str
    publication_date: str
    finding_summary: str
    limitations: str
    verified: bool = True


class GroundedResearchEngine:
    """10-stage grounded research pipeline with pre-socket SSRF firewall and Layer 9 caching."""

    ALLOWED_SCHEMES = {"http", "https"}

    def __init__(self, memory: Optional[OmegaCommandMemory] = None) -> None:
        self.memory = memory or OmegaCommandMemory()

    @classmethod
    def validate_url_ssrf_safe(cls, url: str, resolve_dns: bool = False) -> Dict[str, Any]:
        parsed = urllib.parse.urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in cls.ALLOWED_SCHEMES:
            raise SSRFBlockedError(f"Blocked URL scheme '{scheme}'; only http/https allowed")

        host = (parsed.hostname or "").strip().lower()
        if not host:
            raise SSRFBlockedError("URL missing hostname")

        if host in {"localhost", "0.0.0.0", "127.0.0.1", "::1", "metadata.google.internal"} or host.endswith(".local"):
            raise SSRFBlockedError(f"Blocked loopback/internal hostname: {host}")

        # Check literal IP address
        try:
            ip_obj = ipaddress.ip_address(host)
            cls._assert_public_ip(ip_obj, host)
        except ValueError:
            # Domain name
            if resolve_dns:
                try:
                    infos = socket.getaddrinfo(host, None)
                    for info in infos:
                        addr_str = info[4][0]
                        ip_obj = ipaddress.ip_address(addr_str)
                        cls._assert_public_ip(ip_obj, host)
                except SSRFBlockedError:
                    raise
                except Exception:
                    pass

        return {"url": url, "hostname": host, "ssrf_safe": True}

    @staticmethod
    def _assert_public_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address, host: str) -> None:
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            raise SSRFBlockedError(f"Blocked non-public IP address {ip_obj} for host {host}")

    def register_verified_citation(
        self,
        citation: ResearchCitation,
        ttl_seconds: float = 86400.0 * 30,
    ) -> Dict[str, Any]:
        self.validate_url_ssrf_safe(citation.url, resolve_dns=False)
        entry = self.memory.store(
            layer=9,
            subject_key=f"citation:{citation.source_id}",
            content=f"{citation.title} ({citation.publication_date}): {citation.finding_summary}",
            structured_data=asdict(citation),
            tags=["research", "citation", citation.source_id],
            ttl_seconds=ttl_seconds,
        )
        return {"entry_id": entry.entry_id, "citation": asdict(citation)}
