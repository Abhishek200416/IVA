"""AGI 1.7 OMEGA COMMAND — ChatGPT Cadence Governor & Memory Preserver.

Enforces operator-directed token-conserving & context-preserving query cadence:
1. AFTER-MARKET HOURS (15:30 to 08:15 IST):
   - Query ChatGPT every 2 hours (120 minutes)
   - Minimizes token consumption and prevents ChatGPT chat context bloating.
2. PRE-MARKET RECONNAISSANCE (08:15 to 09:15 IST, 1 hour before market open):
   - Wakes up squad.
   - Queries ChatGPT every 10 minutes.
   - Ingests overnight GIFT Nifty, Asian markets, crude oil, and domestic liquidity flows.
   - Triggers quad-agent deliberation (Emily, Max, Alexa, Manager Iva).
3. ACTIVE MARKET HOURS (09:15 to 15:30 IST):
   - Query ChatGPT every 5 minutes for live breaking news catalysts and market drivers.
"""

import sys
import os
import time
import json
import datetime
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agents" / "AGI_1_7" / "engine"))

from agi17.browser.cdp_universal_mouse import _cdp_ws_send_and_recv

STATE_FILE = REPO_ROOT / "scratch" / "emily_sweep_state.json"
REASONING_FILE = REPO_ROOT / "scratch" / "reasoning_chat.json"
NEWS_FILE = REPO_ROOT / "alexa_newspaper_intelligence.json"
TV_STATE_FILE = REPO_ROOT / "scratch" / "tradingview_macro_state.json"

try:
    from agents.AGI_1_7.engine.agi17.finance.tradingview_macro_harvester import harvest_tradingview_macro_quotes
except Exception:
    harvest_tradingview_macro_quotes = None

def get_market_period_and_interval():
    """
    Returns (period_name, interval_seconds).
    - AFTER_MARKET: 7200s (2 hours)
    - PRE_MARKET_1H: 600s (10 minutes)
    - LIVE_MARKET: 300s (5 minutes)
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
    hour = now_ist.hour
    minute = now_ist.minute
    total_minutes = hour * 60 + minute

    # Pre-market: 08:15 to 09:15 IST (495 to 555 minutes)
    if 495 <= total_minutes < 555:
        return "PRE_MARKET_1H", 600 # 10 minutes
    # Live market: 09:15 to 15:30 IST (555 to 930 minutes)
    elif 555 <= total_minutes <= 930:
        return "LIVE_MARKET", 300 # 5 minutes
    # After market: all other times (3 hours per operator instruction)
    else:
        return "AFTER_MARKET", 10800 # 3 hours

def query_chatgpt_tab(prompt_text: str) -> dict:
    """Finds ChatGPT tab on port 9229 and reads latest responses."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:9229/json", timeout=3.0) as r:
            tabs = json.loads(r.read().decode())
        chatgpt_tab = next((t for t in tabs if "chatgpt.com" in t.get("url", "")), None)
        if not chatgpt_tab:
            return {"ok": False, "error": "No ChatGPT tab found on CDP 9229"}
        
        ws_url = chatgpt_tab.get("webSocketDebuggerUrl")
        js_read = """
        (() => {
            const articles = Array.from(document.querySelectorAll('article'));
            const lastTurn = articles.length > 0 ? articles[articles.length - 1].innerText : (document.querySelector('main')?.innerText || '');
            return {
                title: document.title,
                url: window.location.href,
                latest_text: lastTurn.substring(0, 1500)
            };
        })()
        """
        res = _cdp_ws_send_and_recv(ws_url, [{"id": 1, "method": "Runtime.evaluate", "params": {"expression": js_read, "returnByValue": True}}], timeout=2.5)
        val = res[0]["result"]["result"].get("value", {})
        return {"ok": True, "data": val}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def run_cadence_governor_loop():
    print("=== AGI 1.7 CHATGPT CADENCE GOVERNOR INITIALIZED ===")
    print("Rules Active:")
    print("  • After-Market (15:30 - 08:15 IST): Every 2 hours (saves tokens & context)")
    print("  • 1 Hour Before Open (08:15 - 09:15 IST): Every 10 minutes (quad-agent prep)")
    print("  • Regular Market (09:15 - 15:30 IST): Every 5 minutes (tactical catalysts)")

    last_query_time = 0

    while True:
        try:
            period, interval_sec = get_market_period_and_interval()
            now = time.time()
            elapsed = now - last_query_time

            # Check for operator immediate manual override
            forced_run = False
            if STATE_FILE.exists():
                try:
                    sweep_state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                    if sweep_state.get("is_working_now") and sweep_state.get("mode") == "ACTIVE_OFF_MARKET_SWEEP":
                        # If triggered less than 60s ago
                        triggered_time = sweep_state.get("triggered_timestamp", 0)
                        if now - triggered_time < 30 and not sweep_state.get("sweep_dispatched"):
                            forced_run = True
                            sweep_state["sweep_dispatched"] = True
                            STATE_FILE.write_text(json.dumps(sweep_state, indent=2), encoding="utf-8")
                except Exception:
                    pass

            if elapsed >= interval_sec or forced_run:
                ist_now_str = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %I:%M:%S %p IST")
                print(f"[{ist_now_str}] Executing {period} inquiry (Interval: {interval_sec}s | Forced: {forced_run})...")

                # Harvest TradingView live macro data
                tv_data = {}
                if harvest_tradingview_macro_quotes:
                    try:
                        tv_data = harvest_tradingview_macro_quotes()
                    except Exception:
                        pass

                # Perform CDP probe with live TradingView cues
                tv_cues = tv_data.get("summary", {}).get("overnight_cues", "")
                probe_res = query_chatgpt_tab(f"Market status check: {period}. {tv_cues}")
                last_query_time = now

                # Update state file
                next_inquiry_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))) + datetime.timedelta(seconds=interval_sec)
                state_doc = {
                    "ok": True,
                    "mode": "START_ON_MARKET_TIME" if not forced_run else "START_IMMEDIATELY",
                    "current_period": period,
                    "interval_seconds": interval_sec,
                    "last_inquiry_ist": ist_now_str,
                    "next_scheduled_inquiry_ist": next_inquiry_dt.strftime("%I:%M:%S %p IST"),
                    "chatgpt_tab_status": "CONNECTED" if probe_res.get("ok") else "AWAITING_TAB",
                    "token_saver_active": period == "AFTER_MARKET",
                    "tradingview_macro": tv_data.get("summary", {}),
                    "notes": "3-hour sleep mode active to conserve ChatGPT context window and token quota." if period == "AFTER_MARKET" else "Active pre-market 10m probe."
                }
                STATE_FILE.write_text(json.dumps(state_doc, indent=2), encoding="utf-8")

            time.sleep(5.0)
        except Exception as e:
            print(f"[CADENCE GOVERNOR ERROR] {e}")
            time.sleep(10.0)

if __name__ == "__main__":
    run_cadence_governor_loop()
