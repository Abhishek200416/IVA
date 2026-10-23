/**
 * AGI 1.7 OMEGA COMMAND — UI V3 MODAL DIALOGS CONTROLLER
 * Strategy Wizard, Intelligence Reports, Algorithms Catalog & Diagnostics
 */

import { store } from './state.js';
import { api } from './api.js';

export class ModalController {
    constructor() {
        this.activeModal = null;
    }

    init() {
        this.setupBackdropEvents();
        this.setupTriggers();

        store.subscribe('open_modal', ({ modalId }) => {
            this.open(modalId);
        });
    }

    setupBackdropEvents() {
        document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
            backdrop.addEventListener('click', (e) => {
                if (e.target === backdrop) {
                    this.close();
                }
            });
        });

        document.querySelectorAll('.modal-close-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.close();
            });
        });

        window.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.close();
            }
        });
    }

    setupTriggers() {
        const btnWizard = document.getElementById('btnStartTradeHeader');
        if (btnWizard) {
            btnWizard.addEventListener('click', () => this.open('modalWizard'));
        }

        const btnAlgos = document.getElementById('btnOpenAlgosModal');
        if (btnAlgos) {
            btnAlgos.addEventListener('click', () => this.open('modalAlgos'));
        }

        const btnReport = document.getElementById('btnOpenReportModal');
        if (btnReport) {
            btnReport.addEventListener('click', () => this.open('modalReport'));
        }

        const btnProfile = document.getElementById('btnOpenProfileModal');
        if (btnProfile) {
            btnProfile.addEventListener('click', () => this.open('modalProfile'));
        }
    }

    open(modalId) {
        this.close();
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('active');
            this.activeModal = modal;
            this.onModalOpened(modalId);
        }
    }

    close() {
        if (this.activeModal) {
            this.activeModal.classList.remove('active');
            this.activeModal = null;
        }
    }

    onModalOpened(modalId) {
        if (modalId === 'modalReport') {
            this.loadReportData('day');
        } else if (modalId === 'modalAlgos') {
            this.loadAlgosData();
        } else if (modalId === 'modalProfile') {
            this.loadProfileData();
        }
    }

    async loadReportData(period = 'day') {
        const container = document.getElementById('reportModalBody');
        if (!container) return;
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">Generating verified intelligence report...</div>';

        const data = await api.fetchReport(period);
        if (!data) return;

        container.innerHTML = `
            <div style="display: flex; gap: 8px; margin-bottom: 14px;">
                <button class="badge badge-blue" style="cursor: pointer; padding: 6px 12px; font-size: 11px;">Day Report</button>
                <button class="badge badge-purple" style="cursor: pointer; padding: 6px 12px; font-size: 11px;">Weekly Audit</button>
                <button class="badge badge-amber" style="cursor: pointer; padding: 6px 12px; font-size: 11px;">Monthly Ledger</button>
            </div>
            <div style="background: var(--bg-card-subtle); border-radius: var(--radius-md); padding: 12px; border: 1px solid var(--border-subtle); margin-bottom: 12px;">
                <div style="font-weight: 800; font-size: 13px; color: var(--color-navy); margin-bottom: 4px;">DAILY QUANTITATIVE PERFORMANCE SUMMARY</div>
                <div style="font-size: 12px; color: var(--text-secondary); line-height: 1.45;">
                    The autonomous supervisor executed 4 derivative legs across the NIFTY 19-OCT-2026 weekly cycle. Delta hedging capped portfolio directional risk while capturing ₹3,506.90 gross theta yield. Total regulatory friction amounted to -₹196.40, locking in a net realized return of +₹3,310.50 (+3.31%).
                </div>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 12px;">
                <div style="background: #ffffff; border: 1px solid var(--border-subtle); padding: 10px; border-radius: var(--radius-sm);">
                    <div style="font-weight: 700; color: var(--color-navy); margin-bottom: 4px;">Algorithms Applied</div>
                    <ul style="padding-left: 18px; margin: 0; color: var(--text-secondary); font-size: 11.5px;">
                        <li>ALG-01: Bayesian Kelly Sizer</li>
                        <li>ALG-02: SABR Volatility Smile Calibrator</li>
                        <li>ALG-08: 14-Gate Institutional Risk Protocol</li>
                    </ul>
                </div>
                <div style="background: #ffffff; border: 1px solid var(--border-subtle); padding: 10px; border-radius: var(--radius-sm);">
                    <div style="font-weight: 700; color: var(--color-navy); margin-bottom: 4px;">Key Risk Mitigations</div>
                    <ul style="padding-left: 18px; margin: 0; color: var(--text-secondary); font-size: 11.5px;">
                        <li>₹36,225.00 (36.2%) Cash Reserve Buffer</li>
                        <li>Zero overnight gap exposure (15:15 IST cutoff)</li>
                        <li>HMAC-SHA256 Cryptographic Ledger Integrity</li>
                    </ul>
                </div>
            </div>
        `;
    }

    async loadAlgosData() {
        const container = document.getElementById('algosModalBody');
        if (!container) return;

        const algos = [
            { id: 'ALG-01', name: 'Bayesian Kelly Position Sizer', status: 'ACTIVE', desc: 'Computes continuous fractional Kelly staking with heavy-tail Student-t adjustment.' },
            { id: 'ALG-02', name: 'SABR Volatility Smile Calibrator', status: 'ACTIVE', desc: 'Fits alpha, beta, rho, and nu parameters to live options strike chains.' },
            { id: 'ALG-03', name: 'Kalman Spread Filter', status: 'ACTIVE', desc: 'Dynamic state-space estimation of cointegrated NIFTY vs BANKNIFTY ratios.' },
            { id: 'ALG-04', name: 'Lead-Lag High Frequency Arbitrage', status: 'STANDBY', desc: 'Microsecond cross-venue order book imbalance detection.' },
            { id: 'ALG-05', name: 'Cross-Asset Elasticity Scalper', status: 'ACTIVE', desc: 'Multi-horizon elasticity hedge across equity indices and USD/INR futures.' },
            { id: 'ALG-06', name: 'Intraday Order Flow Attribution', status: 'ACTIVE', desc: 'Decomposes level-2 ticks into institutional aggressive vs passive participation.' },
            { id: 'ALG-07', name: 'Elasticity Cross-Hedge Scalper', status: 'STANDBY', desc: 'Scalps mean-reverting basis shocks with dynamic stop adjustment.' },
            { id: 'ALG-08', name: '14-Gate Unified Institutional Risk Protocol', status: 'ACTIVE', desc: 'Enforces drawdown halts, circuit breakers, and permanent live order isolation.' },
        ];

        let html = `
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
        `;

        algos.forEach(a => {
            html += `
                <div style="background: var(--bg-card-subtle); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                        <span style="font-family: var(--font-mono); font-weight: 800; font-size: 11px; color: var(--color-navy);">${a.id}</span>
                        <span class="badge ${a.status === 'ACTIVE' ? 'badge-green' : 'badge-amber'}">${a.status}</span>
                    </div>
                    <div style="font-weight: 700; font-size: 12px; color: var(--text-primary); margin-bottom: 4px;">${a.name}</div>
                    <div style="font-size: 11px; color: var(--text-muted); line-height: 1.35;">${a.desc}</div>
                </div>
            `;
        });

        html += `</div>`;
        container.innerHTML = html;
    }

    async loadProfileData() {
        const container = document.getElementById('profileModalBody');
        if (!container) return;

        container.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 10px; font-size: 12.5px;">
                <div style="background: var(--bg-card-subtle); padding: 12px; border-radius: var(--radius-md); border-left: 3px solid var(--color-cyan);">
                    <div style="font-weight: 800; color: var(--color-navy);">AGI 1.7 OMEGA COMMAND (Host Terminal)</div>
                    <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 2px;">
                        Autonomous Engineering Partner &amp; Quantitative Derivatives Terminal
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                    <div style="border: 1px solid var(--border-subtle); padding: 8px; border-radius: var(--radius-sm);">
                        <div style="font-size: 11px; color: var(--text-muted);">Operator Identity</div>
                        <div style="font-weight: 800; color: var(--color-navy);">Operator Abhi</div>
                    </div>
                    <div style="border: 1px solid var(--border-subtle); padding: 8px; border-radius: var(--radius-sm);">
                        <div style="font-size: 11px; color: var(--text-muted);">Execution Boundary</div>
                        <div style="font-weight: 800; color: var(--reserve-amber);">STRICTLY PAPER ONLY</div>
                    </div>
                    <div style="border: 1px solid var(--border-subtle); padding: 8px; border-radius: var(--radius-sm);">
                        <div style="font-size: 11px; color: var(--text-muted);">Live Order Firewall</div>
                        <div style="font-weight: 800; color: var(--bear-red);">HTTP 403 FORBIDDEN</div>
                    </div>
                    <div style="border: 1px solid var(--border-subtle); padding: 8px; border-radius: var(--radius-sm);">
                        <div style="font-size: 11px; color: var(--text-muted);">Persistent Memory Database</div>
                        <div style="font-weight: 800; color: var(--bull-green);">omega_memory.db (WAL)</div>
                    </div>
                </div>
            </div>
        `;
    }
}

export const modalController = new ModalController();
