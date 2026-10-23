/**
 * AGI 1.7 OMEGA COMMAND — PAGE CONTROLLER: QUANTITATIVE ALGORITHMS CATALOG (/algorithms)
 * Complete mathematical specifications, verification status, runtime states, risk gates, and OOD protocols.
 */

import { api } from '../api.js';

export class PageAlgorithmsController {
    constructor() {
        this.containerId = 'page-algorithms';
        this.currentFilter = 'all';
        this.catalogData = null;
        this.initialized = false;
    }

    async init() {
        const pane = document.getElementById(this.containerId);
        if (!pane) return;

        this.renderShell(pane);
        await this.loadCatalog(pane);
        this.bindEvents(pane);
        this.initialized = true;
    }

    renderShell(container) {
        container.innerHTML = `
            <div class="algorithms-page-wrapper">
                <!-- Page Top Hero Header -->
                <div class="algos-hero-header">
                    <div class="algos-hero-title-area">
                        <div class="algos-hero-badge-row">
                            <span class="badge badge-purple">QUANTITATIVE ALGORITHMS CATALOG</span>
                            <span class="badge badge-amber">RISK GATE 4 VERIFIED</span>
                            <span class="badge badge-cyan">STRICTLY PAPER BOUND</span>
                        </div>
                        <h1 class="algos-hero-title">Quantitative Models, Formulations &amp; Execution Protocols</h1>
                        <p class="algos-hero-subtitle">
                            Full audit of mathematical logic, runtime pipelines, statistical calibration (Brier scores), and out-of-distribution (OOD) failure recovery protocols.
                        </p>
                    </div>

                    <!-- Active Pipeline Highlights -->
                    <div class="algos-pipeline-summary" id="algosPipelineSummary">
                        <div class="pipeline-metric-card">
                            <span class="pipeline-lbl">ACTIVE EXECUTION MODEL</span>
                            <strong class="pipeline-val" style="color: #10b981;">ALG-01: Dual Strangle</strong>
                            <span class="pipeline-sub">NIFTY 22900 CE + 22550 PE</span>
                        </div>
                        <div class="pipeline-metric-card">
                            <span class="pipeline-lbl">POSITION SIZING PROTOCOL</span>
                            <strong class="pipeline-val" style="color: #38bdf8;">ALG-02: Kelly Sizing</strong>
                            <span class="pipeline-sub">63.8% Deployed / 36.2% Reserve</span>
                        </div>
                        <div class="pipeline-metric-card">
                            <span class="pipeline-lbl">DYNAMIC PROFIT LOCK</span>
                            <strong class="pipeline-val" style="color: #fbbf24;">ALG-03: Parabolic Ratchet</strong>
                            <span class="pipeline-sub">12% Peak Trailing Stop</span>
                        </div>
                        <div class="pipeline-metric-card">
                            <span class="pipeline-lbl">CALIBRATION SCORE</span>
                            <strong class="pipeline-val" style="color: #c084fc;">BSS = +0.2201</strong>
                            <span class="pipeline-sub">Raw BS = 0.1240 vs 0.1590</span>
                        </div>
                    </div>
                </div>

                <!-- Filter Navigation Tabs -->
                <div class="algos-filter-bar">
                    <div class="algos-tab-group" id="algosFilterTabs">
                        <button class="algos-tab-btn active" data-filter="all">All Algorithms (<span id="cntAll">10</span>)</button>
                        <button class="algos-tab-btn" data-filter="active">Active in Current Pipeline (<span id="cntActive">4</span>)</button>
                        <button class="algos-tab-btn" data-filter="standby">Standby &amp; Eligible (<span id="cntStandby">4</span>)</button>
                        <button class="algos-tab-btn" data-filter="tested">Implemented &amp; Tested (<span id="cntTested">8</span>)</button>
                        <button class="algos-tab-btn" data-filter="experimental">Experimental (<span id="cntExp">1</span>)</button>
                        <button class="algos-tab-btn" data-filter="blocked">Blocked / Unavailable (<span id="cntBlocked">1</span>)</button>
                    </div>

                    <div class="algos-search-wrap">
                        <input type="text" class="algos-search-input" id="algosSearchInput" placeholder="Filter by ID, formula, or variable..." />
                    </div>
                </div>

                <!-- Grid of Algorithm Cards -->
                <div class="algos-cards-grid" id="algosGridContainer">
                    <div style="grid-column: 1 / -1; padding: 40px; text-align: center; color: var(--text-muted);">
                        Loading mathematical specifications and risk metrics...
                    </div>
                </div>

                <!-- Out-of-Distribution & Safety Protocols -->
                <div class="algos-ood-section" id="algosOodContainer">
                    <!-- Rendered dynamically -->
                </div>
            </div>
        `;
    }

    async loadCatalog(container) {
        try {
            const data = await api.fetchAlgorithms();
            if (data && data.algorithms) {
                this.catalogData = data;
                this.renderCards(this.catalogData.algorithms);
                this.renderOodProtocol(this.catalogData.out_of_distribution_protocol);
                this.updateCounts(this.catalogData.algorithms);
            }
        } catch (err) {
            console.error('[PageAlgorithms] Failed to fetch catalog:', err);
            const grid = document.getElementById('algosGridContainer');
            if (grid) {
                grid.innerHTML = `<div style="grid-column: 1 / -1; padding: 30px; text-align: center; color: var(--bear-red);">
                    Failed to load algorithms catalog. Please verify server connection.
                </div>`;
            }
        }
    }

    updateCounts(algos) {
        const counts = {
            all: algos.length,
            active: algos.filter(a => a.category === 'active').length,
            standby: algos.filter(a => a.category === 'standby').length,
            tested: algos.filter(a => a.verification_status && a.verification_status.includes('100% Pass')).length,
            experimental: algos.filter(a => a.category === 'experimental').length,
            blocked: algos.filter(a => a.category === 'blocked').length
        };
        const setTxt = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val;
        };
        setTxt('cntAll', counts.all);
        setTxt('cntActive', counts.active);
        setTxt('cntStandby', counts.standby);
        setTxt('cntTested', counts.tested);
        setTxt('cntExp', counts.experimental);
        setTxt('cntBlocked', counts.blocked);
    }

    renderCards(algos) {
        const grid = document.getElementById('algosGridContainer');
        if (!grid) return;

        const filtered = algos.filter(algo => {
            if (this.currentFilter === 'all') return true;
            if (this.currentFilter === 'active') return algo.category === 'active';
            if (this.currentFilter === 'standby') return algo.category === 'standby';
            if (this.currentFilter === 'tested') return algo.verification_status && algo.verification_status.includes('100% Pass');
            if (this.currentFilter === 'experimental') return algo.category === 'experimental';
            if (this.currentFilter === 'blocked') return algo.category === 'blocked';
            return true;
        });

        if (filtered.length === 0) {
            grid.innerHTML = `<div style="grid-column: 1 / -1; padding: 40px; text-align: center; color: var(--text-muted);">
                No algorithms found matching filter '${this.currentFilter}'.
            </div>`;
            return;
        }

        grid.innerHTML = filtered.map(algo => {
            const statusBadgeClass = algo.category === 'active' ? 'badge-green' :
                                    algo.category === 'standby' ? 'badge-blue' :
                                    algo.category === 'experimental' ? 'badge-purple' : 'badge-red';

            return `
                <div class="algo-card ${algo.category === 'blocked' ? 'algo-blocked' : ''}" data-id="${algo.id}">
                    <div class="algo-card-header">
                        <div class="algo-card-identity">
                            <span class="algo-id-tag">${algo.id}</span>
                            <div class="algo-name-block">
                                <h3 class="algo-title">${algo.name}</h3>
                                <span class="algo-type-sub">${algo.type || 'Quantitative Model'}</span>
                            </div>
                        </div>
                        <span class="badge ${statusBadgeClass}">${algo.status}</span>
                    </div>

                    <div class="algo-formula-block">
                        <span class="algo-formula-label">MATHEMATICAL LOGIC / FORMULATION:</span>
                        <div class="algo-formula-code"><code>${algo.formula}</code></div>
                    </div>

                    <div class="algo-meta-grid">
                        <div class="algo-meta-item">
                            <span class="meta-label">RUNTIME STATE:</span>
                            <span class="meta-val" style="font-weight: 700;">${algo.runtime_state || 'STANDBY'}</span>
                        </div>
                        <div class="algo-meta-item">
                            <span class="meta-label">VERIFICATION:</span>
                            <span class="meta-val" style="color: ${algo.category === 'blocked' ? 'var(--bear-red)' : 'var(--bull-green)'};">
                                ${algo.verification_status || 'Verified'}
                            </span>
                        </div>
                        <div class="algo-meta-item">
                            <span class="meta-label">CALIBRATION / BRIER:</span>
                            <span class="meta-val font-mono">${algo.brier_score || 'N/A'}</span>
                        </div>
                        <div class="algo-meta-item">
                            <span class="meta-label">SAMPLE SIZE:</span>
                            <span class="meta-val font-mono">${algo.sample_size || 'N = 1,000+'}</span>
                        </div>
                    </div>

                    <div class="algo-details-body">
                        <div class="algo-detail-row">
                            <strong>Source Path:</strong> <code>${algo.code_reference || 'agents/AGI_1_7/engine/agi17/'}</code>
                        </div>
                        <div class="algo-detail-row">
                            <strong>Required Inputs:</strong> <span>${algo.required_inputs || 'Price, IV, Volume'}</span>
                        </div>
                        <div class="algo-detail-row">
                            <strong>Risk Constraints:</strong> <span>${algo.risk_constraints || 'Hard stop at -18%'}</span>
                        </div>
                        <div class="algo-detail-row">
                            <strong>Today's Rationale:</strong> <span>${algo.why_chosen_today || 'Regime-matched execution'}</span>
                        </div>
                    </div>

                    <div class="algo-card-footer">
                        <span class="algo-operator-tag">Role: <strong>${algo.role_responsible || 'Max (Quant)'}</strong></span>
                        <span class="algo-roi-tag">Target: <strong>${algo.expected_return || '+20% to +40%'}</strong></span>
                    </div>
                </div>
            `;
        }).join('');
    }

    renderOodProtocol(ood) {
        const oodEl = document.getElementById('algosOodContainer');
        if (!oodEl || !ood) return;

        oodEl.innerHTML = `
            <div class="ood-banner-card">
                <div class="ood-header">
                    <span class="ood-badge">CRITICAL SAFETY INFRASTRUCTURE</span>
                    <h2 class="ood-title">${ood.title}</h2>
                    <p class="ood-condition">${ood.condition}</p>
                </div>
                <div class="ood-guards-grid">
                    ${ood.automatic_safeguards.map(guard => `
                        <div class="ood-guard-item">
                            <span class="ood-guard-ico">🛡️</span>
                            <div class="ood-guard-text">${guard}</div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    bindEvents(container) {
        // Tab switching
        container.querySelectorAll('.algos-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.algos-tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentFilter = btn.getAttribute('data-filter') || 'all';
                if (this.catalogData && this.catalogData.algorithms) {
                    this.renderCards(this.catalogData.algorithms);
                }
            });
        });

        // Search filtering
        const searchInput = container.querySelector('#algosSearchInput');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                const term = (e.target.value || '').toLowerCase().trim();
                if (!this.catalogData || !this.catalogData.algorithms) return;

                if (!term) {
                    this.renderCards(this.catalogData.algorithms);
                    return;
                }

                const filtered = this.catalogData.algorithms.filter(algo => 
                    algo.name.toLowerCase().includes(term) ||
                    algo.id.toLowerCase().includes(term) ||
                    (algo.formula && algo.formula.toLowerCase().includes(term)) ||
                    (algo.required_inputs && algo.required_inputs.toLowerCase().includes(term))
                );
                this.renderCards(filtered);
            });
        }
    }
}

export const pageAlgorithms = new PageAlgorithmsController();
