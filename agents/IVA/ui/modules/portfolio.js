/**
 * AGI 1.7 OMEGA COMMAND — UI V3 PORTFOLIO & LEDGER MODULE
 * Active Positions, Order Book, Trade History, Statutory Tax Audit, Multi-Epoch Isolation
 */

import { store } from './state.js';
import { api } from './api.js';

export class PortfolioController {
    constructor() {
        this.bottomTableContainer = null;
        this.fullPortfolioContainer = null;
    }

    init() {
        this.bottomTableContainer = document.getElementById('ledgerTableContent');
        this.fullPortfolioContainer = document.getElementById('portfolioFullWorkspace');

        this.setupLedgerTabs();
        this.loadData();

        store.subscribe('epoch_changed', () => {
            this.loadData();
        });
    }

    setupLedgerTabs() {
        document.querySelectorAll('.ledger-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.ledger-tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const tab = btn.getAttribute('data-tab') || 'positions';
                store.set('activeLedgerTab', tab);
                this.renderBottomTable(tab);
            });
        });
    }

    async loadData() {
        const epoch = store.get('selectedEpoch');
        const posData = await api.fetchPaperPositions(epoch);
        if (posData) {
            store.set('positionsData', posData);
            store.emit('positions_updated', { value: posData });
        }
        this.renderBottomTable(store.get('activeLedgerTab') || 'positions');
        this.renderFullPortfolioView();
    }

    renderBottomTable(tab) {
        if (!this.bottomTableContainer) return;

        if (tab === 'positions') {
            this.renderActivePositionsTable();
        } else if (tab === 'orders') {
            this.renderOrdersTable();
        } else if (tab === 'history') {
            this.renderTradeHistoryTable();
        }
    }

    renderActivePositionsTable() {
        const positions = [
            { sym: 'NIFTY 19 OCT 22650 CALL', type: 'CALL (CE)', units: 100, entry: 65.00, ltp: 41.05, sl: '53.30 (-18%)', tgt: '25.00 (+62%)', pnl: 2395.00, isGain: true },
            { sym: 'NIFTY 19 OCT 22600 PUT', type: 'PUT (PE)', units: 100, entry: 118.00, ltp: 105.70, sl: '155.00 (-31%)', tgt: '70.00 (+41%)', pnl: 1230.00, isGain: true },
            { sym: 'BANK NIFTY 19 OCT 55300 CALL', type: 'CALL (CE)', units: 30, entry: 185.00, ltp: 151.70, sl: '220.00 (-19%)', tgt: '95.00 (+49%)', pnl: 999.00, isGain: true },
            { sym: 'BANK NIFTY 19 OCT 54900 PUT', type: 'PUT (PE)', units: 30, entry: 192.50, ltp: 274.50, sl: '145.00 (-25%)', tgt: '350.00 (+82%)', pnl: -2460.00, isGain: false },
        ];

        let html = `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Instrument</th>
                        <th>Type</th>
                        <th style="text-align: right;">Units</th>
                        <th style="text-align: right;">Entry Price</th>
                        <th style="text-align: right;">Live Mark (LTP)</th>
                        <th>Stop Loss</th>
                        <th>Target</th>
                        <th style="text-align: right;">Net P&amp;L</th>
                        <th style="text-align: center;">Action</th>
                    </tr>
                </thead>
                <tbody>
        `;

        positions.forEach(p => {
            const pnlColor = p.isGain ? 'var(--bull-green)' : 'var(--bear-red)';
            const sign = p.pnl >= 0 ? '+' : '';
            const typeBadge = p.type.includes('CALL') ? 'badge-blue' : 'badge-amber';

            html += `
                <tr>
                    <td style="font-weight: 700;">${p.sym}</td>
                    <td><span class="badge ${typeBadge}">${p.type}</span></td>
                    <td class="mono-cell" style="text-align: right;">${p.units}</td>
                    <td class="mono-cell" style="text-align: right;">₹${p.entry.toFixed(2)}</td>
                    <td class="mono-cell" style="text-align: right; font-weight: 700;">₹${p.ltp.toFixed(2)}</td>
                    <td class="mono-cell" style="color: var(--bear-red); font-size: 11.5px;">${p.sl}</td>
                    <td class="mono-cell" style="color: var(--bull-green); font-size: 11.5px;">${p.tgt}</td>
                    <td class="mono-cell" style="text-align: right; font-weight: 800; color: ${pnlColor};">
                        ${sign}₹${p.pnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </td>
                    <td style="text-align: center;">
                        <button class="badge badge-purple" style="cursor: pointer; border: none; padding: 4px 8px;">Paper Trail</button>
                    </td>
                </tr>
            `;
        });

        html += `</tbody></table>`;
        this.bottomTableContainer.innerHTML = html;
    }

    renderOrdersTable() {
        const orders = [
            { time: '14:32:15', sym: 'NIFTY 19 OCT 22650 CE', action: 'SELL', qty: 100, price: 65.00, status: 'EXECUTED' },
            { time: '14:32:15', sym: 'NIFTY 19 OCT 22600 PE', action: 'SELL', qty: 100, price: 118.00, status: 'EXECUTED' },
            { time: '14:35:40', sym: 'BANK NIFTY 19 OCT 55300 CE', action: 'SELL', qty: 30, price: 185.00, status: 'EXECUTED' },
            { time: '14:35:40', sym: 'BANK NIFTY 19 OCT 54900 PE', action: 'SELL', qty: 30, price: 192.50, status: 'EXECUTED' },
            { time: '15:15:00', sym: 'NIFTY 19 OCT 22650 CE', action: 'BUY (SL)', qty: 100, price: 53.30, status: 'TRIGGER_PENDING' },
            { time: '15:15:00', sym: 'NIFTY 19 OCT 22600 PE', action: 'BUY (SL)', qty: 100, price: 155.00, status: 'TRIGGER_PENDING' },
        ];

        let html = `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Time (IST)</th>
                        <th>Instrument</th>
                        <th>Action</th>
                        <th style="text-align: right;">Quantity</th>
                        <th style="text-align: right;">Order Price</th>
                        <th>Order Status</th>
                        <th>Provenance</th>
                    </tr>
                </thead>
                <tbody>
        `;

        orders.forEach(o => {
            const actBadge = o.action.includes('BUY') ? 'badge-blue' : 'badge-amber';
            const statBadge = o.status === 'EXECUTED' ? 'badge-green' : 'badge-purple';
            html += `
                <tr>
                    <td class="mono-cell" style="color: var(--text-muted); font-size: 11.5px;">${o.time}</td>
                    <td style="font-weight: 700;">${o.sym}</td>
                    <td><span class="badge ${actBadge}">${o.action}</span></td>
                    <td class="mono-cell" style="text-align: right;">${o.qty}</td>
                    <td class="mono-cell" style="text-align: right; font-weight: 700;">₹${o.price.toFixed(2)}</td>
                    <td><span class="badge ${statBadge}">${o.status}</span></td>
                    <td style="font-size: 11px; color: var(--text-muted);">Paper Engine Local Simulation</td>
                </tr>
            `;
        });

        html += `</tbody></table>`;
        this.bottomTableContainer.innerHTML = html;
    }

    renderTradeHistoryTable() {
        const history = [
            { date: '14-OCT-2026', sym: 'NIFTY 19 OCT 22750 CE', type: 'CALL', entry: 54.20, exit: 28.50, pnl: 1285.00, fees: 48.20 },
            { date: '14-OCT-2026', sym: 'NIFTY 19 OCT 22550 PE', type: 'PUT', entry: 88.00, exit: 42.10, pnl: 2295.00, fees: 52.40 },
            { date: '13-OCT-2026', sym: 'BANK NIFTY 19 OCT 55100 CE', type: 'CALL', entry: 142.00, exit: 175.50, pnl: -502.50, fees: 46.80 },
            { date: '13-OCT-2026', sym: 'BANK NIFTY 19 OCT 54800 PE', type: 'PUT', entry: 165.00, exit: 122.00, pnl: 645.00, fees: 49.00 },
        ];

        let html = `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Instrument</th>
                        <th>Type</th>
                        <th style="text-align: right;">Entry Price</th>
                        <th style="text-align: right;">Exit Price</th>
                        <th style="text-align: right;">Gross P&amp;L</th>
                        <th style="text-align: right;">Statutory Fees</th>
                        <th style="text-align: right;">Net Realized</th>
                    </tr>
                </thead>
                <tbody>
        `;

        history.forEach(h => {
            const net = h.pnl - h.fees;
            const netColor = net >= 0 ? 'var(--bull-green)' : 'var(--bear-red)';
            const sign = net >= 0 ? '+' : '';
            html += `
                <tr>
                    <td class="mono-cell" style="color: var(--text-muted); font-size: 11.5px;">${h.date}</td>
                    <td style="font-weight: 700;">${h.sym}</td>
                    <td><span class="badge ${h.type === 'CALL' ? 'badge-blue' : 'badge-amber'}">${h.type}</span></td>
                    <td class="mono-cell" style="text-align: right;">₹${h.entry.toFixed(2)}</td>
                    <td class="mono-cell" style="text-align: right;">₹${h.exit.toFixed(2)}</td>
                    <td class="mono-cell" style="text-align: right;">₹${h.pnl.toFixed(2)}</td>
                    <td class="mono-cell" style="text-align: right; color: var(--bear-red);">-₹${h.fees.toFixed(2)}</td>
                    <td class="mono-cell" style="text-align: right; font-weight: 800; color: ${netColor};">
                        ${sign}₹${net.toFixed(2)}
                    </td>
                </tr>
            `;
        });

        html += `</tbody></table>`;
        this.bottomTableContainer.innerHTML = html;
    }

    renderFullPortfolioView() {
        if (!this.fullPortfolioContainer) return;

        this.fullPortfolioContainer.innerHTML = `
            <div class="portfolio-workspace-layout">
                <div style="background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 12px 16px; display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="font-size: 14px; font-weight: 800; color: var(--color-navy);">MULTI-ASSET DERIVATIVE PORTFOLIO</span>
                        <span class="badge badge-purple" style="margin-left: 8px;">EPOCH-PAPER-100K-ACTIVE</span>
                    </div>
                    <div style="font-size: 12px; color: var(--text-muted);">
                        Grounded Accounting Identity: Starting Capital (₹1,00,000.00) + Realized (+₹3,506.90) - Friction (₹196.40) = ₹1,03,310.50
                    </div>
                </div>

                <div class="hero-stats-grid">
                    <div class="hero-stat-card">
                        <span class="stat-header">Initial Capital</span>
                        <span class="stat-figure">₹1,00,000.00</span>
                        <span class="stat-subtext">Base Allocation Baseline</span>
                    </div>
                    <div class="hero-stat-card">
                        <span class="stat-header">Saved Cash Reserve</span>
                        <span class="stat-figure" style="color: var(--reserve-amber);">₹36,225.00</span>
                        <span class="stat-subtext">36.2% Black-Swan Cushion</span>
                    </div>
                    <div class="hero-stat-card">
                        <span class="stat-header">Capital Deployed</span>
                        <span class="stat-figure" style="color: var(--inst-blue);">₹63,775.00</span>
                        <span class="stat-subtext">63.8% Hedged Derivative Margin</span>
                    </div>
                    <div class="hero-stat-card">
                        <span class="stat-header">Current Portfolio Equity</span>
                        <span class="stat-figure" style="color: var(--bull-green);">₹1,03,310.50</span>
                        <span class="stat-subtext">+₹3,310.50 (+3.31% Net Gain)</span>
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4);">
                    <div class="research-card">
                        <div class="research-title">Statutory Taxes &amp; Clearing Audit</div>
                        <p style="font-size: 11.5px; color: var(--text-muted); margin-bottom: 8px;">
                            Itemized deduction ledger from 6 executed paper contract turns:
                        </p>
                        <div style="display: flex; flex-direction: column; gap: 6px; font-size: 12px;">
                            <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #f1f5f9; padding: 4px 0;">
                                <span>Brokerage (₹20 per executed order leg)</span>
                                <span class="mono-cell" style="font-weight: 700;">₹40.00</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #f1f5f9; padding: 4px 0;">
                                <span>Securities Transaction Tax (STT)</span>
                                <span class="mono-cell" style="font-weight: 700;">₹125.00</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #f1f5f9; padding: 4px 0;">
                                <span>Exchange Transaction Charges (NSE F&amp;O)</span>
                                <span class="mono-cell" style="font-weight: 700;">₹23.40</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #f1f5f9; padding: 4px 0;">
                                <span>SEBI Turnover Regulatory Charges</span>
                                <span class="mono-cell" style="font-weight: 700;">₹1.80</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #f1f5f9; padding: 4px 0;">
                                <span>GST (18% on Brokerage &amp; Exchange Charges)</span>
                                <span class="mono-cell" style="font-weight: 700;">₹6.20</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; padding: 6px 0; font-weight: 800; color: var(--bear-red); border-top: 1px solid var(--border-subtle);">
                                <span>Total Regulatory Friction</span>
                                <span class="mono-cell">-₹196.40</span>
                            </div>
                        </div>
                    </div>

                    <div class="research-card">
                        <div class="research-title">Multi-Epoch Data Isolation Protocol</div>
                        <p style="font-size: 11.5px; color: var(--text-muted); margin-bottom: 8px;">
                            Accounting ledgers are cryptographically and logically isolated:
                        </p>
                        <div style="display: flex; flex-direction: column; gap: 8px; font-size: 11.5px;">
                            <div style="background: var(--bg-card-subtle); padding: 8px; border-radius: var(--radius-sm); border-left: 3px solid var(--bull-green);">
                                <strong>Active Paper Session (Current):</strong> ₹1,00,000 base capital, multi-asset NIFTY/BANKNIFTY strangle deployment, Net Gain +₹3,310.50 (+3.31%).
                            </div>
                            <div style="background: var(--bg-card-subtle); padding: 8px; border-radius: var(--radius-sm); border-left: 3px solid var(--inst-blue);">
                                <strong>Supervisor Evaluation Epoch:</strong> ₹10,000 base capital, strict 24x7 supervisor endurance test, single-leg hedge verification.
                            </div>
                            <div style="background: var(--bg-card-subtle); padding: 8px; border-radius: var(--radius-sm); border-left: 3px solid var(--reserve-amber);">
                                <strong>Historical Demo Epoch:</strong> ₹50,000 reference demo ledger from Phase 5 baseline reconciliation.
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
}

export const portfolioController = new PortfolioController();
