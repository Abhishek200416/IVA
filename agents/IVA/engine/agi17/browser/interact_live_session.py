"""Interact with the live running PersistentBrowserService session and verify changes."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

root_dir = Path(__file__).resolve().parents[4]
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from agents.AGI_1_7.engine.agi17.browser import (
    ActionKind,
    ExecutionMode,
    PersistentBrowserService,
    RiskControlGate,
    VisualAction,
    VisualAgentLoop,
)

def main():
    mgr = PersistentBrowserService()
    session = mgr.session
    assert session is not None

    risk_gate = RiskControlGate(default_mode=ExecutionMode.PAPER)
    loop = VisualAgentLoop(driver=mgr, risk_gate=risk_gate)

    results = []

    # 1. Navigate
    print("[1/5] Navigating to https://www.google.com...")
    s1 = loop.step(VisualAction.navigate("https://www.google.com"))
    results.append({
        "step": 1,
        "action": "navigate",
        "url": mgr.current_url,
        "title": mgr.current_title,
        "verified": s1.verification.is_verified if s1.verification else False,
        "visual_diff_ratio": s1.verification.visual_change_ratio if s1.verification else 0.0,
    })

    # 2. Move mouse
    print("[2/5] Moving mouse to (400, 170)...")
    s2 = loop.step(VisualAction(kind=ActionKind.MOVE_CURSOR, target_coords=(400, 170)))
    results.append({
        "step": 2,
        "action": "move_mouse",
        "cursor": (mgr.cursor_x, mgr.cursor_y),
        "verified": s2.success,
    })

    # 3. Click search box
    print("[3/5] Clicking at (400, 170)...")
    s3 = loop.step(VisualAction.click_coordinate(400, 170))
    results.append({
        "step": 3,
        "action": "click",
        "focused_element": mgr.focused_element_id,
        "cursor": (mgr.cursor_x, mgr.cursor_y),
        "verified": s3.verification.is_verified if s3.verification else False,
    })

    # 4. Type search query
    print("[4/5] Typing search query...")
    s4 = loop.step(VisualAction.type_coordinate(400, 170, "AGI 1.7 OMEGA LIVE INTERACTION"))
    results.append({
        "step": 4,
        "action": "type_text",
        "text": "AGI 1.7 OMEGA LIVE INTERACTION",
        "focused_element": mgr.focused_element_id,
        "element_val": [e.value for e in mgr._dom_elements if e.element_id == mgr.focused_element_id],
        "verified": s4.verification.is_verified if s4.verification else False,
    })

    # 5. Scroll
    print("[5/5] Scrolling viewport...")
    s5 = loop.step(VisualAction.scroll_wheel(delta_y=300))
    results.append({
        "step": 5,
        "action": "scroll",
        "scroll_y": mgr.scroll_y,
        "verified": s5.verification.is_verified if s5.verification else False,
    })

    print("ALL_STEPS_COMPLETED")
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
