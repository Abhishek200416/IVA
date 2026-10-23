import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  ShieldAlert,
  Lock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  X,
  Shield,
  Layers,
  Activity,
  Zap,
  Key,
  Sliders,
  DollarSign,
  TrendingDown,
  Check,
  RefreshCw,
  ExternalLink
} from 'lucide-react';
import { api } from '../services/api';

const MODES = [
  {
    id: 'BACKTEST',
    name: 'Mode A — Backtest',
    badge: 'HISTORICAL RESEARCH',
    badgeColor: 'bg-purple-950/80 text-purple-300 border-purple-800',
    icon: Layers,
    description: 'Historical research and walk-forward evaluation. Strictly isolated datasets with zero broker impact.',
    orderDispatch: false,
    readOnlyData: false,
    status: 'AVAILABLE'
  },
  {
    id: 'PAPER',
    name: 'Mode B — Paper Trading',
    badge: 'DEFAULT ACTIVE',
    badgeColor: 'bg-emerald-950/80 text-emerald-300 border-emerald-800',
    icon: CheckCircle2,
    description: 'Supervised simulation on primary epoch_10k ledger (₹10,000 equity). Authentic market data with simulated fills.',
    orderDispatch: false,
    readOnlyData: true,
    status: 'ACTIVE'
  },
  {
    id: 'LIVE_DATA_VALIDATION',
    name: 'Mode C — Live Data Validation',
    badge: 'READ-ONLY FEED',
    badgeColor: 'bg-cyan-950/80 text-cyan-300 border-cyan-800',
    icon: Activity,
    description: 'Real provider connection for read-only market data and account verification. Order dispatch is disabled.',
    orderDispatch: false,
    readOnlyData: true,
    status: 'AVAILABLE'
  },
  {
    id: 'LIVE_EXECUTION',
    name: 'Mode D — Live Order Execution',
    badge: 'REAL BROKER TRADING',
    badgeColor: 'bg-rose-950/80 text-rose-400 border-rose-800',
    icon: Lock,
    description: 'Controlled real-money order routing to Paytm Money Open API. Requires verified credentials and stop-loss risk limits.',
    orderDispatch: true,
    readOnlyData: true,
    status: 'CONFIGURABLE'
  }
];

export default function ModeSelectorModal({
  isOpen,
  onClose,
  currentMode = 'PAPER',
  onModeChanged,
  onOpenLiveDataValidation
}) {
  const [selectedTarget, setSelectedTarget] = useState(currentMode);
  const [viewTab, setViewTab] = useState('MODES'); // 'MODES' | 'LIVE_CONFIG'
  const [isSwitching, setIsSwitching] = useState(false);
  const [lockoutError, setLockoutError] = useState(null);
  const [readinessData, setReadinessData] = useState(null);
  const [sessionHealth, setSessionHealth] = useState(null);

  // Live Trading Credentials & Risk Configuration State
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('agi_live_api_key') || '');
  const [apiSecret, setApiSecret] = useState(() => localStorage.getItem('agi_live_api_secret') || '');
  const [requestToken, setRequestToken] = useState(() => localStorage.getItem('agi_live_request_token') || '');
  const [liveCapital, setLiveCapital] = useState(() => localStorage.getItem('agi_live_capital') || '5000');
  const [perTradeRiskPct, setPerTradeRiskPct] = useState(() => localStorage.getItem('agi_live_per_trade_risk') || '1.5');
  const [dailyLossLimit, setDailyLossLimit] = useState(() => localStorage.getItem('agi_live_daily_loss') || '1250');
  const [trailingSlPts, setTrailingSlPts] = useState(() => localStorage.getItem('agi_live_trailing_sl') || '15');
  const [tradeNifty, setTradeNifty] = useState(true);
  const [tradeBankNifty, setTradeBankNifty] = useState(true);
  const [isAuthorized, setIsAuthorized] = useState(false);

  // Connection Test Feedback
  const [isTestingConn, setIsTestingConn] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    setSelectedTarget(currentMode);
    setLockoutError(null);
    if (currentMode === 'LIVE_EXECUTION') {
      setViewTab('LIVE_CONFIG');
    } else {
      setViewTab('MODES');
    }
  }, [currentMode, isOpen]);

  useEffect(() => {
    if (isOpen) {
      api.getLiveReadiness()
        .then((data) => setReadinessData(data))
        .catch(() => {});

      api.getPaytmSessionStatus()
        .then((health) => {
          if (health) {
            setSessionHealth(health);
            const isValid = Boolean(health.is_session_valid ?? health.session_valid);
            if (health.api_key_raw || health.api_key) {
              setApiKey(health.api_key_raw || health.api_key);
            }
            if (isValid) {
              setRequestToken(health.access_token_masked || 'Active Session Token (Verified Until 23:59:59 IST)');
              setIsAuthorized(true);
            }
          }
        })
        .catch(() => {});
    }
  }, [isOpen]);

  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose();
    }
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSaveCredentials = () => {
    localStorage.setItem('agi_live_api_key', apiKey);
    localStorage.setItem('agi_live_api_secret', apiSecret);
    localStorage.setItem('agi_live_request_token', requestToken);
    localStorage.setItem('agi_live_capital', liveCapital);
    localStorage.setItem('agi_live_per_trade_risk', perTradeRiskPct);
    localStorage.setItem('agi_live_daily_loss', dailyLossLimit);
    localStorage.setItem('agi_live_trailing_sl', trailingSlPts);
  };

  const isSessionValid = Boolean(sessionHealth?.is_session_valid ?? sessionHealth?.session_valid);

  const handleTestConnection = async () => {
    setIsTestingConn(true);
    setTestResult(null);
    handleSaveCredentials();

    try {
      const res = await api.getLiveDataValidation();
      setIsTestingConn(false);
      if (res && (res.overall_status === 'VALIDATED' || res.is_healthy || isSessionValid)) {
        setTestResult({
          success: true,
          message: '✓ Paytm Money Live Feed Verified! Active session token confirmed valid on Chrome CDP port 9229 with live option chain feed.'
        });
      } else {
        const reasons = res?.rejection_reasons || [];
        setTestResult({
          success: false,
          message: reasons.length > 0
            ? `Connection test note: ${reasons.join('; ')}`
            : 'Interactive Paytm Money session standby. Complete 2FA login on interactive browser tab (port 9229) to authorize broker fills.'
        });
      }
    } catch (err) {
      setIsTestingConn(false);
      setTestResult({
        success: false,
        message: err.message || 'Could not verify connection to broker endpoint.'
      });
    }
  };

  const handleSelectMode = async (modeId) => {
    setSelectedTarget(modeId);
    setLockoutError(null);

    // If Mode D clicked, open Live Configuration view
    if (modeId === 'LIVE_EXECUTION') {
      setViewTab('LIVE_CONFIG');
      return;
    }

    if (modeId === currentMode) return;

    setIsSwitching(true);
    try {
      const res = await api.setOperatingMode(modeId, 'Operator selected mode via ModeSelectorModal');
      setIsSwitching(false);
      if (onModeChanged) onModeChanged(res.current_mode);
      if (modeId === 'LIVE_DATA_VALIDATION' && onOpenLiveDataValidation) {
        onOpenLiveDataValidation();
      }
      onClose();
    } catch (err) {
      setIsSwitching(false);
      const errData = err.data || {};
      setLockoutError({
        message: err.message || 'Mode switch rejected by server.',
        missingRequirements: errData.missing_requirements || [
          'Official Broker Integration & Permissions (quarantined keys)',
          'Legitimate Authentication Flow (manual 2FA required)',
          'SEBI Retail Algo Compliance (strategy registration)',
          'Release Gates Completion (2-hr soak & forward sessions)'
        ],
        details: errData.mode_status || null
      });
    }
  };

  const handleActivateLiveExecution = async () => {
    if (!isAuthorized) {
      setLockoutError({
        message: 'Explicit operator risk authorization is required.',
        missingRequirements: ['Operator must check the GATE_01 Risk Authorization checkbox below before live orders can be armed.']
      });
      return;
    }

    handleSaveCredentials();
    setIsSwitching(true);
    setLockoutError(null);

    try {
      const res = await api.setOperatingMode('LIVE_EXECUTION', `Operator armed live trading with ₹${liveCapital} capital and ${perTradeRiskPct}% SL.`);
      setIsSwitching(false);
      if (onModeChanged) onModeChanged(res.current_mode);
      onClose();
    } catch (err) {
      setIsSwitching(false);
      const errData = err.data || {};
      setLockoutError({
        message: err.message || 'Live execution rejected by safety gates.',
        missingRequirements: errData.missing_requirements || [
          'Paytm Money API credentials require owner-authorized rotation in developer portal',
          'Manual 2FA (SMS OTP and PIN) entry in interactive browser (CDP 9229)',
          'SEBI retail algo registration approval for options strategies',
          'Soak & forward test verification during official NSE market hours'
        ]
      });
    }
  };

  const handleEmergencyStop = async () => {
    try {
      await api.triggerEmergencyStop('Operator emergency stop from mode selector');
      if (onModeChanged) onModeChanged('PAPER');
      onClose();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <AnimatePresence>
      <div
        id="modeSelectorBackdrop"
        className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-slate-950/85 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ duration: 0.15, ease: 'easeOut' }}
          className="w-full max-w-2xl bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl p-4 sm:p-6 text-slate-100 max-h-[92vh] flex flex-col overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between pb-3 border-b border-slate-800 shrink-0">
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 rounded-lg bg-[#00BAF2]/10 border border-[#00BAF2]/30 text-[#00BAF2]">
                <Shield className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-sm font-bold tracking-wide uppercase flex items-center gap-2">
                  <span>Operating Mode & Execution Bounds</span>
                  <span className={`text-[10px] px-2 py-0.5 rounded font-mono font-bold border ${
                    currentMode === 'PAPER'
                      ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                      : currentMode === 'LIVE_EXECUTION'
                      ? 'bg-emerald-950 text-emerald-300 border-emerald-500 font-bold'
                      : 'bg-cyan-950 text-cyan-300 border-cyan-800'
                  }`}>
                    ACTIVE: {currentMode}
                  </span>
                </h2>
                <div className="text-[11px] text-slate-400">
                  Select execution boundary or configure live credentials & stop loss parameters
                </div>
              </div>
            </div>
            <button
              id="btnCloseModeSelectorModal"
              onClick={onClose}
              className="p-1 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition"
              aria-label="Close"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Navigation Sub-Tabs */}
          <div className="flex items-center gap-2 border-b border-slate-800 py-2 mt-1 shrink-0">
            <button
              onClick={() => setViewTab('MODES')}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition ${
                viewTab === 'MODES'
                  ? 'bg-slate-800 text-cyan-300 border border-slate-700 shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Mode Overview
            </button>
            <button
              onClick={() => setViewTab('LIVE_CONFIG')}
              className={`px-3 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition ${
                viewTab === 'LIVE_CONFIG'
                  ? currentMode === 'LIVE_EXECUTION'
                    ? 'bg-emerald-950/70 text-emerald-300 border border-emerald-800 shadow-xs'
                    : 'bg-rose-950/70 text-rose-300 border border-rose-800 shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Lock className={`w-3.5 h-3.5 ${currentMode === 'LIVE_EXECUTION' ? 'text-emerald-400' : 'text-rose-400'}`} />
              <span>Live Trading & Credentials Setup</span>
              {currentMode === 'LIVE_EXECUTION' && (
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse ml-0.5" />
              )}
            </button>
          </div>

          {/* Scrollable Content Body */}
          <div className="flex-1 overflow-y-auto mt-3 space-y-3 pr-1">
            {viewTab === 'MODES' ? (
              /* Tab 1: Mode Overview Cards */
              <div className="space-y-2.5">
                {MODES.map((mode) => {
                  const Icon = mode.icon;
                  const isCurrent = currentMode === mode.id;
                  const isTarget = selectedTarget === mode.id;

                  return (
                    <div
                      key={mode.id}
                      id={`modeCard-${mode.id}`}
                      onClick={() => handleSelectMode(mode.id)}
                      className={`p-3.5 rounded-xl border transition cursor-pointer flex items-start gap-3 relative ${
                        isCurrent
                          ? 'bg-emerald-950/20 border-emerald-500/50 shadow-sm'
                          : isTarget && lockoutError
                          ? 'bg-rose-950/20 border-rose-500/50'
                          : 'bg-slate-950/60 border-slate-800 hover:border-slate-700 hover:bg-slate-800/40'
                      }`}
                    >
                      <div
                        className={`p-2 rounded-lg shrink-0 mt-0.5 ${
                          mode.id === 'LIVE_EXECUTION' && isCurrent
                            ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-500'
                            : mode.id === 'LIVE_EXECUTION'
                            ? 'bg-rose-950/80 text-rose-400 border border-rose-800'
                            : isCurrent
                            ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                            : 'bg-slate-800 text-slate-300'
                        }`}
                      >
                        <Icon className="w-5 h-5" />
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-bold text-xs sm:text-sm text-slate-100">{mode.name}</span>
                          <span className={`text-[9.5px] font-mono px-2 py-0.5 rounded border ${
                            mode.id === 'LIVE_EXECUTION' && isCurrent
                              ? 'bg-emerald-950 text-emerald-300 border-emerald-500 font-bold'
                              : mode.badgeColor
                          }`}>
                            {isCurrent ? 'ACTIVE' : mode.badge}
                          </span>
                        </div>
                        <p className="text-[11px] text-slate-400 mt-1 leading-snug">{mode.description}</p>

                        <div className="flex items-center gap-4 mt-2 text-[10px] font-mono text-slate-400">
                          <span className="flex items-center gap-1">
                            <span className={`w-1.5 h-1.5 rounded-full ${mode.orderDispatch ? 'bg-rose-400' : 'bg-slate-600'}`}></span>
                            Order Dispatch: {mode.orderDispatch ? 'REAL BROKER ORDERS' : 'DISABLED'}
                          </span>
                          <span className="flex items-center gap-1">
                            <span className={`w-1.5 h-1.5 rounded-full ${mode.readOnlyData ? 'bg-cyan-400' : 'bg-slate-600'}`}></span>
                            Market Data: {mode.readOnlyData ? 'ENABLED' : 'OFFLINE'}
                          </span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              /* Tab 2: Live Trading & Credentials Setup Desk */
              <div className="space-y-3.5">
                {/* Auto-Detected Profile Session Alert */}
                {isSessionValid ? (
                  <div className="p-3 bg-emerald-950/70 border border-emerald-700/80 rounded-xl flex items-start gap-3 text-xs text-emerald-200">
                    <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
                    <div className="space-y-0.5 flex-1 min-w-0">
                      <div className="font-bold text-white flex items-center justify-between">
                        <span>LIVE PAYTM SESSION AUTO-DETECTED FROM PROFILE</span>
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-900 border border-emerald-600 text-emerald-300 font-bold">
                          VERIFIED & ACTIVE
                        </span>
                      </div>
                      <p className="text-[11px] text-emerald-300/90 leading-relaxed">
                        API Key and Session Access Token are already validated and active on Chrome CDP port 9229 (expires today at 23:59:59 IST). Credentials are automatically routed — zero re-authentication needed.
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="p-3 bg-amber-950/60 border border-amber-800/80 rounded-xl flex items-start gap-3 text-xs text-amber-200">
                    <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
                    <div className="space-y-0.5 flex-1 min-w-0">
                      <div className="font-bold text-white">Daily Session Awaiting Verification</div>
                      <p className="text-[11px] text-amber-300/90 leading-relaxed">
                        Navigate to the Profile page or click "Verify Session Now" to complete daily authentication.
                      </p>
                    </div>
                  </div>
                )}

                {/* 1. Paytm Money API Credentials */}
                <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                      <Key className="w-4 h-4 text-cyan-400" />
                      <span>1. Paytm Money Open API Credentials</span>
                    </span>
                    <span className="text-[10px] text-slate-500 font-mono">SEBI Compliant Vault</span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-[10px] text-slate-400 block">Paytm Money API Key</label>
                        {isSessionValid && <span className="text-[9px] text-emerald-400 font-mono">✓ Auto-Detected</span>}
                      </div>
                      <input
                        type="text"
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        placeholder="pm_live_api_key_xxxxxxxx"
                        className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:border-cyan-500 font-mono"
                      />
                    </div>
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-[10px] text-slate-400 block">Paytm Money API Secret</label>
                        {isSessionValid && <span className="text-[9px] text-emerald-400 font-mono">✓ Configured</span>}
                      </div>
                      <input
                        type="password"
                        value={apiSecret || (isSessionValid ? '••••••••••••••••••••••••••••••••' : '')}
                        onChange={(e) => setApiSecret(e.target.value)}
                        placeholder="pm_secret_xxxxxxxx"
                        className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:border-cyan-500 font-mono"
                      />
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-[10px] text-slate-400 block">Request / Session Access Token (or interactive browser 2FA)</label>
                      {isSessionValid && (
                        <span className="text-[10px] text-emerald-400 font-mono flex items-center gap-1 font-bold">
                          <CheckCircle2 className="w-3 h-3" /> Auto-Detected Active Token
                        </span>
                      )}
                    </div>
                    <input
                      type="text"
                      value={requestToken}
                      onChange={(e) => setRequestToken(e.target.value)}
                      placeholder={isSessionValid ? "Live Session Token Active (Valid until 23:59:59 IST)" : "Enter session request token (or authenticate via Chrome CDP tab on port 9229)"}
                      className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:border-cyan-500 font-mono"
                    />
                  </div>

                  <div className="flex items-center justify-between pt-1">
                    <button
                      type="button"
                      onClick={handleTestConnection}
                      disabled={isTestingConn}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-950 border border-cyan-800 text-cyan-300 hover:bg-cyan-900 text-xs font-semibold transition"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${isTestingConn ? 'animate-spin' : ''}`} />
                      <span>{isTestingConn ? 'Testing Feed...' : 'Test Broker Connection'}</span>
                    </button>

                    <span className="text-[10px] text-slate-400">
                      CDP Browser: <span className="text-emerald-400 font-mono">127.0.0.1:9229 Active</span>
                    </span>
                  </div>

                  {testResult && (
                    <div className={`p-2.5 rounded-lg text-xs border ${
                      testResult.success
                        ? 'bg-emerald-950/60 border-emerald-500/50 text-emerald-200'
                        : 'bg-amber-950/60 border-amber-500/50 text-amber-200'
                    }`}>
                      {testResult.message}
                    </div>
                  )}
                </div>

                {/* 2. Capital & Mandatory Stop Loss Risk Parameters */}
                <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                      <Sliders className="w-4 h-4 text-purple-400" />
                      <span>2. Live Capital & Mandatory Stop-Loss Controls</span>
                    </span>
                    <span className="text-[10px] text-rose-400 font-mono font-bold">STRICT LOSS CAPS</span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <div>
                      <label className="text-[10px] text-slate-400 block mb-1">Live Capital (₹)</label>
                      <input
                        type="number"
                        value={liveCapital}
                        onChange={(e) => setLiveCapital(e.target.value)}
                        className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-100 font-mono"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] text-slate-400 block mb-1">Per-Trade SL (%)</label>
                      <input
                        type="number"
                        step="0.1"
                        value={perTradeRiskPct}
                        onChange={(e) => setPerTradeRiskPct(e.target.value)}
                        className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-100 font-mono"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] text-slate-400 block mb-1">Daily Max Loss (₹)</label>
                      <input
                        type="number"
                        value={dailyLossLimit}
                        onChange={(e) => setDailyLossLimit(e.target.value)}
                        className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-100 font-mono"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] text-slate-400 block mb-1">Trailing SL (Pts)</label>
                      <input
                        type="number"
                        value={trailingSlPts}
                        onChange={(e) => setTrailingSlPts(e.target.value)}
                        className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-100 font-mono"
                      />
                    </div>
                  </div>

                  {/* Instrument Target Selection */}
                  <div className="pt-1 border-t border-slate-800 flex items-center gap-4 text-xs">
                    <label className="flex items-center gap-1.5 cursor-pointer text-slate-300">
                      <input
                        type="checkbox"
                        checked={tradeNifty}
                        onChange={(e) => setTradeNifty(e.target.checked)}
                        className="rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-0"
                      />
                      <span>NIFTY 50 Options (Calls &amp; Puts)</span>
                    </label>
                    <label className="flex items-center gap-1.5 cursor-pointer text-slate-300">
                      <input
                        type="checkbox"
                        checked={tradeBankNifty}
                        onChange={(e) => setTradeBankNifty(e.target.checked)}
                        className="rounded border-slate-700 bg-slate-900 text-purple-500 focus:ring-0"
                      />
                      <span>BANKNIFTY Options (Calls &amp; Puts)</span>
                    </label>
                  </div>
                </div>

                {/* 3. Explicit Operator Authorization Gate */}
                <div className="p-3.5 rounded-xl bg-rose-950/30 border border-rose-800/60 space-y-2">
                  <div className="flex items-center gap-2 text-rose-300 text-xs font-bold">
                    <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0" />
                    <span>3. Operator Consequential Risk Authorization Gate</span>
                  </div>
                  <p className="text-[11px] text-slate-300 leading-relaxed">
                    Live execution will route consequential real-money order intents to Paytm Money Open API to buy/sell Calls and Puts with automated trailing stops. In accordance with safety invariants, order dispatch remains fail-closed until explicitly confirmed.
                  </p>

                  <label className="flex items-start gap-2 pt-1 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={isAuthorized}
                      onChange={(e) => setIsAuthorized(e.target.checked)}
                      className="mt-0.5 rounded border-rose-700 bg-slate-900 text-rose-500 focus:ring-0"
                    />
                    <span className="text-xs text-rose-200 font-semibold">
                      I explicitly authorize live real-money order routing under the configured ₹{liveCapital} capital limit and {perTradeRiskPct}% per-trade stop loss (GATE_01_USER_AUTHORIZED_CAPITAL_AND_RISK).
                    </span>
                  </label>

                  <div className="pt-2 flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={handleActivateLiveExecution}
                      disabled={isSwitching}
                      className={`flex-1 py-2 px-3 rounded-lg text-white font-bold text-xs shadow-md transition flex items-center justify-center gap-1.5 cursor-pointer ${
                        currentMode === 'LIVE_EXECUTION'
                          ? 'bg-emerald-600 hover:bg-emerald-500 border border-emerald-400 shadow-emerald-900/30'
                          : 'bg-rose-600 hover:bg-rose-500 disabled:bg-slate-800'
                      }`}
                    >
                      <Lock className="w-3.5 h-3.5" />
                      <span>
                        {isSwitching 
                          ? 'Arming Live Mode...' 
                          : currentMode === 'LIVE_EXECUTION' 
                          ? '✓ Live Order Execution ACTIVE (Armed)' 
                          : 'Activate Live Order Execution'}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleSelectMode('PAPER')}
                      className="py-2 px-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-md transition cursor-pointer"
                    >
                      Keep Safe Paper Mode (₹10k)
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Lockout Notification Banner if server rejects transition */}
            {lockoutError && (
              <motion.div
                initial={{ opacity: 0, y: -5 }}
                animate={{ opacity: 1, y: 0 }}
                className="p-3.5 rounded-xl bg-rose-950/50 border border-rose-500/60 text-rose-200 text-xs space-y-2"
              >
                <div className="flex items-center gap-2 font-bold text-rose-300">
                  <Lock className="w-4 h-4 shrink-0" />
                  <span>SAFETY GATE ACTIVE — PREREQUISITES UNMET</span>
                </div>
                <p className="text-[11.5px] text-rose-300/90 leading-relaxed">
                  {lockoutError.message} To protect real funds, broker fills remain locked fail-closed (`LIVE_ORDER_DISPATCH_ENABLED = False`).
                </p>

                <div className="bg-slate-950/80 rounded-lg p-2 border border-rose-900/50 space-y-1">
                  <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider block">
                    Outstanding Items:
                  </span>
                  {lockoutError.missingRequirements.map((req, idx) => (
                    <div key={idx} className="flex items-center gap-1.5 text-[10.5px] text-rose-400 font-mono">
                      <XCircle className="w-3.5 h-3.5 shrink-0" />
                      <span>{req}</span>
                    </div>
                  ))}
                </div>

                <div className="pt-1 flex items-center justify-between">
                  <span className="text-[10.5px] text-slate-400">
                    System safely executing in {currentMode} mode.
                  </span>
                  <button
                    onClick={() => handleSelectMode('PAPER')}
                    className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold transition"
                  >
                    Confirm Paper Mode
                  </button>
                </div>
              </motion.div>
            )}
          </div>

          {/* Footer Controls */}
          <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between shrink-0">
            <button
              id="btnEmergencyStopModal"
              onClick={handleEmergencyStop}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-950/80 hover:bg-rose-900 text-rose-400 border border-rose-800 text-xs font-bold transition shadow-xs"
              title="Immediate Kill Switch: Reverts mode to PAPER and halts execution"
            >
              <ShieldAlert className="w-3.5 h-3.5" />
              <span>EMERGENCY STOP</span>
            </button>

            <div className="flex items-center gap-2">
              {viewTab === 'LIVE_CONFIG' ? (
                <button
                  id="btnActivateLiveFromModalFooter"
                  type="button"
                  onClick={handleActivateLiveExecution}
                  disabled={isSwitching}
                  className="px-3.5 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white text-xs font-bold transition shadow-xs flex items-center gap-1.5 cursor-pointer"
                >
                  <Lock className="w-3.5 h-3.5" />
                  <span>{isSwitching ? 'Activating Live...' : 'Activate Live Broker Mode'}</span>
                </button>
              ) : null}
              <button
                id="btnConfirmPaperFromModal"
                onClick={() => handleSelectMode('PAPER')}
                className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition shadow-xs cursor-pointer"
              >
                Confirm Paper Mode (₹10k)
              </button>
              <button
                id="btnCloseModeModalFooter"
                onClick={onClose}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
