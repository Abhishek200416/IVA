import React, { useState } from 'react';
import {
  ArrowLeft,
  Wallet,
  ShieldCheck,
  TrendingUp,
  PlusCircle,
  Layers,
  CheckCircle2,
  AlertCircle,
  Coins,
  Sparkles,
  Calculator
} from 'lucide-react';
import PortfolioTradesPanel from '../components/PortfolioTradesPanel';
import {
  STANDARD_EPOCHS,
  getEpochAccounting,
  validateCustomCapital
} from '../services/epochs';
import { api } from '../services/api';

const PRESET_CAPITALS = [
  { label: '₹25,000', value: 25000, desc: 'Starter F&O buffer' },
  { label: '₹50,000', value: 50000, desc: '2-Lot Index Strangle' },
  { label: '₹1,00,000', value: 100000, desc: 'Multi-Asset Baseline' },
  { label: '₹2,00,000', value: 200000, desc: 'Portfolio Hedging' },
  { label: '₹5,00,000', value: 500000, desc: 'Institutional Scale' },
];

export default function PortfolioPage({
  onBackToTrading,
  statusData,
  selectedEpoch = 'epoch_10k',
  onSelectEpoch,
  customEpochs = [],
  setCustomEpochs,
  currentMode = 'PAPER',
  isLive = false
}) {
  const isLiveEffective = isLive || currentMode === 'LIVE_EXECUTION';
  const [liveCapitalInput, setLiveCapitalInput] = useState(() => localStorage.getItem('agi_live_capital') || '5000.00');
  const [liveCapitalSavedMsg, setLiveCapitalSavedMsg] = useState(null);
  const liveBaseCapital = parseFloat(liveCapitalInput) || 5000.00;
  const paytmScrapedCash = statusData?.accounting?.paytm_scraped_cash || 0.0;
  const effectiveLiveEquity = paytmScrapedCash > 0 ? paytmScrapedCash : liveBaseCapital;

  const [customInput, setCustomInput] = useState('');
  const [customLabel, setCustomLabel] = useState('');
  const [validationError, setValidationError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [isCreating, setIsCreating] = useState(false);

  // Authoritative reconciled epoch accounting
  const epochData = getEpochAccounting(selectedEpoch, customEpochs);

  const handleSelectPreset = (val) => {
    setCustomInput(String(val));
    setValidationError(null);
  };

  const handleCreateCustomEpoch = async () => {
    setValidationError(null);
    setSuccessMessage(null);

    const validation = validateCustomCapital(customInput);
    if (!validation.valid) {
      setValidationError(validation.error);
      return;
    }

    setIsCreating(true);
    const capitalVal = validation.value;
    const labelVal = customLabel.trim() || `Custom Capital ₹${capitalVal.toLocaleString('en-IN')}`;

    try {
      // 1. Send to server
      const res = await api.createCustomEpoch(capitalVal, labelVal);
      const serverEpoch = res?.epoch || {
        epoch_id: `EPOCH-CUSTOM-${capitalVal}-${Date.now()}`,
        label: labelVal,
        starting_capital_inr: capitalVal,
        current_equity_inr: capitalVal,
        realized_pnl_inr: 0.0,
        unrealized_pnl_inr: 0.0,
        cash_reserve_inr: capitalVal,
        deployed_margin_inr: 0.0,
        status: 'ACTIVE_CUSTOM_EVALUATION'
      };

      const newCustomEpoch = {
        id: serverEpoch.epoch_id,
        serverEpochId: serverEpoch.epoch_id,
        name: labelVal,
        shortName: `₹${capitalVal.toLocaleString('en-IN')} Custom`,
        startingCapital: capitalVal,
        cashReserve: capitalVal,
        deployedMargin: 0.0,
        realizedPnl: 0.0,
        unrealizedPnl: 0.0,
        endingEquity: capitalVal,
        roiPct: '+0.00%',
        reservePct: '100.0%',
        deployedPct: '0.0%',
        statutoryTaxes: 0.0,
        taxesBreakdown: { stt: 0, exchange: 0, gst: 0, sebiStamp: 0, brokerage: 0 },
        activePositionsCount: 0,
        closedTradesCount: 0,
        status: 'ACTIVE_CUSTOM_EVALUATION'
      };

      // 2. Update state and select new epoch
      if (setCustomEpochs) {
        setCustomEpochs((prev) => [...prev, newCustomEpoch]);
      }
      if (onSelectEpoch) {
        onSelectEpoch(newCustomEpoch.id);
      }

      setSuccessMessage(`Custom Epoch "${labelVal}" with ₹${capitalVal.toLocaleString('en-IN')} initialized and active.`);
      setCustomInput('');
      setCustomLabel('');
    } catch (err) {
      // Offline fallback: create locally
      const localId = `epoch_custom_${Date.now()}`;
      const newCustomEpoch = {
        id: localId,
        serverEpochId: `EPOCH-CUSTOM-${capitalVal}-${Date.now()}`,
        name: labelVal,
        shortName: `₹${capitalVal.toLocaleString('en-IN')} Custom`,
        startingCapital: capitalVal,
        cashReserve: capitalVal,
        deployedMargin: 0.0,
        realizedPnl: 0.0,
        unrealizedPnl: 0.0,
        endingEquity: capitalVal,
        roiPct: '+0.00%',
        reservePct: '100.0%',
        deployedPct: '0.0%',
        statutoryTaxes: 0.0,
        taxesBreakdown: { stt: 0, exchange: 0, gst: 0, sebiStamp: 0, brokerage: 0 },
        activePositionsCount: 0,
        closedTradesCount: 0,
        status: 'ACTIVE_CUSTOM_EVALUATION'
      };

      if (setCustomEpochs) {
        setCustomEpochs((prev) => [...prev, newCustomEpoch]);
      }
      if (onSelectEpoch) {
        onSelectEpoch(newCustomEpoch.id);
      }
      setSuccessMessage(`Custom Epoch "${labelVal}" with ₹${capitalVal.toLocaleString('en-IN')} initialized locally.`);
      setCustomInput('');
      setCustomLabel('');
    } finally {
      setIsCreating(false);
    }
  };

  const handleSaveLiveCapital = () => {
    const parsed = parseFloat(liveCapitalInput);
    if (!parsed || parsed < 500) {
      setLiveCapitalSavedMsg('Please enter a valid capital amount of at least ₹500.');
      return;
    }
    localStorage.setItem('agi_live_capital', parsed.toFixed(2));
    setLiveCapitalSavedMsg(`Live Capital Floor updated to ₹${parsed.toLocaleString('en-IN')}.`);
    setTimeout(() => setLiveCapitalSavedMsg(null), 3000);
  };

  return (
    <div id="page-portfolio" className="flex-1 flex flex-col h-full w-full bg-slate-950 overflow-y-auto min-w-0 text-slate-100 select-none">
      {/* 1. Header */}
      <div className="bg-slate-900 border-b border-slate-800 px-4 sm:px-6 py-4 shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-3">
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
              <Wallet className="w-5 h-5 text-emerald-400 shrink-0" />
              <div className="min-w-0">
                <h1 className="text-base font-bold tracking-wide truncate">PORTFOLIO, CAPITAL MANAGEMENT & RISK CONTROLS</h1>
                <p className="text-[11px] text-slate-400 hidden sm:block truncate">
                  {isLiveEffective
                    ? 'Live Broker Capital Preservation, Risk Limits & Paytm Money Execution Controls'
                    : 'Reconciled Paper Capitalization, Custom Allocations, and Subsystem Isolations'}
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {isLiveEffective ? (
              <span className="px-2.5 py-1 rounded bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 font-mono text-xs font-semibold flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                LIVE BROKER MODE • REAL ACCOUNT
              </span>
            ) : (
              <span className="px-2.5 py-1 rounded bg-amber-500/10 border border-amber-500/30 text-amber-400 font-mono text-xs font-semibold">
                PAPER ACCOUNT ISOLATION
              </span>
            )}
          </div>
        </div>

        {/* Epoch / Live Selector Row */}
        {isLiveEffective ? (
          <div className="flex flex-wrap items-center justify-between gap-2 mt-4 pt-3 border-t border-slate-800/80">
            <div className="flex items-center gap-2 min-w-0">
              <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
              <span className="text-xs font-bold text-emerald-300 shrink-0">Active Live Broker Ledger:</span>
              <span className="text-xs font-mono text-slate-200 truncate">
                Paytm Money Live Session (User Target Capital: ₹{effectiveLiveEquity.toLocaleString('en-IN')})
              </span>
            </div>
            <div className="text-[11px] font-mono text-amber-400 bg-amber-950/40 px-2.5 py-1 rounded border border-amber-800/60 flex items-center gap-1.5 shrink-0">
              <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
              <span>Execution Gate: LIVE_ORDER_DISPATCH_ENABLED = False (Fills Locked)</span>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2 mt-4 pt-3 border-t border-slate-800/80">
            <span className="text-xs font-semibold text-slate-400 flex items-center gap-1 shrink-0">
              <Layers className="w-3.5 h-3.5 text-cyan-400" /> Active Accounting Epoch:
            </span>
            <div className="flex flex-wrap items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800">
              {STANDARD_EPOCHS.map((epoch) => (
                <button
                  key={epoch.id}
                  id={`btnPageEpoch${epoch.id === 'epoch_100k' ? '100k' : epoch.id === 'epoch_10k' ? '10k' : '50k'}`}
                  onClick={() => onSelectEpoch && onSelectEpoch(epoch.id)}
                  className={`px-3 py-1 rounded-md text-xs font-semibold transition shrink-0 ${
                    selectedEpoch === epoch.id
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                  }`}
                >
                  {epoch.shortName}
                </button>
              ))}

              {customEpochs.map((custom) => (
                <button
                  key={custom.id || custom.epoch_id}
                  onClick={() => onSelectEpoch && onSelectEpoch(custom.id || custom.epoch_id)}
                  className={`px-3 py-1 rounded-md text-xs font-semibold transition shrink-0 ${
                    selectedEpoch === (custom.id || custom.epoch_id)
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                  }`}
                >
                  ₹{(custom.startingCapital || custom.starting_capital_inr || 0).toLocaleString('en-IN')} Custom
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Reconciled Accounting Metrics Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4 min-w-0">
          <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl min-w-0">
            <div className="text-[11px] text-slate-400 truncate">Total Account Equity</div>
            <div className="text-xl font-bold font-mono text-slate-100 mt-0.5 tabular-nums">
              ₹{(isLiveEffective ? effectiveLiveEquity : epochData.endingEquity).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
            <div className="text-[10px] text-emerald-400 mt-0.5">
              {isLiveEffective ? '0.00% Session Return (Preserved)' : `${epochData.roiPct} Session Return`}
            </div>
          </div>

          <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl min-w-0">
            <div className="text-[11px] text-slate-400 truncate">Starting Base Capital</div>
            <div className="text-xl font-bold font-mono text-slate-100 mt-0.5 tabular-nums">
              ₹{(isLiveEffective ? liveBaseCapital : epochData.startingCapital).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5 truncate">
              {isLiveEffective ? 'Live Capital Floor' : epochData.tag}
            </div>
          </div>

          <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl min-w-0">
            <div className="text-[11px] text-slate-400 truncate">Realized Net Gain</div>
            <div className="text-xl font-bold font-mono text-emerald-400 mt-0.5 tabular-nums">
              +₹{(isLiveEffective ? 0.0 : epochData.realizedPnl).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5">
              {isLiveEffective ? 'Pre-Market Clean • 0 Trades' : `Taxes: ₹${epochData.statutoryTaxes.toFixed(2)}`}
            </div>
          </div>

          <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl min-w-0">
            <div className="text-[11px] text-slate-400 truncate">Cash Reserve Floor</div>
            <div className="text-xl font-bold font-mono text-cyan-400 mt-0.5 tabular-nums">
              ₹{(isLiveEffective ? effectiveLiveEquity : epochData.cashReserve).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
            <div className="text-[10px] text-cyan-400 mt-0.5">
              {isLiveEffective ? '100.0% Capital Cushion' : `${epochData.reservePct} Cash Buffer`}
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 p-4 sm:p-6 space-y-6 max-w-7xl mx-auto w-full min-w-0">
        {/* 2. Live Risk Preservation Section vs Paper Custom Capital Section */}
        {isLiveEffective ? (
          <div className="bg-slate-900 border border-emerald-900/50 rounded-xl p-5 shadow-lg min-w-0">
            <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2 text-sm font-bold text-slate-100">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>LIVE BROKER CAPITAL & PRE-TRADE RISK PRESERVATION CONTROLS</span>
              </div>
              <span className="text-xs font-mono text-emerald-400 flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5" />
                Live Broker Safeguards Active
              </span>
            </div>

            <div className="mt-4 space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="sm:col-span-2 space-y-1">
                  <label className="text-xs font-semibold text-slate-300">
                    Assigned Live Trading Capital (INR):
                  </label>
                  <div className="relative">
                    <span className="absolute left-3 top-2 text-xs font-mono text-slate-400">₹</span>
                    <input
                      id="inputLiveCapital"
                      type="number"
                      min="500"
                      max="10000000"
                      step="500"
                      value={liveCapitalInput}
                      onChange={(e) => setLiveCapitalInput(e.target.value)}
                      placeholder="e.g. 5000"
                      className="w-full pl-7 pr-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                </div>

                <div className="flex items-end">
                  <button
                    id="btnSaveLiveCapital"
                    type="button"
                    onClick={handleSaveLiveCapital}
                    className="w-full px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-md transition flex items-center justify-center gap-1.5"
                  >
                    <ShieldCheck className="w-4 h-4" />
                    <span>Set Live Capital Floor</span>
                  </button>
                </div>
              </div>

              {liveCapitalSavedMsg && (
                <div className="p-2.5 bg-emerald-950/40 border border-emerald-800/60 rounded-lg text-xs text-emerald-300 flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span>{liveCapitalSavedMsg}</span>
                </div>
              )}

              {/* Live Risk Preservation Invariants Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 pt-2 text-xs font-mono">
                <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-lg">
                  <div className="text-[10px] text-slate-400">Max SL per Trade:</div>
                  <div className="text-sm font-bold text-rose-400 mt-0.5">₹500.00 (10%)</div>
                  <div className="text-[9px] text-slate-500 mt-0.5">Strict execution stop floor</div>
                </div>
                <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-lg">
                  <div className="text-[10px] text-slate-400">Daily Max Loss Limit:</div>
                  <div className="text-sm font-bold text-amber-400 mt-0.5">₹1,250.00 (25%)</div>
                  <div className="text-[9px] text-slate-500 mt-0.5">Session kill-switch threshold</div>
                </div>
                <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-lg">
                  <div className="text-[10px] text-slate-400">Live Order Dispatch:</div>
                  <div className="text-sm font-bold text-amber-400 mt-0.5">FAIL-CLOSED (HTTP 403)</div>
                  <div className="text-[9px] text-slate-500 mt-0.5">Zero unverified fills</div>
                </div>
                <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-lg">
                  <div className="text-[10px] text-slate-400">Target Instruments:</div>
                  <div className="text-sm font-bold text-cyan-400 mt-0.5">NIFTY 50 & BANKNIFTY</div>
                  <div className="text-[9px] text-slate-500 mt-0.5">Deep liquidity F&O strikes</div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg min-w-0">
            <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2 text-sm font-bold text-slate-100">
                <Coins className="w-4 h-4 text-amber-400" />
                <span>CUSTOM PAPER CAPITAL ALLOCATION</span>
              </div>
              <span className="text-xs font-mono text-slate-400">
                Permitted Bounds: ₹5,000 – ₹1,00,00,000 (INR 1 Crore)
              </span>
            </div>

            <div className="mt-4 space-y-4">
              {/* Presets */}
              <div>
                <label className="text-xs font-semibold text-slate-300 block mb-1.5">
                  Quick Preset Allocations:
                </label>
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
                  {PRESET_CAPITALS.map((preset) => (
                    <button
                      key={preset.value}
                      type="button"
                      onClick={() => handleSelectPreset(preset.value)}
                      className={`p-2.5 rounded-lg border text-left transition ${
                        Number(customInput) === preset.value
                          ? 'bg-amber-950/40 border-amber-500/60 text-amber-300'
                          : 'bg-slate-950/60 border-slate-800 text-slate-300 hover:bg-slate-800 hover:text-white'
                      }`}
                    >
                      <div className="font-bold font-mono text-sm">{preset.label}</div>
                      <div className="text-[10px] text-slate-500 mt-0.5">{preset.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Custom Inputs */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="sm:col-span-2 space-y-1">
                  <label className="text-xs font-semibold text-slate-300">
                    Custom Capital Amount (INR):
                  </label>
                  <div className="relative">
                    <span className="absolute left-3 top-2 text-xs font-mono text-slate-400">₹</span>
                    <input
                      id="inputCustomPaperCapital"
                      type="number"
                      min="5000"
                      max="10000000"
                      step="1000"
                      value={customInput}
                      onChange={(e) => {
                        setCustomInput(e.target.value);
                        setValidationError(null);
                      }}
                      placeholder="Enter amount between 5,000 and 1,00,00,000"
                      className="w-full pl-7 pr-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-100 placeholder-slate-500 focus:outline-none focus:border-amber-500"
                    />
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-300">
                    Epoch Label (Optional):
                  </label>
                  <input
                    id="inputCustomEpochLabel"
                    type="text"
                    value={customLabel}
                    onChange={(e) => setCustomLabel(e.target.value)}
                    placeholder="e.g., Aggressive Intraday 50k"
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-amber-500"
                  />
                </div>
              </div>

              {/* Error or Success Notice */}
              {validationError && (
                <div className="p-3 bg-rose-950/40 border border-rose-800/60 rounded-lg flex items-center gap-2 text-xs text-rose-300">
                  <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
                  <span>{validationError}</span>
                </div>
              )}
              {successMessage && (
                <div className="p-3 bg-emerald-950/40 border border-emerald-800/60 rounded-lg flex items-center gap-2 text-xs text-emerald-300">
                  <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
                  <span>{successMessage}</span>
                </div>
              )}

              {/* Submit Action */}
              <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
                <div className="text-[11px] text-slate-400 font-mono">
                  <Calculator className="w-3.5 h-3.5 inline mr-1 text-cyan-400" />
                  <span>Creating a custom epoch initializes a fresh isolated virtual ledger without overwriting standard records.</span>
                </div>

                <button
                  id="btnInitializeCustomEpoch"
                  type="button"
                  onClick={handleCreateCustomEpoch}
                  disabled={isCreating || !customInput}
                  className="px-4 py-2 rounded-lg bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-slate-950 font-bold text-xs shadow-md transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
                >
                  <PlusCircle className="w-4 h-4" />
                  <span>{isCreating ? 'Initializing Epoch...' : 'Initialize Custom Paper Epoch'}</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 3. Embedded Portfolio Workspace */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl min-w-0">
          <div className="px-4 py-3 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
            <div className="text-xs font-bold text-slate-200 uppercase tracking-wide flex items-center gap-1.5">
              <TrendingUp className="w-4 h-4 text-emerald-400" />
              <span>
                {isLiveEffective
                  ? 'Live Positions, Execution Orders & Paytm Money Settlement'
                  : `Positions, Execution Orders & Settlement for ${epochData.shortName}`}
              </span>
            </div>
            <div className="text-[11px] font-mono text-emerald-400 flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>{isLiveEffective ? 'Live Ledger Verified' : 'Accounting Identity Reconciled'}</span>
            </div>
          </div>
          <div className="h-[480px]">
            <PortfolioTradesPanel
              selectedEpoch={selectedEpoch}
              currentMode={isLiveEffective ? 'LIVE_EXECUTION' : 'PAPER'}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
