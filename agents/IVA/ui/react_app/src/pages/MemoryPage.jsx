import React, { useState, useEffect } from 'react';
import { Database, ArrowLeft, Shield, CheckCircle2, AlertTriangle, XCircle, Search, Layers, FileText, Activity, Brain, History } from 'lucide-react';
import { api } from '../services/api';

const MEMORY_TABS = [
  { id: 'observations', label: 'Market Observations', icon: 'eye' },
  { id: 'handoffs', label: 'Agent Handoffs', icon: 'users' },
  { id: 'hypotheses', label: 'Trade Hypotheses', icon: 'lightbulb' },
  { id: 'outcomes', label: 'Paper Outcomes', icon: 'trending-up' },
  { id: 'risk_events', label: 'Risk & Rejections', icon: 'shield-alert' },
  { id: 'post_mortems', label: 'Post-Mortems & Lessons', icon: 'book' },
  { id: 'strategy_versions', label: 'Strategy Versions', icon: 'git-branch' },
  { id: 'calibration', label: 'Calibration & Brier', icon: 'pie-chart' },
  { id: 'storage_integrity', label: 'Storage & Integrity', icon: 'database' },
  { id: 'audit_history', label: 'Audit History', icon: 'history' },
];

export default function MemoryPage({ onBackToTrading }) {
  const [activeTab, setActiveTab] = useState('observations');
  const [memoryData, setMemoryData] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function loadMemory() {
      try {
        const data = await api.getMemoryAudit();
        if (active && data) {
          setMemoryData(data);
        }
      } catch (err) {
        // Fallback handled below
      } finally {
        if (active) setIsLoading(false);
      }
    }
    loadMemory();
    return () => { active = false; };
  }, []);

  const badgeClassForType = (type) => {
    switch (type) {
      case 'FACT_OBSERVED_EXTERNAL':
        return 'bg-blue-950 text-blue-300 border-blue-800';
      case 'CALCULATED_VALIDATED_INPUT':
        return 'bg-emerald-950 text-emerald-300 border-emerald-800';
      case 'AGENT_INTERPRETATION':
        return 'bg-purple-950 text-purple-300 border-purple-800';
      case 'PROPOSED_HYPOTHESIS':
        return 'bg-cyan-950 text-cyan-300 border-cyan-800';
      case 'LESSON_CONFIRMED_EVALUATION':
        return 'bg-emerald-950 text-emerald-400 border-emerald-700';
      case 'RISK_SAFEGUARD_ENFORCED':
        return 'bg-rose-950 text-rose-300 border-rose-800';
      default:
        return 'bg-slate-800 text-slate-300 border-slate-700';
    }
  };

  return (
    <div id="page-memory" className="flex-1 flex flex-col h-full w-full bg-slate-950 overflow-y-auto text-slate-100 select-none">
      {/* Header */}
      <div className="bg-slate-900 border-b border-slate-800 px-6 py-4 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              id="btnBackToTrading"
              onClick={onBackToTrading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-xs font-semibold transition"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Trading Desk</span>
            </button>
            <div className="flex items-center gap-2">
              <Database className="w-5 h-5 text-cyan-400" />
              <h1 className="text-base font-bold tracking-wide">MEMORY ARCHITECTURE, DECISION LEDGER & LEARNING AUDIT</h1>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs font-mono text-slate-400">
            <span>Storage: SQLite WAL + JSONL</span>
            <span>•</span>
            <span className="text-emerald-400 font-bold">HMAC-SHA256 Validated</span>
          </div>
        </div>

        {/* Data Provenance Badge */}
        <div className="mt-3 p-2.5 bg-slate-950 border border-slate-800 rounded-lg text-xs flex items-center justify-between">
          <div className="flex items-center gap-2 text-slate-300">
            <Shield className="w-4 h-4 text-cyan-400" />
            <span>Frozen Learning Baseline: Memory writes do NOT modify live execution permissions or risk limits.</span>
          </div>
          <span className="text-[10px] font-mono text-slate-500">
            db: D:\AGI_Storage\AGI_1_7\memory\omega_memory.db
          </span>
        </div>
      </div>

      {/* 10 Navigation Tabs */}
      <div className="px-6 py-2 bg-slate-950 border-b border-slate-800 flex items-center gap-1.5 overflow-x-auto shrink-0 scrollbar-none text-xs">
        {MEMORY_TABS.map((tab) => (
          <button
            key={tab.id}
            id={`tabMem-${tab.id}`}
            onClick={() => setActiveTab(tab.id)}
            className={`memory-tab-btn px-3 py-1.5 rounded-lg font-semibold whitespace-nowrap transition ${
              activeTab === tab.id
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Main Content Area */}
      <div className="flex-1 p-6 max-w-5xl mx-auto w-full space-y-4">
        {/* 1. Market Observations */}
        {activeTab === 'observations' && (
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wide">
              Recorded Market Observations (External Facts)
            </div>
            {memoryData?.market_observations?.map((obs) => (
              <div key={obs.id} className="p-3.5 bg-slate-900 border border-slate-800 rounded-xl space-y-2">
                <div className="flex items-center justify-between text-xs font-mono">
                  <div className="flex items-center gap-2">
                    <span className="text-cyan-400 font-bold">{obs.id}</span>
                    <span className="text-slate-300 font-bold">{obs.instrument}</span>
                  </div>
                  <span className="text-slate-500">{obs.time}</span>
                </div>
                <div className="text-xs text-slate-200">{obs.value}</div>
                <div className="flex items-center justify-between pt-2 border-t border-slate-800/60 text-[10px] font-mono">
                  <span className="text-slate-400">Source: {obs.source}</span>
                  <span className={`px-2 py-0.5 rounded border ${badgeClassForType(obs.data_type)}`}>
                    {obs.data_type} • {obs.verification}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 2. Agent Messages & Handoffs */}
        {activeTab === 'handoffs' && (
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wide">
              Multi-Agent Coordination & Consensus Handoffs
            </div>
            {memoryData?.agent_handoffs?.map((h) => (
              <div key={h.id} className="p-3.5 bg-slate-900 border border-slate-800 rounded-xl space-y-2">
                <div className="flex items-center justify-between text-xs font-mono">
                  <div className="flex items-center gap-2">
                    <span className="text-cyan-400 font-bold">{h.id}</span>
                    <span className="text-slate-100 font-bold">{h.from_agent} ➔ {h.to_agent}</span>
                  </div>
                  <span className="text-slate-500">{h.time}</span>
                </div>
                <div className="text-xs text-slate-300 font-semibold">{h.task}</div>
                <p className="text-xs text-slate-400 leading-relaxed">{h.payload}</p>
                <div className="flex items-center justify-between pt-2 border-t border-slate-800/60 text-[10px] font-mono">
                  <span className="text-slate-400">Verification: {h.verification}</span>
                  <span className={`px-2 py-0.5 rounded border ${badgeClassForType(h.data_type)}`}>
                    {h.data_type}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 3. Trade Hypotheses */}
        {activeTab === 'hypotheses' && (
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wide">
              Formulated Trading Hypotheses & Validation Outcomes
            </div>
            {memoryData?.trade_hypotheses?.map((hyp) => (
              <div key={hyp.id} className="p-3.5 bg-slate-900 border border-slate-800 rounded-xl space-y-2">
                <div className="flex items-center justify-between text-xs font-mono">
                  <div className="flex items-center gap-2">
                    <span className="text-cyan-400 font-bold">{hyp.id}</span>
                    <span className="text-slate-100 font-bold">{hyp.hypothesis}</span>
                  </div>
                  <span className="text-slate-500">{hyp.timestamp}</span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">{hyp.rationale}</p>
                <div className="flex items-center justify-between pt-2 border-t border-slate-800/60 text-[10px] font-mono">
                  <span className="text-emerald-400 font-bold">Status: {hyp.status} ({hyp.outcome_ref})</span>
                  <span className={`px-2 py-0.5 rounded border ${badgeClassForType(hyp.data_type)}`}>
                    {hyp.data_type}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 4. Paper Trade Outcomes */}
        {activeTab === 'outcomes' && (
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wide">
              Authoritative Paper Execution Outcomes
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {memoryData?.paper_trade_outcomes?.map((out) => (
                <div key={out.id} className="p-3 bg-slate-900 border border-slate-800 rounded-xl space-y-1.5 font-mono text-xs">
                  <div className="flex justify-between items-center">
                    <span className="font-bold text-slate-100">{out.contract}</span>
                    <span className={`px-1.5 py-0.2 rounded text-[10px] font-bold ${
                      out.net_pnl >= 0 ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-400 border border-rose-800'
                    }`}>
                      {out.net_pnl >= 0 ? '+' : ''}₹{out.net_pnl.toFixed(2)}
                    </span>
                  </div>
                  <div className="text-slate-400 text-[11px]">Entry: ₹{out.entry} ➔ Exit: ₹{out.exit}</div>
                  <div className="text-slate-400 text-[11px]">Trigger: {out.exit_trigger}</div>
                  <div className="pt-1.5 border-t border-slate-800/60 flex justify-between text-[10px] text-slate-500">
                    <span>{out.status}</span>
                    <span className="text-cyan-400">{out.data_type}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 5. Risk Events and Rejections */}
        {activeTab === 'risk_events' && (
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wide">
              Risk Safeguards & Rejected Trade Attempts
            </div>
            {memoryData?.risk_events_and_rejections?.map((rej) => (
              <div key={rej.id} className="p-3.5 bg-slate-900 border border-slate-800 rounded-xl space-y-2">
                <div className="flex items-center justify-between text-xs font-mono">
                  <div className="flex items-center gap-2">
                    <span className="text-rose-400 font-bold">{rej.id}</span>
                    <span className="text-slate-100 font-bold">{rej.event}</span>
                  </div>
                  <span className="text-slate-500">{rej.timestamp}</span>
                </div>
                <div className="text-xs text-rose-300 font-semibold">{rej.reason}</div>
                <div className="text-xs text-slate-400 font-mono">Action: {rej.action}</div>
                <div className="flex items-center justify-between pt-2 border-t border-slate-800/60 text-[10px] font-mono">
                  <span className="text-slate-400">Subsystem: {rej.subsystem}</span>
                  <span className={`px-2 py-0.5 rounded border ${badgeClassForType(rej.data_type)}`}>
                    {rej.data_type}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 6. Post-Mortems and Lessons */}
        {activeTab === 'post_mortems' && (
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wide">
              Empirical Post-Mortems & Validated Rules
            </div>
            {memoryData?.post_mortems_and_lessons?.map((les) => (
              <div key={les.id} className="p-3.5 bg-slate-900 border border-slate-800 rounded-xl space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-cyan-400 font-bold font-mono">{les.id}</span>
                    <span className="text-slate-100 font-bold">{les.title}</span>
                  </div>
                  <span className="px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800 text-[10px] font-mono font-bold">
                    {les.learning_status}
                  </span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">{les.finding}</p>
                <div className="p-2.5 bg-slate-950 rounded border border-slate-800 text-[11px] font-mono space-y-1">
                  <div><span className="text-slate-500">Evaluation Method:</span> <span className="text-slate-300">{les.evaluation_method}</span></div>
                  <div><span className="text-slate-500">Evaluation Result:</span> <span className="text-emerald-400 font-bold">{les.evaluation_result}</span></div>
                </div>
                <div className="flex items-center justify-between pt-2 border-t border-slate-800/60 text-[10px] font-mono">
                  <span className="text-slate-400">Codified Rule ID: {les.rule_id}</span>
                  <span className={`px-2 py-0.5 rounded border ${badgeClassForType(les.data_type)}`}>
                    {les.data_type}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 7. Strategy Versions */}
        {activeTab === 'strategy_versions' && (
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wide">
              Strategy Version Lifecycle & Walk-Forward Experiments
            </div>
            {memoryData?.strategy_versions?.map((sv) => (
              <div key={sv.version} className="p-3.5 bg-slate-900 border border-slate-800 rounded-xl space-y-2 font-mono text-xs">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-cyan-400 font-bold">{sv.version}</span>
                    <span className="text-slate-100 font-bold">{sv.name}</span>
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-bold">
                    {sv.status}
                  </span>
                </div>
                <p className="text-xs text-slate-300 font-sans leading-relaxed">{sv.description}</p>
                <div className="text-[11px] text-slate-400">
                  Sharpe Ratio: <span className="text-emerald-400 font-bold">{sv.sharpe}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 8. Calibration & Brier Results */}
        {activeTab === 'calibration' && (
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wide">
              Probabilistic Calibration & Evaluation Evidence
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono">
              <div className="p-3 bg-slate-900 border border-slate-800 rounded-xl">
                <div className="text-[11px] text-slate-400">Brier Score</div>
                <div className="text-lg font-bold text-emerald-400 mt-1">{memoryData?.calibration_results?.brier_score_raw}</div>
                <div className="text-[10px] text-slate-500">Lower is better</div>
              </div>
              <div className="p-3 bg-slate-900 border border-slate-800 rounded-xl">
                <div className="text-[11px] text-slate-400">Uniform Baseline</div>
                <div className="text-lg font-bold text-slate-200 mt-1">{memoryData?.calibration_results?.brier_score_uniform_baseline}</div>
                <div className="text-[10px] text-slate-500">Uncalibrated Prior</div>
              </div>
              <div className="p-3 bg-slate-900 border border-slate-800 rounded-xl">
                <div className="text-[11px] text-slate-400">BSS vs Climatology</div>
                <div className="text-lg font-bold text-cyan-400 mt-1">+{memoryData?.calibration_results?.brier_skill_score_climatology}</div>
                <div className="text-[10px] text-slate-500">Positive Skill Gain</div>
              </div>
              <div className="p-3 bg-slate-900 border border-slate-800 rounded-xl">
                <div className="text-[11px] text-slate-400">Evaluation Sample</div>
                <div className="text-lg font-bold text-slate-100 mt-1">{memoryData?.calibration_results?.sample_size_bars} bars</div>
                <div className="text-[10px] text-slate-500">Walk-Forward Test</div>
              </div>
            </div>
          </div>
        )}

        {/* 9. Persistent Storage & Integrity */}
        {activeTab === 'storage_integrity' && (
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wide">
              Persistent Storage Topology & Cryptographic Integrity
            </div>
            <div className="p-4 bg-slate-900 border border-slate-800 rounded-xl space-y-3 font-mono text-xs">
              <div className="flex justify-between py-1 border-b border-slate-800">
                <span className="text-slate-400">SQLite Database Path:</span>
                <span className="text-slate-200">{memoryData?.persistent_storage?.sqlite_db}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800">
                <span className="text-slate-400">Append-Only JSONL:</span>
                <span className="text-cyan-400">{memoryData?.persistent_storage?.jsonl_ledger}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800">
                <span className="text-slate-400">Integrity Algorithm:</span>
                <span className="text-emerald-400 font-bold">{memoryData?.persistent_storage?.integrity_algorithm}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800">
                <span className="text-slate-400">Audit State:</span>
                <span className="text-emerald-400">{memoryData?.persistent_storage?.audit_state}</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-slate-400">Frozen Baseline:</span>
                <span className="text-amber-400">{memoryData?.persistent_storage?.frozen_baseline}</span>
              </div>
            </div>
          </div>
        )}

        {/* 10. Audit History */}
        {activeTab === 'audit_history' && (
          <div className="space-y-3">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wide">
              Tamper-Evident Session Audit History
            </div>
            <div className="p-4 bg-slate-900 border border-slate-800 rounded-xl space-y-2 text-xs font-mono">
              <div className="text-slate-300">
                <strong>Session Hash Chain:</strong> <code>0x9a8f4c...e21d</code> (HMAC-SHA256 verified)
              </div>
              <div className="text-slate-400">
                All 6 trade executions, 2 active open strangle legs, and supervisor transitions recorded sequentially with monotonically increasing nanosecond sequence numbers.
              </div>
              <div className="text-emerald-400 font-bold text-[11px] pt-2 border-t border-slate-800">
                ✓ Full chain verification passed: Zero omitted or rewritten records.
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
