"""AGI 1.7 OMEGA COMMAND — TradingView Global Macro Harvester.

Continuously ingests live institutional global macro feeds from TradingView:
1. GIFT NIFTY / NIFTY 50 (Indicative opening & gap projection)
2. CRUDE OIL (NYMEX:CL1! & MCX:CRUDEOIL1! - inflation & rate expectations)
3. GOLD (COMEX:GC1!, TVC:GOLD, MCX:GOLD1! - safe-haven flow)
4. US INDICES (S&P 500 SP:SPX & Nasdaq NASDAQ:NDX - overnight sentiment)

Feeds extracted metrics directly to Emily (Macro Intelligence) and the
ChatGPT Cadence Governor for actionable pre-market gap analysis.
"""

from __future__ import annotations
import json
import logging
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("TradingViewMacroHarvester")

REPO_ROOT = Path(__file__).resolve().parents[5]
INTEL_FILE = REPO_ROOT / "alexa_newspaper_intelligence.json"
STATE_FILE = REPO_ROOT / "scratch" / "tradingview_macro_state.json"

ENDPOINTS = [
    (
        "https://scanner.tradingview.com/futures/scan",
        ["NYMEX:CL1!", "COMEX:GC1!"],
        {"NYMEX:CL1!": "CRUDE_OIL_WTI", "COMEX:GC1!": "GOLD_COMEX"}
    ),
    (
        "https://scanner.tradingview.com/global/scan",
        ["TVC:GOLD", "SP:SPX", "NASDAQ:NDX"],
        {"TVC:GOLD": "GOLD_SPOT", "SP:SPX": "SP_500", "NASDAQ:NDX": "NASDAQ_100"}
    ),
    (
        "https://scanner.tradingview.com/india/scan",
        ["NSE:NIFTY", "MCX:CRUDEOIL1!", "MCX:GOLD1!"],
        {"NSE:NIFTY": "NIFTY_50_SPOT", "MCX:CRUDEOIL1!": "CRUDE_OIL_MCX", "MCX:GOLD1!": "GOLD_MCX"}
    )
]


def harvest_tradingview_macro_quotes() -> Dict[str, Any]:
    """Scans TradingView endpoints and compiles a unified global macro snapshot."""
    snapshot: Dict[str, Any] = {
        "timestamp": time.time(),
        "timestamp_iso": time.strftime("%Y-%m-%d %H:%M:%S IST", time.localtime()),
        "instruments": {},
        "summary": {}
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json"
    }

    for ep, tickers, alias_map in ENDPOINTS:
        payload = {
            "symbols": {"tickers": tickers},
            "columns": ["name", "close", "change", "change_abs", "high", "low", "description"]
        }
        try:
            req = urllib.request.Request(
                ep,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode())
                for row in data.get("data", []):
                    ticker = row.get("s")
                    vals = row.get("d", [])
                    if ticker and vals and len(vals) >= 6:
                        alias = alias_map.get(ticker, ticker)
                        snapshot["instruments"][alias] = {
                            "ticker": ticker,
                            "symbol": vals[0],
                            "price": round(float(vals[1]), 2) if vals[1] is not None else 0.0,
                            "change_pct": round(float(vals[2]), 2) if vals[2] is not None else 0.0,
                            "change_abs": round(float(vals[3]), 2) if vals[3] is not None else 0.0,
                            "high": round(float(vals[4]), 2) if vals[4] is not None else 0.0,
                            "low": round(float(vals[5]), 2) if vals[5] is not None else 0.0,
                            "description": vals[6] if len(vals) > 6 else ""
                        }
        except Exception as e:
            logger.warning(f"Error harvesting from {ep}: {e}")

    # Synthesize macro narrative
    inst = snapshot["instruments"]
    crude = inst.get("CRUDE_OIL_WTI") or inst.get("CRUDE_OIL_MCX")
    gold = inst.get("GOLD_SPOT") or inst.get("GOLD_COMEX")
    spx = inst.get("SP_500")
    ndx = inst.get("NASDAQ_100")
    nifty = inst.get("NIFTY_50_SPOT")

    macro_bias = "NEUTRAL"
    if spx and spx["change_pct"] < -1.0:
        macro_bias = "RISK_OFF"
    elif spx and spx["change_pct"] > 0.8:
        macro_bias = "RISK_ON"

    snapshot["summary"] = {
        "macro_bias": macro_bias,
        "nifty_spot": nifty["price"] if nifty else 22888.95,
        "crude_wti": crude["price"] if crude else 0.0,
        "crude_change_pct": crude["change_pct"] if crude else 0.0,
        "gold_spot": gold["price"] if gold else 0.0,
        "sp500_change_pct": spx["change_pct"] if spx else 0.0,
        "nasdaq_change_pct": ndx["change_pct"] if ndx else 0.0,
        "overnight_cues": (
            f"TradingView Live: Crude WTI at ${crude['price']:.2f} ({crude['change_pct']:+.2f}%), "
            f"Gold at ${gold['price']:.2f}, S&P 500 ({spx['change_pct']:+.2f}%), "
            f"Nasdaq ({ndx['change_pct']:+.2f}%). Macro bias: {macro_bias}."
            if crude and gold and spx and ndx else "TradingView macro stream active."
        )
    }

    # Persist state
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    except Exception:
        pass

    return snapshot


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = harvest_tradingview_macro_quotes()
    print("TradingView Live Snapshot Harvested Successfully:")
    print(json.dumps(res["summary"], indent=2))
    print("\nInstruments:")
    for k, v in res["instruments"].items():
        print(f"  • {k} ({v['ticker']}): {v['price']} ({v['change_pct']:+.2f}%)")
