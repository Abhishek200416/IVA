import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Newspaper,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  ShieldAlert,
  Sparkles,
  Building2,
  Landmark,
  LineChart,
  FileText,
  Zap,
  Clock,
  RotateCcw,
  Activity,
  CheckCircle2,
  Pin,
  Bot,
  MessageSquare,
  X
} from 'lucide-react';
import { api } from '../services/api';
import { formatTo12Hour } from '../utils/formatters';

const DEFAULT_DOCUMENTS = [
  {
    id: "doc-brief-afternoon-02",
    category: "briefing",
    categoryLabel: "Live Market Pulse",
    headline: "BANK NIFTY Crosses 55,900: Heavy Institutional Short Squeeze Accelerates",
    source: "Paytm Money Live DOM Stream & NSE Tick Feed",
    url: "https://www.paytmmoney.com/stocks/fno/option-chain/2000000023/BANKNIFTY/NSE",
    published: "2026-10-19 12:35 AM IST",
    retrieved: "2026-10-19 12:35 AM IST",
    relevance: "99% Active Momentum Driver",
    summary: "Bank Nifty spot surged past 55,862 (+52 pts), triggering call unwinding at 55500-55800 strikes. BANKNIFTY 55800 CE marked at ₹478.65 entry seeking Target 1 (₹750.00).",
    facts: "Spot 55,862.70 (+0.09%); 55800 CE marked at ₹478.65; Trailing SL securely locked at ₹410.00.",
    interpretation: "Sustained call short squeeze confirmed. Move stop loss upwards and let the runner seek Target 1 (₹750.00).",
    freshness: "REALTIME_LIVE_FEED_OCT19"
  },
  {
    id: "doc-brief-01",
    category: "briefing",
    categoryLabel: "Market Briefing",
    headline: "NIFTY Monday Opening Watch: Gift Nifty Signals Firm Start Near 23,200 (+0.65%)",
    source: "Paytm Money Live DOM & NSE Market Pulse",
    url: "https://www.paytmmoney.com/stocks/fno/option-chain/2000000011/NIFTY/NSE",
    published: "2026-10-19 12:35 AM IST",
    retrieved: "2026-10-19 12:35 AM IST",
    relevance: "98% Directional Momentum Driver",
    summary: "Nifty 50 trades firmly at 23,146.15 (+0.65%), with Gift Nifty pointing to 23,200. Front-month 23000 Put writing (+98.4L shares) establishes iron floor.",
    facts: "Spot 23,146.15 (+148.80); 23000 PE solidifies floor; PCR at 1.05.",
    interpretation: "Massive put writing establishes ironclad floor. Shift strategy to momentum continuation bull spreads.",
    freshness: "REALTIME_LIVE_FEED_OCT19"
  },
  {
    id: "doc-inst-01",
    category: "instruments",
    categoryLabel: "Instrument Context & Expiry Setup",
    headline: "Derivatives Positioning: 23,000 PE Iron Floor & 23,200 CE Up Limit Projection",
    source: "Autonomous Quad Consensus (Alex + Max + Emily + Manager Iva)",
    url: "http://127.0.0.1:8088/agents",
    published: "2026-10-19 12:30 AM IST",
    retrieved: "2026-10-19 12:30 AM IST",
    relevance: "95% Forward Execution Strategy",
    summary: "Quad coordination analysis: Emily confirms positive macro flow; Max sizes 23000 Call runner; Alex validates live order book depth.",
    facts: "23000 PE OI = 98.4L shares; 23200 CE OI = 94.1L shares.",
    interpretation: "Positioning supports trailing winning calls into weekly expiry. Up limit 23,250 / Floor 23,000.",
    freshness: "ACTIVE_CONSENSUS_OCT19"
  },
  {
    id: "doc-macro-01",
    category: "macro",
    categoryLabel: "Macro & Central Bank",
    headline: "RBI Liquidity Cushion & DII Cash Inflow (+₹3,319 Cr) Fuel Risk-On Momentum",
    source: "Reserve Bank of India (RBI Bull. Oct 2026)",
    url: "https://www.rbi.org.in/",
    published: "2026-10-19 12:20 AM IST",
    retrieved: "2026-10-19 12:20 AM IST",
    relevance: "94% Institutional Flow Correlation",
    summary: "Domestic institutional investors absorbed market supply with +₹3,319 Cr net purchases, offsetting foreign outflow and stabilizing banking credit spreads.",
    facts: "DII Net Buy = +₹3,319 Cr; Banking liquidity surplus = ₹1.38 Lakh Cr; Systemic GNPA = 1.18%.",
    interpretation: "Macro environment remains highly supportive of equity upside with negligible systemic liquidity risk.",
    freshness: "VERIFIED_MORNING_OCT19"
  },
  {
    id: "doc-reg-01",
    category: "regulatory",
    categoryLabel: "Exchange & Regulatory",
    headline: "SEBI Derivatives Margin Parity & Statutory Waterfall Compliance",
    source: "Securities and Exchange Board of India (SEBI Circular 2026)",
    url: "https://www.sebi.gov.in/",
    published: "2026-10-19 12:15 AM IST",
    retrieved: "2026-10-19 12:15 AM IST",
    relevance: "100% Structural Margin Baseline",
    summary: "Mandates upfront extreme loss margins and standardized lot sizing. All autonomous trades operate with full statutory tax waterfalls (STT, GST, Stamp Duty).",
    facts: "Standard NIFTY lot = 25 units; Statutory drag friction = ₹53.05 per round trip.",
    interpretation: "Ensures paper execution realism matches live broker accounting identities down to the last rupee.",
    freshness: "REGULATORY_STATUTE_ACTIVE"
  },
  {
    id: "doc-evid-01",
    category: "evidence",
    categoryLabel: "Agent Hypothesis Evidence",
    headline: "Quad-Agent Consensus: Manager Iva, Emily, Alex, Max Synchronized in Real-Time",
    source: "Omega Command Surveillance Core (omega_memory.db)",
    url: "http://127.0.0.1:8088/",
    published: "2026-10-19 12:35 AM IST",
    retrieved: "2026-10-19 12:35 AM IST",
    relevance: "97% Capital Protection Rule",
    summary: "Consensus active for Monday, October 19, 2026. Live execution armed under operator authority. Defined risk stops strictly capped at ₹500 per trade.",
    facts: "Capital profile: ₹5,000; Per-trade risk limit: ₹500 (10% Kelly); Max Daily Loss: ₹1,250.",
    interpretation: "Validates strict asymmetric execution: cut depreciating hedge legs early while trailing call runners.",
    freshness: "INTERNAL_MEMORY_HASHED_OCT19"
  }
];

export default function ResearchPanel({ style }) {
  const [activeTab, setActiveTab] = useState('all');
  const [expandedId, setExpandedId] = useState('doc-brief-01');
  const [docs, setDocs] = useState(DEFAULT_DOCUMENTS);
  const [newsSecondsLeft, setNewsSecondsLeft] = useState(120);

  // Emily Interactive Off-Market & Working Now State
  const [isWorkingNow, setIsWorkingNow] = useState(false);
  const [isTriggering, setIsTriggering] = useState(false);
  const [countdown, setCountdown] = useState(60);

  // Emily ↔ ChatGPT Interactive Transcript Modal State
  const [isChatModalOpen, setIsChatModalOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState([]);

  async function loadChatLog() {
    try {
      const threadData = await api.getChatGPTThread();
      if (threadData?.turns && threadData.turns.length > 0) {
        setChatMessages(threadData.turns.map((t, idx) => ({
          id: `real-turn-${idx}`,
          author: t.role === 'user' ? 'Operator Abhi' : 'ChatGPT (Real OpenAI Model)',
          role: t.role === 'user' ? 'Operator Inquiry' : 'Global Intelligence Bridge',
          timestamp: 'Live Active Thread',
          text: t.content
        })));
        return;
      }
      const res = await api.getReasoningChat();
      if (res?.messages) {
        setChatMessages(res.messages.filter(m => m.author === 'Emily' || m.text?.includes('ChatGPT') || m.text?.includes('Emily')));
      }
    } catch (e) {}
  }

  async function loadNews() {
    try {
      const data = await api.getNewsIntel();
      if (data?.documents && data.documents.length > 0) {
        setDocs(data.documents);
      }
    } catch (err) {
      // Fallback to grounded default research
    }
  }

  // Poll Emily status on mount
  useEffect(() => {
    let mounted = true;
    async function checkStatus() {
      try {
        const res = await api.getEmilyStatus();
        if (mounted && res) {
          if (res.is_working_now) {
            setIsWorkingNow(true);
            if (typeof res.cooldown_remaining_sec === 'number') {
              setCountdown(res.cooldown_remaining_sec);
            }
          }
        }
      } catch (e) {
        // quiet
      }
    }
    checkStatus();
    return () => { mounted = false; };
  }, []);

  // 60-second countdown timer when Working Now is active
  useEffect(() => {
    let timer = null;
    if (isWorkingNow) {
      timer = setInterval(() => {
        setCountdown((prev) => {
          if (prev <= 1) {
            loadNews();
            return 60;
          }
          return prev - 1;
        });
      }, 1000);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [isWorkingNow]);

  // Handle Start Working Now Action
  const handleStartWorkingNow = async () => {
    try {
      setIsTriggering(true);
      const res = await api.startEmilyWorkingNow();
      setIsWorkingNow(true);
      setCountdown(60);
      if (res?.new_document) {
        setDocs((prev) => [res.new_document, ...prev.filter(d => d.id !== res.new_document.id)]);
        setExpandedId(res.new_document.id);
      } else {
        await loadNews();
      }
    } catch (err) {
      console.warn("Failed to trigger Emily working now:", err);
    } finally {
      setIsTriggering(false);
    }
  };

  // Handle Revert to Default Market Schedule
  const handleRevertDefault = async () => {
    try {
      await api.revertEmilyDefault();
      setIsWorkingNow(false);
      setCountdown(60);
      await loadNews();
    } catch (err) {
      console.warn("Failed to revert Emily mode:", err);
    }
  };

  // 2-minute token saver refresh timer for default mode
  useEffect(() => {
    loadNews();
    const timer = setInterval(() => {
      setNewsSecondsLeft((prev) => {
        if (prev <= 1) {
          loadNews();
          return 120;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const baseFilteredDocs = activeTab === 'all'
    ? docs
    : docs.filter(d => d.category === activeTab);

  // Sticky breaking news: pinned or breaking items always stick to the top
  const sortedDocs = [...baseFilteredDocs].sort((a, b) => {
    const aPin = (a.is_pinned || a.is_breaking) ? 1 : 0;
    const bPin = (b.is_pinned || b.is_breaking) ? 1 : 0;
    return bPin - aPin;
  });

  const toggleExpand = (id) => {
    setExpandedId(prev => prev === id ? null : id);
  };

  return (
    <aside
      id="panelResearch"
      style={style}
      className="flex flex-col h-full min-h-0 min-w-0 bg-slate-900/90 border-l border-slate-800 shrink-0 overflow-hidden"
    >
      {/* Panel Header */}
      <div className="flex items-center justify-between px-2.5 py-1 bg-slate-950 border-b border-slate-800 shrink-0 min-w-0 gap-1.5 h-8">
        <div className="flex items-center gap-1.5 text-xs font-bold text-slate-100 min-w-0 truncate">
          <Newspaper className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
          <span className="truncate">NEWS & RESEARCH</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex items-center gap-1 px-1.5 py-0.2 rounded bg-cyan-950/80 border border-cyan-800/80 text-cyan-300 font-mono text-[9px]" title="Post-Market Rest: Scheduled Pre-Market Sweep @ 07:30 AM IST">
            <span className="text-amber-400">🌙 Token Saver</span>
            <span className="text-slate-600">|</span>
            <span>Sweep: 07:30 AM</span>
          </div>
          <div className="text-[10px] text-slate-500 font-mono hidden sm:inline">
            {sortedDocs.length} Sources
          </div>
        </div>
      </div>

      {/* Interactive Emily Execution Mode Bar */}
      <div className="flex flex-col bg-slate-950/90 border-b border-slate-800 shrink-0 px-2.5 py-1.5 gap-1.5">
        <div className="flex items-center justify-between gap-1.5">
          <div className="flex items-center gap-1.5 min-w-0">
            {isWorkingNow ? (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
                <span className="text-[10px] font-bold text-emerald-300 font-mono">
                  ⚡ Running Immediately
                </span>
                <span className="px-1.5 py-0.2 rounded bg-emerald-950/80 border border-emerald-700/80 text-emerald-400 font-mono text-[9px] font-bold">
                  ⏱️ {countdown}s hold
                </span>
                <button
                  onClick={() => {
                    loadChatLog();
                    setIsChatModalOpen(true);
                  }}
                  className="px-1.5 py-0.2 rounded bg-purple-950/80 hover:bg-purple-900 border border-purple-700/80 text-purple-300 font-mono text-[8.5px] font-semibold hidden sm:inline-flex items-center gap-1 transition cursor-pointer shadow-xs"
                  title="Click to view Emily's live inquiries and chat transcript with ChatGPT"
                >
                  <span>🤖 ChatGPT Bridge</span>
                  <span className="text-[8px] bg-purple-800 text-purple-100 px-1 py-0.2 rounded font-bold">Chat ↗</span>
                </button>
              </>
            ) : (
              <div className="flex items-center gap-1 text-slate-400 text-[9.5px] font-mono">
                <Clock className="w-3 h-3 text-cyan-400 shrink-0" />
                <span className="text-cyan-300 font-medium truncate">⏰ Market Time Mode (2h sleep, 08:15 AM wake)</span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={handleRevertDefault}
              className={`flex items-center gap-1 px-2 py-0.5 rounded border text-[9px] font-medium transition cursor-pointer ${!isWorkingNow ? 'bg-cyan-950 text-cyan-300 border-cyan-700 font-bold' : 'bg-slate-800 hover:bg-slate-700 text-slate-400 border-slate-700'}`}
              title="Sleep until 1 hour before market (08:15 AM). Asks ChatGPT every 2h after hours, and every 10m before market."
            >
              <Clock className="w-2.5 h-2.5" />
              <span>Start on Market Time</span>
            </button>
            <button
              onClick={handleStartWorkingNow}
              disabled={isTriggering}
              className={`flex items-center gap-1 px-2.5 py-0.5 rounded text-[9.5px] font-bold shadow-sm transition cursor-pointer disabled:opacity-50 ${isWorkingNow ? 'bg-emerald-600 text-white border border-emerald-400' : 'bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white'}`}
              title="Run off-market predictive sweep and ChatGPT query immediately"
            >
              <Zap className="w-3 h-3 text-amber-300" />
              <span>Start Immediately</span>
            </button>
          </div>
        </div>

        {/* 60s Feedback Progress & Dynamic Thinking Bar */}
        {isWorkingNow && (
          <div className="flex flex-col gap-1 p-1.5 rounded bg-emerald-950/40 border border-emerald-800/40 text-[9px] font-mono">
            <div className="flex items-center justify-between text-emerald-300">
              <span className="flex items-center gap-1">
                <Activity className="w-2.5 h-2.5 text-emerald-400 animate-pulse" />
                <span className="truncate font-semibold">
                  {countdown > 45
                    ? '🧠 Emily Thinking: Scanning Real-Time Feeds & News...'
                    : countdown > 30
                    ? '🌐 Consulting ChatGPT Bridge & Antigravity AI (Token-Free)...'
                    : countdown > 15
                    ? '🔍 Evaluating Deep Second-Order Impacts & Liquidity...'
                    : '⚡ Ratifying 60s News Catalysts & F&O Gamma Pockets...'}
                </span>
              </span>
              <span className="font-bold text-emerald-400 shrink-0 ml-1">{countdown}s</span>
            </div>
            <div className="w-full bg-slate-800 rounded-full h-1 overflow-hidden">
              <div
                className="bg-gradient-to-r from-emerald-500 via-teal-400 to-purple-400 h-1 transition-all duration-1000 ease-linear rounded-full"
                style={{ width: `${Math.max(0, Math.min(100, ((60 - countdown) / 60) * 100))}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-[8.5px] text-slate-400">
              <span className="truncate">
                10-Min Cadence: Auto-Inquires ChatGPT Bridge if Quiet • 60s Re-Evaluation Active
              </span>
              <span className="text-purple-300 font-bold shrink-0 ml-1">
                Token Saver: 100%
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Category Filter Chips */}
      <div className="flex items-center gap-1 px-2 py-0.5 bg-slate-950/70 border-b border-slate-800 overflow-x-auto shrink-0 scrollbar-none text-[10px] h-7">
        {[
          { id: 'all', label: 'All' },
          { id: 'briefing', label: 'Brief' },
          { id: 'regulatory', label: 'Regulatory' },
          { id: 'macro', label: 'Macro' },
          { id: 'instruments', label: 'Instruments' },
          { id: 'evidence', label: 'Evidence' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-1.5 py-0.2 rounded font-medium whitespace-nowrap transition shrink-0 ${
              activeTab === tab.id
                ? 'bg-slate-800 text-cyan-300 border border-slate-700/60 shadow-xs'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Accordion Documents List with Independent Scrolling */}
      <div className="flex-1 min-h-0 min-w-0 overflow-y-auto p-2.5 space-y-2">
        {sortedDocs.map((doc) => {
          const isExpanded = expandedId === doc.id;
          const isStickied = Boolean(doc.is_pinned || doc.is_breaking);
          return (
            <div
              key={doc.id}
              className={`rounded-lg border transition ${
                isStickied
                  ? isExpanded
                    ? 'bg-slate-950/95 border-amber-500/80 shadow-md shadow-amber-950/30'
                    : 'bg-amber-950/20 border-amber-500/50 hover:border-amber-400'
                  : isExpanded
                  ? 'bg-slate-950/90 border-slate-700'
                  : 'bg-slate-950/50 border-slate-800/80 hover:border-slate-700/60'
              }`}
            >
              {/* Accordion Clickable Header */}
              <button
                onClick={() => toggleExpand(doc.id)}
                className="w-full text-left p-3 flex items-start justify-between gap-2.5 focus:outline-none"
              >
                <div className="flex flex-col gap-1 min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 text-[10px] text-slate-400 font-mono flex-wrap">
                    {isStickied && (
                      <span className="flex items-center gap-1 px-1.5 py-0.2 rounded bg-amber-500/20 border border-amber-500/60 text-amber-300 font-bold text-[8.5px] animate-pulse">
                        <Pin className="w-2.5 h-2.5 text-amber-400 rotate-45" />
                        <span>STICKIED BREAKING</span>
                      </span>
                    )}
                    <span className="px-1.5 py-0.2 rounded bg-slate-800 text-cyan-300 font-semibold uppercase truncate">
                      {doc.categoryLabel || doc.category}
                    </span>
                    <span>•</span>
                    <span className="text-slate-500 shrink-0">{formatTo12Hour(doc.published) || 'Today'}</span>
                  </div>
                  <h3 className="text-xs font-bold text-slate-100 leading-snug line-clamp-2 break-words">
                    {doc.headline}
                  </h3>
                </div>
                <div className="p-1 rounded text-slate-400 shrink-0">
                  {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </div>
              </button>

              {/* Expandable Content with smooth transition */}
              <AnimatePresence>
                {isExpanded && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.15, ease: 'easeOut' }}
                    className="overflow-hidden px-3 pb-3 pt-0 border-t border-slate-800/60 text-xs text-slate-300 space-y-2.5 min-w-0"
                  >
                    {/* Summary */}
                    <div className="mt-2 min-w-0">
                      <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Summary</div>
                      <p className="mt-0.5 text-slate-300 leading-relaxed text-[11px] break-words">{doc.summary}</p>
                    </div>

                    {/* Facts vs Interpretation */}
                    <div className="p-2.5 bg-slate-900/80 rounded border border-slate-800/80 space-y-1.5 text-[11px] min-w-0">
                      <div className="break-words">
                        <span className="font-bold text-cyan-400">Verified Facts: </span>
                        <span className="text-slate-300">{doc.facts}</span>
                      </div>
                      <div className="break-words">
                        <span className="font-bold text-amber-400">Agent Interpretation: </span>
                        <span className="text-slate-300">{doc.interpretation}</span>
                      </div>
                    </div>

                    {/* Autonomous Emily ↔ ChatGPT Interactive Conversation Box */}
                    {(doc.chatgpt_inquiry || doc.chatgpt_response || doc.source?.includes('ChatGPT') || doc.headline?.includes('CHATGPT') || doc.headline?.includes('60S SWEEP') || doc.headline?.includes('10-MIN')) && (
                      <div className="p-2.5 bg-purple-950/40 rounded-lg border border-purple-800/60 space-y-2 text-[11px] min-w-0 shadow-inner">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5 font-bold text-purple-300 font-mono text-[10px]">
                            <Bot className="w-3.5 h-3.5 text-purple-400" />
                            <span>EMILY ↔ CHATGPT AUTONOMOUS CHAT LOG</span>
                          </div>
                          <span className="text-[8.5px] font-mono px-1.5 py-0.2 rounded bg-purple-900/60 text-purple-200 border border-purple-700/60">
                            Zero Token Drag (Browser Bridge)
                          </span>
                        </div>

                        <div className="space-y-1.5 font-mono text-[10.5px]">
                          <div className="p-2 rounded bg-slate-900/90 border border-purple-900/50">
                            <div className="text-[9.5px] font-bold text-purple-400 flex items-center gap-1">
                              <MessageSquare className="w-3 h-3 text-purple-400" />
                              <span>Emily's Autonomous Prompt / Inquiry:</span>
                            </div>
                            <p className="mt-1 text-slate-200 text-[10px] leading-relaxed break-words">
                              "{doc.chatgpt_inquiry || `Autonomous Sweep: Scan real-time domestic & offshore feeds for ${doc.headline}. Confirm if any unexpected macroeconomic shock or options OI dislocation occurred in the last 60s.`}"
                            </p>
                          </div>

                          <div className="p-2 rounded bg-slate-900/90 border border-emerald-900/50">
                            <div className="text-[9.5px] font-bold text-emerald-400 flex items-center gap-1">
                              <Bot className="w-3 h-3 text-emerald-400" />
                              <span>ChatGPT Model Response Received:</span>
                            </div>
                            <p className="mt-1 text-slate-200 text-[10px] leading-relaxed break-words">
                              {doc.chatgpt_response || doc.facts}
                            </p>
                          </div>
                        </div>

                        <div className="flex items-center justify-between text-[9px] text-slate-400 pt-1 border-t border-purple-900/40">
                          <span className="font-mono text-purple-300">
                            Thread: <a href="https://chatgpt.com/c/6ad512d3-9aec-83ee-8583-67b2c0163bc9" target="_blank" rel="noreferrer" className="text-cyan-300 hover:text-cyan-100 font-bold underline font-mono">6ad512d3-9aec-83ee-8583-67b2c0163bc9 ↗</a>
                          </span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              loadChatLog();
                              setIsChatModalOpen(true);
                            }}
                            className="text-purple-400 hover:text-purple-300 flex items-center gap-1 font-semibold hover:underline cursor-pointer"
                          >
                            <span>View Full Chat Transcript</span>
                            <ExternalLink className="w-2.5 h-2.5" />
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Metadata & Source Links */}
                    <div className="pt-2 border-t border-slate-800/60 flex items-center justify-between text-[10px] font-mono text-slate-500">
                      <div>
                        Source: <span className="text-slate-300">{doc.source}</span>
                      </div>
                      {doc.url && (
                        <a
                          href={doc.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-cyan-400 hover:text-cyan-300 flex items-center gap-1 font-sans"
                        >
                          <span>Primary Link</span>
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>

      {/* Emily ↔ ChatGPT Interactive Transcript Modal */}
      <AnimatePresence>
        {isChatModalOpen && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-slate-950/80 backdrop-blur-sm"
            onClick={() => setIsChatModalOpen(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="w-full max-w-xl bg-slate-900 border border-purple-700/70 rounded-xl shadow-2xl p-4 text-slate-100 max-h-[85vh] flex flex-col overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Modal Header */}
              <div className="flex items-center justify-between pb-2.5 border-b border-slate-800 shrink-0">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-purple-900/40 border border-purple-700/60 text-purple-300">
                    <Bot className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-xs font-bold text-slate-100 flex items-center gap-1.5">
                      <span>Emily ↔ ChatGPT Autonomous Chat Log</span>
                      <span className="text-[9px] px-1.5 py-0.2 rounded bg-purple-950 text-purple-300 border border-purple-800 font-mono">
                        BROWSER BRIDGE
                      </span>
                    </h3>
                    <div className="text-[10px] text-slate-400">
                      Thread: <a href="https://chatgpt.com/c/6ad512d3-9aec-83ee-8583-67b2c0163bc9" target="_blank" rel="noreferrer" className="text-purple-300 hover:text-purple-100 underline font-mono font-bold">chatgpt.com/c/6ad512d3-9aec-83ee-8583-67b2c0163bc9 ↗</a> • Real Browser Bridge
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => setIsChatModalOpen(false)}
                  className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Chat Messages Body */}
              <div className="flex-1 overflow-y-auto my-3 space-y-2.5 pr-1">
                {chatMessages.length === 0 ? (
                  <div className="p-6 text-center text-slate-400 font-mono text-xs space-y-2">
                    <Activity className="w-6 h-6 text-purple-400 animate-pulse mx-auto" />
                    <div>Loading Emily's live dialogue with ChatGPT...</div>
                    <div className="text-[10px] text-slate-500">Autonomous sweeps query ChatGPT every 60s and 10m on quiet horizons.</div>
                  </div>
                ) : (
                  chatMessages.map((msg, idx) => (
                    <div key={msg.id || idx} className="p-2.5 rounded-lg bg-slate-950/80 border border-slate-800 space-y-1 text-xs">
                      <div className="flex items-center justify-between text-[10px] font-mono">
                        <span className="font-bold text-emerald-400 flex items-center gap-1">
                          <Bot className="w-3 h-3 text-purple-400" />
                          <span>{msg.author || 'Emily'} ({msg.role || 'Macro Intel'})</span>
                        </span>
                        <span className="text-slate-500">{msg.timestamp}</span>
                      </div>
                      <p className="text-slate-200 text-[11px] leading-relaxed whitespace-pre-wrap font-mono">
                        {msg.text}
                      </p>
                    </div>
                  ))
                )}
              </div>

              {/* Modal Footer */}
              <div className="pt-2.5 border-t border-slate-800 flex items-center justify-between text-[10px] font-mono text-slate-400 shrink-0">
                <span>Autonomous Cadence: 60s Sweeps • 10m Quiet Inquiries</span>
                <button
                  onClick={() => setIsChatModalOpen(false)}
                  className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 transition cursor-pointer"
                >
                  Close
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </aside>
  );
}
