/**
 * AGI 1.7 OMEGA COMMAND — UI V4 REACTIVE APPLICATION STATE
 * Pub/Sub Event Bus and Centralized State Store for Multi-Page Quantitative Terminal
 */

class StateStore {
    constructor() {
        this.state = {
            // Navigation
            activePage: 'trading', // 'trading' | 'market' | 'options' | 'intelligence' | 'portfolio' | 'activity' | 'strategies' | 'memory' | 'system' | 'settings'
            activeWorkspace: 'trading', // compatibility alias
            mobileMenuOpen: false,

            // Selected Instrument (Reconciled from verified Paytm Money DOM session close)
            selectedSymbol: 'NIFTY',
            selectedContractName: 'NIFTY 50',
            selectedContractType: 'INDEX',
            selectedContractLtp: 22622.70,
            selectedContractChg: -99.25,
            selectedContractChgPct: -0.44,
            marketState: 'CLOSED',
            dataState: 'EOD_VERIFIED_SNAPSHOT',
            sourceTimestamp: '2026-10-14 15:30:00 IST',
            receiveTimestamp: '2026-10-14 15:30:00 IST',
            chartMode: 'spot', // 'spot' | 'option' | 'equity'
            chartTimeframe: '15m',
            selectedEpoch: 'EPOCH-PAPER-100K-MULTI-ASSET',

            // UI Layout & Panels
            sidebarCollapsed: false,
            drawerOpen: window.innerWidth >= 1680,
            drawerTab: 'oc', // 'oc' | 'depth' | 'details' | 'agi'
            watchlistTab: 'fno',
            watchlistCollapsed: false,
            activeLedgerTab: 'positions', // 'positions' | 'orders' | 'history'
            activeChatChannel: 'mgr', // 'mgr' | 'team'

            // Data Stores
            statusData: null,
            marketObservations: null,
            marketAnalysis: null,
            positionsData: null,
            paperOrders: [],
            riskData: null,
            performanceRisk: null,
            activeAlgorithms: null,
            decisionTimeline: null,
            memoryHistory: null,
            brokerStatus: null,
            chartData: null,
            chatMessages: [],
            newsDocuments: [],
            fiiDiiData: null,
            telemetry: {
                quoteLatencyMs: 32,
                domPollLatencyMs: 12,
                cdpConnected: true,
                callbackConnected: true,
                fps: 60
            },

            // Settings & Preferences
            settings: {
                theme: 'paytm-light',
                compactRibbon: false,
                reduceMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
                soundAlerts: false,
                autoRefresh: true,
                refreshIntervalMs: 3500
            }
        };

        this.listeners = new Map();
    }

    getState() {
        return this.state;
    }

    get(key) {
        return this.state[key];
    }

    set(key, value, silent = false) {
        const oldVal = this.state[key];
        if (oldVal === value) return;
        this.state[key] = value;
        // Keep activeWorkspace in sync if activePage changes
        if (key === 'activePage') {
            this.state.activeWorkspace = value;
        } else if (key === 'activeWorkspace') {
            this.state.activePage = value;
        }
        if (!silent) {
            this.emit(key, { value, oldValue: oldVal });
            this.emit('state_changed', { key, value, oldValue: oldVal });
        }
    }

    update(partialState, silent = false) {
        const changes = {};
        Object.entries(partialState).forEach(([key, val]) => {
            if (this.state[key] !== val) {
                changes[key] = { value: val, oldValue: this.state[key] };
                this.state[key] = val;
                if (key === 'activePage') this.state.activeWorkspace = val;
                if (key === 'activeWorkspace') this.state.activePage = val;
                if (!silent) {
                    this.emit(key, changes[key]);
                }
            }
        });
        if (!silent && Object.keys(changes).length > 0) {
            this.emit('state_changed', changes);
        }
    }

    subscribe(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, new Set());
        }
        this.listeners.get(event).add(callback);
        return () => this.unsubscribe(event, callback);
    }

    unsubscribe(event, callback) {
        if (this.listeners.has(event)) {
            this.listeners.get(event).delete(callback);
        }
    }

    emit(event, payload) {
        if (this.listeners.has(event)) {
            this.listeners.get(event).forEach(cb => {
                try {
                    cb(payload);
                } catch (err) {
                    console.error(`[State Error] in listener for '${event}':`, err);
                }
            });
        }
    }
}

export const store = new StateStore();
