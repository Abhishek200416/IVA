import React, { useState, useEffect } from 'react';
import {
  ShieldAlert,
  Lock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ArrowLeft,
  Shield,
  FileCheck,
  Calendar,
  AlertOctagon,
  RefreshCw,
  GitBranch,
  Package,
  Landmark,
  Layers,
  Award,
  ChevronRight
} from 'lucide-react';
import { api } from '../services/api';

export default function ReadinessPage({ onBackToTrading }) {
  const [readinessData, setReadinessData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [dimensionFilter, setDimensionFilter] = useState('ALL');
  const [statusFilter, setStatusFilter] = useState('ALL');

  const loadReadiness = async () => {
    setIsLoading(true);
    try {
      const data = await api.getDeploymentReadiness();
      if (data && data.ok) {
        setReadinessData(data);
      }
    } catch (err) {
      console.error('Failed to load deployment readiness:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadReadiness();
  }, []);

  const summary = readinessData?.summary || {};
  const items = readinessData?.items || [];
  const scorecard = readinessData?.scorecard_six_dimensions || {};

  const filteredItems = items.filter((item) => {
    const matchesDimension = dimensionFilter === 'ALL' || item.dimension === dimensionFilter;
    const matchesStatus = statusFilter === 'ALL' || item.status === statusFilter;
    return matchesDimension && matchesStatus;
  });

  const passedCount = items.filter((i) => i.status === 'PASS').length;
  const blockedCount = items.filter((i) => i.status === 'BLOCK').length;

  return (
    <div id="page-readiness" className="flex-1 flex flex-col h-full w-full overflow-hidden bg-slate-950 text-slate-100 select-none">
      {/* Top Header Bar */}
      <header className="h-14 bg-slate-900 border-b border-slate-800 px-4 sm:px-6 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <button
            id="btnBackToTradingFromReadiness"
            onClick={onBackToTrading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-xs font-semibold transition"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Trading Desk</span>
          </button>
          <div className="h-4 w-px bg-slate-800" />
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
              <Shield className="w-4 h-4" />
            </div>
            <div>
              <h1 className="text-sm font-bold tracking-wide uppercase flex items-center gap-2">
                <span>DEPLOYMENT READINESS & SYSTEM QUALIFICATION AUDIT</span>
              </h1>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs font-mono text-slate-400">
            <Calendar className="w-3.5 h-3.5 text-slate-500" />
            <span className="hidden sm:inline">Status:</span>
            <span className="text-emerald-400 font-bold">
              {summary.overall_status || 'QUALIFIED_FOR_LOCAL_PAPER_TRADING'}
            </span>
          </div>
          <button
            onClick={loadReadiness}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-mono border border-slate-700 transition"
            title="Re-run authoritative readiness audit"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-cyan-400 ${isLoading ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Re-Audit</span>
          </button>
        </div>
      </header>

      {/* Main Scrollable Content */}
      <main className="flex-1 overflow-y-auto p-4 sm:p-6 max-w-7xl mx-auto w-full space-y-5">
        {/* Fail-Closed Policy Banner */}
        <section className="p-4 rounded-xl bg-rose-950/20 border border-rose-500/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-lg bg-rose-500/20 text-rose-400 shrink-0 mt-0.5 sm:mt-0">
              <AlertOctagon className="w-5 h-5" />
            </div>
            <div>
              <h2 className="font-bold text-rose-300 text-sm flex items-center gap-2">
                Strict Paper Execution Mandate Enforced
              </h2>
              <p className="text-slate-300 text-xs mt-1 leading-relaxed">
                Live broker order submission is permanently disabled in code (<code className="bg-slate-900 px-1.5 py-0.5 rounded text-rose-400 font-mono">LIVE_ORDER_DISPATCH_ENABLED = False</code>). Any mutate call to <code className="bg-slate-900 px-1.5 py-0.5 rounded text-rose-400 font-mono">/api/orders</code> automatically fails closed with <strong className="text-white">HTTP 403 Forbidden</strong>. Live mode cannot be armed from the UI without explicit authorized regulatory unarming.
              </p>
            </div>
          </div>
          <div className="shrink-0 self-end sm:self-center">
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-900/60 border border-rose-700 text-rose-200 text-xs font-mono font-bold">
              <Lock className="w-3.5 h-3.5 text-rose-400" />
              <span>FAIL-CLOSED ACTIVE</span>
            </span>
          </div>
        </section>

        {/* 3 Distinct Dimension Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Dimension 1: Repo Publishing */}
          <div
            onClick={() => setDimensionFilter(dimensionFilter === 'REPO_PUBLISHING' ? 'ALL' : 'REPO_PUBLISHING')}
            className={`p-4 rounded-xl border cursor-pointer transition ${
              dimensionFilter === 'REPO_PUBLISHING'
                ? 'bg-slate-900 border-cyan-500 ring-1 ring-cyan-500'
                : 'bg-slate-900/70 border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitBranch className="w-4 h-4 text-cyan-400" />
                <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wide">1. Repo Publishing</h3>
              </div>
              <span className="text-xs font-mono font-bold text-cyan-400">{summary.repo_publishing_score || '1/3'}</span>
            </div>
            <div className="mt-2 text-[11.5px] text-slate-400 leading-snug">
              Excludes secrets and credentials. Blocked from public git release by uncommitted working tree modifications.
            </div>
            <div className="mt-3 flex items-center justify-between text-[10px] font-mono">
              <span className="text-amber-400">UNCOMMITTED CHANGES</span>
              <span className="text-slate-500">Click to filter</span>
            </div>
          </div>

          {/* Dimension 2: Deployment Package */}
          <div
            onClick={() => setDimensionFilter(dimensionFilter === 'DEPLOYMENT_PACKAGE' ? 'ALL' : 'DEPLOYMENT_PACKAGE')}
            className={`p-4 rounded-xl border cursor-pointer transition ${
              dimensionFilter === 'DEPLOYMENT_PACKAGE'
                ? 'bg-slate-900 border-purple-500 ring-1 ring-purple-500'
                : 'bg-slate-900/70 border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Package className="w-4 h-4 text-purple-400" />
                <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wide">2. Package Readiness</h3>
              </div>
              <span className="text-xs font-mono font-bold text-purple-400">{summary.deployment_package_score || '1/4'}</span>
            </div>
            <div className="mt-2 text-[11.5px] text-slate-400 leading-snug">
              Manifest hashes sealed. Remote headless deployment blocked by Windows desktop Chrome CDP dependency.
            </div>
            <div className="mt-3 flex items-center justify-between text-[10px] font-mono">
              <span className="text-cyan-400">LOCAL SUPERVISED ONLY</span>
              <span className="text-slate-500">Click to filter</span>
            </div>
          </div>

          {/* Dimension 3: Financial System */}
          <div
            onClick={() => setDimensionFilter(dimensionFilter === 'FINANCIAL_SYSTEM' ? 'ALL' : 'FINANCIAL_SYSTEM')}
            className={`p-4 rounded-xl border cursor-pointer transition ${
              dimensionFilter === 'FINANCIAL_SYSTEM'
                ? 'bg-slate-900 border-emerald-500 ring-1 ring-emerald-500'
                : 'bg-slate-900/70 border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Landmark className="w-4 h-4 text-emerald-400" />
                <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wide">3. Financial System</h3>
              </div>
              <span className="text-xs font-mono font-bold text-emerald-400">{summary.financial_system_score || '2/4'}</span>
            </div>
            <div className="mt-2 text-[11.5px] text-slate-400 leading-snug">
              Paper isolation and fail-closed live gate verified. Authentic broker session required for live execution.
            </div>
            <div className="mt-3 flex items-center justify-between text-[10px] font-mono">
              <span className="text-emerald-400">PAPER QUALIFIED</span>
              <span className="text-slate-500">Click to filter</span>
            </div>
          </div>
        </div>

        {/* 6-Dimension Holistic Scorecard */}
        <section className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 sm:p-5">
          <div className="flex items-center gap-2 pb-3 border-b border-slate-800">
            <Award className="w-4 h-4 text-amber-400" />
            <h2 className="text-xs font-bold text-slate-100 uppercase tracking-wide">
              OMEGA 6-Dimension Holistic Architecture Scorecard
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mt-3">
            {Object.entries(scorecard).map(([dimKey, dimVal]) => {
              const label = dimKey.replace(/^[0-9]_/, '').replace(/_/g, ' ').toUpperCase();
              return (
                <div key={dimKey} className="p-3 bg-slate-950/70 border border-slate-800/80 rounded-lg text-xs space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold text-slate-400 truncate">{label}</span>
                    <span className="font-mono font-bold text-cyan-400">{dimVal.score}</span>
                  </div>
                  <div className="text-[10px] font-mono text-emerald-400 font-semibold">{dimVal.status}</div>
                  <div className="text-[11px] text-slate-300 leading-snug line-clamp-2">{dimVal.evidence}</div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Filter Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400 font-mono">Checklist Filters:</span>
            <div className="flex items-center gap-1 bg-slate-900 p-1 rounded-lg border border-slate-800 text-xs font-semibold">
              {[
                { id: 'ALL', label: `All Checks (${items.length})` },
                { id: 'PASS', label: `Passed (${passedCount})` },
                { id: 'BLOCK', label: `Blocked (${blockedCount})` }
              ].map((s) => (
                <button
                  key={s.id}
                  onClick={() => setStatusFilter(s.id)}
                  className={`px-2.5 py-1 rounded-md transition ${
                    statusFilter === s.id
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
          {dimensionFilter !== 'ALL' && (
            <button
              onClick={() => setDimensionFilter('ALL')}
              className="text-xs font-mono text-cyan-400 hover:underline"
            >
              Reset Dimension Filter ({dimensionFilter})
            </button>
          )}
        </div>

        {/* Checklist Items */}
        <section className="space-y-3">
          {filteredItems.map((item) => {
            const isPass = item.status === 'PASS';
            return (
              <div
                key={item.item_id}
                className={`p-4 rounded-xl border flex flex-col md:flex-row md:items-center justify-between gap-3 transition ${
                  isPass
                    ? 'bg-slate-900/60 border-slate-800'
                    : 'bg-rose-950/15 border-rose-900/40 shadow-xs'
                }`}
              >
                <div className="flex items-start gap-3 min-w-0">
                  <div className="p-2 rounded-lg bg-slate-950 border border-slate-800 shrink-0 mt-0.5 md:mt-0">
                    {isPass ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    ) : (
                      <XCircle className="w-4 h-4 text-rose-400" />
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-cyan-400 font-bold">{item.item_id}</span>
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-400 font-mono">
                        {item.dimension}
                      </span>
                      <span
                        className={`text-[9.5px] px-1.5 py-0.2 rounded font-mono font-bold uppercase ${
                          isPass
                            ? 'bg-emerald-950 text-emerald-400 border border-emerald-500/40'
                            : 'bg-rose-950 text-rose-400 border border-rose-500/40'
                        }`}
                      >
                        {item.status}
                      </span>
                    </div>
                    <h4 className="text-xs font-bold text-slate-100 mt-1">{item.name}</h4>
                    <p className="text-[11px] text-slate-300 mt-0.5 leading-relaxed">{item.details}</p>
                    {item.required_operator_action && (
                      <div className="mt-2 p-2 rounded bg-rose-950/30 border border-rose-900/50 text-[10.5px] font-mono text-rose-300">
                        <strong>Required Action:</strong> {item.required_operator_action}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </section>
      </main>
    </div>
  );
}
