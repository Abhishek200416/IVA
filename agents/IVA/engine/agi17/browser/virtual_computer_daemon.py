"""AGI 1.7 OMEGA COMMAND — In-Chat Virtual Computer Runtime Daemon.

Initializes the persistent browser session, runs the BrowserStreamServer on loopback,
executes the visual interaction loop (Observe -> Ground -> Act -> Verify -> Recover),
and maintains the live background service for external and side-by-side access.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parents[4]
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from agents.AGI_1_7.engine.agi17.browser import (
    ActionKind,
    BrowserControlState,
    BrowserSessionManager,
    BrowserStreamServer,
    ExecutionMode,
    PersistentBrowserService,
    RiskControlGate,
    VisualAction,
    VisualAgentLoop,
)


def run_virtual_computer_demonstration() -> dict:
    # 1. Initialize Authoritative Persistent Browser Service
    mgr = PersistentBrowserService()
    session = mgr.session
    assert session is not None

    # 2. Initialize and Start Loopback Stream Server
    server = BrowserStreamServer(mgr, host="127.0.0.1", port=8765)
    server.start_background()

    # 3. Initialize Visual Computer Use Loop in PAPER Mode (Isolated Sandbox)
    risk_gate = RiskControlGate(default_mode=ExecutionMode.PAPER)
    loop = VisualAgentLoop(driver=mgr, risk_gate=risk_gate)

    results = []

    # Action 1: Navigate to test interface
    act1 = VisualAction.navigate("https://www.google.com")
    step1 = loop.step(act1)
    results.append({
        "action": "navigate",
        "target": "https://www.google.com",
        "success": step1.success,
        "verified": step1.verification.is_verified if step1.verification else False,
        "url": mgr.current_url,
        "title": mgr.current_title,
    })

    # Action 2: Move mouse cursor to test input field
    act2 = VisualAction(kind=ActionKind.MOVE_CURSOR, target_coords=(400, 170))
    step2 = loop.step(act2)
    results.append({
        "action": "move_mouse",
        "coords": (400, 170),
        "cursor": (mgr.cursor_x, mgr.cursor_y),
        "success": step2.success,
    })

    # Action 3: Click visible element (search box)
    act3 = VisualAction.click_coordinate(400, 170)
    step3 = loop.step(act3)
    results.append({
        "action": "click",
        "coords": (400, 170),
        "focused_element": mgr.focused_element_id,
        "success": step3.success,
        "verified": step3.verification.is_verified if step3.verification else False,
    })

    # Action 4: Type into safe test field
    act4 = VisualAction.type_coordinate(400, 170, "AGI 1.7 OMEGA VIRTUAL COMPUTER DEMO")
    step4 = loop.step(act4)
    results.append({
        "action": "type_text",
        "text": "AGI 1.7 OMEGA VIRTUAL COMPUTER DEMO",
        "focused_element": mgr.focused_element_id,
        "success": step4.success,
        "verified": step4.verification.is_verified if step4.verification else False,
    })

    # Action 5: Scroll viewport
    act5 = VisualAction.scroll_wheel(delta_y=300)
    step5 = loop.step(act5)
    results.append({
        "action": "scroll",
        "scroll_offset": (mgr.scroll_x, mgr.scroll_y),
        "success": step5.success,
        "verified": step5.verification.is_verified if step5.verification else False,
    })

    status = mgr.get_status()

    output = {
        "session_id": session.session_id,
        "browser_status": session.health_status.value,
        "control_state": session.control_state.value,
        "display_status": {
            "viewport_width": mgr.viewport_width,
            "viewport_height": mgr.viewport_height,
            "dpi_scale": mgr.dpi_scale,
            "active_tab": session.active_tab_id,
            "current_url": mgr.current_url,
            "current_title": mgr.current_title,
        },
        "input_controller_status": {
            "mode": "ISOLATED_SANDBOX_PAPER",
            "host_desktop_actuation": "DISABLED (Host Safe)",
            "total_actions_executed": session.total_actions_executed,
        },
        "live_stream": {
            "host": "127.0.0.1",
            "port": server.server_port,
            "token": session.external_access_token,
            "external_url": session.external_url,
            "server_active": True,
        },
        "actions_log": results,
    }

    # Save persistent state to disk
    state_file = Path(mgr.profile_dir) / "virtual_computer_state.json"
    state_file.write_text(json.dumps(output, indent=2), encoding="utf-8")

    return output


if __name__ == "__main__":
    out = run_virtual_computer_demonstration()
    print("VIRTUAL_COMPUTER_RESULT_JSON_START")
    print(json.dumps(out, indent=2))
    print("VIRTUAL_COMPUTER_RESULT_JSON_END")
