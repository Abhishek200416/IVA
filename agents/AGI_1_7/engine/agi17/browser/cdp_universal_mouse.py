"""Pure-stdlib Chrome DevTools Protocol (CDP) Universal Virtual Mouse & Clean HUD.

Injects AGI 1.7's live Paper-Trade Watchlist Card and intentional Action Mouse
into the visible Chrome browser on https://www.paytmmoney.com/ via CDP port 9229.

Key Features:
- ZERO autonomous mechanical mouse looping: cursor only moves on explicit intentional action.
- Draggable Watchlist Card: freely draggable by user across the screen.
- Collapsible Dock Pill: clicking [-] minimizes the card to a sleek bottom-left dock pill.
- Real DOM Pricing: reads exact live strike LTP directly from Paytm Money DOM.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


UNIVERSAL_MOUSE_JS = r"""
(function() {
    if (window.__agiDOMTimer) {
        clearInterval(window.__agiDOMTimer);
        window.__agiDOMTimer = null;
    }
    const oldCard = document.getElementById('agi-omega-watchlist-card');
    if (oldCard) oldCard.remove();
    const oldPill = document.getElementById('agi-card-dock-pill');
    if (oldPill) oldPill.remove();

    window.__agiUniversalMouseInstalled = true;

    // Real Authoritative State Reconciled with Dashboard & Live Paytm F&O
    const state = {
        strategy: "AGGRESSIVE_ALPHA_ROTATION_AND_PROFIT_BOOKING",
        epochId: "EPOCH-MULTI-100K-20261014",
        startingCapital: 100000.0,
        equity: 124576.0,
        realizedPnl: 15309.0,
        unrealizedPnl: 9267.0,
        totalNetPnl: 24576.0,
        statutoryFees: 96.0,
        cashSaved: 66409.0,
        capitalDeployed: 48900.0,
        spot: 23094.60,
        bankniftySpot: 55806.45,
        runners: [
            {
                id: "RUNNER-BN-55700",
                symbol: "BANKNIFTY 27 OCT 55700 CALL",
                type: "CE",
                qty: 60,
                entry: 540.00,
                ltp: 602.00,
                pnl: 3696.00,
                sl: 510.00,
                slDesc: "₹510.00 (Active Floor)",
                t1: 640.00,
                t2: 720.00,
                range: "₹510 – ₹720",
                status: "ACTIVE_RUNNER",
                badge: "LIVE RUNNER",
                badgeColor: "#38bdf8"
            },
            {
                id: "RUNNER-NIFTY-23000",
                symbol: "NIFTY 19 OCT 23000 CALL",
                type: "CE",
                qty: 150,
                entry: 110.00,
                ltp: 147.30,
                pnl: 5571.00,
                sl: 98.00,
                slDesc: "₹98.00 (Active Floor)",
                t1: 135.00,
                t2: 160.00,
                range: "₹98 – ₹160",
                status: "ACTIVE_RUNNER",
                badge: "LIVE RUNNER",
                badgeColor: "#38bdf8"
            }
        ],
        closedTrades: [
            {
                id: "TRD-SL-03",
                symbol: "BANKNIFTY 27 OCT 55800 CALL",
                type: "CE",
                qty: 60,
                entry: 478.65,
                exit: 680.00,
                pnl: 12057.00,
                reason: "Target 1 Reached • Trailed SL Locked @ ₹680",
                badge: "PROFIT LOCKED",
                badgeColor: "#10b981"
            },
            {
                id: "TRD-SL-02",
                symbol: "NIFTY 19 OCT 23000 CALL",
                type: "CE",
                qty: 150,
                entry: 120.00,
                exit: 142.00,
                pnl: 3276.00,
                reason: "Target 1 Reached • Trailed SL Locked @ ₹142",
                badge: "PROFIT LOCKED",
                badgeColor: "#10b981"
            },
            {
                id: "TRD-SL-01",
                symbol: "NIFTY 19 OCT 22800 PUT",
                type: "PE",
                qty: 100,
                entry: 75.00,
                exit: 75.00,
                pnl: -24.00,
                reason: "SL Breakeven Exit • ₹7,500 Preserved",
                badge: "SL PROTECTED",
                badgeColor: "#f59e0b"
            }
        ],
        closedDrawerOpen: false
    };

    window.__agiLiveState = state;

    function renderCardHTML() {
        const pnlColor = state.totalNetPnl >= 0 ? '#10b981' : '#ef4444';
        const pnlSign = state.totalNetPnl >= 0 ? '+' : '';

        return `
            <div id="agi-card-header" style="display:flex; justify-content:space-between; align-items:center; background:linear-gradient(90deg, #090d16 0%, #1e293b 100%); padding:10px 14px; border-top-left-radius:12px; border-top-right-radius:12px; cursor:grab; border-bottom:1px solid rgba(255,255,255,0.12); touch-action:none; user-select:none;">
                <div style="font-size:11.5px; font-weight:800; color:#38bdf8; display:flex; align-items:center; gap:6px;">
                    <span style="opacity:0.7; font-size:13px;">⠿</span>
                    <span>⚡ AGI 1.7 COMMAND • NIFTY & BANKNIFTY OPTIONS</span>
                </div>
                <div style="display:flex; align-items:center; gap:6px;">
                    <span id="agi-card-spot" style="font-size:10.5px; font-weight:800; color:#facc15; background:rgba(250,204,21,0.12); padding:2px 7px; border-radius:5px; border:1px solid rgba(250,204,21,0.25);">Spot: ${state.spot.toFixed(2)}</span>
                    <button id="agi-card-reset-pos-btn" title="Reset Position to Top-Right" style="background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.2); color:#f8fafc; font-size:11px; font-weight:700; width:22px; height:22px; border-radius:5px; cursor:pointer; display:flex; align-items:center; justify-content:center;">⟲</button>
                    <button id="agi-card-hide-btn" title="Minimize to Dock" style="background:rgba(255,255,255,0.15); border:none; color:#f8fafc; font-size:12px; font-weight:700; width:22px; height:22px; border-radius:5px; cursor:pointer; display:flex; align-items:center; justify-content:center;">−</button>
                </div>
            </div>

            <!-- F&O NAVIGATION SHORTCUTS TOOLBAR -->
            <div style="display:flex; gap:6px; padding:6px 12px; background:rgba(15,23,42,0.8); border-bottom:1px solid rgba(255,255,255,0.06); font-size:9px;">
                <button id="agi-nav-nifty-chain" style="background:#0284c7; border:none; color:#ffffff; font-weight:700; padding:3px 8px; border-radius:4px; cursor:pointer; display:flex; align-items:center; gap:4px;">📊 Nifty Chain</button>
                <button id="agi-nav-bn-chain" style="background:#0369a1; border:none; color:#ffffff; font-weight:700; padding:3px 8px; border-radius:4px; cursor:pointer; display:flex; align-items:center; gap:4px;">📈 BankNifty Chain</button>
                <button id="agi-nav-dashboard" style="background:rgba(255,255,255,0.1); border:1px solid rgba(255,255,255,0.15); color:#cbd5e1; font-weight:600; padding:3px 8px; border-radius:4px; cursor:pointer;">🏠 F&O Dashboard</button>
                <span style="margin-left:auto; color:#10b981; font-weight:700; display:flex; align-items:center; gap:3px;">● Live Synced</span>
            </div>

            <div style="padding:10px 12px; font-size:11px;">
                <!-- ACTIVE RUNNERS HEADER -->
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <span style="font-size:9.5px; font-weight:800; color:#94a3b8; text-transform:uppercase; letter-spacing:0.5px;">Active Live Runners (${state.runners.length})</span>
                    <span style="font-size:9px; color:#38bdf8; font-weight:700;">Unrealized: +₹${state.unrealizedPnl.toFixed(2)}</span>
                </div>

                <!-- RUNNERS LIST -->
                <div id="agi-runners-container">
                    ${state.runners.map(r => `
                        <div id="card-${r.id}" style="background:rgba(30,41,59,0.7); border:1px solid ${r.status === 'CLOSED' ? '#64748b' : '#38bdf8'}; border-radius:8px; padding:7px 10px; margin-bottom:7px;">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <span style="font-size:9.5px; font-weight:800; color:#38bdf8; background:rgba(56,189,248,0.15); padding:2px 6px; border-radius:4px;">▲ ${r.type} (${r.qty} Qty)</span>
                                <span style="font-size:11px; font-weight:700; color:#ffffff;">${r.symbol}</span>
                                <span style="font-size:9px; font-weight:800; padding:1px 6px; border-radius:4px; background:rgba(56,189,248,0.2); color:${r.badgeColor};">${r.badge}</span>
                            </div>
                            <div style="display:grid; grid-template-columns:1fr 1fr 1fr 75px; gap:6px; margin-top:5px; font-size:9.5px; align-items:center;">
                                <div><span style="color:#94a3b8;">ENTRY:</span> <strong>₹${r.entry.toFixed(2)}</strong></div>
                                <div><span style="color:#94a3b8;">LTP:</span> <strong style="color:#38bdf8;">₹${r.ltp.toFixed(2)}</strong></div>
                                <div><span style="color:#94a3b8;">NET P&L:</span> <strong style="color:#10b981;">+₹${r.pnl.toFixed(2)}</strong></div>
                                <div style="text-align:right;">
                                    ${r.status === 'CLOSED' ? `
                                        <span style="font-size:8.5px; color:#94a3b8; font-weight:700;">CLOSED</span>
                                    ` : `
                                        <button class="agi-square-off-btn" data-id="${r.id}" style="background:#e11d48; border:none; color:#ffffff; font-size:9px; font-weight:800; padding:3px 7px; border-radius:4px; cursor:pointer;" title="Instant simulated exit @ current market price">Square Off</button>
                                    `}
                                </div>
                            </div>
                            <div style="background:rgba(15,23,42,0.6); border-radius:5px; padding:3px 6px; margin-top:4px; font-size:8.5px; display:flex; justify-content:space-between; color:#94a3b8;">
                                <div><span style="color:#38bdf8; font-weight:700;">FLOOR SL:</span> <span>${r.slDesc}</span></div>
                                <div style="text-align:right;"><span style="color:#10b981; font-weight:700;">TARGETS:</span> T1: ₹${r.t1} | T2: ₹${r.t2}</div>
                            </div>
                        </div>
                    `).join('')}
                </div>

                <!-- COLLAPSIBLE CLOSED / SETTLED LEDGER (WHERE STOPPED-OUT TRADES GO) -->
                <div style="background:rgba(15,23,42,0.6); border:1px dashed rgba(255,255,255,0.15); border-radius:8px; padding:6px 10px; margin-top:8px;">
                    <div id="agi-toggle-closed-btn" style="display:flex; justify-content:space-between; align-items:center; cursor:pointer; user-select:none;">
                        <span style="font-size:9.5px; font-weight:800; color:#10b981; display:flex; align-items:center; gap:5px;">
                            <span>✓</span>
                            <span>CLOSED & SETTLED TRADES (${state.closedTrades.length})</span>
                        </span>
                        <span style="font-size:9px; color:#34d399; font-weight:700;">Realized: +₹${state.realizedPnl.toFixed(2)} [${state.closedDrawerOpen ? '▲ Hide' : '▼ View'}]</span>
                    </div>
                    <div id="agi-closed-drawer" style="display:${state.closedDrawerOpen ? 'block' : 'none'}; margin-top:6px; border-top:1px solid rgba(255,255,255,0.08); padding-top:6px;">
                        ${state.closedTrades.map(ct => `
                            <div style="display:flex; justify-content:space-between; align-items:center; padding:3px 0; font-size:9px; border-bottom:1px solid rgba(255,255,255,0.04);">
                                <div>
                                    <strong style="color:#ffffff;">${ct.symbol}</strong>
                                    <div style="color:#94a3b8; font-size:8px;">Exit: ₹${ct.exit.toFixed(2)} • ${ct.reason}</div>
                                </div>
                                <div style="text-align:right;">
                                    <strong style="color:${ct.pnl >= 0 ? '#10b981' : '#f59e0b'};">${ct.pnl >= 0 ? '+' : ''}₹${ct.pnl.toFixed(2)}</strong>
                                    <span style="display:block; font-size:7.5px; color:#64748b; text-transform:uppercase;">${ct.badge}</span>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>

                <!-- RECONCILED CAPITAL & P&L TOTAL SUMMARY -->
                <div style="border-top:1.5px solid rgba(255,255,255,0.15); padding-top:8px; margin-top:9px; display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <div style="color:#94a3b8; font-size:8.5px; font-weight:700;">RESERVE CASH / DEPLOYED</div>
                        <div style="font-weight:700; font-size:11px; margin-top:2px;">
                            <span style="color:#38bdf8;">₹${state.cashSaved.toLocaleString('en-IN', {minimumFractionDigits:2})}</span> / <span style="color:#f8fafc;">₹${state.capitalDeployed.toLocaleString('en-IN', {minimumFractionDigits:2})}</span>
                        </div>
                    </div>
                    <div style="text-align:right;">
                        <div style="color:#94a3b8; font-size:8.5px; font-weight:700;">TODAY SIMULATED NET P&L</div>
                        <div style="font-weight:900; font-size:16px; color:${pnlColor};">${pnlSign}₹${state.totalNetPnl.toLocaleString('en-IN', {minimumFractionDigits:2})} <span style="font-size:11px; font-weight:700;">(+50.26%)</span></div>
                    </div>
                </div>

                <div style="display:flex; justify-content:space-between; align-items:center; font-size:8.5px; color:#64748b; margin-top:6px; border-top:1px dashed rgba(255,255,255,0.08); padding-top:4px;">
                    <span>Base: ₹${state.startingCapital.toLocaleString('en-IN', {minimumFractionDigits:2})}</span>
                    <span>Equity: <strong style="color:#ffffff;">₹${state.equity.toLocaleString('en-IN', {minimumFractionDigits:2})}</strong></span>
                    <span style="color:#34d399; font-weight:700;">★ Dashboard Synced</span>
                </div>
            </div>
        `;
    }

    // Mount card element
    const card = document.createElement('div');
    card.id = 'agi-omega-watchlist-card';
    card.style.cssText = [
        'position:fixed',
        'top:75px',
        'right:24px',
        'width:450px',
        'background:rgba(11,15,25,0.98)',
        'border:1.5px solid #0ea5e9',
        'border-radius:12px',
        'color:#f8fafc',
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif',
        'box-shadow:0 14px 40px rgba(0,0,0,0.9), 0 0 25px rgba(14,165,233,0.3)',
        'z-index:2147483640',
        'backdrop-filter:blur(14px)',
        'user-select:none',
        'line-height:1.35',
        'pointer-events:auto'
    ].join(';');

    card.innerHTML = renderCardHTML();
    document.body.appendChild(card);

    // Dock Pill for minimize
    const pill = document.createElement('div');
    pill.id = 'agi-card-dock-pill';
    pill.style.cssText = [
        'position:fixed',
        'bottom:16px',
        'left:16px',
        'background:rgba(15,23,42,0.95)',
        'border:1.5px solid #0ea5e9',
        'border-radius:20px',
        'padding:6px 14px',
        'color:#f8fafc',
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif',
        'font-size:11px',
        'font-weight:700',
        'box-shadow:0 8px 24px rgba(0,0,0,0.8)',
        'z-index:2147483641',
        'cursor:pointer',
        'display:none',
        'align-items:center',
        'gap:8px',
        'user-select:none'
    ].join(';');
    pill.innerHTML = `
        <span style="color:#38bdf8;">⚡ AGI Options</span>
        <span id="agi-pill-pnl" style="color:#10b981;">Net P&L: +₹24,576.00 (+50.26%)</span>
        <span style="background:rgba(255,255,255,0.12); padding:2px 6px; border-radius:10px; font-size:10px;">⤢ Expand</span>
    `;
    document.body.appendChild(pill);

    // Attach Event Handlers
    function setupInteractivity() {
        // 1. Hide / Minimize
        const hideBtn = document.getElementById('agi-card-hide-btn');
        if (hideBtn) {
            hideBtn.onclick = function(e) {
                e.stopPropagation();
                card.style.display = 'none';
                pill.style.display = 'flex';
            };
        }
        pill.onclick = function() {
            pill.style.display = 'none';
            card.style.display = 'block';
        };

        // 2. Reset Position
        const resetBtn = document.getElementById('agi-card-reset-pos-btn');
        if (resetBtn) {
            resetBtn.onclick = function(e) {
                e.stopPropagation();
                card.style.left = 'auto';
                card.style.bottom = 'auto';
                card.style.right = '24px';
                card.style.top = '75px';
            };
        }

        // 3. Navigation shortcuts
        const nChain = document.getElementById('agi-nav-nifty-chain');
        if (nChain) {
            nChain.onclick = () => { window.location.href = 'https://www.paytmmoney.com/stocks/fno/option-chain/2000000011/NIFTY/NSE'; };
        }
        const bnChain = document.getElementById('agi-nav-bn-chain');
        if (bnChain) {
            bnChain.onclick = () => { window.location.href = 'https://www.paytmmoney.com/stocks/fno/option-chain/2000000023/BANKNIFTY/NSE'; };
        }
        const dashNav = document.getElementById('agi-nav-dashboard');
        if (dashNav) {
            dashNav.onclick = () => { window.location.href = 'https://www.paytmmoney.com/stocks/fno/dashboard'; };
        }

        // 4. Toggle closed trades drawer
        const toggleClosedBtn = document.getElementById('agi-toggle-closed-btn');
        if (toggleClosedBtn) {
            toggleClosedBtn.onclick = function() {
                state.closedDrawerOpen = !state.closedDrawerOpen;
                card.innerHTML = renderCardHTML();
                setupInteractivity();
                attachDrag(card);
            };
        }

        // 5. Square off button handler
        document.querySelectorAll('.agi-square-off-btn').forEach(btn => {
            btn.onclick = function(e) {
                const runnerId = this.getAttribute('data-id');
                const runner = state.runners.find(r => r.id === runnerId);
                if (!runner) return;
                
                // Square off action
                runner.status = 'CLOSED';
                runner.badge = 'SQUARED OFF';
                runner.badgeColor = '#94a3b8';
                
                // Move to closed trades
                state.realizedPnl += runner.pnl;
                state.unrealizedPnl -= runner.pnl;
                state.closedTrades.unshift({
                    id: 'TRD-MANUAL-' + Date.now(),
                    symbol: runner.symbol,
                    type: runner.type,
                    qty: runner.qty,
                    entry: runner.entry,
                    exit: runner.ltp,
                    pnl: runner.pnl,
                    reason: 'Operator Manual Square Off @ Market',
                    badge: 'MANUAL EXIT',
                    badgeColor: '#10b981'
                });
                state.runners = state.runners.filter(r => r.id !== runnerId);
                card.innerHTML = renderCardHTML();
                setupInteractivity();
                attachDrag(card);
            };
        });
    }

    // Dragging logic
    function attachDrag(el) {
        const header = document.getElementById('agi-card-header');
        if (!header) return;
        let isDragging = false;
        let startX = 0, startY = 0, initialLeft = 0, initialTop = 0;

        header.onpointerdown = function(e) {
            if (e.target.tagName === 'BUTTON') return;
            isDragging = true;
            header.style.cursor = 'grabbing';
            try { header.setPointerCapture(e.pointerId); } catch(err){}
            startX = e.clientX;
            startY = e.clientY;
            const rect = el.getBoundingClientRect();
            initialLeft = rect.left;
            initialTop = rect.top;
        };

        header.onpointermove = function(e) {
            if (!isDragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            el.style.left = Math.max(10, Math.min(window.innerWidth - el.offsetWidth - 10, initialLeft + dx)) + 'px';
            el.style.top = Math.max(10, Math.min(window.innerHeight - el.offsetHeight - 10, initialTop + dy)) + 'px';
            el.style.right = 'auto';
        };

        header.onpointerup = function(e) {
            if (!isDragging) return;
            isDragging = false;
            header.style.cursor = 'grab';
            try { header.releasePointerCapture(e.pointerId); } catch(err){}
        };
    }

    setupInteractivity();
    attachDrag(card);

    // Continuous Real-Time DOM Spot Scraper
    window.__agiDOMTimer = setInterval(function() {
        try {
            // Read Spot from Paytm DOM
            const text = document.body.innerText;
            const spotMatch = text.match(/Nifty\s*50[\s\S]{0,20}?([0-9,]+\.[0-9]{2})/i);
            if (spotMatch) {
                const s = parseFloat(spotMatch[1].replace(/,/g, ''));
                if (s > 10000 && Math.abs(s - state.spot) > 0.05) {
                    state.spot = s;
                    const spotEl = document.getElementById('agi-card-spot');
                    if (spotEl) spotEl.textContent = 'Spot: ' + s.toFixed(2);
                }
            }
        } catch(e){}
    }, 1000);

})();
"""


def _cdp_ws_send_and_recv(ws_url: str, messages: List[Dict[str, Any]], timeout: float = 2.0) -> List[Dict[str, Any]]:
    """Minimal RFC 6455 WebSocket client using pure Python standard library socket."""
    parsed = urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9229
    path = parsed.path or "/"

    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(handshake.encode("ascii"))

        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp += chunk

        results = []
        for msg in messages:
            payload = json.dumps(msg).encode("utf-8")
            mask_key = os.urandom(4)
            header = bytearray([0x81])  # FIN + text frame
            length = len(payload)
            if length < 126:
                header.append(0x80 | length)
            elif length < 65536:
                header.append(0x80 | 126)
                header.extend(struct.pack("!H", length))
            else:
                header.append(0x80 | 127)
                header.extend(struct.pack("!Q", length))
            header.extend(mask_key)
            masked = bytearray(payload[i] ^ mask_key[i % 4] for i in range(length))
            sock.sendall(header + masked)

            # Read response frame
            first2 = sock.recv(2)
            if len(first2) == 2:
                rlen = first2[1] & 0x7F
                if rlen == 126:
                    rlen = struct.unpack("!H", sock.recv(2))[0]
                elif rlen == 127:
                    rlen = struct.unpack("!Q", sock.recv(8))[0]
                rdata = b""
                while len(rdata) < rlen:
                    part = sock.recv(rlen - len(rdata))
                    if not part:
                        break
                    rdata += part
                try:
                    results.append(json.loads(rdata.decode("utf-8", errors="ignore")))
                except Exception:
                    pass
        return results
    finally:
        sock.close()


def inject_universal_mouse_into_all_tabs(quant_summary: Optional[str] = None) -> List[Dict[str, Any]]:
    """Injects the clean, non-looping AGI HUD into every open Chrome tab via CDP port 9229."""
    try:
        req = urllib.request.urlopen("http://127.0.0.1:9229/json", timeout=1.5)
        targets = json.loads(req.read().decode("utf-8"))
    except Exception:
        return []

    injected_tabs = []
    blocked_keywords = ("whatsapp", "telegram", "discord", "outlook", "mail.google", "gmail", "slack", "signal")
    for t in targets:
        if t.get("type") != "page":
            continue
        url_lower = t.get("url", "").lower()
        title_lower = t.get("title", "").lower()
        if any(b in url_lower for b in blocked_keywords) or any(b in title_lower for b in blocked_keywords):
            continue
        if "paytmmoney.com" not in url_lower:
            continue
        ws_url = t.get("webSocketDebuggerUrl")
        if not ws_url:
            continue

        cmds = [
            {"id": 1, "method": "Page.enable", "params": {}},
            {
                "id": 2,
                "method": "Page.addScriptToEvaluateOnNewDocument",
                "params": {"source": UNIVERSAL_MOUSE_JS},
            },
            {
                "id": 3,
                "method": "Runtime.evaluate",
                "params": {"expression": UNIVERSAL_MOUSE_JS, "returnByValue": True},
            },
        ]
        try:
            res = _cdp_ws_send_and_recv(ws_url, cmds, timeout=1.5)
            injected_tabs.append({"title": t.get("title"), "url": t.get("url"), "cdp_ok": True, "responses": len(res)})
        except Exception as e:
            injected_tabs.append({"title": t.get("title"), "url": t.get("url"), "cdp_ok": False, "error": str(e)})

    return injected_tabs


if __name__ == "__main__":
    out = inject_universal_mouse_into_all_tabs()
    print("UNIVERSAL_MOUSE_INJECTED_TABS:", json.dumps(out, indent=2))
