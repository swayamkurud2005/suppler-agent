import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BarChart3,
  CheckCircle2,
  Clock3,
  Loader2,
  Play,
  RefreshCw,
  ShieldAlert,
} from 'lucide-react';
import {
  getEvaluationRecords,
  listEvaluationRuns,
  startEvaluationRun,
} from '../services/api/evaluations';
import './AiQuality.css';

const metricInfo = [
  { id: 'faithfulness', label: 'Faithfulness', description: 'Answer claims grounded in retrieved evidence' },
  { id: 'answer_relevancy', label: 'Answer relevancy', description: 'How directly the answer addresses the question' },
  { id: 'context_precision', label: 'Context precision', description: 'Relevant evidence ranked near the top' },
  { id: 'context_recall', label: 'Context recall', description: 'Reference facts covered by retrieved evidence' },
];

const formatScore = (value) => Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—';

function MetricValue({ value }) {
  if (!Number.isFinite(value)) return <span className="quality-score-empty">No score</span>;
  return <span className="quality-score-value">{formatScore(value)}</span>;
}

function StatusBadge({ status }) {
  const icon = status === 'completed'
    ? <CheckCircle2 size={14} />
    : ['queued', 'running'].includes(status)
      ? <Loader2 size={14} className="quality-spin" />
      : <Clock3 size={14} />;
  return <span className={`quality-status quality-status-${status || 'unknown'}`}>{icon}{status || 'unknown'}</span>;
}

export default function AiQuality() {
  const [runs, setRuns] = useState([]);
  const [records, setRecords] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [limit, setLimit] = useState(10);
  const [acknowledged, setAcknowledged] = useState(false);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const refreshRuns = useCallback(async () => {
    setError('');
    try {
      const latestRuns = await listEvaluationRuns();
      setRuns(latestRuns);
      if (selectedRunId && !latestRuns.some((run) => run.run_id === selectedRunId)) {
        setSelectedRunId('');
        setRecords([]);
      }
    } catch (err) {
      setError(err.message || 'Could not load evaluation runs.');
    } finally {
      setLoadingRuns(false);
    }
  }, [selectedRunId]);

  useEffect(() => { refreshRuns(); }, [refreshRuns]);

  const hasActiveRun = runs.some((run) => ['queued', 'running'].includes(run.status));
  useEffect(() => {
    if (!hasActiveRun) return undefined;
    const timer = window.setInterval(refreshRuns, 4000);
    return () => window.clearInterval(timer);
  }, [hasActiveRun, refreshRuns]);

  const completedRuns = useMemo(() => runs.filter((run) => run.status === 'completed'), [runs]);
  const latestRun = completedRuns[0];

  const chooseRun = async (runId) => {
    setSelectedRunId(runId);
    setRecords([]);
    setError('');
    try {
      setRecords(await getEvaluationRecords(runId));
    } catch (err) {
      setError(err.message || 'Could not load evaluation records.');
    }
  };

  const handleStart = async (event) => {
    event.preventDefault();
    setStarting(true);
    setError('');
    setNotice('');
    try {
      const run = await startEvaluationRun({ limit: Number(limit) || undefined, allowExternalCalls: acknowledged });
      setNotice(`Run ${run.run_id} queued. Scores will appear here when it finishes.`);
      setAcknowledged(false);
      await refreshRuns();
    } catch (err) {
      setError(err.message || 'Could not start the evaluation.');
    } finally {
      setStarting(false);
    }
  };

  return (
    <section className="quality-page">
      <header className="quality-header">
        <div>
          <div className="quality-eyebrow"><BarChart3 size={15} /> AI QUALITY</div>
          <h1>Evaluation runs</h1>
          <p>Measure answer grounding and retrieval quality against the validated contract question set.</p>
        </div>
        <button className="quality-refresh" type="button" onClick={refreshRuns} disabled={loadingRuns}>
          <RefreshCw size={16} className={loadingRuns ? 'quality-spin' : ''} /> Refresh
        </button>
      </header>

      {error && <div className="quality-alert quality-alert-error" role="alert">{error}</div>}
      {notice && <div className="quality-alert quality-alert-info" role="status">{notice}</div>}

      <div className="quality-metrics">
        {metricInfo.map((metric) => (
          <article className="quality-metric-card" key={metric.id}>
            <div className="quality-metric-label">{metric.label}</div>
            <MetricValue value={latestRun?.metrics?.[metric.id]?.mean} />
            <div className="quality-metric-description">{metric.description}</div>
            <div className="quality-metric-count">
              {latestRun?.metrics?.[metric.id]?.scored_count ?? 0} scored in latest run
            </div>
          </article>
        ))}
      </div>

      <div className="quality-columns">
        <section className="quality-panel quality-run-panel">
          <div className="quality-panel-heading">
            <div>
              <h2>Start an evaluation</h2>
              <p>Evaluation endpoints are available only when the backend runs in development mode.</p>
            </div>
          </div>
          <form onSubmit={handleStart}>
            <label className="quality-field-label" htmlFor="evaluation-limit">Questions to run</label>
            <input
              id="evaluation-limit"
              className="quality-number-input"
              type="number"
              min="1"
              max="100"
              value={limit}
              onChange={(event) => setLimit(event.target.value)}
            />
            <label className="quality-consent">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />
              <span>
                I understand this run sends the questions, generated answers, and retrieved contract excerpts to Groq for generation and scoring.
              </span>
            </label>
            <div className="quality-privacy-note"><ShieldAlert size={16} /> Langfuse content capture remains off; evaluation artifacts are stored locally.</div>
            <button className="quality-run-button" type="submit" disabled={!acknowledged || starting || hasActiveRun}>
              {starting ? <Loader2 size={17} className="quality-spin" /> : <Play size={17} />}
              {hasActiveRun ? 'A run is in progress' : starting ? 'Queueing…' : 'Run evaluation'}
            </button>
          </form>
        </section>

        <section className="quality-panel quality-runs-panel">
          <div className="quality-panel-heading">
            <div><h2>Previous runs</h2><p>Each run is saved separately with a unique ID.</p></div>
            <span className="quality-run-count">{runs.length}</span>
          </div>
          {loadingRuns ? (
            <div className="quality-empty"><Loader2 size={20} className="quality-spin" /> Loading runs…</div>
          ) : runs.length === 0 ? (
            <div className="quality-empty">No evaluation runs yet.</div>
          ) : (
            <div className="quality-run-list">
              {runs.map((run) => (
                <button
                  className={`quality-run-row ${selectedRunId === run.run_id ? 'selected' : ''}`}
                  key={run.run_id}
                  type="button"
                  onClick={() => run.status === 'completed' && chooseRun(run.run_id)}
                  disabled={run.status !== 'completed'}
                >
                  <span className="quality-run-main">
                    <strong>{run.run_id}</strong>
                    <small>{run.created_at_utc ? new Date(run.created_at_utc).toLocaleString() : 'Waiting for status'}</small>
                  </span>
                  <span className="quality-run-meta">
                    {run.record_count ? `${run.record_count} questions` : ''}
                    <StatusBadge status={run.status} />
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>

      {selectedRunId && (
        <section className="quality-panel quality-records-panel">
          <div className="quality-panel-heading">
            <div><h2>Question scores</h2><p>Run {selectedRunId}. Answer text and evidence excerpts are not returned by the API.</p></div>
          </div>
          {records.length === 0 ? <div className="quality-empty">No result records were found for this run.</div> : (
            <div className="quality-record-table-wrap">
              <table className="quality-record-table">
                <thead><tr><th>Question</th><th>Category</th><th>Mode</th>{metricInfo.map((item) => <th key={item.id}>{item.label}</th>)}</tr></thead>
                <tbody>
                  {records.map((record) => (
                    <tr key={record.question_id}>
                      <td><strong>{record.question_id}</strong><span>{record.source_document}</span></td>
                      <td>{record.category || '—'}</td>
                      <td>{record.generation_mode || '—'}</td>
                      {metricInfo.map((metric) => {
                        const result = record.metrics?.[metric.id];
                        return <td key={metric.id} title={result?.reason || result?.error_type || ''}>
                          {result?.status === 'scored' ? formatScore(result.score) : result?.status === 'unavailable' ? 'N/A' : 'Error'}
                        </td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </section>
  );
}
