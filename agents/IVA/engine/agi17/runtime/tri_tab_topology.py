"""AGI 1.7 OMEGA COMMAND — Three-Tab Chrome Topology & Target Registry (Phase 17.19).

Manages the target browser topology across exactly three designated roles:
1. NIFTY_CHAIN: Official Paytm Money Nifty Option Chain
2. BANKNIFTY_CHAIN: Official Paytm Money BankNifty Option Chain
3. AGI_DASHBOARD: Local Standalone Dashboard (http://127.0.0.1:8088/)

Enforces:
- Exactly one tab per designated role.
- Target reuse without repeated tab opening.
- Explicit target identity matching (not reliant on index or title alone).
- Controlled role recovery if a tab is closed or navigated away.
"""

import enum
import json
import logging
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("TriTabTopology")


class TabRole(str, enum.Enum):
    NIFTY_CHAIN = "NIFTY_CHAIN"
    BANKNIFTY_CHAIN = "BANKNIFTY_CHAIN"
    AGI_DASHBOARD = "AGI_DASHBOARD"
    UNKNOWN = "UNKNOWN"


ROLE_URL_MAP = {
    TabRole.NIFTY_CHAIN: "https://www.paytmmoney.com/stocks/fno/option-chain/2000000011/NIFTY/NSE",
    TabRole.BANKNIFTY_CHAIN: "https://www.paytmmoney.com/stocks/fno/option-chain/2000000023/BANKNIFTY/NSE",
    TabRole.AGI_DASHBOARD: "http://127.0.0.1:8088/",
}


@dataclass
class BrowserTarget:
    target_id: str
    role: TabRole
    url: str
    title: str
    ws_url: Optional[str] = None
    is_attached: bool = False
    last_heartbeat: Optional[str] = None
    last_error: Optional[str] = None
    recovery_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["role"] = self.role.value
        return d


class TriTabTopology:
    """Maintains and verifies the 3-tab Chrome topology."""

    def __init__(self, cdp_port: int = 9229):
        self.cdp_port = cdp_port
        self.registry: Dict[TabRole, BrowserTarget] = {}
        self.last_audit_time: Optional[str] = None

    def classify_url_role(self, url: str) -> TabRole:
        """Deterministically classifies tab URL into a designated role."""
        if not url:
            return TabRole.UNKNOWN
        u = url.lower()
        if "paytmmoney.com/stocks/fno/option-chain" in u and ("2000000011" in u or "nifty/nse" in u) and "bank" not in u:
            return TabRole.NIFTY_CHAIN
        if "paytmmoney.com/stocks/fno/option-chain" in u and ("2000000023" in u or "banknifty" in u):
            return TabRole.BANKNIFTY_CHAIN
        if "127.0.0.1:8088" in u or "localhost:8088" in u:
            return TabRole.AGI_DASHBOARD
        return TabRole.UNKNOWN

    def query_cdp_targets(self) -> List[Dict[str, Any]]:
        """Queries /json from CDP port."""
        url = f"http://127.0.0.1:{self.cdp_port}/json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AGI-TriTab-Auditor"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode())
                return [t for t in data if t.get("type") == "page"]
        except Exception as e:
            logger.debug(f"CDP query failed: {e}")
            return []

    def audit_topology(self) -> Dict[str, Any]:
        """Audits current CDP tabs against the 3 target roles."""
        self.last_audit_time = datetime.now(timezone.utc).isoformat()
        pages = self.query_cdp_targets()

        active_roles: Dict[TabRole, BrowserTarget] = {}
        unassigned_pages: List[Dict[str, Any]] = []

        for p in pages:
            url = p.get("url", "")
            target_id = p.get("id", "")
            ws_url = p.get("webSocketDebuggerUrl")
            title = p.get("title", "")
            role = self.classify_url_role(url)

            if role != TabRole.UNKNOWN:
                # If we already have a target for this role, preserve the first healthy one
                if role not in active_roles:
                    target = BrowserTarget(
                        target_id=target_id,
                        role=role,
                        url=url,
                        title=title,
                        ws_url=ws_url,
                        is_attached=True,
                        last_heartbeat=self.last_audit_time
                    )
                    active_roles[role] = target
                else:
                    unassigned_pages.append(p)
            else:
                unassigned_pages.append(p)

        self.registry = active_roles
        missing_roles = [r.value for r in [TabRole.NIFTY_CHAIN, TabRole.BANKNIFTY_CHAIN, TabRole.AGI_DASHBOARD] if r not in active_roles]

        return {
            "timestamp": self.last_audit_time,
            "cdp_port": self.cdp_port,
            "total_pages_detected": len(pages),
            "assigned_roles": {r.value: t.to_dict() for r, t in active_roles.items()},
            "missing_roles": missing_roles,
            "all_roles_satisfied": len(missing_roles) == 0,
            "unassigned_tabs_count": len(unassigned_pages)
        }

    def recover_missing_role(self, role: TabRole) -> Tuple[bool, Optional[str]]:
        """Safely creates the tab for the missing role via CDP /json/new."""
        if role in self.registry:
            return True, "Role already satisfied"

        target_url = ROLE_URL_MAP.get(role)
        if not target_url:
            return False, f"Unknown role {role}"

        # Request CDP to open new target tab with designated URL
        encoded_url = urllib.parse.quote(target_url, safe=":/")
        new_tab_endpoint = f"http://127.0.0.1:{self.cdp_port}/json/new?{encoded_url}"
        try:
            req = urllib.request.Request(new_tab_endpoint, method="PUT")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode())
                target_id = data.get("id")
                ws_url = data.get("webSocketDebuggerUrl")
                title = data.get("title", "")

                bt = BrowserTarget(
                    target_id=target_id,
                    role=role,
                    url=target_url,
                    title=title,
                    ws_url=ws_url,
                    is_attached=True,
                    last_heartbeat=datetime.now(timezone.utc).isoformat(),
                    recovery_count=1
                )
                self.registry[role] = bt
                return True, None
        except Exception as e:
            return False, f"Failed to create target for {role.value}: {e}"
