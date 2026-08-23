import { useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';
import './AdminScreen.css';

export interface TestSuite {
  suite_id: string;
  name: string;
  description: string;
  timeout_seconds: number;
}

export interface TestRun {
  run_id: string;
  suite_id: string;
  suite_name: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  start_time: string;
  end_time: string | null;
  error: string | null;
}

export interface MetricsDashboard {
  timestamp: string;
  summary: {
    total_runs_last_20: number;
    successful: number;
    partial: number;
    success_rate: number;
  };
  recent_runs: Array<any>;
  ingester_health: Record<string, any>;
  pipeline_trend: Array<any>;
}

export interface EngineStatus {
  name: string;
  port: number;
  alive: boolean;
  latency_ms: number | null;
  role: string;
}

export interface EnginesStatus {
  engines: EngineStatus[];
  primary_alive: boolean;
}

export function AdminScreen() {
  const [testSuites, setTestSuites] = useState<TestSuite[]>([]);
  const [dashboard, setDashboard] = useState<MetricsDashboard | null>(null);
  const [activeRun, setActiveRun] = useState<TestRun | null>(null);
  const [enginesStatus, setEnginesStatus] = useState<EnginesStatus | null>(null);
  const [engineBusy, setEngineBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'tests' | 'metrics' | 'engines'>('metrics');

  // Load initial data
  useEffect(() => {
    loadTestSuites();
    loadMetricsDashboard();
    loadEnginesStatus();
  }, []);

  // Poll test status if test is running
  useEffect(() => {
    if (!activeRun) return;
    if (activeRun.status === 'success' || activeRun.status === 'failed') return;

    const interval = setInterval(() => {
      pollTestStatus();
    }, 2000);

    return () => clearInterval(interval);
  }, [activeRun]);

  // Poll engine health while the engines tab is open
  useEffect(() => {
    if (tab !== 'engines') return;
    const interval = setInterval(loadEnginesStatus, 10000);
    return () => clearInterval(interval);
  }, [tab]);

  async function loadTestSuites() {
    try {
      const result = await invoke<{ suites: TestSuite[] }>('test_list_suites');
      setTestSuites(result.suites);
      setError(null);
    } catch (err) {
      const message = typeof err === 'string' ? err : JSON.stringify(err);
      setError(`Failed to load test suites: ${message}`);
    }
  }

  async function loadMetricsDashboard() {
    try {
      const result = await invoke<MetricsDashboard>('metrics_get_dashboard');
      setDashboard(result);
      setError(null);
    } catch (err) {
      const message = typeof err === 'string' ? err : JSON.stringify(err);
      setError(`Failed to load metrics: ${message}`);
    }
  }

  async function startTest(suiteId: string) {
    setLoading(true);
    setError(null);

    try {
      const result = await invoke<{ run_id: string }>('test_run_suite', {
        suite_id: suiteId,
      });

      setActiveRun({
        run_id: result.run_id,
        suite_id: suiteId,
        suite_name: testSuites.find((s) => s.suite_id === suiteId)?.name || suiteId,
        status: 'running',
        start_time: new Date().toISOString(),
        end_time: null,
        error: null,
      });

      setTab('tests');
    } catch (err) {
      const message = typeof err === 'string' ? err : JSON.stringify(err);
      setError(`Failed to start test: ${message}`);
    } finally {
      setLoading(false);
    }
  }

  async function loadEnginesStatus() {
    try {
      const result = await invoke<EnginesStatus>('fetch_engines_status');
      setEnginesStatus(result);
      setError(null);
    } catch (err) {
      const message = typeof err === 'string' ? err : JSON.stringify(err);
      setError(`Failed to load engine status: ${message}`);
    }
  }

  async function startEngine(name: string) {
    setEngineBusy(name);
    setError(null);
    try {
      const result = await invoke<{ engine: string; detail: string }>(
        'start_execution_engine',
        { engine: name }
      );
      // Give the probe inside start a moment to settle, then refresh
      setTimeout(loadEnginesStatus, 1500);
      setError(null);
      console.log(result.detail);
    } catch (err) {
      const message = typeof err === 'string' ? err : JSON.stringify(err);
      setError(`Failed to start ${name} engine: ${message}`);
    } finally {
      setEngineBusy(null);
    }
  }

  async function pollTestStatus() {
    if (!activeRun) return;

    try {
      const result = await invoke<TestRun>('test_get_status', {
        run_id: activeRun.run_id,
      });

      setActiveRun(result);

      if (result.status === 'success' || result.status === 'failed') {
        await loadMetricsDashboard();
      }
    } catch (err) {
      console.error('Failed to poll test status:', err);
    }
  }

  async function getTestResults() {
    if (!activeRun) return;

    try {
      const result = await invoke<any>('test_get_results', {
        run_id: activeRun.run_id,
      });

      return result;
    } catch (err) {
      const message = typeof err === 'string' ? err : JSON.stringify(err);
      setError(`Failed to get results: ${message}`);
      return null;
    }
  }
  void getTestResults;

  return (
    <div className="admin-screen">
      <div className="admin-header">
        <h1>🔬 Admin Screen - Testing & Metrics</h1>
        <div className="tab-buttons">
          <button
            className={`tab-btn ${tab === 'metrics' ? 'active' : ''}`}
            onClick={() => setTab('metrics')}
          >
            📊 Metrics
          </button>
          <button
            className={`tab-btn ${tab === 'tests' ? 'active' : ''}`}
            onClick={() => setTab('tests')}
          >
            🧪 Tests
          </button>
          <button
            className={`tab-btn ${tab === 'engines' ? 'active' : ''}`}
            onClick={() => {
              setTab('engines');
              loadEnginesStatus();
            }}
          >
            ⚙️ Engines
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {tab === 'metrics' && (
        <div className="metrics-panel">
          <div className="panel-header">
            <h2>Metrics Dashboard</h2>
            <button onClick={loadMetricsDashboard} disabled={loading}>
              🔄 Refresh
            </button>
          </div>

          {dashboard ? (
            <div className="metrics-content">
              <div className="summary-cards">
                <div className="card">
                  <div className="card-label">Total Runs (last 20)</div>
                  <div className="card-value">{dashboard.summary.total_runs_last_20}</div>
                </div>
                <div className="card">
                  <div className="card-label">Success Rate</div>
                  <div className="card-value">
                    {(dashboard.summary.success_rate * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="card">
                  <div className="card-label">Successful</div>
                  <div className="card-value">{dashboard.summary.successful}</div>
                </div>
                <div className="card">
                  <div className="card-label">Partial</div>
                  <div className="card-value">{dashboard.summary.partial}</div>
                </div>
              </div>

              <div className="recent-runs">
                <h3>Recent Test Runs</h3>
                {dashboard.recent_runs.length > 0 ? (
                  <table>
                    <thead>
                      <tr>
                        <th>Run ID</th>
                        <th>Status</th>
                        <th>Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dashboard.recent_runs.slice(0, 5).map((run: any) => (
                        <tr key={run.run_id}>
                          <td className="monospace">{run.run_id.substring(0, 12)}</td>
                          <td>
                            <span className={`status-badge ${run.status}`}>
                              {run.status}
                            </span>
                          </td>
                          <td>{run.start_time}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="empty-state">No recent runs</p>
                )}
              </div>
            </div>
          ) : (
            <div className="loading">Loading metrics...</div>
          )}
        </div>
      )}

      {tab === 'engines' && (
        <div className="engines-panel">
          <div className="panel-header">
            <h2>Execution Engines</h2>
            <button onClick={loadEnginesStatus}>
              🔄 Refresh
            </button>
          </div>

          {enginesStatus ? (
            <>
              {!enginesStatus.primary_alive && (
                <div className="error-banner">
                  ⚠️ Primary (C++) engine is down — signals will fail over to the Rust
                  secondary automatically.
                </div>
              )}
              <div className="summary-cards">
                {enginesStatus.engines.map((e) => (
                  <div className="card" key={e.name}>
                    <div className="card-label">
                      {e.name.toUpperCase()} · :{e.port} · {e.role}
                    </div>
                    <div className="card-value">
                      <span
                        className={`status-badge ${e.alive ? 'success' : 'failed'}`}
                        style={{ fontSize: '0.9em', marginRight: 8 }}
                      >
                        {e.alive ? 'LIVE' : 'DOWN'}
                      </span>
                      {e.alive && e.latency_ms != null
                        ? `${e.latency_ms.toFixed(2)}ms`
                        : '—'}
                    </div>
                    <button
                      style={{ marginTop: 8 }}
                      disabled={engineBusy != null || e.alive}
                      onClick={() => startEngine(e.name)}
                    >
                      {engineBusy === e.name
                        ? 'Starting…'
                        : e.alive
                          ? 'Running'
                          : `Start ${e.name}`}
                    </button>
                  </div>
                ))}
              </div>
              <p className="empty-state" style={{ marginTop: 16 }}>
                Health = TCP connect probe to the engine's msgpack port. Starting the
                C++ engine launches it inside WSL; starting the Rust engine spawns the
                local release binary. Auto-refreshes every 10s while this tab is open.
              </p>
            </>
          ) : (
            <div className="loading">Loading engine status...</div>
          )}
        </div>
      )}

      {tab === 'tests' && (
        <div className="tests-panel">
          <div className="panel-header">
            <h2>Test Suites</h2>
            <button onClick={loadTestSuites} disabled={loading}>
              🔄 Reload
            </button>
          </div>

          {activeRun && (
            <div className="active-test">
              <h3>Currently Running Test</h3>
              <div className="run-status">
                <div className="run-header">
                  <h4>{activeRun.suite_name}</h4>
                  <span className={`status-badge ${activeRun.status}`}>
                    {activeRun.status}
                  </span>
                </div>

                <div className="run-details">
                  <p>
                    <strong>Run ID:</strong> <code>{activeRun.run_id}</code>
                  </p>
                  <p>
                    <strong>Started:</strong> {new Date(activeRun.start_time).toLocaleString()}
                  </p>

                  {activeRun.status === 'running' && (
                    <div className="progress-bar">
                      <div className="progress-fill"></div>
                    </div>
                  )}

                  {activeRun.error && (
                    <div className="error-details">
                      <strong>Error:</strong>
                      <pre>{activeRun.error}</pre>
                    </div>
                  )}

                  {activeRun.status === 'success' && (
                    <TestResults runId={activeRun.run_id} />
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="test-suites">
            <h3>Available Test Suites</h3>
            {testSuites.length > 0 ? (
              <div className="suite-grid">
                {testSuites.map((suite) => (
                  <div key={suite.suite_id} className="suite-card">
                    <h4>{suite.name}</h4>
                    <p>{suite.description}</p>
                    <div className="suite-meta">
                      <span>⏱️ {suite.timeout_seconds}s</span>
                    </div>
                    <button
                      className="run-btn"
                      onClick={() => startTest(suite.suite_id)}
                      disabled={loading || activeRun?.status === 'running'}
                    >
                      {loading ? 'Starting...' : 'Run Test'}
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="loading">Loading test suites...</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function TestResults({ runId }: { runId: string }) {
  const [results, setResults] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadResults();
  }, [runId]);

  async function loadResults() {
    setLoading(true);
    try {
      const data = await invoke<any>('test_get_results', { run_id: runId });
      setResults(data);
    } catch (err) {
      console.error('Failed to load results:', err);
    } finally {
      setLoading(false);
    }
  }

  if (loading) return <div className="loading">Loading results...</div>;
  if (!results) return <div className="error">No results available</div>;

  return (
    <div className="test-results">
      <h4>Test Results</h4>
      <pre>{JSON.stringify(results, null, 2)}</pre>
    </div>
  );
}

export default AdminScreen;
