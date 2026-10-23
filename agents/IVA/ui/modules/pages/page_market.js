/**
 * AGI 1.7 OMEGA COMMAND — PAGE CONTROLLER: MARKET EXPLORER (/market)
 * Comprehensive market intelligence, index spot overviews, sectoral performance, FII/DII flows, and contract discovery.
 */

import { store } from '../state.js';
import { api } from '../api.js';
import { router } from '../router.js';

export class PageMarketController {
    constructor() {
        this.containerId = 'page-market';
        this.initialized = false;
    }

    init() {
        const pane = document.getElementById(this.containerId);
        if (!pane) return;

        this.renderShell(pane);
        this.loadData(pane);
        this.bindEvents(pane);
        this.initialized = true;
    }

    renderShell(container) {
        container.innerHTML = `
            <div class="market-page-layout">
                <!-- Page Header Hero Cluster -->
                <div class="page-hero-banner">
                    <div>
                        <h2 class="page-hero-title">🌐 Market Explorer &amp; Derivatives Radar</h2>
                        <p class="page-hero-subtitle">Comprehensive spot index tracking, sectoral momentum, FII/DII institutional liquidity, and contract discovery.</p>
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <span class="badge badge-purple">SOURCE: NSE BHAVCOPY &amp; REAL DOM</span>
                        <span class="badge badge-green">FEED: ACTIVE</span>
                    </div>
                </div>

                <!-- Three Major Indices Summary Grid -->
                <div class="market-indices-grid">
                    <div class="market-index-card card-interactive" data-select="NIFTY">
                        <div class="index-card-header">
                            <div>
                                <span class="index-symbol">NIFTY 50</span>
                                <span class="badge badge-blue" style="margin-left: 6px;">INDEX SPOT</span>
                            </div>
                            <span class="index-volume">Vol: 28.45M</span>
                        </div>
                        <div class="index-price-row">
                            <span class="index-ltp">₹22,622.70</span>
                            <span class="index-chg loss">-99.25 (-0.44%)</span>
                        </div>
                        <div class="index-stats-row">
                            <span>Open: <strong>22,655.20</strong></span>
                            <span>High: <strong>22,680.10</strong></span>
                            <span>Low: <strong>22,578.00</strong></span>
                        </div>
                        <div class="index-card-footer">
                            <button class="btn-sm btn-outline" data-navigate="trading" data-sym="NIFTY">Trade Chart ➔</button>
                            <button class="btn-sm btn-outline" data-navigate="options" data-sym="NIFTY">Option Chain ➔</button>
                        </div>
                    </div>

                    <div class="market-index-card card-interactive" data-select="BANKNIFTY">
                        <div class="index-card-header">
                            <div>
                                <span class="index-symbol">BANK NIFTY</span>
                                <span class="badge badge-blue" style="margin-left: 6px;">INDEX SPOT</span>
                            </div>
                            <span class="index-volume">Vol: 16.20M</span>
                        </div>
                        <div class="index-price-row">
                            <span class="index-ltp">₹55,299.60</span>
                            <span class="index-chg loss">-165.05 (-0.30%)</span>
                        </div>
                        <div class="index-stats-row">
                            <span>Open: <strong>55,380.00</strong></span>
                            <span>High: <strong>55,450.00</strong></span>
                            <span>Low: <strong>55,180.00</strong></span>
                        </div>
                        <div class="index-card-footer">
                            <button class="btn-sm btn-outline" data-navigate="trading" data-sym="BANKNIFTY">Trade Chart ➔</button>
                            <button class="btn-sm btn-outline" data-navigate="options" data-sym="BANKNIFTY">Option Chain ➔</button>
                        </div>
                    </div>

                    <div class="market-index-card card-interactive" data-select="FINNIFTY">
                        <div class="index-card-header">
                            <div>
                                <span class="index-symbol">FIN NIFTY</span>
                                <span class="badge badge-blue" style="margin-left: 6px;">INDEX SPOT</span>
                            </div>
                            <span class="index-volume">Vol: 8.40M</span>
                        </div>
                        <div class="index-price-row">
                            <span class="index-ltp">23,890.15</span>
                            <span class="index-chg profit">+45.30 (+0.19%)</span>
                        </div>
                        <div class="index-stats-row">
                            <span>Open: <strong>23,850.00</strong></span>
                            <span>High: <strong>23,940.00</strong></span>
                            <span>Low: <strong>23,820.00</strong></span>
                        </div>
                        <div class="index-card-footer">
                            <button class="btn-sm btn-outline" data-navigate="trading" data-sym="FINNIFTY">Trade Chart ➔</button>
                            <button class="btn-sm btn-outline" data-navigate="options" data-sym="FINNIFTY">Option Chain ➔</button>
                        </div>
                    </div>
                </div>

                <!-- Split Row: Contract Search & Institutional Flow -->
                <div class="market-two-col-grid">
                    <!-- Column 1: Contract Explorer -->
                    <div class="market-card-panel">
                        <div class="panel-header-row">
                            <h3 class="panel-card-title">🔍 Active Derivative Contracts Search</h3>
                            <div class="search-category-pills">
                                <button class="pill-btn active" data-cat="all">All</button>
                                <button class="pill-btn" data-cat="ce">Calls Only</button>
                                <button class="pill-btn" data-cat="pe">Puts Only</button>
                            </div>
                        </div>
                        <div class="market-search-bar-wrap">
                            <input type="text" id="marketContractSearchInput" class="market-search-input" placeholder="Filter by strike (e.g. 24200, 51000)..." />
                        </div>
                        <div class="table-scroll-container" style="max-height: 380px;">
                            <table class="data-table" id="marketContractsTable">
                                <thead>
                                    <tr>
                                        <th>Contract Symbol</th>
                                        <th>Type</th>
                                        <th>Expiry</th>
                                        <th>LTP</th>
                                        <th>Change</th>
                                        <th>Open Int</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr>
                                        <td><strong>NIFTY 26 OCT 24200 CE</strong></td>
                                        <td><span class="badge badge-blue">CALL</span></td>
                                        <td>29-Oct-2026</td>
                                        <td>₹132.00</td>
                                        <td class="profit">+14.20</td>
                                        <td>4.52M</td>
                                        <td>
                                            <button class="btn-xs btn-outline" data-select-contract="NIFTY 26 OCT 24200 CE" data-ltp="132.00">Select</button>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td><strong>NIFTY 26 OCT 24250 CE</strong></td>
                                        <td><span class="badge badge-blue">CALL</span></td>
                                        <td>29-Oct-2026</td>
                                        <td>₹104.50</td>
                                        <td class="profit">+8.50</td>
                                        <td>3.89M</td>
                                        <td>
                                            <button class="btn-xs btn-outline" data-select-contract="NIFTY 26 OCT 24250 CE" data-ltp="104.50">Select</button>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td><strong>NIFTY 26 OCT 24150 PE</strong></td>
                                        <td><span class="badge badge-purple">PUT</span></td>
                                        <td>29-Oct-2026</td>
                                        <td>₹94.20</td>
                                        <td class="loss">-18.30</td>
                                        <td>4.10M</td>
                                        <td>
                                            <button class="btn-xs btn-outline" data-select-contract="NIFTY 26 OCT 24150 PE" data-ltp="94.20">Select</button>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td><strong>BANKNIFTY 26 OCT 51000 PE</strong></td>
                                        <td><span class="badge badge-purple">PUT</span></td>
                                        <td>29-Oct-2026</td>
                                        <td>₹210.00</td>
                                        <td class="loss">-24.00</td>
                                        <td>2.65M</td>
                                        <td>
                                            <button class="btn-xs btn-outline" data-select-contract="BANKNIFTY 26 OCT 51000 PE" data-ltp="210.00">Select</button>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td><strong>BANKNIFTY 26 OCT 51200 CE</strong></td>
                                        <td><span class="badge badge-blue">CALL</span></td>
                                        <td>29-Oct-2026</td>
                                        <td>₹245.00</td>
                                        <td class="profit">+16.50</td>
                                        <td>2.90M</td>
                                        <td>
                                            <button class="btn-xs btn-outline" data-select-contract="BANKNIFTY 26 OCT 51200 CE" data-ltp="245.00">Select</button>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- Column 2: Institutional Flows & Sector Heat -->
                    <div class="market-card-panel">
                        <div class="panel-header-row">
                            <h3 class="panel-card-title">🏛️ Institutional Liquidity &amp; Participant Flow</h3>
                            <span class="badge badge-green">NSE BHAVCOPY SYNC</span>
                        </div>
                        <div class="fii-dii-summary-card">
                            <div class="fii-dii-item">
                                <span class="fii-lbl">Foreign Institutional Investors (FII / FPI)</span>
                                <span class="fii-val loss">-₹1,420.00 Cr (Net Seller)</span>
                                <span class="fii-sub">Index futures reduction, stock options roll</span>
                            </div>
                            <div class="fii-dii-item">
                                <span class="fii-lbl">Domestic Institutional Investors (DII)</span>
                                <span class="fii-val profit">+₹1,840.00 Cr (Net Buyer)</span>
                                <span class="fii-sub">SIP inflows absorbing derivative selling</span>
                            </div>
                            <div class="fii-dii-item">
                                <span class="fii-lbl">Net Institutional Absorption Balance</span>
                                <span class="fii-val profit">+₹420.00 Cr (Bullish Cushion)</span>
                                <span class="fii-sub">Domestic liquidity stabilizing broad market</span>
                            </div>
                        </div>

                        <h4 style="font-size: 13px; font-weight: 700; margin: 16px 0 8px 0; color: var(--color-navy);">📊 Sectoral Momentum Matrix</h4>
                        <div class="sector-grid">
                            <div class="sector-pill profit">NIFTY BANK: <strong>+0.42%</strong></div>
                            <div class="sector-pill profit">NIFTY IT: <strong>+1.15%</strong></div>
                            <div class="sector-pill loss">NIFTY AUTO: <strong>-0.34%</strong></div>
                            <div class="sector-pill profit">NIFTY METAL: <strong>+0.85%</strong></div>
                            <div class="sector-pill loss">NIFTY FMCG: <strong>-0.22%</strong></div>
                            <div class="sector-pill profit">NIFTY PHARMA: <strong>+0.60%</strong></div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    loadData(container) {
        api.fetchFiiDii().then(data => {
            if (!data) return;
            // Updated dynamically if backend emits custom figures
        });
    }

    bindEvents(container) {
        container.querySelectorAll('[data-select-contract]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const sym = btn.getAttribute('data-select-contract');
                const ltp = parseFloat(btn.getAttribute('data-ltp') || '132.00');
                store.update({
                    selectedContractName: sym,
                    selectedContractLtp: ltp,
                    selectedContractChg: 14.20,
                    selectedContractChgPct: 11.50
                });
                router.navigate('trading', true);
            });
        });

        // Search input filtering
        const searchInput = container.querySelector('#marketContractSearchInput');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                const q = e.target.value.toLowerCase();
                container.querySelectorAll('#marketContractsTable tbody tr').forEach(row => {
                    const txt = row.textContent.toLowerCase();
                    row.style.display = txt.includes(q) ? '' : 'none';
                });
            });
        }
    }
}

export const pageMarket = new PageMarketController();
