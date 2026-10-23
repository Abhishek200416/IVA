import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Activity,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Shield,
  ShieldAlert,
  Clock,
  Wifi,
  WifiOff,
  X,
  ExternalLink,
  Lock
} from 'lucide-react';
import { api } from '../services/api';

export default function LiveDataValidationPanel({
  isOpen,
  onClose,
  onSwitchToPaper
}) {
  const [diagnostics, setDiagnostics] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState(null);

  const fetchDiagnostics = async () => {
    setIsLoading(true);
    try {
      const data = await api.getLiveDataValidation();
      setDiagnostics(data);
      setLastRefreshed(new Date().toLocaleTimeString());
    } catch (err) {
      console.warn('Could not fetch live data validation diagnostics:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchDiagnostics();
      const interval = setInterval(fetchDiagnostics, 3000);
      return () => clearInterval(interval);
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

  const isConnected = diagnostics?.feed_connection_status === 'CONNECTED';
  const isHealthy = diagnostics?.is_healthy ?? false;
  const healthScore = Math.round(diagnostics?.feed_health_score_pct ?? 0);
  const isStale = diagnostics?.is_stale ?? false;
  const rejectionReasons = diagnostics?.rejection_reasons || [];

  return (
    <AnimatePresence>
      <div
        id="liveDataValidationBackdrop"
        className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-slate-950/85 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ duration: 0.15, ease: 'easeOut' }}
          className="w-full max-w-2xl bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl p-4 sm:p-6 text-slate-100 max-h-[90vh] flex flex-col overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between pb-3 border-b border-slate-800 shrink-0">
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
                <Activity className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-sm font-bold tracking-wide uppercase flex items-center gap-2">
                  <span>Live Market Data Feed Qualification</span>
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded font-mono border ${
                      isConnected
                        ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                        : 'bg-amber-950 text-amber-300 border-amber-800'
                    }`}
                  >
                    {isConnected ? 'FEED CONNECTED' : 'AWAITING AUTH / STANDBY'}
                  </span>
                </h2>
                <div className="text-[11px] text-slate-400">
                  Read-Only Diagnostic Inspector • Verified under SEBI latency & sanity standards
                </div>
              </div>
            </div>
            <button
              id="btnCloseLiveDataValidationModal"
              onClick={onClose}
              className="p-1 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition"
              aria-label="Close"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Metric Summary Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mt-4 shrink-0">
            {/* Feed Status */}
            <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl flex flex-col">
              <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider">Feed Gateway</span>
              <div className="flex items-center gap-1.5 mt-1">
                {isConnected ? (
                  <Wifi className="w-4 h-4 text-emerald-400" />
                ) : (
                  <WifiOff className="w-4 h-4 text-amber-400" />
                )}
                <span className="text-xs font-bold text-slate-200 truncate">
                  {diagnostics?.feed_connection_status || 'STANDBY'}
                </span>
              </div>
            </div>

            {/* Health Score */}
            <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl flex flex-col">
              <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider">Health Score</span>
              <div className="flex items-center gap-1.5 mt-1">
                <span
                  className={`text-base font-extrabold font-mono ${
                    healthScore >= 80 ? 'text-emerald-400' : healthScore >= 50 ? 'text-amber-400' : 'text-rose-400'
                  }`}
                >
                  {healthScore}%
                </span>
                <span className="text-[10px] text-slate-500 font-mono">
                  {isHealthy ? 'PASSED' : 'CHECK'}
                </span>
              </div>
            </div>

            {/* Latency / Quote Age */}
            <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl flex flex-col">
              <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider">Quote Age</span>
              <div className="flex items-center gap-1.5 mt-1">
                <Clock className="w-4 h-4 text-slate-400" />
                <span
                  className={`text-xs font-bold font-mono ${
                    isStale ? 'text-amber-400' : 'text-slate-200'
                  }`}
                >
                  {diagnostics?.data_age_seconds !== undefined
                    ? `${diagnostics.data_age_seconds.toFixed(1)}s`
                    : '—'}
                </span>
                {isStale && (
                  <span className="text-[9px] px-1 bg-amber-950 text-amber-300 rounded font-mono">STALE</span>
                )}
              </div>
            </div>

            {/* Integrity Sanity */}
            <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl flex flex-col">
              <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider">Spread & Vol Sanity</span>
              <div className="flex items-center gap-1.5 mt-1">
                {diagnostics?.integrity_checks_passed ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                ) : (
                  <AlertTriangle className="w-4 h-4 text-amber-400" />
                )}
                <span className="text-xs font-bold text-slate-200">
                  {diagnostics?.integrity_checks_passed ? 'VERIFIED' : 'PENDING'}
                </span>
              </div>
            </div>
          </div>

          {/* Diagnostic Details & Feed Integrity Breakdown */}
          <div className="flex-1 overflow-y-auto mt-4 space-y-3 pr-1 text-xs">
            {/* Connection Information */}
            <div className="p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl space-y-2">
              <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider block">
                Provider Telemetry & Authentication Status
              </span>
              <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
                <div>
                  <span className="text-slate-400">Provider: </span>
                  <span className="text-slate-200 font-semibold">{diagnostics?.provider || 'Paytm Money Open API'}</span>
                </div>
                <div>
                  <span className="text-slate-400">Auth Status: </span>
                  <span className="text-cyan-300 font-semibold">{diagnostics?.auth_status || 'WAITING_FOR_OPERATOR_AUTH'}</span>
                </div>
                <div>
                  <span className="text-slate-400">Active Instruments: </span>
                  <span className="text-slate-200 font-semibold">
                    {diagnostics?.active_instruments ? diagnostics.active_instruments.join(', ') : 'NIFTY, BANKNIFTY'}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400">Market Hours: </span>
                  <span className={diagnostics?.is_market_hours ? 'text-emerald-400' : 'text-slate-400'}>
                    {diagnostics?.is_market_hours ? 'ACTIVE (09:15-15:30 IST)' : 'CLOSED (OFF-MARKET)'}
                  </span>
                </div>
              </div>
            </div>

            {/* Rejection / Blocking Reasons List */}
            {rejectionReasons.length > 0 && (
              <div className="p-3.5 bg-amber-950/30 border border-amber-500/40 rounded-xl space-y-1.5">
                <div className="flex items-center gap-2 font-bold text-amber-300 text-xs">
                  <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                  <span>Feed Diagnostics Advisory ({rejectionReasons.length} active notices)</span>
                </div>
                <div className="space-y-1 pt-1">
                  {rejectionReasons.map((reason, idx) => (
                    <div key={idx} className="flex items-start gap-2 text-[11px] text-amber-200/90 font-mono">
                      <span className="text-amber-400 mt-0.5">•</span>
                      <span>{reason}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Zero-Reload & Single-Tab Safety Notice */}
            <div className="p-3.5 bg-slate-950/80 border border-cyan-900/40 rounded-xl space-y-1 text-[11px] text-slate-300">
              <div className="flex items-center gap-2 font-bold text-cyan-300">
                <Shield className="w-4 h-4 text-cyan-400 shrink-0" />
                <span>Zero-Reload Single-Tab Architecture Active</span>
              </div>
              <p className="text-slate-400 leading-relaxed text-[11px]">
                The background browser daemon operates strictly in passive DOM read mode. Automated page reloads, rapid retries, and cycle parameter appending are permanently eliminated. Operator 2FA OTP/PIN entry remains undisturbed in the active browser tab.
              </p>
            </div>
          </div>

          {/* Footer Controls */}
          <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <button
                id="btnRefreshDiagnostics"
                onClick={fetchDiagnostics}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold transition disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
                <span>Refresh Diagnostics</span>
              </button>
              {lastRefreshed && (
                <span className="text-[10px] font-mono text-slate-500 hidden sm:inline">
                  Updated: {lastRefreshed}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                id="btnReturnToPaperFromValidation"
                onClick={async () => {
                  try {
                    await api.setOperatingMode('PAPER', 'Operator returned to paper mode from live validation');
                    if (onSwitchToPaper) onSwitchToPaper();
                    onClose();
                  } catch (e) {
                    console.error(e);
                  }
                }}
                className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition shadow-xs"
              >
                Return to Safe Paper Mode
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
