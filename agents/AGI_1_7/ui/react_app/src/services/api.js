/**
 * Central API Client for AGI 1.7 OMEGA COMMAND (V5 Final)
 * Strictly connects to authoritative backend services on 127.0.0.1:8088.
 */

const BASE_URL = '';

async function fetchJson(endpoint, options = {}) {
  try {
    const res = await fetch(`${BASE_URL}${endpoint}`, {
      headers: {
        'Accept': 'application/json',
        ...(options.headers || {})
      },
      ...options
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error || `API ${endpoint} failed with HTTP ${res.status}`);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  } catch (err) {
    console.warn(`[API Warning] ${endpoint}:`, err.message);
    throw err;
  }
}

export const api = {
  // Telemetry and Reconciled Accounting (epoch-aware)
  async getStatus(epochId) {
    const q = epochId ? `?epoch=${encodeURIComponent(epochId)}` : '';
    return fetchJson(`/api/status${q}`);
  },

  // Authoritative Portfolio Equity Curve (epoch-aware)
  async getPortfolioEquity(timeframe = '15m', epochId) {
    const qEpoch = epochId ? `&epoch=${encodeURIComponent(epochId)}` : '';
    return fetchJson(`/api/market_chart?symbol=PORTFOLIO_EQUITY&timeframe=${encodeURIComponent(timeframe)}${qEpoch}`);
  },

  // Active Paper Positions and Orders (epoch-aware)
  async getPaperPositions(epochId) {
    const q = epochId ? `?epoch=${encodeURIComponent(epochId)}` : '';
    return fetchJson(`/api/paper_positions${q}`);
  },

  // Paper Capital Allocation & Reserves (epoch-aware)
  async getLivePortfolio(epochId) {
    const q = epochId ? `?epoch=${encodeURIComponent(epochId)}` : '';
    return fetchJson(`/api/live_portfolio${q}`);
  },

  // Agent Reasoning & Directives Stream
  async getReasoningChat() {
    return fetchJson('/api/reasoning_chat');
  },

  // Post Operator Directive to Manager Abhi
  async sendDirective(text, author = 'Operator Abhi') {
    return fetchJson('/api/reasoning_chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'directive',
        author: author,
        message: text,
        timestamp: new Date().toISOString()
      })
    });
  },

  // News, Regulatory & Macro Intelligence
  async getNewsIntel() {
    return fetchJson('/api/news_intel');
  },

  // Real ChatGPT Browser Bridge Thread Logs
  async getChatGPTThread() {
    return fetchJson('/api/chatgpt/thread');
  },

  // Verified Algorithms Catalog
  async getAlgorithms() {
    return fetchJson('/api/algorithms');
  },

  // Structured Intelligence Audit Reports
  async getReport(period = 'day') {
    return fetchJson(`/api/report?period=${encodeURIComponent(period)}`);
  },

  // Operator Profile & System Diagnostics
  async getProfile() {
    return fetchJson('/api/profile');
  },

  // Paytm Money Open API Session Diagnostics & Verification
  async getPaytmSessionStatus() {
    return fetchJson('/api/paytm/session_status');
  },

  async verifyPaytmSession() {
    return fetchJson('/api/paytm/verify_session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
  },

  async updatePaytmSession(tokenData) {
    return fetchJson('/api/paytm/update_session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(tokenData)
    });
  },

  async getPaytmKeepAliveStatus() {
    return fetchJson('/api/paytm/keepalive_status');
  },

  // Structured Memory & Learning Catalog
  async getMemoryAudit() {
    return fetchJson('/api/memory_audit');
  },

  // Market Candlesticks for Underlying / Option
  async getMarketCandles(symbol = 'NIFTY', timeframe = '15m') {
    return fetchJson(`/api/market_chart?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`);
  },

  // Authoritative Epochs Catalog
  async getEpochs() {
    return fetchJson('/api/epochs');
  },

  // Create Custom Paper Capital Epoch
  async createCustomEpoch(capital, label = 'Custom Paper Capital') {
    return fetchJson('/api/epochs/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        capital: Number(capital),
        label: label
      })
    });
  },

  // -------------------------------------------------------------
  // Phase 13 Research Laboratory Endpoints
  // -------------------------------------------------------------
  async getResearchStrategies() {
    return fetchJson('/api/research/strategies');
  },

  async getResearchStrategyDetails(id) {
    return fetchJson(`/api/research/strategy_details?id=${encodeURIComponent(id)}`);
  },

  async getResearchDatasets() {
    return fetchJson('/api/research/datasets');
  },

  async getResearchJobs() {
    return fetchJson('/api/research/jobs');
  },

  async getResearchExperiments() {
    return fetchJson('/api/research/experiments');
  },

  async getResearchExplainability(strategyId = 'STRAT-ORB-V1') {
    return fetchJson(`/api/research/explainability?strategy_id=${encodeURIComponent(strategyId)}`);
  },

  async runResearchExperiment(payload) {
    return fetchJson('/api/research/experiments/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  },

  async cancelResearchJob(jobId) {
    return fetchJson('/api/research/jobs/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: jobId })
    });
  },

  // -------------------------------------------------------------
  // Phase 14 Session Control Plane & Operator Orchestration
  // -------------------------------------------------------------
  async getSessionStatus() {
    return fetchJson('/api/session/current');
  },

  async getSessionIntakeQuestion() {
    return fetchJson('/api/session/intake');
  },

  async getSessionConfigPreview() {
    return fetchJson('/api/session/config/preview');
  },

  async startSessionIntake() {
    return fetchJson('/api/session/intake/start', { method: 'POST' });
  },

  async answerSessionIntake(answer) {
    return fetchJson('/api/session/intake/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer })
    });
  },

  async loadSessionDefaults() {
    return fetchJson('/api/session/intake/defaults', { method: 'POST' });
  },

  async bulkSubmitSessionConfig(answers) {
    return fetchJson('/api/session/intake/bulk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers })
    });
  },

  async confirmSession(phrase = 'CONFIRM PAPER SESSION') {
    return fetchJson('/api/session/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phrase })
    });
  },

  async runSessionPreflight() {
    return fetchJson('/api/session/preflight', { method: 'POST' });
  },

  async pauseSession() {
    return fetchJson('/api/session/pause', { method: 'POST' });
  },

  async resumeSession() {
    return fetchJson('/api/session/resume', { method: 'POST' });
  },

  async stopSession() {
    return fetchJson('/api/session/stop', { method: 'POST' });
  },

  async emergencyStopSession(reason = 'Operator manual emergency stop') {
    return fetchJson('/api/session/emergency_stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason })
    });
  },

  async getSessionEvents() {
    return fetchJson('/api/session/events');
  },

  async getSessionHealth() {
    return fetchJson('/api/session/health');
  },

  // -------------------------------------------------------------
  // Phase 17.17 Controlled Operating Mode & Live Validation Endpoints
  // -------------------------------------------------------------
  async getOperatingModeStatus() {
    return fetchJson('/api/mode/status');
  },

  async getLiveReadiness() {
    return fetchJson('/api/mode/readiness');
  },

  async setOperatingMode(mode, reason = 'Operator requested via UI') {
    return fetchJson('/api/mode/set', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, reason })
    });
  },

  async triggerEmergencyStop(reason = 'Operator manual emergency stop') {
    return fetchJson('/api/mode/emergency_stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason })
    });
  },

  async disarmLiveExecution(reason = 'Operator requested disarm') {
    return fetchJson('/api/mode/disarm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason })
    });
  },

  async getLiveDataValidation() {
    return fetchJson('/api/live_data/validation');
  },

  async reconcileAccount(brokerData = null, ledgerId = 'epoch_10k') {
    return fetchJson('/api/account/reconcile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ broker_data: brokerData, ledger_id: ledgerId })
    });
  },

  async getPendingOrderReviews() {
    return fetchJson('/api/order/pending_reviews');
  },

  async proposeOrderReview(order, operator = 'Operator Abhi') {
    return fetchJson('/api/order/propose_review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ order, operator })
    });
  },

  async approveOrderReview(intentId, signature, operator = 'Operator Abhi') {
    return fetchJson('/api/order/approve_review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intent_id: intentId, signature, operator })
    });
  },

  // -------------------------------------------------------------
  // Phase 17.21 OMEGA Control Center Endpoints
  // -------------------------------------------------------------
  async getCatalogAlgorithms(category, status) {
    const params = new URLSearchParams();
    if (category) params.append('category', category);
    if (status) params.append('status', status);
    const q = params.toString() ? `?${params.toString()}` : '';
    return fetchJson(`/api/catalog/algorithms${q}`);
  },

  async getCatalogAlgorithm(id) {
    return fetchJson(`/api/catalog/algorithms/${encodeURIComponent(id)}`);
  },

  async toggleCatalogAlgorithm(id, enabled) {
    return fetchJson(`/api/catalog/algorithms/${encodeURIComponent(id)}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
  },

  async getCatalogAgents(family, status, runtime_type) {
    const params = new URLSearchParams();
    if (family) params.append('family', family);
    if (status) params.append('status', status);
    if (runtime_type) params.append('runtime_type', runtime_type);
    const q = params.toString() ? `?${params.toString()}` : '';
    return fetchJson(`/api/catalog/agents${q}`);
  },

  async getAgentSummaryMetrics() {
    return fetchJson('/api/catalog/agents/summary');
  },

  async getCatalogAgent(id) {
    return fetchJson(`/api/catalog/agents/${encodeURIComponent(id)}`);
  },

  async getOrchestrationTasks(jobId, parentId, state) {
    const params = new URLSearchParams();
    if (jobId) params.append('job_id', jobId);
    if (parentId) params.append('parent_task_id', parentId);
    if (state) params.append('state', state);
    const q = params.toString() ? `?${params.toString()}` : '';
    return fetchJson(`/api/orchestration/tasks${q}`);
  },

  async getOrchestrationTask(taskId) {
    return fetchJson(`/api/orchestration/tasks/${encodeURIComponent(taskId)}`);
  },

  async getOrchestrationOverview() {
    return fetchJson('/api/orchestration/overview');
  },

  async cancelOrchestrationTask(taskId, reason = 'Operator cancelled via UI') {
    return fetchJson(`/api/orchestration/tasks/${encodeURIComponent(taskId)}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason })
    });
  },

  async getDeploymentReadiness() {
    return fetchJson('/api/release/readiness');
  },

  async verifyCatalogAlgorithms() {
    return fetchJson('/api/catalog/algorithms/verify');
  },

  async recordTaskHeartbeat(taskId, timestamp, pid) {
    return fetchJson(`/api/orchestration/tasks/${encodeURIComponent(taskId)}/heartbeat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ timestamp, pid })
    });
  },

  // Emily Intelligence & Working Now Controls
  async getEmilyStatus() {
    return fetchJson('/api/emily/status');
  },

  async startEmilyWorkingNow() {
    return fetchJson('/api/emily/start_working_now', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'START_WORKING_NOW', timestamp: new Date().toISOString() })
    });
  },

  async revertEmilyDefault() {
    return fetchJson('/api/emily/revert_default', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'REVERT_DEFAULT', timestamp: new Date().toISOString() })
    });
  },

  // Scraped Real Browser Observations from Chrome Port 9229
  async getLiveObservations() {
    return fetchJson('/api/live_observations');
  }
};



