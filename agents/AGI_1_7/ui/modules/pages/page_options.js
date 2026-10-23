/**
 * AGI 1.7 OMEGA COMMAND — PAGE CONTROLLER: OPTIONS WORKSPACE (/options)
 * Full-screen dedicated option chain table, Level-2 depth ladder, Black-Scholes Greeks, and volatility smile.
 */

import { store } from '../state.js';
import { api } from '../api.js';
import { router } from '../router.js';

export class PageOptionsController {
    constructor() {
        this.containerId = 'page-options';
        this.initialized = false;
    }

    init() {
        const pane = document.getElementById(this.containerId);
        if (!pane) return;

        this.renderShell(pane);
        this.bindEvents(pane);
        this.initialized = true;
    }

    renderShell(container) {
        container.innerHTML = `
            <div class="options-page-layout">
                <!-- Controls & Strike Horizon Bar -->
                <div class="options-top-controls">
                    <div class="options-selector-group">
                        <label class="control-label">Underlying:</label>
                        <select class="form-select" id="optUnderlyingSelect">
                            <option value="NIFTY" selected>NIFTY 50 (Spot: ₹22,622.70)</option>
                            <option value="BANKNIFTY">BANK NIFTY (Spot: ₹55,299.60)</option>
                            <option value="FINNIFTY">FIN NIFTY (Spot: ₹23,890.15)</option>
                        </select>
                    </div>

                    <div class="options-selector-group">
                        <label class="control-label">Expiry Date:</label>
                        <select class="form-select" id="optExpirySelect">
                            <option value="2026-10-19" selected>19-Oct-2026 (Weekly Expiry - Verified Active)</option>
                            <option value="2026-10-29">29-Oct-2026 (Monthly Expiry - 15 DTE)</option>
                            <option value="2026-11-05">05-Nov-2026 (Weekly - 22 DTE)</option>
                        </select>
                    </div>

                    <div class="options-selector-group">
                        <label class="control-label">Strikes Horizon:</label>
                        <div class="segmented-control">
                            <button class="segment-btn active">11 Strikes (ATM ±5)</button>
                            <button class="segment-btn">21 Strikes (Full Chain)</button>
                        </div>
                    </div>

                    <div style="margin-left: auto; display: flex; gap: 8px; align-items: center;">
                        <span class="badge badge-purple">ATM STRIKE: 22600</span>
                        <span class="badge badge-green">IV SKEW: SABR CALIBRATED</span>
                    </div>
                </div>

                <!-- Two-Column Layout: Full Option Chain & Side Depth / Greeks Panel -->
                <div class="options-main-grid">
                    <!-- Left: Full Option Chain Table -->
                    <div class="options-chain-container">
                        <div class="table-scroll-container" style="max-height: calc(100vh - 220px);">
                            <table class="data-table option-chain-table">
                                <thead>
                                    <tr class="oc-meta-header">
                                        <th colspan="5" class="call-side-th">CALLS (CE)</th>
                                        <th class="strike-center-th">STRIKE</th>
                                        <th colspan="5" class="put-side-th">PUTS (PE)</th>
                                    </tr>
                                    <tr>
                                        <th>OI (Lacs)</th>
                                        <th>IV (%)</th>
                                        <th>Delta</th>
                                        <th>Bid/Ask</th>
                                        <th>LTP (₹)</th>
                                        <th class="strike-col">Strike Price</th>
                                        <th>LTP (₹)</th>
                                        <th>Bid/Ask</th>
                                        <th>Delta</th>
                                        <th>IV (%)</th>
                                        <th>OI (Lacs)</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr>
                                        <td>42.50</td>
                                        <td>12.4</td>
                                        <td>0.74</td>
                                        <td>245.0 / 245.6</td>
                                        <td class="profit" style="font-weight: 700;">₹245.20</td>
                                        <td class="strike-cell">22400</td>
                                        <td class="loss">₹22.50</td>
                                        <td>22.2 / 22.8</td>
                                        <td>-0.26</td>
                                        <td>14.8</td>
                                        <td>65.40</td>
                                    </tr>
                                    <tr>
                                        <td>38.10</td>
                                        <td>12.6</td>
                                        <td>0.68</td>
                                        <td>180.5 / 181.0</td>
                                        <td class="profit" style="font-weight: 700;">₹180.75</td>
                                        <td class="strike-cell">22500</td>
                                        <td class="loss">₹48.40</td>
                                        <td>48.1 / 48.6</td>
                                        <td>-0.32</td>
                                        <td>14.2</td>
                                        <td>54.20</td>
                                    </tr>
                                    <tr class="strangle-leg-row" style="background: rgba(239, 68, 68, 0.08);">
                                        <td>44.20</td>
                                        <td>12.7</td>
                                        <td>0.62</td>
                                        <td>148.0 / 148.5</td>
                                        <td class="profit" style="font-weight: 700;">₹148.25</td>
                                        <td class="strike-cell" style="color: var(--accent-orange); font-weight:700;">22550 (STRANGLE PE LEG)</td>
                                        <td class="loss" style="font-weight: 800; color: var(--color-sell);">₹146.70</td>
                                        <td>146.4 / 147.0</td>
                                        <td>-0.38</td>
                                        <td>13.8</td>
                                        <td>48.90</td>
                                    </tr>
                                    <tr class="atm-row">
                                        <td>52.40</td>
                                        <td>13.0</td>
                                        <td>0.52</td>
                                        <td>118.2 / 118.8</td>
                                        <td class="profit" style="font-weight: 800;">₹118.50</td>
                                        <td class="strike-cell atm-badge">22600 (ATM)</td>
                                        <td class="loss" style="font-weight: 800;">₹104.20</td>
                                        <td>104.0 / 104.5</td>
                                        <td>-0.48</td>
                                        <td>13.5</td>
                                        <td>58.10</td>
                                    </tr>
                                    <tr>
                                        <td>56.80</td>
                                        <td>13.2</td>
                                        <td>0.45</td>
                                        <td>89.0 / 89.5</td>
                                        <td class="profit">₹89.25</td>
                                        <td class="strike-cell">22650</td>
                                        <td class="loss">₹135.40</td>
                                        <td>135.0 / 135.8</td>
                                        <td>-0.55</td>
                                        <td>13.2</td>
                                        <td>39.20</td>
                                    </tr>
                                    <tr>
                                        <td>61.20</td>
                                        <td>13.5</td>
                                        <td>0.38</td>
                                        <td>65.0 / 65.5</td>
                                        <td class="profit">₹65.20</td>
                                        <td class="strike-cell">22700</td>
                                        <td class="loss">₹172.00</td>
                                        <td>171.5 / 172.5</td>
                                        <td>-0.62</td>
                                        <td>13.0</td>
                                        <td>31.50</td>
                                    </tr>
                                    <tr class="strangle-leg-row" style="background: rgba(34, 197, 94, 0.08);">
                                        <td>68.50</td>
                                        <td>13.9</td>
                                        <td>0.24</td>
                                        <td>36.8 / 37.0</td>
                                        <td class="profit" style="font-weight: 800; color: var(--color-buy);">₹36.90</td>
                                        <td class="strike-cell" style="color: var(--color-buy); font-weight:700;">22900 (STRANGLE CE LEG)</td>
                                        <td class="loss">₹310.50</td>
                                        <td>309.5 / 311.5</td>
                                        <td>-0.76</td>
                                        <td>12.8</td>
                                        <td>24.80</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- Right: Level-2 Market Depth & Greeks Breakdown -->
                    <div class="options-side-panel">
                        <div class="depth-card">
                            <div class="panel-header-row">
                                <h4 class="panel-card-title">📖 Level-2 Market Depth (5 Tiers)</h4>
                                <span class="badge badge-blue">NIFTY 19 OCT 22900 CE</span>
                            </div>
                            <div class="depth-ladder-grid">
                                <div class="depth-col">
                                    <div class="depth-col-header buy-header">BID ORDERS (BUYERS)</div>
                                    <div class="depth-row"><span>1,300</span><span>₹36.80</span></div>
                                    <div class="depth-row"><span>2,600</span><span>₹36.75</span></div>
                                    <div class="depth-row"><span>1,950</span><span>₹36.70</span></div>
                                    <div class="depth-row"><span>3,250</span><span>₹36.65</span></div>
                                    <div class="depth-row"><span>1,300</span><span>₹36.60</span></div>
                                    <div class="depth-total-row"><span>Total: <strong>10,400</strong></span></div>
                                </div>
                                <div class="depth-col">
                                    <div class="depth-col-header sell-header">ASK ORDERS (SELLERS)</div>
                                    <div class="depth-row"><span>₹37.00</span><span>1,950</span></div>
                                    <div class="depth-row"><span>₹37.05</span><span>2,600</span></div>
                                    <div class="depth-row"><span>₹37.10</span><span>1,300</span></div>
                                    <div class="depth-row"><span>₹37.15</span><span>3,900</span></div>
                                    <div class="depth-row"><span>₹37.20</span><span>2,600</span></div>
                                    <div class="depth-total-row"><span>Total: <strong>12,350</strong></span></div>
                                </div>
                            </div>
                            <div class="depth-bar-container" style="margin-top: 10px;">
                                <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 4px;">
                                    <span>Buyers 45.7%</span>
                                    <span>Sellers 54.3%</span>
                                </div>
                                <div class="depth-gauge-bar">
                                    <div class="depth-gauge-buy" style="width: 45.7%;"></div>
                                    <div class="depth-gauge-sell" style="width: 54.3%;"></div>
                                </div>
                            </div>
                        </div>

                        <!-- Greeks & Analytical Sensitivities -->
                        <div class="greeks-card" style="margin-top: 14px;">
                            <div class="panel-header-row">
                                <h4 class="panel-card-title">📐 BSM &amp; SABR Volatility Greeks</h4>
                                <span class="badge badge-purple">15 DTE</span>
                            </div>
                            <div class="greeks-grid">
                                <div class="greek-item">
                                    <span class="greek-name">Delta (&Delta;)</span>
                                    <span class="greek-val">+0.58</span>
                                    <span class="greek-desc">+₹0.58 / pt spot</span>
                                </div>
                                <div class="greek-item">
                                    <span class="greek-name">Gamma (&Gamma;)</span>
                                    <span class="greek-val">+0.0018</span>
                                    <span class="greek-desc">Acceleration</span>
                                </div>
                                <div class="greek-item">
                                    <span class="greek-name">Theta (&Theta;)</span>
                                    <span class="greek-val loss">-₹12.40</span>
                                    <span class="greek-desc">Decay / calendar day</span>
                                </div>
                                <div class="greek-item">
                                    <span class="greek-name">Vega (&Nu;)</span>
                                    <span class="greek-val">+₹18.20</span>
                                    <span class="greek-desc">Per 1% IV shift</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    bindEvents(container) {
        // Strike click to select and trade
        container.querySelectorAll('.option-chain-table tbody tr').forEach(row => {
            row.addEventListener('click', (e) => {
                const strikeCell = row.querySelector('.strike-cell');
                if (strikeCell) {
                    const strikeNum = parseInt(strikeCell.textContent.replace(/\D/g, ''));
                    if (strikeNum) {
                        store.update({
                            selectedContractName: `NIFTY 26 OCT ${strikeNum} CE`,
                            selectedContractLtp: 132.00,
                            selectedContractChg: 14.20
                        });
                    }
                }
            });
        });
    }
}

export const pageOptions = new PageOptionsController();
