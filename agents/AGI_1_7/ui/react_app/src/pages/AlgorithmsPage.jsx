import React, { useState, useEffect } from 'react';
import {
  Cpu,
  ArrowLeft,
  Search,
  CheckCircle2,
  Clock,
  AlertTriangle,
  ShieldAlert,
  Code,
  Sliders,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Power,
  ShieldCheck,
  AlertOctagon,
  FileCode2,
  Layers
} from 'lucide-react';
import { api } from '../services/api';

export default function AlgorithmsPage({ onBackToTrading }) {
  const [filter, setFilter] = useState('all');
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [algoList, setAlgoList] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [expandedAlgos, setExpandedAlgos] = useState({});
  const [actionMessage, setActionMessage] = useState(null);
  const [togglingId, setTogglingId] = useState(null);
  const [isVerifying, setIsVerifying] = useState(false);
  const [verifyReport, setVerifyReport] = useState(null);

  const loadAlgorithms = async () => {
    setIsLoading(true);
    try {
      const data = await api.getCatalogAlgorithms();
      if (data && data.algorithms) {
        setAlgoList(data.algorithms);
      }
    } catch (err) {
      console.error('Failed to load algorithms catalog:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleVerifyModules = async () => {
    setIsVerifying(true);
    try {
      const res = await api.verifyCatalogAlgorithms();
      setVerifyReport(res);
      setActionMessage({
        type: res?.overall_integrity_pass ? 'success' : 'error',
        text: res?.overall_integrity_pass
          ? `✓ Integrity Verified: All ${res.verified_algorithms_count}/${res.total_algorithms} algorithm source modules and entry points passed import validation.`
          : `⚠️ Verification Warning: Only ${res?.verified_algorithms_count}/${res?.total_algorithms} algorithms passed source module integrity audit.`
      });
      await loadAlgorithms();
    } catch (err) {
      setActionMessage({
        type: 'error',
        text: `Verification Failed: ${err.message || 'Unknown error'}`
      });
    } finally {
      setIsVerifying(false);
    }
  };

  useEffect(() => {
    loadAlgorithms();
  }, []);

  const toggleExpand = (id) => {
    setExpandedAlgos((prev) => ({
      ...prev,
      [id]: !prev[id]
    }));
  };

  const handleToggle = async (algo) => {
    const isCurrentlyEnabled = algo.implementation_status === 'ENABLED' || algo.implementation_status === 'RUNNING';
    const targetState = !isCurrentlyEnabled;
    setTogglingId(algo.algorithm_id);
    setActionMessage(null);

    try {
      const res = await api.toggleCatalogAlgorithm(algo.algorithm_id, targetState);
      if (res && res.ok) {
        setActionMessage({
          type: 'success',
          text: `Algorithm ${algo.algorithm_id} successfully ${targetState ? 'ENABLED' : 'DISABLED'}.`
        });
        await loadAlgorithms();
      }
    } catch (err) {
      const msg = err.data?.error || err.message || 'Operation rejected by risk controller.';
      setActionMessage({
        type: 'error',
        text: `Toggle Blocked: ${msg}`
      });
    } finally {
      setTogglingId(null);
    }
  };

  // Metrics derived authoritatively from list
  const totalCount = algoList.length;
  const enabledCount = algoList.filter((a) => a.implementation_status === 'ENABLED' || a.implementation_status === 'RUNNING').length;
  const implementedCount = algoList.filter((a) => a.implementation_status === 'IMPLEMENTED' || a.implementation_status === 'AVAILABLE').length;
  const experimentalCount = algoList.filter((a) => a.implementation_status === 'EXPERIMENTAL').length;
  const blockedCount = algoList.filter((a) => a.implementation_status === 'BLOCKED_BY_RISK').length;

  const categories = ['all', ...Array.from(new Set(algoList.map((a) => a.category).filter(Boolean)))];

  const filteredAlgos = algoList.filter((algo) => {
    // Status filter
    const matchesFilter =
      filter === 'all'
        ? true
        : filter === 'enabled'
        ? algo.implementation_status === 'ENABLED' || algo.implementation_status === 'RUNNING'
        : filter === 'implemented'
        ? algo.implementation_status === 'IMPLEMENTED' || algo.implementation_status === 'AVAILABLE'
        : filter === 'experimental'
        ? algo.implementation_status === 'EXPERIMENTAL'
        : filter === 'blocked'
        ? algo.implementation_status === 'BLOCKED_BY_RISK'
        : true;

    // Category filter
    const matchesCategory = categoryFilter === 'all' || algo.category === categoryFilter;

    // Search query
    const q = searchQuery.toLowerCase().trim();
    const matchesSearch =
      q === ''
        ? true
        : algo.algorithm_id?.toLowerCase().includes(q) ||
          algo.display_name?.toLowerCase().includes(q) ||
          algo.description?.toLowerCase().includes(q) ||
          algo.source_module?.toLowerCase().includes(q) ||
          algo.category?.toLowerCase().includes(q);

    return matchesFilter && matchesCategory && matchesSearch;
  });

  return (
    <div id="page-algorithms" className="flex-1 flex flex-col h-full w-full bg-slate-950 overflow-y-auto min-w-0 text-slate-100 select-none">
      {/* Page Header */}
      <div className="bg-slate-900 border-b border-slate-800 px-4 sm:px-6 py-4 shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-3 min-w-0">
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
              <Cpu className="w-5 h-5 text-cyan-400 shrink-0" />
              <div className="min-w-0">
                <h1 className="text-base font-bold tracking-wide truncate">QUANTITATIVE ALGORITHMS REGISTRY & AUDIT</h1>
                <p className="text-[11px] text-slate-400 hidden sm:block truncate">
                  Authoritative Implementations, Parameter Contracts, Risk Controls & Execution Status
                </p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={handleVerifyModules}
              disabled={isVerifying || isLoading}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-cyan-950/80 hover:bg-cyan-900/80 text-cyan-300 text-xs font-mono border border-cyan-700/60 transition shrink-0"
              title="Audit and verify all algorithm source files and entry points via dynamic import"
            >
              <ShieldCheck className={`w-3.5 h-3.5 text-cyan-400 ${isVerifying ? 'animate-spin' : ''}`} />
              <span>{isVerifying ? 'Verifying...' : 'Verify Modules'}</span>
            </button>
            <button
              onClick={loadAlgorithms}
              disabled={isLoading || isVerifying}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-mono border border-slate-700 transition shrink-0"
              title="Refresh algorithm registry from server"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-cyan-400 ${isLoading ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Action / Notification Banner */}
        {actionMessage && (
          <div
            className={`mt-3 p-2.5 rounded-lg text-xs font-mono flex items-center justify-between ${
              actionMessage.type === 'success'
                ? 'bg-emerald-950/60 border border-emerald-500/40 text-emerald-300'
                : 'bg-rose-950/60 border border-rose-500/40 text-rose-300'
            }`}
          >
            <span>{actionMessage.text}</span>
            <button onClick={() => setActionMessage(null)} className="text-slate-400 hover:text-white ml-2 text-sm font-bold">
              ×
            </button>
          </div>
        )}

        {/* Authoritative Pipeline Summary Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3 mt-4 min-w-0">
          <div
            onClick={() => setFilter('all')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              filter === 'all' ? 'border-cyan-500 ring-1 ring-cyan-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-slate-400 font-medium truncate">Total Registered</div>
            <div className="text-lg font-bold font-mono text-slate-100 mt-0.5">{totalCount} Algorithms</div>
          </div>
          <div
            onClick={() => setFilter('enabled')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              filter === 'enabled' ? 'border-emerald-500 ring-1 ring-emerald-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-emerald-400 font-medium truncate">Enabled / Active</div>
            <div className="text-lg font-bold font-mono text-emerald-400 mt-0.5">{enabledCount} Algorithms</div>
          </div>
          <div
            onClick={() => setFilter('implemented')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              filter === 'implemented' ? 'border-cyan-500 ring-1 ring-cyan-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-cyan-400 font-medium truncate">Implemented / Standby</div>
            <div className="text-lg font-bold font-mono text-cyan-400 mt-0.5">{implementedCount} Algorithms</div>
          </div>
          <div
            onClick={() => setFilter('experimental')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              filter === 'experimental' ? 'border-amber-500 ring-1 ring-amber-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-amber-400 font-medium truncate">Experimental</div>
            <div className="text-lg font-bold font-mono text-amber-400 mt-0.5">{experimentalCount} Algorithms</div>
          </div>
          <div
            onClick={() => setFilter('blocked')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              filter === 'blocked' ? 'border-rose-500 ring-1 ring-rose-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-rose-400 font-medium truncate">Blocked by Risk</div>
            <div className="text-lg font-bold font-mono text-rose-400 mt-0.5">{blockedCount} Algorithm</div>
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="px-4 sm:px-6 py-3 bg-slate-950 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3 shrink-0 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {/* Status Tabs */}
          <div className="flex flex-wrap items-center gap-1 bg-slate-900 p-1 rounded-lg border border-slate-800 text-xs font-semibold">
            {[
              { id: 'all', label: `All (${totalCount})` },
              { id: 'enabled', label: `Enabled (${enabledCount})` },
              { id: 'implemented', label: `Standby (${implementedCount})` },
              { id: 'experimental', label: `Experimental (${experimentalCount})` },
              { id: 'blocked', label: `Blocked (${blockedCount})` }
            ].map((t) => (
              <button
                key={t.id}
                onClick={() => setFilter(t.id)}
                className={`px-2.5 py-1 rounded-md transition ${
                  filter === t.id
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Category Dropdown */}
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300 font-medium focus:outline-none focus:border-cyan-500"
          >
            {categories.map((c) => (
              <option key={c} value={c}>
                {c === 'all' ? 'All Categories' : c}
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
            placeholder="Search ID, name, module..."
            className="w-full pl-8 pr-3 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500"
          />
        </div>
      </div>

      {/* Algorithm Cards Grid */}
      <div className="flex-1 p-4 sm:p-6 grid grid-cols-1 xl:grid-cols-2 gap-4 max-w-7xl mx-auto w-full min-w-0">
        {filteredAlgos.map((algo) => {
          const isExpanded = expandedAlgos[algo.algorithm_id];
          const isEnabled = algo.implementation_status === 'ENABLED' || algo.implementation_status === 'RUNNING';
          const isBlocked = algo.implementation_status === 'BLOCKED_BY_RISK';
          const isToggling = togglingId === algo.algorithm_id;

          return (
            <div
              key={algo.algorithm_id}
              className={`algo-card flex flex-col p-4 bg-slate-900/80 border rounded-xl transition min-w-0 overflow-hidden ${
                isBlocked
                  ? 'border-rose-900/50 bg-rose-950/10'
                  : isEnabled
                  ? 'border-emerald-500/40 bg-emerald-950/10'
                  : 'border-slate-800 hover:border-slate-700'
              }`}
            >
              {/* Top row: ID, Name, Category, Toggle Button */}
              <div className="flex items-start justify-between gap-2 pb-2.5 border-b border-slate-800/80 min-w-0">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[10.5px] font-mono text-cyan-400 font-bold">{algo.algorithm_id}</span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                      {algo.category}
                    </span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">
                      {algo.version}
                    </span>
                  </div>
                  <h3 className="text-sm font-bold text-slate-100 mt-1 truncate">{algo.display_name}</h3>
                </div>

                {/* Status Badge + Toggle */}
                <div className="flex items-center gap-2 shrink-0">
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-wider shrink-0 ${
                      isEnabled
                        ? 'bg-emerald-950/80 border border-emerald-500/40 text-emerald-300'
                        : isBlocked
                        ? 'bg-rose-950/80 border border-rose-500/40 text-rose-300'
                        : algo.implementation_status === 'EXPERIMENTAL'
                        ? 'bg-amber-950/80 border border-amber-500/40 text-amber-300'
                        : 'bg-cyan-950/80 border border-cyan-500/40 text-cyan-300'
                    }`}
                  >
                    {algo.implementation_status}
                  </span>

                  {/* Toggle button */}
                  <button
                    onClick={() => handleToggle(algo)}
                    disabled={isToggling}
                    className={`p-1.5 rounded-lg border transition flex items-center justify-center ${
                      isEnabled
                        ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40 hover:bg-emerald-500/30'
                        : isBlocked
                        ? 'bg-rose-950/60 text-rose-400 border-rose-800 cursor-not-allowed opacity-75'
                        : 'bg-slate-800 text-slate-400 border-slate-700 hover:text-white hover:bg-slate-700'
                    }`}
                    title={isBlocked ? 'Blocked by risk safety policy' : isEnabled ? 'Click to disable' : 'Click to enable'}
                  >
                    <Power className={`w-3.5 h-3.5 ${isToggling ? 'animate-spin' : ''}`} />
                  </button>
                </div>
              </div>

              {/* Description */}
              <p className="mt-2.5 text-xs text-slate-300 leading-relaxed">{algo.description}</p>

              {/* Source & Entry Point */}
              <div className="mt-2 p-2 bg-slate-950 rounded border border-slate-800/80 text-[11px] font-mono text-slate-400 flex items-center justify-between gap-1.5 min-w-0">
                <div className="flex items-center gap-1.5 min-w-0 truncate">
                  <FileCode2 className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                  <span className="text-slate-300 truncate">{algo.source_module}</span>
                </div>
                <span className="text-cyan-400 shrink-0 text-[10px] font-bold">{algo.entry_point}</span>
              </div>

              {/* Key Verification Badges */}
              <div className="flex flex-wrap items-center gap-1.5 mt-2.5 text-[10px] font-mono">
                <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-300">
                  Instruments: <strong className="text-cyan-300">{algo.instruments.join(', ')}</strong>
                </span>
                <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-300">
                  Owner: <strong className="text-purple-300">{algo.owner}</strong>
                </span>
                <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-300">
                  Validation: <strong className={algo.validation_status === 'ACCEPTED_FOR_PAPER' ? 'text-emerald-400' : 'text-amber-400'}>{algo.validation_status}</strong>
                </span>
                <span className={`px-2 py-0.5 rounded border text-[9.5px] font-bold ${
                  algo.is_executing
                    ? 'bg-emerald-950/80 border-emerald-500/60 text-emerald-300 animate-pulse'
                    : isBlocked
                    ? 'bg-rose-950/80 border-rose-600/60 text-rose-300'
                    : 'bg-slate-950 border-slate-800 text-slate-400'
                }`}>
                  Execution: <strong>{algo.execution_state || (algo.is_executing ? 'EXECUTING' : 'IDLE')}</strong>
                </span>
                {verifyReport?.results?.[algo.algorithm_id] && (
                  <span className={`px-2 py-0.5 rounded border text-[9.5px] font-bold ${
                    verifyReport.results[algo.algorithm_id].verified
                      ? 'bg-emerald-950/80 border-emerald-500/60 text-emerald-300'
                      : 'bg-rose-950/80 border-rose-500/60 text-rose-300'
                  }`}>
                    Source: {verifyReport.results[algo.algorithm_id].status}
                  </span>
                )}
              </div>

              {/* Expandable Parameters, Methodology & Safety Controls */}
              <button
                onClick={() => toggleExpand(algo.algorithm_id)}
                className="mt-3 flex items-center justify-between text-xs text-slate-400 hover:text-slate-200 transition pt-2 border-t border-slate-800/80 focus:outline-none"
              >
                <span className="flex items-center gap-1.5 font-medium">
                  <Sliders className="w-3.5 h-3.5 text-cyan-400" />
                  <span>{isExpanded ? 'Hide Specifications & Contracts' : 'View Parameters, Contracts & Risk Rules'}</span>
                </span>
                {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </button>

              {isExpanded && (
                <div className="mt-2.5 space-y-2.5 pt-1 text-xs">
                  {/* Methodology */}
                  <div className="p-2.5 bg-slate-950/80 rounded-lg border border-slate-800">
                    <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Methodology & Logic</div>
                    <div className="text-[11px] text-slate-200 mt-1 leading-relaxed">{algo.methodology}</div>
                  </div>

                  {/* Parameters Grid */}
                  <div className="p-2.5 bg-slate-950/80 rounded-lg border border-slate-800">
                    <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Parameter Schema</div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-1.5 font-mono text-[10.5px]">
                      {Object.entries(algo.parameters || {}).map(([key, val]) => (
                        <div key={key} className="p-1.5 rounded bg-slate-900 border border-slate-800">
                          <span className="text-slate-500 block text-[9.5px] truncate">{key}:</span>
                          <span className="text-cyan-300 font-bold truncate">{String(val)}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Risk Controls */}
                  <div className="p-2.5 bg-slate-950/80 rounded-lg border border-slate-800">
                    <div className="text-[10px] font-bold text-emerald-400 uppercase tracking-wide flex items-center gap-1">
                      <ShieldCheck className="w-3.5 h-3.5" />
                      <span>Strict Risk Controls</span>
                    </div>
                    <ul className="mt-1 space-y-1 list-disc list-inside text-[11px] text-slate-300 font-mono">
                      {algo.risk_controls.map((rc, idx) => (
                        <li key={idx}>{rc}</li>
                      ))}
                    </ul>
                  </div>

                  {/* Known Limitations */}
                  {algo.limitations && algo.limitations.length > 0 && (
                    <div className="p-2.5 bg-rose-950/20 rounded-lg border border-rose-900/40">
                      <div className="text-[10px] font-bold text-rose-400 uppercase tracking-wide flex items-center gap-1">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        <span>Known Limitations & Failure Regimes</span>
                      </div>
                      <ul className="mt-1 space-y-1 list-disc list-inside text-[10.5px] text-rose-300/90 font-mono">
                        {algo.limitations.map((lim, idx) => (
                          <li key={idx}>{lim}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Unit Test & Last Verified */}
                  <div className="text-[10px] font-mono text-slate-400 flex flex-wrap items-center justify-between gap-1 pt-1">
                    <span>Test: <strong className="text-slate-300">{algo.test_status}</strong></span>
                    <span>Verified: {new Date(algo.last_verified).toLocaleString()}</span>
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
