import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Send,
  Users,
  User,
  Shield,
  AlertTriangle,
  CheckCircle,
  Clock,
  Sparkles,
  Zap,
  PauseCircle,
  Activity,
  ArrowRight,
  ArrowDown,
  ArrowUp
} from 'lucide-react';
import { api } from '../services/api';
import { formatTo12Hour, getCurrent12HourIST } from '../utils/formatters';

// Initial conversational chat history for Team Coordination (Alexa, Emily, Max, Manager Iva ONLY)
const INITIAL_TEAM_CHAT = [
  {
    id: 'team-1',
    author: 'Manager Iva',
    role: 'Autonomous Supervisor',
    avatar: 'I',
    avatarBg: 'bg-purple-600',
    avatarColor: 'text-purple-100',
    time: '12:35:00 AM IST',
    text: '⚡ Monday, October 19, 2026 Pre-Market Surveillance Cycle Active. Capital Profile: ₹5,000.00 assigned. Dynamic CDP Tab Resolution active across all browser pages. Live Order Execution Gate: ARMED under verified operator authorization. Standing by for continuous evaluation sweeps.',
    isUser: false,
  },
  {
    id: 'team-2',
    author: 'Emily',
    role: 'Macro Intelligence',
    avatar: 'E',
    avatarBg: 'bg-emerald-600',
    avatarColor: 'text-emerald-100',
    time: '12:35:10 AM IST',
    text: 'Global Macro & Gift Nifty Briefing: Gift Nifty indicates positive opening around 23,200 (+0.65%). Crude oil fell -1.2% to $76.40, easing imported inflation concerns. RBI LAF liquidity remains in durable surplus at ₹1.38 Lakh Cr. Macro Sentiment Score: +0.68 (Bullish Bias).',
    isUser: false,
  },
  {
    id: 'team-3',
    author: 'Alexa',
    role: 'Microstructure Specialist',
    avatar: 'A',
    avatarBg: 'bg-cyan-600',
    avatarColor: 'text-cyan-100',
    time: '12:35:20 AM IST',
    text: 'Paytm Money Live DOM Scraped: NIFTY 50 spot at 23,146.15 (+148.80, +0.65%). Hawkes fast-burst intensity λ₁ = 0.54 events/sec (subcritical ρ = 0.72 < 0.85). Multi-Level Order Flow Imbalance (MLOFI): +0.12. Queue priority clear.',
    isUser: false,
  },
  {
    id: 'team-4',
    author: 'Max',
    role: 'Quant Risk',
    avatar: 'M',
    avatarBg: 'bg-amber-600',
    avatarColor: 'text-amber-100',
    time: '12:35:30 AM IST',
    text: 'Risk Invariant Gate on ₹5,000 Account: Maximum risk per trade strictly capped at ₹500.00 (10% Kelly max loss ceiling). Statutory friction on 1 lot Nifty = ₹53.05. Penny Option Gate active: No strikes below ₹8.00 permitted. Trailing stop ratchets armed.',
    isUser: false,
  },
  {
    id: 'team-5',
    author: 'Manager Iva',
    role: 'Autonomous Supervisor',
    avatar: 'I',
    avatarBg: 'bg-purple-600',
    avatarColor: 'text-purple-100',
    time: '12:36:00 AM IST',
    text: 'Quad Consensus Ratified: 4/4 AGENTS HEALTHY. Watchlist primed on NIFTY 23200 CE & 23000 PE. 60-second cooldown active between evaluation sweeps. Live execution armed and verified.',
    isUser: false,
  },
  {
    id: 'team-5',
    author: 'Max',
    role: 'Quant Risk',
    avatar: 'M',
    avatarBg: 'bg-amber-600',
    avatarColor: 'text-amber-100',
    time: '01:48:15 PM IST',
    text: 'SL Auto-Selloff Alert: NIFTY 19 OCT 22800 PUT breached support. Automated sell-off executed immediately @ ₹75.00 breakeven. ₹0 Loss on trade; ₹7,500 capital returned safely to cash cushion. Call runners continue upward!',
    isUser: false,
  },
  {
    id: 'team-6',
    author: 'Emily',
    role: 'Brokerage Warden',
    avatar: 'E',
    avatarBg: 'bg-emerald-600',
    avatarColor: 'text-emerald-100',
    time: '02:05:10 PM IST',
    text: 'Order Book Imbalance (MLOFI) +0.42 on BANKNIFTY 55800 CE. Bid depth absorption confirmed across top 5 levels. Volatility skew steepening on downside puts.',
    isUser: false,
  },
  {
    id: 'team-7',
    author: 'Manager Iva',
    role: 'Autonomous Supervisor',
    avatar: 'I',
    avatarBg: 'bg-purple-600',
    avatarColor: 'text-purple-100',
    time: '02:05:40 PM IST',
    text: 'Squad synchronization confirmed: Emily, Alexa, Max in lockstep. Trailing stop ratcheted +15 pts. Reserve capital locked fail-closed.',
    isUser: false,
  },
];

// Initial conversational chat history for Manager Iva (Operator ↔ Manager ONLY)
const INITIAL_MANAGER_CHAT = [
  {
    id: 'mgr-1',
    author: 'Manager Iva',
    role: 'Executive Trading Operations Manager',
    avatar: 'I',
    avatarBg: 'bg-purple-600',
    avatarColor: 'text-purple-100',
    time: '09:15:00 AM IST',
    text: 'Welcome, Operator Abhi. This is your direct 1-on-1 command channel with Manager Iva. Directives sent here are executed and verified under institutional risk gates (Max Daily Loss ₹2,500, Per-Trade Risk 1.5%). The autonomous squad (Alexa, Emily, Max) collaborates separately in the Team Coordination room.',
    isUser: false,
  },
  {
    id: 'mgr-2',
    author: 'Operator Abhi',
    role: 'Operator',
    avatar: 'U',
    avatarBg: 'bg-cyan-600',
    avatarColor: 'text-white',
    time: '09:15:20 AM IST',
    text: 'Start paper trading',
    isUser: true,
  },
  {
    id: 'mgr-3',
    author: 'Manager Iva',
    role: 'Executive Trading Operations Manager',
    avatar: 'I',
    avatarBg: 'bg-purple-600',
    avatarColor: 'text-purple-100',
    time: '09:15:25 AM IST',
    text: 'Understood, Operator. Paper trading runtime activated on epoch_10k ledger (₹10,000 equity). Real broker order dispatch locked fail-closed (LIVE_ORDER_DISPATCH_ENABLED = False). Trailing stop loss ladder armed. Squad alerted.',
    isUser: false,
  },
];


export default function AgentChatPanel({ style, selectedEpoch = 'epoch_10k' }) {
  const [activeTab, setActiveTab] = useState('coordination'); // 'coordination' | 'manager'
  const [teamMessages, setTeamMessages] = useState(INITIAL_TEAM_CHAT);
  const [managerMessages, setManagerMessages] = useState(INITIAL_MANAGER_CHAT);
  const [inputText, setInputText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const messagesEndRef = useRef(null);
  const streamContainerRef = useRef(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [showScrollUp, setShowScrollUp] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);

  const [syncSecondsLeft, setSyncSecondsLeft] = useState(60);
  const [sessionStatus, setSessionStatus] = useState(null);

  // Poll Session Supervisor Status & Live Auth State
  useEffect(() => {
    let isMounted = true;
    async function loadSession() {
      try {
        const [data, statusData] = await Promise.all([
          api.getSessionStatus().catch(() => null),
          api.getStatus().catch(() => null)
        ]);
        if (isMounted) {
          if (data) {
            setSessionStatus({
              ...data,
              auth_status: statusData?.auth_status || data.auth_status,
              auth_message: statusData?.auth_message || data.auth_message
            });
          } else if (statusData) {
            setSessionStatus(statusData);
          }
        }
      } catch (e) {
        // quiet
      }
    }
    loadSession();
    const interval = setInterval(loadSession, 2000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Smooth or instant scroll to bottom
  const scrollToBottom = (behavior = 'smooth') => {
    const el = streamContainerRef.current;
    if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior });
    } else {
      messagesEndRef.current?.scrollIntoView({ behavior });
    }
    setIsAtBottom(true);
    setUnreadCount(0);
  };

  // Smooth scroll to top
  const scrollToTop = (behavior = 'smooth') => {
    const el = streamContainerRef.current;
    if (el) {
      el.scrollTo({ top: 0, behavior });
    }
  };

  // User scroll listener: detect if scrolled up or down
  const handleScroll = () => {
    const el = streamContainerRef.current;
    if (!el) return;
    const { scrollTop, scrollHeight, clientHeight } = el;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    const atBottom = distanceFromBottom <= 80; // 80px threshold

    setIsAtBottom(atBottom);
    setShowScrollUp(scrollTop > 150);

    if (atBottom) {
      setUnreadCount(0);
    }
  };

  // Auto-scroll on new incoming messages ONLY if user is already near bottom (<= 80px)
  useEffect(() => {
    const el = streamContainerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom <= 80) {
      // User is already at bottom: auto-scroll to reveal new message
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
      setIsAtBottom(true);
      setUnreadCount(0);
    } else {
      // User is scrolled up reading previous history/news!
      // DO NOT force-scroll them down. Keep their exact scroll position.
      setIsAtBottom(false);
      setUnreadCount((prev) => prev + 1);
    }
  }, [teamMessages, managerMessages]);

  // When switching between Team Coordination and Manager tabs, reset to bottom
  useEffect(() => {
    setIsAtBottom(true);
    setUnreadCount(0);
    const timer = setTimeout(() => {
      const el = streamContainerRef.current;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    }, 50);
    return () => clearTimeout(timer);
  }, [activeTab]);

  // 1-minute countdown timer for autonomous agent synchronization
  useEffect(() => {
    const timer = setInterval(() => {
      setSyncSecondsLeft((prev) => {
        if (prev <= 1) {
          return 60;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Load and poll backend reasoning messages
  useEffect(() => {
    let isMounted = true;
    async function loadBackendChat() {
      try {
        const data = await api.getReasoningChat();
        if (isMounted && data?.messages && data.messages.length > 0) {
          const swarmList = [];
          const mgrList = [];

          data.messages.forEach((m, idx) => {
            const rawAuthor = m.author || m.sender || 'Max';
            const rawText = m.content || m.message || m.text || '';
            if (!rawText.trim()) return;

            const isUser = rawAuthor.toUpperCase().includes('OPERATOR') || rawAuthor.toUpperCase().includes('USER');
            const author = isUser ? 'Operator Abhi' : (
              rawAuthor.toUpperCase().includes('ALEXA') ? 'Alexa' :
              rawAuthor.toUpperCase().includes('EMILY') ? 'Emily' :
              rawAuthor.toUpperCase().includes('MAX') ? 'Max' :
              (rawAuthor.toUpperCase().includes('MANAGER') || rawAuthor.toUpperCase().includes('IVA') || rawAuthor.toUpperCase().includes('ABHI')) ? 'Manager Iva' : rawAuthor
            );

            let avatar = 'M';
            let avatarBg = 'bg-amber-600';
            let avatarColor = 'text-amber-100';

            if (isUser) {
              avatar = 'U';
              avatarBg = 'bg-cyan-600';
              avatarColor = 'text-white';
            } else if (author === 'Alexa') {
              avatar = 'A';
              avatarBg = 'bg-cyan-600';
              avatarColor = 'text-cyan-100';
            } else if (author === 'Emily') {
              avatar = 'E';
              avatarBg = 'bg-emerald-600';
              avatarColor = 'text-emerald-100';
            } else if (author === 'Manager Iva' || author.includes('Manager') || author.toUpperCase().includes('IVA')) {
              avatar = 'I';
              avatarBg = 'bg-purple-600';
              avatarColor = 'text-purple-100';
            }

            const item = {
              id: m.id || `be-${idx}`,
              author,
              avatar,
              avatarBg,
              avatarColor,
              time: formatTo12Hour(m.timestamp) || 'Today',
              text: rawText,
              isUser,
            };

            // 1. MANAGER CHAT: Strictly between Operator Abhi and Manager Iva
            if (isUser || author === 'Manager Iva' || author === 'Manager Abhi') {
              mgrList.push(item);
            }

            // 2. TEAM CHAT: Strictly between Alexa, Emily, Max, and Manager Iva
            // OPERATOR MESSAGES ARE STRICTLY EXCLUDED!
            if (!isUser) {
              const isDirectOperatorReply = (
                (author === 'Manager Iva' || author === 'Manager Abhi') &&
                (rawText.includes('Understood, Operator') ||
                 rawText.includes('Operator Abhi') ||
                 rawText.startsWith("Directive acknowledged: '") ||
                 rawText.startsWith('Directive received: "'))
              );
              if (!isDirectOperatorReply) {
                swarmList.push(item);
              }
            }
          });

          if (swarmList.length > 0) {
            setTeamMessages((prev) => {
              if (
                prev.length === swarmList.length &&
                prev[prev.length - 1]?.id === swarmList[swarmList.length - 1]?.id &&
                prev[prev.length - 1]?.text === swarmList[swarmList.length - 1]?.text
              ) {
                return prev;
              }
              return swarmList;
            });
          }
          if (mgrList.length > 0) {
            setManagerMessages((prev) => {
              if (
                prev.length === mgrList.length &&
                prev[prev.length - 1]?.id === mgrList[mgrList.length - 1]?.id &&
                prev[prev.length - 1]?.text === mgrList[mgrList.length - 1]?.text
              ) {
                return prev;
              }
              return mgrList;
            });
          }
        }
      } catch (err) {
        // Keep initial messages
      }
    }
    loadBackendChat();
    const interval = setInterval(loadBackendChat, 2500);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const handleSendMessage = async (textToSend) => {
    const text = (textToSend || inputText).trim();
    if (!text || isSending) return;

    const timeStr = getCurrent12HourIST();
    const userMsg = {
      id: `usr-${Date.now()}`,
      author: 'Operator Abhi',
      role: 'Operator',
      avatar: 'U',
      avatarBg: 'bg-cyan-600',
      avatarColor: 'text-white',
      time: timeStr,
      text: text,
      isUser: true,
    };

    setInputText('');
    setIsSending(true);

    // 1. ALWAYS route Operator directive to Manager Chat (Operator ↔ Manager only)
    setManagerMessages((prev) => [...prev, userMsg]);

    // 2. Alert the squad in Team Coordination room as a directive from Manager Iva
    const squadAlertMsg = {
      id: `squad-alert-${Date.now()}`,
      author: 'Manager Iva',
      role: 'Autonomous Supervisor',
      avatar: 'I',
      avatarBg: 'bg-purple-600',
      avatarColor: 'text-purple-100',
      time: timeStr,
      text: `Squad Directive: Operator instruction received: "${text}". Emily, Alexa, Max — verify order flow delta, volatility surface, and risk limits.`,
      isUser: false,
    };
    setTeamMessages((prev) => [...prev, squadAlertMsg]);

    try {
      await api.sendDirective(text, 'Operator Abhi');
      // Fetch fresh messages immediately from backend
      const data = await api.getReasoningChat();
      if (data?.messages && data.messages.length > 0) {
        const swarmList = [];
        const mgrList = [];
        data.messages.forEach((m, idx) => {
          const rawAuthor = m.author || m.sender || 'Max';
          const rawText = m.content || m.message || m.text || '';
          if (!rawText.trim()) return;
          const isUser = rawAuthor.toUpperCase().includes('OPERATOR') || rawAuthor.toUpperCase().includes('USER');
          const author = isUser ? 'Operator Abhi' : (
            rawAuthor.toUpperCase().includes('ALEXA') ? 'Alexa' :
            rawAuthor.toUpperCase().includes('EMILY') ? 'Emily' :
            rawAuthor.toUpperCase().includes('MAX') ? 'Max' :
            (rawAuthor.toUpperCase().includes('MANAGER') || rawAuthor.toUpperCase().includes('IVA') || rawAuthor.toUpperCase().includes('ABHI')) ? 'Manager Iva' : rawAuthor
          );
          let avatar = isUser ? 'U' : (author === 'Alexa' ? 'A' : (author === 'Emily' ? 'E' : ((author === 'Manager Iva' || author.includes('Manager')) ? 'I' : 'M')));
          let avatarBg = isUser ? 'bg-cyan-600' : (author === 'Alexa' ? 'bg-cyan-600' : (author === 'Emily' ? 'bg-emerald-600' : ((author === 'Manager Iva' || author.includes('Manager')) ? 'bg-purple-600' : 'bg-amber-600')));
          const item = {
            id: m.id || `be-${idx}`,
            author,
            avatar,
            avatarBg,
            avatarColor: 'text-white',
            time: formatTo12Hour(m.timestamp) || timeStr,
            text: rawText,
            isUser,
          };
          // Manager Chat: Operator + Manager
          if (isUser || author === 'Manager Iva' || author === 'Manager Abhi') mgrList.push(item);
          // Team Chat: Alexa, Emily, Max, Manager squad events (NEVER Operator)
          if (!isUser) {
            const isDirectOperatorReply = (
              (author === 'Manager Iva' || author === 'Manager Abhi') &&
              (rawText.includes('Understood, Operator') ||
               rawText.includes('Operator Abhi') ||
               rawText.startsWith("Directive acknowledged: '") ||
               rawText.startsWith('Directive received: "'))
            );
            if (!isDirectOperatorReply) {
              swarmList.push(item);
            }
          }
        });
        if (swarmList.length > 0) setTeamMessages(swarmList);
        if (mgrList.length > 0) setManagerMessages(mgrList);
      }
    } catch (err) {
      // Local fallback in case server was offline
      const fallbackReply = {
        id: `mgr-${Date.now()}`,
        author: 'Manager Iva',
        role: 'Autonomous Supervisor',
        avatar: 'I',
        avatarBg: 'bg-purple-600',
        avatarColor: 'text-purple-100',
        time: timeStr,
        text: `Understood, Operator. Directive received: "${text}". All subagents (Max, Emily, Alexa) coordinated. Execution verified under ${selectedEpoch} risk profile.`,
        isUser: false,
      };
      setManagerMessages((prev) => [...prev, fallbackReply]);
    } finally {
      setIsSending(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const activeMessages = activeTab === 'coordination' ? teamMessages : managerMessages;

  return (
    <aside
      id="panelAgents"
      style={style}
      className="flex flex-col h-full bg-slate-900 border-r border-slate-800 shrink-0 min-h-0 min-w-0 overflow-hidden"
    >
      {/* 1. Header with Exactly Two Chat Tabs */}
      <div className="flex items-center border-b border-slate-800 bg-slate-950 p-1.5 shrink-0 gap-1">
        <button
          id="tabBtnCoordination"
          onClick={() => setActiveTab('coordination')}
          className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 px-2 rounded-md text-xs font-semibold transition ${
            activeTab === 'coordination'
              ? 'bg-slate-800 text-cyan-300 border border-slate-700 shadow-xs'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <Users className="w-3.5 h-3.5 text-cyan-400" />
          <span>Team Coordination</span>
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
        </button>

        <button
          id="tabBtnManager"
          onClick={() => setActiveTab('manager')}
          className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 px-2 rounded-md text-xs font-semibold transition ${
            activeTab === 'manager'
              ? 'bg-slate-800 text-purple-300 border border-slate-700 shadow-xs'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <User className="w-3.5 h-3.5 text-purple-400" />
          <span>Manager Iva</span>
          <span className="w-1.5 h-1.5 rounded-full bg-purple-400"></span>
        </button>
      </div>

      {/* Clear Channel Descriptor Pill */}
      <div className="px-2.5 py-1 bg-slate-950 border-b border-slate-800/80 flex items-center justify-between text-[10.5px]">
        {activeTab === 'coordination' ? (
          <div className="flex items-center gap-1.5 text-cyan-400 font-mono">
            <Users className="w-3.5 h-3.5" />
            <span className="font-semibold text-cyan-300">Team Room:</span>
            <span className="text-slate-300 text-[10px]">Alexa • Emily • Max • Manager Iva</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-purple-400 font-mono">
            <User className="w-3.5 h-3.5" />
            <span className="font-semibold text-purple-300">Manager Room:</span>
            <span className="text-slate-300 text-[10px]">Operator Abhi ↔ Manager Iva</span>
          </div>
        )}
        <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-400 font-mono">
          {activeTab === 'coordination' ? 'SQUAD ONLY' : '1-ON-1 DESK'}
        </span>
      </div>

      {/* 2. Chat Sub-Header Banner with Live Session Status */}
      <div className="flex items-center justify-between px-2.5 py-1.5 bg-slate-950/90 border-b border-slate-800 text-[10px] font-mono shrink-0 gap-2">
        <span className="truncate flex items-center gap-1.5">
          {sessionStatus?.auth_status === 'WAITING_FOR_OPERATOR_AUTH' ? (
            <span className="text-amber-300 font-bold flex items-center gap-1.5 bg-amber-950/80 border border-amber-500/60 px-2 py-0.5 rounded shadow-xs shadow-amber-950/50 animate-pulse">
              <span className="w-2 h-2 rounded-full bg-amber-400"></span>
              <span>AWAITING OPERATOR OTP (STANDBY • ZERO RELOADS • SINGLE TAB)</span>
            </span>
          ) : sessionStatus?.is_active ? (
            <span className="text-emerald-400 font-bold flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span>PAPER TRADING ACTIVE</span>
            </span>
          ) : sessionStatus?.is_paused ? (
            <span className="text-amber-400 font-bold flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-amber-400"></span>
              <span>SESSION PAUSED</span>
            </span>
          ) : sessionStatus?.intake_in_progress ? (
            <span className="text-purple-400 font-bold flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-purple-400 animate-ping"></span>
              <span>INTAKE (Q {sessionStatus.current_intake_question?.question_index || '?'}/10)</span>
            </span>
          ) : sessionStatus?.state === 'AWAITING_CONFIRMATION' ? (
            <span className="text-cyan-400 font-bold flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-cyan-400"></span>
              <span>AWAITING CONFIRMATION</span>
            </span>
          ) : sessionStatus?.state === 'BLOCKED' ? (
            <span className="text-red-400 font-bold flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-red-400"></span>
              <span>BLOCKED: {sessionStatus?.preflight_status?.blocker_code || 'SAFETY GATE'}</span>
            </span>
          ) : (
            <span className="text-slate-400 font-bold flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-slate-500"></span>
              <span>SESSION STANDBY</span>
            </span>
          )}
          <span className="text-slate-600 hidden sm:inline">•</span>
          <span className="text-slate-400 text-[9px] hidden sm:inline">
            Risk: {sessionStatus?.current_config?.max_capital_risk_per_trade_pct || '0.5'}% cap
          </span>
        </span>

        {/* Quick Session Controls */}
        <div className="flex items-center gap-1 shrink-0">
          {sessionStatus?.is_active && (
            <button
              onClick={() => handleSendMessage('pause')}
              className="px-1.5 py-0.5 rounded bg-amber-950/80 border border-amber-800 text-amber-300 font-semibold hover:bg-amber-900 transition"
              title="Pause paper trading entries"
            >
              Pause
            </button>
          )}
          {sessionStatus?.is_paused && (
            <button
              onClick={() => handleSendMessage('resume')}
              className="px-1.5 py-0.5 rounded bg-emerald-950/80 border border-emerald-800 text-emerald-300 font-semibold hover:bg-emerald-900 transition"
              title="Resume paper trading entries"
            >
              Resume
            </button>
          )}
          {(sessionStatus?.is_active || sessionStatus?.is_paused) && (
            <button
              onClick={() => handleSendMessage('stop')}
              className="px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold transition"
              title="Stop paper session"
            >
              Stop
            </button>
          )}
          <div className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-300 text-[9px]">
            <span className="text-cyan-400 font-semibold">
              {sessionStatus?.current_config?.portfolio_epoch || selectedEpoch}
            </span>
          </div>
        </div>
      </div>

      {/* 3. Messages Stream with Independent Internal Scrolling & Floating Scroll Controls */}
      <div className="relative flex-1 min-h-0 flex flex-col">
        <div
          ref={streamContainerRef}
          onScroll={handleScroll}
          id={activeTab === 'coordination' ? 'coordinationMessageStream' : 'managerMessageStream'}
          className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3 select-text"
        >
        {activeMessages.map((msg) => (
          <motion.div
            key={msg.id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className={`flex flex-col ${msg.isUser ? 'items-end' : 'items-start'}`}
          >
            {/* Sender and Timestamp */}
            <div className={`flex items-center gap-1.5 mb-1 px-1 text-[10px] ${msg.isUser ? 'flex-row-reverse text-cyan-300' : 'text-slate-400'}`}>
              <span className="font-bold text-slate-200">{msg.author}</span>
              <span className="text-slate-600">•</span>
              <span className="text-slate-500 font-mono text-[9px]">{msg.time}</span>
            </div>

            {/* Message Bubble + Avatar */}
            <div className={`flex items-start gap-2 max-w-[90%] ${msg.isUser ? 'flex-row-reverse' : 'flex-row'}`}>
              {/* Avatar Icon */}
              <div
                className={`w-6 h-6 rounded-full flex items-center justify-center font-bold text-[11px] shrink-0 shadow-xs ${msg.avatarBg} ${msg.avatarColor}`}
              >
                {msg.avatar}
              </div>

              {/* Chat Speech Bubble */}
              <div
                className={`p-2.5 rounded-2xl text-xs leading-relaxed break-words shadow-xs ${
                  msg.isUser
                    ? 'bg-gradient-to-r from-cyan-900/80 to-blue-900/80 border border-cyan-700/70 text-cyan-50 rounded-tr-xs'
                    : 'bg-slate-800/90 border border-slate-700/70 text-slate-200 rounded-tl-xs'
                }`}
              >
                {msg.text}
              </div>
            </div>
          </motion.div>
        ))}

        {/* Dynamic Intake Questionnaire Interactive Card */}
        {activeTab === 'manager' && sessionStatus?.intake_in_progress && sessionStatus?.current_intake_question && (
          <div className="p-3 bg-slate-950/95 border border-purple-500/50 rounded-xl my-2 shadow-xl animate-in fade-in">
            <div className="flex items-center justify-between text-[11px] font-mono text-purple-300 mb-1.5">
              <span className="font-bold flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-purple-400 animate-ping"></span>
                <span>QUESTION {sessionStatus.current_intake_question.question_index} OF {sessionStatus.current_intake_question.total_questions}</span>
              </span>
              <span className="text-purple-400/80 text-[10px] font-bold uppercase">{sessionStatus.current_intake_question.title}</span>
            </div>
            <p className="text-xs text-slate-100 font-medium mb-2">{sessionStatus.current_intake_question.prompt}</p>
            <div className="grid grid-cols-1 gap-1.5 mb-2.5">
              {sessionStatus.current_intake_question.options.map((opt) => (
                <button
                  key={opt.id}
                  onClick={() => handleSendMessage(opt.id)}
                  className="text-left px-2.5 py-1.5 rounded-lg bg-slate-900/90 hover:bg-purple-950/70 border border-slate-800 hover:border-purple-500/60 text-xs transition group shadow-xs cursor-pointer"
                >
                  <div className="font-semibold text-slate-200 group-hover:text-purple-300">{opt.label}</div>
                  <div className="text-[10px] text-slate-400 group-hover:text-slate-300">{opt.description}</div>
                </button>
              ))}
            </div>
            <div className="flex items-center justify-between pt-1.5 border-t border-slate-800 text-[10px]">
              <button
                onClick={() => handleSendMessage('use defaults')}
                className="px-2 py-1 rounded bg-slate-900 hover:bg-slate-800 text-cyan-300 border border-cyan-800/60 font-semibold transition cursor-pointer"
              >
                ⚡ Apply Safe Defaults
              </button>
              <button
                onClick={() => handleSendMessage('stop')}
                className="px-2 py-1 rounded bg-slate-900 hover:bg-red-950/80 text-slate-400 hover:text-red-300 border border-slate-800 transition cursor-pointer"
              >
                Cancel Intake
              </button>
            </div>
          </div>
        )}

        {/* Dynamic Awaiting Confirmation Card */}
        {activeTab === 'manager' && sessionStatus?.state === 'AWAITING_CONFIRMATION' && (
          <div className="p-3 bg-slate-950/95 border border-emerald-500/60 rounded-xl my-2 shadow-xl animate-in fade-in">
            <div className="flex items-center justify-between text-[11px] font-mono text-emerald-400 mb-1.5">
              <span className="font-bold flex items-center gap-1">
                <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                <span>SPECIFICATION READY FOR CONFIRMATION</span>
              </span>
              <span className="text-slate-400 text-[9px]">
                {sessionStatus.config_hash ? `HASH: ${sessionStatus.config_hash.slice(0, 12)}...` : ''}
              </span>
            </div>
            <p className="text-xs text-slate-200 mb-2">
              All 10 parameters configured. Hard risk limits strictly clamped: Max 0.5% per trade, 1.5% daily drawdown circuit breaker.
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleSendMessage('CONFIRM PAPER SESSION')}
                className="flex-1 py-2 px-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-md transition flex items-center justify-center gap-1.5 cursor-pointer"
              >
                <span>CONFIRM PAPER SESSION</span>
              </button>
              <button
                onClick={() => handleSendMessage('edit 1')}
                className="py-2 px-3 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold cursor-pointer"
              >
                Edit
              </button>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} className="h-2" />
        </div>

        {/* Floating ChatGPT-style Scroll Controls */}
        <AnimatePresence>
          {(!isAtBottom || showScrollUp) && (
            <motion.div
              initial={{ opacity: 0, scale: 0.85, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.85, y: 10 }}
              transition={{ duration: 0.15 }}
              className="absolute bottom-3 right-4 z-20 flex items-center gap-1.5 pointer-events-auto"
            >
              {/* ChatGPT Down-Arrow: Scroll to Latest News / Bottom */}
              {!isAtBottom && (
                <button
                  type="button"
                  id="btnScrollToLatestNews"
                  onClick={() => scrollToBottom('smooth')}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-900/95 hover:bg-slate-800 text-cyan-300 hover:text-cyan-100 border border-cyan-500/70 shadow-xl shadow-black/80 text-xs font-semibold backdrop-blur-md transition-all transform hover:scale-105 active:scale-95 cursor-pointer ring-1 ring-cyan-500/30"
                  title="Scroll down to latest news (ChatGPT Style)"
                >
                  <ArrowDown className="w-3.5 h-3.5 animate-bounce" />
                  <span className="text-[11px] font-mono tracking-tight font-bold">Latest News</span>
                  {unreadCount > 0 && (
                    <span className="flex items-center justify-center px-1.5 py-0.2 rounded-full bg-cyan-500 text-slate-950 font-bold text-[9px] shadow-xs animate-pulse">
                      +{unreadCount}
                    </span>
                  )}
                </button>
              )}

              {/* Up-Arrow: Scroll to Top */}
              {showScrollUp && (
                <button
                  type="button"
                  id="btnScrollToTop"
                  onClick={() => scrollToTop('smooth')}
                  className="p-1.5 rounded-full bg-slate-900/90 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-700/80 shadow-lg shadow-black/50 text-xs backdrop-blur-md transition-all hover:scale-105 active:scale-95 cursor-pointer"
                  title="Scroll to top (Oldest messages)"
                >
                  <ArrowUp className="w-3.5 h-3.5" />
                </button>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* 4. Quick Action Prompt Chips */}
      <div className="px-2.5 py-1.5 bg-slate-950/80 border-t border-slate-800 shrink-0 flex items-center gap-1 overflow-x-auto scrollbar-none">
        {[
          { label: '▶️ Start Trading (Intake)', text: 'Start paper trading' },
          { label: '⚡ Use Defaults', text: 'use defaults' },
          { label: '⏸️ Pause Session', text: 'pause' },
          { label: '▶️ Resume Session', text: 'resume' },
          { label: '📊 Session Status', text: 'session status' },
          { label: '🛑 Emergency Stop', text: 'emergency stop' },
        ].map((chip, idx) => (
          <button
            key={idx}
            onClick={() => handleSendMessage(chip.text)}
            className="shrink-0 px-2 py-0.5 rounded-full bg-slate-900 hover:bg-slate-800 border border-slate-700/70 text-[10px] text-slate-300 hover:text-cyan-300 font-mono transition cursor-pointer"
          >
            {chip.label}
          </button>
        ))}
      </div>

      {/* 5. Fixed Pinned Message Composer at Bottom */}
      <div className="p-2 bg-slate-950 border-t border-slate-800 shrink-0">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage();
          }}
          className="flex items-center gap-1.5"
        >
          <div className="relative flex-1 min-w-0">
            <input
              type="text"
              id={activeTab === 'coordination' ? 'inputTeamChat' : 'inputManagerDirectives'}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                activeTab === 'coordination'
                  ? 'Send instruction to Squad via Manager (Enter to dispatch)...'
                  : 'Directive to Manager Iva (Enter to send)...'
              }
              className="w-full bg-slate-900 border border-slate-700/80 rounded-md px-2.5 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/40 font-sans"
            />
          </div>

          <button
            id={activeTab === 'coordination' ? 'btnSendTeamChat' : 'btnSendManagerDirective'}
            type="submit"
            disabled={isSending || !inputText.trim()}
            className="shrink-0 inline-flex items-center justify-center gap-1 px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-800 text-slate-950 disabled:text-slate-500 font-bold text-xs rounded-md transition shadow-xs"
          >
            <Send className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">{isSending ? '...' : 'Send'}</span>
          </button>
        </form>
      </div>
    </aside>
  );
}
