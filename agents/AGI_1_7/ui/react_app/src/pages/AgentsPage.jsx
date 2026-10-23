import React, { useState, useEffect } from 'react';
import {
  Bot,
  ArrowLeft,
  Search,
  CheckCircle2,
  Clock,
  AlertTriangle,
  RefreshCw,
  Cpu,
  Layers,
  Wrench,
  Shield,
  Activity,
  FileCheck,
  ChevronDown,
  ChevronUp,
  Terminal,
  Zap,
  Info
} from 'lucide-react';
import { api } from '../services/api';

export default function AgentsPage({ onBackToTrading, onSelectAgentTask }) {
  const [agents, setAgents] = useState([]);
  const [summary, setSummary] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [familyFilter, setFamilyFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [expandedCards, setExpandedCards] = useState({});

  const loadAgents = async () => {
    setIsLoading(true);
    try {
      const data = await api.getCatalogAgents();
      if (data && data.agents) {
        setAgents(data.agents);
        setSummary(data.summary || null);
      }
    } catch (err) {
      console.error('Failed to load agents catalog:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadAgents();
  }, []);

  const toggleExpand = (id) => {
    setExpandedCards((prev) => ({
      ...prev,
      [id]: !prev[id]
    }));
  };

  // Derive unique families
  const families = ['all', ...Array.from(new Set(agents.map((a) => a.family).filter(Boolean)))];

  // Derived filtered list
  const filteredAgents = agents.filter((ag) => {
    // Status filter
    const matchesStatus =
      statusFilter === 'all'
        ? true
        : statusFilter === 'executing'
        ? ag.status === 'RUNNING' || ag.status === 'EXECUTING'
        : statusFilter === 'standby'
        ? ag.status === 'IDLE' || ag.status === 'STANDBY'
        : statusFilter === 'registered'
        ? ag.status === 'REGISTERED'
        : statusFilter === 'error'
        ? ag.status === 'ERROR' || ag.status === 'FAILED'
        : true;

    // Type filter
    const matchesType = typeFilter === 'all' || ag.runtime_type === typeFilter;

    // Family filter
    const matchesFamily = familyFilter === 'all' || ag.family === familyFilter;

    // Search query
    const q = searchQuery.toLowerCase().trim();
    const matchesSearch =
      q === ''
        ? true
        : ag.agent_id.toLowerCase().includes(q) ||
          ag.display_name.toLowerCase().includes(q) ||
          ag.family.toLowerCase().includes(q) ||
          ag.role_description.toLowerCase().includes(q) ||
          (ag.capabilities || []).some((c) => c.toLowerCase().includes(q)) ||
          (ag.allowed_tools || []).some((t) => t.toLowerCase().includes(q));

    return matchesStatus && matchesType && matchesFamily && matchesSearch;
  });

  return (
    <div id="page-agents" className="flex-1 flex flex-col h-full w-full bg-slate-950 overflow-y-auto min-w-0 text-slate-100 select-none">
      {/* Header */}
      <div className="bg-slate-900 border-b border-slate-800 px-4 sm:px-6 py-4 shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-3 min-w-0">
          <div className="flex items-center gap-3 min-w-0">
            <button
              id="btnBackToTradingFromAgents"
              onClick={onBackToTrading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-xs font-semibold transition shrink-0"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Trading Desk</span>
            </button>
            <div className="flex items-center gap-2 min-w-0">
              <Bot className="w-5 h-5 text-cyan-400 shrink-0" />
              <div className="min-w-0">
                <h1 className="text-base font-bold tracking-wide truncate">
                  AGENT OPERATIONS & SPECIALIST OBSERVABILITY
                </h1>
                <p className="text-[11px] text-slate-400 hidden sm:block truncate">
                  Authoritative Registry of 106 Embedded Specialists, Coordinators & Active Execution Lifecycles
                </p>
              </div>
            </div>
          </div>
          <button
            onClick={loadAgents}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-mono border border-slate-700 transition shrink-0"
            title="Refresh agents telemetry"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-cyan-400 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>

        {/* Real Summary Metric Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3 mt-4 min-w-0">
          <div
            onClick={() => setStatusFilter('all')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              statusFilter === 'all' ? 'border-cyan-500 ring-1 ring-cyan-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-slate-400 font-medium truncate">Total Registered Roles</div>
            <div className="text-lg font-bold font-mono text-slate-100 mt-0.5">
              {summary?.registered_roles_total || agents.length} Agents
            </div>
          </div>
          <div
            onClick={() => setStatusFilter('executing')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              statusFilter === 'executing' ? 'border-emerald-500 ring-1 ring-emerald-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-emerald-400 font-medium truncate">Actively Executing</div>
            <div className="text-lg font-bold font-mono text-emerald-400 mt-0.5">
              {summary?.actively_executing_agents || 0} Agents
            </div>
          </div>
          <div
            onClick={() => setStatusFilter('standby')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              statusFilter === 'standby' ? 'border-cyan-500 ring-1 ring-cyan-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-cyan-400 font-medium truncate">Idle / Standby</div>
            <div className="text-lg font-bold font-mono text-cyan-400 mt-0.5">
              {summary?.idle_or_standby_agents || agents.length} Agents
            </div>
          </div>
          <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl min-w-0">
            <div className="text-[11px] text-purple-400 font-medium truncate">Completed Tasks</div>
            <div className="text-lg font-bold font-mono text-purple-400 mt-0.5">
              {summary?.completed_agent_tasks || 0} Tasks
            </div>
          </div>
          <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl min-w-0">
            <div className="text-[11px] text-amber-400 font-medium truncate">Functional Families</div>
            <div className="text-lg font-bold font-mono text-amber-400 mt-0.5">
              {summary?.functional_families_count || families.length - 1} Families
            </div>
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="px-4 sm:px-6 py-3 bg-slate-950 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3 shrink-0 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {/* Status Tabs */}
          <div className="flex items-center gap-1 bg-slate-900 p-1 rounded-lg border border-slate-800 text-xs font-semibold">
            {[
              { id: 'all', label: 'All Roles' },
              { id: 'executing', label: `Executing (${summary?.actively_executing_agents || 0})` },
              { id: 'standby', label: 'Standby' },
              { id: 'registered', label: 'Registered Catalog (100)' }
            ].map((t) => (
              <button
                key={t.id}
                onClick={() => setStatusFilter(t.id)}
                className={`px-2.5 py-1 rounded-md transition ${
                  statusFilter === t.id
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Runtime Type Filter */}
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300 font-medium focus:outline-none focus:border-cyan-500"
          >
            <option value="all">All Runtime Types</option>
            <option value="PRIMARY_ORCHESTRATOR">Primary Orchestrator</option>
            <option value="EXECUTIVE_COORDINATOR">Executive Coordinators</option>
            <option value="EMBEDDED_SPECIALIST">Embedded Specialists (100 Catalog)</option>
          </select>

          {/* Family Dropdown */}
          <select
            value={familyFilter}
            onChange={(e) => setFamilyFilter(e.target.value)}
            className="px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300 font-medium focus:outline-none focus:border-cyan-500"
          >
            {families.map((f) => (
              <option key={f} value={f}>
                {f === 'all' ? 'All Functional Families' : f}
              </option>
            ))}
          </select>
        </div>

        {/* Search */}
        <div className="relative min-w-0 w-full sm:w-64">
          <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search role, capability, tool..."
            className="w-full pl-8 pr-3 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500"
          />
        </div>
      </div>

      {/* Agents Cards Grid */}
      <div className="flex-1 p-4 sm:p-6 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 max-w-7xl mx-auto w-full min-w-0">
        {filteredAgents.map((ag) => {
          const isExecuting = ag.status === 'RUNNING' || ag.status === 'EXECUTING';
          const isExpanded = expandedCards[ag.agent_id];

          return (
            <div
              key={ag.agent_id}
              className={`flex flex-col p-4 bg-slate-900/80 border rounded-xl transition min-w-0 overflow-hidden ${
                isExecuting
                  ? 'border-emerald-500/50 bg-emerald-950/15 shadow-md shadow-emerald-950/20'
                  : 'border-slate-800 hover:border-slate-700'
              }`}
            >
              {/* Top Row: Name, Status badge */}
              <div className="flex items-start justify-between gap-2 pb-2 border-b border-slate-800/80 min-w-0">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] font-mono text-cyan-400 font-bold truncate">{ag.agent_id}</span>
                  </div>
                  <h3 className="text-sm font-bold text-slate-100 mt-0.5 truncate">{ag.display_name}</h3>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <span
                    className={`px-2 py-0.5 rounded text-[9.5px] font-mono font-bold uppercase tracking-wider ${
                      isExecuting
                        ? 'bg-emerald-950/90 border border-emerald-500/50 text-emerald-300 animate-pulse'
                        : ag.status === 'REGISTERED'
                        ? 'bg-amber-950/40 border border-amber-600/40 text-amber-300/90'
                        : 'bg-slate-800 border border-slate-700 text-slate-400'
                    }`}
                  >
                    {ag.status}
                  </span>
                  <span className="text-[9px] text-slate-500 font-mono">{ag.runtime_type}</span>
                </div>
              </div>

              {/* Family Tag */}
              <div className="mt-2 flex items-center gap-1.5 text-[10.5px] text-slate-400 font-mono">
                <Layers className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                <span className="text-purple-300 font-medium truncate">{ag.family}</span>
              </div>

              {/* Role Description */}
              <p className="mt-2 text-xs text-slate-300 leading-relaxed line-clamp-2">{ag.role_description}</p>

              {/* Registered - Unverified Execution Notice */}
              {ag.validation_status === 'REGISTERED — EXECUTION NOT VERIFIED' && (
                <div className="mt-2 px-2 py-1 bg-amber-950/30 border border-amber-500/30 rounded text-[10px] font-mono text-amber-300/90 flex items-center gap-1.5">
                  <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0" />
                  <span className="truncate">REGISTERED — EXECUTION NOT VERIFIED</span>
                </div>
              )}

              {/* Active / Current Task if executing */}
              {isExecuting && ag.current_task_id && (
                <div className="mt-2.5 p-2 bg-emerald-950/40 border border-emerald-500/30 rounded-lg text-xs font-mono">
                  <div className="text-[9.5px] text-emerald-400 font-bold uppercase tracking-wider flex items-center gap-1">
                    <Activity className="w-3 h-3 animate-spin" />
                    <span>Active Task</span>
                  </div>
                  <div className="text-slate-200 mt-0.5 font-bold truncate">{ag.current_task_id}</div>
                </div>
              )}

              {/* Last Outcome if idle */}
              {!isExecuting && ag.last_completed_task && (
                <div className="mt-2.5 p-2 bg-slate-950/60 border border-slate-800/80 rounded-lg text-[11px] font-mono flex items-center justify-between">
                  <div className="truncate">
                    <span className="text-slate-500 text-[9.5px] block">Last Task:</span>
                    <span className="text-slate-300 truncate">{ag.last_completed_task}</span>
                  </div>
                  <span className="text-emerald-400 text-[10px] font-bold shrink-0">{ag.recent_outcome}</span>
                </div>
              )}

              {/* Expand Toggle */}
              <button
                onClick={() => toggleExpand(ag.agent_id)}
                className="mt-3 flex items-center justify-between text-xs text-slate-400 hover:text-slate-200 transition pt-2 border-t border-slate-800/80 focus:outline-none"
              >
                <span className="flex items-center gap-1.5 font-medium">
                  <Wrench className="w-3.5 h-3.5 text-cyan-400" />
                  <span>{isExpanded ? 'Hide Specifications' : 'View Tools & Capabilities'}</span>
                </span>
                {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </button>

              {/* Expanded Specs */}
              {isExpanded && (
                <div className="mt-2.5 space-y-2 pt-1 text-xs">
                  {/* Capabilities */}
                  <div>
                    <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Capabilities</div>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {(ag.capabilities || []).map((cap, idx) => (
                        <span key={idx} className="px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800 text-[10px] font-mono text-cyan-300">
                          {cap}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Allowed Tools */}
                  <div>
                    <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Allowed Tools</div>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {(ag.allowed_tools || []).map((tool, idx) => (
                        <span key={idx} className="px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800 text-[10px] font-mono text-emerald-400">
                          {tool}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Model & Runtime Configuration */}
                  <div className="p-2 rounded bg-slate-950 border border-slate-800 text-[10.5px] font-mono space-y-1">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Model:</span>
                      <span className="text-slate-300">{ag.model_config}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Timeout:</span>
                      <span className="text-slate-300">{ag.execution_timeout_sec}s</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500">Validation:</span>
                      <span className={`font-bold text-[10px] ${
                        ag.validation_status === 'VERIFIED_PASS' || ag.validation_status === 'ACTIVE_TASK_EXECUTING'
                          ? 'text-emerald-400'
                          : 'text-amber-400'
                      }`}>
                        {ag.validation_status}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
