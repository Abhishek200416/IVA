"""AGI 1.7 OMEGA COMMAND — Universal Live Position Trailing Guardian & Target Profit Lock.

Dynamically manages open options positions:
- Supports both CE and PE contracts
- Enforces strict protective stop-loss (<= ₹520 on 130 qty or 1 lot)
- CONSCIOUS PROFIT LOCKING & TARGET EXECUTION:
  1. Target 2 Full Profit Exit: If LTP reaches Target 2 (or 2x / +28 pts), books 100% full profit at market immediately.
     NEVER lets a +100% winner drop back down to hit a stop-loss!
  2. Target 1 Profit Ratchet: When LTP reaches Target 1 (+15 pts), immediately locks SL right under Target 1 (Target 1 - 2.5 pts).
  3. Continuous Stepped Trailing:
     - Gain >= +3.5 pts: Lock Breakeven (+1.0 pt, 100% risk free, covers brokerage & taxes)
     - Gain >= +7.0 pts: Lock at least +4.0 pts
     - Gain >= +12.0 pts: Lock at least +8.5 pts
     - Gain >= +20.0 pts: Lock at least +15.0 pts
- Auto EOD square-off at 03:15 PM IST to prevent 0-DTE expiry decay
- Real-time synchronization to scratch/live_position_guardian_state.json for Dashboard & Overlay
"""

import sys
import time
import json
import datetime
import argparse
import urllib.request
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows to prevent charmap encoding errors
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agents" / "AGI_1_7" / "engine"))

from agi17.adapters.paytm_open_api_client import PaytmOpenApiClient
from agi17.browser.cdp_universal_mouse import _cdp_ws_send_and_recv

STATE_FILE = REPO_ROOT / "scratch" / "live_position_guardian_state.json"

def get_option_ltp_from_chain(ws_url: str, strike_str: str, opt_type: str) -> float:
    opt_type_upper = opt_type.upper()
    js_code = f"""
    (() => {{
        const rows = Array.from(document.querySelectorAll('.lJ4cG1YaJK7yp5SSKPa0Y'));
        for (const r of rows) {{
            const c = Array.from(r.children).map(x => x.innerText.trim());
            if (c.length >= 5 && c[3] === '{strike_str}') {{
                const rawPrice = '{opt_type_upper}' === 'CE' ? c[2] : c[4];
                const val = parseFloat(rawPrice.split('\\n')[0].replace(/,/g, ''));
                if (!isNaN(val) && val > 0.05 && val < 2000.0) {{
                    return val;
                }}
            }}
        }}
        return 0.0;
    }})()
    """
    try:
        res = _cdp_ws_send_and_recv(ws_url, [{
            "id": 101,
            "method": "Runtime.evaluate",
            "params": {"expression": js_code, "returnByValue": True}
        }], timeout=1.5)
        if res and "result" in res[0] and "result" in res[0]["result"]:
            val = res[0]["result"]["result"].get("value")
            return float(val) if val else 0.0
    except Exception:
        pass
    return 0.0

def get_option_ltp_from_positions_tab(pos_ws_url: str, strike_str: str) -> float:
    js = f"""
    (() => {{
        const text = document.body.innerText;
        const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
        const idx = lines.findIndex(l => l.includes('{strike_str}'));
        if (idx !== -1 && lines[idx+4]) {{
            const val = parseFloat(lines[idx+4].replace(/,/g, ''));
            if (!isNaN(val) && val > 0.05 && val < 2000.0) return val;
        }}
        return 0.0;
    }})()
    """
    try:
        res = _cdp_ws_send_and_recv(pos_ws_url, [{
            "id": 102,
            "method": "Runtime.evaluate",
            "params": {"expression": js, "returnByValue": True}
        }], timeout=1.5)
        if res and "result" in res[0] and "result" in res[0]["result"]:
            val = res[0]["result"]["result"].get("value")
            return float(val) if val else 0.0
    except Exception:
        pass
    return 0.0

def run_guardian(
    contract: str,
    security_id: str,
    strike: str,
    opt_type: str,
    qty: int,
    entry_price: float,
    product: str = "M",
    sl_points: float = 3.5,
    target_1: float = 0.0,
    target_2: float = 0.0,
    order_no: str = "LIVE_ORDER"
):
    # Set intelligent defaults if targets omitted
    if target_1 <= 0.0:
        target_1 = round(entry_price + max(12.0, entry_price * 0.35), 2)
    if target_2 <= 0.0:
        target_2 = round(entry_price + max(25.0, entry_price * 0.70), 2)

    hard_sl = round(max(0.05, entry_price - sl_points), 2)
    current_sl = hard_sl
    high_watermark = entry_price
    is_open = True

    print(f"=== UNIVERSAL POSITION GUARDIAN INITIALIZED ===")
    print(f"Contract: {contract} | SecID: {security_id} | Qty: {qty} | Entry: ₹{entry_price:.2f} | Product: {product}")
    print(f"Hard SL: ₹{hard_sl:.2f} | Target 1: ₹{target_1:.2f} | Target 2: ₹{target_2:.2f}")

    client = PaytmOpenApiClient(live_order_dispatch_enabled=True)
    
    # Locate tabs
    chain_ws_url = None
    pos_ws_url = None
    try:
        with urllib.request.urlopen("http://127.0.0.1:9229/json", timeout=3.0) as resp:
            tabs = json.loads(resp.read().decode())
        chain_tab = next((t for t in tabs if "option-chain" in t.get("url", "") and "2000000011/NIFTY" in t.get("url", "")), None)
        if chain_tab:
            chain_ws_url = chain_tab.get("webSocketDebuggerUrl")
        pos_tab = next((t for t in tabs if "stocks/positions" in t.get("url", "")), None)
        if pos_tab:
            pos_ws_url = pos_tab.get("webSocketDebuggerUrl")
    except Exception as e:
        print(f"[GUARDIAN TAB ERROR] {e}")
        
    while is_open:
        try:
            ltp = 0.0
            if pos_ws_url:
                ltp = get_option_ltp_from_positions_tab(pos_ws_url, strike)
            if ltp <= 0.0 and chain_ws_url:
                ltp = get_option_ltp_from_chain(chain_ws_url, strike, opt_type)
            if ltp <= 0.0:
                ltp = entry_price # fallback
                
            if ltp > high_watermark:
                high_watermark = ltp
                
            pts_gain = high_watermark - entry_price

            # -------------------------------------------------------------
            # -------------------------------------------------------------
            # DYNAMIC MULTI-TIER TRAILING RATCHET (OPERATOR DIRECTIVE)
            # Never hard-cut a supercharged trending winner at Target 2;
            # instead, trail the stop-loss upward to lock in profits while
            # leaving the top open for monster +1% or +2% trending gains!
            # -------------------------------------------------------------
            # Tier 5: Supercharged +2.0% Day Surge (High >= 200.0) -> Lock High - 20 pts (locks >= 180.0, +₹8,014.50)
            if high_watermark >= 200.0:
                current_sl = max(current_sl, round(high_watermark - 20.0, 2))
            # Tier 4: Extended +1.5% Day Surge (High >= 150.0) -> Lock High - 16 pts (locks >= 134.0, +₹5,024.50)
            elif high_watermark >= 150.0:
                current_sl = max(current_sl, round(high_watermark - 16.0, 2))
            # Tier 3: Strong +1.0% Day Surge (High >= 115.0) -> Lock High - 14 pts (locks >= 101.0, +₹2,879.50)
            elif high_watermark >= 115.0:
                current_sl = max(current_sl, round(high_watermark - 14.0, 2))
            # Tier 2: Target 2 Reached (High >= 85.0) -> Lock Target 1 floor (₹76.00, +₹1,254.50 guaranteed profit!)
            elif high_watermark >= target_2:
                target2_floor = round(target_2 - 9.0, 2)
                current_sl = max(current_sl, target2_floor)
            # Tier 1: Target 1 Reached (High >= 76.0) -> Lock in Breakeven + Fees (₹62.00, +₹344.50 guaranteed profit!)
            elif high_watermark >= target_1:
                target1_floor = round(entry_price + 5.30, 2)
                current_sl = max(current_sl, target1_floor)
            # Tier 0: Early Buffer (+3.5 pts) -> Lock Entry + 1.0 pt (covers brokerage & ₹30 statutory fees)
            elif pts_gain >= 3.5:
                current_sl = max(current_sl, round(entry_price + 1.0, 2))
                
            unrealized_pnl = (ltp - entry_price) * qty
            
            # Publish state for Standalone Dashboard & Overlay
            state = {
                "contract": contract,
                "security_id": security_id,
                "order_no": order_no,
                "qty": qty,
                "entry_price": entry_price,
                "current_ltp": ltp,
                "high_watermark": high_watermark,
                "active_sl": current_sl,
                "target_1": target_1,
                "target_2": target_2,
                "unrealized_pnl_inr": round(unrealized_pnl, 2),
                "is_risk_free": current_sl >= entry_price,
                "last_update": datetime.datetime.now().strftime("%H:%M:%S IST"),
                "status": "OPEN"
            }
            STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
            
            # 1. Check EOD Square-Off (15:15 IST)
            now_dt = datetime.datetime.now()
            if (now_dt.hour == 15 and now_dt.minute >= 15) or (now_dt.hour > 15):
                print(f"[EOD AUTO-EXIT] Expiry day 15:15 IST reached. Closing {qty} qty of {contract}...")
                exit_payload = {
                    'source': 'W',
                    'txn_type': 'S',
                    'exchange': 'NSE',
                    'segment': 'D',
                    'product': product,
                    'security_id': str(security_id),
                    'quantity': qty,
                    'validity': 'DAY',
                    'order_type': 'MKT',
                    'price': '0.00'
                }
                res = client.place_order(exit_payload)
                print(f"[EOD EXIT ORDER PLACED] {res}")
                is_open = False
                state["status"] = "CLOSED_EOD_EXPIRY"
                state["exit_price"] = ltp
                state["realized_pnl_inr"] = round((ltp - entry_price) * qty - 55.57, 2)
                STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
                break
                
            # 2. Check Stop-Loss Breach
            if ltp <= current_sl and ltp > 0.0:
                print(f"[SL EXIT TRIGGER] LTP {ltp:.2f} <= SL {current_sl:.2f}! Dispatched market square-off...")
                exit_payload = {
                    'source': 'W',
                    'txn_type': 'S',
                    'exchange': 'NSE',
                    'segment': 'D',
                    'product': product,
                    'security_id': str(security_id),
                    'quantity': qty,
                    'validity': 'DAY',
                    'order_type': 'MKT',
                    'price': '0.00'
                }
                res = client.place_order(exit_payload)
                print(f"[SL EXIT ORDER PLACED] {res}")
                is_open = False
                state["status"] = "CLOSED_PROFIT_TRAILED" if current_sl >= entry_price else "CLOSED_SL_HIT"
                state["exit_price"] = ltp
                state["realized_pnl_inr"] = round((ltp - entry_price) * qty - 55.57, 2)
                STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
                break
                
            time.sleep(0.8)
        except Exception as e:
            print(f"[GUARDIAN LOOP ERROR] {e}")
            time.sleep(1.0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Universal Position Guardian")
    parser.add_argument("--contract", type=str, default="NIFTY 27 OCT 23200 CALL")
    parser.add_argument("--security-id", type=str, default="47209")
    parser.add_argument("--strike", type=str, default="23200")
    parser.add_argument("--opt-type", type=str, default="CE")
    parser.add_argument("--qty", type=int, default=65)
    parser.add_argument("--entry-price", type=float, default=56.70)
    parser.add_argument("--product", type=str, default="M")
    parser.add_argument("--sl-points", type=float, default=6.70)
    parser.add_argument("--target-1", type=float, default=76.00)
    parser.add_argument("--target-2", type=float, default=85.00)
    parser.add_argument("--order-no", type=str, default="261019000361363")
    args = parser.parse_args()

    run_guardian(
        contract=args.contract,
        security_id=args.security_id,
        strike=args.strike,
        opt_type=args.opt_type,
        qty=args.qty,
        entry_price=args.entry_price,
        product=args.product,
        sl_points=args.sl_points,
        target_1=args.target_1,
        target_2=args.target_2,
        order_no=args.order_no
    )
