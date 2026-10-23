import React, { useState, useRef, useEffect } from 'react';
import {
  Clock,
  Cpu,
  Wallet,
  Database,
  User,
  Settings,
  ChevronDown,
  Lock,
  CheckCircle2,
  Shield,
  Layers,
  FlaskConical,
  Bot,
  GitPullRequest,
  Activity
} from 'lucide-react';

export default function AppHeader({
  activePage,
  onNavigate,
  onOpenHistory,
  onOpenPortfolio,
  onToggleSettings,
  onOpenLiveReadiness,
  onOpenModeSelector,
  onOpenLiveDataValidation,
  onSelectMode,
  onEmergencyStop,
  isSettingsOpen,
  isHistoryOpen,
  isPortfolioOpen,
  statusData,
  selectedEpoch = 'epoch_10k'
}) {
  const [isModeMenuOpen, setIsModeMenuOpen] = useState(false);
  const modeMenuRef = useRef(null);

  const [isNavDropdownOpen, setIsNavDropdownOpen] = useState(false);
  const navDropdownRef = useRef(null);

  const currentMode = statusData?.operating_mode?.current_mode || statusData?.mode || 'PAPER';

  // Complete List of Terminal Sub-Tabs / Views for Seamless Navigation
  const NAV_ITEMS = [
    { id: 'trading', label: 'Trading Desk', icon: Activity, color: 'text-cyan-400', badge: 'Active Desk', desc: 'Real-Time Tri-Tab Chart & Live Execution' },
    { id: 'history', label: 'History', icon: Clock, color: 'text-[#00BAF2]', badge: 'Settlement', desc: 'Closed Trades & Historical Audit Ledger' },
    { id: 'algorithms', label: 'Algorithms', icon: Cpu, color: 'text-[#00BAF2]', badge: 'Catalog', desc: 'Verified Quantitative Trading Models' },
    { id: 'agents', label: 'Agents', icon: Bot, color: 'text-cyan-400', badge: '106 Squad', desc: '16 Families Specialist Mesh' },
    { id: 'orchestration', label: 'Orchestration', icon: GitPullRequest, color: 'text-purple-400', badge: 'DAG Pipeline', desc: 'Task Orchestration & Continuous Loops' },
    { id: 'research', label: 'Research', icon: FlaskConical, color: 'text-amber-400', badge: 'Quant Lab', desc: 'Frontier Alpha & Strategy Registry' },
    { id: 'portfolio', label: 'Portfolio', icon: Wallet, color: 'text-[#00b574]', badge: currentMode === 'LIVE_EXECUTION' ? 'Live Broker' : 'Paper Epochs', desc: 'Capital Management & Pre-Trade Risk Limits' },
    { id: 'memory', label: 'Memory', icon: Database, color: 'text-purple-400', badge: '4-Tier', desc: 'SQLite WAL Memory Architecture' },
    { id: 'profile', label: 'Profile & Live API', icon: User, color: 'text-blue-400', badge: 'Auth Status', desc: 'Operator Profile & Live Paytm Session Verification' },
  ];

  const activeNavItem = NAV_ITEMS.find((item) => item.id === activePage) || NAV_ITEMS[0];
  const ActiveNavIcon = activeNavItem.icon;

  // Live ticking clock in IST
  const [liveClock, setLiveClock] = useState(() => {
    return new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
  });

  useEffect(() => {
    const timer = setInterval(() => {
      setLiveClock(new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Close dropdowns on click outside or Escape
  useEffect(() => {
    function handleClickOutside(e) {
      if (modeMenuRef.current && !modeMenuRef.current.contains(e.target)) {
        setIsModeMenuOpen(false);
      }
      if (navDropdownRef.current && !navDropdownRef.current.contains(e.target)) {
        setIsNavDropdownOpen(false);
      }
    }
    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        setIsModeMenuOpen(false);
        setIsNavDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  return (
    <header className="h-12 bg-gradient-to-r from-[#00173d] via-[#001c4a] to-[#00173d] border-b border-[#00BAF2]/30 px-2 sm:px-3 flex items-center justify-between shrink-0 select-none z-30 gap-1.5 w-full max-w-full overflow-visible shadow-md">
      {/* 1. Left: Paytm Money Brand & Live Broker Connection Badge */}
      <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
        <button
          id="btnBrandHome"
          onClick={() => onNavigate('trading')}
          className="flex items-center gap-1.5 group text-left focus:outline-none"
          title="Return to Paytm Money Trading Desk"
        >
          {/* Paytm Money Signature Logo */}
          <div className="w-6 h-6 rounded-md bg-[#002E6E] border border-[#00BAF2]/50 flex items-center justify-center shadow-xs shadow-[#00BAF2]/30 shrink-0">
            <span className="text-[12px] font-black text-[#00BAF2] tracking-tighter">₹</span>
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-1">
              <span className="text-xs font-black tracking-wide text-white group-hover:text-[#00BAF2] transition-colors">
                Paytm Money
              </span>
              <span className="text-[10px] font-bold text-[#00BAF2] hidden xl:inline">
                • AGI 1.7 COMMAND
              </span>
            </div>
            <span className="text-[8.5px] font-mono text-slate-400 hidden 2xl:inline -mt-0.5">
              Supervised High-Density Options Engine
            </span>
          </div>
        </button>

        {/* Live Paytm Money Connection Status (Port 9229) / OTP Standby Badge */}
        {statusData?.auth_status === 'WAITING_FOR_OPERATOR_AUTH' ? (
          <div 
            className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-400/80 text-amber-300 text-[10px] font-mono font-bold animate-pulse shadow-sm shadow-amber-950/40 shrink-0"
            title="Paytm Money OTP / 2FA Login Required. Agent is standing by calmly with zero reloads, zero scraping, and single-tab lock."
          >
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
            <span>Awaiting Operator OTP (Standby)</span>
          </div>
        ) : (
          <a
            href="https://www.paytmmoney.com/stocks"
            target="_blank"
            rel="noreferrer"
            className="hidden md:inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[#002E6E]/60 border border-[#00BAF2]/40 text-[#00BAF2] text-[10px] font-mono hover:bg-[#002E6E] hover:border-[#00BAF2] transition shadow-xs"
            title="Connected to Paytm Money Web on port 9229 • Active Dual-Tab Live DOM Sync"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-[#00b574] animate-pulse"></span>
            <span className="font-semibold text-slate-100">Paytm Live (9229)</span>
          </a>
        )}

        {/* Single-Tab Actuator Indicator */}
        <div 
          className="hidden 2xl:inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-[#061224] border border-[#00BAF2]/30 text-[9.5px] font-mono text-cyan-300"
          title="Single-Tab Actuator Active: Reuses existing tab without spawning popup bloat"
        >
          <span className="text-[#00BAF2]">⚡</span>
          <span>Single-Tab</span>
        </div>

        {/* Ambience Paper vs Live Badge */}
        <div className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-mono font-semibold tracking-wide shrink-0 border ${
          currentMode === 'LIVE_EXECUTION'
            ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300 font-bold'
            : 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
        }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${currentMode === 'LIVE_EXECUTION' ? 'bg-emerald-400 animate-pulse' : 'bg-emerald-400'}`}></span>
          <span>{currentMode === 'LIVE_EXECUTION' ? 'LIVE BROKER' : 'PAPER'}</span>
        </div>
      </div>

      {/* 2. Center: Principal Dashboard Controls with Responsive Dropdown Menu */}
      <div className="flex-1 min-w-0 flex items-center justify-center mx-1 relative" ref={navDropdownRef}>
        {/* Compact Active View Button (Always visible on compressed/zoomed screens, < 2xl) */}
        <div className="flex 2xl:hidden items-center">
          <button
            id="btnHeaderNavDropdownCompact"
            onClick={() => setIsNavDropdownOpen((prev) => !prev)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#061224] border border-[#00BAF2]/40 text-xs font-semibold text-slate-100 hover:border-[#00BAF2] hover:bg-[#002E6E]/60 transition shadow-xs cursor-pointer"
            title="Switch Dashboard Sub-Tabs & Views"
          >
            <ActiveNavIcon className={`w-3.5 h-3.5 ${activeNavItem.color}`} />
            <span className="font-bold truncate max-w-[110px] sm:max-w-[150px]">{activeNavItem.label}</span>
            <ChevronDown className={`w-3.5 h-3.5 text-cyan-400 transition-transform duration-150 ${isNavDropdownOpen ? 'rotate-180' : ''}`} />
          </button>
        </div>

        {/* Wide Horizontal Sub-Tabs (Visible on 2xl+, with More Views dropdown) */}
        <nav className="hidden 2xl:flex items-center gap-0.5 sm:gap-1 bg-[#061224]/90 p-0.5 rounded-lg border border-slate-800 shrink-0">
          {/* History */}
          <button
            id="btnHeaderHistory"
            onClick={() => onNavigate('history')}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold transition shrink-0 ${
              activePage === 'history'
                ? 'bg-[#00BAF2]/20 text-[#00BAF2] border border-[#00BAF2]/40 shadow-xs'
                : 'text-slate-300 hover:text-white hover:bg-slate-800/80'
            }`}
            title="View Closed Trades & Historical Settlement Ledger (/history)"
          >
            <Clock className="w-3.5 h-3.5 text-[#00BAF2]" />
            <span>History</span>
          </button>

          {/* Algorithms */}
          <button
            id="btnHeaderAlgorithms"
            onClick={() => onNavigate('algorithms')}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold transition shrink-0 ${
              activePage === 'algorithms'
                ? 'bg-[#00BAF2]/20 text-[#00BAF2] border border-[#00BAF2]/40 shadow-xs'
                : 'text-slate-300 hover:text-white hover:bg-slate-800/80'
            }`}
            title="Verified Algorithms Catalog (/algorithms)"
          >
            <Cpu className="w-3.5 h-3.5 text-[#00BAF2]" />
            <span>Algorithms</span>
          </button>

          {/* Agents */}
          <button
            id="btnHeaderAgents"
            onClick={() => onNavigate('agents')}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold transition shrink-0 ${
              activePage === 'agents'
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                : 'text-slate-300 hover:text-white hover:bg-slate-800/80'
            }`}
            title="Agent Operations & 106 Embedded Specialists (/agents)"
          >
            <Bot className="w-3.5 h-3.5 text-cyan-400" />
            <span>Agents</span>
          </button>

          {/* Orchestration */}
          <button
            id="btnHeaderOrchestration"
            onClick={() => onNavigate('orchestration')}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold transition shrink-0 ${
              activePage === 'orchestration'
                ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40 shadow-xs'
                : 'text-slate-300 hover:text-white hover:bg-slate-800/80'
            }`}
            title="Task Orchestration & DAG Pipeline (/orchestration)"
          >
            <GitPullRequest className="w-3.5 h-3.5 text-purple-400" />
            <span>Orchestration</span>
          </button>

          {/* Research Lab */}
          <button
            id="btnHeaderResearch"
            onClick={() => onNavigate('research')}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold transition shrink-0 ${
              activePage === 'research'
                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-xs'
                : 'text-slate-300 hover:text-white hover:bg-slate-800/80'
            }`}
            title="Quantitative Research Lab & Strategy Registry (/research)"
          >
            <FlaskConical className="w-3.5 h-3.5 text-amber-400" />
            <span>Research</span>
          </button>

          {/* Portfolio */}
          <button
            id="btnHeaderPortfolio"
            onClick={() => onNavigate('portfolio')}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold transition shrink-0 ${
              activePage === 'portfolio'
                ? 'bg-[#00b574]/20 text-[#00b574] border border-[#00b574]/40 shadow-xs font-bold'
                : 'text-slate-300 hover:text-white hover:bg-slate-800/80'
            }`}
            title="Portfolio, Custom Paper Capital & Epoch Overview (/portfolio)"
          >
            <Wallet className="w-3.5 h-3.5 text-[#00b574]" />
            <span>Portfolio</span>
          </button>

          {/* Memory & Learning */}
          <button
            id="btnHeaderMemory"
            onClick={() => onNavigate('memory')}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold transition shrink-0 ${
              activePage === 'memory'
                ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40 shadow-xs'
                : 'text-slate-300 hover:text-white hover:bg-slate-800/80'
            }`}
            title="4-Tier Memory & Learning System"
          >
            <Database className="w-3.5 h-3.5 text-purple-400" />
            <span>Memory</span>
          </button>

          {/* Profile & Diagnostics */}
          <button
            id="btnHeaderProfile"
            onClick={() => onNavigate('profile')}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold transition shrink-0 ${
              activePage === 'profile'
                ? 'bg-blue-500/20 text-blue-300 border border-blue-500/40 shadow-xs'
                : 'text-slate-300 hover:text-white hover:bg-slate-800/80'
            }`}
            title="Operator Profile & Paytm Integration Status"
          >
            <User className="w-3.5 h-3.5 text-blue-400" />
            <span>Profile</span>
          </button>

          {/* More Views Dropdown Button */}
          <button
            id="btnHeaderNavDropdownWide"
            onClick={() => setIsNavDropdownOpen((prev) => !prev)}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold transition shrink-0 cursor-pointer ${
              isNavDropdownOpen
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/80'
            }`}
            title="All Sub-Tabs Menu"
          >
            <span>More</span>
            <ChevronDown className={`w-3 h-3 text-cyan-400 transition-transform duration-150 ${isNavDropdownOpen ? 'rotate-180' : ''}`} />
          </button>
        </nav>

        {/* The Responsive Navigation Dropdown Menu (Z-50, Never Hidden on Zoom or Screen Shrink!) */}
        {isNavDropdownOpen && (
          <div
            id="menuHeaderNavDropdown"
            className="absolute top-full left-1/2 -translate-x-1/2 mt-1.5 w-72 sm:w-80 bg-slate-900/98 border border-[#00BAF2]/40 rounded-xl shadow-2xl p-2 z-50 backdrop-blur-md animate-in fade-in zoom-in-95 duration-100"
          >
            <div className="flex items-center justify-between px-2.5 py-1.5 border-b border-slate-800 text-[10.5px] font-mono text-slate-400">
              <span className="font-bold text-slate-200">SWITCH VIEW / SUB-TAB</span>
              <span className="text-[#00BAF2]">9 Available</span>
            </div>
            <div className="grid grid-cols-1 gap-1 mt-1 max-h-[70vh] overflow-y-auto">
              {NAV_ITEMS.map((item) => {
                const ItemIcon = item.icon;
                const isActive = activePage === item.id;
                return (
                  <button
                    key={item.id}
                    id={`btnNavDropdown_${item.id}`}
                    onClick={() => {
                      onNavigate(item.id);
                      setIsNavDropdownOpen(false);
                    }}
                    className={`flex items-center justify-between w-full px-2.5 py-2 rounded-lg text-left transition cursor-pointer ${
                      isActive
                        ? 'bg-cyan-500/20 text-cyan-200 border border-cyan-500/40 shadow-xs'
                        : 'text-slate-300 hover:bg-slate-800/90 hover:text-white border border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className={`p-1.5 rounded-md ${isActive ? 'bg-cyan-500/30' : 'bg-slate-800'} shrink-0`}>
                        <ItemIcon className={`w-4 h-4 ${item.color}`} />
                      </div>
                      <div className="min-w-0">
                        <div className="text-xs font-bold truncate flex items-center gap-1.5">
                          <span>{item.label}</span>
                          {isActive && <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse"></span>}
                        </div>
                        <div className="text-[10px] text-slate-400 truncate">{item.desc}</div>
                      </div>
                    </div>
                    <span className={`text-[9.5px] font-mono px-1.5 py-0.5 rounded shrink-0 border ${
                      isActive
                        ? 'bg-cyan-500/30 border-cyan-400/50 text-cyan-200 font-bold'
                        : 'bg-slate-800 border-slate-700 text-slate-400'
                    }`}>
                      {item.badge}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* 3. Right: Live Clock & Date + Live Today's P&L Badge + Trading Mode Selector + Settings */}
      <div className="flex items-center gap-1.5 shrink-0">
        {/* Real-Time Live Clock & Session Date */}
        <div className="hidden md:flex items-center gap-1.5 px-2 py-1 rounded-lg bg-slate-900 border border-slate-700/80 text-[10.5px] font-mono text-cyan-300 shadow-xs" title="Authoritative Real-Time System Clock (IST)">
          <Clock className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
          <span className="text-slate-300 font-semibold">Mon, 19 Oct 2026</span>
          <span className="text-slate-600">|</span>
          <span className="font-extrabold text-white tabular-nums">{liveClock} IST</span>
        </div>

        {/* Live Reconciled Today's P&L Badge */}
        <div 
          className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-[#00b574]/15 border border-[#00b574]/35 text-[#00b574] text-xs font-mono font-bold shadow-xs cursor-pointer hover:bg-[#00b574]/25 transition"
          onClick={() => onNavigate('portfolio')}
          title="Click to view full portfolio & settled P&L breakdown"
        >
          <span className="text-[9.5px] uppercase tracking-wider text-[#00b574] hidden sm:inline">
            {currentMode === 'LIVE_EXECUTION' ? 'Today (Live Broker):' : 'Today (19 Oct):'}
          </span>
          <span className="text-slate-100 tabular-nums font-extrabold">
            {currentMode === 'LIVE_EXECUTION'
              ? (statusData?.live_today_profit != null && statusData.live_today_profit !== 0 ? `+₹${statusData.live_today_profit.toFixed(2)}` : '₹0.00')
              : (statusData?.today_profit != null && statusData.today_profit !== 0 ? `+₹${statusData.today_profit.toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '₹0.00')}
          </span>
          <span className="text-[#00b574] text-[10px] tabular-nums font-bold hidden md:inline">
            {currentMode === 'LIVE_EXECUTION'
              ? (statusData?.live_today_profit_pct || '(+0.00%)')
              : (statusData?.today_profit_pct != null ? `(${statusData.today_profit_pct})` : '(+0.00%)')}
          </span>
        </div>

        {/* Trading Mode Selector Dropdown */}
        <div className="relative" ref={modeMenuRef}>
          <div className="flex items-center gap-1 bg-[#061224] border border-slate-800 p-0.5 rounded-lg">
            {/* Mode Select Button */}
            {(() => {
              const isEmergency = statusData?.operating_mode?.emergency_stop_active || statusData?.emergency_stop_active;
              let dotColor = 'bg-emerald-400';
              let badgeColor = 'text-emerald-300 bg-emerald-500/10 border-emerald-500/25';
              let label = 'PAPER';

              if (isEmergency) {
                dotColor = 'bg-rose-500';
                badgeColor = 'text-rose-300 bg-rose-500/10 border-rose-500/25';
                label = 'STOPPED';
              } else if (currentMode === 'BACKTEST') {
                dotColor = 'bg-purple-400';
                badgeColor = 'text-purple-300 bg-purple-500/10 border-purple-500/25';
                label = 'BACKTEST';
              } else if (currentMode === 'LIVE_DATA_VALIDATION') {
                dotColor = 'bg-cyan-400';
                badgeColor = 'text-cyan-300 bg-cyan-500/10 border-cyan-500/25';
                label = 'LIVE DATA';
              } else if (currentMode === 'LIVE_EXECUTION') {
                dotColor = 'bg-emerald-400';
                badgeColor = 'text-emerald-300 bg-emerald-500/20 border-emerald-500/50';
                label = 'LIVE BROKER';
              }

              return (
                <button
                  id="btnTradingModeSelector"
                  onClick={() => {
                    if (onOpenModeSelector) onOpenModeSelector();
                    else setIsModeMenuOpen((prev) => !prev);
                  }}
                  className="flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono font-medium text-slate-200 hover:text-white hover:bg-slate-800 transition cursor-pointer"
                  title="Click to select Operating Mode (Paper Trading, Live Trading, Backtest)"
                  aria-expanded={isModeMenuOpen}
                >
                  <span className={`w-2 h-2 rounded-full ${dotColor} animate-pulse`}></span>
                  <span className="font-bold hidden lg:inline">Mode: {label}</span>
                  <span className="font-bold lg:hidden">{label}</span>
                  <ChevronDown className="w-3 h-3 text-slate-400" />
                </button>
              );
            })()}

            {/* Emergency Stop Button */}
            <button
              id="btnEmergencyStopHeader"
              onClick={() => {
                if (onEmergencyStop) onEmergencyStop();
              }}
              className="px-1.5 py-0.5 rounded bg-rose-950/60 hover:bg-rose-900 border border-rose-800 text-[10px] font-mono text-rose-400 font-bold transition shadow-xs"
              title="Immediate Kill Switch: Revert to Safe PAPER Mode"
            >
              STOP
            </button>
          </div>

          {/* Mode Dropdown Menu */}
          {isModeMenuOpen && (
            <div
              id="tradingModeDropdownMenu"
              className="absolute right-0 mt-1.5 w-72 max-w-[calc(100vw-24px)] bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl p-1.5 text-xs text-slate-100 z-50 animate-in fade-in zoom-in-95 duration-100"
            >
              <div className="px-2 py-1 text-[10px] font-mono text-slate-400 uppercase tracking-wider border-b border-slate-800 mb-1 flex items-center justify-between">
                <span>Execution Mode Boundary</span>
                <span className="text-[9px] text-[#00BAF2]">4 Modes</span>
              </div>

              {/* Mode A: Backtest */}
              <button
                id="menuOptionBacktest"
                onClick={() => {
                  setIsModeMenuOpen(false);
                  if (onSelectMode) onSelectMode('BACKTEST');
                }}
                className="w-full flex items-start gap-2.5 p-2 rounded-lg text-left transition hover:bg-slate-800/80 mt-0.5 border border-transparent hover:border-purple-800"
              >
                <Layers className="w-4 h-4 text-purple-400 shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold text-purple-300 flex items-center gap-1.5">
                    <span>Mode A: Backtest</span>
                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-purple-950 text-purple-300 font-mono">
                      RESEARCH
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5 leading-tight">
                    Historical walk-forward evaluation. Isolated datasets, 0 broker impact.
                  </div>
                </div>
              </button>

              {/* Mode B: Paper Trading */}
              <button
                id="menuOptionPaperTrading"
                onClick={() => {
                  setIsModeMenuOpen(false);
                  if (onSelectMode) onSelectMode('PAPER');
                }}
                className="w-full flex items-start gap-2.5 p-2 rounded-lg bg-emerald-950/40 border border-emerald-500/30 text-left transition hover:bg-emerald-950/60 mt-1"
              >
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold text-emerald-300 flex items-center gap-1.5">
                    <span>Mode B: Paper Trading</span>
                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 font-mono">
                      DEFAULT ACTIVE
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5 leading-tight">
                    Supervised simulation on epoch_10k ledger (₹10,000). Safe execution.
                  </div>
                </div>
              </button>

              {/* Mode C: Live Data Validation */}
              <button
                id="menuOptionLiveDataValidation"
                onClick={() => {
                  setIsModeMenuOpen(false);
                  if (onSelectMode) onSelectMode('LIVE_DATA_VALIDATION');
                  if (onOpenLiveDataValidation) onOpenLiveDataValidation();
                }}
                className="w-full flex items-start gap-2.5 p-2 rounded-lg text-left transition hover:bg-slate-800/80 mt-1 border border-transparent hover:border-cyan-800"
              >
                <Activity className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold text-cyan-300 flex items-center gap-1.5">
                    <span>Mode C: Live Data Validation</span>
                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-300 font-mono">
                      READ-ONLY
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5 leading-tight">
                    Genuine Paytm feed inspection & account checks. Live orders disabled.
                  </div>
                </div>
              </button>

              {/* Mode D: Live Trading (Locked) */}
              <button
                id="menuOptionLiveTrading"
                onClick={() => {
                  setIsModeMenuOpen(false);
                  if (onOpenModeSelector) onOpenModeSelector();
                  else if (onOpenLiveReadiness) onOpenLiveReadiness();
                }}
                className="w-full flex items-start gap-2.5 p-2 rounded-lg text-left transition hover:bg-slate-800/80 mt-1 border border-transparent hover:border-rose-800"
              >
                <Lock className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                <div className="flex-1">
                  <div className="font-semibold text-slate-200 flex items-center justify-between gap-1.5">
                    <span>Mode D: Live Execution</span>
                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-rose-950/80 text-rose-400 border border-rose-800 font-mono">
                      LOCKED / PREREQUISITES UNMET
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5 leading-tight">
                    Requires 12-item readiness checklist clearance. Order dispatch locked fail-closed.
                  </div>
                </div>
              </button>

              <div className="mt-1 pt-1 border-t border-slate-800 flex items-center justify-between px-1">
                <button
                  id="btnOpenModeControlCenter"
                  onClick={() => {
                    setIsModeMenuOpen(false);
                    if (onOpenModeSelector) onOpenModeSelector();
                  }}
                  className="py-1 text-[11px] font-mono text-[#00BAF2] hover:underline"
                >
                  Mode Controls & Matrix →
                </button>
                <button
                  id="btnOpenReadinessFromHeader"
                  onClick={() => {
                    setIsModeMenuOpen(false);
                    onNavigate('readiness');
                  }}
                  className="py-1 text-[11px] font-mono text-slate-400 hover:text-slate-200 hover:underline"
                >
                  Full Checklist →
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Settings Button */}
        <div className="relative">
          <button
            id="btnSettingsToggle"
            onClick={onToggleSettings}
            className={`p-1.5 rounded-lg border transition ${
              isSettingsOpen
                ? 'bg-slate-800 text-cyan-400 border-cyan-500/50'
                : 'bg-slate-900 text-slate-400 hover:text-slate-200 border-slate-800 hover:border-slate-700'
            }`}
            title="Settings & Layout Reset"
            aria-label="Settings"
          >
            <Settings className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  );
}
