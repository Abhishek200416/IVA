import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  FlaskConical,
  ArrowLeft,
  Play,
  RotateCw,
  ShieldAlert,
  CheckCircle,
  AlertTriangle,
  FileText,
  BarChart3,
  Layers,
  Cpu,
  Sliders,
  TrendingUp,
  Clock,
  Sparkles,
  Info
} from 'lucide-react';
import { api } from '../services/api';
import { formatCurrency, formatPercent } from '../utils/formatters';

export default function ResearchLabPage({ onBackToTrading, selectedEpoch = 'epoch_10k' }) {
  const [activeTab, setActiveTab] = useState('registry'); // 'registry' | 'runner' | 'results' | 'explainability'
  const [strategies, setStrategies] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [experiments, setExperiments] = useState([]);
  const [explainData, setExplainData] = useState(null);
  const [selectedStrategyId, setSelectedStrategyId] = useState('STRAT-ORB-V1');
  const [selectedDatasetId, setSelectedDatasetId] = useState('DS-SYNTH-OPTIONS-WALKFORWARD-V1');
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState(null);
  const [runSuccess, setRunSuccess] = useState(null);

  // Form parameters
  const [paramRangeMinutes, setParamRangeMinutes] = useState(15);
  const [paramBufferAtr, setParamBufferAtr] = useState(0.1);
  const [paramMaxRiskPct, setParamMaxRiskPct] = useState(0.005); // 0.5% max risk

  // Load research data
  const loadData = async () => {
    try {
      const [stratRes, dsRes, jobRes, expRes] = await Promise.all([
        api.getResearchStrategies().catch(() => ({ strategies: [] })),
        api.getResearchDatasets().catch(() => ({ datasets: [] })),
        api.getResearchJobs().catch(() => ({ jobs: [] })),
        api.getResearchExperiments().catch(() => ({ experiments: [] })),
      ]);
      setStrategies(stratRes.strategies || []);
      setDatasets(dsRes.datasets || []);
      setJobs(jobRes.jobs || []);
      setExperiments(expRes.experiments || []);
    } catch (err) {
      console.warn('Failed to fetch research lab data:', err);
    }
  };

  const loadExplainability = async (stratId) => {
    try {
      const exp = await api.getResearchExplainability(stratId);
      setExplainData(exp);
    } catch (err) {
      console.warn('Failed to load explainability data:', err);
    }
  };

  useEffect(() => {
    loadData();
    loadExplainability(selectedStrategyId);
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, [selectedStrategyId]);

  const handleLaunchExperiment = async () => {
    setIsRunning(true);
    setRunError(null);
    setRunSuccess(null);
    try {
      const res = await api.runResearchExperiment({
        strategy_id: selectedStrategyId,
        dataset_id: selectedDatasetId,
        parameters: {
          range_minutes: Number(paramRangeMinutes),
          buffer_atr_mult: Number(paramBufferAtr),
          max_risk_pct_capital: Number(paramMaxRiskPct),
        },
        epoch_id: selectedEpoch,
      });

      if (res.decision === 'PROCEED_TO_EXPERIMENT') {
        setRunSuccess(`Experiment completed! Artifact: ${res.job?.artifact_id || 'Generated'}`);
        await loadData();
        setActiveTab('results');
      } else {
        setRunError(`Multi-Agent Gate Halted: ${res.binding_blocker || res.decision}`);
      }
    } catch (err) {
      setRunError(err.message || 'Execution failed');
    } finally {
      setIsRunning(false);
    }
  };

  const selectedStrat = strategies.find((s) => s.strategy_id === selectedStrategyId) || strategies[0];
  const latestExperiment = experiments[0];

  return (
    <div id="page-research-lab" className="flex-1 flex flex-col h-full w-full bg-slate-950 overflow-y-auto min-w-0 text-slate-100 select-none">
      {/* Top Header */}
      <div className="bg-slate-900 border-b border-slate-800 px-4 sm:px-6 py-4 shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-3 min-w-0">
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={onBackToTrading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-xs font-semibold transition shrink-0"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Trading Desk</span>
            </button>
            <div className="flex items-center gap-2 min-w-0">
              <FlaskConical className="w-5 h-5 text-purple-400 shrink-0" />
              <div className="min-w-0">
                <h1 className="text-base font-bold tracking-wide truncate">
                  OMEGA QUANT RESEARCH & STRATEGY EVALUATION LAB
                </h1>
                <p className="text-[11px] text-slate-400 hidden sm:block truncate">
                  Phase 13 Systematic Walk-Forward Research, Statutory Friction & Pre-Trade Risk Gates
                </p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-1 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-mono font-semibold">
              STRICT PAPER ONLY
            </span>
            <span className="px-2.5 py-1 rounded-md bg-purple-500/10 border border-purple-500/20 text-purple-300 text-xs font-mono font-semibold">
              Epoch: {selectedEpoch === 'epoch_10k' ? '₹10,000 Sandbox' : selectedEpoch}
            </span>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-2 mt-4 border-b border-slate-800/80 -mb-4 pb-2">
          <button
            onClick={() => setActiveTab('registry')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeTab === 'registry'
                ? 'bg-purple-600 text-white shadow-sm shadow-purple-900/50'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Strategy Registry ({strategies.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('runner')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeTab === 'runner'
                ? 'bg-purple-600 text-white shadow-sm shadow-purple-900/50'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
            }`}
          >
            <Play className="w-3.5 h-3.5" />
            <span>Experiment Runner & Queue</span>
          </button>

          <button
            onClick={() => setActiveTab('results')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeTab === 'results'
                ? 'bg-purple-600 text-white shadow-sm shadow-purple-900/50'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Tear Sheet & Evidence ({experiments.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('explainability')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeTab === 'explainability'
                ? 'bg-purple-600 text-white shadow-sm shadow-purple-900/50'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
            }`}
          >
            <Cpu className="w-3.5 h-3.5" />
            <span>Explainability & Multi-Agent Gate</span>
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="p-4 sm:p-6 space-y-6">
        {/* TAB 1: STRATEGY REGISTRY */}
        {activeTab === 'registry' && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {strategies.map((strat) => (
                <div
                  key={strat.strategy_id}
                  onClick={() => setSelectedStrategyId(strat.strategy_id)}
                  className={`p-4 rounded-xl border transition cursor-pointer ${
                    selectedStrategyId === strat.strategy_id
                      ? 'bg-purple-950/20 border-purple-500/50 ring-1 ring-purple-500/20'
                      : 'bg-slate-900/80 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <span className="font-mono text-xs font-bold text-purple-400">{strat.strategy_id}</span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                      {strat.lifecycle_state}
                    </span>
                  </div>
                  <h3 className="text-sm font-bold text-slate-100">{strat.strategy_name}</h3>
                  <p className="text-xs text-slate-400 mt-1 line-clamp-2">{strat.description}</p>
                  <div className="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-500 font-mono">
                    <span>Granularity: {strat.required_granularity}</span>
                    <span>Verdict: {strat.verdict}</span>
                  </div>
                </div>
              ))}
            </div>

            {selectedStrat && (
              <div className="p-5 bg-slate-900 border border-slate-800 rounded-xl space-y-4">
                <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                  <div>
                    <h2 className="text-base font-bold text-slate-100">{selectedStrat.strategy_name} ({selectedStrat.strategy_id})</h2>
                    <p className="text-xs text-slate-400 mt-0.5">Version {selectedStrat.version} • {selectedStrat.source_code_version}</p>
                  </div>
                  <span className="px-3 py-1 rounded-md text-xs font-bold bg-amber-500/10 border border-amber-500/20 text-amber-400">
                    Verdict: {selectedStrat.verdict}
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                  <div className="p-3 bg-slate-950/70 border border-slate-800/80 rounded-lg">
                    <h4 className="font-semibold text-slate-300 mb-1 flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-purple-400" />
                      <span>Hypothesis & Economic Rationale</span>
                    </h4>
                    <p className="text-slate-400 mb-2">{selectedStrat.hypothesis}</p>
                    <p className="text-slate-500 italic">{selectedStrat.economic_rationale}</p>
                  </div>

                  <div className="p-3 bg-slate-950/70 border border-slate-800/80 rounded-lg">
                    <h4 className="font-semibold text-slate-300 mb-1 flex items-center gap-1.5">
                      <ShieldAlert className="w-3.5 h-3.5 text-red-400" />
                      <span>Known Limitations & Prohibited Use</span>
                    </h4>
                    <ul className="list-disc list-inside text-slate-400 space-y-1">
                      {selectedStrat.known_limitations?.map((lim, idx) => (
                        <li key={idx}>{lim}</li>
                      ))}
                    </ul>
                  </div>
                </div>

                <div className="p-3 bg-slate-950/70 border border-slate-800/80 rounded-lg text-xs">
                  <h4 className="font-semibold text-slate-300 mb-2">Default Parameter Constraints</h4>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono text-[11px]">
                    {Object.entries(selectedStrat.default_parameters || {}).map(([k, v]) => (
                      <div key={k} className="p-2 bg-slate-900 border border-slate-800 rounded">
                        <span className="text-slate-500 block truncate">{k}</span>
                        <span className="text-purple-300 font-bold">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* TAB 2: EXPERIMENT RUNNER & QUEUE */}
        {activeTab === 'runner' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-1 p-5 bg-slate-900 border border-slate-800 rounded-xl space-y-4">
              <h2 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                <Sliders className="w-4 h-4 text-purple-400" />
                <span>Configure Walk-Forward Experiment</span>
              </h2>

              <div className="space-y-3 text-xs">
                <div>
                  <label className="text-slate-400 block mb-1 font-medium">Target Strategy:</label>
                  <select
                    value={selectedStrategyId}
                    onChange={(e) => setSelectedStrategyId(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-slate-200 font-mono focus:outline-none focus:border-purple-500"
                  >
                    {strategies.map((s) => (
                      <option key={s.strategy_id} value={s.strategy_id}>
                        {s.strategy_name} ({s.strategy_id})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="text-slate-400 block mb-1 font-medium">Evaluation Dataset:</label>
                  <select
                    value={selectedDatasetId}
                    onChange={(e) => setSelectedDatasetId(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-slate-200 font-mono focus:outline-none focus:border-purple-500"
                  >
                    {datasets.map((d) => (
                      <option key={d.dataset_id} value={d.dataset_id}>
                        {d.dataset_name} ({d.record_count} bars)
                      </option>
                    ))}
                  </select>
                </div>

                <div className="pt-2 border-t border-slate-800 space-y-3">
                  <div>
                    <div className="flex justify-between text-slate-400 mb-1">
                      <span>Range Minutes:</span>
                      <span className="font-mono text-purple-300 font-bold">{paramRangeMinutes}m</span>
                    </div>
                    <input
                      type="range"
                      min="5"
                      max="30"
                      step="5"
                      value={paramRangeMinutes}
                      onChange={(e) => setParamRangeMinutes(Number(e.target.value))}
                      className="w-full accent-purple-500"
                    />
                  </div>

                  <div>
                    <div className="flex justify-between text-slate-400 mb-1">
                      <span>Buffer ATR Mult:</span>
                      <span className="font-mono text-purple-300 font-bold">{paramBufferAtr}x</span>
                    </div>
                    <input
                      type="range"
                      min="0.0"
                      max="0.5"
                      step="0.05"
                      value={paramBufferAtr}
                      onChange={(e) => setParamBufferAtr(Number(e.target.value))}
                      className="w-full accent-purple-500"
                    />
                  </div>

                  <div>
                    <div className="flex justify-between text-slate-400 mb-1">
                      <span>Max Per-Trade Risk:</span>
                      <span className="font-mono text-emerald-400 font-bold">{(paramMaxRiskPct * 100).toFixed(1)}%</span>
                    </div>
                    <input
                      type="range"
                      min="0.002"
                      max="0.02"
                      step="0.001"
                      value={paramMaxRiskPct}
                      onChange={(e) => setParamMaxRiskPct(Number(e.target.value))}
                      className="w-full accent-emerald-500"
                    />
                  </div>
                </div>

                {runError && (
                  <div className="p-3 bg-red-950/40 border border-red-500/30 rounded-lg text-red-300 text-[11px]">
                    <span className="font-bold block mb-0.5">Execution Blocked:</span>
                    {runError}
                  </div>
                )}

                {runSuccess && (
                  <div className="p-3 bg-emerald-950/40 border border-emerald-500/30 rounded-lg text-emerald-300 text-[11px]">
                    <span className="font-bold block mb-0.5">Success:</span>
                    {runSuccess}
                  </div>
                )}

                <button
                  disabled={isRunning}
                  onClick={handleLaunchExperiment}
                  className="w-full mt-2 py-2.5 px-4 rounded-lg bg-purple-600 hover:bg-purple-500 active:bg-purple-700 disabled:opacity-50 text-white font-semibold text-xs flex items-center justify-center gap-2 transition shadow-lg shadow-purple-950/50"
                >
                  {isRunning ? (
                    <>
                      <RotateCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Deliberating & Running...</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-3.5 h-3.5" />
                      <span>Run Controlled Experiment</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Jobs Queue Table */}
            <div className="lg:col-span-2 p-5 bg-slate-900 border border-slate-800 rounded-xl space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                  <Clock className="w-4 h-4 text-cyan-400" />
                  <span>Durable Research Job Scheduler</span>
                </h3>
                <span className="text-xs text-slate-400 font-mono">{jobs.length} Jobs Tracked</span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs font-mono">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-400 text-[11px]">
                      <th className="py-2 px-3">Job ID</th>
                      <th className="py-2 px-3">Strategy</th>
                      <th className="py-2 px-3">Dataset</th>
                      <th className="py-2 px-3">State</th>
                      <th className="py-2 px-3">Step</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {jobs.length === 0 ? (
                      <tr>
                        <td colSpan="5" className="py-6 text-center text-slate-500">
                          No research jobs currently queued.
                        </td>
                      </tr>
                    ) : (
                      jobs.map((j) => (
                        <tr key={j.job_id} className="hover:bg-slate-800/30">
                          <td className="py-2.5 px-3 font-bold text-purple-300">{j.job_id}</td>
                          <td className="py-2.5 px-3 text-slate-300">{j.strategy_id}</td>
                          <td className="py-2.5 px-3 text-slate-400 text-[11px] truncate max-w-[140px]">{j.dataset_id}</td>
                          <td className="py-2.5 px-3">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                                j.state === 'COMPLETED'
                                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                  : j.state === 'FAILED'
                                  ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                                  : 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                              }`}
                            >
                              {j.state}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-slate-400 text-[11px] truncate max-w-[200px]">{j.current_step}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* TAB 3: QUANTITATIVE EVIDENCE & TEAR SHEET */}
        {activeTab === 'results' && (
          <div className="space-y-5">
            {latestExperiment ? (
              <>
                <div className="p-5 bg-slate-900 border border-slate-800 rounded-xl space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
                    <div>
                      <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
                        <span>Experiment Tear Sheet: {latestExperiment.experiment_id}</span>
                      </h2>
                      <p className="text-xs text-slate-400 mt-0.5 font-mono">
                        Strategy: {latestExperiment.strategy_id} ({latestExperiment.strategy_version}) • Dataset: {latestExperiment.dataset_id}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="px-3 py-1 rounded bg-slate-800 border border-slate-700 text-xs font-mono text-purple-300">
                        Status: {latestExperiment.status}
                      </span>
                    </div>
                  </div>

                  {/* Top Key Metrics Grid */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-lg">
                      <span className="text-[11px] text-slate-500 font-medium">Net P&L (Cost Adjusted)</span>
                      <div className="text-lg font-bold font-mono text-emerald-400 mt-0.5">
                        {formatCurrency(latestExperiment.performance_metrics?.net_pnl || 0)}
                      </div>
                    </div>

                    <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-lg">
                      <span className="text-[11px] text-slate-500 font-medium">Annualized Sharpe Ratio</span>
                      <div className="text-lg font-bold font-mono text-cyan-400 mt-0.5">
                        {(latestExperiment.performance_metrics?.sharpe_ratio || 0).toFixed(3)}
                      </div>
                    </div>

                    <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-lg">
                      <span className="text-[11px] text-slate-500 font-medium">Maximum Drawdown</span>
                      <div className="text-lg font-bold font-mono text-amber-400 mt-0.5">
                        {(latestExperiment.performance_metrics?.max_drawdown_pct || 0).toFixed(2)}%
                      </div>
                    </div>

                    <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-lg">
                      <span className="text-[11px] text-slate-500 font-medium">Profit Factor</span>
                      <div className="text-lg font-bold font-mono text-purple-400 mt-0.5">
                        {(latestExperiment.performance_metrics?.profit_factor || 0).toFixed(2)}
                      </div>
                    </div>
                  </div>

                  {/* Rejection / Limitation Alerts */}
                  {latestExperiment.rejection_reasons?.length > 0 && (
                    <div className="p-4 bg-amber-950/30 border border-amber-500/30 rounded-xl space-y-1">
                      <div className="text-xs font-bold text-amber-400 flex items-center gap-1.5">
                        <AlertTriangle className="w-4 h-4" />
                        <span>Data Sufficiency / Methodological Boundary Warning:</span>
                      </div>
                      {latestExperiment.rejection_reasons.map((r, i) => (
                        <p key={i} className="text-xs text-amber-300/90 pl-5">• {r}</p>
                      ))}
                    </div>
                  )}

                  {/* Friction & Execution Breakdown */}
                  <div className="p-4 bg-slate-950/70 border border-slate-800/80 rounded-xl space-y-3">
                    <h4 className="text-xs font-bold text-slate-300">Statutory & Brokerage Friction Model</h4>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs font-mono">
                      <div>
                        <span className="text-slate-500 block">Slippage Model:</span>
                        <span className="text-slate-300 font-semibold">{latestExperiment.slippage_model}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Cost Schedule:</span>
                        <span className="text-slate-300 font-semibold">{latestExperiment.cost_schedule_version}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Reproducibility SHA-256:</span>
                        <span className="text-purple-400 text-[10px] truncate block">{latestExperiment.reproducibility_hash}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="p-12 text-center text-slate-500 bg-slate-900 border border-slate-800 rounded-xl">
                No experiment results recorded yet. Launch an experiment from the Runner tab.
              </div>
            )}
          </div>
        )}

        {/* TAB 4: EXPLAINABILITY & MULTI-AGENT COUNCIL */}
        {activeTab === 'explainability' && (
          <div className="space-y-5">
            <div className="p-5 bg-slate-900 border border-slate-800 rounded-xl space-y-4">
              <div className="border-b border-slate-800 pb-3">
                <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
                  <ShieldAlert className="w-4 h-4 text-purple-400" />
                  <span>Independent Multi-Agent Pre-Trade Deliberation Ledger</span>
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Verifiable roles for Max (Quant/RMS), Emily (Data Quality), Alexa (Circulars/Macro), and Manager Iva (Synthesis).
                </p>
              </div>

              {explainData?.latest_deliberation ? (
                <div className="space-y-4">
                  <div className="flex items-center justify-between p-3 bg-slate-950 border border-slate-800 rounded-lg text-xs">
                    <div>
                      <span className="text-slate-500 block">Deliberation ID:</span>
                      <span className="font-mono text-purple-300 font-bold">{explainData.latest_deliberation.deliberation_id}</span>
                    </div>
                    <div>
                      <span className="text-slate-500 block">Council Decision:</span>
                      <span
                        className={`font-mono font-bold ${
                          explainData.latest_deliberation.final_decision === 'PROCEED_TO_EXPERIMENT'
                            ? 'text-emerald-400'
                            : 'text-amber-400'
                        }`}
                      >
                        {explainData.latest_deliberation.final_decision}
                      </span>
                    </div>
                  </div>

                  {/* 4 Agent Cards */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {explainData.latest_deliberation.agent_tasks?.map((task) => (
                      <div
                        key={task.agent}
                        className={`p-4 rounded-xl border text-xs space-y-2 ${
                          task.blocker
                            ? 'bg-amber-950/20 border-amber-500/40'
                            : 'bg-slate-950/80 border-slate-800'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-bold font-mono text-purple-300">{task.agent}</span>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                              task.status === 'COMPLETED'
                                ? 'bg-emerald-500/10 text-emerald-400'
                                : 'bg-amber-500/10 text-amber-400'
                            }`}
                          >
                            {task.status}
                          </span>
                        </div>
                        <p className="text-slate-400 font-medium">{task.role}</p>
                        {task.blocker && (
                          <div className="p-2 bg-amber-500/10 border border-amber-500/20 rounded text-amber-300 text-[11px]">
                            <strong>Blocker:</strong> {task.blocker}
                          </div>
                        )}
                        <div className="pt-2 border-t border-slate-800/80 text-[11px] text-slate-500 font-mono">
                          {JSON.stringify(task.findings)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="p-8 text-center text-slate-500 text-xs">
                  No previous council deliberations found for this strategy. Run an experiment to record deliberation evidence.
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
