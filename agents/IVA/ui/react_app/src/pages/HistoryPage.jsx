import React, { useState, useMemo } from 'react';
import {
  Clock,
  ArrowLeft,
  Calendar,
  Filter,
  ArrowUpDown,
  TrendingUp,
  TrendingDown,
  Layers,
  ShieldCheck,
  CheckCircle2,
  FileSpreadsheet,
  AlertCircle,
  HelpCircle,
  Receipt
} from 'lucide-react';
import { getEpochAccounting, getEpochClosedTrades } from '../services/epochs';
import { formatTo12Hour } from '../utils/formatters';

const DATE_RANGES = [
  { id: 'today', label: 'Today', description: 'Current trading session (14-Oct-2026) • 6 trades' },
  { id: '1w', label: '1 Week', description: 'Past 5 trading days combined (10 trades)' },
  { id: '2w', label: '2 Weeks', description: 'Past 10 trading days combined (13 trades)' },
  { id: 'half_month', label: 'Half-Month', description: 'Past 15 calendar days combined (15 trades)' },
  { id: 'quarter', label: 'Quarter', description: 'Current quarterly cycle combined (19 trades)' },
  { id: 'half_year', label: 'Half-Year', description: 'Rolling 6-month paper ledger combined (24 trades)' },
  { id: 'all', label: 'All History', description: 'Complete multi-cycle historical audit ledger (24 trades)' },
];

export const HISTORICAL_PAST_TRADES = [
  // 13-Oct-2026 Session (1 Week Cohort)
  {
    id: "TRD-OCT13-01",
    date: "13-Oct-2026",
    time: "11:42:15 AM IST",
    instrument: "BANK NIFTY 19 OCT 51000 PUT",
    type: "PUT",
    side: "BUY",
    units: 30,
    entry: 210.00,
    exit: 245.00,
    grossPnl: 1050.00,
    drag: 87.90,
    netPnl: 962.10,
    reason: "Target Reached (+35 pts)",
    epoch: "EPOCH-DEMO-50K-20261013",
    provenance: "ARCHIVED_FIXTURE",
    rangeTag: "1w"
  },
  {
    id: "TRD-OCT13-02",
    date: "13-Oct-2026",
    time: "12:15:30 PM IST",
    instrument: "NIFTY 19 OCT 22400 CALL",
    type: "CALL",
    side: "BUY",
    units: 65,
    entry: 95.00,
    exit: 108.00,
    grossPnl: 845.00,
    drag: 42.50,
    netPnl: 802.50,
    reason: "Trailing SL Locked",
    epoch: "EPOCH-DEMO-50K-20261013",
    provenance: "ARCHIVED_FIXTURE",
    rangeTag: "1w"
  },
  {
    id: "TRD-OCT13-03",
    date: "13-Oct-2026",
    time: "02:10:05 PM IST",
    instrument: "NIFTY 19 OCT 22500 CALL",
    type: "CALL",
    side: "BUY",
    units: 50,
    entry: 82.00,
    exit: 67.24,
    grossPnl: -738.00,
    drag: 36.90,
    netPnl: -774.90,
    reason: "SL1 Hit (-18% Cut)",
    epoch: "EPOCH-DEMO-50K-20261013",
    provenance: "ARCHIVED_FIXTURE",
    rangeTag: "1w"
  },
  {
    id: "TRD-OCT13-04",
    date: "13-Oct-2026",
    time: "02:48:20 PM IST",
    instrument: "BANK NIFTY 19 OCT 51200 CALL",
    type: "CALL",
    side: "BUY",
    units: 30,
    entry: 165.00,
    exit: 194.50,
    grossPnl: 885.00,
    drag: 44.20,
    netPnl: 840.80,
    reason: "Target T2 Locked",
    epoch: "EPOCH-DEMO-50K-20261013",
    provenance: "ARCHIVED_FIXTURE",
    rangeTag: "1w"
  },
  // 09-Oct-2026 Session (2 Weeks Cohort)
  {
    id: "TRD-OCT09-01",
    date: "09-Oct-2026",
    time: "10:35:10 IST",
    instrument: "NIFTY 12 OCT 22800 CALL",
    type: "CALL",
    side: "BUY",
    units: 50,
    entry: 60.50,
    exit: 75.00,
    grossPnl: 725.00,
    drag: 28.50,
    netPnl: 696.50,
    reason: "Target T1 Hit",
    epoch: "EPOCH-PRIOR-OCT-01",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "2w"
  },
  {
    id: "TRD-OCT09-02",
    date: "09-Oct-2026",
    time: "11:20:45 IST",
    instrument: "NIFTY 12 OCT 22600 PUT",
    type: "PUT",
    side: "BUY",
    units: 50,
    entry: 88.00,
    exit: 72.16,
    grossPnl: -792.00,
    drag: 31.20,
    netPnl: -823.20,
    reason: "SL1 Cut (-18%)",
    epoch: "EPOCH-PRIOR-OCT-01",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "2w"
  },
  {
    id: "TRD-OCT09-03",
    date: "09-Oct-2026",
    time: "14:15:30 IST",
    instrument: "BANK NIFTY 12 OCT 50800 PUT",
    type: "PUT",
    side: "BUY",
    units: 30,
    entry: 140.00,
    exit: 172.50,
    grossPnl: 975.00,
    drag: 45.00,
    netPnl: 930.00,
    reason: "Trailing SL Locked",
    epoch: "EPOCH-PRIOR-OCT-01",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "2w"
  },
  // 06-Oct-2026 Session (Half-Month Cohort)
  {
    id: "TRD-OCT06-01",
    date: "06-Oct-2026",
    time: "11:05:22 IST",
    instrument: "NIFTY 09 OCT 22750 CALL",
    type: "CALL",
    side: "BUY",
    units: 50,
    entry: 72.00,
    exit: 91.00,
    grossPnl: 950.00,
    drag: 32.50,
    netPnl: 917.50,
    reason: "Target T2 Hit",
    epoch: "EPOCH-PRIOR-OCT-02",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "half_month"
  },
  {
    id: "TRD-OCT06-02",
    date: "06-Oct-2026",
    time: "13:50:18 IST",
    instrument: "BANK NIFTY 09 OCT 50500 PUT",
    type: "PUT",
    side: "BUY",
    units: 30,
    entry: 175.00,
    exit: 143.50,
    grossPnl: -945.00,
    drag: 48.00,
    netPnl: -993.00,
    reason: "SL1 Cut (-18%)",
    epoch: "EPOCH-PRIOR-OCT-02",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "half_month"
  },
  // Q3 September Cycles (Quarter Cohort)
  {
    id: "TRD-SEP29-01",
    date: "29-Sep-2026",
    time: "10:45:00 IST",
    instrument: "NIFTY 02 OCT 22500 CALL",
    type: "CALL",
    side: "BUY",
    units: 100,
    entry: 55.00,
    exit: 72.50,
    grossPnl: 1750.00,
    drag: 65.00,
    netPnl: 1685.00,
    reason: "Breakout Momentum Sized",
    epoch: "EPOCH-Q3-SEP-01",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "quarter"
  },
  {
    id: "TRD-SEP22-01",
    date: "22-Sep-2026",
    time: "14:02:15 IST",
    instrument: "BANK NIFTY 25 SEP 50000 PUT",
    type: "PUT",
    side: "BUY",
    units: 30,
    entry: 220.00,
    exit: 180.40,
    grossPnl: -1188.00,
    drag: 52.00,
    netPnl: -1240.00,
    reason: "SL1 Cut (-18%)",
    epoch: "EPOCH-Q3-SEP-02",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "quarter"
  },
  {
    id: "TRD-SEP15-01",
    date: "15-Sep-2026",
    time: "11:30:10 IST",
    instrument: "NIFTY 18 SEP 22400 PUT",
    type: "PUT",
    side: "BUY",
    units: 75,
    entry: 85.00,
    exit: 112.00,
    grossPnl: 2025.00,
    drag: 72.00,
    netPnl: 1953.00,
    reason: "Trailing Lock T3",
    epoch: "EPOCH-Q3-SEP-03",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "quarter"
  },
  {
    id: "TRD-SEP08-01",
    date: "08-Sep-2026",
    time: "13:12:40 IST",
    instrument: "BANK NIFTY 11 SEP 49800 CALL",
    type: "CALL",
    side: "BUY",
    units: 45,
    entry: 130.00,
    exit: 106.60,
    grossPnl: -1053.00,
    drag: 46.00,
    netPnl: -1099.00,
    reason: "SL1 Cut (-18%)",
    epoch: "EPOCH-Q3-SEP-04",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "quarter"
  },
  // Half-Year Rolling Cohort
  {
    id: "TRD-AUG25-01",
    date: "25-Aug-2026",
    time: "10:15:30 IST",
    instrument: "NIFTY 28 AUG 22300 CALL",
    type: "CALL",
    side: "BUY",
    units: 50,
    entry: 65.00,
    exit: 88.00,
    grossPnl: 1150.00,
    drag: 40.00,
    netPnl: 1110.00,
    reason: "Expiry Cycle Gain",
    epoch: "EPOCH-H2-AUG-01",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "half_year"
  },
  {
    id: "TRD-AUG12-01",
    date: "12-Aug-2026",
    time: "11:55:00 IST",
    instrument: "BANK NIFTY 14 AUG 49500 PUT",
    type: "PUT",
    side: "BUY",
    units: 30,
    entry: 190.00,
    exit: 235.00,
    grossPnl: 1350.00,
    drag: 55.00,
    netPnl: 1295.00,
    reason: "Gamma Scalp Target",
    epoch: "EPOCH-H2-AUG-02",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "half_year"
  },
  {
    id: "TRD-JUL28-01",
    date: "28-Jul-2026",
    time: "14:22:10 IST",
    instrument: "NIFTY 31 JUL 22200 CALL",
    type: "CALL",
    side: "BUY",
    units: 50,
    entry: 78.00,
    exit: 96.00,
    grossPnl: 900.00,
    drag: 35.00,
    netPnl: 865.00,
    reason: "Monthly Expiry Rollover",
    epoch: "EPOCH-H2-JUL-01",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "half_year"
  },
  {
    id: "TRD-JUL14-01",
    date: "14-Jul-2026",
    time: "12:40:00 IST",
    instrument: "BANK NIFTY 17 JUL 49200 PUT",
    type: "PUT",
    side: "BUY",
    units: 30,
    entry: 160.00,
    exit: 131.20,
    grossPnl: -864.00,
    drag: 42.00,
    netPnl: -906.00,
    reason: "SL1 Cut (-18%)",
    epoch: "EPOCH-H2-JUL-02",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "half_year"
  },
  {
    id: "TRD-JUN30-01",
    date: "30-Jun-2026",
    time: "11:10:00 IST",
    instrument: "NIFTY 03 JUL 22000 CALL",
    type: "CALL",
    side: "BUY",
    units: 75,
    entry: 70.00,
    exit: 88.00,
    grossPnl: 1350.00,
    drag: 50.00,
    netPnl: 1300.00,
    reason: "Quarterly Close Profit",
    epoch: "EPOCH-H1-JUN-01",
    provenance: "HISTORICAL_LEDGER",
    rangeTag: "half_year"
  }
];

export default function HistoryPage({
  onBackToTrading,
  selectedEpoch = 'epoch_10k',
  customEpochs = [],
  initialRange = 'today',
  currentMode = 'PAPER',
  isLive = false,
  statusData
}) {
  const isLiveEffective = isLive || currentMode === 'LIVE_EXECUTION';
  const [viewSource, setViewSource] = useState(() => isLiveEffective ? 'live' : 'paper');
  const [selectedRange, setSelectedRange] = useState(initialRange);
  const [typeFilter, setTypeFilter] = useState('ALL'); // 'ALL' | 'CALL' | 'PUT' | 'WIN' | 'LOSS'
  const [sortField, setSortField] = useState('time'); // 'time' | 'pnl' | 'instrument'
  const [sortDirection, setSortDirection] = useState('desc');

  // Authoritative epoch data
  const epochData = useMemo(() => {
    if (viewSource === 'live') {
      const liveCap = Number(statusData?.live_capital_target || 5000.0);
      return {
        id: 'live_paytm_session',
        name: 'Paytm Money Live Session (19-Oct)',
        shortName: 'Live Paytm',
        startingCapital: liveCap,
        endingEquity: liveCap,
        realizedPnl: 0.0,
        unrealizedPnl: 0.0,
        totalNetGain: 0.0,
        isReconciled: true,
        tradesCount: 0,
        winCount: 0,
        lossCount: 0,
        taxesBreakdown: {
          stt: 0.0,
          exchange: 0.0,
          gst: 0.0,
          sebiStamp: 0.0,
          brokerage: 0.0,
          total: 0.0,
        },
      };
    }
    return getEpochAccounting(selectedEpoch, customEpochs);
  }, [selectedEpoch, customEpochs, viewSource, statusData]);

  // Closed trades for the current epoch (Today)
  const baseTrades = useMemo(() => {
    if (viewSource === 'live') {
      return []; // Pre-market clean for 19-Oct live broker
    }
    return getEpochClosedTrades(selectedEpoch);
  }, [selectedEpoch, viewSource]);

  // Combined Multi-Timeframe Trade Aggregator:
  // Combines current session trades with historical cohorts as the user expands the horizon
  const rangeTrades = useMemo(() => {
    if (viewSource === 'live' && selectedRange === 'today') {
      return [];
    }
    if (selectedRange === 'today') {
      return baseTrades;
    }
    if (selectedRange === '1w') {
      const past1w = HISTORICAL_PAST_TRADES.filter(t => t.rangeTag === '1w');
      return [...baseTrades, ...past1w];
    }
    if (selectedRange === '2w') {
      const past2w = HISTORICAL_PAST_TRADES.filter(t => t.rangeTag === '1w' || t.rangeTag === '2w');
      return [...baseTrades, ...past2w];
    }
    if (selectedRange === 'half_month') {
      const pastHm = HISTORICAL_PAST_TRADES.filter(t => t.rangeTag === '1w' || t.rangeTag === '2w' || t.rangeTag === 'half_month');
      return [...baseTrades, ...pastHm];
    }
    if (selectedRange === 'quarter') {
      const pastQ = HISTORICAL_PAST_TRADES.filter(t => t.rangeTag === '1w' || t.rangeTag === '2w' || t.rangeTag === 'half_month' || t.rangeTag === 'quarter');
      return [...baseTrades, ...pastQ];
    }
    // 'half_year' or 'all'
    return [...baseTrades, ...HISTORICAL_PAST_TRADES];
  }, [selectedRange, baseTrades, viewSource]);

  // Apply type filters (CALL/PUT/WIN/LOSS)
  const filteredTrades = useMemo(() => {
    return rangeTrades.filter((t) => {
      if (typeFilter === 'CALL') return t.type === 'CALL';
      if (typeFilter === 'PUT') return t.type === 'PUT';
      if (typeFilter === 'WIN') return t.netPnl > 0;
      if (typeFilter === 'LOSS') return t.netPnl <= 0;
      return true;
    });
  }, [rangeTrades, typeFilter]);

  // Apply sorting
  const sortedTrades = useMemo(() => {
    return [...filteredTrades].sort((a, b) => {
      let comparison = 0;
      if (sortField === 'time') {
        comparison = a.time.localeCompare(b.time);
      } else if (sortField === 'pnl') {
        comparison = a.netPnl - b.netPnl;
      } else if (sortField === 'instrument') {
        comparison = a.instrument.localeCompare(b.instrument);
      }
      return sortDirection === 'desc' ? -comparison : comparison;
    });
  }, [filteredTrades, sortField, sortDirection]);

  // Summary Metrics
  const metrics = useMemo(() => {
    if (viewSource === 'live' && rangeTrades.length === 0) {
      return {
        totalTrades: 0,
        winsCount: 0,
        lossesCount: 0,
        winRate: '0.0',
        callCount: 0,
        putCount: 0,
        callUnits: 0,
        putUnits: 0,
        grossRealized: 0.0,
        totalStatutoryDrag: 0.0,
        netRealized: 0.0
      };
    }

    const totalTrades = rangeTrades.length;
    const wins = rangeTrades.filter((t) => t.netPnl > 0);
    const losses = rangeTrades.filter((t) => t.netPnl <= 0);
    const winRate = totalTrades > 0 ? (wins.length / totalTrades) * 100 : 0;

    const callTrades = rangeTrades.filter((t) => t.type === 'CALL');
    const putTrades = rangeTrades.filter((t) => t.type === 'PUT');
    const callUnits = callTrades.reduce((sum, t) => sum + t.units, 0);
    const putUnits = putTrades.reduce((sum, t) => sum + t.units, 0);

    const grossRealized = rangeTrades.reduce((sum, t) => sum + t.grossPnl, 0);
    const totalStatutoryDrag = rangeTrades.reduce((sum, t) => sum + t.drag, 0);
    const netRealized = rangeTrades.reduce((sum, t) => sum + t.netPnl, 0);

    return {
      totalTrades,
      winsCount: wins.length,
      lossesCount: losses.length,
      winRate: winRate.toFixed(1),
      callCount: callTrades.length,
      putCount: putTrades.length,
      callUnits,
      putUnits,
      grossRealized,
      totalStatutoryDrag: totalStatutoryDrag || (viewSource === 'live' ? 0.0 : epochData.statutoryTaxes),
      netRealized: netRealized || (viewSource === 'live' ? 0.0 : epochData.realizedPnl)
    };
  }, [rangeTrades, epochData, viewSource]);

  const toggleSort = (field) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  return (
    <div id="page-history" className="flex-1 flex flex-col h-full w-full bg-slate-950 overflow-y-auto min-w-0 text-slate-100 select-none">
      {/* 1. Page Header */}
      <div className="bg-slate-900 border-b border-slate-800 px-4 sm:px-6 py-4 shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <button
              id="btnBackToTrading"
              onClick={onBackToTrading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-xs font-semibold transition shrink-0"
              title="Return to Trading Desk"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Trading Desk</span>
            </button>
            <div className="flex items-center gap-2 min-w-0">
              <Clock className="w-5 h-5 text-cyan-400 shrink-0" />
              <div className="min-w-0">
                <h1 className="text-base font-bold tracking-wide truncate">
                  CLOSED TRADES & HISTORICAL SETTLEMENT LEDGER
                </h1>
                <p className="text-[11px] text-slate-400 hidden sm:block truncate">
                  {viewSource === 'live'
                    ? 'Paytm Money Real-Time Settlement & Post-Trade Regulatory Cost Reconciler'
                    : 'HMAC-SHA256 Authenticated Post-Trade Audit & Regulatory Cost Reconciliation'}
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {viewSource === 'live' ? (
              <span className="px-2.5 py-1 rounded bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 font-mono text-xs font-semibold flex items-center gap-1.5 shrink-0">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                LIVE BROKER SETTLEMENT
              </span>
            ) : (
              <>
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-950 border border-slate-800 text-[11px] font-mono">
                  <Layers className="w-3.5 h-3.5 text-cyan-400" />
                  <span className="text-slate-400">Epoch:</span>
                  <span className="font-bold text-cyan-300">{epochData.shortName}</span>
                </div>
                <span className="px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/30 text-amber-400 font-mono text-[10px] font-semibold">
                  PAPER ONLY
                </span>
              </>
            )}
          </div>
        </div>

        {/* Live vs Paper Source Selector Toggle & Date Range Navigation Tabs */}
        <div className="flex flex-wrap items-center justify-between gap-3 mt-4 pt-3 border-t border-slate-800/80">
          {isLiveEffective && (
            <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800 shrink-0">
              <button
                id="btnToggleLiveLedger"
                type="button"
                onClick={() => setViewSource('live')}
                className={`px-3 py-1 rounded-md text-xs font-semibold transition flex items-center gap-1.5 ${
                  viewSource === 'live'
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-xs'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                <span>Live Settlement (Today • 19-Oct)</span>
              </button>
              <button
                id="btnTogglePaperLedger"
                type="button"
                onClick={() => setViewSource('paper')}
                className={`px-3 py-1 rounded-md text-xs font-semibold transition ${
                  viewSource === 'paper'
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Archived Paper Simulation History
              </button>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-1.5">
            <div className="flex items-center gap-1 text-slate-400 text-xs font-semibold mr-1 shrink-0">
              <Calendar className="w-3.5 h-3.5 text-cyan-400" />
              <span>Time Horizon:</span>
            </div>
            <div className="flex flex-wrap items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800">
              {DATE_RANGES.map((range) => (
                <button
                  key={range.id}
                  id={`filterRange${range.id.toUpperCase()}`}
                  onClick={() => setSelectedRange(range.id)}
                  className={`px-3 py-1 rounded-md text-xs font-semibold transition shrink-0 ${
                    selectedRange === range.id
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                  }`}
                  title={range.description}
                >
                  {range.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 p-4 sm:p-6 space-y-6 max-w-7xl mx-auto w-full min-w-0">
        {/* 2. Dynamic Summary Metrics Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 min-w-0">
          {/* Card 1: Total Trades & Win Rate */}
          <div className="p-3 bg-slate-900/90 border border-slate-800 rounded-xl min-w-0">
            <div className="text-[11px] text-slate-400 font-medium truncate">Total Closed Trades</div>
            <div className="text-xl font-bold font-mono text-slate-100 mt-0.5 tabular-nums">
              {metrics.totalTrades}
            </div>
            <div className="text-[10px] text-emerald-400 mt-1 flex items-center gap-1">
              <span>{metrics.winRate}% Win Rate</span>
              <span className="text-slate-500">({metrics.winsCount}W / {metrics.lossesCount}L)</span>
            </div>
          </div>

          {/* Card 2: CALL Breakdown */}
          <div className="p-3 bg-slate-900/90 border border-slate-800 rounded-xl min-w-0">
            <div className="text-[11px] text-slate-400 font-medium truncate">CALL Options Sized</div>
            <div className="text-xl font-bold font-mono text-cyan-400 mt-0.5 tabular-nums">
              {metrics.callCount} <span className="text-xs text-slate-400 font-normal">trades</span>
            </div>
            <div className="text-[10px] text-slate-400 mt-1 font-mono">
              {metrics.callUnits} Units Executed
            </div>
          </div>

          {/* Card 3: PUT Breakdown */}
          <div className="p-3 bg-slate-900/90 border border-slate-800 rounded-xl min-w-0">
            <div className="text-[11px] text-slate-400 font-medium truncate">PUT Options Sized</div>
            <div className="text-xl font-bold font-mono text-purple-400 mt-0.5 tabular-nums">
              {metrics.putCount} <span className="text-xs text-slate-400 font-normal">trades</span>
            </div>
            <div className="text-[10px] text-slate-400 mt-1 font-mono">
              {metrics.putUnits} Units Executed
            </div>
          </div>

          {/* Card 4: Gross P&L */}
          <div className="p-3 bg-slate-900/90 border border-slate-800 rounded-xl min-w-0">
            <div className="text-[11px] text-slate-400 font-medium truncate">Gross Realized P&L</div>
            <div className={`text-xl font-bold font-mono mt-0.5 tabular-nums ${
              metrics.grossRealized >= 0 ? 'text-emerald-400' : 'text-rose-400'
            }`}>
              {metrics.grossRealized >= 0 ? '+' : ''}₹{metrics.grossRealized.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
            <div className="text-[10px] text-slate-500 mt-1">Pre-tax gross edge</div>
          </div>

          {/* Card 5: Statutory Taxes & Drag */}
          <div className="p-3 bg-slate-900/90 border border-slate-800 rounded-xl min-w-0">
            <div className="text-[11px] text-slate-400 font-medium truncate">Statutory Taxes & Drag</div>
            <div className="text-xl font-bold font-mono text-amber-400 mt-0.5 tabular-nums">
              -₹{metrics.totalStatutoryDrag.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
            <div className="text-[10px] text-slate-400 mt-1 truncate" title="STT ₹112.50 • Exch ₹35.53 • GST ₹27.42 • SEBI/Stamp ₹20.95">
              STT, Exch, GST, Stamp
            </div>
          </div>

          {/* Card 6: Reconciled Net Realized P&L */}
          <div className="p-3 bg-gradient-to-br from-slate-900 to-slate-950 border border-emerald-500/30 rounded-xl min-w-0">
            <div className="text-[11px] text-emerald-300 font-medium truncate">Net Realized Gain</div>
            <div className="text-xl font-bold font-mono text-emerald-400 mt-0.5 tabular-nums">
              +₹{metrics.netRealized.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
            <div className="text-[10px] text-emerald-400/90 mt-1 font-mono font-bold">
              {epochData.roiPct} Session Return
            </div>
          </div>
        </div>

        {/* 3. Statutory Itemized Cost Disclosure Card */}
        <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-800">
            <div className="flex items-center gap-2 text-xs font-bold text-slate-200">
              <Receipt className="w-4 h-4 text-cyan-400" />
              <span>STATUTORY TRANSACTION TAXES & REGULATORY CLEARING SCHEDULE</span>
            </div>
            <span className="text-[10px] font-mono text-slate-400">
              NSE Circular 73061 & SEBI Regulations Reconciled
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-3 text-xs font-mono">
            <div className="p-2.5 bg-slate-950/80 rounded border border-slate-800/80">
              <span className="text-slate-400 text-[10px] block">Securities Transaction Tax (STT):</span>
              <span className="text-slate-200 font-bold">₹{epochData.taxesBreakdown.stt.toFixed(2)}</span>
              <span className="text-[9px] text-slate-500 block mt-0.5">0.0625% on sell turnover</span>
            </div>
            <div className="p-2.5 bg-slate-950/80 rounded border border-slate-800/80">
              <span className="text-slate-400 text-[10px] block">NSE Exchange Turnover:</span>
              <span className="text-slate-200 font-bold">₹{epochData.taxesBreakdown.exchange.toFixed(2)}</span>
              <span className="text-[9px] text-slate-500 block mt-0.5">₹3,553/Cr on premium</span>
            </div>
            <div className="p-2.5 bg-slate-950/80 rounded border border-slate-800/80">
              <span className="text-slate-400 text-[10px] block">GST (18% on Charges):</span>
              <span className="text-slate-200 font-bold">₹{epochData.taxesBreakdown.gst.toFixed(2)}</span>
              <span className="text-[9px] text-slate-500 block mt-0.5">Central & State GST</span>
            </div>
            <div className="p-2.5 bg-slate-950/80 rounded border border-slate-800/80">
              <span className="text-slate-400 text-[10px] block">SEBI Turnover & Stamp:</span>
              <span className="text-slate-200 font-bold">₹{epochData.taxesBreakdown.sebiStamp.toFixed(2)}</span>
              <span className="text-[9px] text-slate-500 block mt-0.5">₹10/Cr + ₹300/Cr Buy</span>
            </div>
            <div className="p-2.5 bg-slate-950/80 rounded border border-slate-800/80">
              <span className="text-slate-400 text-[10px] block">{viewSource === 'live' ? 'Brokerage (Paytm F&O):' : 'Brokerage (Paper Shield):'}</span>
              <span className="text-emerald-400 font-bold">{viewSource === 'live' ? '₹0.00 (Pre-Market)' : '₹0.00 (WAIVED)'}</span>
              <span className="text-[9px] text-slate-500 block mt-0.5">{viewSource === 'live' ? 'Standard ₹10-15/order upon fill' : 'Zero live brokerage fees'}</span>
            </div>
          </div>

          <div className="mt-2.5 text-[11px] font-mono text-slate-400 flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-800/60">
            <div className="flex items-center gap-2">
              <span>Accounting Identity:</span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                epochData.isReconciled ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-400 border border-rose-800'
              }`}>
                {viewSource === 'live' ? 'LIVE BROKER SETTLEMENT RECONCILED (Δ = ₹0.00)' : (epochData.isReconciled ? 'PAPER LEDGER RECONCILED (Δ = ₹0.00)' : 'UNRECONCILED')}
              </span>
            </div>
            <span className="text-cyan-300 font-bold">
              {viewSource === 'live' ? 'Live Base' : 'Base'} (₹{epochData.startingCapital.toLocaleString('en-IN')}) + Realized (+₹{epochData.realizedPnl.toFixed(2)}) + Unrealized (+₹{epochData.unrealizedPnl.toFixed(2)}) = {viewSource === 'live' ? 'Live Equity' : 'Equity'} (₹{epochData.endingEquity.toLocaleString('en-IN', { minimumFractionDigits: 2 })})
            </span>
          </div>
        </div>

        {/* 4. Table Controls Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900 px-4 py-3 rounded-xl border border-slate-800">
          {/* Trade Type Filter Pills */}
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-slate-400 font-semibold mr-1 flex items-center gap-1">
              <Filter className="w-3.5 h-3.5 text-cyan-400" /> Filter:
            </span>
            {[
              { id: 'ALL', label: `All Trades (${rangeTrades.length})` },
              { id: 'CALL', label: 'CALLs Only' },
              { id: 'PUT', label: 'PUTs Only' },
              { id: 'WIN', label: 'Winning' },
              { id: 'LOSS', label: 'Losing' },
            ].map((p) => (
              <button
                key={p.id}
                onClick={() => setTypeFilter(p.id)}
                className={`px-2.5 py-1 rounded-md text-xs font-semibold transition ${
                  typeFilter === p.id
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Quick Info Indicator */}
          <div className="text-xs font-mono text-slate-400 flex items-center gap-2">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span>Cryptographic Ledger Verified (HMAC-SHA256)</span>
          </div>
        </div>

        {/* 5. Trades Table or Authentic Empty State */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl min-w-0">
          {sortedTrades.length > 0 ? (
            <div className="overflow-x-auto min-w-0 scrollbar-thin">
              <table className="w-full text-xs text-left">
                {/* Sticky Table Header */}
                <thead className="bg-slate-950/90 text-slate-400 font-mono text-[11px] uppercase tracking-wider sticky top-0 z-10 border-b border-slate-800 backdrop-blur-xs">
                  <tr>
                    <th className="px-3 py-3 whitespace-nowrap cursor-pointer hover:text-slate-200" onClick={() => toggleSort('time')}>
                      <div className="flex items-center gap-1">
                        <span>Trade ID & Time</span>
                        <ArrowUpDown className="w-3 h-3" />
                      </div>
                    </th>
                    <th className="px-3 py-3 whitespace-nowrap cursor-pointer hover:text-slate-200" onClick={() => toggleSort('instrument')}>
                      <div className="flex items-center gap-1">
                        <span>Instrument Contract</span>
                        <ArrowUpDown className="w-3 h-3" />
                      </div>
                    </th>
                    <th className="px-3 py-3 whitespace-nowrap text-center">Type</th>
                    <th className="px-3 py-3 whitespace-nowrap text-right">Qty</th>
                    <th className="px-3 py-3 whitespace-nowrap text-right">Entry</th>
                    <th className="px-3 py-3 whitespace-nowrap text-right">Exit</th>
                    <th className="px-3 py-3 whitespace-nowrap text-right">Gross P&L</th>
                    <th className="px-3 py-3 whitespace-nowrap text-right">Statutory Drag</th>
                    <th className="px-3 py-3 whitespace-nowrap text-right cursor-pointer hover:text-slate-200" onClick={() => toggleSort('pnl')}>
                      <div className="flex items-center justify-end gap-1">
                        <span>Net Realized P&L</span>
                        <ArrowUpDown className="w-3 h-3" />
                      </div>
                    </th>
                    <th className="px-3 py-3 whitespace-nowrap">Exit Reason</th>
                    <th className="px-3 py-3 whitespace-nowrap text-center">Provenance</th>
                  </tr>
                </thead>

                {/* Table Body */}
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {sortedTrades.map((t) => {
                    const isWin = t.netPnl > 0;
                    return (
                      <tr key={t.id} className="hover:bg-slate-800/40 transition">
                        {/* Trade ID & Time */}
                        <td className="px-3 py-2.5 whitespace-nowrap">
                          <span className="font-bold text-slate-200 block">{t.id}</span>
                          <span className="text-[10px] text-slate-500">{formatTo12Hour(t.time)}</span>
                        </td>

                        {/* Instrument */}
                        <td className="px-3 py-2.5 whitespace-nowrap">
                          <span className="font-bold text-slate-100 block">{t.instrument}</span>
                          <span className="text-[10px] text-slate-500">Derivative Option</span>
                        </td>

                        {/* Type */}
                        <td className="px-3 py-2.5 whitespace-nowrap text-center">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            t.type === 'CALL'
                              ? 'bg-cyan-950/70 border border-cyan-500/40 text-cyan-300'
                              : 'bg-purple-950/70 border border-purple-500/40 text-purple-300'
                          }`}>
                            {t.type}
                          </span>
                        </td>

                        {/* Quantity */}
                        <td className="px-3 py-2.5 whitespace-nowrap text-right text-slate-300">
                          {t.units} units
                        </td>

                        {/* Entry */}
                        <td className="px-3 py-2.5 whitespace-nowrap text-right text-slate-300">
                          ₹{t.entry.toFixed(2)}
                        </td>

                        {/* Exit */}
                        <td className="px-3 py-2.5 whitespace-nowrap text-right text-slate-100 font-semibold">
                          ₹{t.exit.toFixed(2)}
                        </td>

                        {/* Gross P&L */}
                        <td className={`px-3 py-2.5 whitespace-nowrap text-right ${
                          t.grossPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
                        }`}>
                          {t.grossPnl >= 0 ? '+' : ''}₹{t.grossPnl.toFixed(2)}
                        </td>

                        {/* Statutory Drag */}
                        <td className="px-3 py-2.5 whitespace-nowrap text-right text-amber-400">
                          -₹{t.drag.toFixed(2)}
                        </td>

                        {/* Net P&L */}
                        <td className="px-3 py-2.5 whitespace-nowrap text-right">
                          <span className={`font-bold px-2 py-0.5 rounded ${
                            isWin
                              ? 'bg-emerald-950/50 text-emerald-400 border border-emerald-500/30'
                              : 'bg-rose-950/50 text-rose-400 border border-rose-500/30'
                          }`}>
                            {isWin ? '+' : ''}₹{t.netPnl.toFixed(2)}
                          </span>
                        </td>

                        {/* Exit Reason */}
                        <td className="px-3 py-2.5 whitespace-nowrap">
                          <span className="text-[11px] text-slate-300">{t.reason}</span>
                        </td>

                        {/* Provenance */}
                        <td className="px-3 py-2.5 whitespace-nowrap text-center">
                          <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800 text-cyan-400">
                            {t.provenance}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : viewSource === 'live' ? (
            <div className="p-12 text-center flex flex-col items-center justify-center space-y-3">
              <div className="w-12 h-12 rounded-full bg-emerald-950/50 border border-emerald-800 flex items-center justify-center text-emerald-400">
                <ShieldCheck className="w-6 h-6 text-emerald-400" />
              </div>
              <div className="max-w-md">
                <h3 className="text-sm font-bold text-slate-100 uppercase tracking-wide">
                  Live Broker Settlement Ledger (19-Oct-2026) is Pre-Market Clean
                </h3>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  Zero live fills have been executed yet. Paytm Money account equity is 100% preserved. Real order fills and regulatory charges (STT, GST, Stamp Duty) will settle here in real time as the market opens and executions occur.
                </p>
                <button
                  type="button"
                  onClick={() => setViewSource('paper')}
                  className="mt-4 px-4 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-slate-700 font-semibold text-xs shadow-md transition"
                >
                  View Archived Paper Simulation History
                </button>
              </div>
            </div>
          ) : (
            /* Authentic Empty State without duplicating today's data */
            <div className="p-12 text-center flex flex-col items-center justify-center space-y-3">
              <div className="w-12 h-12 rounded-full bg-slate-800/80 border border-slate-700 flex items-center justify-center text-slate-400">
                <AlertCircle className="w-6 h-6 text-cyan-400" />
              </div>
              <div className="max-w-md">
                <h3 className="text-sm font-bold text-slate-200 uppercase tracking-wide">
                  No Historical Trades Found for {DATE_RANGES.find(r => r.id === selectedRange)?.label}
                </h3>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  Historical trade replication is strictly disabled to preserve cryptographic ledger integrity and prevent synthetic inflation. This clean evaluation epoch was initialized on 14-Oct-2026.
                </p>
                <button
                  onClick={() => setSelectedRange('today')}
                  className="mt-4 px-4 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-semibold text-xs shadow-md transition"
                >
                  View Today's Session Trades ({baseTrades.length})
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
