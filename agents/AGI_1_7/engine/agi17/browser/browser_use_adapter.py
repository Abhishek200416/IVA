"""AGI 1.7 OMEGA COMMAND — Browser Use Architecture Adapter.

Integrates Browser Use's paradigm into AGI 1.7's PersistentBrowserService:
- Builds an accessible, indexed interactive element registry (1-indexed monotonic targets).
- Provides element-indexed action routing (click_by_index, type_by_index, hover_by_index).
- Generates compact DOM accessibility text summaries optimized for LLM token budgets.
- Integrates with the native Antigravity sidecar panel without external Chrome windows or Docker.
- Enforces PAPER mode safety and human takeover gates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .browser_service import BrowserControlState, PersistentBrowserService
from .observation_pipeline import PageElement

logger = logging.getLogger("BrowserUseAdapter")


@dataclass
class BrowserUseElement:
    """Indexed interactive element following the Browser Use paradigm."""
    index: int
    element_id: str
    tag: str
    role: str
    name: str
    bounding_box: Dict[str, float]
    center_x: int
    center_y: int
    is_interactive: bool = True
    is_enabled: bool = True
    value: Optional[str] = None

    def to_summary_line(self) -> str:
        val_str = f' value="{self.value}"' if self.value is not None else ""
        return (
            f"[{self.index}] <{self.tag} role=\"{self.role}\" name=\"{self.name}\"{val_str}> "
            f"at ({self.center_x}, {self.center_y})"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "id": self.element_id,
            "tag": self.tag,
            "role": self.role,
            "name": self.name,
            "box": self.bounding_box,
            "center": (self.center_x, self.center_y),
            "value": self.value,
        }


class BrowserUseAdapter:
    """Adapter implementing Browser Use DOM-grounded interaction for AGI 1.7."""

    def __init__(self, browser_service: Optional[Any] = None) -> None:
        self.browser_service = browser_service if browser_service is not None else PersistentBrowserService()
        self._indexed_elements: Dict[int, BrowserUseElement] = {}

    def extract_dom_state(self) -> List[BrowserUseElement]:
        """Indexes all active interactive DOM elements monotonically [1..N]."""
        self._indexed_elements.clear()
        raw_elements = self.browser_service.get_dom_elements()

        indexed: List[BrowserUseElement] = []
        for idx, elem in enumerate(raw_elements, start=1):
            bbox = elem.bounding_box or {"x": 400.0, "y": 170.0, "width": 100.0, "height": 30.0}
            bx = bbox.get("x", 0.0)
            by = bbox.get("y", 0.0)
            bw = bbox.get("width", 0.0)
            bh = bbox.get("height", 0.0)
            cx = int(bx + (bw / 2.0))
            cy = int(by + (bh / 2.0))

            bue = BrowserUseElement(
                index=idx,
                element_id=elem.element_id,
                tag=elem.tag,
                role=elem.role,
                name=elem.name,
                bounding_box=bbox,
                center_x=cx,
                center_y=cy,
                is_interactive=elem.is_interactive,
                is_enabled=elem.is_enabled,
                value=elem.value,
            )
            self._indexed_elements[idx] = bue
            indexed.append(bue)

        return indexed

    def get_annotated_dom_text(self) -> str:
        """Returns compact text representation of indexed elements for LLM reasoning."""
        elements = self.extract_dom_state()
        if not elements:
            return "[Browser Use DOM]: No interactive elements detected."
        lines = ["[Browser Use Indexed DOM]:"]
        for elem in elements:
            lines.append(f"  {elem.to_summary_line()}")
        return "\n".join(lines)

    def get_element_by_index(self, index: int) -> Optional[BrowserUseElement]:
        """Looks up an indexed element, re-indexing if cache is empty."""
        if not self._indexed_elements:
            self.extract_dom_state()
        return self._indexed_elements.get(index)

    def click_by_index(self, index: int, button: str = "left") -> Dict[str, Any]:
        """Dispatches click action targeting an element by its Browser Use index."""
        target = self.get_element_by_index(index)
        if not target:
            raise KeyError(f"Browser Use element index [{index}] not found in current DOM state.")

        result = self.browser_service.click_at(target.center_x, target.center_y, button=button)
        result["browser_use_index"] = index
        result["target_element"] = target.name
        return result

    def type_by_index(self, index: int, text: str, clear_first: bool = True) -> Dict[str, Any]:
        """Dispatches typing action targeting an element by its Browser Use index."""
        target = self.get_element_by_index(index)
        if not target:
            raise KeyError(f"Browser Use element index [{index}] not found in current DOM state.")

        result = self.browser_service.type_at(
            target.center_x, target.center_y, text=text, clear_first=clear_first
        )
        result["browser_use_index"] = index
        result["target_element"] = target.name
        # Refresh cache to capture updated value
        self.extract_dom_state()
        return result

    def hover_by_index(self, index: int) -> Dict[str, Any]:
        """Moves virtual cursor to hover over the indexed element."""
        target = self.get_element_by_index(index)
        if not target:
            raise KeyError(f"Browser Use element index [{index}] not found in current DOM state.")

        result = self.browser_service.move_cursor(target.center_x, target.center_y)
        result["browser_use_index"] = index
        return result

    def navigate(self, url: str) -> Dict[str, Any]:
        """Navigates browser to URL and invalidates indexed DOM cache."""
        res = self.browser_service.navigate(url)
        self.extract_dom_state()
        return res

    def scroll(self, direction: str = "down", amount: int = 300) -> Dict[str, Any]:
        """Scrolls page and updates coordinate offsets."""
        res = self.browser_service.scroll(direction=direction, amount=amount)
        self.extract_dom_state()
        return res

    def get_latest_viewport_png(self) -> bytes:
        """Returns the authoritative viewport frame PNG."""
        if hasattr(self.browser_service, "get_latest_viewport_png"):
            return self.browser_service.get_latest_viewport_png()
        return self.browser_service.get_raw_screenshot_bytes(reason="browser_use_viewport")

    def get_panel_telemetry(self) -> Dict[str, Any]:
        """Returns live telemetry payload formatted for the native Antigravity panel."""
        elements = self.extract_dom_state()
        status = self.browser_service.get_status()
        return {
            "session_id": status.get("session_id"),
            "url": self.browser_service.current_url,
            "title": self.browser_service.current_title,
            "control_state": status.get("control_state"),
            "cursor": (self.browser_service.cursor_x, self.browser_service.cursor_y),
            "scroll_y": self.browser_service.scroll_y,
            "indexed_element_count": len(elements),
            "indexed_elements": [e.to_dict() for e in elements],
        }
