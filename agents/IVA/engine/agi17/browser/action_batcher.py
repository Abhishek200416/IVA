"""Action Batcher for high-speed, token-efficient browser operation sequences.

Allows executing sequences of safe deterministic actions in a single driver invocation
without requiring language model round-trips for each individual keystroke or click.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    FILL = "fill"
    PRESS_KEY = "press_key"
    SCROLL = "scroll"
    READ_PAGE = "read_page"
    INSPECT_ELEMENT = "inspect_element"
    WAIT_FOR_STATE = "wait_for_state"
    WAIT_FOR_NETWORK_IDLE = "wait_for_network_idle"
    CAPTURE_VIEW = "capture_view"
    GET_TABS = "get_tabs"
    SWITCH_TAB = "switch_tab"
    NEW_TAB = "new_tab"
    CLOSE_TAB = "close_tab"
    BROWSER_HEALTH = "browser_health"
    TAKE_CONTROL = "take_control"
    RETURN_CONTROL = "return_control"
    CLICK_COORDINATE = "click_coordinate"
    TYPE_COORDINATE = "type_coordinate"
    SCROLL_WHEEL = "scroll_wheel"
    MOVE_CURSOR = "move_cursor"
    DISMISS_MODAL = "dismiss_modal"


@dataclass
class BrowserAction:
    """A single typed browser operation."""
    action_type: ActionType
    selector: Optional[str] = None
    value: Optional[str] = None
    timeout_ms: int = 5000
    expected_postcondition: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def navigate(cls, url: str) -> BrowserAction:
        return cls(action_type=ActionType.NAVIGATE, value=url)

    @classmethod
    def click(cls, selector: str, expected_state: Optional[str] = None) -> BrowserAction:
        return cls(action_type=ActionType.CLICK, selector=selector, expected_postcondition=expected_state)

    @classmethod
    def type_text(cls, selector: str, text: str) -> BrowserAction:
        return cls(action_type=ActionType.TYPE, selector=selector, value=text)

    @classmethod
    def fill(cls, selector: str, text: str) -> BrowserAction:
        return cls(action_type=ActionType.FILL, selector=selector, value=text)

    @classmethod
    def press_key(cls, key: str) -> BrowserAction:
        return cls(action_type=ActionType.PRESS_KEY, value=key)

    @classmethod
    def scroll(cls, direction: str = "down", amount: int = 300) -> BrowserAction:
        return cls(action_type=ActionType.SCROLL, value=direction, metadata={"amount": amount})

    @classmethod
    def wait_for_state(cls, condition: str, timeout_ms: int = 5000) -> BrowserAction:
        return cls(action_type=ActionType.WAIT_FOR_STATE, value=condition, timeout_ms=timeout_ms)

    @classmethod
    def click_coordinate(cls, x: int, y: int, button: str = "left") -> BrowserAction:
        return cls(action_type=ActionType.CLICK_COORDINATE, metadata={"x": x, "y": y, "button": button})

    @classmethod
    def type_coordinate(cls, x: int, y: int, text: str) -> BrowserAction:
        return cls(action_type=ActionType.TYPE_COORDINATE, value=text, metadata={"x": x, "y": y})

    @classmethod
    def scroll_wheel(cls, delta_x: int, delta_y: int, x: Optional[int] = None, y: Optional[int] = None) -> BrowserAction:
        return cls(action_type=ActionType.SCROLL_WHEEL, metadata={"delta_x": delta_x, "delta_y": delta_y, "x": x, "y": y})

    @classmethod
    def move_cursor(cls, x: int, y: int) -> BrowserAction:
        return cls(action_type=ActionType.MOVE_CURSOR, metadata={"x": x, "y": y})

    @classmethod
    def dismiss_modal(cls) -> BrowserAction:
        return cls(action_type=ActionType.DISMISS_MODAL)


@dataclass
class BrowserBatchResult:
    """Result of executing a batch of actions."""
    success: bool
    actions_attempted: int
    actions_confirmed: int
    elapsed_ms: float
    final_url: str
    final_title: str
    last_observation: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    interrupted_by_human: bool = False
    action_logs: List[Dict[str, Any]] = field(default_factory=list)


class ActionBatcher:
    """Executes a list of BrowserActions sequentially against a browser driver."""

    def __init__(self, driver: Any) -> None:
        self.driver = driver

    def execute_batch(
        self,
        actions: List[BrowserAction],
        stop_on_human_takeover: bool = True,
    ) -> BrowserBatchResult:
        """Executes a batch of actions in sequence."""
        start_time = time.time()
        actions_confirmed = 0
        logs: List[Dict[str, Any]] = []

        for i, action in enumerate(actions):
            # Check if human takeover occurred
            if stop_on_human_takeover and hasattr(self.driver, "is_human_in_control"):
                if self.driver.is_human_in_control():
                    elapsed = (time.time() - start_time) * 1000.0
                    return BrowserBatchResult(
                        success=False,
                        actions_attempted=i,
                        actions_confirmed=actions_confirmed,
                        elapsed_ms=round(elapsed, 2),
                        final_url=getattr(self.driver, "current_url", ""),
                        final_title=getattr(self.driver, "current_title", ""),
                        interrupted_by_human=True,
                        error_message="Batch paused: Human takeover initiated.",
                        action_logs=logs,
                    )

            step_start = time.time()
            try:
                result = self._dispatch_action(action)
                step_elapsed = (time.time() - step_start) * 1000.0
                actions_confirmed += 1
                logs.append({
                    "step": i + 1,
                    "action": action.action_type.value,
                    "selector": action.selector,
                    "success": True,
                    "elapsed_ms": round(step_elapsed, 2),
                    "result": result,
                })
            except Exception as exc:
                step_elapsed = (time.time() - step_start) * 1000.0
                logs.append({
                    "step": i + 1,
                    "action": action.action_type.value,
                    "selector": action.selector,
                    "success": False,
                    "elapsed_ms": round(step_elapsed, 2),
                    "error": str(exc),
                })
                elapsed = (time.time() - start_time) * 1000.0
                return BrowserBatchResult(
                    success=False,
                    actions_attempted=i + 1,
                    actions_confirmed=actions_confirmed,
                    elapsed_ms=round(elapsed, 2),
                    final_url=getattr(self.driver, "current_url", ""),
                    final_title=getattr(self.driver, "current_title", ""),
                    error_message=f"Action {action.action_type.value} failed: {exc}",
                    action_logs=logs,
                )

        elapsed = (time.time() - start_time) * 1000.0
        obs = self.driver.get_compact_observation() if hasattr(self.driver, "get_compact_observation") else None

        return BrowserBatchResult(
            success=True,
            actions_attempted=len(actions),
            actions_confirmed=actions_confirmed,
            elapsed_ms=round(elapsed, 2),
            final_url=getattr(self.driver, "current_url", ""),
            final_title=getattr(self.driver, "current_title", ""),
            last_observation=obs,
            action_logs=logs,
        )

    def _dispatch_action(self, action: BrowserAction) -> Any:
        t = action.action_type
        if t == ActionType.NAVIGATE:
            return self.driver.navigate(action.value or "about:blank")
        elif t == ActionType.CLICK:
            return self.driver.click(action.selector or "")
        elif t == ActionType.TYPE:
            return self.driver.type_text(action.selector or "", action.value or "")
        elif t == ActionType.FILL:
            return self.driver.fill(action.selector or "", action.value or "")
        elif t == ActionType.PRESS_KEY:
            return self.driver.press_key(action.value or "Enter")
        elif t == ActionType.SCROLL:
            amount = action.metadata.get("amount", 300)
            return self.driver.scroll(action.value or "down", amount)
        elif t == ActionType.WAIT_FOR_STATE:
            return self.driver.wait_for_state(action.value or "", action.timeout_ms)
        elif t == ActionType.READ_PAGE:
            return self.driver.read_page()
        elif t == ActionType.INSPECT_ELEMENT:
            return self.driver.inspect_element(action.selector or "")
        elif t == ActionType.SWITCH_TAB:
            return self.driver.switch_tab(action.value or "")
        elif t == ActionType.NEW_TAB:
            return self.driver.new_tab(action.value or "about:blank")
        elif t == ActionType.CLOSE_TAB:
            return self.driver.close_tab(action.value or "")
        elif t == ActionType.TAKE_CONTROL:
            return self.driver.take_control()
        elif t == ActionType.RETURN_CONTROL:
            return self.driver.return_control()
        elif t == ActionType.CLICK_COORDINATE:
            x = action.metadata.get("x", 0)
            y = action.metadata.get("y", 0)
            button = action.metadata.get("button", "left")
            return self.driver.click_at(x, y, button=button)
        elif t == ActionType.TYPE_COORDINATE:
            x = action.metadata.get("x", 0)
            y = action.metadata.get("y", 0)
            return self.driver.type_at(x, y, action.value or "")
        elif t == ActionType.SCROLL_WHEEL:
            delta_x = action.metadata.get("delta_x", 0)
            delta_y = action.metadata.get("delta_y", 300)
            x = action.metadata.get("x")
            y = action.metadata.get("y")
            return self.driver.scroll_wheel(delta_x, delta_y, x=x, y=y)
        elif t == ActionType.MOVE_CURSOR:
            x = action.metadata.get("x", 0)
            y = action.metadata.get("y", 0)
            return self.driver.move_cursor(x, y)
        elif t == ActionType.DISMISS_MODAL:
            return self.driver.dismiss_modal()
        else:
            raise ValueError(f"Unsupported action type: {t}")
