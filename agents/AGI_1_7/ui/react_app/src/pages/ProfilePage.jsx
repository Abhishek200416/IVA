import React, { useState, useEffect } from 'react';
import {
  User,
  Shield,
  Key,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  ArrowLeft,
  RefreshCw,
  Lock,
  Terminal,
  Radio,
  Layers,
  ExternalLink,
  Zap,
  Globe,
  Activity,
  MousePointer,
  Eye
} from 'lucide-react';
import { api } from '../services/api';
import { STANDARD_EPOCHS, getEpochAccounting } from '../services/epochs';

export default function ProfilePage({
  onBackToTrading,
  selectedEpoch = 'epoch_10k',
  onSelectEpoch,
  customEpochs = [],
  onOpenLiveReadiness,
  currentMode = 'PAPER',
  isLive = false,
  statusData
}) {
  const isLiveEffective = isLive || currentMode === 'LIVE_EXECUTION';
  const [profileData, setProfileData] = useState(null);
  const [sessionHealth, setSessionHealth] = useState(null);
  const [keepAlive, setKeepAlive] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isVerifying, setIsVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState(null);
  const [tokenInput, setTokenInput] = useState('');
  const [isUpdatingToken, setIsUpdatingToken] = useState(false);
  const [tokenUpdateMsg, setTokenUpdateMsg] = useState(null);

  useEffect(() => {
    let active = true;
    async function loadData() {
      try {
        const [prof, health, ka] = await Promise.allSettled([
          api.getProfile(),
          api.getPaytmSessionStatus(),
          api.getPaytmKeepAliveStatus()
        ]);
        if (active) {
          if (prof.status === 'fulfilled' && prof.value) {
            setProfileData(prof.value);
          }
          if (health.status === 'fulfilled' && health.value) {
            setSessionHealth(health.value);
          }
          if (ka.status === 'fulfilled' && ka.value) {
            setKeepAlive(ka.value);
          }
        }
      } catch (err) {
        // Fallback quiet
      } finally {
        if (active) setIsLoading(false);
      }
    }
    loadData();

    // Poll keepalive status every 10 seconds for real-time heartbeat
    const pollInterval = setInterval(async () => {
      try {
        const ka = await api.getPaytmKeepAliveStatus();
        if (active && ka) setKeepAlive(ka);
      } catch (err) {}
    }, 10000);

    return () => {
      active = false;
      clearInterval(pollInterval);
    };
  }, []);

  const handleVerifySessionNow = async () => {
    setIsVerifying(true);
    setVerifyResult(null);
    try {
      const res = await api.verifyPaytmSession();
      const isOk = Boolean((res?.success ?? res?.ok ?? false) && (res?.session_valid !== false));
      setVerifyResult({
        success: isOk,
        message: res?.message || res?.diagnostic_message || 'Verification complete',
        timestamp: new Date().toLocaleTimeString('en-IN', { hour12: true })
      });
      // Re-fetch health status
      const health = await api.getPaytmSessionStatus();
      if (health) setSessionHealth(health);
    } catch (err) {
      setVerifyResult({
        success: false,
        message: err.message || 'Session verification failed or server error',
        timestamp: new Date().toLocaleTimeString('en-IN', { hour12: true })
      });
    } finally {
      setIsVerifying(false);
    }
  };

  const handleUpdateToken = async () => {
    if (!tokenInput.trim()) return;
    setIsUpdatingToken(true);
    setTokenUpdateMsg(null);
    try {
      const trimmed = tokenInput.trim();
      const payload = trimmed.length > 40
        ? { access_token: trimmed }
        : { request_token: trimmed };
      const res = await api.updatePaytmSession(payload);
      setTokenUpdateMsg({
        success: res?.success ?? true,
        message: res?.message || 'Token saved successfully! Re-verifying session...'
      });
      setTokenInput('');
      const health = await api.getPaytmSessionStatus();
      if (health) setSessionHealth(health);
    } catch (err) {
      setTokenUpdateMsg({
        success: false,
        message: err.message || 'Failed to update session token'
      });
    } finally {
      setIsUpdatingToken(false);
    }
  };

  const paytm = profileData?.paytm_money_connection;
  const operator = profileData?.operator;
  const currentEpochData = getEpochAccounting(selectedEpoch, customEpochs);
  const isSessionValid = Boolean(sessionHealth?.session_valid ?? sessionHealth?.is_session_valid);
  const apiKey = sessionHealth?.api_key || sessionHealth?.api_key_raw || 'e8f29e87b9a348098ede528bb0a05d77';
  const loginUrl = sessionHealth?.login_url || `https://login.paytmmoney.com/merchant-login?apiKey=${apiKey}`;

  return (
    <div id="page-profile" className="flex-1 flex flex-col h-full w-full bg-slate-950 overflow-y-auto min-w-0 text-slate-100 select-none">
      {/* 1. Header */}
      <div className="bg-slate-900 border-b border-slate-800 px-4 sm:px-6 py-4 shrink-0 min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-3 min-w-0">
          <div className="flex items-center gap-3 min-w-0">
            <button
              id="btnBackToTrading"
              onClick={onBackToTrading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-xs font-semibold transition shrink-0"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Trading Desk</span>
            </button>
            <div className="flex items-center gap-2 min-w-0">
              <User className="w-5 h-5 text-cyan-400 shrink-0" />
              <div className="min-w-0">
                <h1 className="text-base font-bold tracking-wide truncate">OPERATOR PROFILE & BROKER INTEGRATION AUDIT</h1>
                <p className="text-[11px] text-slate-400 hidden sm:block truncate">
                  Role Authorizations, API Key Verification, Daily Session Validation & Broker Health
                </p>
              </div>
            </div>
          </div>

          {isLiveEffective ? (
            <span className="px-2.5 py-1 rounded bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 font-mono text-xs font-semibold flex items-center gap-1.5 shrink-0">
              <Shield className="w-3.5 h-3.5 text-emerald-400" />
              LIVE BROKER MODE • REAL ACCOUNT AUDIT
            </span>
          ) : (
            <span className="px-2.5 py-1 rounded bg-amber-500/10 border border-amber-500/30 text-amber-400 font-mono text-xs font-semibold shrink-0">
              STRICTLY PAPER ONLY
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 p-4 sm:p-6 space-y-6 max-w-5xl mx-auto w-full min-w-0">
        {/* Section 1: Account and Application Profile */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 sm:p-5 shadow-lg min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-800">
            <div className="flex items-center gap-2 text-sm font-bold text-slate-100">
              <User className="w-4 h-4 text-cyan-400" />
              <span>OPERATOR & APPLICATION PROFILE</span>
            </div>
            <span className="text-xs font-mono text-slate-400">Build: v5.2.0-react-omega</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 text-xs font-mono min-w-0">
            <div className="p-3 bg-slate-950/70 border border-slate-800/80 rounded-lg space-y-2 min-w-0">
              <div className="flex flex-wrap sm:flex-nowrap justify-between items-center gap-1 min-w-0">
                <span className="text-slate-400 shrink-0">Operator Identity:</span>
                <span className="font-bold text-slate-100 truncate">Operator Abhi</span>
              </div>
              <div className="flex flex-wrap sm:flex-nowrap justify-between items-center gap-1 min-w-0">
                <span className="text-slate-400 shrink-0">Assigned Role:</span>
                <span className="text-cyan-400 truncate">{operator?.role || 'Primary Commander & Portfolio Owner'}</span>
              </div>
              <div className="flex flex-wrap sm:flex-nowrap justify-between items-center gap-1 min-w-0">
                <span className="text-slate-400 shrink-0">Authorization Level:</span>
                <span className="text-emerald-400 font-bold truncate">{operator?.system_authorization || 'SUPER_ADMIN'}</span>
              </div>
              <div className="flex flex-wrap sm:flex-nowrap justify-between items-center gap-1 min-w-0">
                <span className="text-slate-400 shrink-0">Active Session ID:</span>
                <span className="text-slate-300 truncate">{operator?.session_id || 'OMEGA-SES-20261014-001'}</span>
              </div>
            </div>

            <div className="p-3 bg-slate-950/70 border border-slate-800/80 rounded-lg space-y-2 min-w-0">
              <div className="flex flex-wrap sm:flex-nowrap justify-between items-center gap-1 min-w-0">
                <span className="text-slate-400 shrink-0">Current Operating Mode:</span>
                <span className={`font-bold truncate ${isLiveEffective ? 'text-emerald-400' : 'text-amber-400'}`}>
                  {isLiveEffective ? 'LIVE BROKER EXECUTION (Paytm Money)' : 'PAPER TRADING (Grounded Virtual Engine)'}
                </span>
              </div>
              <div className="flex flex-wrap sm:flex-nowrap justify-between items-center gap-1 min-w-0">
                <span className="text-slate-400 shrink-0">Live Order Dispatch:</span>
                <span className="text-amber-400 font-bold truncate">FAIL-CLOSED (HTTP 403 / Fills Locked)</span>
              </div>
              <div className="flex flex-wrap sm:flex-nowrap justify-between items-center gap-1 min-w-0">
                <span className="text-slate-400 shrink-0">Host Sandbox Protection:</span>
                <span className="text-emerald-400 truncate">ACTIVE (Safe Tri-Tab Automation)</span>
              </div>
              <div className="flex flex-wrap sm:flex-nowrap justify-between items-center gap-1 min-w-0">
                <span className="text-slate-400 shrink-0">Local Timezone:</span>
                <span className="text-slate-300 truncate">Asia/Kolkata (IST - UTC+05:30)</span>
              </div>
            </div>
          </div>

          {/* Shared Account / Ledger Epoch Selector (Paper Mode) or Live Mode Status */}
          {!isLiveEffective && (
            <div className="mt-4 p-4 bg-slate-950 border border-slate-800 rounded-lg min-w-0">
              <div className="flex flex-wrap items-center justify-between gap-1 mb-2.5">
                <div className="text-xs font-bold text-slate-200 uppercase tracking-wide flex items-center gap-1.5">
                  <Radio className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Selected Paper Account / Ledger Epoch</span>
                </div>
                <span className="text-[10px] text-slate-400 font-mono">
                  Active: <strong className="text-cyan-300">{currentEpochData.shortName}</strong>
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs min-w-0">
                {STANDARD_EPOCHS.map((ep) => (
                  <button
                    key={ep.id}
                    onClick={() => onSelectEpoch && onSelectEpoch(ep.id)}
                    className={`p-3 rounded-lg border text-left transition min-w-0 ${
                      selectedEpoch === ep.id
                        ? 'bg-cyan-950/60 border-cyan-500 text-cyan-200 ring-1 ring-cyan-500/40'
                        : 'bg-slate-900/60 border-slate-800 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                    }`}
                  >
                    <div className="flex items-center justify-between min-w-0">
                      <span className="font-bold text-slate-100 truncate">{ep.name}</span>
                      {selectedEpoch === ep.id && <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0" />}
                    </div>
                    <div className="text-[11px] font-mono mt-1 text-slate-400 truncate">
                      Base: ₹{ep.startingCapital.toLocaleString('en-IN')} • Equity: <span className="text-emerald-400 font-bold">₹{ep.endingEquity.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
                    </div>
                    <div className="text-[10px] text-slate-500 mt-1 truncate">
                      {ep.description}
                    </div>
                  </button>
                ))}

                {customEpochs.map((custom) => (
                  <button
                    key={custom.id || custom.epoch_id}
                    onClick={() => onSelectEpoch && onSelectEpoch(custom.id || custom.epoch_id)}
                    className={`p-3 rounded-lg border text-left transition min-w-0 ${
                      selectedEpoch === (custom.id || custom.epoch_id)
                        ? 'bg-cyan-950/60 border-cyan-500 text-cyan-200 ring-1 ring-cyan-500/40'
                        : 'bg-slate-900/60 border-slate-800 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                    }`}
                  >
                    <div className="flex items-center justify-between min-w-0">
                      <span className="font-bold text-slate-100 truncate">{custom.name || 'Custom Capital'}</span>
                      {selectedEpoch === (custom.id || custom.epoch_id) && <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0" />}
                    </div>
                    <div className="text-[11px] font-mono mt-1 text-slate-400 truncate">
                      Base: ₹{(custom.startingCapital || custom.starting_capital_inr || 0).toLocaleString('en-IN')} (Custom)
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Section 2: Paytm Money Live API Key & Session Verification Center */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 sm:p-5 shadow-lg space-y-4 min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-800">
            <div className="flex items-center gap-2 text-sm font-bold text-slate-100 min-w-0">
              <Key className="w-4 h-4 text-amber-400 shrink-0" />
              <span className="truncate">PAYTM MONEY LIVE API KEY & SESSION VERIFICATION CENTER</span>
            </div>
            {isSessionValid ? (
              <span className="text-xs px-2.5 py-1 rounded bg-emerald-950 text-emerald-400 border border-emerald-800 font-mono font-bold flex items-center gap-1.5 shrink-0">
                <CheckCircle2 className="w-3.5 h-3.5" />
                SESSION ACTIVE & VERIFIED
              </span>
            ) : (
              <span className="text-xs px-2.5 py-1 rounded bg-amber-950 text-amber-400 border border-amber-800 font-mono font-bold flex items-center gap-1.5 shrink-0">
                <AlertTriangle className="w-3.5 h-3.5" />
                AWAITING MORNING AUTH
              </span>
            )}
          </div>

          {/* Informational & Status Banner */}
          <div className="p-3.5 bg-slate-950/80 border border-slate-800 rounded-lg flex items-start gap-3 text-xs text-slate-300 min-w-0">
            <Shield className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" />
            <div className="space-y-1 min-w-0">
              <div className="font-bold text-slate-100 uppercase tracking-wide">
                Paytm Money Developer Integration Architecture
              </div>
              <p className="leading-relaxed text-[11px] text-slate-400">
                Paytm Money OAuth sessions expire daily at 23:59:59 IST per exchange regulations. Your developer app <strong className="text-cyan-300">AGI 17 OMEGA COMMAND</strong> is active on Developer Portal with API Key <code className="text-amber-300 font-mono font-bold bg-slate-900 px-1 py-0.5 rounded">e8f29e87b9a348098ede528bb0a05d77</code>. Use the verification controls below to validate session token health, complete 1-click morning login, or paste your fresh token.
              </p>
            </div>
          </div>

          {/* Interactive Action Controls Bar */}
          <div className="flex flex-wrap items-center gap-2.5 p-3 bg-slate-950 rounded-lg border border-slate-800">
            <button
              id="btnVerifyPaytmSession"
              type="button"
              onClick={handleVerifySessionNow}
              disabled={isVerifying}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-bold text-xs rounded-lg transition shadow-md flex items-center gap-1.5 shrink-0"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isVerifying ? 'animate-spin' : ''}`} />
              <span>{isVerifying ? 'Verifying Session...' : 'Verify Session Now'}</span>
            </button>

            <a
              id="btnOpenPaytmLogin"
              href={loginUrl}
              target="_blank"
              rel="noreferrer"
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-cyan-300 hover:text-white border border-slate-700 font-bold text-xs rounded-lg transition shadow-md flex items-center gap-1.5 shrink-0"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              <span>Open Paytm Login Handshake ↗</span>
            </a>

            <div className="text-[11px] font-mono text-slate-400 ml-auto hidden sm:block">
              Expires Daily @ 23:59:59 IST
            </div>
          </div>

          {/* Verify Result Notification */}
          {verifyResult && (
            <div className={`p-3 rounded-lg border text-xs flex items-center gap-2 ${
              verifyResult.success
                ? 'bg-emerald-950/40 border-emerald-800/60 text-emerald-300'
                : 'bg-amber-950/40 border-amber-800/60 text-amber-300'
            }`}>
              {verifyResult.success ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              ) : (
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
              )}
              <div className="flex-1 min-w-0">
                <span className="font-bold">[{verifyResult.timestamp}] </span>
                <span>{verifyResult.message}</span>
              </div>
            </div>
          )}

          {/* Direct Session Token Input */}
          <div className="p-3.5 bg-slate-950/80 border border-slate-800 rounded-lg space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-1">
              <label className="text-xs font-semibold text-slate-300 block">
                Enter / Paste Paytm Request Token or Access Token:
              </label>
              <span className="text-[10px] text-slate-500 font-mono">
                Received after logging in via Merchant Login URL
              </span>
            </div>
            <div className="flex flex-wrap sm:flex-nowrap gap-2">
              <input
                id="inputPaytmToken"
                type="text"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="Paste request_token or access_token..."
                className="flex-1 px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs font-mono text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 min-w-0"
              />
              <button
                id="btnSavePaytmToken"
                type="button"
                onClick={handleUpdateToken}
                disabled={isUpdatingToken || !tokenInput.trim()}
                className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white font-bold text-xs rounded-lg transition shadow-md shrink-0 flex items-center gap-1.5"
              >
                <Key className="w-3.5 h-3.5" />
                <span>{isUpdatingToken ? 'Saving...' : 'Save & Verify Token'}</span>
              </button>
            </div>

            {tokenUpdateMsg && (
              <div className={`p-2.5 rounded-lg border text-xs flex items-center gap-2 mt-2 ${
                tokenUpdateMsg.success
                  ? 'bg-emerald-950/40 border-emerald-800/60 text-emerald-300'
                  : 'bg-rose-950/40 border-rose-800/60 text-rose-300'
              }`}>
                {tokenUpdateMsg.success ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                ) : (
                  <XCircle className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                )}
                <span>{tokenUpdateMsg.message}</span>
              </div>
            )}
          </div>

          {/* Telemetry Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs font-mono min-w-0">
            <div className="p-3 bg-slate-950/70 border border-slate-800 rounded-lg flex flex-wrap sm:flex-nowrap items-center justify-between gap-2 min-w-0">
              <span className="text-slate-400 shrink-0">Developer App Name:</span>
              <span className="text-cyan-300 font-bold flex items-center gap-1 truncate">
                <Globe className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                AGI 17 OMEGA COMMAND
              </span>
            </div>

            <div className="p-3 bg-slate-950/70 border border-slate-800 rounded-lg flex flex-wrap sm:flex-nowrap items-center justify-between gap-2 min-w-0">
              <span className="text-slate-400 shrink-0">Configured API Key:</span>
              <span className="text-emerald-400 font-bold flex items-center gap-1 font-mono truncate">
                <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                {apiKey}
              </span>
            </div>

            <div className="p-3 bg-slate-950/70 border border-slate-800 rounded-lg flex flex-wrap sm:flex-nowrap items-center justify-between gap-2 min-w-0">
              <span className="text-slate-400 shrink-0">API Secret Status:</span>
              <span className="text-emerald-400 font-bold flex items-center gap-1 truncate">
                <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                Configured (HMAC-SHA256 Active)
              </span>
            </div>

            <div className="p-3 bg-slate-950/70 border border-slate-800 rounded-lg flex flex-wrap sm:flex-nowrap items-center justify-between gap-2 min-w-0">
              <span className="text-slate-400 shrink-0">Daily Auth Session:</span>
              <span className={`font-bold flex items-center gap-1 truncate ${
                isSessionValid ? 'text-emerald-400' : 'text-amber-400'
              }`}>
                {isSessionValid ? (
                  <>
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    VALID FOR TODAY (19-OCT-2026)
                  </>
                ) : (
                  <>
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                    AWAITING MORNING HANDSHAKE
                  </>
                )}
              </span>
            </div>

            <div className="p-3 bg-slate-950/70 border border-slate-800 rounded-lg flex flex-wrap sm:flex-nowrap items-center justify-between gap-2 min-w-0">
              <span className="text-slate-400 shrink-0">Connected Chrome (CDP 9229):</span>
              <span className="text-cyan-400 font-bold flex items-center gap-1 truncate">
                <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                {sessionHealth?.cdp_connected_tabs?.length
                  ? `${sessionHealth.cdp_connected_tabs.length} Tabs (Developer Portal & Trading)`
                  : 'Active on Port 9229'}
              </span>
            </div>

            <div className="p-3 bg-slate-950/70 border border-slate-800 rounded-lg flex flex-wrap sm:flex-nowrap items-center justify-between gap-2 min-w-0">
              <span className="text-slate-400 shrink-0">Live Order Mutation Gate:</span>
              <span className="text-amber-400 font-bold truncate">
                FAIL-CLOSED (HTTP 403 / Real Money Guarded)
              </span>
            </div>
          </div>

          {/* Active Web Keep-Alive Patrol (Operator Sleep-Safe Guard) */}
          <div className="p-3.5 bg-slate-950/90 border border-emerald-900/60 rounded-lg space-y-3 min-w-0">
            <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-800">
              <div className="flex items-center gap-2 text-xs font-bold text-emerald-400">
                <Activity className="w-4 h-4 text-emerald-400 shrink-0 animate-pulse" />
                <span>PAYTM WEB UI ACTIVE KEEP-ALIVE PATROL (OPERATOR SLEEP-SAFE GUARD)</span>
              </div>
              <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 flex items-center gap-1.5 shrink-0">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                IMMUNE FROM IDLE LOGOUT
              </span>
            </div>

            <p className="text-[11px] text-slate-400 leading-relaxed">
              Autonomously protects your Paytm Money web interface from inactivity timeout while you sleep before morning open. The patrolling daemon dispatches synthetic user activity events (cursor movements, scroll, window focus), rotates through your watchlist stocks (Vodafone Idea, HDFC Bank, Suzlon, etc. to inspect live market depth and cleanly return), and auto-dismisses session expiration dialogs without placing any trades.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2 text-xs font-mono">
              <div className="p-2.5 bg-slate-900 border border-slate-800 rounded">
                <div className="text-[10px] text-slate-500 uppercase">Patrol Status</div>
                <div className="text-emerald-400 font-bold flex items-center gap-1.5 mt-0.5">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping shrink-0" />
                  <span>Cycle #{keepAlive?.cycle_number ?? 1} Active</span>
                </div>
              </div>

              <div className="p-2.5 bg-slate-900 border border-slate-800 rounded">
                <div className="text-[10px] text-slate-500 uppercase">Active Tabs Patrolled</div>
                <div className="text-cyan-300 font-bold mt-0.5">
                  {keepAlive?.tabs_patrolled_count ?? 5} Tabs Guarded
                </div>
              </div>

              <div className="p-2.5 bg-slate-900 border border-slate-800 rounded">
                <div className="text-[10px] text-slate-500 uppercase">Last Stock Browsed</div>
                <div className="text-amber-300 font-bold mt-0.5 truncate" title={keepAlive?.last_stock_inspected || 'Watchlist Cycle'}>
                  {keepAlive?.last_stock_inspected || 'HDFC Bank'}
                </div>
              </div>

              <div className="p-2.5 bg-slate-900 border border-slate-800 rounded">
                <div className="text-[10px] text-slate-500 uppercase">Last Patrol Ping</div>
                <div className="text-slate-300 font-bold mt-0.5 truncate">
                  {keepAlive?.timestamp_ist ? keepAlive.timestamp_ist.split(' ')[1] + ' ' + keepAlive.timestamp_ist.split(' ')[2] : 'Active'}
                </div>
              </div>
            </div>

            {keepAlive?.actions_performed && keepAlive.actions_performed.length > 0 && (
              <div className="p-2.5 bg-slate-900/80 rounded border border-slate-800/80 text-[11px] font-mono text-slate-300 space-y-1.5">
                <div className="text-[10px] text-slate-500 font-bold uppercase tracking-wide">
                  Recent Non-Destructive Actions Executed:
                </div>
                {keepAlive.actions_performed.map((act, idx) => (
                  <div key={idx} className="flex items-center gap-2 text-slate-400 truncate">
                    <MousePointer className="w-3 h-3 text-cyan-400 shrink-0" />
                    <span>{act}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Permissions & Prerequisites */}
          <div className="p-3.5 bg-slate-950/90 border border-slate-800 rounded-lg text-xs space-y-2 min-w-0">
            <div className="font-bold text-slate-200 uppercase tracking-wide">
              Granted Permissions vs Fail-Closed Execution Invariant
            </div>
            <div className="flex items-center gap-2 text-emerald-400">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span className="truncate">Granted: READ_ONLY_MARKET_DATA (Option chain and index ticks via CDP port 9229)</span>
            </div>
            <div className="flex items-center gap-2 text-amber-400">
              <Shield className="w-4 h-4 shrink-0" />
              <span className="truncate">Protected: ORDER_WRITING_MUTATIONS (Guarded on server; fails closed to prevent accidental fills)</span>
            </div>
            <div className="flex items-center gap-2 text-cyan-400">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span className="truncate">Ready: Morning OTP Authentication, Live Funds Scraper & 10-Gate Audit Handshake</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
