import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Wallet, X, ArrowUpRight, TrendingUp, ShieldCheck, ExternalLink, Layers, CheckCircle2 } from 'lucide-react';
import { getEpochAccounting, STANDARD_EPOCHS } from '../services/epochs';

export default function PortfolioSummaryPanel({
  isOpen,
  onClose,
  statusData,
  onNavigatePortfolio,
  selectedEpoch = 'epoch_10k',
  onSelectEpoch,
  customEpochs = []
}) {
  React.useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose();
    }
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  // Authoritative, reconciled accounting data for the selected epoch
  const epochData = getEpochAccounting(selectedEpoch, customEpochs);

  const startingCap = epochData.startingCapital;
  const realizedPnl = epochData.realizedPnl;
  const unrealizedPnl = epochData.unrealizedPnl;
  const endingEquity = epochData.endingEquity;
  const cashReserve = epochData.cashReserve;
  const activeCount = epochData.activePositionsCount;
  const tradeCount = epochData.closedTradesCount;
  const roiPct = epochData.roiPct;
  const taxes = epochData.statutoryTaxes;

  return (
    <AnimatePresence>
      <div
        id="portfolioModalBackdrop"
        className="fixed inset-0 z-50 flex items-start justify-center pt-16 px-4 bg-slate-950/60 backdrop-blur-xs"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, y: -10, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -10, scale: 0.98 }}
          transition={{ duration: 0.15, ease: 'easeOut' }}
          className="w-full max-w-md bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl p-5 text-slate-100 min-w-0"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <div className="flex items-center gap-2">
              <Wallet className="w-4 h-4 text-emerald-400" />
              <h2 className="text-sm font-bold text-slate-100 uppercase tracking-wide">
                Today's Portfolio Snapshot
              </h2>
            </div>
            <button
              onClick={onClose}
              className="p-1 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition"
              aria-label="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Epoch Switcher strictly separating 100k milestone, 10k sandbox, 50k demo & custom */}
          <div className="mt-3 bg-slate-950 p-1.5 rounded-lg border border-slate-800 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono text-slate-400 uppercase flex items-center gap-1">
                <Layers className="w-3 h-3 text-cyan-400" /> Accounting Epoch:
              </span>
              <span className="text-[9px] font-mono text-emerald-400 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> Paper Ledger Reconciled
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-1">
              {STANDARD_EPOCHS.map((epoch) => (
                <button
                  key={epoch.id}
                  id={`btnEpoch${epoch.id === 'epoch_100k' ? '100k' : epoch.id === 'epoch_10k' ? '10k' : '50k'}`}
                  onClick={() => onSelectEpoch && onSelectEpoch(epoch.id)}
                  className={`px-2.5 py-1 rounded text-[11px] font-semibold transition shrink-0 ${
                    selectedEpoch === epoch.id
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                  }`}
                >
                  {epoch.shortName}
                </button>
              ))}

              {customEpochs.map((custom) => (
                <button
                  key={custom.id || custom.epoch_id}
                  onClick={() => onSelectEpoch && onSelectEpoch(custom.id || custom.epoch_id)}
                  className={`px-2.5 py-1 rounded text-[11px] font-semibold transition shrink-0 ${
                    selectedEpoch === (custom.id || custom.epoch_id)
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                  }`}
                >
                  ₹{(custom.startingCapital || custom.starting_capital_inr || 0).toLocaleString('en-IN')} Custom
                </button>
              ))}
            </div>
          </div>

          {/* Primary Equity Card */}
          <div className="mt-3 p-4 bg-gradient-to-br from-slate-950 to-slate-900 border border-slate-800 rounded-xl">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-slate-400">Total Portfolio Equity</span>
              <span className="text-[10px] font-mono text-amber-400 bg-amber-950/40 px-1.5 py-0.5 rounded border border-amber-500/20">
                {epochData.tag}
              </span>
            </div>
            <div className="flex items-baseline justify-between mt-1">
              <span className="text-2xl font-bold font-mono text-slate-100 tabular-nums">
                ₹{endingEquity.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <span className="text-xs font-semibold text-emerald-400 bg-emerald-950/50 border border-emerald-500/30 px-2 py-0.5 rounded flex items-center gap-0.5">
                <ArrowUpRight className="w-3.5 h-3.5" /> {roiPct} ROI
              </span>
            </div>
            <div className="text-[11px] text-slate-400 mt-1 font-mono flex items-center justify-between">
              <span>Starting Base Capital:</span>
              <span className="text-slate-200 font-bold">
                ₹{startingCap.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </span>
            </div>
          </div>

          {/* Grid of Key Metrics */}
          <div className="grid grid-cols-2 gap-2.5 mt-3">
            <div className="p-3 bg-slate-950/70 border border-slate-800 rounded-lg">
              <div className="text-[11px] text-slate-400">Realized Net P&L</div>
              <div className="text-sm font-bold font-mono text-emerald-400 mt-0.5 tabular-nums">
                +₹{realizedPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5">
                Taxes: ₹{taxes.toFixed(2)}
              </div>
            </div>

            <div className="p-3 bg-slate-950/70 border border-slate-800 rounded-lg">
              <div className="text-[11px] text-slate-400">Unrealized P&L</div>
              <div className="text-sm font-bold font-mono text-emerald-400 mt-0.5 tabular-nums">
                +₹{unrealizedPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5">Current mark MTM</div>
            </div>

            <div className="p-3 bg-slate-950/70 border border-slate-800 rounded-lg">
              <div className="text-[11px] text-slate-400">Available Cash Reserve</div>
              <div className="text-sm font-bold font-mono text-cyan-400 mt-0.5 tabular-nums">
                ₹{cashReserve.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5">
                {epochData.reservePct} cash buffer
              </div>
            </div>

            <div className="p-3 bg-slate-950/70 border border-slate-800 rounded-lg">
              <div className="text-[11px] text-slate-400">Positions & Trades</div>
              <div className="text-sm font-bold font-mono text-slate-200 mt-0.5 tabular-nums">
                {activeCount} Active / {tradeCount} Closed
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5">
                {epochData.shortName}
              </div>
            </div>
          </div>

          {/* Accounting Identity */}
          <div className="mt-3 p-2.5 bg-slate-950/80 border border-slate-800/80 rounded-lg text-[11px] text-slate-400 flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-slate-300">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" /> Identity:
            </span>
            <span className="font-mono text-cyan-300 text-[10px] font-bold">
              ₹{startingCap.toLocaleString('en-IN')} + ₹{realizedPnl.toFixed(2)} + ₹{unrealizedPnl.toFixed(2)} = ₹{endingEquity.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </span>
          </div>

          {/* Footer Actions */}
          <div className="mt-4 flex items-center justify-between pt-3 border-t border-slate-800">
            <button
              onClick={() => {
                onClose();
                if (onNavigatePortfolio) onNavigatePortfolio();
              }}
              className="inline-flex items-center gap-1.5 text-xs text-cyan-400 hover:text-cyan-300 transition"
            >
              <span>Manage Custom Capital & Full Risk</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={onClose}
              className="px-4 py-1.5 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg border border-slate-700 transition"
            >
              Close
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
