/**
 * Authoritative Epoch Definitions and Reconciled Accounting Catalog
 * For AGI 1.7 OMEGA COMMAND (V5.2 Corrective Pass)
 * 
 * Strictly isolates:
 * 1. epoch_10k: ₹10,000 Active Evaluation Sandbox (EPOCH-PAPER-10K-20261014-001)
 * 2. epoch_50k: ₹50,000 Historical Demo Baseline (EPOCH-DEMO-50K-20261013)
 * 3. epoch_100k: ₹1,00,000 Multi-Asset Milestone (EPOCH-MULTI-100K-20261014)
 * 4. Custom Epochs: User-configured paper capital within bounds [₹5,000 to ₹1,00,00,000]
 */

export const STANDARD_EPOCHS = [
  {
    id: 'epoch_100k',
    serverEpochId: 'EPOCH-MULTI-100K-20261019',
    name: '₹1,00,000 Paytm Live Supervised Session (19 Oct)',
    shortName: '₹1,00,000 Paytm Session',
    tag: 'Active Live Session',
    startingCapital: 108392.50,
    cashReserve: 108392.50,
    deployedMargin: 0.0,
    grossRealizedPnl: 0.0,
    realizedPnl: 0.0,
    unrealizedPnl: 0.0,
    endingEquity: 108392.50,
    roiPct: '+0.00%',
    reservePct: '100.0%',
    deployedPct: '0.0%',
    statutoryTaxes: 0.0,
    taxesBreakdown: {
      stt: 0.0,
      exchange: 0.0,
      gst: 0.0,
      sebiStamp: 0.0,
      brokerage: 0.0
    },
    activePositionsCount: 0,
    closedTradesCount: 4,
    status: 'ACTIVE_PAYTM_SESSION',
    isolation: 'PAYTM_SYNCHRONIZED_LEDGER',
    accountingIdentity: '108392.50 + 0.00 + 0.00 = 108392.50',
    isReconciled: true,
    description: 'Active Paytm Money session for 19-Oct-2026. Flat book overnight: 0 open runners, 100% cash preserved. All 16-Oct trades settled (+₹8,392.50 net) into capital balance.'
  },
  {
    id: 'epoch_10k',
    serverEpochId: 'EPOCH-PAPER-10K-20261014-001',
    name: '₹10,000 Scaled Evaluation Sandbox',
    shortName: '₹10,000 Sandbox',
    tag: 'Scaled Live Session',
    startingCapital: 10000.0,
    cashReserve: 6640.9,
    deployedMargin: 4890.0,
    grossRealizedPnl: 1540.50,
    realizedPnl: 1530.90,
    unrealizedPnl: 926.70,
    endingEquity: 12457.60,
    roiPct: '+24.58%',
    reservePct: '66.4%',
    deployedPct: '48.9%',
    statutoryTaxes: 9.60,
    taxesBreakdown: {
      stt: 5.45,
      exchange: 1.85,
      gst: 1.40,
      sebiStamp: 0.90,
      brokerage: 0.0
    },
    activePositionsCount: 2,
    closedTradesCount: 3,
    status: 'ACTIVE_EVALUATION',
    isolation: 'SCALED_SANDBOX_ISOLATION',
    accountingIdentity: '10000.00 + 1530.90 + 926.70 = 12457.60',
    isReconciled: true,
    description: 'Scaled ₹10,000 internal paper-evaluation sandbox tracking live Paytm trade execution.'
  },
  {
    id: 'epoch_50k',
    serverEpochId: 'EPOCH-DEMO-50K-20261013',
    name: '₹50,000 Historical Demo Baseline',
    shortName: '₹50,000 Demo',
    tag: 'Archived Baseline',
    startingCapital: 50000.0,
    cashReserve: 41420.0,
    deployedMargin: 8580.0,
    grossRealizedPnl: 1768.35,
    realizedPnl: 1680.45,
    unrealizedPnl: 585.00,
    endingEquity: 52265.45,
    roiPct: '+4.53%',
    reservePct: '82.8%',
    deployedPct: '17.2%',
    statutoryTaxes: 87.90,
    taxesBreakdown: {
      stt: 46.20,
      exchange: 18.50,
      gst: 13.20,
      sebiStamp: 10.00,
      brokerage: 0.0
    },
    activePositionsCount: 1,
    closedTradesCount: 2,
    status: 'ARCHIVED_BASELINE',
    isolation: 'ARCHIVED_LEDGER_FIXTURE',
    accountingIdentity: '50000.00 + 1680.45 + 585.00 = 52265.45',
    isReconciled: true,
    description: 'Archived historical baseline for regression verification and calibration testing.'
  }
];

export const CLOSED_TRADES_100K = [
  {
    id: "TRD-EOD-56000",
    time: "03:30:00 PM IST",
    instrument: "BANKNIFTY 27 OCT 56000 CALL",
    type: "CALL",
    side: "BUY",
    units: 60,
    entry: 465.00,
    exit: 482.80,
    grossPnl: 1068.00,
    drag: 24.00,
    netPnl: 1068.00,
    reason: "EOD Auto-Square Off & Settlement • Profit Locked",
    epoch: "EPOCH-MULTI-100K-20261016",
    provenance: "LIVE_PAYTM_SESSION"
  },
  {
    id: "TRD-SL-23150",
    time: "11:10:00 AM IST",
    instrument: "NIFTY 19 OCT 23150 CALL",
    type: "CALL",
    side: "BUY",
    units: 150,
    entry: 86.95,
    exit: 74.00,
    grossPnl: -1942.50,
    drag: 24.00,
    netPnl: -1942.50,
    reason: "🛑 STOP LOSS HIT: Live price breached ₹74.00 floor (Defended capital vs ₹63.95 low)",
    epoch: "EPOCH-MULTI-100K-20261016",
    provenance: "LIVE_PAYTM_SESSION"
  },
  {
    id: "TRD-ROT-02",
    time: "10:55:00 AM IST",
    instrument: "BANKNIFTY 27 OCT 55700 CALL",
    type: "CALL",
    side: "BUY",
    units: 60,
    entry: 540.00,
    exit: 602.00,
    grossPnl: 3720.00,
    drag: 24.00,
    netPnl: 3696.00,
    reason: "Target 1 Hit • Trailed SL Locked @ ₹602.00",
    epoch: "EPOCH-MULTI-100K-20261016",
    provenance: "LIVE_PAYTM_SESSION"
  },
  {
    id: "TRD-ROT-01",
    time: "10:54:30 AM IST",
    instrument: "NIFTY 19 OCT 23000 CALL",
    type: "CALL",
    side: "BUY",
    units: 150,
    entry: 110.00,
    exit: 147.30,
    grossPnl: 5595.00,
    drag: 24.00,
    netPnl: 5571.00,
    reason: "Target 1 Hit • Trailed SL Locked @ ₹147.30",
    epoch: "EPOCH-MULTI-100K-20261016",
    provenance: "LIVE_PAYTM_SESSION"
  }
];

export const CLOSED_TRADES_10K = [];

export const CLOSED_TRADES_50K = [
  {
    id: "TRD-DEMO-01",
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
    provenance: "ARCHIVED_FIXTURE"
  },
  {
    id: "TRD-DEMO-SETTLED",
    time: "10:30:00 AM IST",
    instrument: "NIFTY 19 OCT 22400 CALL",
    type: "CALL",
    side: "BUY",
    units: 50,
    entry: 95.00,
    exit: 109.37,
    grossPnl: 718.35,
    drag: 0.00,
    netPnl: 718.35,
    reason: "Trailing SL Locked (Settled Session P&L)",
    epoch: "EPOCH-DEMO-50K-20261013",
    provenance: "ARCHIVED_FIXTURE"
  }
];

/**
 * Retrieve reconciled accounting data for any epoch ID.
 */
export function getEpochAccounting(epochId, customEpochs = []) {
  // Check standard epochs first
  const std = STANDARD_EPOCHS.find(e => e.id === epochId || e.serverEpochId === epochId);
  if (std) {
    const isReconciled = Math.abs((std.startingCapital + std.realizedPnl + std.unrealizedPnl) - std.endingEquity) < 0.05;
    return {
      ...std,
      isReconciled,
      accountingIdentity: `${std.startingCapital.toFixed(2)} + ${std.realizedPnl.toFixed(2)} + ${std.unrealizedPnl.toFixed(2)} = ${std.endingEquity.toFixed(2)}`
    };
  }

  // Check custom epochs
  const custom = customEpochs.find(e => e.id === epochId || e.epoch_id === epochId);
  if (custom) {
    const cap = Number(custom.startingCapital || custom.starting_capital_inr || 50000.0);
    const realized = Number(custom.realizedPnl || custom.realized_pnl_inr || 0.0);
    const unrealized = Number(custom.unrealizedPnl || custom.unrealized_pnl_inr || 0.0);
    const equity = Number(custom.endingEquity || custom.current_equity_inr || (cap + realized + unrealized));
    const cash = Number(custom.cashReserve || custom.cash_reserve_inr || cap);
    const deployed = Number(custom.deployedMargin || custom.deployed_margin_inr || 0.0);
    const isReconciled = Math.abs((cap + realized + unrealized) - equity) < 0.05;

    return {
      id: custom.id || custom.epoch_id,
      serverEpochId: custom.serverEpochId || custom.epoch_id,
      name: custom.name || custom.label || `Custom Epoch ₹${cap.toLocaleString('en-IN')}`,
      shortName: `₹${cap.toLocaleString('en-IN')} Custom`,
      tag: 'Custom Paper Capital',
      startingCapital: cap,
      cashReserve: cash,
      deployedMargin: deployed,
      grossRealizedPnl: realized,
      realizedPnl: realized,
      unrealizedPnl: unrealized,
      endingEquity: equity,
      roiPct: cap > 0 ? `${((equity - cap) / cap * 100).toFixed(2)}%` : '+0.00%',
      reservePct: cap > 0 ? `${(cash / cap * 100).toFixed(1)}%` : '100.0%',
      deployedPct: cap > 0 ? `${(deployed / cap * 100).toFixed(1)}%` : '0.0%',
      statutoryTaxes: 0.0,
      taxesBreakdown: { stt: 0, exchange: 0, gst: 0, sebiStamp: 0, brokerage: 0 },
      activePositionsCount: custom.activePositionsCount || 0,
      closedTradesCount: custom.closedTradesCount || 0,
      status: 'ACTIVE_CUSTOM_EVALUATION',
      isolation: 'ISOLATED_CUSTOM_PAPER_LEDGER',
      accountingIdentity: `${cap.toFixed(2)} + ${realized.toFixed(2)} + ${unrealized.toFixed(2)} = ${equity.toFixed(2)}`,
      isReconciled,
      description: `User-defined custom paper trading capital of ₹${cap.toLocaleString('en-IN')}. Clean isolated virtual ledger.`
    };
  }

  // Fallback to active 10k sandbox
  return STANDARD_EPOCHS[0];
}

/**
 * Retrieve closed trades for an epoch ID.
 */
export function getEpochClosedTrades(epochId) {
  if (epochId === 'epoch_10k' || epochId === 'EPOCH-PAPER-10K-20261014-001') {
    return CLOSED_TRADES_10K;
  }
  if (epochId === 'epoch_50k' || epochId === 'EPOCH-DEMO-50K-20261013') {
    return CLOSED_TRADES_50K;
  }
  if (epochId === 'epoch_100k' || epochId === 'EPOCH-MULTI-100K-20261014') {
    return CLOSED_TRADES_100K;
  }
  // For custom epochs, start clean with 0 historical trades
  return [];
}

/**
 * Validate custom paper capital input.
 * Bounds: ₹5,000 to ₹1,00,00,000 (1 Crore INR).
 */
export function validateCustomCapital(amount) {
  const num = Number(amount);
  if (isNaN(num) || !isFinite(num)) {
    return { valid: false, error: 'Please enter a valid numeric capital amount.' };
  }
  if (num < 5000) {
    return { valid: false, error: 'Minimum starting paper capital is ₹5,000 (statutory option margin floor).' };
  }
  if (num > 10000000) {
    return { valid: false, error: 'Maximum starting paper capital is ₹1,00,00,000 (INR 1 Crore).' };
  }
  return { valid: true, error: null, value: num };
}
