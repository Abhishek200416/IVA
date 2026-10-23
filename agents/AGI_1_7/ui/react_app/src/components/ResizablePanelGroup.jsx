import React, { useState, useEffect, useRef } from 'react';
import AgentChatPanel from './AgentChatPanel';
import EquityPerformanceChart from './EquityPerformanceChart';
import PortfolioTradesPanel from './PortfolioTradesPanel';
import ResearchPanel from './ResearchPanel';
import { Users, TrendingUp, Newspaper } from 'lucide-react';

export default function ResizablePanelGroup({ resetSignal, selectedEpoch = 'epoch_10k', currentMode = 'PAPER' }) {
  const [windowDims, setWindowDims] = useState(() => ({
    width: typeof window !== 'undefined' ? window.innerWidth : 1280,
    height: typeof window !== 'undefined' ? window.innerHeight : 800
  }));

  // Track window resizing with zero layout latency
  useEffect(() => {
    function handleResize() {
      setWindowDims({
        width: window.innerWidth,
        height: window.innerHeight
      });
    }
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const isMobile = windowDims.width < 560; // Only narrow mobile phone screens use tabs (< 560px); laptops and tablets retain 3 persistent panels
  const [mobileTab, setMobileTab] = useState('center'); // 'left' | 'center' | 'right'

  // Proportional responsive defaults based on available dimensions
  const availableDeskH = Math.max(300, windowDims.height - 48);
  const defaultLeftW = Math.max(170, Math.min(320, Math.round(windowDims.width * 0.22)));
  const defaultRightW = Math.max(180, Math.min(340, Math.round(windowDims.width * 0.25)));
  const minPortfolioH = 100; // Leaves sufficient room for portfolio dock header & summary bar
  const minChartH = 42; // Allows collapsing chart down to minimal top bar
  const maxChartH = Math.max(minChartH, availableDeskH - minPortfolioH); // Allows expanding chart/projections down to 75-80% of screen
  const defaultChartH = Math.max(minChartH, Math.min(maxChartH, Math.round(availableDeskH * 0.46)));

  const [leftWidth, setLeftWidth] = useState(() => {
    const saved = localStorage.getItem('agi_v5_left_w');
    const val = parseInt(saved, 10);
    return !isNaN(val) && val >= 170 && val <= 400 ? val : defaultLeftW;
  });

  const [rightWidth, setRightWidth] = useState(() => {
    const saved = localStorage.getItem('agi_v5_right_w');
    const val = parseInt(saved, 10);
    return !isNaN(val) && val >= 180 && val <= 440 ? val : defaultRightW;
  });

  const [chartHeight, setChartHeight] = useState(() => {
    const saved = localStorage.getItem('agi_v5_chart_h');
    const val = parseInt(saved, 10);
    return !isNaN(val) && val >= minChartH && val <= maxChartH ? val : defaultChartH;
  });

  const [activeResizer, setActiveResizer] = useState(null); // 'left' | 'right' | 'chart' | null

  // Reset layout handler
  useEffect(() => {
    if (resetSignal) {
      setLeftWidth(defaultLeftW);
      setRightWidth(defaultRightW);
      setChartHeight(defaultChartH);
      localStorage.removeItem('agi_v5_left_w');
      localStorage.removeItem('agi_v5_right_w');
      localStorage.removeItem('agi_v5_chart_h');
    }
  }, [resetSignal, defaultLeftW, defaultRightW, defaultChartH]);

  // Persist dimensions
  useEffect(() => {
    localStorage.setItem('agi_v5_left_w', String(leftWidth));
  }, [leftWidth]);

  useEffect(() => {
    localStorage.setItem('agi_v5_right_w', String(rightWidth));
  }, [rightWidth]);

  useEffect(() => {
    localStorage.setItem('agi_v5_chart_h', String(chartHeight));
  }, [chartHeight]);

  // Dynamic clamping to guarantee ZERO screen overflow and true 3-way balance
  const splitterTotalW = 14; // 2 splitters x 7px
  const totalContentW = Math.max(600, windowDims.width - splitterTotalW);
  const oneThirdW = Math.round(totalContentW / 3);

  // Guarantee that each of the 3 panels can range from 200px to 48% of screen
  const minPanelW = 190;
  const maxSideW = Math.round(totalContentW * 0.46);

  // Center panel must have at least minPanelW
  const maxCombinedSideW = totalContentW - minPanelW;
  let effectiveLeftW = Math.max(minPanelW, Math.min(maxSideW, leftWidth));
  let effectiveRightW = Math.max(minPanelW, Math.min(maxSideW, rightWidth));

  if (effectiveLeftW + effectiveRightW > maxCombinedSideW) {
    const scale = maxCombinedSideW / (effectiveLeftW + effectiveRightW);
    effectiveLeftW = Math.round(effectiveLeftW * scale);
    effectiveRightW = Math.round(effectiveRightW * scale);
  }

  // 1-Click 3-Way Equal Balance Handler (33% / 33% / 33%)
  const handleBalanceThreeWays = () => {
    setLeftWidth(oneThirdW);
    setRightWidth(oneThirdW);
  };

  // 2. Vertical bounds: Chart vs Portfolio inside availableDeskH
  const effectiveChartH = Math.max(minChartH, Math.min(maxChartH, chartHeight));

  // Pointer dragging for Left Splitter
  const handleLeftPointerDown = (e) => {
    e.preventDefault();
    setActiveResizer('left');
    const startX = e.clientX;
    const startW = effectiveLeftW;

    const onPointerMove = (moveEvent) => {
      const delta = moveEvent.clientX - startX;
      const newW = Math.max(minPanelW, Math.min(maxSideW, startW + delta));
      setLeftWidth(newW);
    };

    const onPointerUp = () => {
      setActiveResizer(null);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    };

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
  };

  // Pointer dragging for Right Splitter
  const handleRightPointerDown = (e) => {
    e.preventDefault();
    setActiveResizer('right');
    const startX = e.clientX;
    const startW = effectiveRightW;

    const onPointerMove = (moveEvent) => {
      const delta = startX - moveEvent.clientX;
      const newW = Math.max(minPanelW, Math.min(maxSideW, startW + delta));
      setRightWidth(newW);
    };

    const onPointerUp = () => {
      setActiveResizer(null);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    };

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
  };

  // Pointer dragging for Horizontal Chart/Portfolio Splitter
  const handleChartPointerDown = (e) => {
    e.preventDefault();
    setActiveResizer('chart');
    const startY = e.clientY;
    const startH = effectiveChartH;

    const onPointerMove = (moveEvent) => {
      const delta = moveEvent.clientY - startY;
      const newH = Math.max(minChartH, Math.min(maxChartH, startH + delta));
      setChartHeight(newH);
    };

    const onPointerUp = () => {
      setActiveResizer(null);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    };

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
  };

  return (
    <div className="flex-1 min-h-0 min-w-0 flex flex-col h-full w-full max-h-full max-w-full overflow-hidden select-none bg-slate-950">
      {/* Mobile-Only Tabs (< 768px) */}
      {isMobile && (
        <div
          id="mobileDeskTabs"
          role="tablist"
          aria-label="Trading Desk Viewport Tabs"
          className="flex items-center bg-slate-900 border-b border-slate-800 p-1 shrink-0 z-20 h-10"
        >
          <button
            role="tab"
            aria-selected={mobileTab === 'left'}
            onClick={() => setMobileTab('left')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1 px-2 rounded-md text-xs font-semibold transition ${
              mobileTab === 'left' ? 'bg-slate-800 text-cyan-400 border border-slate-700 shadow-xs' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            <span>Agents</span>
          </button>
          <button
            role="tab"
            aria-selected={mobileTab === 'center'}
            onClick={() => setMobileTab('center')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1 px-2 rounded-md text-xs font-semibold transition ${
              mobileTab === 'center' ? 'bg-slate-800 text-cyan-400 border border-slate-700 shadow-xs' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <TrendingUp className="w-3.5 h-3.5" />
            <span>Desk</span>
          </button>
          <button
            role="tab"
            aria-selected={mobileTab === 'right'}
            onClick={() => setMobileTab('right')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1 px-2 rounded-md text-xs font-semibold transition ${
              mobileTab === 'right' ? 'bg-slate-800 text-cyan-400 border border-slate-700 shadow-xs' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Newspaper className="w-3.5 h-3.5" />
            <span>Research</span>
          </button>
        </div>
      )}

      {/* Main 3-Panel Trading Desk Workspace */}
      <div className="flex-1 min-h-0 min-w-0 flex h-full w-full max-h-full max-w-full overflow-hidden relative">
        {/* PANEL A: LEFT (Agent Chat) */}
        {(!isMobile || mobileTab === 'left') && (
          <AgentChatPanel
            style={isMobile ? { width: '100%' } : { width: `${effectiveLeftW}px`, flexShrink: 0 }}
            selectedEpoch={selectedEpoch}
          />
        )}

        {/* Vertical Splitter 1: Left / Center */}
        {!isMobile && (
          <div
            id="resizerLeftCenter"
            onPointerDown={handleLeftPointerDown}
            onDoubleClick={handleBalanceThreeWays}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'ArrowLeft') setLeftWidth((w) => Math.max(minPanelW, w - 10));
              if (e.key === 'ArrowRight') setLeftWidth((w) => Math.min(maxSideW, w + 10));
            }}
            className={`w-1.5 hover:w-2 shrink-0 cursor-col-resize transition-all z-20 flex items-center justify-center group ${
              activeResizer === 'left' ? 'bg-cyan-500 w-2' : 'bg-slate-800 hover:bg-cyan-500/60'
            }`}
            title="Drag to resize, double-click to balance 3 panels equally (33% each)"
          >
            <div className="w-0.5 h-8 bg-slate-600 rounded-full group-hover:bg-cyan-300" />
          </div>
        )}

        {/* PANEL B: CENTER (Market Chart on Top, Portfolio Dock Below) */}
        {(!isMobile || mobileTab === 'center') && (
          <main
            id="panelCenter"
            className="flex-1 min-w-0 min-h-0 flex flex-col h-full max-h-full overflow-hidden bg-slate-900 relative"
          >
            {/* Center-Top Chart */}
            <div
              id="chartAreaWrapper"
              style={{ height: `${effectiveChartH}px` }}
              className="w-full shrink-0 min-h-0 overflow-hidden"
            >
              <EquityPerformanceChart selectedEpoch={selectedEpoch} currentMode={currentMode} />
            </div>

            {/* Resizable Horizontal Divider between Chart and Portfolio */}
            <div
              id="resizerChartPortfolio"
              onPointerDown={handleChartPointerDown}
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'ArrowUp') setChartHeight((h) => Math.max(minChartH, h - 25));
                if (e.key === 'ArrowDown') setChartHeight((h) => Math.min(maxChartH, h + 25));
              }}
              onDoubleClick={() => setChartHeight(defaultChartH)}
              className={`h-6 shrink-0 cursor-row-resize transition-all z-20 flex items-center justify-between px-2 sm:px-3 border-y border-slate-700/90 bg-slate-900/95 shadow-sm select-none ${
                activeResizer === 'chart' ? 'bg-cyan-950 border-cyan-400' : 'hover:bg-slate-800 hover:border-cyan-500/80'
              }`}
              title="Drag up/down to adjust panel heights (42px to 700px), or click quick buttons"
            >
              {/* Left quick actions: Expand Chart / Projections */}
              <div className="flex items-center gap-1 text-[9px] font-mono text-cyan-300">
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setChartHeight(Math.round(availableDeskH * 0.70)); }}
                  className="px-2 py-0.5 bg-slate-950 hover:bg-cyan-950 text-cyan-300 hover:text-cyan-200 rounded border border-slate-700 hover:border-cyan-400 transition font-bold flex items-center gap-1 cursor-pointer shadow-2xs"
                  title="Expand Projections / Chart view to 70% height"
                >
                  <span>▲ Expand Projections (70%)</span>
                </button>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setChartHeight(Math.round(availableDeskH * 0.50)); }}
                  className="px-2 py-0.5 bg-slate-950 hover:bg-cyan-950 text-cyan-300 hover:text-cyan-200 rounded border border-slate-700 hover:border-cyan-400 transition font-bold flex items-center gap-1 cursor-pointer shadow-2xs"
                  title="Split center view equally 50/50"
                >
                  <span>↕ 50/50 Split</span>
                </button>
              </div>

              {/* Center Grab Handle */}
              <div className="flex items-center gap-1.5 text-slate-400 hover:text-cyan-300 transition text-[9px] font-mono font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse"></span>
                <span className="hidden md:inline">Drag to Adjust Height ({effectiveChartH}px)</span>
                <div className="h-1 w-12 bg-slate-600 rounded-full group-hover:bg-cyan-300 mx-1" />
              </div>

              {/* Right quick actions: Maximize Portfolio List */}
              <div className="flex items-center gap-1 text-[9px] font-mono text-cyan-300">
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setChartHeight(Math.round(availableDeskH * 0.25)); }}
                  className="px-2 py-0.5 bg-slate-950 hover:bg-cyan-950 text-cyan-300 hover:text-cyan-200 rounded border border-slate-700 hover:border-cyan-400 transition font-bold flex items-center gap-1 cursor-pointer shadow-2xs"
                  title="Expand Portfolio & Options History list to 75% height"
                >
                  <span>▼ Maximize List (75%)</span>
                </button>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setChartHeight(minChartH); }}
                  className="px-1.5 py-0.5 bg-slate-950 hover:bg-slate-800 text-slate-400 hover:text-slate-200 rounded border border-slate-700 transition cursor-pointer"
                  title="Collapse Chart to top ribbon (42px)"
                >
                  <span>Collapse (42px)</span>
                </button>
              </div>
            </div>

            {/* Center-Bottom Portfolio Dock Workspace */}
            <div className="flex-1 min-h-0 min-w-0 w-full max-h-full overflow-hidden flex flex-col">
              <PortfolioTradesPanel selectedEpoch={selectedEpoch} currentMode={currentMode} />
            </div>
          </main>
        )}

        {/* Vertical Splitter 2: Center / Right */}
        {!isMobile && (
          <div
            id="resizerCenterRight"
            onPointerDown={handleRightPointerDown}
            onDoubleClick={handleBalanceThreeWays}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'ArrowLeft') setRightWidth((w) => Math.min(maxSideW, w + 10));
              if (e.key === 'ArrowRight') setRightWidth((w) => Math.max(minPanelW, w - 10));
            }}
            className={`w-1.5 hover:w-2 shrink-0 cursor-col-resize transition-all z-20 flex items-center justify-center group ${
              activeResizer === 'right' ? 'bg-cyan-500 w-2' : 'bg-slate-800 hover:bg-cyan-500/60'
            }`}
            title="Drag to resize, double-click to balance 3 panels equally (33% each)"
          >
            <div className="w-0.5 h-8 bg-slate-600 rounded-full group-hover:bg-cyan-300" />
          </div>
        )}

        {/* PANEL C: RIGHT (News & Research) */}
        {(!isMobile || mobileTab === 'right') && (
          <ResearchPanel
            style={isMobile ? { width: '100%' } : { width: `${effectiveRightW}px`, flexShrink: 0 }}
          />
        )}
      </div>
    </div>
  );
}
