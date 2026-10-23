import React, { useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  ShieldAlert,
  Lock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  X,
  ExternalLink,
  Shield,
  FileCheck,
  UserCheck
} from 'lucide-react';
import { READINESS_GATES, READINESS_AUDIT_TIMESTAMP } from '../services/readinessData';

export default function LiveReadinessModal({ isOpen, onClose, onNavigateToReadiness }) {
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

  const passedCount = READINESS_GATES.filter((g) => g.status === 'PASSED').length;
  const blockedCount = READINESS_GATES.filter((g) => g.status === 'BLOCKED').length;
  const pendingCount = READINESS_GATES.filter((g) => g.status === 'PENDING').length;

  return (
    <AnimatePresence>
      <div
        id="liveReadinessBackdrop"
        className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-slate-950/80 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ duration: 0.15, ease: 'easeOut' }}
          className="w-full max-w-3xl bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl p-4 sm:p-6 text-slate-100 max-h-[85vh] flex flex-col overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between pb-3 border-b border-slate-800 shrink-0">
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400">
                <Lock className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-sm font-bold tracking-wide uppercase flex items-center gap-2">
                  <span>Live Trading Readiness & Safety Audit</span>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-rose-950 text-rose-400 border border-rose-800 font-mono">
                    LOCKED • FAIL-CLOSED
                  </span>
                </h2>
                <div className="text-[11px] text-slate-400">
                  Strict 10-Gate Protocol • Live orders permanently disabled at HTTP 403 Forbidden
                </div>
              </div>
            </div>
            <button
              id="btnCloseLiveReadinessModal"
              onClick={onClose}
              className="p-1 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition"
              aria-label="Close"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Audit Metrics Banner */}
          <div className="grid grid-cols-3 gap-2 mt-3 shrink-0 text-center text-xs font-mono">
            <div className="p-2 bg-emerald-950/30 border border-emerald-500/30 rounded-lg">
              <span className="text-emerald-400 font-bold text-sm block">{passedCount} / 10</span>
              <span className="text-slate-400 text-[10px]">Verified Gates</span>
            </div>
            <div className="p-2 bg-rose-950/30 border border-rose-500/30 rounded-lg">
              <span className="text-rose-400 font-bold text-sm block">{blockedCount} / 10</span>
              <span className="text-slate-400 text-[10px]">Hard Blockers</span>
            </div>
            <div className="p-2 bg-amber-950/30 border border-amber-500/30 rounded-lg">
              <span className="text-amber-400 font-bold text-sm block">{pendingCount} / 10</span>
              <span className="text-slate-400 text-[10px]">Pending Check</span>
            </div>
          </div>

          {/* Gates List (Scrollable) */}
          <div className="flex-1 overflow-y-auto mt-3 space-y-2 pr-1">
            {READINESS_GATES.map((gate) => (
              <div
                key={gate.id}
                className="p-3 bg-slate-950/80 border border-slate-800/80 rounded-lg flex flex-col gap-1.5 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="shrink-0">
                      {gate.status === 'PASSED' && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                      {gate.status === 'BLOCKED' && <XCircle className="w-4 h-4 text-rose-400" />}
                      {gate.status === 'PENDING' && <AlertTriangle className="w-4 h-4 text-amber-400" />}
                    </span>
                    <span className="font-bold text-slate-200">
                      {gate.id}. {gate.title}
                    </span>
                  </div>
                  <span
                    className={`text-[9px] font-mono font-bold uppercase px-1.5 py-0.2 rounded ${
                      gate.status === 'PASSED'
                        ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                        : gate.status === 'BLOCKED'
                        ? 'bg-rose-950 text-rose-400 border border-rose-800'
                        : 'bg-amber-950 text-amber-400 border border-amber-800'
                    }`}
                  >
                    {gate.status}
                  </span>
                </div>

                <p className="text-slate-400 text-[11px] leading-relaxed pl-6">{gate.detail}</p>

                <div className="pl-6 grid grid-cols-1 sm:grid-cols-2 gap-2 text-[10px] font-mono mt-1 pt-1 border-t border-slate-800/50">
                  <div className="text-slate-400">
                    <span className="text-cyan-400 font-bold">Evidence: </span>
                    {gate.evidence}
                  </div>
                  <div>
                    <span className={`font-bold ${gate.status === 'BLOCKED' ? 'text-rose-400' : 'text-amber-400'}`}>
                      Action Needed:{' '}
                    </span>
                    <span className="text-slate-300">{gate.ownerAction}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Action Footer */}
          <div className="mt-3 pt-3 border-t border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-2 shrink-0">
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-rose-400 flex items-center gap-1">
                <ShieldAlert className="w-3.5 h-3.5 shrink-0" />
                <span>Protected paper mode locked. Order writing returns HTTP 403.</span>
              </span>
            </div>

            <div className="flex items-center gap-2 self-end sm:self-auto">
              {onNavigateToReadiness && (
                <button
                  id="btnOpenDedicatedReadinessPage"
                  onClick={() => {
                    onClose();
                    onNavigateToReadiness();
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-cyan-950 hover:bg-cyan-900 text-cyan-300 rounded-lg border border-cyan-800/80 transition"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  <span>Full Audit Page</span>
                </button>
              )}
              <button
                id="btnCloseReadinessFooter"
                onClick={onClose}
                className="px-4 py-1.5 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg border border-slate-700 transition"
              >
                Close Audit
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
