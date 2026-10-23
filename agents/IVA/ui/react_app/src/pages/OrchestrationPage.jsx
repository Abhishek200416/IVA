import React, { useState, useEffect } from 'react';
import {
  GitPullRequest,
  ArrowLeft,
  Search,
  CheckCircle2,
  Clock,
  AlertTriangle,
  RefreshCw,
  Play,
  XCircle,
  CornerDownRight,
  ChevronRight,
  ShieldAlert,
  Layers,
  Bot,
  Activity,
  Calendar,
  Sliders,
  Check
} from 'lucide-react';
import { api } from '../services/api';

export default function OrchestrationPage({ onBackToTrading }) {
  const [tasks, setTasks] = useState([]);
  const [overview, setOverview] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [stateFilter, setStateFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTask, setSelectedTask] = useState(null);
  const [cancellingId, setCancellingId] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);

  const loadOrchestrationData = async () => {
    setIsLoading(true);
    try {
      const [ovData, tasksData] = await Promise.all([
        api.getOrchestrationOverview().catch(() => null),
        api.getOrchestrationTasks().catch(() => null)
      ]);
      if (ovData) setOverview(ovData);
      if (tasksData && tasksData.tasks) setTasks(tasksData.tasks);
    } catch (err) {
      console.error('Failed to load orchestration data:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadOrchestrationData();
  }, []);

  const handleCancelTask = async (taskId) => {
    if (!window.confirm(`Are you sure you want to cancel task ${taskId}?`)) return;
    setCancellingId(taskId);
    setActionMessage(null);
    try {
      const res = await api.cancelOrchestrationTask(taskId, 'Operator cancelled from UI');
      if (res && res.ok) {
        setActionMessage({
          type: 'success',
          text: `Task ${taskId} cancelled successfully.`
        });
        await loadOrchestrationData();
      }
    } catch (err) {
      setActionMessage({
        type: 'error',
        text: `Failed to cancel task: ${err.message}`
      });
    } finally {
      setCancellingId(null);
    }
  };

  // Metrics derived from tasks list or overview
  const totalTasks = tasks.length;
  const runningTasks = tasks.filter((t) => t.state === 'RUNNING').length;
  const succeededTasks = tasks.filter((t) => t.state === 'SUCCEEDED').length;
  const queuedTasks = tasks.filter((t) => t.state === 'QUEUED' || t.state === 'PENDING').length;
  const failedTasks = tasks.filter((t) => t.state === 'FAILED').length;

  const filteredTasks = tasks.filter((t) => {
    const matchesState =
      stateFilter === 'all'
        ? true
        : stateFilter === 'running'
        ? t.state === 'RUNNING'
        : stateFilter === 'succeeded'
        ? t.state === 'SUCCEEDED'
        : stateFilter === 'queued'
        ? t.state === 'QUEUED' || t.state === 'PENDING'
        : stateFilter === 'failed'
        ? t.state === 'FAILED'
        : true;

    const q = searchQuery.toLowerCase().trim();
    const matchesSearch =
      q === ''
        ? true
        : t.task_id.toLowerCase().includes(q) ||
          (t.title && t.title.toLowerCase().includes(q)) ||
          (t.description && t.description.toLowerCase().includes(q)) ||
          (t.specialist_id && t.specialist_id.toLowerCase().includes(q)) ||
          (t.job_id && t.job_id.toLowerCase().includes(q));

    return matchesState && matchesSearch;
  });

  // Group into root tasks and child tasks
  const rootTasks = filteredTasks.filter((t) => !t.parent_task_id);
  const getChildren = (parentId) => filteredTasks.filter((t) => t.parent_task_id === parentId);

  return (
    <div id="page-orchestration" className="flex-1 flex flex-col h-full w-full bg-slate-950 overflow-y-auto min-w-0 text-slate-100 select-none">
      {/* Top Header */}
      <div className="bg-slate-900 border-b border-slate-800 px-4 sm:px-6 py-4 shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-3 min-w-0">
          <div className="flex items-center gap-3 min-w-0">
            <button
              id="btnBackToTradingFromOrch"
              onClick={onBackToTrading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-xs font-semibold transition shrink-0"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Trading Desk</span>
            </button>
            <div className="flex items-center gap-2 min-w-0">
              <GitPullRequest className="w-5 h-5 text-cyan-400 shrink-0" />
              <div className="min-w-0">
                <h1 className="text-base font-bold tracking-wide truncate">
                  TASK ORCHESTRATION, DAG & RUNTIME JOBS
                </h1>
                <p className="text-[11px] text-slate-400 hidden sm:block truncate">
                  Authoritative TaskStore SQLite WAL Hierarchy, Execution Lineage, Dependencies & Cancellations
                </p>
              </div>
            </div>
          </div>
          <button
            onClick={loadOrchestrationData}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-mono border border-slate-700 transition shrink-0"
            title="Refresh tasks from TaskStore"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-cyan-400 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
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

        {/* Summary Metric Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3 mt-4 min-w-0">
          <div
            onClick={() => setStateFilter('all')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              stateFilter === 'all' ? 'border-cyan-500 ring-1 ring-cyan-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-slate-400 font-medium truncate">Total Tracked Tasks</div>
            <div className="text-lg font-bold font-mono text-slate-100 mt-0.5">{totalTasks} Tasks</div>
          </div>
          <div
            onClick={() => setStateFilter('running')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              stateFilter === 'running' ? 'border-emerald-500 ring-1 ring-emerald-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-emerald-400 font-medium truncate">Running Tasks</div>
            <div className="text-lg font-bold font-mono text-emerald-400 mt-0.5">{runningTasks} Running</div>
          </div>
          <div
            onClick={() => setStateFilter('succeeded')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              stateFilter === 'succeeded' ? 'border-blue-500 ring-1 ring-blue-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-blue-400 font-medium truncate">Succeeded Tasks</div>
            <div className="text-lg font-bold font-mono text-blue-400 mt-0.5">{succeededTasks} Succeeded</div>
          </div>
          <div
            onClick={() => setStateFilter('queued')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              stateFilter === 'queued' ? 'border-amber-500 ring-1 ring-amber-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-amber-400 font-medium truncate">Queued Tasks</div>
            <div className="text-lg font-bold font-mono text-amber-400 mt-0.5">{queuedTasks} Queued</div>
          </div>
          <div
            onClick={() => setStateFilter('failed')}
            className={`p-3 bg-slate-950/80 border rounded-xl cursor-pointer transition min-w-0 ${
              stateFilter === 'failed' ? 'border-rose-500 ring-1 ring-rose-500' : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="text-[11px] text-rose-400 font-medium truncate">Failed Tasks</div>
            <div className="text-lg font-bold font-mono text-rose-400 mt-0.5">{failedTasks} Failed</div>
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="px-4 sm:px-6 py-3 bg-slate-950 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3 shrink-0 min-w-0">
        <div className="flex flex-wrap items-center gap-1 bg-slate-900 p-1 rounded-lg border border-slate-800 text-xs font-semibold">
          {[
            { id: 'all', label: `All (${totalTasks})` },
            { id: 'running', label: `Running (${runningTasks})` },
            { id: 'succeeded', label: `Succeeded (${succeededTasks})` },
            { id: 'queued', label: `Queued (${queuedTasks})` },
            { id: 'failed', label: `Failed (${failedTasks})` }
          ].map((t) => (
            <button
              key={t.id}
              onClick={() => setStateFilter(t.id)}
              className={`px-2.5 py-1 rounded-md transition ${
                stateFilter === t.id
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="relative min-w-0 w-full sm:w-64">
          <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search task ID, title, specialist..."
            className="w-full pl-8 pr-3 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500"
          />
        </div>
      </div>

      {/* Main Task List & Details */}
      <div className="flex-1 p-4 sm:p-6 max-w-7xl mx-auto w-full space-y-3">
        {rootTasks.length === 0 && filteredTasks.length === 0 ? (
          <div className="p-8 text-center text-slate-500 font-mono text-xs bg-slate-900/40 rounded-xl border border-slate-800">
            No orchestration tasks found matching query.
          </div>
        ) : null}

        {/* Render hierarchical DAG cards */}
        {rootTasks.map((rootTask) => {
          const children = getChildren(rootTask.task_id);
          return (
            <div key={rootTask.task_id} className="space-y-2">
              <TaskCard
                task={rootTask}
                onSelect={() => setSelectedTask(rootTask)}
                onCancel={() => handleCancelTask(rootTask.task_id)}
                isCancelling={cancellingId === rootTask.task_id}
                isRoot={true}
              />
              {children.length > 0 && (
                <div className="pl-6 sm:pl-8 space-y-2 border-l-2 border-cyan-900/40 ml-4 sm:ml-6 mt-2">
                  {children.map((child) => (
                    <TaskCard
                      key={child.task_id}
                      task={child}
                      onSelect={() => setSelectedTask(child)}
                      onCancel={() => handleCancelTask(child.task_id)}
                      isCancelling={cancellingId === child.task_id}
                      isRoot={false}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}

        {/* Render orphaned or un-rooted children if filter filtered out the root */}
        {filteredTasks
          .filter((t) => t.parent_task_id && !rootTasks.some((r) => r.task_id === t.parent_task_id))
          .map((orphan) => (
            <TaskCard
              key={orphan.task_id}
              task={orphan}
              onSelect={() => setSelectedTask(orphan)}
              onCancel={() => handleCancelTask(orphan.task_id)}
              isCancelling={cancellingId === orphan.task_id}
              isRoot={false}
            />
          ))}
      </div>

      {/* Task Inspection Modal / Drawer */}
      {selectedTask && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-slate-900 border border-slate-700/80 rounded-2xl max-w-2xl w-full p-5 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between border-b border-slate-800 pb-3">
              <div>
                <span className="text-xs font-mono text-cyan-400 font-bold">{selectedTask.task_id}</span>
                <h3 className="text-base font-bold text-slate-100 mt-0.5">{selectedTask.title || 'Untitled Task'}</h3>
              </div>
              <button
                onClick={() => setSelectedTask(null)}
                className="text-slate-400 hover:text-white p-1 text-lg font-bold"
              >
                ×
              </button>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">{selectedTask.description}</p>

            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                <span className="text-slate-500 text-[10px] block">State / Health:</span>
                <span className="font-bold">
                  <span className={selectedTask.state === 'RUNNING' ? 'text-emerald-400' : 'text-slate-200'}>{selectedTask.state}</span>
                  {selectedTask.execution_health && (
                    <span className="text-[10px] ml-1.5 px-1 py-0.2 rounded bg-slate-900 border border-slate-700 text-cyan-300">
                      {selectedTask.execution_health}
                    </span>
                  )}
                </span>
              </div>
              <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                <span className="text-slate-500 text-[10px] block">Provenance:</span>
                <span className="text-amber-300 font-bold">{selectedTask.provenance || 'SEEDED_FIXTURE'}</span>
              </div>
              <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                <span className="text-slate-500 text-[10px] block">Specialist Assigned:</span>
                <span className="text-cyan-300 font-bold">{selectedTask.specialist_id || selectedTask.specialist_role}</span>
              </div>
              <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                <span className="text-slate-500 text-[10px] block">Worker PID:</span>
                <span className="text-slate-300 font-mono">{selectedTask.pid || selectedTask.worker_pid || 'None (No Active OS Process)'}</span>
              </div>
              <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                <span className="text-slate-500 text-[10px] block">Job ID:</span>
                <span className="text-slate-300">{selectedTask.job_id}</span>
              </div>
              <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                <span className="text-slate-500 text-[10px] block">Parent Task:</span>
                <span className="text-slate-300">{selectedTask.parent_task_id || 'None (Root Task)'}</span>
              </div>
            </div>

            {/* Verification Evidence */}
            {selectedTask.verification_evidence && Object.keys(selectedTask.verification_evidence).length > 0 && (
              <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 text-xs">
                <div className="text-[10px] font-bold text-cyan-400 uppercase tracking-wide">Verification Evidence</div>
                <pre className="font-mono text-[10.5px] text-cyan-200 mt-1.5 overflow-x-auto whitespace-pre-wrap">
                  {JSON.stringify(selectedTask.verification_evidence, null, 2)}
                </pre>
              </div>
            )}

            {/* Checkpoint / Results */}
            {selectedTask.result && Object.keys(selectedTask.result).length > 0 && (
              <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 text-xs">
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Result Payload</div>
                <pre className="font-mono text-[10.5px] text-slate-300 mt-1.5 overflow-x-auto whitespace-pre-wrap">
                  {JSON.stringify(selectedTask.result, null, 2)}
                </pre>
              </div>
            )}

            <div className="flex justify-end pt-2 border-t border-slate-800">
              <button
                onClick={() => setSelectedTask(null)}
                className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TaskCard({ task, onSelect, onCancel, isCancelling, isRoot }) {
  const isRunning = task.state === 'RUNNING';
  const isSucceeded = task.state === 'SUCCEEDED';
  const isQueued = task.state === 'QUEUED' || task.state === 'PENDING';
  const isFailed = task.state === 'FAILED';
  const isStale = task.is_stale || task.execution_health === 'STALE_HEARTBEAT' || task.execution_health === 'ORPHANED_DEAD';

  return (
    <div
      className={`p-3.5 bg-slate-900/90 border rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-3 transition ${
        isStale
          ? 'border-amber-500/60 bg-amber-950/20'
          : isRunning
          ? 'border-emerald-500/50 bg-emerald-950/10 shadow-xs'
          : isSucceeded
          ? 'border-slate-800 hover:border-slate-700'
          : isFailed
          ? 'border-rose-900/50 bg-rose-950/10'
          : 'border-slate-800 hover:border-slate-700'
      }`}
    >
      <div className="flex items-start gap-3 min-w-0">
        <div className="p-2 rounded-lg bg-slate-950 border border-slate-800 shrink-0 mt-0.5 sm:mt-0">
          {isStale ? (
            <AlertTriangle className="w-4 h-4 text-amber-400" />
          ) : isRunning ? (
            <Activity className="w-4 h-4 text-emerald-400 animate-spin" />
          ) : isSucceeded ? (
            <CheckCircle2 className="w-4 h-4 text-blue-400" />
          ) : isQueued ? (
            <Clock className="w-4 h-4 text-amber-400" />
          ) : (
            <AlertTriangle className="w-4 h-4 text-rose-400" />
          )}
        </div>

        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] font-mono text-cyan-400 font-bold">{task.task_id}</span>
            {task.job_id && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-400 font-mono">
                {task.job_id}
              </span>
            )}
            <span
              className={`px-1.5 py-0.2 rounded text-[9px] font-mono font-bold uppercase tracking-wider ${
                isRunning
                  ? 'bg-emerald-950 text-emerald-400 border border-emerald-500/40'
                  : isSucceeded
                  ? 'bg-blue-950 text-blue-400 border border-blue-500/40'
                  : isQueued
                  ? 'bg-amber-950 text-amber-400 border border-amber-500/40'
                  : 'bg-rose-950 text-rose-400 border border-rose-500/40'
              }`}
            >
              {task.state}
            </span>

            {/* Provenance Badge */}
            <span
              className={`px-1.5 py-0.2 rounded text-[9px] font-mono font-medium ${
                task.provenance === 'REAL_DISPATCHED'
                  ? 'bg-emerald-950/80 border border-emerald-500/40 text-emerald-300'
                  : 'bg-slate-800 border border-slate-700 text-amber-300'
              }`}
            >
              {task.provenance || 'SEEDED_FIXTURE'}
            </span>

            {/* Health / Staleness Warning Badge */}
            {isStale && (
              <span className="px-1.5 py-0.2 rounded text-[9px] font-mono font-bold bg-amber-950 border border-amber-500 text-amber-300">
                {task.execution_health === 'ORPHANED_DEAD' ? '💀 DEAD PROCESS / NO PID' : '⚠️ STALE HEARTBEAT'}
              </span>
            )}
          </div>

          <h4 className="text-xs font-bold text-slate-100 mt-1 truncate">{task.title || 'Untitled Task'}</h4>
          <p className="text-[11px] text-slate-400 line-clamp-1 mt-0.5">{task.description}</p>

          <div className="flex flex-wrap items-center gap-2 mt-1.5 text-[10px] font-mono text-slate-400">
            <span>
              Specialist: <strong className="text-purple-300">{task.specialist_id || task.specialist_role}</strong>
            </span>
            {task.parent_task_id && (
              <span>
                Parent: <strong className="text-slate-300">{task.parent_task_id}</strong>
              </span>
            )}
            {task.verification_status && (
              <span>
                Verification: <strong className={task.verification_status === 'VERIFIED_PASS' ? 'text-cyan-400' : 'text-amber-400'}>{task.verification_status}</strong>
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
        <button
          onClick={onSelect}
          className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium border border-slate-700 transition"
        >
          Inspect
        </button>

        {isRunning && (
          <button
            onClick={onCancel}
            disabled={isCancelling}
            className="px-2.5 py-1 rounded bg-rose-950/60 hover:bg-rose-900 border border-rose-800 text-rose-300 text-xs font-medium transition"
          >
            {isCancelling ? 'Cancelling...' : 'Cancel'}
          </button>
        )}
      </div>
    </div>
  );
}
