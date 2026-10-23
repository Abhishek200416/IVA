/**
 * AGI 1.7 OMEGA COMMAND — UI V3 WATCHLIST & INSTRUMENT SELECTOR MODULE
 * Fast Search, Tabbed Contracts, Selection Bus, Collapsible Drawer
 */

import { store } from './state.js';

export const WATCHLIST_DATA = {
    fno: [
        { id: 'NIFTY', symbol: 'NIFTY 50', desc: 'Spot Benchmark Index', ltp: 22622.70, chg: -99.25, pct: -0.44, type: 'INDEX' },
        { id: 'BANKNIFTY', symbol: 'BANK NIFTY', desc: 'Banking Benchmark Index', ltp: 55299.60, chg: -165.05, pct: -0.30, type: 'INDEX' },
        { id: 'NIFTY22600PE', symbol: 'NIFTY 19 OCT 22600 PE', desc: 'Weekly ATM Put Option', ltp: 105.70, chg: 47.40, pct: 31.40, type: 'PE' },
        { id: 'NIFTY22650CE', symbol: 'NIFTY 19 OCT 22650 CE', desc: 'Weekly OTM Call Option', ltp: 41.05, chg: -23.95, pct: -36.80, type: 'CE' },
        { id: 'BANKNIFTY54900PE', symbol: 'BANK NIFTY 19 OCT 54900 PE', desc: 'Weekly OTM Put Option', ltp: 274.50, chg: 82.00, pct: 42.60, type: 'PE' },
        { id: 'BANKNIFTY55300CE', symbol: 'BANK NIFTY 19 OCT 55300 CE', desc: 'Weekly ATM Call Option', ltp: 151.70, chg: -33.30, pct: -18.00, type: 'CE' },
    ],
    indices: [
        { id: 'NIFTY', symbol: 'NIFTY 50', desc: 'National Stock Exchange of India', ltp: 22622.70, chg: -99.25, pct: -0.44, type: 'INDEX' },
        { id: 'BANKNIFTY', symbol: 'BANK NIFTY', desc: '12 Liquid Indian Banking Stocks', ltp: 55299.60, chg: -165.05, pct: -0.30, type: 'INDEX' },
        { id: 'FINNIFTY', symbol: 'NIFTY FINANCIAL', desc: 'Financial Services Sector Index', ltp: 24110.20, chg: -45.10, pct: -0.19, type: 'INDEX' },
        { id: 'INDIAVIX', symbol: 'INDIA VIX', desc: 'National Volatility Index', ltp: 13.82, chg: 0.64, pct: 4.85, type: 'INDEX' },
    ],
    active: [
        { id: 'NIFTY22650CE', symbol: 'NIFTY 19 OCT 22650 CE', desc: 'Short Strangle Leg (50 Qty)', ltp: 41.05, chg: -23.95, pct: -36.80, type: 'CE' },
        { id: 'NIFTY22600PE', symbol: 'NIFTY 19 OCT 22600 PE', desc: 'Short Strangle Leg (50 Qty)', ltp: 105.70, chg: 47.40, pct: 31.40, type: 'PE' },
        { id: 'BANKNIFTY55300CE', symbol: 'BANK NIFTY 19 OCT 55300 CE', desc: 'Directional Scalp (15 Qty)', ltp: 151.70, chg: -33.30, pct: -18.00, type: 'CE' },
        { id: 'BANKNIFTY54900PE', symbol: 'BANK NIFTY 19 OCT 54900 PE', desc: 'Directional Hedge (15 Qty)', ltp: 274.50, chg: 82.00, pct: 42.60, type: 'PE' },
    ]
};

export class WatchlistController {
    constructor() {
        this.container = null;
        this.listEl = null;
        this.searchInput = null;
        this.searchTerm = '';
        this.currentTab = 'fno';
    }

    init() {
        this.container = document.getElementById('watchlistSidebar');
        this.listEl = document.getElementById('watchlistItemsContainer');
        this.searchInput = document.getElementById('watchlistSearchInput');

        this.setupSearch();
        this.setupTabs();
        this.setupToggle();
        this.render();

        // Restore collapsed preference
        const savedCollapsed = localStorage.getItem('agi_watchlist_collapsed');
        if (savedCollapsed === 'true') {
            this.setCollapsed(true);
        }
    }

    setupSearch() {
        if (!this.searchInput) return;
        let debounceTimer;
        this.searchInput.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                this.searchTerm = e.target.value.trim().toLowerCase();
                this.render();
            }, 120);
        });
    }

    setupTabs() {
        document.querySelectorAll('.wl-subtab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.wl-subtab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                this.currentTab = tab.getAttribute('data-tab') || 'fno';
                this.render();
            });
        });
    }

    setupToggle() {
        const toggleBtn = document.getElementById('btnToggleWatchlist');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                const isCollapsed = this.container.classList.contains('collapsed');
                this.setCollapsed(!isCollapsed);
            });
        }
    }

    setCollapsed(collapsed) {
        if (!this.container) return;
        if (collapsed) {
            this.container.classList.add('collapsed');
            localStorage.setItem('agi_watchlist_collapsed', 'true');
        } else {
            this.container.classList.remove('collapsed');
            localStorage.setItem('agi_watchlist_collapsed', 'false');
        }
        store.set('watchlistCollapsed', collapsed);
        // Notify chart to resize
        store.emit('viewport_resized', {});
    }

    render() {
        if (!this.listEl) return;
        const items = WATCHLIST_DATA[this.currentTab] || [];
        const filtered = items.filter(it => {
            if (!this.searchTerm) return true;
            return it.symbol.toLowerCase().includes(this.searchTerm) ||
                   it.desc.toLowerCase().includes(this.searchTerm);
        });

        const selectedSym = store.get('selectedSymbol');

        this.listEl.innerHTML = filtered.map(item => {
            const isUp = item.chg >= 0;
            const chgColor = isUp ? 'var(--bull-green)' : 'var(--bear-red)';
            const chgSign = isUp ? '+' : '';
            const isSelected = selectedSym === item.id;

            return `
                <div class="wl-contract-card ${isSelected ? 'active' : ''}" data-id="${item.id}" data-symbol="${item.symbol}" data-type="${item.type}" data-ltp="${item.ltp}" data-chg="${item.chg}" data-pct="${item.pct}">
                    <div style="min-width: 0; overflow: hidden;">
                        <span class="wl-sym-primary">${item.symbol}</span>
                        <span class="wl-sym-desc">${item.desc}</span>
                    </div>
                    <div class="wl-price-col">
                        <span class="wl-price-ltp">₹${item.ltp.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                        <span class="wl-price-chg" style="color: ${chgColor};">${chgSign}${item.chg.toFixed(2)} (${chgSign}${item.pct.toFixed(2)}%)</span>
                    </div>
                </div>
            `;
        }).join('');

        this.listEl.querySelectorAll('.wl-contract-card').forEach(card => {
            card.addEventListener('click', () => {
                const id = card.getAttribute('data-id');
                const symbol = card.getAttribute('data-symbol');
                const type = card.getAttribute('data-type');
                const ltp = parseFloat(card.getAttribute('data-ltp'));
                const chg = parseFloat(card.getAttribute('data-chg'));
                const pct = parseFloat(card.getAttribute('data-pct'));

                store.update({
                    selectedSymbol: id,
                    selectedContractName: symbol,
                    selectedContractType: type,
                    selectedContractLtp: ltp,
                    selectedContractChg: chg,
                    selectedContractChgPct: pct
                });

                store.emit('symbol_changed', { id, symbol, type, ltp, chg, pct });
                this.render();
            });
        });
    }
}

export const watchlistController = new WatchlistController();
