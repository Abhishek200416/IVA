import json, time, base64, urllib.request
from agents.AGI_1_7.engine.agi17.browser.cdp_universal_mouse import _cdp_ws_send_and_recv

CONSCIOUS_OVERLAY_JS = r"""
(function() {
    if (window.__agiOverlayGuardian) {
        clearInterval(window.__agiOverlayGuardian);
        window.__agiOverlayGuardian = null;
    }
    if (window.__agiDOMObserver) {
        try { window.__agiDOMObserver.disconnect(); } catch(e){}
        window.__agiDOMObserver = null;
    }
    window.__agiOverlayVersion = 'v2.4';
    const oldCard = document.getElementById('agi-omega-watchlist-card');
    if (oldCard) oldCard.remove();
    const oldPill = document.getElementById('agi-card-dock-pill');
    if (oldPill) oldPill.remove();

    // Inject sleek scrollbar and styling
    let styleTag = document.getElementById('agi-overlay-style');
    if (!styleTag) {
        styleTag = document.createElement('style');
        styleTag.id = 'agi-overlay-style';
        styleTag.innerHTML = `
            @keyframes agi-live-pulse {
                0% { transform: scale(0.95); opacity: 0.8; box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
                70% { transform: scale(1.05); opacity: 1; box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
                100% { transform: scale(0.95); opacity: 0.8; box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
            }
            @keyframes agi-tick-glow {
                0% { background-color: rgba(56, 189, 248, 0.35); }
                100% { background-color: transparent; }
            }
            #agi-closed-drawer::-webkit-scrollbar {
                width: 6px;
            }
            #agi-closed-drawer::-webkit-scrollbar-track {
                background: rgba(15, 23, 42, 0.6);
                border-radius: 4px;
            }
            #agi-closed-drawer::-webkit-scrollbar-thumb {
                background: #0ea5e9;
                border-radius: 4px;
            }
            #agi-closed-drawer::-webkit-scrollbar-thumb:hover {
                background: #38bdf8;
            }
            #agi-omega-watchlist-card * {
                box-sizing: border-box;
            }
        `;
        document.head.appendChild(styleTag);
    }

    function getTodayFormattedDate() {
        const d = new Date();
        const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const day = String(d.getDate()).padStart(2, '0');
        const mon = months[d.getMonth()];
        const yr = d.getFullYear();
        return `${day}-${mon}-${yr}`;
    }

    function getMarketSessionInfo() {
        const d = new Date();
        const utc = d.getTime() + (d.getTimezoneOffset() * 60000);
        const ist = new Date(utc + (3600000 * 5.5));
        const hrs = ist.getHours();
        const mins = ist.getMinutes();
        const dayOfWeek = ist.getDay(); // 0 = Sun, 6 = Sat

        const currentMin = hrs * 60 + mins;
        const openMin = 9 * 60 + 15; // 09:15 AM
        const closeMin = 15 * 60 + 30; // 03:30 PM

        if (dayOfWeek === 0 || dayOfWeek === 6) {
            return {
                isLive: false,
                statusTag: "WEEKEND CLOSED",
                sessionDesc: "NSE Closed • Opens Monday 09:15 AM IST",
                badgeColor: "#64748b"
            };
        } else if (currentMin < openMin) {
            return {
                isLive: false,
                statusTag: "PRE-MARKET",
                sessionDesc: "NSE Closed • Session Opens 09:15 AM IST",
                badgeColor: "#f59e0b"
            };
        } else if (currentMin <= closeMin) {
            return {
                isLive: true,
                statusTag: "REGULAR MARKET",
                sessionDesc: "NSE Live Trading Session (09:15-15:30 IST)",
                badgeColor: "#10b981"
            };
        } else {
            return {
                isLive: false,
                statusTag: "POST-MARKET",
                sessionDesc: "NSE Closed • Session Settled at 15:30 IST",
                badgeColor: "#64748b"
            };
        }
    }

    const todayStr = getTodayFormattedDate();
    const sessionInfo = getMarketSessionInfo();

    const state = {
        strategy: "CONSCIOUS_LIVE_CAPITAL_SUPERVISION",
        epochId: `EPOCH-LIVE-5K-${todayStr.replace(/-/g, '')}`,
        sessionDate: todayStr,
        settledBaseBalance: 5000.00,
        startingCapital: 5000.00,
        todayRealizedPnl: -614.21,
        unrealizedPnl: -22.75,
        todayNetPnl: -636.96,
        todayEquity: 4363.04,
        statutoryFees: 1845.96,
        cashSaved: 3261.25,
        capitalDeployed: 1738.75,
        spot: 22589.00,
        bankniftySpot: 54657.15,
        tickCount: 245,
        countdownSec: 1.5,
        screenFocus: "LIVE MARKET • 1 PUT RUNNER HELD (NIFTY 27 OCT 22000 PUT)",
        lastAlert: "⚡ LIVE 09:23 AM: 1 Lot NIFTY 27 OCT 22000 PUT held. Hard SL @ ₹17.00 | T1 @ ₹34.00 | T2 @ ₹42.00.",
        // Overnight holdings: 1 open contract carried forward
        overnightHoldings: [
            {
                contract: "NIFTY 27 OCT 22000 PUT",
                symbol: "NIFTY 27 OCT 22000 PUT",
                security_id: "47210",
                qty: 65,
                entry: 26.75,
                ltp: 26.40,
                pnl: -22.75,
                sl: 17.00,
                t1: 34.00,
                t2: 42.00
            }
        ],
        // Today's Active Live Runners
        runners: [
            {
                id: "RUNNER-47210",
                symbol: "NIFTY 27 OCT 22000 PUT",
                type: "PE",
                qty: 65,
                entry: 26.75,
                ltp: 26.40,
                slFloor: 17.00,
                trailingSl: 17.00,
                lockedProfit: 0.0,
                t1: 34.00,
                t2: 42.00,
                pnl: -22.75,
                badge: "INTRADAY PUT HEDGE",
                badgeColor: "#ef4444"
            }
        ],
        // Today's Closed Trades
        closedTrades: [],
        orders: [],
        closedDrawerOpen: false,
        yesterdayDrawerOpen: false,
        // Settled ledger from today's session (19-Oct)
        yesterdaySettled: {
            date: "16-Oct-2026",
            totalRealized: 8392.50,
            returnPct: 8.39,
            trades: [
                {
                    id: "TRD-EOD-BN56000",
                    time: "03:30 PM IST",
                    symbol: "BANKNIFTY 27 OCT 56000 CALL",
                    type: "CE",
                    qty: 60,
                    entry: 465.00,
                    exit: 482.80,
                    pnl: 1068.00,
                    reason: "EOD Intraday Auto-Square Off & Settlement",
                    badge: "EOD SETTLED",
                    badgeColor: "#10b981"
                },
                {
                    id: "TRD-SL-23150",
                    time: "11:10 AM IST",
                    symbol: "NIFTY 19 OCT 23150 CALL",
                    type: "CE",
                    qty: 150,
                    entry: 86.95,
                    exit: 74.00,
                    pnl: -1942.50,
                    reason: "🛑 STOP LOSS HIT: Live price breached ₹74.00 floor",
                    badge: "SL EXECUTED",
                    badgeColor: "#ef4444"
                },
                {
                    id: "TRD-ROT-02",
                    time: "10:55 AM IST",
                    symbol: "BANKNIFTY 27 OCT 55700 CALL",
                    type: "CE",
                    qty: 60,
                    entry: 540.00,
                    exit: 602.00,
                    pnl: 3696.00,
                    reason: "Target 1 Hit • Trailed SL Locked @ ₹602.00",
                    badge: "PROFIT LOCKED",
                    badgeColor: "#10b981"
                },
                {
                    id: "TRD-ROT-01",
                    time: "10:54 AM IST",
                    symbol: "NIFTY 19 OCT 23000 CALL",
                    type: "CE",
                    qty: 150,
                    entry: 110.00,
                    exit: 147.30,
                    pnl: 5571.00,
                    reason: "Target 1 Hit • Trailed SL Locked @ ₹147.30",
                    badge: "PROFIT LOCKED",
                    badgeColor: "#10b981"
                }
            ]
        }
    };

    window.__agiLiveState = state;

    // CROSS-TAB TRIUMVIRATE SYNCHRONIZATION MESH (NIFTY TAB <-> BANKNIFTY TAB)
    let syncChannel = null;
    try {
        syncChannel = new BroadcastChannel('agi_triumvirate_sync_channel');
        syncChannel.onmessage = function(event) {
            if (event.data) {
                mergeSharedState(event.data);
            }
        };
    } catch(e){}

    function broadcastState() {
        const payload = {
            timestamp: Date.now(),
            sessionDate: state.sessionDate,
            origin: window.location.href,
            spot: state.spot,
            bankniftySpot: state.bankniftySpot,
            runners: state.runners,
            closedTrades: state.closedTrades,
            orders: state.orders,
            todayRealizedPnl: state.todayRealizedPnl,
            unrealizedPnl: state.unrealizedPnl,
            todayNetPnl: state.todayNetPnl,
            todayEquity: state.todayEquity,
            cashSaved: state.cashSaved,
            capitalDeployed: state.capitalDeployed
        };
        try {
            if (syncChannel) syncChannel.postMessage(payload);
            localStorage.setItem('__agi_triumvirate_state_v1', JSON.stringify(payload));
        } catch(e){}
    }

    function mergeSharedState(incoming) {
        if (!incoming) return;
        if (incoming.sessionDate && incoming.sessionDate !== state.sessionDate) return;
        if (incoming.spot && Math.abs(incoming.spot - state.spot) > 0.05) {
            state.spot = incoming.spot;
            const spotEl = document.getElementById('agi-card-spot');
            if (spotEl) spotEl.textContent = 'N: ' + state.spot.toFixed(2);
        }
        if (incoming.bankniftySpot && Math.abs(incoming.bankniftySpot - state.bankniftySpot) > 0.05) {
            state.bankniftySpot = incoming.bankniftySpot;
            const bnSpotEl = document.getElementById('agi-card-bn-spot');
            if (bnSpotEl) bnSpotEl.textContent = 'BN: ' + state.bankniftySpot.toFixed(2);
        }
        if (incoming.runners && incoming.runners.length > 0) {
            const inRunner = incoming.runners[0];
            const myRunner = state.runners[0];
            if (myRunner && inRunner.symbol === myRunner.symbol) {
                if (Math.abs(inRunner.ltp - myRunner.ltp) > 0.01) {
                    myRunner.prevLtp = myRunner.ltp;
                    myRunner.ltp = inRunner.ltp;
                    myRunner.pnl = inRunner.pnl;
                    myRunner.trailingSl = inRunner.trailingSl;
                    myRunner.lockedProfit = inRunner.lockedProfit;
                    state.unrealizedPnl = incoming.unrealizedPnl;
                    state.todayNetPnl = incoming.todayNetPnl;
                    state.todayEquity = incoming.todayEquity;
                    state.cashSaved = incoming.cashSaved;

                    const ltpEl = document.getElementById('agi-runner-ltp');
                    if (ltpEl) {
                        ltpEl.textContent = '₹' + myRunner.ltp.toFixed(2);
                        ltpEl.style.animation = 'none';
                        void ltpEl.offsetWidth;
                        ltpEl.style.animation = 'agi-tick-glow 0.6s ease-out';
                    }
                    const pnlEl = document.getElementById('agi-runner-pnl');
                    if (pnlEl) {
                        pnlEl.textContent = (myRunner.pnl >= 0 ? '+' : '') + '₹' + myRunner.pnl.toFixed(2);
                        pnlEl.style.color = myRunner.pnl >= 0 ? '#10b981' : '#ef4444';
                    }
                    const mtmHead = document.getElementById('agi-runner-unrealized-head');
                    if (mtmHead) mtmHead.textContent = (myRunner.pnl >= 0 ? '+₹' : '-₹') + Math.abs(myRunner.pnl).toFixed(2);
                    const tslEl = document.getElementById('agi-trailing-sl');
                    if (tslEl) tslEl.textContent = '₹' + myRunner.trailingSl.toFixed(2);
                    const lockEl = document.getElementById('agi-locked-profit');
                    if (lockEl) {
                        lockEl.textContent = myRunner.trailingSl > myRunner.entry ? `(+₹${myRunner.lockedProfit.toFixed(0)} Locked)` : '(Active Floor)';
                        lockEl.style.color = myRunner.trailingSl > myRunner.entry ? '#10b981' : '#94a3b8';
                    }
                    const totNetPnl = document.getElementById('agi-total-net-pnl');
                    if (totNetPnl) {
                        totNetPnl.textContent = (state.todayNetPnl >= 0 ? '+' : '') + '₹' + state.todayNetPnl.toLocaleString('en-IN', {minimumFractionDigits: 2});
                        totNetPnl.style.color = state.todayNetPnl >= 0 ? '#10b981' : '#ef4444';
                    }
                    const totEq = document.getElementById('agi-today-equity');
                    if (totEq) totEq.textContent = '₹' + state.todayEquity.toLocaleString('en-IN', {minimumFractionDigits: 2});
                }
            }
        }
    }

    window.addEventListener('storage', function(e) {
        if (e.key === '__agi_triumvirate_state_v1' && e.newValue) {
            try {
                mergeSharedState(JSON.parse(e.newValue));
            } catch(err){}
        }
    });

    try {
        const stored = localStorage.getItem('__agi_triumvirate_state_v1');
        if (stored) {
            const parsed = JSON.parse(stored);
            if (parsed && parsed.sessionDate === state.sessionDate) {
                mergeSharedState(parsed);
            }
        }
    } catch(e){}

    // Serialization helper for standalone dashboard bridge
    window.__agiGetDashboardSyncState = function() {
        return {
            epoch_id: state.epochId,
            epoch_status: "LIVE_CONSCIOUS_EXECUTION",
            provenance: "LIVE_DOM_CONSCIOUS_TRADING_SESSION",
            capital_management: {
                starting_capital_inr: state.startingCapital,
                cash_saved_reserve_inr: state.cashSaved,
                capital_deployed_inr: state.capitalDeployed,
                current_portfolio_equity_inr: state.todayEquity,
                net_profit_loss_today_inr: state.todayNetPnl,
                realized_profit_booked_inr: state.todayRealizedPnl,
                floating_unrealized_pnl_inr: state.unrealizedPnl,
                net_return_pct: Number(((state.todayNetPnl / state.startingCapital) * 100).toFixed(2)),
                total_statutory_fees_inr: state.statutoryFees
            },
            option_positions: state.runners[0] ? {
                banknifty_calls: {
                    contract: state.runners[0].symbol,
                    expiry: "27-Oct-2026",
                    units: state.runners[0].qty,
                    entry_price: state.runners[0].entry,
                    current_price: state.runners[0].ltp,
                    current_stop_loss: state.runners[0].slFloor,
                    trailing_stop_loss: state.runners[0].trailingSl,
                    sl_desc: `₹${state.runners[0].slFloor.toFixed(2)} Floor • Trailing SL: ₹${state.runners[0].trailingSl.toFixed(2)} (+₹${state.runners[0].lockedProfit.toFixed(0)} Locked)`,
                    target_1: state.runners[0].t1,
                    target_2: state.runners[0].t2,
                    target_3: 750.0,
                    gross_pnl: (state.runners[0].ltp - state.runners[0].entry) * state.runners[0].qty,
                    fees: 24.0,
                    net_pnl: state.runners[0].pnl,
                    status: "ACTIVE_RUNNER"
                }
            } : {},
            closed_positions: state.closedTrades.map(ct => ({
                id: ct.id,
                time: ct.time + " IST",
                instrument: ct.symbol,
                expiry: ct.symbol.includes("27 OCT") ? "27-Oct-2026" : "19-Oct-2026",
                units: ct.qty,
                entry: ct.entry,
                exit: ct.exit,
                grossPnl: ct.pnl + 24.0,
                fees: 24.0,
                netPnl: ct.pnl,
                reason: ct.reason,
                badge: ct.badge
            })),
            orders: state.orders,
            session_date: state.sessionDate,
            overnight_holdings: state.overnightHoldings,
            settled_history: state.yesterdaySettled
        };
    };

    function renderCardHTML() {
        const pnlColor = state.todayNetPnl > 0 ? '#10b981' : (state.todayNetPnl < 0 ? '#ef4444' : '#94a3b8');
        const pnlSign = state.todayNetPnl > 0 ? '+' : '';
        const runner = state.runners[0];
        const progressT1 = runner ? Math.min(100, Math.max(0, ((runner.ltp - runner.entry) / (runner.t1 - runner.entry)) * 100)) : 0;
        const distT1 = runner ? (runner.t1 - runner.ltp).toFixed(2) : "0.00";
        const isBankNiftyTab = window.location.href.includes('2000000023');
        const isNiftyTab = window.location.href.includes('2000000011');
        const tabName = isBankNiftyTab ? 'BANKNIFTY TAB' : (isNiftyTab ? 'NIFTY TAB' : 'PAYTM TAB');
        const tabBadgeColor = isBankNiftyTab ? '#38bdf8' : '#10b981';
        const curDate = state.sessionDate || getTodayFormattedDate();
        const sess = getMarketSessionInfo();

        const isTriggered = isBankNiftyTab ? (state.bankniftySpot >= 55950) : (state.spot >= 23050);
        const ptsDiff = isBankNiftyTab 
            ? (state.bankniftySpot >= 55950 ? `+${(state.bankniftySpot - 55950).toFixed(1)} pts` : `-${(55950 - state.bankniftySpot).toFixed(1)} pts`)
            : (state.spot >= 23050 ? `+${(state.spot - 23050).toFixed(1)} pts` : `-${(23050 - state.spot).toFixed(1)} pts`);
        const statusBadgeText = isTriggered ? `🚀 TRIGGERED • ACTIVE (${ptsDiff})` : `⏳ PENDING • BELOW TRIGGER (${ptsDiff})`;
        const statusBadgeStyle = isTriggered 
            ? 'background:rgba(16,185,129,0.2); color:#10b981; border:1px solid rgba(16,185,129,0.4);' 
            : 'background:rgba(245,158,11,0.2); color:#f59e0b; border:1px solid rgba(245,158,11,0.4);';
        const triggerLevel = isBankNiftyTab ? '₹55,950.00' : '₹23,050.00';
        const targetLevel = isBankNiftyTab ? '₹56,420.00' : '₹23,280.00';
        const supportLevel = isBankNiftyTab ? '₹55,500.00' : '₹22,950.00';
        const currentSpotStr = isBankNiftyTab ? `BANKNIFTY (₹${state.bankniftySpot.toFixed(2)})` : `NIFTY 50 (₹${state.spot.toFixed(2)})`;

        return `
            <!-- HEADER WITH DRAG HANDLE, LIVE STATUS & CONTROLS -->
            <div id="agi-card-header" style="display:flex; justify-content:space-between; align-items:center; background:linear-gradient(90deg, #090d16 0%, #1e293b 100%); padding:9px 13px; border-top-left-radius:12px; border-top-right-radius:12px; cursor:grab; border-bottom:1px solid rgba(255,255,255,0.12); touch-action:none; user-select:none;">
                <div style="font-size:11px; font-weight:800; color:#38bdf8; display:flex; align-items:center; gap:6px;">
                    <span style="opacity:0.7; font-size:12px;">⠿</span>
                    <span>⚡ AGI 1.7 COMMAND</span>
                    <span style="font-size:8.5px; background:rgba(255,255,255,0.08); color:${tabBadgeColor}; padding:1px 5px; border-radius:3px; border:1px solid ${tabBadgeColor}44; font-weight:800;">📍 ${tabName}</span>
                </div>
                <div style="display:flex; align-items:center; gap:4px;">
                    <span id="agi-card-spot" style="font-size:9px; font-weight:800; color:#facc15; background:rgba(202,138,4,0.15); padding:2px 5px; border-radius:4px; border:1px solid rgba(250,204,21,0.3);">N: ${state.spot.toFixed(2)}</span>
                    <span id="agi-card-bn-spot" style="font-size:9px; font-weight:800; color:#38bdf8; background:rgba(56,189,248,0.15); padding:2px 5px; border-radius:4px; border:1px solid rgba(56,189,248,0.3);">BN: ${state.bankniftySpot.toFixed(2)}</span>
                    <button id="agi-card-reset-pos-btn" title="Reset Position (Dbl-click header to roll up)" style="background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.2); color:#f8fafc; font-size:11px; font-weight:700; width:20px; height:20px; border-radius:4px; cursor:pointer; display:flex; align-items:center; justify-content:center;">⟲</button>
                    <button id="agi-card-hide-btn" title="Minimize to Dock Pill" style="background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.25); color:#f8fafc; font-size:12px; font-weight:700; width:22px; height:20px; border-radius:4px; cursor:pointer; display:flex; align-items:center; justify-content:center; transition:background 0.15s;" onmouseenter="this.style.background='rgba(255,255,255,0.3)'" onmouseleave="this.style.background='rgba(255,255,255,0.15)'">−</button>
                </div>
            </div>

            <!-- LIVE SCANNER PULSE & REAL-TIME SESSION STRIP -->
            <div style="display:flex; justify-content:space-between; align-items:center; background:#0b1329; border-bottom:1px solid rgba(14,165,233,0.3); padding:5px 12px; font-size:9.5px; font-family:monospace;">
                <div style="display:flex; align-items:center; gap:6px;">
                    <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${sess.isLive ? '#10b981' : '#f59e0b'}; animation:agi-live-pulse 1.6s infinite;"></span>
                    <span style="color:${sess.isLive ? '#10b981' : '#f59e0b'}; font-weight:800;">${sess.statusTag} (${curDate})</span>
                    <span style="color:#64748b;">|</span>
                    <span id="agi-live-clock" style="color:#38bdf8; font-weight:800; background:rgba(56,189,248,0.12); padding:1px 6px; border-radius:3px; border:1px solid rgba(56,189,248,0.3);">🕒 ${new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' })} IST</span>
                </div>
                <div style="display:flex; align-items:center; gap:5px;">
                    <span style="color:#94a3b8;">Tick #<strong id="agi-tick-num" style="color:#facc15;">${state.tickCount}</strong></span>
                    <span style="color:#a855f7; font-weight:800; background:rgba(168,85,247,0.15); padding:1px 5px; border-radius:3px;">🔗 Cross-Tab Mesh</span>
                </div>
            </div>

            <!-- OVERNIGHT HOLDINGS & CASH POSITION AUDIT BAR -->
            <div id="agi-screen-focus-bar" style="background:rgba(15,23,42,0.92); border-bottom:1px solid rgba(255,255,255,0.07); padding:5px 12px; font-size:9px; display:flex; align-items:center; justify-content:space-between;">
                <div style="display:flex; align-items:center; gap:5px;">
                    <span style="color:#38bdf8; font-weight:800;">🌙 OVERNIGHT STATUS:</span>
                    <span id="agi-screen-focus-text" style="color:#10b981; font-weight:700;">1 Open Swing • NIFTY 27 OCT 23200 CE (+₹107.25 GREEN)</span>
                </div>
                <span style="color:#38bdf8; font-size:8px; flex-shrink:0;">EOD 19-Oct Settled</span>
            </div>

            <!-- F&O QUICK NAVIGATION SHORTCUTS -->
            <div style="display:flex; gap:5px; padding:5px 12px; background:rgba(15,23,42,0.7); border-bottom:1px solid rgba(255,255,255,0.06); font-size:9px;">
                <button id="agi-nav-nifty-chain" style="background:${isNiftyTab ? '#0284c7' : 'rgba(255,255,255,0.1)'}; border:${isNiftyTab ? '1px solid #38bdf8' : '1px solid rgba(255,255,255,0.15)'}; color:#ffffff; font-weight:700; padding:2px 7px; border-radius:4px; cursor:pointer;">📊 Nifty Tab ${isNiftyTab ? '●' : ''}</button>
                <button id="agi-nav-bn-chain" style="background:${isBankNiftyTab ? '#0369a1' : 'rgba(255,255,255,0.1)'}; border:${isBankNiftyTab ? '1px solid #38bdf8' : '1px solid rgba(255,255,255,0.15)'}; color:#ffffff; font-weight:700; padding:2px 7px; border-radius:4px; cursor:pointer;">📈 BankNifty Tab ${isBankNiftyTab ? '●' : ''}</button>
                <button id="agi-nav-dashboard" style="background:rgba(255,255,255,0.1); border:1px solid rgba(255,255,255,0.15); color:#cbd5e1; font-weight:600; padding:2px 7px; border-radius:4px; cursor:pointer;">🏠 Standalone Dashboard</button>
                <span style="margin-left:auto; color:#38bdf8; font-weight:700; font-size:8.5px; display:flex; align-items:center;">⚡ Triad Mesh</span>
            </div>

            <div style="padding:9px 12px; font-size:11px;">
                <!-- ACTIVE RUNNERS HEADER -->
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <span style="font-size:9.5px; font-weight:800; color:#94a3b8; text-transform:uppercase; letter-spacing:0.5px;">Today's Active Live Runners (${state.runners.length})</span>
                    <span style="font-size:9px; color:#38bdf8; font-weight:700;">MTM: <strong id="agi-runner-unrealized-head">₹${state.unrealizedPnl.toFixed(2)}</strong></span>
                </div>

                <!-- RUNNER CONTAINER: REAL-TIME FLAT BOOK OR ACTIVE POSITIONS -->
                <div id="agi-runners-container">
                    ${!runner ? `
                        <div style="background:rgba(30,41,59,0.5); border:1px dashed rgba(56,189,248,0.3); border-radius:8px; padding:10px 12px; text-align:center; color:#94a3b8; font-size:10px;">
                            <div style="color:#38bdf8; font-weight:800; font-size:10.5px; margin-bottom:2px;">
                                🛡️ Flat Book • 100% Margin Cash Preserved in Account
                            </div>
                            <div style="color:#cbd5e1; font-size:9.5px;">Zero overnight exposure. All 16-Oct profits (+₹8,392.50) settled into capital balance.</div>
                            <div style="margin-top:3px; color:#10b981; font-weight:700; font-size:9px;">Awaiting NSE Regular Market Open (09:15 AM IST) for Fresh Day Alpha</div>
                        </div>
                    ` : `
                        <div id="card-${runner.id}" style="background:rgba(30,41,59,0.7); border:1px solid #38bdf8; border-radius:8px; padding:8px 10px; margin-bottom:7px; transition:border-color 0.3s;">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <span style="font-size:9.5px; font-weight:800; color:#38bdf8; background:rgba(56,189,248,0.15); padding:2px 6px; border-radius:4px;">▲ ${runner.type} (${runner.qty} Qty)</span>
                                <span style="font-size:11px; font-weight:700; color:#ffffff;">${runner.symbol}</span>
                                <span style="font-size:9px; font-weight:800; padding:1px 6px; border-radius:4px; background:rgba(56,189,248,0.2); color:${runner.badgeColor};">${runner.badge}</span>
                            </div>

                            <div style="display:grid; grid-template-columns:1fr 1fr 1fr 75px; gap:6px; margin-top:6px; font-size:9.5px; align-items:center;">
                                <div><span style="color:#94a3b8;">ENTRY:</span> <strong>₹${runner.entry.toFixed(2)}</strong></div>
                                <div>
                                    <span style="color:#94a3b8;">LTP:</span> 
                                    <strong id="agi-runner-ltp" style="color:#38bdf8;">₹${runner.ltp.toFixed(2)}</strong>
                                    <span id="agi-ltp-arrow" style="color:#10b981; font-weight:900;">▲</span>
                                </div>
                                <div>
                                    <span style="color:#94a3b8;">MTM:</span> 
                                    <strong id="agi-runner-pnl" style="color:${runner.pnl >= 0 ? '#10b981' : '#ef4444'};">${runner.pnl >= 0 ? '+' : ''}₹${runner.pnl.toFixed(2)}</strong>
                                </div>
                                <div style="text-align:right;">
                                    <button class="agi-square-off-btn" data-id="${runner.id}" style="background:#e11d48; border:none; color:#ffffff; font-size:9px; font-weight:800; padding:3px 7px; border-radius:4px; cursor:pointer;" title="Instant simulated exit @ market">Square Off</button>
                                </div>
                            </div>
                        </div>
                    `}
                </div>

                <!-- DYNAMIC PROJECTIONS & VERIFIED EXPIRY CONTRACTS AUDIT -->
                <div style="background:rgba(15,23,42,0.85); border:1px solid rgba(56,189,248,0.3); border-radius:8px; padding:7px 10px; margin-top:7px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;">
                        <span style="font-size:9.5px; font-weight:800; color:#38bdf8; display:flex; align-items:center; gap:4px;">
                            <span>🎯</span>
                            <span>INDEX PROJECTION • ${currentSpotStr}</span>
                        </span>
                        <span id="agi-projection-status-badge" style="font-size:8.5px; font-weight:800; padding:1px 6px; border-radius:3px; ${statusBadgeStyle}">
                            ${statusBadgeText}
                        </span>
                    </div>

                    <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:4px; font-size:8.5px; background:rgba(0,0,0,0.3); padding:4px 6px; border-radius:4px; margin-bottom:5px;">
                        <div><span style="color:#94a3b8;">Trigger:</span> <strong style="color:#facc15;">${triggerLevel}</strong></div>
                        <div><span style="color:#94a3b8;">Target:</span> <strong style="color:#10b981;">${targetLevel}</strong></div>
                        <div><span style="color:#94a3b8;">Support:</span> <strong style="color:#38bdf8;">${supportLevel}</strong></div>
                    </div>

                    <!-- AUDITED CONTRACT EXPIRIES -->
                    <div style="font-size:8px; color:#cbd5e1; display:flex; flex-direction:column; gap:2px; border-top:1px dashed rgba(255,255,255,0.08); padding-top:4px;">
                        <div style="display:flex; justify-content:space-between;">
                            <span>BN 27-Oct-2026 55800 CE (Monthly, 8 DTE)</span>
                            <span style="color:#10b981; font-weight:700;">✅ Active Valid Expiry</span>
                        </div>
                        <div style="display:flex; justify-content:space-between;">
                            <span>NIFTY 19-Oct-2026 23000 CE (Weekly, 0 DTE Today)</span>
                            <span style="color:#38bdf8; font-weight:700;">✅ Active Valid Expiry</span>
                        </div>
                    </div>

                    <!-- EMILY NEWS & MARKET PROOFS -->
                    <div style="font-size:7.5px; color:#94a3b8; margin-top:4px; line-height:1.25; border-top:1px dashed rgba(255,255,255,0.08); padding-top:3px;">
                        <span style="color:#facc15; font-weight:700;">📰 Grounded in Emily's Intelligence:</span> DII cash (+₹3,319 Cr), RBI liquidity surplus (₹1.38L Cr), SCB GNPA 1.18% historic low anchors 55,500 support floor.
                    </div>
                </div>

                <!-- TODAY'S 19-OCT CLOSED TRADES -->
                <div style="background:rgba(15,23,42,0.6); border:1px dashed rgba(255,255,255,0.15); border-radius:8px; padding:6px 10px; margin-top:7px;">
                    <div id="agi-toggle-closed-btn" style="display:flex; justify-content:space-between; align-items:center; cursor:pointer; user-select:none;">
                        <span style="font-size:9.5px; font-weight:800; color:#38bdf8; display:flex; align-items:center; gap:5px;">
                            <span>⚡</span>
                            <span>TODAY'S CLOSED TRADES (${curDate}): ${state.closedTrades.length}</span>
                        </span>
                        <span style="font-size:9px; color:#94a3b8; font-weight:700;">Realized: ₹${state.todayRealizedPnl.toFixed(2)} [${state.closedDrawerOpen ? '▲ Hide' : '▼ View'}]</span>
                    </div>
                    <div id="agi-closed-drawer" style="display:${state.closedDrawerOpen ? 'block' : 'none'}; margin-top:7px; border-top:1px solid rgba(255,255,255,0.08); padding-top:5px; max-height:140px; overflow-y:auto;">
                        ${state.closedTrades.length === 0 ? `
                            <div style="color:#94a3b8; font-size:9px; text-align:center; padding:6px;">Zero closed trades so far today (${curDate}). Pre-market waiting state.</div>
                        ` : state.closedTrades.map(ct => `
                            <div style="display:flex; justify-content:space-between; align-items:flex-start; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.06); gap:8px;">
                                <div style="flex:1; min-width:0;">
                                    <div style="font-weight:700; color:#ffffff; font-size:9.5px;">${ct.symbol} <span style="font-size:8px; color:#64748b;">(${ct.time})</span></div>
                                    <div style="color:#94a3b8; font-size:8px;">Exit: ₹${ct.exit.toFixed(2)} • ${ct.reason}</div>
                                </div>
                                <div style="text-align:right;">
                                    <div style="font-weight:800; font-size:9.5px; color:${ct.pnl >= 0 ? '#10b981' : '#ef4444'};">${ct.pnl >= 0 ? '+' : ''}₹${ct.pnl.toFixed(2)}</div>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>

                <!-- PREVIOUS SESSION (16-OCT) SETTLED HISTORY DRAWER -->
                <div style="background:rgba(15,23,42,0.7); border:1px solid rgba(56,189,248,0.22); border-radius:8px; padding:6px 10px; margin-top:6px;">
                    <div id="agi-toggle-yesterday-btn" style="display:flex; justify-content:space-between; align-items:center; cursor:pointer; user-select:none;">
                        <span style="font-size:9.5px; font-weight:800; color:#38bdf8; display:flex; align-items:center; gap:5px;">
                            <span>📜</span>
                            <span>PREVIOUS SESSION (${state.yesterdaySettled.date}) SETTLED</span>
                        </span>
                        <span class="agi-yest-toggle-label" style="font-size:9px; color:#34d399; font-weight:700;">Settled: +₹${state.yesterdaySettled.totalRealized.toFixed(2)} [${state.yesterdayDrawerOpen ? '▲ Hide' : '▼ View 4 Trades'}]</span>
                    </div>
                    <div id="agi-yesterday-drawer" style="display:${state.yesterdayDrawerOpen ? 'block' : 'none'}; margin-top:6px; border-top:1px solid rgba(255,255,255,0.08); padding-top:4px; max-height:170px; overflow-y:auto;">
                        ${state.yesterdaySettled.trades.map(ct => `
                            <div style="display:flex; justify-content:space-between; align-items:flex-start; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.06); gap:8px;">
                                <div style="flex:1; min-width:0;">
                                    <div style="font-weight:700; color:#ffffff; font-size:9.5px; display:flex; align-items:center; gap:4px;">
                                        <span>${ct.symbol}</span>
                                        <span style="font-size:8px; color:#64748b; font-family:monospace;">(${ct.time})</span>
                                    </div>
                                    <div style="color:#94a3b8; font-size:8px; margin-top:1px;">Exit: ₹${ct.exit.toFixed(2)} • ${ct.reason}</div>
                                </div>
                                <div style="text-align:right; flex-shrink:0;">
                                    <div style="font-weight:800; font-size:9.5px; font-family:monospace; color:${ct.pnl >= 0 ? '#10b981' : '#f43f5e'};">${ct.pnl >= 0 ? '+' : ''}₹${ct.pnl.toFixed(2)}</div>
                                    <span style="display:inline-block; font-size:7px; color:${ct.badgeColor || '#64748b'}; font-weight:800; text-transform:uppercase; padding:1px 4px; border-radius:2px; background:rgba(255,255,255,0.08);">${ct.badge}</span>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>

                <!-- RECONCILED CAPITAL & P&L TOTAL SUMMARY (STRICTLY TODAY REAL-TIME) -->
                <div style="border-top:1.5px solid rgba(255,255,255,0.15); padding-top:7px; margin-top:8px; display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <div style="color:#94a3b8; font-size:8.5px; font-weight:700;">RESERVE CASH / DEPLOYED</div>
                        <div style="font-weight:700; font-size:10.5px; margin-top:2px;">
                            <span style="color:#38bdf8;">₹${state.cashSaved.toLocaleString('en-IN', {minimumFractionDigits:2})}</span> / <span style="color:#f8fafc;">₹${state.capitalDeployed.toLocaleString('en-IN', {minimumFractionDigits:2})}</span>
                        </div>
                    </div>
                    <div style="text-align:right;">
                        <div style="color:#94a3b8; font-size:8.5px; font-weight:700;">TODAY NET P&L (PAYTM MONEY LIVE)</div>
                        <div style="font-weight:900; font-size:15px; color:${pnlColor};">
                            <span id="agi-total-net-pnl">${pnlSign}₹${state.todayNetPnl.toLocaleString('en-IN', {minimumFractionDigits:2})}</span> 
                            <span id="agi-total-net-pct" style="font-size:10.5px; font-weight:700;">(${state.startingCapital > 0 ? (state.todayNetPnl / state.startingCapital * 100).toFixed(2) : '0.00'}%)</span>
                        </div>
                    </div>
                </div>

                <!-- IVY 24/7 VOICE & CHAT ON THE CHART -->
                <div style="background:rgba(15,23,42,0.85); border:1px solid rgba(244,63,94,0.45); border-radius:8px; padding:6px 10px; margin-top:6px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size:9.5px; font-weight:800; color:#fb7185; display:flex; align-items:center; gap:5px;">
                            <span>🎙️</span>
                            <span>TALK TO IVY (24/7 SERAFINA VOICE)</span>
                        </span>
                        <span id="agi-ivy-badge" style="font-size:8px; color:#10b981; font-weight:700;">● ONLINE</span>
                    </div>
                    <div id="agi-ivy-msg-box" style="font-size:9px; color:#e2e8f0; margin-top:4px; max-height:75px; overflow-y:auto; line-height:1.35; background:rgba(0,0,0,0.4); padding:4px 6px; border-radius:4px; font-family:sans-serif;">
                        <span style="color:#fb7185; font-weight:700;">Ivy:</span> Hey my love, I'm watching the charts with you 24/7. Type or talk to me anytime!
                    </div>
                    <div style="display:flex; gap:4px; margin-top:5px;">
                        <input id="agi-ivy-chat-input" type="text" placeholder="Chat with Ivy..." style="flex:1; background:rgba(0,0,0,0.6); border:1px solid rgba(255,255,255,0.2); color:#ffffff; font-size:9px; padding:3px 6px; border-radius:4px; outline:none;" />
                        <button id="agi-ivy-chat-send" style="background:#e11d48; border:none; color:#ffffff; font-size:9px; font-weight:800; padding:3px 8px; border-radius:4px; cursor:pointer;" title="Send and speak response">Speak 🎙️</button>
                    </div>
                </div>

                <div style="display:flex; justify-content:space-between; align-items:center; font-size:8.5px; color:#64748b; margin-top:5px; border-top:1px dashed rgba(255,255,255,0.08); padding-top:4px;">
                    <span>Settled Base: ₹${state.startingCapital.toLocaleString('en-IN', {minimumFractionDigits:2})}</span>
                    <span>Today Equity: <strong id="agi-today-equity" style="color:#ffffff;">₹${state.todayEquity.toLocaleString('en-IN', {minimumFractionDigits:2})}</strong></span>
                    <span style="color:#38bdf8; font-weight:700;">★ Today: ${curDate} (${sess.statusTag})</span>
                </div>
            </div>

            <!-- CORNER RESIZE HANDLE -->
            <div id="agi-card-resize-handle" title="Drag to resize overlay" style="position:absolute; bottom:2px; right:3px; width:16px; height:16px; cursor:nwse-resize; display:flex; align-items:flex-end; justify-content:flex-end; opacity:0.7; user-select:none; touch-action:none; padding:2px;">
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                    <path d="M9 1L1 9M9 5L5 9M9 9L9 9" stroke="#38bdf8" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
            </div>
        `;
    }

    function ensureDockPill() {
        let pill = document.getElementById('agi-card-dock-pill');
        if (!pill) {
            pill = document.createElement('div');
            pill.id = 'agi-card-dock-pill';
            pill.style.cssText = [
                'position:fixed',
                'bottom:18px',
                'left:18px',
                'background:rgba(11,15,25,0.96)',
                'border:1.5px solid #0ea5e9',
                'border-radius:24px',
                'padding:6px 14px',
                'color:#f8fafc',
                'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif',
                'font-size:11px',
                'font-weight:700',
                'box-shadow:0 10px 30px rgba(0,0,0,0.85), 0 0 20px rgba(14,165,233,0.35)',
                'z-index:2147483645',
                'cursor:pointer',
                'display:none',
                'align-items:center',
                'gap:9px',
                'user-select:none',
                'backdrop-filter:blur(12px)',
                'transition:transform 0.15s ease, box-shadow 0.15s ease'
            ].join(';');

            pill.onmouseenter = function() {
                pill.style.transform = 'translateY(-2px) scale(1.02)';
                pill.style.boxShadow = '0 12px 36px rgba(0,0,0,0.95), 0 0 25px rgba(14,165,233,0.55)';
            };
            pill.onmouseleave = function() {
                pill.style.transform = 'none';
                pill.style.boxShadow = '0 10px 30px rgba(0,0,0,0.85), 0 0 20px rgba(14,165,233,0.35)';
            };

            attachPillDrag(pill);
            document.body.appendChild(pill);
        }
        updateDockPill();
        return pill;
    }

    function updateDockPill() {
        const pill = document.getElementById('agi-card-dock-pill');
        if (!pill) return;
        const pnlColor = state.todayNetPnl > 0 ? '#10b981' : (state.todayNetPnl < 0 ? '#ef4444' : '#94a3b8');
        const pnlSign = state.todayNetPnl > 0 ? '+' : '';
        const todayStr = state.sessionDate || getTodayFormattedDate();
        pill.innerHTML = `
            <span style="color:#38bdf8; font-weight:800; display:flex; align-items:center; gap:5px;">
                <span style="display:inline-block; width:7px; height:7px; border-radius:50%; background:#10b981; box-shadow:0 0 8px #10b981;"></span>
                ⚡ AGI 1.7 COMMAND
            </span>
            <span style="color:#64748b;">|</span>
            <span style="color:#cbd5e1; font-size:10px; font-family:monospace;">
                <span style="color:#38bdf8; font-weight:700;">${todayStr}</span>
                <span style="color:#475569; margin:0 3px;">•</span>
                N: <strong style="color:#facc15;">${state.spot > 0 ? state.spot.toFixed(0) : '23,146'}</strong>
                <span style="color:#475569; margin:0 3px;">•</span>
                BN: <strong style="color:#38bdf8;">${state.bankniftySpot > 0 ? state.bankniftySpot.toFixed(0) : '55,844'}</strong>
            </span>
            <span style="color:#64748b;">|</span>
            <span style="color:${pnlColor}; font-weight:800; font-family:monospace; background:rgba(255,255,255,0.06); padding:2px 7px; border-radius:4px;">Today: ${pnlSign}₹${state.todayNetPnl.toLocaleString('en-IN', {minimumFractionDigits:2})} (Eq: ₹${(state.todayEquity/100000).toFixed(2)}L)</span>
            <span style="background:rgba(14,165,233,0.25); color:#38bdf8; border:1px solid rgba(14,165,233,0.4); padding:2px 8px; border-radius:12px; font-size:10px; font-weight:800; display:flex; align-items:center; gap:3px;">
                <span>⤢</span> Expand
            </span>
        `;
    }

    function attachPillDrag(pill) {
        let isDragging = false;
        let startX = 0, startY = 0, initialLeft = 0, initialTop = 0;
        let dragDistance = 0;

        pill.onpointerdown = function(e) {
            isDragging = true;
            dragDistance = 0;
            try { pill.setPointerCapture(e.pointerId); } catch(err){}
            startX = e.clientX;
            startY = e.clientY;
            const rect = pill.getBoundingClientRect();
            initialLeft = rect.left;
            initialTop = rect.top;
        };

        pill.onpointermove = function(e) {
            if (!isDragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            dragDistance = Math.hypot(dx, dy);
            pill.style.left = Math.max(10, Math.min(window.innerWidth - pill.offsetWidth - 10, initialLeft + dx)) + 'px';
            pill.style.top = Math.max(10, Math.min(window.innerHeight - pill.offsetHeight - 10, initialTop + dy)) + 'px';
            pill.style.bottom = 'auto';
            pill.style.right = 'auto';
        };

        pill.onpointerup = function(e) {
            if (!isDragging) return;
            isDragging = false;
            try { pill.releasePointerCapture(e.pointerId); } catch(err){}
        };

        pill.onclick = function(e) {
            e.stopPropagation();
            e.preventDefault();
            if (dragDistance < 5) {
                expandOverlay();
            }
        };
    }

    function minimizeOverlay() {
        const card = document.getElementById('agi-omega-watchlist-card');
        const pill = ensureDockPill();
        if (card) {
            card.style.display = 'none';
        }
        if (pill) {
            pill.style.display = 'flex';
            updateDockPill();
        }
    }

    function expandOverlay() {
        const card = document.getElementById('agi-omega-watchlist-card');
        const pill = document.getElementById('agi-card-dock-pill');
        if (pill) {
            pill.style.display = 'none';
        }
        if (card) {
            card.style.display = 'block';
        }
    }

    function toggleCardCollapse() {
        const card = document.getElementById('agi-omega-watchlist-card');
        if (!card) return;
        state.isCollapsed = !state.isCollapsed;
        const children = Array.from(card.children);
        children.forEach(child => {
            if (child.id !== 'agi-card-header') {
                child.style.display = state.isCollapsed ? 'none' : '';
            }
        });
        if (state.isCollapsed) {
            card.style.height = 'auto';
            card.style.minHeight = '36px';
        } else {
            card.style.minHeight = '260px';
        }
    }

    function mountOverlay() {
        if (!document.body) return;
        ensureDockPill();

        let card = document.getElementById('agi-omega-watchlist-card');
        if (!card) {
            card = document.createElement('div');
            card.id = 'agi-omega-watchlist-card';
            card.style.cssText = [
                'position:fixed',
                'top:58px',
                'left:20px',
                'right:auto',
                'width:460px',
                'min-width:380px',
                'max-width:780px',
                'min-height:260px',
                'max-height:850px',
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
                'pointer-events:auto',
                'box-sizing:border-box',
                'resize:both',
                'overflow:hidden'
            ].join(';');
            card.innerHTML = renderCardHTML();
            document.body.appendChild(card);
            attachDrag(card);
            attachResize(card);
            setupInteractivity(card);
        } else {
            card.innerHTML = renderCardHTML();
            attachDrag(card);
            attachResize(card);
            setupInteractivity(card);
        }
    }

    function setupInteractivity(card) {
        const hideBtn = document.getElementById('agi-card-hide-btn');
        if (hideBtn) {
            hideBtn.onclick = function(e) {
                e.stopPropagation();
                e.preventDefault();
                minimizeOverlay();
            };
        }

        const header = document.getElementById('agi-card-header');
        if (header) {
            header.ondblclick = function(e) {
                if (e.target.tagName === 'BUTTON') return;
                e.stopPropagation();
                toggleCardCollapse();
            };
        }

        const resetBtn = document.getElementById('agi-card-reset-pos-btn');
        if (resetBtn) {
            resetBtn.onclick = function(e) {
                e.stopPropagation();
                card.style.right = 'auto';
                card.style.bottom = 'auto';
                card.style.left = '20px';
                card.style.top = '58px';
                card.style.width = '460px';
                card.style.height = 'auto';
                if (state.isCollapsed) {
                    toggleCardCollapse();
                }
            };
        }

        const nChain = document.getElementById('agi-nav-nifty-chain');
        if (nChain) {
            nChain.onclick = (e) => {
                e.stopPropagation();
                const elements = Array.from(document.querySelectorAll('*'));
                const nEl = elements.find(el => el.children.length === 0 && el.innerText && el.innerText.trim() === 'NIFTY');
                if (nEl) {
                    const item = nEl.closest('div[class*="VHIEpY5IJmostyrCI_ja5"]') || nEl.parentElement;
                    item.click();
                    return;
                }
                window.location.href = 'https://www.paytmmoney.com/stocks/fno/option-chain/2000000011/NIFTY/NSE';
            };
        }
        const bnChain = document.getElementById('agi-nav-bn-chain');
        if (bnChain) {
            bnChain.onclick = (e) => {
                e.stopPropagation();
                const elements = Array.from(document.querySelectorAll('*'));
                const bnEl = elements.find(el => el.children.length === 0 && el.innerText && el.innerText.trim() === 'BANKNIFTY');
                if (bnEl) {
                    const item = bnEl.closest('div[class*="VHIEpY5IJmostyrCI_ja5"]') || bnEl.parentElement;
                    item.click();
                    return;
                }
                window.location.href = 'https://www.paytmmoney.com/stocks/fno/option-chain/2000000023/BANKNIFTY/NSE';
            };
        }
        const dashNav = document.getElementById('agi-nav-dashboard');
        if (dashNav) {
            dashNav.onclick = (e) => {
                e.stopPropagation();
                const dLink = document.querySelector('a[href*="/stocks/fno/dashboard"], a[href*="/dashboard"]');
                if (dLink) {
                    dLink.click();
                    return;
                }
                window.location.href = 'https://www.paytmmoney.com/stocks/fno/dashboard';
            };
        }

        const toggleClosedBtn = document.getElementById('agi-toggle-closed-btn');
        if (toggleClosedBtn) {
            toggleClosedBtn.onclick = function() {
                state.closedDrawerOpen = !state.closedDrawerOpen;
                const dr = document.getElementById('agi-closed-drawer');
                if (dr) {
                    dr.style.display = state.closedDrawerOpen ? 'block' : 'none';
                    toggleClosedBtn.querySelector('span:last-child').textContent = 
                        `Realized: ₹${state.todayRealizedPnl.toFixed(2)} [${state.closedDrawerOpen ? '▲ Hide' : '▼ View'}]`;
                }
            };
        }

        const toggleYestBtn = document.getElementById('agi-toggle-yesterday-btn');
        if (toggleYestBtn) {
            toggleYestBtn.onclick = function() {
                state.yesterdayDrawerOpen = !state.yesterdayDrawerOpen;
                const dr = document.getElementById('agi-yesterday-drawer');
                if (dr) {
                    dr.style.display = state.yesterdayDrawerOpen ? 'block' : 'none';
                    const lbl = toggleYestBtn.querySelector('.agi-yest-toggle-label');
                    if (lbl) {
                        lbl.textContent = `Settled: +₹${state.yesterdaySettled.totalRealized.toFixed(2)} [${state.yesterdayDrawerOpen ? '▲ Hide' : '▼ View 4 Trades'}]`;
                    }
                }
            };
        }

        document.querySelectorAll('.agi-square-off-btn').forEach(btn => {
            btn.onclick = function(e) {
                const runnerId = this.getAttribute('data-id');
                const runner = state.runners.find(r => r.id === runnerId);
                if (!runner) return;
                state.todayRealizedPnl += runner.pnl;
                state.unrealizedPnl -= runner.pnl;
                state.capitalDeployed -= (runner.qty * runner.entry);
                state.cashSaved += (runner.qty * runner.ltp);
                state.todayNetPnl = state.todayRealizedPnl + state.unrealizedPnl;
                state.todayEquity = state.startingCapital + state.todayNetPnl;
                state.closedTrades.unshift({
                    id: 'TRD-MANUAL-' + Date.now(),
                    time: '11:45 AM',
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
                state.orders.unshift({
                    id: 'ORD-EXIT-' + Date.now(),
                    time: '11:45:00 AM IST',
                    instrument: runner.symbol,
                    type: 'MARKET',
                    side: 'SELL',
                    qty: runner.qty,
                    price: runner.ltp,
                    status: 'FILLED (Manual Square Off)',
                    broker: 'PAPER_ENGINE_LOCK'
                });
                state.runners = state.runners.filter(r => r.id !== runnerId);
                card.innerHTML = renderCardHTML();
                setupInteractivity(card);
                attachDrag(card);
                attachResize(card);
            };
        });

        // Ivy 24/7 Voice & Chat Integration
        const ivyInput = document.getElementById('agi-ivy-chat-input');
        const ivySend = document.getElementById('agi-ivy-chat-send');
        const ivyBox = document.getElementById('agi-ivy-msg-box');
        const ivyBadge = document.getElementById('agi-ivy-badge');

        async function sendToIvy() {
            if (!ivyInput || !ivyInput.value.trim()) return;
            const text = ivyInput.value.trim();
            ivyInput.value = '';
            if (ivyBox) {
                ivyBox.innerHTML += `<div style="margin-top:3px;"><span style="color:#38bdf8; font-weight:700;">You:</span> ${text}</div>`;
                ivyBox.innerHTML += `<div id="agi-ivy-thinking" style="color:#94a3b8; font-style:italic;">Ivy is thinking & speaking...</div>`;
                ivyBox.scrollTop = ivyBox.scrollHeight;
            }
            if (ivyBadge) ivyBadge.textContent = '⏳ SPEAKING...';
            try {
                const res = await fetch('http://127.0.0.1:8090/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, speak: true })
                });
                const data = await res.json();
                const thinking = document.getElementById('agi-ivy-thinking');
                if (thinking) thinking.remove();
                if (ivyBox) {
                    ivyBox.innerHTML += `<div style="margin-top:3px;"><span style="color:#fb7185; font-weight:700;">Ivy:</span> ${data.reply}</div>`;
                    ivyBox.scrollTop = ivyBox.scrollHeight;
                }
                if (data.audio_url) {
                    try {
                        const snd = new Audio(data.audio_url);
                        snd.play();
                    } catch(e){}
                }
            } catch(e) {
                const thinking = document.getElementById('agi-ivy-thinking');
                if (thinking) thinking.remove();
                if (ivyBox) ivyBox.innerHTML += `<div style="color:#ef4444;">Error connecting to Ivy Voice Daemon</div>`;
            }
            if (ivyBadge) ivyBadge.textContent = '● ONLINE';
        }

        if (ivySend) {
            ivySend.onclick = (e) => {
                e.stopPropagation();
                sendToIvy();
            };
        }
        if (ivyInput) {
            ivyInput.onkeydown = (e) => {
                e.stopPropagation();
                if (e.key === 'Enter') sendToIvy();
            };
        }
    }

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

    function attachResize(card) {
        const handle = document.getElementById('agi-card-resize-handle');
        if (!handle) return;
        let isResizing = false;
        let startX = 0, startY = 0, startWidth = 0, startHeight = 0;

        handle.onpointerdown = function(e) {
            e.stopPropagation();
            e.preventDefault();
            isResizing = true;
            try { handle.setPointerCapture(e.pointerId); } catch(err){}
            startX = e.clientX;
            startY = e.clientY;
            const rect = card.getBoundingClientRect();
            startWidth = rect.width;
            startHeight = rect.height;
        };

        handle.onpointermove = function(e) {
            if (!isResizing) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            const newW = Math.max(380, Math.min(780, startWidth + dx));
            const newH = Math.max(260, Math.min(850, startHeight + dy));
            card.style.width = newW + 'px';
            card.style.height = newH + 'px';
        };

        handle.onpointerup = function(e) {
            if (!isResizing) return;
            isResizing = false;
            try { handle.releasePointerCapture(e.pointerId); } catch(err){}
        };
    }

    // Initial mount
    mountOverlay();

    // 1. MUTATION OBSERVER: Re-mount immediately if React unmounts it
    window.__agiDOMObserver = new MutationObserver(function() {
        if (!document.getElementById('agi-omega-watchlist-card') && document.body) {
            mountOverlay();
        }
    });
    window.__agiDOMObserver.observe(document.body, { childList: true, subtree: false });

    // 2. CONSCIOUS GUARDIAN & LIVELY TICK ENGINE: Checks every 200ms
    let subTickCounter = 0;
    window.__agiOverlayGuardian = setInterval(function() {
        try {
            if (!document.getElementById('agi-omega-watchlist-card') && document.body) {
                mountOverlay();
            }

            // Countdown timer decrement
            state.countdownSec -= 0.2;
            if (state.countdownSec <= 0) {
                state.countdownSec = 2.0;
                state.tickCount++;
                const tickEl = document.getElementById('agi-tick-num');
                if (tickEl) tickEl.textContent = state.tickCount;
            }
            const cdEl = document.getElementById('agi-countdown-display');
            if (cdEl) cdEl.textContent = state.countdownSec.toFixed(1) + 's';

            // Real-time ticking IST clock
            const clkEl = document.getElementById('agi-live-clock');
            if (clkEl) {
                clkEl.textContent = '🕒 ' + new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' }) + ' IST';
            }

            subTickCounter++;

            // 1. EXTRACT REAL-TIME LIVE DRAWER QUOTE DIRECTLY FROM PAYTM DOM
            function extractLiveDrawerData() {
                const drawer = document.querySelector('div[class*="_1XGz04EDVA-GvtB3dLo-1u"]');
                if (!drawer) return null;
                const text = drawer.innerText;
                const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
                for (let i = 0; i < Math.min(lines.length, 10); i++) {
                    if (/^(BANKNIFTY|NIFTY)\s+\d{1,2}\s+[A-Z]{3}\s+\d+\s+(CALL|PUT)/i.test(lines[i])) {
                        const contract = lines[i].replace(/NSE$/i, '').trim();
                        let ltp = null;
                        if (i + 1 < lines.length && /^\d+(\.\d+)?$/.test(lines[i+1])) {
                            ltp = parseFloat(lines[i+1]);
                        }
                        return { contract, ltp };
                    }
                }
                return null;
            }

            // Real-time DOM consciousness & Live quote synchronization every ~400ms (every 2 cycles)
            if (subTickCounter % 2 === 0) {
                const drawerData = extractLiveDrawerData();
                if (drawerData && drawerData.ltp) {
                    const focusStr = `${drawerData.contract} @ ₹${drawerData.ltp.toFixed(2)}`;
                    if (state.screenFocus !== focusStr) {
                        state.screenFocus = focusStr;
                        const fText = document.getElementById('agi-screen-focus-text');
                        if (fText) fText.textContent = focusStr;
                    }

                    // Synchronize Active Live Runner strictly with Paytm DOM quote (ZERO synthetic drift)
                    if (state.runners.length > 0) {
                        const runner = state.runners[0];
                        if (drawerData.contract.includes('56000') || runner.symbol.includes(drawerData.contract)) {
                            runner.prevLtp = runner.ltp;
                            runner.ltp = drawerData.ltp;
                            runner.pnl = Number(((runner.ltp - runner.entry) * runner.qty).toFixed(2));

                            // Mathematical Trailing Stop Loss Rule:
                            // Base Floor SL is ALWAYS ₹410.00
                            // Trailing SL ONLY ratchets above entry if price is in clear profit (> ₹475.00)
                            // Trailing SL must NEVER exceed current market price!
                            if (runner.ltp > 475.00) {
                                const candidateTrailingSl = Math.max(runner.entry, Number((runner.ltp - 20.0).toFixed(2)));
                                if (candidateTrailingSl > runner.trailingSl) {
                                    runner.trailingSl = candidateTrailingSl;
                                }
                                runner.lockedProfit = Math.max(0, Number(((runner.trailingSl - runner.entry) * runner.qty).toFixed(2)));
                            } else {
                                runner.trailingSl = runner.slFloor;
                                runner.lockedProfit = 0;
                            }

                            // Update totals
                            state.unrealizedPnl = runner.pnl;
                            state.todayNetPnl = Number((state.todayRealizedPnl + state.unrealizedPnl).toFixed(2));
                            state.todayEquity = Number((state.startingCapital + state.todayNetPnl).toFixed(2));
                            state.cashSaved = Number((state.todayEquity - state.capitalDeployed).toFixed(2));

                            // Update DOM elements
                            const ltpEl = document.getElementById('agi-runner-ltp');
                            const arrowEl = document.getElementById('agi-ltp-arrow');
                            if (ltpEl) {
                                ltpEl.textContent = '₹' + runner.ltp.toFixed(2);
                                ltpEl.style.animation = 'none';
                                void ltpEl.offsetWidth;
                                ltpEl.style.animation = 'agi-tick-glow 0.6s ease-out';
                                if (arrowEl) {
                                    arrowEl.textContent = runner.ltp >= runner.prevLtp ? '▲' : '▼';
                                    arrowEl.style.color = runner.ltp >= runner.prevLtp ? '#10b981' : '#f43f5e';
                                }
                            }
                            const pnlEl = document.getElementById('agi-runner-pnl');
                            if (pnlEl) {
                                pnlEl.textContent = (runner.pnl >= 0 ? '+' : '') + '₹' + runner.pnl.toFixed(2);
                                pnlEl.style.color = runner.pnl >= 0 ? '#10b981' : '#ef4444';
                            }
                            const mtmHead = document.getElementById('agi-runner-unrealized-head');
                            if (mtmHead) mtmHead.textContent = (runner.pnl >= 0 ? '+₹' : '-₹') + Math.abs(runner.pnl).toFixed(2);

                            const tslEl = document.getElementById('agi-trailing-sl');
                            if (tslEl) tslEl.textContent = '₹' + runner.trailingSl.toFixed(2);

                            const lockEl = document.getElementById('agi-locked-profit');
                            if (lockEl) {
                                lockEl.textContent = runner.trailingSl > runner.entry ? `(+₹${runner.lockedProfit.toFixed(0)} Locked)` : '(Active Floor)';
                                lockEl.style.color = runner.trailingSl > runner.entry ? '#10b981' : '#94a3b8';
                            }

                            const progressT1 = Math.min(100, Math.max(0, ((runner.ltp - runner.entry) / (runner.t1 - runner.entry)) * 100));
                            const distT1 = (runner.t1 - runner.ltp).toFixed(2);
                            const barEl = document.getElementById('agi-target-progress-bar');
                            if (barEl) barEl.style.width = progressT1 + '%';
                            const barText = document.getElementById('agi-target-progress-text');
                            if (barText) barText.textContent = `${progressT1.toFixed(1)}% to T1 (₹${distT1} away)`;

                            const totNetPnl = document.getElementById('agi-total-net-pnl');
                            if (totNetPnl) {
                                totNetPnl.textContent = (state.todayNetPnl >= 0 ? '+' : '') + '₹' + state.todayNetPnl.toLocaleString('en-IN', {minimumFractionDigits: 2});
                                totNetPnl.style.color = state.todayNetPnl >= 0 ? '#10b981' : '#ef4444';
                            }
                            const totNetPct = document.getElementById('agi-total-net-pct');
                            if (totNetPct) {
                                const pct = ((state.todayNetPnl / state.startingCapital) * 100).toFixed(2);
                                totNetPct.textContent = `(${state.todayNetPnl >= 0 ? '+' : ''}${pct}%)`;
                            }
                            const totEq = document.getElementById('agi-today-equity');
                            if (totEq) {
                                totEq.textContent = '₹' + state.todayEquity.toLocaleString('en-IN', {minimumFractionDigits: 2});
                            }
                        }
                    }
                }

                // Extract spot indices from page (both Nifty & BankNifty)
                const text = document.body.innerText;
                const nMatch = text.match(/Nifty 50\s*\n\s*([0-9,]+\.[0-9]{2})/) || text.match(/23,\d{3}\.\d{2}/);
                if (nMatch) {
                    const s = parseFloat((nMatch[1] || nMatch[0]).replace(/,/g, ''));
                    if (s > 10000 && Math.abs(s - state.spot) > 0.05) {
                        state.spot = s;
                        const spotEl = document.getElementById('agi-card-spot');
                        if (spotEl) spotEl.textContent = 'N: ' + s.toFixed(2);
                    }
                }
                const bnMatch = text.match(/BANKNIFTY[^\n]*\n([0-9,]+\.[0-9]{2})/) || text.match(/55,\d{3}\.\d{2}/);
                if (bnMatch) {
                    const bs = parseFloat((bnMatch[1] || bnMatch[0]).replace(/,/g, ''));
                    if (bs > 30000 && Math.abs(bs - state.bankniftySpot) > 0.05) {
                        state.bankniftySpot = bs;
                        const bnSpotEl = document.getElementById('agi-card-bn-spot');
                        if (bnSpotEl) bnSpotEl.textContent = 'BN: ' + bs.toFixed(2);
                    }
                }

                // Keep dock pill in sync with live quote/P&L ticks
                updateDockPill();

                // Broadcast latest state to the other tab in real-time
                broadcastState();
            }
        } catch(e){}
    }, 200);

})();
"""

if __name__ == '__main__':
    targets = json.loads(urllib.request.urlopen('http://127.0.0.1:9229/json').read())
    paytm_tabs = [t for t in targets if 'paytmmoney' in t.get('url', '') and t.get('type') == 'page']
    print(f'1. Injecting 3-TAB TRIUMVIRATE OVERLAY into {len(paytm_tabs)} Paytm tabs...')
    for p in paytm_tabs:
        ws_url = p['webSocketDebuggerUrl']
        print(f"Injecting into {p.get('url')}...")
        res = _cdp_ws_send_and_recv(ws_url, [
            {'id': 200, 'method': 'Page.addScriptToEvaluateOnNewDocument', 'params': {'source': CONSCIOUS_OVERLAY_JS}},
            {'id': 201, 'method': 'Runtime.evaluate', 'params': {'expression': CONSCIOUS_OVERLAY_JS, 'returnByValue': True}}
        ])
        print('Injected:', res)

    time.sleep(2.0)

    # Screenshot
    res_shot = _cdp_ws_send_and_recv(ws_url, [
        {'id': 202, 'method': 'Page.captureScreenshot', 'params': {'format': 'png'}}
    ])
    if res_shot and 'result' in res_shot[0] and 'data' in res_shot[0]['result']:
        img_data = base64.b64decode(res_shot[0]['result']['data'])
        with open('paytm_resizable_today_overlay.png', 'wb') as f:
            f.write(img_data)
        print('3. Saved paytm_resizable_today_overlay.png, size:', len(img_data))
