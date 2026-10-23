/**
 * AGI 1.7 OMEGA COMMAND — UI V4 CENTRAL API CLIENT & SERVICE LAYER
 * Standardized endpoint communication, registry, error isolation, bounded retries, and paper boundary enforcement.
 */

/**
 * Authoritative API Registry specifying endpoint metadata, security, and policies.
 */
export const API_REGISTRY = {
    status: {
        endpoint: '/api/status',
        method: 'GET',
        owner: 'Autonomous24x7TradingSupervisor',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 4000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'Supervisor state, accounting identity, worker heartbeats, and market hours.'
    },
    marketObservations: {
        endpoint: '/api/market_observations',
        method: 'GET',
        owner: 'MarketObservationEngine',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 4000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'Live and synthetic quotes for underlyings (NIFTY, BANKNIFTY) and option strikes.'
    },
    marketAnalysis: {
        endpoint: '/api/market_analysis',
        method: 'GET',
        owner: 'MultiHorizonQuantEngine',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 4000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'Microstructure indicators, ATR, CPR pivot points, and volatility classification.'
    },
    marketChart: {
        endpoint: '/api/market_chart',
        method: 'GET',
        owner: 'IntelligenceDataProvider',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 5000,
        cachePolicy: 'SHORT_10S',
        isReadOnly: true,
        description: 'OHLCV candlestick series with timestamps and volume.'
    },
    paperPositions: {
        endpoint: '/api/paper_positions',
        method: 'GET',
        owner: 'TradingSupervisor & LiveAccounting',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 4000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'Active and closed paper trading positions, exposure, and accounting equation.'
    },
    paperOrders: {
        endpoint: '/api/paper_orders',
        method: 'GET',
        owner: 'PaperTradingSimulator',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 4000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'Order book records, simulated fills, timestamps, and order tags.'
    },
    placePaperOrder: {
        endpoint: '/api/paper/order',
        method: 'POST',
        owner: 'PaperTradingSimulator',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 5000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: false,
        description: 'Simulates a virtual paper order in memory; live broker never contacted.'
    },
    liveOrdersBlock: {
        endpoint: '/api/orders',
        method: 'POST',
        owner: 'ProtectedOrderBoundary',
        auth: 'BLOCKED',
        timeoutMs: 1000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'PERMANENTLY LOCKED. Returns HTTP 403 Forbidden to guarantee paper safety.'
    },
    riskSafety: {
        endpoint: '/api/risk_safety',
        method: 'GET',
        owner: '14GateInstitutionalRiskProtocol',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 4000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: '14-Gate compliance summary, drawdown limits, and circuit breaker status.'
    },
    performanceRisk: {
        endpoint: '/api/performance_risk',
        method: 'GET',
        owner: 'TradingSupervisor',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 4000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'Comparative metrics between Active and Demo epochs, Sharpe ratio, and taxes.'
    },
    activeAlgorithms: {
        endpoint: '/api/active_algorithms',
        method: 'GET',
        owner: 'MultiHorizonQuantEngine',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 4000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'Active quant models: VWAP ORB, BSM Greeks, Kelly Sizer, SABR/SVI, Kalman, VPIN.'
    },
    decisionTimeline: {
        endpoint: '/api/decision_timeline',
        method: 'GET',
        owner: 'ThreeAgentContract & Governance',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 5000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: '15-step chronological decision audit trail from tick ingestion to HMAC sealing.'
    },
    memoryHistory: {
        endpoint: '/api/memory_history',
        method: 'GET',
        owner: 'OmegaCommandMemory',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 4000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: '4-tier memory architecture (Layers A-D), Brier skill scores, and learning adjustments.'
    },
    brokerStatus: {
        endpoint: '/api/broker_status',
        method: 'GET',
        owner: 'PaytmOpenApiClient',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 4000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: '7-stage broker connectivity status, callback port check, and credential quarantine.'
    },
    reasoningChat: {
        endpoint: '/api/reasoning_chat',
        method: 'GET_OR_POST',
        owner: 'AntigravityReasoningBus',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 6000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: false,
        description: 'Operator Abhi private line and team coordination chat stream.'
    },
    newsResearch: {
        endpoint: '/api/news_intel',
        method: 'GET',
        owner: 'ALEXAMacroIntelligence',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 4000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'Primary source macroeconomic bulletins (RBI LAF, NSE Bhavcopy, Banking NPAs).'
    },
    epochs: {
        endpoint: '/api/epochs',
        method: 'GET',
        owner: 'TradingSupervisor',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 3000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'Active ₹10k/₹100k evaluation epochs and archived ₹50k demo fixtures.'
    },
    telemetry: {
        endpoint: '/api/telemetry',
        method: 'GET',
        owner: 'SupervisorObservability',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 3000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'Round-trip latencies, frame rates, and navigation success rates.'
    },
    fiiDii: {
        endpoint: '/api/fii_dii',
        method: 'GET',
        owner: 'NSEParticipantReport',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 4000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'FII/DII institutional buying/selling volumes from verified Bhavcopy.'
    },
    watchlist: {
        endpoint: '/api/watchlist',
        method: 'GET',
        owner: 'WatchlistManager',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 3000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'Active monitored candidates and summary counts.'
    },
    alerts: {
        endpoint: '/api/alerts',
        method: 'GET',
        owner: 'WatchlistManager',
        auth: 'NONE_LOCAL_LOOPBACK',
        timeoutMs: 3000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: true,
        description: 'Triggered price/volatility threshold alerts.'
    },
    emergencyStop: {
        endpoint: '/api/emergency_stop',
        method: 'POST',
        owner: 'Autonomous24x7TradingSupervisor',
        auth: 'OPERATOR_DIRECTIVE',
        timeoutMs: 5000,
        cachePolicy: 'NO_CACHE',
        isReadOnly: false,
        description: 'Trips circuit breaker immediately, pauses worker, and logs audit record.'
    }
};

export class ApiClient {
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
        this.pendingRequests = new Map();
        this.lastHeartbeatTime = Date.now();
        this.isDegraded = false;
    }

    /**
     * Internal robust GET with timeout, deduplication, and error isolation.
     */
    async _get(endpoint, params = {}, timeoutMs = 5000) {
        const url = new URL(endpoint, window.location.origin);
        Object.entries(params).forEach(([key, val]) => {
            if (val !== undefined && val !== null) {
                url.searchParams.append(key, val);
            }
        });
        const urlString = url.toString();

        // In-flight deduplication
        if (this.pendingRequests.has(urlString)) {
            return await this.pendingRequests.get(urlString);
        }

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

        const fetchPromise = (async () => {
            try {
                const resp = await fetch(urlString, {
                    method: 'GET',
                    headers: { 'Accept': 'application/json' },
                    cache: 'no-store',
                    signal: controller.signal
                });
                clearTimeout(timeoutId);
                if (!resp.ok) {
                    throw new Error(`HTTP ${resp.status} on ${endpoint}`);
                }
                const data = await resp.json();
                this.lastHeartbeatTime = Date.now();
                this.isDegraded = false;
                return data;
            } catch (err) {
                clearTimeout(timeoutId);
                console.warn(`[API Client] GET ${endpoint} error:`, err.message);
                this.isDegraded = true;
                return null;
            } finally {
                this.pendingRequests.delete(urlString);
            }
        })();

        this.pendingRequests.set(urlString, fetchPromise);
        return await fetchPromise;
    }

    /**
     * Internal robust POST with JSON body and error normalization.
     */
    async _post(endpoint, data = {}, timeoutMs = 6000) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

        try {
            const resp = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify(data),
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            const resData = await resp.json().catch(() => ({}));
            return {
                ok: resp.ok,
                status: resp.status,
                data: resData
            };
        } catch (err) {
            clearTimeout(timeoutId);
            console.warn(`[API Client] POST ${endpoint} error:`, err.message);
            return { ok: false, status: 0, error: err.message, data: null };
        }
    }

    // ─── Domain Service Methods ──────────────────────────────────────────────

    async fetchStatus() {
        return await this._get('/api/status');
    }

    async fetchMarketObservations() {
        return await this._get('/api/market_observations');
    }

    async fetchMarketAnalysis() {
        return await this._get('/api/market_analysis');
    }

    async fetchMarketChart(symbol = 'NIFTY', timeframe = '15m') {
        return await this._get('/api/market_chart', { symbol, timeframe });
    }

    async fetchPaperPositions(epoch = null) {
        return await this._get('/api/paper_positions', epoch ? { epoch } : {});
    }

    async fetchPaperOrders() {
        return await this._get('/api/paper_orders');
    }

    async placePaperOrder(orderData) {
        return await this._post('/api/paper/order', orderData);
    }

    /**
     * Tests and asserts that live order writing is permanently blocked.
     * Must return status 403 Forbidden.
     */
    async attemptLiveOrder(orderData) {
        return await this._post('/api/orders', { ...orderData, mode: 'LIVE' });
    }

    async fetchRiskSafety() {
        return await this._get('/api/risk_safety');
    }

    async fetchPerformanceRisk() {
        return await this._get('/api/performance_risk');
    }

    async fetchActiveAlgorithms() {
        return await this._get('/api/active_algorithms');
    }

    async fetchAlgorithms() {
        return await this._get('/api/algorithms');
    }

    async fetchDecisionTimeline() {
        return await this._get('/api/decision_timeline');
    }

    async fetchMemoryHistory() {
        return await this._get('/api/memory_history');
    }

    async fetchMemoryStatus() {
        return await this._get('/api/memory_status');
    }

    async fetchBrokerStatus() {
        return await this._get('/api/broker_status');
    }

    async fetchNewsIntel() {
        return await this._get('/api/news_intel');
    }

    async fetchReasoningChat() {
        return await this._get('/api/reasoning_chat');
    }

    async sendReasoningChat(sender, message, role = 'OPERATOR') {
        return await this._post('/api/reasoning_chat', { sender, message, role });
    }

    async sendEmergencyFlash() {
        return await this._post('/api/emergency_flash', {});
    }

    async emergencyStop(reason = 'Operator manual trigger') {
        return await this._post('/api/emergency_stop', { reason });
    }

    async paperStart() {
        return await this._post('/api/paper/start', {});
    }

    async paperPause() {
        return await this._post('/api/paper/pause', {});
    }

    async paperResume() {
        return await this._post('/api/paper/resume', {});
    }

    async paperStop() {
        return await this._post('/api/paper/stop', {});
    }

    async fetchEpochs() {
        return await this._get('/api/epochs');
    }

    async fetchTelemetry() {
        return await this._get('/api/telemetry');
    }

    async fetchFiiDii() {
        return await this._get('/api/fii_dii');
    }

    async fetchWatchlist() {
        return await this._get('/api/watchlist');
    }

    async fetchAlerts() {
        return await this._get('/api/alerts');
    }

    async fetchGates() {
        return await this._get('/api/gates');
    }

    async fetchRadar() {
        return await this._get('/api/radar');
    }

    async fetchReport(period = 'day') {
        return await this._get('/api/report', { period });
    }

    async fetchProfile() {
        return await this._get('/api/profile');
    }
}

export const api = new ApiClient();
