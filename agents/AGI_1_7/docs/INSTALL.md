# AGI 1.7 OMEGA COMMAND — Installation & Setup Guide

## Overview

AGI 1.7 OMEGA COMMAND is an autonomous quantitative trading research, risk modeling, and transparent visible-browser execution system for Indian indices (**NIFTY 50** and **BANK NIFTY**).

### Security Invariants & Safe Defaults
1. **Default Mode is strictly PAPER / ANALYSIS ONLY**: A fresh installation will never execute live financial transactions or touch real capital.
2. **Zero Hardcoded Credentials**: Broker passwords, PINs, OTPs, session cookies, and JWTs are never saved to disk or repository commits.
3. **Visible Desktop Execution**: All browser interactions occur through a genuine visible Chrome window on `WinSta0\Default`. Headless execution and synthetic DOM scripts are prohibited for order placement.
4. **Mandatory Live Arming Gate**: Transitioning to live brokerage requires passing all 13 readiness gates, explicit user signature (`GO REAL`), independent capital allocation, and broker regulatory verification.

---

## 1. System Requirements

- **Operating System:** Windows 10 / 11 (64-bit) with interactive desktop (`WinSta0\Default`)
- **Python Version:** Python 3.10, 3.11, 3.12, or 3.14
- **Browser:** Google Chrome (or Chrome for Testing) with Remote Debugging Port (`--remote-debugging-port=9229`)
- **Storage:** Local NTFS drive (Default: `D:\AGI_Storage\AGI_1_7` or auto-fallback to `./agents/AGI_1_7/runtime_storage`)

---

## 2. Installation Steps

### Step 1: Clone Repository & Create Virtual Environment
```powershell
git clone <repository_url>
cd pt
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Step 2: Install Package in Editable Mode
```powershell
pip install -e .
```

### Step 3: Copy Configuration Template
```powershell
Copy-Item agents/AGI_1_7/config/config.template.yaml config.yaml
```

---

## 3. Launching the System

### A. Launch Paper Trading Research (Default)
To launch the 24/7 autonomous paper trading supervisor, global risk radar, and quantitative engine:
```powershell
python agents/AGI_1_7/run_agi_17.py trading
```

### B. Launch Standalone Control Dashboard
To open the independent web telemetry dashboard (running outside any IDE):
```powershell
python -c "from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer; s = StandaloneDashboardServer(port=8088); s.serve_forever()"
```
Then navigate to: `http://127.0.0.1:8088/` in your browser.

### C. Launching Visible Paytm Money Browser
To start the dedicated visible browser for interactive session authentication:
```powershell
python agents/AGI_1_7/engine/agi17/browser/launch_visible_paytm.py
```
Log in manually using your own 2FA credentials. The system never intercepts or stores your master credentials.

---

## 4. Operational Gating & Safety

- **Intraday vs Overnight**: Positions are intraday by default with mandatory square-off before 15:15 IST. Overnight positions require separate scenario evaluation and explicit `allow_overnight=True`.
- **Circuit Breakers**: Daily loss is strictly capped at 1.5% of starting capital. Once triggered, the session automatically locks out new entries.
- **Emergency Stop**: Instant manual halt available via CLI or dashboard `/api/emergency_stop`. All open positions are catalogued and new order placement is blocked.
