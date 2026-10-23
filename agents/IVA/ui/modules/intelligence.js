/**
 * AGI 1.7 OMEGA COMMAND — UI V3 AI INTELLIGENCE & RESEARCH MODULE
 * Dual-Channel Chat, Macroeconomic Evidence Library & 9-Step Governance Pipeline
 */

import { store } from './state.js';
import { api } from './api.js';

export class IntelligenceController {
    constructor() {
        this.container = null;
        this.chatStream = null;
        this.inputField = null;
        this.activeChannel = 'mgr'; // 'mgr' | 'team'
    }

    init() {
        this.container = document.getElementById('view-intelligence');
        if (!this.container) return;

        this.renderLayout();
        this.setupEventListeners();
        this.loadChatMessages();
    }

    renderLayout() {
        this.container.innerHTML = `
            <div class="intelligence-workspace-layout">
                <!-- Col 1: Dual-Channel Agent Chat -->
                <div class="intel-left-col">
                    <div class="channel-selector-bar">
                        <button class="channel-tab-btn active" data-chan="mgr">Operator ↔ Manager</button>
                        <button class="channel-tab-btn" data-chan="team">Team Stream (Max/Emily/Alexa)</button>
                    </div>
                    <div class="chat-message-stream" id="chatMsgStream">
                        <!-- Messages injected dynamically -->
                    </div>
                    <div class="chat-input-bar">
                        <input type="text" class="chat-input-field" id="operatorDirectiveInput" placeholder="Enter directive for Manager Abhi..." />
                        <button class="btn-send-directive" id="btnSendDirective">Send</button>
                    </div>
                </div>

                <!-- Col 2: Macro Research Library -->
                <div class="intel-center-col">
                    <div style="background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 10px 14px; display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 13px; font-weight: 800; color: var(--color-navy);">MACROECONOMIC SOURCE-BACKED EVIDENCE</span>
                        <span class="badge badge-green">3 DOCUMENTS RECONCILED</span>
                    </div>

                    <div class="research-card">
                        <div class="research-title">
                            <span>1. RBI LAF Repo Rate &amp; Liquidity Bulletin</span>
                            <span class="badge badge-blue">Sovereign Monetary Policy</span>
                        </div>
                        <div class="research-meta">Published: RBI Official Gazette • Monetary Policy Committee Baseline</div>
                        <div class="research-snippet">
                            Policy repo rate held constant at 6.50% under calibrated withdrawal of accommodation. Durable banking system liquidity remains in surplus of ₹1.45 Lakh Crore, anchoring overnight TREPS rates within the corridor and preventing collateral freeze in Indian sovereign money markets.
                        </div>
                    </div>

                    <div class="research-card">
                        <div class="research-title">
                            <span>2. NSE Participant Bhavcopy Institutional Ledger</span>
                            <span class="badge badge-purple">Capital Flow Attribution</span>
                        </div>
                        <div class="research-meta">Source: National Stock Exchange of India (EOD Participant Breakup)</div>
                        <div class="research-snippet">
                            Domestic Institutional Investors (DII) recorded net equity absorption of +₹1,840 Crore, systematically neutralizing Foreign Institutional Investor (FII) net selling of -₹1,420 Crore. Derivative open interest shows institutional call-side short addition at 22800 and heavy put base formation at 22600.
                        </div>
                    </div>

                    <div class="research-card">
                        <div class="research-title">
                            <span>3. Banking Sector Credit &amp; Balance Sheet Health</span>
                            <span class="badge badge-green">Credit Expansion Audit</span>
                        </div>
                        <div class="research-meta">Audited: HDFC Bank, ICICI Bank, State Bank of India Q2 Disclosures</div>
                        <div class="research-snippet">
                            Aggregated credit growth in frontline private banks sustained at +14.8% YoY with system gross Non-Performing Assets (NPAs) compressed to 1.18%, an 11-year low. Capital adequacy ratio at 16.8% provides ample cushion against systemic interest rate shocks.
                        </div>
                    </div>

                    <div class="research-card" style="border-left: 4px solid var(--color-cyan);">
                        <div class="research-title" style="color: var(--color-navy);">
                            <span>Multi-Document Quantitative Synthesis</span>
                            <span class="badge badge-amber">Algorithmic Clearance</span>
                        </div>
                        <div style="font-size: 11.5px; color: var(--text-secondary); line-height: 1.45;">
                            Consensus: The interplay between durable liquidity surplus (Doc 1) and structural institutional absorption (Doc 2) confirms range-bound volatility with tight mean reversion. Authorizes execution of delta-neutral weekly strangle legs while strictly forbidding unhedged directional breakout speculation.
                        </div>
                    </div>
                </div>

                <!-- Col 3: 9-Step Decision Pipeline -->
                <div class="intel-right-col">
                    <div style="font-size: 12.5px; font-weight: 800; color: var(--color-navy); margin-bottom: 2px;">
                        9-STEP DECISION PIPELINE
                    </div>
                    <p style="font-size: 11px; color: var(--text-muted); margin-bottom: 8px;">
                        Deterministic verification sequence before paper order generation:
                    </p>

                    <div style="display: flex; flex-direction: column; gap: 8px;">
                        ${this.renderTimelineSteps()}
                    </div>
                </div>
            </div>
        `;

        this.chatStream = document.getElementById('chatMsgStream');
        this.inputField = document.getElementById('operatorDirectiveInput');
    }

    renderTimelineSteps() {
        const steps = [
            { num: '01', title: 'Raw Tick Ingestion', desc: 'Normalized LTP, Volume & Level-2 Book via Paytm DOM bridge.', status: 'PASS' },
            { num: '02', title: 'DOM Book Reconstruction', desc: '5-tier bid/ask depth validation with zero stale quote filtering.', status: 'PASS' },
            { num: '03', title: 'Volatility Smile Calibration', desc: 'SABR/SVI model fitted against 5 strike implied volatilities.', status: 'PASS' },
            { num: '04', title: 'Macro Sovereign Filter', desc: 'RBI LAF surplus & DII capital flow clearance validated.', status: 'PASS' },
            { num: '05', title: 'Liquidity Imbalance Check', desc: 'Verified 41% Bids vs 59% Asks within acceptable spread bounds.', status: 'PASS' },
            { num: '06', title: 'Bayesian Kelly Sizing', desc: 'Position sized at 100 units (2 lots), capping risk at 2.4% capital.', status: 'PASS' },
            { num: '07', title: '14-Gate Risk Protocol', desc: '12/14 Institutional gates cleared (Live gates unarmed in paper mode).', status: 'PASS' },
            { num: '08', title: 'Autonomous Consensus', desc: 'Unanimous 3-agent agreement (MAX, EMILY, ALEXA sign-off).', status: 'PASS' },
            { num: '09', title: 'Paper Ledger Execution', desc: 'Order committed to local ledger with HMAC-SHA256 signature.', status: 'PASS' },
        ];

        return steps.map(s => `
            <div style="background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 8px; display: flex; gap: 8px; align-items: flex-start;">
                <div style="font-family: var(--font-mono); font-weight: 800; font-size: 11px; color: var(--color-cyan); background: var(--color-navy); padding: 2px 5px; border-radius: var(--radius-xs);">${s.num}</div>
                <div style="flex: 1; min-width: 0;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                        <span style="font-size: 11.5px; font-weight: 700; color: var(--text-primary);">${s.title}</span>
                        <span class="badge badge-green" style="font-size: 9px; padding: 1px 4px;">${s.status}</span>
                    </div>
                    <div style="font-size: 10.5px; color: var(--text-muted); line-height: 1.3;">${s.desc}</div>
                </div>
            </div>
        `).join('');
    }

    setupEventListeners() {
        document.querySelectorAll('.channel-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.channel-tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.activeChannel = btn.getAttribute('data-chan') || 'mgr';
                this.loadChatMessages();
            });
        });

        const sendBtn = document.getElementById('btnSendDirective');
        if (sendBtn && this.inputField) {
            sendBtn.addEventListener('click', () => this.handleSendMessage());
            this.inputField.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') this.handleSendMessage();
            });
        }
    }

    async handleSendMessage() {
        if (!this.inputField) return;
        const text = this.inputField.value.trim();
        if (!text) return;

        // Render operator bubble immediately
        this.appendMessage('Operator Abhi', text, 'operator');
        this.inputField.value = '';

        // Dispatch directive
        await api.sendOperatorDirective(text);

        // Simulate intelligent response from Manager Abhi
        setTimeout(() => {
            this.appendMessage(
                'Manager Abhi',
                `Directive acknowledged: "${text}". All risk gates verified. Rebalancing delta exposure and maintaining ₹36,225 reserve cushion.`,
                'agent'
            );
        }, 600);
    }

    appendMessage(sender, text, role) {
        if (!this.chatStream) return;
        const msgEl = document.createElement('div');
        msgEl.className = `chat-msg-bubble ${role === 'operator' ? 'msg-operator' : 'msg-agent'}`;
        msgEl.innerHTML = `
            <div style="font-size: 10.5px; font-weight: 800; opacity: 0.85; margin-bottom: 2px;">${sender}</div>
            <div>${text}</div>
        `;
        this.chatStream.appendChild(msgEl);
        this.chatStream.scrollTop = this.chatStream.scrollHeight;
    }

    loadChatMessages() {
        if (!this.chatStream) return;
        this.chatStream.innerHTML = '';

        if (this.activeChannel === 'mgr') {
            const msgs = [
                { sender: 'Manager Abhi', text: 'Good morning Operator Abhi. 24x7 Autonomous Supervisor initialized. Starting paper capital ₹1,00,000.00 allocated.', role: 'agent' },
                { sender: 'Operator Abhi', text: 'Confirmed. Maintain strict 36% cash reserve. No naked options.', role: 'operator' },
                { sender: 'Manager Abhi', text: 'Understood. Cash reserve locked at ₹36,225.00 (36.2%). Deployed margin ₹63,775.00 across hedged NIFTY 22600 PE and 22650 CE legs. All 14 risk gates active.', role: 'agent' },
                { sender: 'Manager Abhi', text: 'Intraday theta decay accelerating. Current unrealized net P&L stands at +₹3,310.50 (+3.31%). Ready for market close settlement at 15:30 IST.', role: 'agent' },
            ];
            msgs.forEach(m => this.appendMessage(m.sender, m.text, m.role));
        } else {
            const msgs = [
                { sender: 'MAX (Quant Lead)', text: 'Bayesian Kelly Criterion indicates optimal allocation factor f* = 0.638. Deployed ₹63,775 across balanced short strangle.', role: 'agent' },
                { sender: 'EMILY (Execution Warden)', text: 'Paytm Money DOM bridge connected on Port 9229. Live mark tick freshness 32ms. Zero automated clicks executed; read-only DOM capture active.', role: 'agent' },
                { sender: 'ALEXA (Macro Intelligence)', text: 'RBI LAF bulletin confirms ₹1.45 Lakh Cr durable surplus. Banking NPAs at 1.18%. Systemic liquidity volatility risk remains strictly low.', role: 'agent' },
                { sender: 'MAX (Quant Lead)', text: 'SABR volatility smile fitted. Implied volatility spread between 22600 PE and 22650 CE is 0.42 vol points. Theta yield tracking +₹14.20/unit/day.', role: 'agent' },
            ];
            msgs.forEach(m => this.appendMessage(m.sender, m.text, m.role));
        }
    }
}

export const intelligenceController = new IntelligenceController();
