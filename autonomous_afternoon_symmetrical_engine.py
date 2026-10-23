"""AGI 1.7 OMEGA COMMAND — Autonomous Afternoon Symmetrical Alpha Engine.

Designed for fully autonomous, fail-closed operation during the 12:45 PM - 15:15 PM window.
Monitors NIFTY 50 Spot in real-time via Chrome CDP.
Executes high-conviction symmetrical setups (Calls on bullish squeeze, Puts on breakdown).
Guarantees strict margin fit, single-order locking, and wide breathing-room trailing stops.
"""

import sys
import time
import json
import datetime
import subprocess
import urllib.request
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agents" / "AGI_1_7" / "engine"))

from agi17.adapters.paytm_open_api_client import PaytmOpenApiClient
from agi17.browser.cdp_universal_mouse import _cdp_ws_send_and_recv

STATE_FILE = REPO_ROOT / "scratch" / "autonomous_afternoon_engine_state.json"
GUARDIAN_STATE_FILE = REPO_ROOT / "scratch" / "live_position_guardian_state.json"

# Strict Symmetrical Triggers
BULLISH_CE_TRIGGER = 22965.0   # Spot reclaiming morning VWAP
BEARISH_PE_TRIGGER = 22910.0   # Spot cracking morning breakdown support
CHOP_LOWER_BOUND   = 22910.0
CHOP_UPPER_BOUND   = 22965.0

MAX_CASH_ALLOCATION_PER_TRADE = 1150.0  # Fits comfortably inside ₹1,260 available cash
LOT_SIZE = 65

def get_nifty_spot_from_cdp() -> float:
    try:
        tabs_url = "http://127.0.0.1:9229/json"
        with urllib.request.urlopen(tabs_url, timeout=2.5) as resp:
            tabs = json.loads(resp.read().decode())
        chain_tab = next((t for t in tabs if "option-chain" in t.get("url", "") and "2000000011/NIFTY" in t.get("url", "")), None)
        if not chain_tab:
            chain_tab = next((t for t in tabs if "/stocks/positions" in t.get("url", "")), None)
        if not chain_tab:
            return 0.0
        ws_url = chain_tab.get("webSocketDebuggerUrl")
        if not ws_url:
            return 0.0
        
        cmd = [{
            "id": 11,
            "method": "Runtime.evaluate",
            "params": {
                "expression": """
                (() => {
                    const text = document.body.innerText;
                    const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                    for (let i = 0; i < lines.length; i++) {
                        if (lines[i] === 'Nifty 50' || lines[i].includes('NIFTY 50') || lines[i].includes('Nifty 50 down') || lines[i].includes('Nifty 50 up')) {
                            for (let j = i + 1; j < Math.min(i + 5, lines.length); j++) {
                                const val = parseFloat(lines[j].replace(/,/g, ''));
                                if (!isNaN(val) && val > 20000 && val < 30000) {
                                    return val;
                                }
                            }
                        }
                    }
                    return 0.0;
                })()
                """,
                "returnByValue": True
            }
        }]
        res = _cdp_ws_send_and_recv(ws_url, cmd, timeout=2.0)
        if res and "result" in res[0] and "result" in res[0]["result"]:
            val = res[0]["result"]["result"].get("value")
            return float(val) if val else 0.0
    except Exception:
        pass
    return 0.0

def get_option_ltp_from_chain(strike_str: str, opt_type: str) -> float:
    try:
        tabs_url = "http://127.0.0.1:9229/json"
        with urllib.request.urlopen(tabs_url, timeout=2.0) as resp:
            tabs = json.loads(resp.read().decode())
        chain_tab = next((t for t in tabs if "option-chain" in t.get("url", "") and "2000000011/NIFTY" in t.get("url", "")), None)
        if not chain_tab:
            return 0.0
        ws_url = chain_tab.get("webSocketDebuggerUrl")
        opt_type_upper = opt_type.upper()
        js_code = f"""
        (() => {{
            const rows = Array.from(document.querySelectorAll('.lJ4cG1YaJK7yp5SSKPa0Y'));
            for (const r of rows) {{
                const c = Array.from(r.children).map(x => x.innerText.trim());
                if (c.length >= 5 && c[3] === '{strike_str}') {{
                    const rawPrice = '{opt_type_upper}' === 'CE' ? c[2] : c[4];
                    const val = parseFloat(rawPrice.split('\\n')[0].replace(/,/g, ''));
                    if (!isNaN(val) && val > 0.05 && val < 2000.0) return val;
                }}
            }}
            return 0.0;
        }})()
        """
        res = _cdp_ws_send_and_recv(ws_url, [{
            "id": 12,
            "method": "Runtime.evaluate",
            "params": {"expression": js_code, "returnByValue": True}
        }], timeout=1.5)
        if res and "result" in res[0] and "result" in res[0]["result"]:
            val = res[0]["result"]["result"].get("value")
            return float(val) if val else 0.0
    except Exception:
        pass
    return 0.0

def execute_autonomous_order(side: str, spot: float) -> bool:
    print(f"\n=================================================================")
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S IST')}] HIGH-CONVICTION {side} TRIGGER DETECTED! Spot: {spot:.2f}")
    print(f"=================================================================")
    
    client = PaytmOpenApiClient(live_order_dispatch_enabled=True)
    
    if side == "CE":
        # Candidate 1: NIFTY 19 OCT 23050 CALL (SecID: 47164)
        sec_id = "47164"
        contract = "NIFTY 19 OCT 23050 CALL"
        strike = "23050"
        opt_type = "CE"
        est_price = 14.00
    else:
        # Candidate 2: NIFTY 19 OCT 22800 PUT (SecID: 47154)
        sec_id = "47154"
        contract = "NIFTY 19 OCT 22800 PUT"
        strike = "22800"
        opt_type = "PE"
        est_price = 11.20
        
    # Read live price
    live_price = get_option_ltp_from_chain(strike, opt_type)
    if live_price > 0.05:
        est_price = live_price
        
    # Marketable Limit Order (+1.50 pts to ensure instant execution without market order RMS penalties)
    limit_price = round(round((est_price + 1.50) / 0.05) * 0.05, 2)
    
    # Enforce strict cash allocation ceiling (Max ₹1,150)
    qty = LOT_SIZE
    if qty * limit_price > MAX_CASH_ALLOCATION_PER_TRADE:
        limit_price = round(round((MAX_CASH_ALLOCATION_PER_TRADE / qty) / 0.05) * 0.05, 2)
        print(f"[MARGIN GUARD] Capped limit price to ₹{limit_price:.2f} (Total: ₹{qty*limit_price:.2f}) to ensure 100% margin pass.")
        
    buy_payload = {
        'source': 'W',
        'txn_type': 'B',
        'exchange': 'NSE',
        'segment': 'D',
        'product': 'M',
        'security_id': sec_id,
        'quantity': qty,
        'validity': 'DAY',
        'order_type': 'LMT',
        'price': f"{limit_price:.2f}"
    }
    
    print(f"[DISPATCHING ORDER] {qty} units of {contract} @ LMT ₹{limit_price:.2f}...")
    try:
        res = client.place_order(buy_payload)
        order_no = str(res.get("order_no", "ORD_SENT"))
        print(f"[ORDER PLACED] Ref: {order_no}")
        
        # Poll order book for fill status
        time.sleep(2.0)
        ob = client.get_order_book()
        recent = next((o for o in ob if str(o.get("order_no")) == str(order_no)), None)
        
        fill_price = limit_price
        if recent:
            st = recent.get("status", "")
            if st == "Traded":
                fill_price = float(recent.get("avg_traded_price", limit_price))
                print(f"[FILL CONFIRMED] {qty} units filled @ ₹{fill_price:.2f}!")
            elif st == "Rejected":
                reason = recent.get("reason_description", "RMS Reject")
                print(f"[ORDER REJECTED BY BROKER] Reason: {reason}")
                return False
            else:
                print(f"[ORDER PENDING] Status: {st}")
                time.sleep(2.0)
                ob2 = client.get_order_book()
                recent2 = next((o for o in ob2 if str(o.get("order_no")) == str(order_no)), None)
                if recent2 and recent2.get("status") == "Traded":
                    fill_price = float(recent2.get("avg_traded_price", limit_price))
                    print(f"[FILL CONFIRMED ON 2ND POLL] {qty} units filled @ ₹{fill_price:.2f}!")
                else:
                    print(f"[ORDER NOT TRADED] Canceling and entering cooldown...")
                    try:
                        client.cancel_order({'order_no': order_no})
                    except Exception:
                        pass
                    return False
        else:
            print("[WARN] Order not found in top book. Proceeding to attach guardian.")
            
        # Spawn Universal Trailing Guardian
        python_exe = sys.executable
        guardian_cmd = [
            python_exe,
            str(REPO_ROOT / "live_position_trailing_guardian.py"),
            "--contract", contract,
            "--security-id", sec_id,
            "--strike", strike,
            "--opt-type", opt_type,
            "--qty", str(qty),
            "--entry-price", str(fill_price),
            "--product", "M",
            "--sl-points", "3.5",
            "--order-no", order_no
        ]
        subprocess.Popen(guardian_cmd, cwd=str(REPO_ROOT))
        print(f"[GUARDIAN ACTIVE] Armed with ₹3.50 initial SL, breakeven ratchet, and wide trailing!")
        return True
    except Exception as e:
        print(f"[EXECUTION ERROR] {e}")
        return False

def run_autonomous_engine():
    print("=================================================================")
    print("=== AGI 1.7 OMEGA COMMAND — AUTONOMOUS AFTERNOON ALPHA ENGINE ===")
    print("=================================================================")
    print(f"Bullish Reclaim Trigger (CALL): Spot >= {BULLISH_CE_TRIGGER:.2f}")
    print(f"Bearish Breakdown Trigger (PUT): Spot <= {BEARISH_PE_TRIGGER:.2f}")
    print(f"Safety Mode: STRICT FAIL-CLOSED (Max Risk ₹227 per trade)")
    print("=================================================================\n")
    
    cooldown_until = 0
    last_had_position = False
    
    while True:
        try:
            now_dt = datetime.datetime.now()
            cur_time_str = now_dt.strftime("%H:%M:%S IST")
            
            # Hard EOD Shutdown
            if (now_dt.hour == 15 and now_dt.minute >= 15) or (now_dt.hour > 15):
                print(f"[{cur_time_str}] Market 15:15 IST reached. Autonomous engine completed for the day.")
                break
                
            # Check if a position is currently open
            has_open_pos = False
            if GUARDIAN_STATE_FILE.exists():
                try:
                    g_data = json.loads(GUARDIAN_STATE_FILE.read_text(encoding="utf-8"))
                    if g_data.get("qty", 0) > 0 and g_data.get("status") == "OPEN":
                        has_open_pos = True
                except Exception:
                    pass
                    
            # Position transition: When a position closes, apply a mandatory 180s cooldown
            if last_had_position and not has_open_pos:
                cooldown_until = time.time() + 180.0
                print(f"[{cur_time_str}] Position cleanly exited. 180-second market cooldown initiated.")
            last_had_position = has_open_pos
            
            spot = get_nifty_spot_from_cdp()
            if spot <= 0.0:
                spot = 22935.0 # fallback
                
            in_cooldown = time.time() < cooldown_until
            remaining_cd = max(0, int(cooldown_until - time.time()))
            
            dist_to_ce = BULLISH_CE_TRIGGER - spot
            dist_to_pe = spot - BEARISH_PE_TRIGGER
            
            status_desc = "ARMED_MONITORING"
            if has_open_pos:
                status_desc = "IN_POSITION_GUARDIAN_ACTIVE"
            elif in_cooldown:
                status_desc = f"COOLDOWN_ACTIVE_{remaining_cd}s"
            elif CHOP_LOWER_BOUND < spot < CHOP_UPPER_BOUND:
                status_desc = "PATIENT_CHOP_ZONE"
                
            engine_state = {
                "timestamp": cur_time_str,
                "nifty_spot": spot,
                "bullish_ce_trigger": BULLISH_CE_TRIGGER,
                "bearish_pe_trigger": BEARISH_PE_TRIGGER,
                "dist_to_bullish_pts": round(dist_to_ce, 2),
                "dist_to_bearish_pts": round(dist_to_pe, 2),
                "has_open_position": has_open_pos,
                "in_cooldown": in_cooldown,
                "cooldown_remaining_sec": remaining_cd,
                "status": status_desc,
                "ce_contract": "NIFTY 19 OCT 23050 CALL",
                "pe_contract": "NIFTY 19 OCT 22800 PUT",
                "risk_per_trade_inr": 227.50
            }
            STATE_FILE.write_text(json.dumps(engine_state, indent=2), encoding="utf-8")
            
            # Autonomous Trigger Check
            if not has_open_pos and not in_cooldown:
                if spot <= BEARISH_PE_TRIGGER:
                    print(f"[{cur_time_str}] Breakdown triggered! Executing PUT entry...")
                    success = execute_autonomous_order("PE", spot)
                    if not success:
                        cooldown_until = time.time() + 60.0
                elif spot >= BULLISH_CE_TRIGGER:
                    print(f"[{cur_time_str}] Reclaim triggered! Executing CALL entry...")
                    success = execute_autonomous_order("CE", spot)
                    if not success:
                        cooldown_until = time.time() + 60.0
                        
            time.sleep(3)
        except Exception as e:
            print(f"[ENGINE LOOP ERROR] {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_autonomous_engine()
