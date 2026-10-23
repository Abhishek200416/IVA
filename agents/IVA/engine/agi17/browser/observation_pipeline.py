"""Tiered Observation Pipeline for Token-Efficient Persistent Browsing.

Implements the 4-tier observation doctrine:
- Tier 1: Structured data first (compact DOM, ARIA accessible roles, controls, text snippets)
- Tier 2: Event-driven page updates (DOM mutations, lifecycle state, debounced change detection)
- Tier 3: Targeted visual inspection (screenshots only for canvas/charts/ambiguity)
- Tier 4: Critical-action pre/post verification
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ObservationTier(str, Enum):
    TIER_1_STRUCTURED = "TIER_1_STRUCTURED"
    TIER_2_EVENT_DRIVEN = "TIER_2_EVENT_DRIVEN"
    TIER_3_VISUAL = "TIER_3_VISUAL"
    TIER_4_CRITICAL_VERIFY = "TIER_4_CRITICAL_VERIFY"


@dataclass
class PageElement:
    """Semantic interactive page control."""
    element_id: str
    tag: str
    role: str
    name: str
    selector: str
    is_interactive: bool = True
    is_enabled: bool = True
    value: Optional[str] = None
    bounding_box: Optional[Dict[str, float]] = None

    def to_compact_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.element_id,
            "role": self.role,
            "name": self.name,
            "selector": self.selector,
        }
        if not self.is_enabled:
            d["disabled"] = True
        if self.value:
            d["value"] = self.value
        return d


@dataclass
class PageObservation:
    """Compact, structured page observation state representation."""
    url: str
    title: str
    tier: ObservationTier
    timestamp: float = field(default_factory=time.time)
    tab_id: str = "tab-default"
    interactive_elements: List[PageElement] = field(default_factory=list)
    visible_text_snippet: str = ""
    active_element: Optional[str] = None
    dialog_open: bool = False
    dialog_text: Optional[str] = None
    is_loading: bool = False
    screenshot_base64: Optional[str] = None
    screenshot_sha256: Optional[str] = None
    state_digest: str = ""

    def __post_init__(self) -> None:
        if not self.state_digest:
            raw = f"{self.url}|{self.title}|{len(self.interactive_elements)}|{self.visible_text_snippet[:100]}"
            self.state_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_compact_summary(self) -> Dict[str, Any]:
        """Returns minimal representation suitable for LLM context without token bloat."""
        return {
            "url": self.url,
            "title": self.title,
            "tier": self.tier.value,
            "timestamp": round(self.timestamp, 3),
            "is_loading": self.is_loading,
            "dialog_open": self.dialog_open,
            "element_count": len(self.interactive_elements),
            "key_controls": [e.to_compact_dict() for e in self.interactive_elements[:15]],
            "text_summary": self.visible_text_snippet[:250],
            "state_digest": self.state_digest,
            "has_screenshot": bool(self.screenshot_base64),
        }


class TieredObservationPipeline:
    """Manages the tiered observation lifecycle and observation cache."""

    def __init__(self, cache_ttl_sec: float = 3.0) -> None:
        self.cache_ttl_sec = cache_ttl_sec
        self.last_observation: Optional[PageObservation] = None
        self.observation_count: int = 0
        self.screenshot_count: int = 0
        self.cached_observations_served: int = 0

    def capture_tier1_structured(
        self,
        url: str,
        title: str,
        elements: List[PageElement],
        text_snippet: str,
        tab_id: str = "tab-default",
        is_loading: bool = False,
    ) -> PageObservation:
        """Tier 1: Extract compact DOM/ARIA structure. Zero screenshot overhead."""
        self.observation_count += 1
        obs = PageObservation(
            url=url,
            title=title,
            tier=ObservationTier.TIER_1_STRUCTURED,
            tab_id=tab_id,
            interactive_elements=elements,
            visible_text_snippet=text_snippet,
            is_loading=is_loading,
        )
        self.last_observation = obs
        return obs

    def capture_tier2_event_driven(
        self,
        url: str,
        title: str,
        mutated_elements: List[PageElement],
        text_snippet: str,
        tab_id: str = "tab-default",
    ) -> PageObservation:
        """Tier 2: Emitted upon significant DOM mutation or state change."""
        self.observation_count += 1
        obs = PageObservation(
            url=url,
            title=title,
            tier=ObservationTier.TIER_2_EVENT_DRIVEN,
            tab_id=tab_id,
            interactive_elements=mutated_elements,
            visible_text_snippet=text_snippet,
        )
        self.last_observation = obs
        return obs

    def capture_tier3_visual(
        self,
        url: str,
        title: str,
        screenshot_bytes: bytes,
        reason: str,
        elements: Optional[List[PageElement]] = None,
        tab_id: str = "tab-default",
    ) -> PageObservation:
        """Tier 3: Targeted visual inspection only when strictly justified."""
        import base64
        self.observation_count += 1
        self.screenshot_count += 1
        b64 = base64.b64encode(screenshot_bytes).decode("ascii")
        sha = hashlib.sha256(screenshot_bytes).hexdigest()
        obs = PageObservation(
            url=url,
            title=title,
            tier=ObservationTier.TIER_3_VISUAL,
            tab_id=tab_id,
            interactive_elements=elements or [],
            screenshot_base64=b64,
            screenshot_sha256=sha,
            visible_text_snippet=f"[Visual Inspection: {reason}]",
        )
        self.last_observation = obs
        return obs

    def verify_tier4_critical(
        self,
        action_name: str,
        target_selector: str,
        expected_precondition: Dict[str, Any],
        actual_state: Dict[str, Any],
    ) -> bool:
        """Tier 4: Verify target and account state before and after consequential action."""
        for key, expected_val in expected_precondition.items():
            actual_val = actual_state.get(key)
            if actual_val != expected_val:
                return False
        return True
