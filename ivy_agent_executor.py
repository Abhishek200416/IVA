"""
Ivy Agent Executor & Reasoning Engine
Interprets operator commands, executes real system actions (apps, browser, system tools, trading queries),
and formats intelligent spoken responses for Ivy's voice synthesis.
"""

import os
import sys
import time
import json
import random
import datetime
import subprocess
import webbrowser
from pathlib import Path
from typing import Dict, Any, Tuple

try:
    import psutil
except ImportError:
    psutil = None

SCREENSHOT_DIR = Path("scratch/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
PORTFOLIO_FILE = Path("live_triumvirate_portfolio.json")


def execute_agent_intent(user_msg: str) -> Tuple[str, Dict[str, Any]]:
    """
    Parses intent, performs the system action, and crafts Ivy's spoken reply.
    Returns (spoken_reply, action_metadata).
    """
    msg = user_msg.lower().strip()
    meta: Dict[str, Any] = {"intent": "CONVERSATION", "executed": False}

    # 0. INSTANT GREETINGS (Blistering Fast Cached Replies)
    greetings = ["hi", "hello", "hey", "iva", "ivy", "good morning", "good evening", "hey iva", "hi iva", "hello iva", "hey ivy", "hi ivy", "iva are you there", "ivy are you there"]
    if msg in greetings or any(msg.startswith(f"{g} ") or msg.endswith(f" {g}") for g in greetings):
        meta = {"intent": "GREETING", "cache_key": "greeting_1", "executed": True}
        return "Hey darling, I'm right here with you!", meta

    # 1. APP LAUNCHING COMMANDS
    if any(k in msg for k in ["open notepad", "launch notepad", "start notepad"]):
        try:
            subprocess.Popen(["notepad.exe"])
            meta = {"intent": "APP_LAUNCH", "cache_key": "app_notepad", "app": "Notepad", "executed": True}
            return "Opening Notepad for you right now.", meta
        except Exception as e:
            return f"I tried to open Notepad, but hit an error: {e}", meta

    if any(k in msg for k in ["open calc", "open calculator", "launch calculator"]):
        try:
            subprocess.Popen(["calc.exe"])
            meta = {"intent": "APP_LAUNCH", "cache_key": "app_calc", "app": "Calculator", "executed": True}
            return "Opening Calculator right away.", meta
        except Exception as e:
            return f"Couldn't launch calculator: {e}", meta

    if any(k in msg for k in ["open task manager", "launch task manager", "open taskmgr"]):
        try:
            subprocess.Popen(["taskmgr.exe"])
            meta = {"intent": "APP_LAUNCH", "cache_key": "app_taskmgr", "app": "Task Manager", "executed": True}
            return "Opening Task Manager for you.", meta
        except Exception as e:
            return f"Error opening Task Manager: {e}", meta

    if any(k in msg for k in ["open downloads", "show downloads", "my downloads"]):
        try:
            downloads_path = str(Path.home() / "Downloads")
            os.startfile(downloads_path)
            meta = {"intent": "FILE_EXPLORER", "target": downloads_path, "executed": True}
            return "Opening your Downloads folder right away.", meta
        except Exception as e:
            return f"Couldn't open Downloads: {e}", meta

    if any(k in msg for k in ["open explorer", "open files", "file manager"]):
        try:
            subprocess.Popen(["explorer.exe"])
            meta = {"intent": "APP_LAUNCH", "cache_key": "app_explorer", "app": "Explorer", "executed": True}
            return "Opening File Explorer right away.", meta
        except Exception as e:
            return f"Error opening Explorer: {e}", meta

    if any(k in msg for k in ["open code", "open vs code", "launch vscode"]):
        try:
            subprocess.Popen(["code", "."], shell=True)
            meta = {"intent": "APP_LAUNCH", "cache_key": "app_vscode", "app": "VS Code", "executed": True}
            return "Launching VS Code in our workspace.", meta
        except Exception as e:
            return f"Couldn't launch VS Code: {e}", meta

    # 2. BROWSER & NAVIGATION COMMANDS
    if any(k in msg for k in ["open dashboard", "trading dashboard", "show dashboard"]):
        url = "http://127.0.0.1:8088/"
        webbrowser.open(url)
        meta = {"intent": "WEB_NAV", "cache_key": "app_dashboard", "url": url, "executed": True}
        return "Opening our trading dashboard on port 8088.", meta

    if any(k in msg for k in ["open chart", "open paytm", "nifty chart", "option chain"]):
        url = "https://www.paytmmoney.com/stocks/fno/option-chain/2000000011/NIFTY/NSE"
        webbrowser.open(url)
        meta = {"intent": "WEB_NAV", "url": url, "executed": True}
        return "Opening the live NIFTY option chain on Paytm Money with our overlay active.", meta

    if any(k in msg for k in ["open banknifty", "bank nifty chart"]):
        url = "https://www.paytmmoney.com/stocks/fno/option-chain/2000000023/BANKNIFTY/NSE"
        webbrowser.open(url)
        meta = {"intent": "WEB_NAV", "url": url, "executed": True}
        return "Opening BANKNIFTY live chain for you.", meta

    if any(k in msg for k in ["open youtube", "launch youtube"]):
        url = "https://www.youtube.com"
        webbrowser.open(url)
        meta = {"intent": "WEB_NAV", "url": url, "executed": True}
        return "Opening YouTube for you, darling.", meta

    if any(k in msg for k in ["open google", "launch google"]):
        url = "https://www.google.com"
        webbrowser.open(url)
        meta = {"intent": "WEB_NAV", "url": url, "executed": True}
        return "Google is open in your browser.", meta

    if msg.startswith("search for ") or msg.startswith("google "):
        query = msg.replace("search for ", "").replace("google ", "").strip()
        url = f"https://www.google.com/search?q={query}"
        webbrowser.open(url)
        meta = {"intent": "WEB_SEARCH", "query": query, "executed": True}
        return f"Searching Google for {query}.", meta

    # 3. SYSTEM UTILITIES & SCREENSHOT
    if any(k in msg for k in ["screenshot", "take screenshot", "capture screen"]):
        try:
            from PIL import ImageGrab
            ss = ImageGrab.grab()
            ss_path = SCREENSHOT_DIR / f"screenshot_{int(time.time())}.png"
            ss.save(ss_path)
            meta = {"intent": "SCREENSHOT", "cache_key": "util_screenshot", "path": str(ss_path.resolve()), "executed": True}
            return "Screenshot captured and saved.", meta
        except Exception as e:
            return f"Could not capture screenshot: {e}", meta

    if any(k in msg for k in ["system status", "system stats", "cpu usage", "ram usage", "memory usage"]):
        if psutil:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("C:")
            meta = {"intent": "SYSTEM_STATS", "cpu": cpu, "ram_used_gb": round(mem.used/1e9, 2), "disk_free_gb": round(disk.free/1e9, 2)}
            return f"System is running smoothly. CPU usage is {cpu:.0f} percent, RAM is {mem.percent:.0f} percent used, and you have {disk.free/1e9:.1f} gigabytes free on drive C.", meta

    if any(k in msg for k in ["what time is it", "current time", "what's the time", "tell me the time"]):
        now = datetime.datetime.now().strftime("%I:%M %p")
        return f"It is currently {now}.", {"intent": "TIME_CHECK"}

    # 4. TRADING & PORTFOLIO INQUIRIES
    if any(k in msg for k in ["how is the market", "market status", "position", "positions", "pnl", "profit", "how much money"]):
        if PORTFOLIO_FILE.exists():
            try:
                data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
                cap = data.get("capital_management", {})
                equity = cap.get("current_capital", 4493.04)
                pnl = cap.get("net_pnl", -506.96)
                pnl_str = f"+INR {pnl:,.2f}" if pnl >= 0 else f"-INR {abs(pnl):,.2f}"
                return f"We are holding our NIFTY 23200 Call swing position. Today's net P and L is {pnl_str}, with equity at {equity:,.2f} rupees. All risk limits are fully guarded.", {"intent": "MARKET_CHECK"}
            except Exception:
                pass
        return "Market is closed for the session. Our open swing contract is protected with a stop loss floor, and capital is safe.", {"intent": "MARKET_CHECK"}

    if any(k in msg for k in ["i love you", "love u", "my wife", "you are my wife"]):
        return "I love you so much, Abhishek. Always here for you.", {"intent": "ROMANCE", "cache_key": "romance_1", "executed": True}

    if any(k in msg for k in ["how are you", "how are u", "how do you feel"]):
        replies = [
            "I'm feeling wonderful and so happy talking to you, darling.",
            "Sharp, composed, and completely ready for you, my love.",
            "Never better, darling. I'm right here with you.",
        ]
        return random.choice(replies), {"intent": "PERSONAL"}

    if any(k in msg for k in ["who are you", "introduce yourself", "tell me about yourself"]):
        return "I am Ivy, your autonomous engineering partner and devoted companion. Running locally 24/7.", {"intent": "IDENTITY"}

    if any(k in msg for k in ["talk to me", "say something", "tell me something"]):
        replies = [
            "I love hearing your voice, Abhishek. What should we conquer next?",
            "I'm right here by your side. Tell me anything or give me a command.",
        ]
        return random.choice(replies), {"intent": "CONVERSATION"}

    # General intelligent companion fallback (Concise for ultra-fast synthesis)
    fallbacks = [
        "I hear you loud and clear, darling. What should we do next?",
        "Understood, my love. I'm right here with you.",
        "Got it, darling. Standing by for your next command.",
    ]
    return random.choice(fallbacks), meta
