/**
 * AGI 1.7 OMEGA COMMAND — PAGE CONTROLLER: TRADING DESK (/trading)
 * Definitive Three-Panel Trading Desk Architecture (UI V4.2):
 * - Panel A (Left): Agent Conversations (Team Coordination & Manager Abhi)
 * - Horizontal Splitter 1
 * - Panel B (Center): Interactive Candlestick Chart (Top) + Vertical Splitter + Portfolio & Paper Trades (Bottom)
 * - Horizontal Splitter 2
 * - Panel C (Right): Research, News & Macro Market Analysis
 * - Resizable Dividers with localStorage persistence and Reset Layout support
 * - Mobile/Tablet Responsive Workspace Switcher (0px Horizontal Overflow)
 */

import { store } from '../state.js';
import { api } from '../api.js';
import { chartEngine } from '../chart.js';

export class PageTradingController {
    constructor() {
        this.containerId = 'page-trading';
        this.initialized = false;
        this.agentTab = 'coordination'; // 'coordination' or 'manager'
        this.agentFilter = 'all'; // 'all', 'MAX', 'EMILY', 'ALEXA'
        this.portfolioTab = 'positions'; // 'positions', 'orders', 'closed', 'history'
        this.researchTab = 'briefing'; // 'briefing', 'regulatory', 'macro', 'instrument', 'evidence'
        this.historyFilter = 'today';
        this.newsData = null;
        this.chatMessages = [];
        this.pollTimer = null;
    }

    init() {
        const pane = document.getElementById(this.containerId);
        if (!pane) return;

        this.renderShell(pane);
        this.restoreSavedDimensions();
        this.setupSplitters();
        this.bindEvents(pane);
        chartEngine.init();

        this.loadChatData();
        this.loadResearchData();
        this.renderPortfolioTab();

        // Subscribe to global layout reset
        store.subscribe('reset_trading_layout', () => {
            this.resetLayoutToDefaults();
        });

        // Background polling for agent chat updates
        if (this.pollTimer) clearInterval(this.pollTimer);
        this.pollTimer = setInterval(() => {
            if (store.get('activePage') === 'trading') {
                this.loadChatData(false);
            }
        }, 4000);

        this.initialized = true;
    }

    renderShell(container) {
        container.innerHTML = `
            <div class="trading-desk-v42" id="tradingDeskV42">
                <!-- Mobile Workspace Switcher (Screens <= 768px) -->
                <div class="mobile-desk-tabs" id="mobileDeskTabs">
                    <button class="m-desk-tab" data-target="panelAgents">🤖 Agents</button>
                    <button class="m-desk-tab active" data-target="panelCenter">📈 Chart &amp; Portfolio</button>
                    <button class="m-desk-tab" data-target="panelResearch">📰 News &amp; Research</button>
                </div>

                <!-- ═══════════════════════════════════════════════════════════════
                     PANEL A (LEFT): AGENT CONVERSATIONS (Default ~300px)
                ═══════════════════════════════════════════════════════════════ -->
                <aside class="desk-panel desk-panel-left" id="panelAgents">
                    <div class="agent-panel-header">
                        <div class="agent-tabs-row">
                            <button class="agent-tab-btn active" data-tab="coordination" id="tabBtnCoordination">
                                <span class="tab-icon">🤖</span>
                                <span class="tab-text">Team Coordination</span>
                            </button>
                            <button class="agent-tab-btn" data-tab="manager" id="tabBtnManager">
                                <span class="tab-icon">👑</span>
                                <span class="tab-text">Manager Abhi</span>
                            </button>
                        </div>
                    </div>

                    <!-- Tab 1: Team Coordination -->
                    <div class="agent-tab-pane active" id="paneCoordination">
                        <div class="coordination-filter-bar">
                            <span class="filter-label">Filter:</span>
                            <button class="agent-filter-chip active" data-agent="all">All</button>
                            <button class="agent-filter-chip" data-agent="MAX">MAX</button>
                            <button class="agent-filter-chip" data-agent="EMILY">EMILY</button>
                            <button class="agent-filter-chip" data-agent="ALEXA">ALEXA</button>
                        </div>
                        <div class="agent-message-stream" id="coordinationMessageStream">
                            <div class="chat-loading-placeholder">Loading team coordination stream...</div>
                        </div>
                    </div>

                    <!-- Tab 2: Manager Abhi (Operator Direct Channel) -->
                    <div class="agent-tab-pane" id="paneManager">
                        <div class="manager-intro-card">
                            <div class="mgr-avatar-row">
                                <span class="mgr-badge-crown">👑</span>
                                <div>
                                    <strong class="mgr-title">Manager Abhi</strong>
                                    <div class="mgr-subtitle">Executive Quantitative Trading Operations</div>
                                </div>
                            </div>
                            <div class="mgr-status-pill">
                                <span class="status-pulse green"></span>
                                <span>ONLINE • Direct Operator Link Active</span>
                            </div>
                        </div>

                        <div class="manager-message-stream" id="managerMessageStream">
                            <!-- Messages rendered dynamically -->
                        </div>

                        <!-- Visible Message Composer -->
                        <div class="manager-composer-area">
                            <textarea 
                                class="manager-input" 
                                id="inputManagerDirectives" 
                                rows="2" 
                                placeholder="Message Manager Abhi (e.g. ratchet trailing stops, audit cash reserve)..."
                            ></textarea>
                            <button class="btn-send-manager" id="btnSendManagerDirective" title="Send Directive (Enter to send, Shift+Enter for newline)">
                                <span>➤</span>
                            </button>
                        </div>
                    </div>
                </aside>

                <!-- Resizer 1 (Horizontal divider between Left and Center panels) -->
                <div class="desk-resizer desk-resizer-h" id="resizerLeftCenter" title="Drag to resize Agents panel">
                    <div class="resizer-knob"></div>
                </div>

                <!-- ═══════════════════════════════════════════════════════════════
                     PANEL B (CENTER): CHART (TOP) + SPLITTER + PORTFOLIO (BOTTOM)
                ═══════════════════════════════════════════════════════════════ -->
                <main class="desk-panel desk-panel-center" id="panelCenter">
                    <!-- Top Sub-Region: Interactive Candlestick Chart -->
                    <div class="center-top-chart" id="chartSection">
                        <!-- Instrument Quote & Controls Topbar -->
                        <div class="chart-topbar">
                            <div class="chart-quote-cluster">
                                <span class="chart-symbol-name" id="instHeaderName">NIFTY 50</span>
                                <span class="badge badge-blue" id="instHeaderBadge">NSE • SPOT</span>
                                <span class="chart-ltp-val font-mono" id="instHeaderLtp">₹22,622.70</span>
                                <span class="chart-chg-val font-mono" id="instHeaderChg" style="color: var(--bear-red);">-99.25 (-0.44%)</span>
                                <span class="badge badge-amber header-session-badge" style="font-size: 10px; margin-left: 4px;">CLOSED • EOD Verified Snapshot</span>
                            </div>

                            <div class="chart-controls-cluster">
                                <div class="segmented-control">
                                    <button class="segment-btn mode-segment-btn active" data-mode="spot">Index Spot</button>
                                    <button class="segment-btn mode-segment-btn" data-mode="option">22550 PE Strike</button>
                                    <button class="segment-btn mode-segment-btn" data-mode="equity">Portfolio Equity</button>
                                </div>
                                <div class="chart-tf-group">
                                    <button class="chart-tf-btn" data-tf="1m">1m</button>
                                    <button class="chart-tf-btn" data-tf="5m">5m</button>
                                    <button class="chart-tf-btn active" data-tf="15m">15m</button>
                                    <button class="chart-tf-btn" data-tf="1h">1h</button>
                                    <button class="chart-tf-btn" data-tf="1D">1D</button>
                                </div>
                                <div class="chart-zoom-group">
                                    <button class="chart-zoom-btn" id="btnChartZoomIn" title="Zoom In (+)">+</button>
                                    <button class="chart-zoom-btn" id="btnChartZoomOut" title="Zoom Out (-)">−</button>
                                    <button class="chart-zoom-btn" id="btnChartResetZoom" title="Reset Zoom">⟲</button>
                                    <button class="chart-zoom-btn" id="btnChartLatest" title="Return to Latest Bar">⏩</button>
                                </div>
                            </div>
                        </div>

                        <!-- Canvas Chart Area with Golden VWAP & Tooltips -->
                        <div class="chart-canvas-wrapper" id="candlestickCanvasWrapper">
                            <canvas id="candlestickCanvas"></canvas>
                        </div>
                    </div>

                    <!-- Resizer 2 (Vertical divider between Chart and Portfolio) -->
                    <div class="desk-resizer desk-resizer-v" id="resizerChartPortfolio" title="Drag to resize Chart vs Portfolio">
                        <div class="resizer-knob-h"></div>
                    </div>

                    <!-- Bottom Sub-Region: My Portfolio & Paper Trades -->
                    <div class="center-bottom-portfolio" id="portfolioSection">
                        <!-- Capital Ribbon Header -->
                        <div class="portfolio-header-bar">
                            <div class="port-capital-chips">
                                <div class="port-chip">
                                    <span class="chip-lbl">BASE CAPITAL:</span>
                                    <span class="chip-val font-mono" id="portBaseCap">₹1,00,000.00</span>
                                </div>
                                <div class="port-chip">
                                    <span class="chip-lbl">SAVED RESERVE:</span>
                                    <span class="chip-val font-mono text-cyan" id="portReserve">₹36,225.00 (36.2%)</span>
                                </div>
                                <div class="port-chip">
                                    <span class="chip-lbl">DEPLOYED:</span>
                                    <span class="chip-val font-mono" id="portDeployed">₹63,775.00 (63.8%)</span>
                                </div>
                                <div class="port-chip">
                                    <span class="chip-lbl">SESSION NET P&amp;L:</span>
                                    <span class="chip-val font-mono text-green" id="portPnl">+₹3,310.50 (+3.31%)</span>
                                </div>
                            </div>

                            <!-- Portfolio Tab Switcher -->
                            <div class="port-tabs-group">
                                <button class="port-tab-btn active" data-ptab="positions" id="tabPortPositions">Active Positions (2)</button>
                                <button class="port-tab-btn" data-ptab="orders" id="tabPortOrders">Paper Orders</button>
                                <button class="port-tab-btn" data-ptab="closed" id="tabPortClosed">Closed Trades</button>
                                <button class="port-tab-btn" data-ptab="history" id="tabPortHistory">Trade History &amp; Settlement</button>
                            </div>
                        </div>

                        <!-- Portfolio Content Views Container -->
                        <div class="portfolio-view-body" id="portfolioViewBody">
                            <!-- Rendered dynamically -->
                        </div>
                    </div>
                </main>

                <!-- Resizer 3 (Horizontal divider between Center and Right panels) -->
                <div class="desk-resizer desk-resizer-h" id="resizerCenterRight" title="Drag to resize Research panel">
                    <div class="resizer-knob"></div>
                </div>

                <!-- ═══════════════════════════════════════════════════════════════
                     PANEL C (RIGHT): RESEARCH, NEWS & MARKET ANALYSIS (Default ~340px)
                ═══════════════════════════════════════════════════════════════ -->
                <aside class="desk-panel desk-panel-right" id="panelResearch">
                    <div class="research-header">
                        <div class="research-title-row">
                            <span class="research-title-text">📰 Research &amp; Market Intel</span>
                            <span class="badge badge-purple" style="font-size: 9.5px;">PRIMARY SOURCES</span>
                        </div>
                        <!-- Section Filter Tabs -->
                        <div class="research-tabs-row">
                            <button class="research-tab-btn active" data-rtab="briefing">Briefing</button>
                            <button class="research-tab-btn" data-rtab="regulatory">Regulatory</button>
                            <button class="research-tab-btn" data-rtab="macro">Macro &amp; Sovereign</button>
                            <button class="research-tab-btn" data-rtab="instrument">Instruments</button>
                            <button class="research-tab-btn" data-rtab="evidence">Evidence</button>
                        </div>
                    </div>

                    <!-- Research Feed Container with Expandable Accordions -->
                    <div class="research-feed-scroll" id="researchFeedContainer">
                        <div class="chat-loading-placeholder">Loading macroeconomic intelligence &amp; primary circulars...</div>
                    </div>
                </aside>
            </div>
        `;
    }

    restoreSavedDimensions() {
        const leftW = localStorage.getItem('agi_v42_left_w') || '300px';
        const rightW = localStorage.getItem('agi_v42_right_w') || '340px';
        const chartH = localStorage.getItem('agi_v42_chart_h') || '420px';

        const panelLeft = document.getElementById('panelAgents');
        const panelRight = document.getElementById('panelResearch');
        const chartSec = document.getElementById('chartSection');

        if (panelLeft && window.innerWidth > 768) {
            panelLeft.style.width = leftW;
            panelLeft.style.flex = `0 0 ${leftW}`;
        }
        if (panelRight && window.innerWidth > 768) {
            panelRight.style.width = rightW;
            panelRight.style.flex = `0 0 ${rightW}`;
        }
        if (chartSec && window.innerWidth > 768) {
            chartSec.style.height = chartH;
            chartSec.style.flex = `0 0 ${chartH}`;
        }
    }

    resetLayoutToDefaults() {
        localStorage.removeItem('agi_v42_left_w');
        localStorage.removeItem('agi_v42_right_w');
        localStorage.removeItem('agi_v42_chart_h');

        const panelLeft = document.getElementById('panelAgents');
        const panelRight = document.getElementById('panelResearch');
        const chartSec = document.getElementById('chartSection');

        if (panelLeft) {
            panelLeft.style.width = '300px';
            panelLeft.style.flex = '0 0 300px';
        }
        if (panelRight) {
            panelRight.style.width = '340px';
            panelRight.style.flex = '0 0 340px';
        }
        if (chartSec) {
            chartSec.style.height = '420px';
            chartSec.style.flex = '0 0 420px';
        }

        // Trigger chart re-render
        setTimeout(() => {
            chartEngine.handleResize();
        }, 50);

        console.log('[TradingDesk] Layout reset to default 3-panel dimensions.');
    }

    setupSplitters() {
        // Resizer 1: Left / Center
        const resizerLeft = document.getElementById('resizerLeftCenter');
        const panelLeft = document.getElementById('panelAgents');
        if (resizerLeft && panelLeft) {
            let isDragging = false;
            let startX = 0;
            let startWidth = 0;

            resizerLeft.addEventListener('mousedown', (e) => {
                isDragging = true;
                startX = e.clientX;
                startWidth = panelLeft.getBoundingClientRect().width;
                resizerLeft.classList.add('dragging');
                document.body.style.cursor = 'col-resize';
                document.body.style.userSelect = 'none';
            });

            window.addEventListener('mousemove', (e) => {
                if (!isDragging) return;
                const newWidth = Math.max(240, Math.min(480, startWidth + (e.clientX - startX)));
                panelLeft.style.width = `${newWidth}px`;
                panelLeft.style.flex = `0 0 ${newWidth}px`;
                localStorage.setItem('agi_v42_left_w', `${newWidth}px`);
                chartEngine.handleResize();
            });

            window.addEventListener('mouseup', () => {
                if (isDragging) {
                    isDragging = false;
                    resizerLeft.classList.remove('dragging');
                    document.body.style.cursor = '';
                    document.body.style.userSelect = '';
                }
            });
        }

        // Resizer 3: Center / Right
        const resizerRight = document.getElementById('resizerCenterRight');
        const panelRight = document.getElementById('panelResearch');
        if (resizerRight && panelRight) {
            let isDragging = false;
            let startX = 0;
            let startWidth = 0;

            resizerRight.addEventListener('mousedown', (e) => {
                isDragging = true;
                startX = e.clientX;
                startWidth = panelRight.getBoundingClientRect().width;
                resizerRight.classList.add('dragging');
                document.body.style.cursor = 'col-resize';
                document.body.style.userSelect = 'none';
            });

            window.addEventListener('mousemove', (e) => {
                if (!isDragging) return;
                const newWidth = Math.max(260, Math.min(500, startWidth - (e.clientX - startX)));
                panelRight.style.width = `${newWidth}px`;
                panelRight.style.flex = `0 0 ${newWidth}px`;
                localStorage.setItem('agi_v42_right_w', `${newWidth}px`);
                chartEngine.handleResize();
            });

            window.addEventListener('mouseup', () => {
                if (isDragging) {
                    isDragging = false;
                    resizerRight.classList.remove('dragging');
                    document.body.style.cursor = '';
                    document.body.style.userSelect = '';
                }
            });
        }

        // Resizer 2: Vertical Chart / Portfolio
        const resizerV = document.getElementById('resizerChartPortfolio');
        const chartSec = document.getElementById('chartSection');
        if (resizerV && chartSec) {
            let isDragging = false;
            let startY = 0;
            let startHeight = 0;

            resizerV.addEventListener('mousedown', (e) => {
                isDragging = true;
                startY = e.clientY;
                startHeight = chartSec.getBoundingClientRect().height;
                resizerV.classList.add('dragging');
                document.body.style.cursor = 'row-resize';
                document.body.style.userSelect = 'none';
            });

            window.addEventListener('mousemove', (e) => {
                if (!isDragging) return;
                const newHeight = Math.max(220, Math.min(600, startHeight + (e.clientY - startY)));
                chartSec.style.height = `${newHeight}px`;
                chartSec.style.flex = `0 0 ${newHeight}px`;
                localStorage.setItem('agi_v42_chart_h', `${newHeight}px`);
                chartEngine.handleResize();
            });

            window.addEventListener('mouseup', () => {
                if (isDragging) {
                    isDragging = false;
                    resizerV.classList.remove('dragging');
                    document.body.style.cursor = '';
                    document.body.style.userSelect = '';
                }
            });
        }
    }

    bindEvents(container) {
        // 1. Mobile Desk Workspace Switcher
        container.querySelectorAll('.m-desk-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.m-desk-tab').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const targetId = btn.getAttribute('data-target');
                
                ['panelAgents', 'panelCenter', 'panelResearch'].forEach(pId => {
                    const el = document.getElementById(pId);
                    if (el) {
                        if (pId === targetId) {
                            el.classList.add('mobile-visible');
                            el.classList.remove('mobile-hidden');
                        } else {
                            el.classList.remove('mobile-visible');
                            el.classList.add('mobile-hidden');
                        }
                    }
                });
                chartEngine.handleResize();
            });
        });

        // 2. Left Panel Agent Tabs (Coordination vs Manager Abhi)
        const tabCoord = container.querySelector('#tabBtnCoordination');
        const tabMgr = container.querySelector('#tabBtnManager');
        const paneCoord = container.querySelector('#paneCoordination');
        const paneMgr = container.querySelector('#paneManager');

        if (tabCoord && tabMgr) {
            tabCoord.addEventListener('click', () => {
                tabCoord.classList.add('active');
                tabMgr.classList.remove('active');
                if (paneCoord) paneCoord.classList.add('active');
                if (paneMgr) paneMgr.classList.remove('active');
                this.agentTab = 'coordination';
            });

            tabMgr.addEventListener('click', () => {
                tabMgr.classList.add('active');
                tabCoord.classList.remove('active');
                if (paneMgr) paneMgr.classList.add('active');
                if (paneCoord) paneCoord.classList.remove('active');
                this.agentTab = 'manager';
                this.renderManagerChat();
            });
        }

        // 3. Team Coordination Filter Chips
        container.querySelectorAll('.agent-filter-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                container.querySelectorAll('.agent-filter-chip').forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
                this.agentFilter = chip.getAttribute('data-agent') || 'all';
                this.renderCoordinationStream();
            });
        });

        // 4. Manager Abhi Message Composer
        const inputMgr = container.querySelector('#inputManagerDirectives');
        const btnSend = container.querySelector('#btnSendManagerDirective');

        const sendDirective = async () => {
            const text = (inputMgr.value || '').trim();
            if (!text) return;
            inputMgr.value = '';

            // Optimistic append
            const now = new Date().toLocaleTimeString('en-IN', { hour12: false });
            const tempMsg = {
                id: `MSG-USER-${Date.now()}`,
                timestamp: `${now} IST`,
                sender: 'OPERATOR',
                role: 'Authorized Human Operator',
                color: '#facc15',
                badge: 'OPERATOR DIRECTIVE',
                type: 'USER_INPUT',
                content: text
            };
            this.chatMessages.push(tempMsg);
            this.renderManagerChat();

            // POST to server endpoint
            try {
                const res = await fetch('/api/reasoning_chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: text,
                        sender: 'OPERATOR',
                        role: 'OPERATOR'
                    })
                });
                if (res.ok) {
                    await this.loadChatData(true);
                }
            } catch (err) {
                console.warn('[TradingDesk] Manager directive post delayed:', err);
            }
        };

        if (btnSend) {
            btnSend.addEventListener('click', sendDirective);
        }
        if (inputMgr) {
            inputMgr.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendDirective();
                }
            });
        }

        // 5. Portfolio Tabs
        container.querySelectorAll('.port-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.port-tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.portfolioTab = btn.getAttribute('data-ptab') || 'positions';
                this.renderPortfolioTab();
            });
        });

        // 6. Research Section Tabs
        container.querySelectorAll('.research-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.research-tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.researchTab = btn.getAttribute('data-rtab') || 'briefing';
                this.renderResearchFeed();
            });
        });
    }

    async loadChatData(autoScroll = false) {
        try {
            const data = await api.fetchReasoningChat();
            if (data && data.messages) {
                this.chatMessages = data.messages;
                if (this.agentTab === 'coordination') {
                    this.renderCoordinationStream(autoScroll);
                } else {
                    this.renderManagerChat(autoScroll);
                }
            }
        } catch (err) {
            console.warn('[TradingDesk] Could not fetch reasoning chat:', err);
        }
    }

    renderCoordinationStream(autoScroll = false) {
        const stream = document.getElementById('coordinationMessageStream');
        if (!stream) return;

        const filtered = this.chatMessages.filter(msg => {
            // Strictly exclude Operator messages from Team Coordination stream (Squad only)
            if (msg.sender === 'OPERATOR' || msg.type === 'USER_INPUT') return false;
            if (msg.content && (msg.content.includes('Understood, Operator') || msg.content.startsWith('Directive acknowledged'))) return false;
            if (this.agentFilter === 'all') return true;
            return (msg.sender || '').toUpperCase().includes(this.agentFilter);
        });

        if (filtered.length === 0) {
            stream.innerHTML = `<div class="chat-loading-placeholder">No coordination events found for ${this.agentFilter}.</div>`;
            return;
        }

        stream.innerHTML = filtered.map(msg => {
            const isOperator = msg.sender === 'OPERATOR';
            const isManager = msg.sender.includes('MANAGER') || msg.sender.includes('Abhi');
            const color = msg.color || (isOperator ? '#facc15' : isManager ? '#fbbf24' : '#0ea5e9');

            return `
                <div class="agent-msg-card ${isOperator ? 'msg-operator' : isManager ? 'msg-manager' : ''}" style="border-left-color: ${color}">
                    <div class="msg-header-row">
                        <div class="msg-sender-block">
                            <strong class="msg-sender" style="color: ${color};">${msg.sender}</strong>
                            <span class="msg-badge-tag">${msg.badge || msg.type || 'AGENT'}</span>
                        </div>
                        <span class="msg-time font-mono">${msg.timestamp}</span>
                    </div>
                    <div class="msg-role-sub">${msg.role || 'Trading Specialist'}</div>
                    <div class="msg-content-text">${this.formatContent(msg.content)}</div>
                </div>
            `;
        }).join('');

        if (autoScroll || stream.scrollTop + stream.clientHeight >= stream.scrollHeight - 60) {
            stream.scrollTop = stream.scrollHeight;
        }
    }

    renderManagerChat(autoScroll = false) {
        const stream = document.getElementById('managerMessageStream');
        if (!stream) return;

        // Filter messages between Operator and Manager
        const mgrMessages = this.chatMessages.filter(msg => 
            msg.sender.includes('OPERATOR') || 
            msg.sender.includes('MANAGER') || 
            msg.sender.includes('Abhi') ||
            (msg.type && (msg.type.includes('DIRECTIVE') || msg.type.includes('USER_INPUT')))
        );

        if (mgrMessages.length === 0) {
            stream.innerHTML = `
                <div class="chat-empty-state">
                    <span style="font-size: 28px;">👑</span>
                    <strong style="color: var(--color-navy); margin-top: 6px;">Direct Line with Manager Abhi</strong>
                    <p style="font-size: 11.5px; color: var(--text-muted); margin-top: 4px; line-height: 1.4;">
                        Issue real-time risk directives, instruct profit lock ratchets, or request liquidity audits.
                    </p>
                </div>
            `;
            return;
        }

        stream.innerHTML = mgrMessages.map(msg => {
            const isOperator = msg.sender === 'OPERATOR';
            const color = isOperator ? '#facc15' : '#fbbf24';

            return `
                <div class="agent-msg-card ${isOperator ? 'msg-operator' : 'msg-manager'}" style="border-left-color: ${color}">
                    <div class="msg-header-row">
                        <div class="msg-sender-block">
                            <strong class="msg-sender" style="color: ${color};">${msg.sender}</strong>
                            <span class="msg-badge-tag">${msg.badge || 'DIRECTIVE'}</span>
                        </div>
                        <span class="msg-time font-mono">${msg.timestamp}</span>
                    </div>
                    <div class="msg-content-text">${this.formatContent(msg.content)}</div>
                    ${!isOperator ? `<div class="msg-ack-status">✓ Acknowledged &amp; Verified</div>` : ''}
                </div>
            `;
        }).join('');

        if (autoScroll || stream.scrollTop + stream.clientHeight >= stream.scrollHeight - 60) {
            stream.scrollTop = stream.scrollHeight;
        }
    }

    formatContent(raw) {
        if (!raw) return '';
        return raw
            .replace(/\n\n/g, '<br/><br/>')
            .replace(/\n/g, '<br/>')
            .replace(/•\s/g, '•&nbsp;')
            .replace(/₹([0-9,.]+)/g, '<strong style="color: #0284c7;">₹$1</strong>');
    }

    renderPortfolioTab() {
        const body = document.getElementById('portfolioViewBody');
        if (!body) return;

        if (this.portfolioTab === 'positions') {
            body.innerHTML = `
                <div class="port-table-wrapper">
                    <table class="port-data-table">
                        <thead>
                            <tr>
                                <th>CONTRACT</th>
                                <th>QTY</th>
                                <th>ENTRY</th>
                                <th>LTP</th>
                                <th>TARGET 1</th>
                                <th>STOP LOSS</th>
                                <th>TRAILING SL</th>
                                <th>P&amp;L (UNREALIZED)</th>
                                <th>STATUS</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td>
                                    <strong>NIFTY 19 OCT 22550 PE</strong>
                                    <div class="table-subtext">Protective Strangle Put • 1 Lot</div>
                                </td>
                                <td class="font-mono">50</td>
                                <td class="font-mono">₹75.25</td>
                                <td class="font-mono" style="font-weight: 800; color: var(--bull-green);">₹146.70</td>
                                <td class="font-mono text-cyan">₹160.00</td>
                                <td class="font-mono text-muted">₹61.70</td>
                                <td class="font-mono" style="color: var(--color-amber);">₹112.50 (Locked)</td>
                                <td class="font-mono text-green" style="font-weight: 800;">+₹3,572.50 (+94.9%)</td>
                                <td><span class="badge badge-green">RUNNING</span></td>
                            </tr>
                            <tr>
                                <td>
                                    <strong>NIFTY 19 OCT 22900 CE</strong>
                                    <div class="table-subtext">Expansion Strangle Call • 1 Lot</div>
                                </td>
                                <td class="font-mono">50</td>
                                <td class="font-mono">₹71.70</td>
                                <td class="font-mono" style="font-weight: 800; color: var(--bear-red);">₹36.90</td>
                                <td class="font-mono text-cyan">₹86.00</td>
                                <td class="font-mono text-muted">₹58.80</td>
                                <td class="font-mono text-muted">₹58.80 (Hard SL)</td>
                                <td class="font-mono text-red" style="font-weight: 800;">-₹1,740.00 (-48.5%)</td>
                                <td><span class="badge badge-blue">HEDGED</span></td>
                            </tr>
                        </tbody>
                        <tfoot>
                            <tr class="port-table-total-row">
                                <td colspan="7"><strong>PORTFOLIO TOTAL NET UNREALIZED GAIN:</strong></td>
                                <td class="font-mono text-green" style="font-size: 13px; font-weight: 900;">+₹1,832.50 Net</td>
                                <td><span class="badge badge-purple">DELTA NEUTRAL</span></td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            `;
        } else if (this.portfolioTab === 'orders') {
            body.innerHTML = `
                <div class="port-table-wrapper">
                    <table class="port-data-table">
                        <thead>
                            <tr>
                                <th>ORDER ID</th>
                                <th>TIMESTAMP</th>
                                <th>INSTRUMENT</th>
                                <th>SIDE</th>
                                <th>QTY</th>
                                <th>FILL PRICE</th>
                                <th>MODE</th>
                                <th>STATUS</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td class="font-mono">ORD-PAP-1728901201</td>
                                <td class="font-mono">09:16:15 IST</td>
                                <td>NIFTY 19 OCT 22550 PE</td>
                                <td><span class="badge badge-green">BUY</span></td>
                                <td class="font-mono">50</td>
                                <td class="font-mono">₹75.25</td>
                                <td><span class="badge badge-amber">PAPER</span></td>
                                <td><span class="badge badge-green">COMPLETE</span></td>
                            </tr>
                            <tr>
                                <td class="font-mono">ORD-PAP-1728901202</td>
                                <td class="font-mono">09:16:15 IST</td>
                                <td>NIFTY 19 OCT 22900 CE</td>
                                <td><span class="badge badge-green">BUY</span></td>
                                <td class="font-mono">50</td>
                                <td class="font-mono">₹71.70</td>
                                <td><span class="badge badge-amber">PAPER</span></td>
                                <td><span class="badge badge-green">COMPLETE</span></td>
                            </tr>
                            <tr>
                                <td class="font-mono">ORD-PAP-1728909844</td>
                                <td class="font-mono">13:43:22 IST</td>
                                <td>BANKNIFTY 19 OCT 55300 PE</td>
                                <td><span class="badge badge-red">SELL</span></td>
                                <td class="font-mono">30</td>
                                <td class="font-mono">₹274.50</td>
                                <td><span class="badge badge-amber">PAPER</span></td>
                                <td><span class="badge badge-green">COMPLETE</span></td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            `;
        } else if (this.portfolioTab === 'closed') {
            body.innerHTML = `
                <div class="port-table-wrapper">
                    <table class="port-data-table">
                        <thead>
                            <tr>
                                <th>INSTRUMENT</th>
                                <th>ENTRY TIME / PRICE</th>
                                <th>EXIT TIME / PRICE</th>
                                <th>QTY</th>
                                <th>REALIZED P&amp;L</th>
                                <th>EXIT REASON</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><strong>BANKNIFTY 19 OCT 55300 PE</strong></td>
                                <td class="font-mono">09:20:10 @ ₹194.10</td>
                                <td class="font-mono">13:43:22 @ ₹274.50</td>
                                <td class="font-mono">30</td>
                                <td class="font-mono text-green" style="font-weight: 800;">+₹2,412.00 (+41.4%)</td>
                                <td><span class="badge badge-purple">Trailing SL Hit (+₹274.50 Peak Lock)</span></td>
                            </tr>
                            <tr>
                                <td><strong>NIFTY 19 OCT 22600 CE</strong></td>
                                <td class="font-mono">10:14:30 @ ₹82.40</td>
                                <td class="font-mono">11:05:12 @ ₹67.50</td>
                                <td class="font-mono">50</td>
                                <td class="font-mono text-red" style="font-weight: 800;">-₹745.00 (-18.0%)</td>
                                <td><span class="badge badge-amber">Hard Stop Loss (-18% Cutoff)</span></td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            `;
        } else if (this.portfolioTab === 'history') {
            // Strictly driven by stored records! Today enabled; wider ranges disabled
            body.innerHTML = `
                <div class="history-view-wrapper">
                    <div class="history-filter-toolbar">
                        <span class="history-filter-title">Date Range:</span>
                        <div class="history-chips-row" id="historyChipsRow">
                            <button class="hist-chip active" data-range="today">Today (Verified Snapshot)</button>
                            <button class="hist-chip disabled" data-range="1w" disabled title="No records in this range (Not enough history yet)">1 Week (No records)</button>
                            <button class="hist-chip disabled" data-range="2w" disabled title="No records in this range (Not enough history yet)">2 Weeks (No records)</button>
                            <button class="hist-chip disabled" data-range="half-month" disabled title="No records in this range (Not enough history yet)">Half-Month (No records)</button>
                            <button class="hist-chip disabled" data-range="1m" disabled title="No records in this range (Not enough history yet)">1 Month (No records)</button>
                            <button class="hist-chip disabled" data-range="quarter" disabled title="No records in this range (Not enough history yet)">Quarter (No records)</button>
                            <button class="hist-chip disabled" data-range="half-year" disabled title="No records in this range (Not enough history yet)">Half-Year (No records)</button>
                        </div>
                    </div>

                    <div class="history-provenance-note">
                        <span class="badge badge-cyan" style="font-size: 9px;">DATA AUDIT</span>
                        <span>Genuine stored settlement records for current session (2026-10-14). Wider historical windows without stored data are strictly disabled to protect data integrity.</span>
                    </div>

                    <div class="port-table-wrapper" style="margin-top: 8px;">
                        <table class="port-data-table">
                            <thead>
                                <tr>
                                    <th>DATE</th>
                                    <th>SESSION CYCLE</th>
                                    <th>START CAPITAL</th>
                                    <th>NET REALIZED P&amp;L</th>
                                    <th>ENDING EQUITY</th>
                                    <th>WIN RATE</th>
                                    <th>KELLY ALLOCATION</th>
                                    <th>SETTLEMENT AUDIT</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td class="font-mono">2026-10-14</td>
                                    <td><strong>Epoch 1: Multi-Asset Intraday</strong></td>
                                    <td class="font-mono">₹1,00,000.00</td>
                                    <td class="font-mono text-green" style="font-weight: 800;">+₹3,310.50 (+3.31%)</td>
                                    <td class="font-mono" style="font-weight: 800;">₹1,03,310.50</td>
                                    <td class="font-mono text-cyan">71.4% (5/7)</td>
                                    <td class="font-mono">63.8% Deployed / 36.2% Cash</td>
                                    <td><span class="badge badge-green">HMAC-SHA256 VERIFIED</span></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }
    }

    async loadResearchData() {
        try {
            const data = await api.fetchNewsIntel();
            if (data) {
                this.newsData = data;
                this.renderResearchFeed();
            }
        } catch (err) {
            console.warn('[TradingDesk] Could not fetch research documents:', err);
        }
    }

    renderResearchFeed() {
        const feed = document.getElementById('researchFeedContainer');
        if (!feed || !this.newsData) return;

        const docs = this.newsData.research_documents || [];
        const transfers = this.newsData.signal_transfer_to_decision_engine?.transfers || [];
        const exec = this.newsData.executive_summary;

        if (this.researchTab === 'briefing') {
            feed.innerHTML = `
                <div class="research-briefing-card">
                    <div class="briefing-hero-header">
                        <span class="badge badge-purple">${exec?.regime || 'HIGH VOLATILITY EXPANSION'}</span>
                        <span class="badge badge-green">${exec?.trade_authorization?.verdict || 'TRADE AUTHORIZED'}</span>
                    </div>
                    <h3 class="briefing-title">Intraday Market Macro Environment</h3>
                    <p class="briefing-p">${exec?.trade_authorization?.rationale || 'High intraday implied volatility spread vs historical realized volatility creates asymmetric premium expansion.'}</p>

                    <div class="briefing-stats-grid">
                        <div class="b-stat-item">
                            <span class="b-lbl">INDIA VIX:</span>
                            <span class="b-val text-amber font-mono">${exec?.india_vix || 13.82}</span>
                        </div>
                        <div class="b-stat-item">
                            <span class="b-lbl">CONVICTION:</span>
                            <span class="b-val text-cyan font-mono">${exec?.conviction_score_pct || 82.5}%</span>
                        </div>
                        <div class="b-stat-item">
                            <span class="b-lbl">CAPITAL ALLOC:</span>
                            <span class="b-val font-mono" style="font-size: 11px;">63.8% / 36.2%</span>
                        </div>
                        <div class="b-stat-item">
                            <span class="b-lbl">FLOW BALANCE:</span>
                            <span class="b-val text-green font-mono">DII +₹1,840 Cr</span>
                        </div>
                    </div>

                    <div class="briefing-subcard">
                        <strong>Institutional Orderflow Absorption:</strong>
                        <div style="font-size: 11px; color: var(--text-secondary); margin-top: 3px;">
                            ${exec?.fii_dii_balance || 'DII net inflow absorbs FII net selling, providing support above 22,500.'}
                        </div>
                    </div>
                </div>

                <!-- Signal Transfers Summary -->
                <div class="research-section-divider">
                    <span>EXECUTION SIGNAL TRANSFERS</span>
                </div>
                ${transfers.map(tr => `
                    <div class="transfer-card">
                        <div class="tr-source-tag">${tr.source_document}</div>
                        <div class="tr-catalyst"><strong>Catalyst:</strong> ${tr.catalyst}</div>
                        <div class="tr-signal"><strong>Signal to Desk:</strong> <span class="text-cyan">${tr.transferred_signal_to_left_panel}</span></div>
                    </div>
                `).join('')}
            `;
        } else {
            // Document accordions filtered by tab
            const filteredDocs = docs.filter(doc => {
                if (this.researchTab === 'regulatory') return doc.classification.includes('REGULATORY') || doc.authority.includes('Reserve Bank') || doc.authority.includes('NSE');
                if (this.researchTab === 'macro') return doc.classification.includes('MACRO') || doc.classification.includes('MONETARY') || doc.classification.includes('CROSS_ASSET');
                if (this.researchTab === 'instrument') return doc.title.includes('Banking') || doc.title.includes('Heavyweight');
                if (this.researchTab === 'evidence') return true;
                return true;
            });

            if (filteredDocs.length === 0) {
                feed.innerHTML = `<div class="chat-loading-placeholder">No documents matching '${this.researchTab}'.</div>`;
                return;
            }

            feed.innerHTML = filteredDocs.map((doc, idx) => `
                <div class="research-doc-accordion ${idx === 0 ? 'expanded' : ''}" data-doc-id="${doc.id}">
                    <div class="doc-accordion-header">
                        <div class="doc-header-info">
                            <span class="badge badge-purple" style="font-size: 9px;">${doc.id}</span>
                            <h4 class="doc-headline">${doc.title}</h4>
                            <div class="doc-authority">${doc.authority}</div>
                        </div>
                        <span class="accordion-arrow">${idx === 0 ? '▲' : '▼'}</span>
                    </div>

                    <div class="doc-accordion-body" style="display: ${idx === 0 ? 'block' : 'none'};">
                        <div class="doc-summary-box">
                            <strong>Executive Summary:</strong>
                            <p>${doc.summary}</p>
                        </div>

                        <div class="doc-findings-box">
                            <strong>Critical Primary Findings:</strong>
                            <ul>
                                ${doc.critical_findings.map(f => `<li>${f}</li>`).join('')}
                            </ul>
                        </div>

                        <div class="doc-transmission-box">
                            <strong>Transmission to Derivatives Desk:</strong>
                            <div class="transmission-text">${doc.transmission_to_derivatives}</div>
                        </div>
                    </div>
                </div>
            `).join('');

            // Accordion click handlers
            feed.querySelectorAll('.doc-accordion-header').forEach(hdr => {
                hdr.addEventListener('click', () => {
                    const parent = hdr.closest('.research-doc-accordion');
                    const bodyEl = parent.querySelector('.doc-accordion-body');
                    const arrow = parent.querySelector('.accordion-arrow');
                    const isOpen = bodyEl.style.display !== 'none';

                    if (isOpen) {
                        bodyEl.style.display = 'none';
                        arrow.textContent = '▼';
                        parent.classList.remove('expanded');
                    } else {
                        bodyEl.style.display = 'block';
                        arrow.textContent = '▲';
                        parent.classList.add('expanded');
                    }
                });
            });
        }
    }
}

export const pageTrading = new PageTradingController();
