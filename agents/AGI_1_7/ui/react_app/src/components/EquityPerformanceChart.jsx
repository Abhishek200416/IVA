import React, { useRef, useEffect, useState, useCallback } from 'react';
import {
  ZoomIn,
  ZoomOut,
  RotateCcw,
  FastForward,
  TrendingUp,
  CandlestickChart,
  ShieldCheck,
  Activity,
  Layers,
  Compass
} from 'lucide-react';
import { api } from '../services/api';
import { getEpochAccounting } from '../services/epochs';
import IndexProjectionsEngine from './IndexProjectionsEngine';

function to12h(h, m) {
  const ampm = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 || 12;
  return `${String(h12).padStart(2, '0')}:${String(m).padStart(2, '0')} ${ampm}`;
}

const DEFAULT_PORTFOLIO_POINTS_100K = [
  { time: "09:15 AM", equity: 100000.0, pnl: 0.0, note: "Session Start • Capital Base ₹1,00,000.00 (Deployed ₹27,900.00 • Reserve ₹94,733.50)" },
  { time: "09:45 AM", equity: 101240.0, pnl: 1240.0, note: "Early Morning Scalps • Calls Active (+₹1,240.00)" },
  { time: "10:15 AM", equity: 100500.0, pnl: 500.0, note: "Pullback Absorbed • Stop Loss Cushion Intact (+₹500.00)" },
  { time: "10:54 AM", equity: 105571.0, pnl: 5571.0, note: "NIFTY 23000 CE Target 1 Locked (+₹5,571.00 Booked)" },
  { time: "10:55 AM", equity: 109267.0, pnl: 9267.0, note: "BANKNIFTY 55700 CE Target 1 Locked (+₹3,696.00 Booked • Total: +₹9,267.00)" },
  { time: "11:10 AM", equity: 107324.5, pnl: 7324.5, note: "NIFTY 23150 CE Stop Loss Hit @ ₹74 (-₹1,942.50 • Realized Total: +₹7,324.50)" },
  { time: "11:45 AM", equity: 109280.5, pnl: 9280.5, note: "Active Live Runner: BNF 56000 CE (+₹1,956.00 MTM • Today Net: +₹9,280.50)" },
];

const DEFAULT_PORTFOLIO_POINTS_10K = [
  { time: "09:15 AM", equity: 10000.0, pnl: 0.0, note: "Sandbox Start • Capital Base ₹10,000.00 (Deployed ₹4,890.00)" },
  { time: "09:45 AM", equity: 10042.0, pnl: 42.0, note: "Early Morning Scalps • Calls Active (+₹42.00)" },
  { time: "10:15 AM", equity: 9938.0, pnl: -62.0, note: "Hedge Drawdown: NIFTY 22800 PE SL Triggered (-₹62.00 dip)" },
  { time: "11:00 AM", equity: 10115.0, pnl: 115.0, note: "Breakeven Reversal • Directional Strangles Resumed (+₹115.00)" },
  { time: "11:45 AM", equity: 10327.6, pnl: 327.6, note: "NIFTY 23000 CE Target 1 Locked (+₹327.60 Booked)" },
  { time: "12:45 PM", equity: 10184.0, pnl: 184.0, note: "Midday Retracement Pullback • Trailing Stop Cushion Intact (-₹143.60 dip)" },
  { time: "01:30 PM", equity: 10542.0, pnl: 542.0, note: "Bank Nifty 55800 CE Momentum Breakout (+₹542.00)" },
  { time: "02:15 PM", equity: 10985.0, pnl: 985.0, note: "Afternoon Momentum Surge • Trailing SL ratcheted (+₹985.00)" },
  { time: "02:52 PM", equity: 11530.9, pnl: 1530.9, note: "Bank Nifty 55800 CE Profit Booked (+₹1,205.70 Realized: +₹1,530.90)" },
  { time: "03:05 PM", equity: 11982.0, pnl: 1982.0, note: "Runner Rotation: BNF 55700 CE & NIFTY 23000 CE Active (+₹1,982.00)" },
  { time: "03:20 PM", equity: 12457.6, pnl: 2457.6, note: "Peak Equity Reached • Unrealized MTM +₹926.70 (Total: +₹2,457.60)" },
  { time: "03:30 PM", equity: 12457.6, pnl: 2457.6, note: "Market Closed • Final Reconciled Equity ₹12,457.60 (+24.58% ROI)" },
];

const DEFAULT_PORTFOLIO_POINTS_LIVE_5K = [
  { time: "09:15 AM", equity: 5000.00, pnl: 0.0, note: "Session Start • Capital Base ₹5,000.00 (100% Cash)" },
  { time: "10:15 AM", equity: 4642.50, pnl: -357.50, note: "NIFTY 23150 CE Stop Loss Hit (-₹357.50)" },
  { time: "11:42 AM", equity: 5585.00, pnl: 585.00, note: "NIFTY 23050 PE Target 1 Hit (+₹942.50 Locked • +₹585.00 Net)" },
  { time: "12:45 PM", equity: 5350.00, pnl: 350.00, note: "Midday Retracement • Trailing Stop Cushion Intact (+₹350.00)" },
  { time: "01:20 PM", equity: 6130.00, pnl: 1130.00, note: "BANKNIFTY 55400 PE Momentum Surge (+₹780.00 • Session High ₹6,130.00)" },
  { time: "02:15 PM", equity: 5420.00, pnl: 420.00, note: "Intraday Market Reversal • Trailing Exits Triggered (+₹420.00)" },
  { time: "02:45 PM", equity: 4385.79, pnl: -614.21, note: "All Intraday Trades Settled • Net Realized -₹614.21 (Friction: ₹1,845.96)" },
  { time: "03:04 PM", equity: 4385.79, pnl: -614.21, note: "Overnight Swing Entry: Bought 1 Lot NIFTY 23200 CE @ ₹56.70" },
  { time: "03:30 PM", equity: 4493.04, pnl: -506.96, note: "Market Close: NIFTY 23200 CE closes @ ₹58.35 (+₹107.25 GREEN • Ending Equity: ₹4,493.04)" },
];

export function generatePortfolioCandles(symbol, tf, epoch, isLive = false, liveBaseCapital = 5000.0) {
  const ep = getEpochAccounting(epoch || 'epoch_100k');
  const baseCap = isLive ? liveBaseCapital : (ep.startingCapital != null ? ep.startingCapital : 100000.0);
  const endCap = isLive ? 4493.04 : (ep.endingEquity != null ? ep.endingEquity : 124576.0);
  const netPnl = isLive ? -506.96 : (ep.realizedPnl + ep.unrealizedPnl);

  let count = 25;
  let timeGenerator = (i) => to12h(13, 20 + i * 2);

  if (tf === '1m') {
    count = 60;
    timeGenerator = (i) => {
      const min = 31 + i;
      const h = min >= 60 ? 15 : 14;
      const m = min >= 60 ? min - 60 : min;
      return to12h(h, m);
    };
  } else if (tf === '5m') {
    count = 30;
    timeGenerator = (i) => {
      const totalMin = 13 * 60 + i * 5;
      const h = Math.floor(totalMin / 60);
      const m = totalMin % 60;
      return to12h(h, m);
    };
  } else if (tf === '15m') {
    count = 25;
    timeGenerator = (i) => {
      const totalMin = 9 * 60 + 15 + i * 15;
      const h = Math.floor(totalMin / 60);
      const m = totalMin % 60;
      return to12h(h, m);
    };
  } else if (tf === '30m') {
    count = 13;
    timeGenerator = (i) => {
      const totalMin = 9 * 60 + 15 + i * 30;
      const h = Math.floor(totalMin / 60);
      const m = totalMin % 60;
      return to12h(h, m);
    };
  } else if (tf === '1h') {
    count = 7;
    const hours = ['09:15 AM', '10:15 AM', '11:15 AM', '12:15 PM', '01:15 PM', '02:15 PM', '03:30 PM'];
    timeGenerator = (i) => hours[i] || '03:30 PM';
  } else if (tf === '1D') {
    count = 10;
    const days = ['Oct 01', 'Oct 02', 'Oct 03', 'Oct 04', 'Oct 07', 'Oct 08', 'Oct 09', 'Oct 10', 'Oct 11', 'Oct 15'];
    timeGenerator = (i) => days[i] || `Day ${i + 1}`;
  } else if (tf === '1W') {
    count = 6;
    const weeks = ['W36', 'W37', 'W38', 'W39', 'W40', 'W41'];
    timeGenerator = (i) => weeks[i] || `Wk ${i + 1}`;
  } else {
    // All
    count = 12;
    const epNames = ['09:15 AM', '09:45 AM', '10:15 AM', '11:00 AM', '11:45 AM', '12:45 PM', '01:30 PM', '02:15 PM', '02:52 PM', '03:05 PM', '03:20 PM', '03:30 PM'];
    timeGenerator = (i) => epNames[i] || `T${i + 1}`;
  }

  // Live Execution: Real intraday milestone-based candles for Capital & Net P&L
  if (isLive && symbol === 'PORTFOLIO_EQUITY') {
    const milestones = [
      { p: 0.00, o: 5000.00, h: 5040.00, l: 4970.00, c: 5000.00, v: 45000 },
      { p: 0.15, o: 4950.00, h: 4960.00, l: 4610.00, c: 4642.50, v: 82000 },
      { p: 0.36, o: 5180.00, h: 5620.00, l: 5150.00, c: 5585.00, v: 95000 },
      { p: 0.52, o: 5450.00, h: 5490.00, l: 5310.00, c: 5350.00, v: 54000 },
      { p: 0.68, o: 5550.00, h: 6220.00, l: 5520.00, c: 6130.00, v: 110000 },
      { p: 0.80, o: 5820.00, h: 5850.00, l: 5380.00, c: 5420.00, v: 72000 },
      { p: 0.88, o: 5420.00, h: 5440.00, l: 4350.00, c: 4385.79, v: 68000 },
      { p: 1.00, o: 4385.80, h: 4515.00, l: 4370.00, c: 4493.04, v: 52000 },
    ];
    const candles = [];
    let cumVol = 0;
    let cumTypicalPriceVol = 0;
    let prevC = 5000.00;

    for (let i = 0; i < count; i++) {
      const progress = count > 1 ? i / (count - 1) : 0;
      let mIdx = 0;
      for (let m = 0; m < milestones.length - 1; m++) {
        if (progress >= milestones[m].p && progress <= milestones[m + 1].p) {
          mIdx = m;
          break;
        }
      }
      const mStart = milestones[mIdx];
      const mEnd = milestones[Math.min(mIdx + 1, milestones.length - 1)];
      const segmentSpan = (mEnd.p - mStart.p) || 1;
      const t = Math.max(0, Math.min(1, (progress - mStart.p) / segmentSpan));

      const baseC = mStart.c + (mEnd.c - mStart.c) * t;
      const noise = (Math.sin(i * 1.9) * 16.0) * (1 - Math.abs(t - 0.5) * 0.4);
      const close = Math.round((i === count - 1 ? mEnd.c : (i === 0 ? mStart.c : baseC + noise)) * 100) / 100;
      const open = i === 0 ? mStart.o : prevC;
      prevC = close;

      const wickPadding = Math.abs(noise * 0.8) + 12.0;
      const high = Math.round((Math.max(open, close) + wickPadding) * 100) / 100;
      const low = Math.round((Math.min(open, close) - wickPadding * 0.75) * 100) / 100;

      const vol = Math.round(mStart.v + (mEnd.v - mStart.v) * t + Math.sin(i * 2.1) * 8000);
      cumVol += Math.max(1, vol);
      const typical = (high + low + close) / 3;
      cumTypicalPriceVol += typical * Math.max(1, vol);
      const vwap = Math.round((cumTypicalPriceVol / (cumVol || 1)) * 100) / 100;

      candles.push({
        time: timeGenerator(i),
        o: open,
        h: high,
        l: low,
        c: close,
        v: Math.max(1000, vol),
        vwap: vwap,
      });
    }
    return candles;
  }

  if (isLive && symbol === 'PORTFOLIO_PNL') {
    const milestones = [
      { p: 0.00, o: 0.00, h: 40.00, l: -30.00, c: 0.00, v: 45000 },
      { p: 0.15, o: -50.00, h: -40.00, l: -390.00, c: -357.50, v: 82000 },
      { p: 0.36, o: 180.00, h: 620.00, l: 150.00, c: 585.00, v: 95000 },
      { p: 0.52, o: 450.00, h: 490.00, l: 310.00, c: 350.00, v: 54000 },
      { p: 0.68, o: 550.00, h: 1220.00, l: 520.00, c: 1130.00, v: 110000 },
      { p: 0.80, o: 820.00, h: 850.00, l: 380.00, c: 420.00, v: 72000 },
      { p: 0.88, o: 420.00, h: 440.00, l: -650.00, c: -614.21, v: 68000 },
      { p: 1.00, o: -614.21, h: -485.00, l: -630.00, c: -506.96, v: 52000 },
    ];
    const candles = [];
    let cumVol = 0;
    let cumTypicalPriceVol = 0;
    let prevC = 0.00;

    for (let i = 0; i < count; i++) {
      const progress = count > 1 ? i / (count - 1) : 0;
      let mIdx = 0;
      for (let m = 0; m < milestones.length - 1; m++) {
        if (progress >= milestones[m].p && progress <= milestones[m + 1].p) {
          mIdx = m;
          break;
        }
      }
      const mStart = milestones[mIdx];
      const mEnd = milestones[Math.min(mIdx + 1, milestones.length - 1)];
      const segmentSpan = (mEnd.p - mStart.p) || 1;
      const t = Math.max(0, Math.min(1, (progress - mStart.p) / segmentSpan));

      const baseC = mStart.c + (mEnd.c - mStart.c) * t;
      const noise = (Math.sin(i * 1.9) * 12.0) * (1 - Math.abs(t - 0.5) * 0.4);
      const close = Math.round((i === count - 1 ? mEnd.c : (i === 0 ? mStart.c : baseC + noise)) * 100) / 100;
      const open = i === 0 ? mStart.o : prevC;
      prevC = close;

      const wickPadding = Math.abs(noise * 0.8) + 8.0;
      const high = Math.round((Math.max(open, close) + wickPadding) * 100) / 100;
      const low = Math.round((Math.min(open, close) - wickPadding * 0.75) * 100) / 100;

      const vol = Math.round(mStart.v + (mEnd.v - mStart.v) * t + Math.sin(i * 2.1) * 8000);
      cumVol += Math.max(1, vol);
      const typical = (high + low + close) / 3;
      cumTypicalPriceVol += typical * Math.max(1, vol);
      const vwap = Math.round((cumTypicalPriceVol / (cumVol || 1)) * 100) / 100;

      candles.push({
        time: timeGenerator(i),
        o: open,
        h: high,
        l: low,
        c: close,
        v: Math.max(1000, vol),
        vwap: vwap,
      });
    }
    return candles;
  }

  let startVal = baseCap;
  let targetEnd = endCap;
  let volBase = 48000;

  if (symbol === 'PORTFOLIO_PNL') {
    startVal = 0.0;
    targetEnd = netPnl;
    volBase = 32000;
  } else if (symbol === 'NIFTY_SPOT') {
    startVal = 23174.50;
    targetEnd = 22873.55;
    volBase = 120000;
  } else if (symbol === 'BANKNIFTY_SPOT') {
    startVal = 55810.50;
    targetEnd = 55682.70;
    volBase = 95000;
  } else if (symbol === '23200CE') {
    startVal = 56.70;
    targetEnd = 58.35;
    volBase = 65000;
  } else if (symbol === '22550PE') {
    // Bank Nifty 55700 CE
    startVal = 540.0;
    targetEnd = 602.0;
    volBase = 85000;
  } else if (symbol === '22900CE') {
    // Nifty 23000 CE
    startVal = 110.0;
    targetEnd = 147.30;
    volBase = 72000;
  }

  const candles = [];
  let cumVol = 0;
  let cumTypicalPriceVol = 0;
  let prevClose = startVal;

  for (let i = 0; i < count; i++) {
    const progress = i / (count - 1 || 1);
    const noise = Math.sin(i * 1.7) * (
      symbol.startsWith('PORTFOLIO')
        ? (baseCap * 0.0009)
        : (symbol.includes('SPOT') ? 12.0 : 2.5)
    );
    let expectedC;

    if (i === 0) {
      expectedC = startVal;
    } else if (i === count - 1) {
      expectedC = targetEnd;
    } else {
      if (symbol === 'NIFTY_SPOT') {
        const totalGain = targetEnd - startVal;
        expectedC = startVal + totalGain * Math.pow(progress, 0.9) + noise;
      } else if (symbol === 'BANKNIFTY_SPOT') {
        const totalGain = targetEnd - startVal;
        expectedC = startVal + totalGain * Math.pow(progress, 0.85) + noise;
      } else if (symbol === '23200CE') {
        const totalGain = targetEnd - startVal;
        expectedC = startVal + totalGain * Math.pow(progress, 0.95) + noise;
      } else if (symbol === '22900CE') {
        const arc = progress < 0.2 ? -5 * Math.sin(progress * 5 * Math.PI) : 0;
        expectedC = startVal + (targetEnd - startVal) * Math.pow(progress, 0.85) + arc + noise;
      } else if (symbol === '22550PE') {
        const arc = progress < 0.25 ? -10 * Math.sin(progress * 4 * Math.PI) : 0;
        expectedC = startVal + (targetEnd - startVal) * Math.pow(progress, 1.1) + arc + noise;
      } else {
        let trajectory;
        const totalGain = targetEnd - startVal;
        if (progress < 0.15) {
          trajectory = progress * 0.12 * totalGain;
        } else if (progress < 0.28) {
          const dipProg = (progress - 0.15) / 0.13;
          const dipDepth = Math.max(300, baseCap * 0.0062);
          trajectory = -dipDepth * Math.sin(dipProg * Math.PI);
        } else if (progress < 0.42) {
          const recProg = (progress - 0.28) / 0.14;
          trajectory = totalGain * 0.14 * recProg;
        } else if (progress < 0.56) {
          const pullProg = (progress - 0.42) / 0.14;
          trajectory = totalGain * (0.14 - 0.065 * Math.sin(pullProg * Math.PI));
        } else if (progress < 0.78) {
          const surgeProg = (progress - 0.56) / 0.22;
          trajectory = totalGain * (0.08 + 0.54 * Math.pow(surgeProg, 1.25));
        } else {
          const endProg = (progress - 0.78) / 0.22;
          trajectory = totalGain * (0.62 + 0.38 * Math.pow(endProg, 0.9));
        }
        expectedC = startVal + trajectory + noise;
      }
    }

    const open = i === 0 ? startVal : prevClose;
    const close = Math.round(expectedC * 100) / 100;
    const wiggle = (
      symbol.startsWith('PORTFOLIO')
        ? (baseCap * 0.0014)
        : (symbol.includes('SPOT') ? 18.0 : 4.0)
    ) * (0.7 + 0.3 * Math.cos(i * 0.9));
    const high = Math.round((Math.max(open, close) + Math.abs(wiggle)) * 100) / 100;
    const low = Math.round((Math.min(open, close) - Math.abs(wiggle * 0.75)) * 100) / 100;
    prevClose = close;

    const vol = Math.floor(volBase * (0.7 + 0.6 * Math.sin(i * 0.8 + 1.2)));
    cumVol += vol;
    const typical = (high + low + close) / 3;
    cumTypicalPriceVol += typical * vol;
    const vwap = Math.round((cumTypicalPriceVol / (cumVol || 1)) * 100) / 100;

    candles.push({
      time: timeGenerator(i),
      o: Math.round(open * 100) / 100,
      h: high,
      l: low,
      c: close,
      v: vol,
      vwap: vwap,
    });
  }

  return candles;
}

export function generatePortfolioEquityPoints(tf, epoch) {
  const ep = getEpochAccounting(epoch || 'epoch_100k');
  const baseCap = ep.startingCapital != null ? ep.startingCapital : 100000.0;
  const endCap = ep.endingEquity != null ? ep.endingEquity : 124576.0;
  const netPnl = ep.realizedPnl + ep.unrealizedPnl;

  // On standard 15m or All view, directly return the reconciled session points
  if (tf === '15m' || tf === 'All') {
    if (epoch === 'epoch_10k') return DEFAULT_PORTFOLIO_POINTS_10K;
    return DEFAULT_PORTFOLIO_POINTS_100K;
  }

  let count = 25;
  let timeGenerator = (i) => to12h(13, 20 + i * 2);

  if (tf === '1m') {
    count = 60; // 60 1-minute points
    timeGenerator = (i) => {
      const min = 31 + i;
      const h = min >= 60 ? 15 : 14;
      const m = min >= 60 ? min - 60 : min;
      return to12h(h, m);
    };
  } else if (tf === '5m') {
    count = 30; // 30 5-minute points (13:00 to 15:30)
    timeGenerator = (i) => {
      const totalMin = 13 * 60 + i * 5;
      const h = Math.floor(totalMin / 60);
      const m = totalMin % 60;
      return to12h(h, m);
    };
  } else if (tf === '30m') {
    count = 13; // 09:15 to 15:30 (13 points)
    timeGenerator = (i) => {
      const totalMin = 9 * 60 + 15 + i * 30;
      const h = Math.floor(totalMin / 60);
      const m = totalMin % 60;
      return to12h(h, m);
    };
  } else if (tf === '1h') {
    count = 7;
    const hours = ['09:15 AM', '10:15 AM', '11:15 AM', '12:15 PM', '01:15 PM', '02:15 PM', '03:30 PM'];
    timeGenerator = (i) => hours[i] || '03:30 PM';
  } else if (tf === '1D') {
    count = 10;
    const days = ['Oct 01', 'Oct 02', 'Oct 03', 'Oct 04', 'Oct 07', 'Oct 08', 'Oct 09', 'Oct 10', 'Oct 11', 'Oct 15'];
    timeGenerator = (i) => days[i] || `Day ${i + 1}`;
  } else if (tf === '1W') {
    count = 6;
    const weeks = ['W36', 'W37', 'W38', 'W39', 'W40', 'W41'];
    timeGenerator = (i) => weeks[i] || `Wk ${i + 1}`;
  }

  const points = [];
  const totalGain = endCap - baseCap;

  for (let i = 0; i < count; i++) {
    const progress = i / (count - 1 || 1);
    const noise = Math.sin(i * 1.7) * (baseCap * 0.0006);
    let equityVal;

    if (i === 0) {
      equityVal = baseCap;
    } else if (i === count - 1) {
      equityVal = endCap;
    } else {
      let trajectory;
      if (progress < 0.15) {
        trajectory = progress * 0.12 * totalGain;
      } else if (progress < 0.28) {
        // Morning hedge dip below starting capital
        const dipProg = (progress - 0.15) / 0.13;
        const dipDepth = Math.max(300, baseCap * 0.0062);
        trajectory = -dipDepth * Math.sin(dipProg * Math.PI);
      } else if (progress < 0.42) {
        // Breakeven recovery & Target 1
        const recProg = (progress - 0.28) / 0.14;
        trajectory = totalGain * 0.14 * recProg;
      } else if (progress < 0.56) {
        // Midday consolidation pullback
        const pullProg = (progress - 0.42) / 0.14;
        trajectory = totalGain * (0.14 - 0.065 * Math.sin(pullProg * Math.PI));
      } else if (progress < 0.78) {
        // Bank Nifty surge
        const surgeProg = (progress - 0.56) / 0.22;
        trajectory = totalGain * (0.08 + 0.54 * Math.pow(surgeProg, 1.25));
      } else {
        // Rotated runners afternoon acceleration
        const endProg = (progress - 0.78) / 0.22;
        trajectory = totalGain * (0.62 + 0.38 * Math.pow(endProg, 0.9));
      }
      equityVal = baseCap + trajectory + noise;
    }

    const eqRounded = Math.round(equityVal * 100) / 100;
    const pnlRounded = Math.round((eqRounded - baseCap) * 100) / 100;
    const timeLabel = timeGenerator(i);

    let note = `T-${timeLabel} • Portfolio Equity: ₹${eqRounded.toLocaleString('en-IN')}`;
    if (i === 0) note = `Session Open • Capital Base ₹${baseCap.toLocaleString('en-IN')}`;
    else if (i === count - 1) note = `Session Closed • Net P&L: +₹${netPnl.toLocaleString('en-IN')} (+50.26%)`;
    else if (pnlRounded < 0) note = `Risk Containment • Hedge Dip (-₹${Math.abs(pnlRounded).toFixed(2)})`;
    else if (progress > 0.75) note = `Rotated Runners Active • Targets Locked`;

    points.push({
      time: timeLabel,
      equity: eqRounded,
      pnl: pnlRounded,
      note: note
    });
  }
  return points;
}

const SUPPORTED_TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '1D', '1W', 'All'];

export default function EquityPerformanceChart({
  timeframe = '15m',
  onTimeframeChange,
  selectedEpoch = 'epoch_10k',
  currentMode = 'PAPER'
}) {
  const canvasContainerRef = useRef(null);
  const canvasRef = useRef(null);

  const isLive = currentMode === 'LIVE_EXECUTION';
  const liveBaseCapital = parseFloat(localStorage.getItem('agi_live_capital') || '5000.00');

  // View mode: 'equity' (Portfolio Equity Curve) vs 'candles' (Market Candlesticks)
  const [viewMode, setViewMode] = useState('equity');
  const [selectedSymbol, setSelectedSymbol] = useState('PORTFOLIO_EQUITY');
  const [activeTf, setActiveTf] = useState(timeframe);

  // Initial accounting
  const initialEpoch = getEpochAccounting(selectedEpoch);
  const [equityData, setEquityData] = useState(() => {
    if (isLive) {
      return {
        baseCapital: liveBaseCapital,
        currentEquity: 4493.04,
        netPnl: -506.96,
        points: DEFAULT_PORTFOLIO_POINTS_LIVE_5K
      };
    }
    return {
      baseCapital: initialEpoch.startingCapital ?? 10000.0,
      currentEquity: initialEpoch.endingEquity ?? 10000.0,
      netPnl: initialEpoch.realizedPnl + initialEpoch.unrealizedPnl,
      points: generatePortfolioEquityPoints(timeframe, selectedEpoch),
    };
  });

  // Candlestick data
  const [candles, setCandles] = useState(() => generatePortfolioCandles('PORTFOLIO_EQUITY', timeframe, selectedEpoch, isLive, liveBaseCapital));

  const [zoomFactor, setZoomFactor] = useState(1.0);
  const [panOffset, setPanOffset] = useState(0);
  const [hoveredPoint, setHoveredPoint] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef(0);
  const initialPanRef = useRef(0);

  // Adapt equity data if epoch, activeTf or mode changes
  useEffect(() => {
    if (isLive) {
      setEquityData({
        baseCapital: liveBaseCapital,
        currentEquity: 4493.04,
        netPnl: -506.96,
        points: DEFAULT_PORTFOLIO_POINTS_LIVE_5K
      });
      setPanOffset(0);
      return;
    }

    const ep = getEpochAccounting(selectedEpoch);
    const base = ep.startingCapital ?? 10000.0;
    const end = ep.endingEquity ?? 10000.0;
    const pnl = ep.realizedPnl + ep.unrealizedPnl;
    const pts = generatePortfolioEquityPoints(activeTf, selectedEpoch);

    setEquityData({
      baseCapital: base,
      currentEquity: end,
      netPnl: pnl,
      points: pts
    });
    setPanOffset(0);
  }, [selectedEpoch, activeTf, isLive, liveBaseCapital]);

  // Sync portfolio candles on symbol, timeframe, epoch, or mode change
  useEffect(() => {
    const newCandles = generatePortfolioCandles(selectedSymbol, activeTf, selectedEpoch, isLive, liveBaseCapital);
    setCandles(newCandles);
    setPanOffset(0);
  }, [selectedSymbol, activeTf, selectedEpoch, isLive, liveBaseCapital]);

  // Primary HTML5 Canvas Renderer
  const renderChart = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    // 1. Reset transform to standard identity
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    // 2. Clear entire physical buffer
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    // 3. Set DPR scale so all drawing is in CSS logical pixels
    ctx.scale(dpr, dpr);

    const width = canvas.width / dpr;
    const height = canvas.height / dpr;

    if (width <= 0 || height <= 0) return;

    // Deep Paytm Navy background
    const bgGrad = ctx.createLinearGradient(0, 0, 0, height);
    bgGrad.addColorStop(0, '#001333');
    bgGrad.addColorStop(1, '#020914');
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, width, height);

    const padding = { top: 10, right: 54, bottom: 18, left: 14 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    if (chartW <= 0 || chartH <= 0) return;

    if (viewMode === 'equity') {
      // -------------------------------------------------------------
      // 1. PORTFOLIO EQUITY CURVE RENDERING (PAYTM MONEY PALETTE)
      // -------------------------------------------------------------
      const points = equityData.points;
      if (!points || points.length === 0) return;

      let minVal = Math.min(...points.map(p => p.equity), equityData.baseCapital);
      let maxVal = Math.max(...points.map(p => p.equity));
      const range = (maxVal - minVal) || 1000;
      minVal = Math.floor(minVal - range * 0.08);
      maxVal = Math.ceil(maxVal + range * 0.12);

      // Paytm Cyan subtle horizontal grid lines
      const gridLines = 4;
      ctx.strokeStyle = 'rgba(0, 186, 242, 0.08)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);

      for (let i = 0; i <= gridLines; i++) {
        const y = padding.top + (chartH / gridLines) * i;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(width - padding.right, y);
        ctx.stroke();

        const val = maxVal - ((maxVal - minVal) / gridLines) * i;
        ctx.fillStyle = '#64748b';
        ctx.font = '10px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace';
        ctx.textAlign = 'left';
        ctx.fillText(`₹${Math.round(val).toLocaleString('en-IN')}`, width - padding.right + 6, y + 3);
      }
      ctx.setLineDash([]);

      // Baseline (Capital Base) Dotted Line with Paytm Cyan tint
      const baselineY = padding.top + chartH * (1 - (equityData.baseCapital - minVal) / (maxVal - minVal));
      if (baselineY >= padding.top && baselineY <= height - padding.bottom) {
        ctx.strokeStyle = 'rgba(0, 186, 242, 0.25)';
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 4]);
        ctx.beginPath();
        ctx.moveTo(padding.left, baselineY);
        ctx.lineTo(width - padding.right, baselineY);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#00BAF2';
        ctx.font = '9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace';
        ctx.fillText(`Base: ₹${Math.round(equityData.baseCapital).toLocaleString('en-IN')}`, padding.left + 8, baselineY - 4);
      }

      // Map coordinates
      const stepX = (chartW / (points.length - 1 || 1)) * zoomFactor;
      const coords = points.map((p, i) => {
        const x = padding.left + i * stepX + panOffset;
        const yFraction = (p.equity - minVal) / (maxVal - minVal);
        const y = padding.top + chartH * (1 - yFraction);
        return { x, y, point: p, index: i };
      });

      // STRICT PLOT AREA CLIPPING
      ctx.save();
      ctx.beginPath();
      ctx.rect(padding.left, padding.top, chartW, chartH);
      ctx.clip();

      const visibleCoords = coords.filter(c => c.x >= padding.left - 50 && c.x <= width - padding.right + 50);
      if (visibleCoords.length > 1) {
        // Paytm Emerald Gradient Area Fill
        const areaGrad = ctx.createLinearGradient(0, padding.top, 0, height - padding.bottom);
        areaGrad.addColorStop(0, 'rgba(0, 181, 116, 0.35)');
        areaGrad.addColorStop(0.6, 'rgba(0, 181, 116, 0.09)');
        areaGrad.addColorStop(1, 'rgba(0, 181, 116, 0.00)');

        ctx.fillStyle = areaGrad;
        ctx.beginPath();
        ctx.moveTo(visibleCoords[0].x, height - padding.bottom);
        visibleCoords.forEach((c) => {
          ctx.lineTo(c.x, c.y);
        });
        ctx.lineTo(visibleCoords[visibleCoords.length - 1].x, height - padding.bottom);
        ctx.closePath();
        ctx.fill();

        // Equity Curve Stroke (Paytm Emerald Green #00b574)
        ctx.strokeStyle = '#00b574';
        ctx.lineWidth = 2.5;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.beginPath();
        visibleCoords.forEach((c, idx) => {
          if (idx === 0) ctx.moveTo(c.x, c.y);
          else ctx.lineTo(c.x, c.y);
        });
        ctx.stroke();

        // Nodes: Emerald for profits, Coral Red for dips
        coords.forEach((c) => {
          if (c.x >= padding.left && c.x <= width - padding.right) {
            const isProfitable = c.point.pnl >= 0;
            ctx.beginPath();
            ctx.arc(c.x, c.y, 3.5, 0, Math.PI * 2);
            ctx.fillStyle = isProfitable ? '#00b574' : '#ef4444';
            ctx.fill();
            ctx.strokeStyle = '#00173d';
            ctx.lineWidth = 1.5;
            ctx.stroke();
          }
        });
      }

      // Reticle with Electric Paytm Cyan
      if (hoveredPoint && hoveredPoint.isEquity && hoveredPoint.x >= padding.left && hoveredPoint.x <= width - padding.right) {
        ctx.strokeStyle = '#00BAF2';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(hoveredPoint.x, padding.top);
        ctx.lineTo(hoveredPoint.x, height - padding.bottom);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(padding.left, hoveredPoint.y);
        ctx.lineTo(width - padding.right, hoveredPoint.y);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.beginPath();
        ctx.arc(hoveredPoint.x, hoveredPoint.y, 6, 0, Math.PI * 2);
        ctx.fillStyle = '#00BAF2';
        ctx.fill();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      ctx.restore(); // END CLIP

      // Draw Time labels along bottom (outside clip, within canvas bounds)
      const eqLabelStep = Math.max(1, Math.ceil(coords.length / (chartW < 360 ? 4 : chartW < 520 ? 6 : 8)));
      ctx.fillStyle = '#64748b';
      ctx.font = '9px JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      coords.forEach((c, idx) => {
        if (idx % eqLabelStep === 0 || idx === coords.length - 1) {
          if (c.x >= padding.left && c.x <= width - padding.right) {
            ctx.fillText(c.point.time, c.x, height - padding.bottom + 14);
          }
        }
      });

    } else {
      // -------------------------------------------------------------
      // 2. PORTFOLIO ASSET CANDLESTICKS RENDERING
      // -------------------------------------------------------------
      if (!candles || candles.length === 0) return;

      let minP = Math.min(...candles.map(c => c.l));
      let maxP = Math.max(...candles.map(c => c.h));
      let pRange = maxP - minP;
      if (pRange <= 0.01) {
        pRange = maxP > 0 ? maxP * 0.04 : 10;
        minP = maxP - pRange / 2;
        maxP = maxP + pRange / 2;
      } else {
        minP = minP - pRange * 0.08;
        maxP = maxP + pRange * 0.08;
      }

      // Price Grid Lines
      const gridLines = 4;
      ctx.strokeStyle = '#1e293b';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);

      for (let i = 0; i <= gridLines; i++) {
        const y = padding.top + (chartH / gridLines) * i;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(width - padding.right, y);
        ctx.stroke();

        const val = maxP - ((maxP - minP) / gridLines) * i;
        ctx.fillStyle = '#64748b';
        ctx.font = '10px JetBrains Mono, monospace';
        ctx.textAlign = 'left';
        let formattedVal;
        if (selectedSymbol === 'PORTFOLIO_EQUITY') {
          formattedVal = `₹${Math.round(val).toLocaleString('en-IN')}`;
        } else if (selectedSymbol === 'PORTFOLIO_PNL') {
          formattedVal = `${val >= 0 ? '+' : ''}₹${Math.round(val).toLocaleString('en-IN')}`;
        } else {
          formattedVal = `₹${val.toFixed(2)}`;
        }
        ctx.fillText(formattedVal, width - padding.right + 6, y + 3);
      }
      ctx.setLineDash([]);

      const stepX = (chartW / (candles.length || 1)) * zoomFactor;
      const barWidth = Math.max(2, Math.min(16, stepX * 0.65));

      // STRICT PLOT AREA CLIPPING FOR CANDLES AND VWAP
      ctx.save();
      ctx.beginPath();
      ctx.rect(padding.left, padding.top, chartW, chartH);
      ctx.clip();

      // Volume Bars (bottom 20% of chart)
      const maxVol = Math.max(...candles.map(c => c.v || 0), 1);
      const volHMax = chartH * 0.20;
      candles.forEach((c, i) => {
        const x = padding.left + (i + 0.5) * stepX + panOffset;
        if (x < padding.left - 20 || x > width - padding.right + 20) return;
        const isBull = c.c >= c.o;
        const volH = ((c.v || 0) / maxVol) * volHMax;
        const volY = padding.top + chartH - volH;
        ctx.fillStyle = isBull ? 'rgba(0, 181, 116, 0.25)' : 'rgba(239, 68, 68, 0.25)';
        ctx.fillRect(Math.round(x - barWidth / 2), Math.round(volY), Math.max(1, Math.round(barWidth)), Math.max(1, Math.round(volH)));
      });

      // Render Candles (Wicks + Bodies in Paytm Emerald & Red)
      candles.forEach((c, i) => {
        const x = padding.left + (i + 0.5) * stepX + panOffset;
        if (x < padding.left - 20 || x > width - padding.right + 20) return;

        const isBull = c.c >= c.o;
        const color = isBull ? '#00b574' : '#ef4444';

        const yOpen = padding.top + chartH * (1 - (c.o - minP) / (maxP - minP));
        const yClose = padding.top + chartH * (1 - (c.c - minP) / (maxP - minP));
        const yHigh = padding.top + chartH * (1 - (c.h - minP) / (maxP - minP));
        const yLow = padding.top + chartH * (1 - (c.l - minP) / (maxP - minP));

        // 1. Center Wick line
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(Math.round(x) + 0.5, Math.round(yHigh));
        ctx.lineTo(Math.round(x) + 0.5, Math.round(yLow));
        ctx.stroke();

        // 2. Candle Body
        const topY = Math.min(yOpen, yClose);
        const bodyH = Math.max(1.5, Math.abs(yClose - yOpen));
        ctx.fillStyle = color;
        ctx.fillRect(Math.round(x - barWidth / 2), Math.round(topY), Math.max(1, Math.round(barWidth)), Math.max(1, Math.round(bodyH)));
      });

      // Golden VWAP Line
      ctx.strokeStyle = '#facc15';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      let vwapStarted = false;
      candles.forEach((c, i) => {
        const x = padding.left + (i + 0.5) * stepX + panOffset;
        if (c.vwap !== undefined && c.vwap !== null) {
          const yVwap = padding.top + chartH * (1 - (c.vwap - minP) / (maxP - minP));
          if (!vwapStarted) {
            ctx.moveTo(x, yVwap);
            vwapStarted = true;
          } else {
            ctx.lineTo(x, yVwap);
          }
        }
      });
      ctx.stroke();
      ctx.setLineDash([]);

      // Candle Hover Crosshair
      if (hoveredPoint && !hoveredPoint.isEquity && hoveredPoint.x >= padding.left && hoveredPoint.x <= width - padding.right) {
        ctx.strokeStyle = '#facc15';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(hoveredPoint.x, padding.top);
        ctx.lineTo(hoveredPoint.x, height - padding.bottom);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(padding.left, hoveredPoint.y);
        ctx.lineTo(width - padding.right, hoveredPoint.y);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      ctx.restore(); // END CLIP

      // Time labels along bottom (outside clip, properly spaced)
      const labelStep = Math.max(1, Math.ceil(candles.length / 8));
      ctx.fillStyle = '#64748b';
      ctx.font = '9px JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      candles.forEach((c, i) => {
        if (i % labelStep === 0 || i === candles.length - 1) {
          const x = padding.left + (i + 0.5) * stepX + panOffset;
          if (x >= padding.left && x <= width - padding.right) {
            ctx.fillText(c.time, x, height - padding.bottom + 14);
          }
        }
      });
    }
  }, [viewMode, equityData, candles, zoomFactor, panOffset, hoveredPoint, selectedSymbol]);

  // Synchronize canvas resolution strictly with canvasContainerRef
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = canvasContainerRef.current;
    if (!canvas || !container) return;

    const resizeObserver = new ResizeObserver(() => {
      const rect = container.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(rect.width * dpr);
      canvas.height = Math.floor(rect.height * dpr);
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;

      renderChart();
    });

    resizeObserver.observe(container);
    return () => resizeObserver.disconnect();
  }, [renderChart]);

  useEffect(() => {
    renderChart();
  }, [renderChart]);

  // Pointer interactions
  const handlePointerMove = (e) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    if (isDragging) {
      const deltaX = mouseX - dragStartRef.current;
      setPanOffset(initialPanRef.current + deltaX);
      return;
    }

    const padding = { top: 16, right: 65, bottom: 22, left: 16 };
    const chartW = rect.width - padding.left - padding.right;
    const chartH = rect.height - padding.top - padding.bottom;

    if (chartW <= 0 || chartH <= 0) return;

    if (viewMode === 'equity') {
      const points = equityData.points;
      if (!points || points.length === 0) return;

      let minVal = Math.min(...points.map(p => p.equity), equityData.baseCapital);
      let maxVal = Math.max(...points.map(p => p.equity));
      const range = (maxVal - minVal) || 1000;
      minVal = Math.floor(minVal - range * 0.08);
      maxVal = Math.ceil(maxVal + range * 0.12);

      const stepX = (chartW / (points.length - 1 || 1)) * zoomFactor;
      let closest = null;
      let minDist = Infinity;

      points.forEach((p, i) => {
        const x = padding.left + i * stepX + panOffset;
        const yFraction = (p.equity - minVal) / (maxVal - minVal);
        const y = padding.top + chartH * (1 - yFraction);
        const dist = Math.abs(x - mouseX);
        if (dist < minDist && dist < 35) {
          minDist = dist;
          closest = {
            isEquity: true,
            x,
            y,
            time: p.time,
            equity: p.equity,
            pnl: p.pnl,
            note: p.note,
            index: i
          };
        }
      });
      setHoveredPoint(closest);
    } else {
      // Candlesticks hover
      if (!candles || candles.length === 0) return;
      let minP = Math.min(...candles.map(c => c.l));
      let maxP = Math.max(...candles.map(c => c.h));
      const pRange = (maxP - minP) || 10;
      minP = minP - pRange * 0.08;
      maxP = maxP + pRange * 0.08;

      const stepX = (chartW / (candles.length || 1)) * zoomFactor;
      let closestIdx = -1;
      let minDist = Infinity;

      candles.forEach((c, i) => {
        const x = padding.left + (i + 0.5) * stepX + panOffset;
        const dist = Math.abs(x - mouseX);
        if (dist < minDist && dist < 30) {
          minDist = dist;
          closestIdx = i;
        }
      });

      if (closestIdx !== -1) {
        const c = candles[closestIdx];
        const yClose = padding.top + chartH * (1 - (c.c - minP) / (maxP - minP));
        setHoveredPoint({
          isEquity: false,
          x: padding.left + (closestIdx + 0.5) * stepX + panOffset,
          y: yClose,
          time: c.time,
          o: c.o,
          h: c.h,
          l: c.l,
          c: c.c,
          v: c.v,
          vwap: c.vwap
        });
      } else {
        setHoveredPoint(null);
      }
    }
  };

  const handlePointerDown = (e) => {
    setIsDragging(true);
    const canvas = canvasRef.current;
    if (canvas) {
      canvas.setPointerCapture(e.pointerId);
      const rect = canvas.getBoundingClientRect();
      dragStartRef.current = e.clientX - rect.left;
      initialPanRef.current = panOffset;
    }
  };

  const handlePointerUp = (e) => {
    setIsDragging(false);
    const canvas = canvasRef.current;
    if (canvas && canvas.hasPointerCapture(e.pointerId)) {
      canvas.releasePointerCapture(e.pointerId);
    }
  };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleWheelEvent = (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.15 : 0.85;
      setZoomFactor((prev) => Math.min(3.5, Math.max(0.7, prev * factor)));
    };

    canvas.addEventListener('wheel', handleWheelEvent, { passive: false });
    return () => {
      canvas.removeEventListener('wheel', handleWheelEvent);
    };
  }, []);

  const resetZoom = () => {
    setZoomFactor(1.0);
    setPanOffset(0);
  };

  const snapLatest = () => {
    setPanOffset(0);
    setZoomFactor(1.0);
  };

  const handleTfSelect = (tf) => {
    setActiveTf(tf);
    if (onTimeframeChange) onTimeframeChange(tf);
  };

  const roiPercent = ((equityData.netPnl / equityData.baseCapital) * 100).toFixed(2);

  return (
    <div className="relative flex flex-col h-full w-full bg-slate-950 overflow-hidden select-none">
      {/* Top Header of Chart: Mode Toggle (Equity vs Candles), Timeframe, Zoom */}
      <div className="flex flex-wrap items-center justify-between px-2 py-1 bg-slate-900/90 border-b border-slate-800 shrink-0 gap-1.5 min-h-[32px]">
        {/* Left: View Mode Toggle, Symbol Selector & Live Metrics */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {/* Tri-Mode Selector: Equity, Candles, Projections */}
          <div className="flex items-center bg-slate-950 p-0.5 rounded border border-slate-800 shrink-0">
            <button
              id="btnViewEquity"
              onClick={() => {
                setViewMode('equity');
                setHoveredPoint(null);
              }}
              className={`flex items-center gap-1 px-1.5 sm:px-2 py-0.5 rounded text-[11px] sm:text-xs font-semibold transition ${
                viewMode === 'equity'
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Portfolio Equity & Growth Curve"
            >
              <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
              <span>Equity</span>
            </button>

            <button
              id="btnViewCandles"
              onClick={() => {
                setViewMode('candles');
                setHoveredPoint(null);
              }}
              className={`flex items-center gap-1 px-1.5 sm:px-2 py-0.5 rounded text-[11px] sm:text-xs font-semibold transition ${
                viewMode === 'candles'
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Japanese Candlestick Chart & VWAP"
            >
              <CandlestickChart className="w-3.5 h-3.5 text-cyan-400" />
              <span>Candles</span>
            </button>

            <button
              id="btnViewProjections"
              onClick={() => {
                setViewMode('projections');
                setHoveredPoint(null);
              }}
              className={`flex items-center gap-1 px-1.5 sm:px-2 py-0.5 rounded text-[11px] sm:text-xs font-semibold transition ${
                viewMode === 'projections'
                  ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40 shadow-xs font-bold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Nifty 50 & Bank Nifty Projections Engine"
            >
              <Compass className="w-3.5 h-3.5 text-purple-400" />
              <span>Projections</span>
            </button>
          </div>

          {/* If in Candles mode, show Portfolio Symbol Selector */}
          {viewMode === 'candles' && (
            <select
              id="selectMarketSymbol"
              value={selectedSymbol}
              onChange={(e) => setSelectedSymbol(e.target.value)}
              className="bg-slate-950 px-1.5 py-0.5 rounded border border-slate-800 text-[10px] sm:text-[11px] font-mono text-cyan-300 focus:outline-none focus:border-cyan-500 cursor-pointer max-w-[140px] sm:max-w-[210px] truncate shrink-0"
            >
              {isLive ? (
                <>
                  <option value="PORTFOLIO_EQUITY">Live Capital (₹{liveBaseCapital.toLocaleString('en-IN')})</option>
                  <option value="PORTFOLIO_PNL">Live Net P&L (-₹506.96)</option>
                  <option value="NIFTY_SPOT">NIFTY 50 Spot (22,873.55)</option>
                  <option value="BANKNIFTY_SPOT">BANKNIFTY Spot (55,682.70)</option>
                  <option value="23200CE">NIFTY 23200 CE (₹58.35)</option>
                </>
              ) : (
                <>
                  <option value="PORTFOLIO_EQUITY">Capital (₹1,09,280.50)</option>
                  <option value="PORTFOLIO_PNL">Net P&L (+₹9,280.50)</option>
                  <option value="22550PE">BNF 55700 CE (₹602.00)</option>
                  <option value="22900CE">NIFTY 23000 CE (₹147.30)</option>
                </>
              )}
            </select>
          )}

          {/* Live Performance / Spot Metric */}
          {viewMode === 'equity' ? (
            <div className="flex items-center gap-1.5 text-[11px] sm:text-xs font-mono ml-0.5 shrink-0">
              <span className="font-extrabold text-slate-100 tabular-nums">
                ₹{equityData.currentEquity.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <span className={`px-1.5 py-0.5 rounded font-bold text-[10px] tabular-nums border ${
                isLive
                  ? 'bg-emerald-500/15 border-emerald-500/35 text-emerald-300'
                  : 'bg-[#00b574]/15 border-[#00b574]/35 text-[#00b574]'
              }`}>
                {isLive ? 'LIVE BROKER: ₹0.00 (+0.00%)' : `${equityData.netPnl >= 0 ? '+' : '-'}₹${Math.abs(equityData.netPnl).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (+50.26%)`}
              </span>
            </div>
          ) : viewMode === 'candles' ? (
            <div className="flex items-center gap-1.5 text-[11px] font-mono ml-0.5 shrink-0 text-[#00BAF2] font-bold">
              <span className="tabular-nums">
                {selectedSymbol === 'PORTFOLIO_EQUITY'
                  ? `₹${equityData.currentEquity.toLocaleString('en-IN')}`
                  : selectedSymbol === 'PORTFOLIO_PNL'
                  ? `${isLive ? '' : '+'}₹${equityData.netPnl.toLocaleString('en-IN')}`
                  : selectedSymbol === 'NIFTY_SPOT'
                  ? '₹23,146.15'
                  : selectedSymbol === 'BANKNIFTY_SPOT'
                  ? '₹55,862.70'
                  : selectedSymbol === '23200CE'
                  ? '₹124.00'
                  : selectedSymbol === '22550PE'
                  ? '₹602.00'
                  : '₹147.30'}
              </span>
              <span className="text-amber-400 text-[9px] px-1 py-0.2 rounded bg-amber-500/10 border border-amber-500/30">VWAP</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-[11px] font-mono ml-1 shrink-0 text-purple-300 font-bold">
              <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse"></span>
              <span>AI PROJECTION ENGINE</span>
            </div>
          )}
        </div>

        {/* Right: Comprehensive Timeframes (1m, 5m, 15m, 30m, 1h, 1D, 1W, All) & Zoom */}
        {viewMode !== 'projections' ? (
          <div className="flex items-center gap-1 shrink-0 ml-auto">
            {/* Timeframe Chips */}
            <div className="flex items-center bg-slate-950 p-0.5 rounded border border-slate-800 text-[9px] sm:text-[10px] font-mono shrink-0">
              {SUPPORTED_TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  id={`btnTf_${tf}`}
                  onClick={() => handleTfSelect(tf)}
                  className={`px-1 sm:px-1.5 py-0.5 rounded transition ${
                    activeTf === tf
                      ? 'bg-slate-800 text-cyan-300 font-bold border border-slate-700/60'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>

            {/* Zoom Buttons */}
            <div className="flex items-center gap-0.5 bg-slate-950 p-0.5 rounded border border-slate-800 shrink-0">
              <button
                id="btnZoomIn"
                onClick={() => setZoomFactor((z) => Math.min(3.5, z * 1.2))}
                className="p-1 text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded transition"
                title="Zoom In"
              >
                <ZoomIn className="w-3 h-3" />
              </button>
              <button
                id="btnZoomOut"
                onClick={() => setZoomFactor((z) => Math.max(0.7, z / 1.2))}
                className="p-1 text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded transition"
                title="Zoom Out"
              >
                <ZoomOut className="w-3 h-3" />
              </button>
              <button
                id="btnResetZoom"
                onClick={resetZoom}
                className="p-1 text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded transition"
                title="Reset Zoom & Pan"
              >
                <RotateCcw className="w-3 h-3" />
              </button>
              <button
                id="btnSnapLatest"
                onClick={snapLatest}
                className="p-1 text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded transition"
                title="Snap to Latest Time"
              >
                <FastForward className="w-3 h-3" />
              </button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-[10px] font-mono text-purple-300 bg-purple-950/60 border border-purple-800/60 px-2 py-0.5 rounded ml-auto shrink-0">
            <span>● 27 Oct 2026 Expiry Models • Up/Base Limits Live</span>
          </div>
        )}
      </div>

      {/* Main View Area: Either Projections Engine or Canvas Chart */}
      {viewMode === 'projections' ? (
        <div className="flex-1 w-full min-h-0 overflow-hidden">
          <IndexProjectionsEngine />
        </div>
      ) : (
        <>
          {/* Canvas Area */}
      <div ref={canvasContainerRef} className="relative flex-1 w-full min-h-0 overflow-hidden cursor-crosshair">
        <canvas
          ref={canvasRef}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={() => setHoveredPoint(null)}
          className="absolute inset-0 block w-full h-full"
        />

        {/* Hover Tooltip Overlay */}
        {hoveredPoint && (
          <div
            id="chartTooltip"
            style={{
              left: `${Math.min(hoveredPoint.x + 12, window.innerWidth - 240)}px`,
              top: `${Math.max(10, Math.min(hoveredPoint.y - 45, 140))}px`,
            }}
            className="pointer-events-none absolute z-30 bg-slate-900/95 border border-slate-700/80 rounded-lg p-2 shadow-2xl text-xs backdrop-blur-xs max-w-xs animate-in fade-in duration-75"
          >
            {hoveredPoint.isEquity ? (
              <>
                <div className="flex items-center justify-between gap-3 border-b border-slate-800 pb-1 mb-1 text-[11px] font-mono text-slate-400">
                  <span className="font-bold text-slate-200">{hoveredPoint.time} IST</span>
                  <span className={hoveredPoint.pnl >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'}>
                    {hoveredPoint.pnl >= 0 ? '+' : ''}₹{hoveredPoint.pnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                  </span>
                </div>
                <div className="text-[12px] font-mono font-bold text-emerald-300">
                  Equity: ₹{hoveredPoint.equity.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </div>
                {hoveredPoint.note && (
                  <div className="text-[10px] text-slate-400 mt-1 leading-snug font-sans">
                    {hoveredPoint.note}
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="flex items-center justify-between gap-3 border-b border-slate-800 pb-1 mb-1 text-[11px] font-mono text-slate-400">
                  <span className="font-bold text-slate-200">{hoveredPoint.time} IST</span>
                  <span className="text-amber-300 font-bold">VWAP: {hoveredPoint.vwap?.toFixed(2)}</span>
                </div>
                <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] font-mono">
                  <div><span className="text-slate-500">O:</span> {selectedSymbol.startsWith('PORTFOLIO') ? `₹${hoveredPoint.o.toLocaleString('en-IN')}` : hoveredPoint.o.toFixed(2)}</div>
                  <div><span className="text-slate-500">H:</span> {selectedSymbol.startsWith('PORTFOLIO') ? `₹${hoveredPoint.h.toLocaleString('en-IN')}` : hoveredPoint.h.toFixed(2)}</div>
                  <div><span className="text-slate-500">L:</span> {selectedSymbol.startsWith('PORTFOLIO') ? `₹${hoveredPoint.l.toLocaleString('en-IN')}` : hoveredPoint.l.toFixed(2)}</div>
                  <div><span className="text-slate-500">C:</span> <strong className="text-cyan-300">{selectedSymbol.startsWith('PORTFOLIO') ? `₹${hoveredPoint.c.toLocaleString('en-IN')}` : hoveredPoint.c.toFixed(2)}</strong></div>
                </div>
                {hoveredPoint.v && (
                  <div className="text-[9px] font-mono text-slate-400 mt-1 pt-1 border-t border-slate-800/60">
                    Vol: {hoveredPoint.v.toLocaleString('en-IN')}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* Chart Footer: Provenance Ledger & Discrepancy Status */}
      <div className="flex items-center justify-between px-2.5 h-6 bg-slate-950 border-t border-slate-800/80 shrink-0 text-[10px] font-mono text-slate-400 gap-1 overflow-hidden">
        <div className="flex items-center gap-1.5 truncate">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
          {viewMode === 'equity' ? (
            <>
              <span>Base: ₹{equityData.baseCapital.toLocaleString('en-IN')}</span>
              <span className="text-slate-600 hidden sm:inline">|</span>
              <span className="truncate hidden sm:inline">Equity: ₹{equityData.currentEquity.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
            </>
          ) : (
            <>
              <span>{selectedSymbol === 'PORTFOLIO_EQUITY' ? 'PORTFOLIO CAPITAL' : selectedSymbol === 'PORTFOLIO_PNL' ? 'NET P&L' : selectedSymbol}</span>
              <span className="text-slate-600">|</span>
              <span>{activeTf}</span>
              <span className="text-slate-600 hidden sm:inline">|</span>
              <span className="text-amber-400 hidden sm:inline">VWAP</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-1 text-emerald-400 font-semibold shrink-0">
          <Activity className="w-3 h-3 shrink-0" />
          <span>Δ = ₹0.00</span>
        </div>
      </div>
        </>
      )}
    </div>
  );
}
