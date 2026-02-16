import { Card, Statistic, Row, Col, Table, Tag, Button, Spin, Alert, Progress } from 'antd';
import { useState, useEffect } from 'react';
import { usePipeline } from '../hooks/usePipeline';
import { useSignal } from '../contexts/SignalContext';
import { transformSignalForRag } from '../utils/signalTransform';

interface SignalsScreenProps {
  onNavigate?: (key: string) => void;
}

export default function SignalsScreen({ onNavigate }: SignalsScreenProps) {
  const [mode, setMode] = useState<'dev' | 'real'>('dev');
  const { isRunning, status, results, error, startPipeline, currentJobId } = usePipeline();
  const [performanceHistory, setPerformanceHistory] = useState<any[]>([]);
  const { setActiveSignal } = useSignal();

  useEffect(() => {
    if (results?.signals) {
      // Update performance history when signals arrive
      setPerformanceHistory(
        results.signals.map((signal, idx) => ({
          key: idx,
          time: new Date(signal.timestamp).toLocaleTimeString(),
          instrument: signal.symbol,
          dir: signal.direction,
          conf: signal.confidence,
          status: 'GENERATED',
          pnl: 'N/A',
          reason: 'Orchestrator Signal',
        }))
      );
    }
  }, [results]);

  const handleRunPipeline = () => {
    startPipeline(mode, false);
  };

  const handleExplainerClick = () => {
    if (activeSignal) {
      // Transform signal to RAG format and set it
      const transformedSignal = transformSignalForRag(activeSignal);
      setActiveSignal(transformedSignal);
      onNavigate?.('explainer');
    }
  };

  // Display active signal or loading state
  const activeSignal = results?.signals?.[0] || null;
  const metrics = results?.metrics;

  return (
    <div style={{ padding: 24 }}>
      {/* Error Banner */}
      {error && (
        <Alert
          message="Pipeline Error"
          description={error}
          type="error"
          closable
          style={{ marginBottom: 16 }}
          showIcon
        />
      )}

      {/* Control Panel */}
      <Card title="Pipeline Control" style={{ marginBottom: 16 }} bordered={false}>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <Button
            type="primary"
            size="large"
            loading={isRunning}
            onClick={handleRunPipeline}
            disabled={isRunning}
          >
            {isRunning ? 'Running Pipeline...' : 'Refresh Signals'}
          </Button>

          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as 'dev' | 'real')}
            disabled={isRunning}
            style={{
              padding: '8px 12px',
              borderRadius: '4px',
              border: '1px solid #d9d9d9',
              cursor: isRunning ? 'not-allowed' : 'pointer',
            }}
          >
            <option value="dev">DEV Mode</option>
            <option value="real">REAL Mode</option>
          </select>

          {currentJobId && (
            <span style={{ fontSize: 12, color: '#888' }}>Job ID: {currentJobId}</span>
          )}
        </div>

        {/* Progress Display */}
        {isRunning && status && (
          <div style={{ marginTop: 16 }}>
            <div style={{ marginBottom: 8 }}>
              <strong>Phase:</strong> {status.phase ? status.phase.replace(/_/g, ' ') : 'processing'} ({status.progress}%)
            </div>
            <Progress percent={status.progress} status={status.status === 'error' ? 'exception' : 'active'} />
          </div>
        )}
      </Card>

      <Row gutter={16}>
        <Col span={12}>
          <Card title="Active Signal" bordered={false}>
            {isRunning ? (
              <div style={{ textAlign: 'center', padding: '20px' }}>
                <Spin tip="Generating signal..." />
              </div>
            ) : activeSignal ? (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <Tag color={activeSignal.direction === 'LONG' ? 'green' : 'red'} style={{ fontSize: 16 }}>
                      {activeSignal.direction}
                    </Tag>
                    <span style={{ fontWeight: 600, fontSize: 18, marginLeft: 8 }}>{activeSignal.symbol}</span>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <span style={{ fontSize: 22, fontWeight: 700, color: '#00ff88' }}>
                      {(activeSignal.confidence * 100).toFixed(0)}%
                    </span>
                    <div style={{ fontSize: 12, color: '#aaa' }}>Confidence</div>
                  </div>
                </div>
                <div style={{ marginTop: 12, fontSize: 14 }}>
                  Generated: {new Date(activeSignal.timestamp).toLocaleString()}
                  <br />
                  Quantity: {activeSignal.target_quantity} contracts
                  <br />
                  Horizon: {activeSignal.horizon_minutes} minutes
                </div>
                <Card type="inner" title="Signal Metadata" style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 12 }}>
                    <div>Signal ID: {activeSignal.signal_id}</div>
                    {activeSignal.metadata && Object.entries(activeSignal.metadata).map(([key, value]: any) => (
                      <div key={key}>
                        {key}: {value}
                      </div>
                    ))}
                  </div>
                </Card>
                <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
                  <Button type="default">📊 View Supporting Data</Button>
                  <Button type="primary" onClick={handleExplainerClick}>🤖 Full Explanation</Button>
                  <Button type="dashed">✓ Execute</Button>
                </div>
              </>
            ) : (
              <div style={{ color: '#999', textAlign: 'center', padding: '20px' }}>
                Click "Refresh Signals" to generate a new trading signal
              </div>
            )}
          </Card>
        </Col>

        <Col span={12}>
          <Card title="Pipeline Metrics" bordered={false}>
            {metrics ? (
              <Row gutter={8}>
                <Col span={12}>
                  <Statistic
                    title="Total Time"
                    value={metrics.total_time.toFixed(2)}
                    suffix="s"
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="Avg Confidence"
                    value={(metrics.avg_confidence * 100).toFixed(0)}
                    suffix="%"
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="Ingestion"
                    value={metrics.ingest_time.toFixed(2)}
                    suffix="s"
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="Feature Engineering"
                    value={metrics.feature_time.toFixed(2)}
                    suffix="s"
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="Inference"
                    value={metrics.inference_time.toFixed(2)}
                    suffix="s"
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="Signals Generated"
                    value={metrics.signals_generated}
                  />
                </Col>
              </Row>
            ) : (
              <div style={{ color: '#999', textAlign: 'center', padding: '20px' }}>
                No metrics available
              </div>
            )}

            {metrics && (
              <div style={{ marginTop: 16, fontSize: 12 }}>
                <div>
                  <strong>Cache Hits:</strong>
                  <span style={{ marginLeft: 8 }}>
                    LMP: {metrics.lmp_cache_hit ? '✓' : '✗'}
                    &nbsp;&nbsp;
                    CME: {metrics.cme_cache_hit ? '✓' : '✗'}
                  </span>
                </div>
                <div style={{ marginTop: 4 }}>
                  <strong>Mode:</strong> {metrics.mode}
                </div>
                <div style={{ marginTop: 4 }}>
                  <strong>Timestamp:</strong> {new Date(metrics.run_timestamp).toLocaleString()}
                </div>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="Signal History" bordered={false}>
            {performanceHistory.length > 0 ? (
              <Table
                size="small"
                dataSource={performanceHistory}
                rowKey="key"
                pagination={{ pageSize: 10 }}
                columns={[
                  { title: 'Time', dataIndex: 'time', width: 120 },
                  { title: 'Instrument', dataIndex: 'instrument', width: 100 },
                  {
                    title: 'Dir',
                    dataIndex: 'dir',
                    width: 60,
                    render: (v) => (
                      <Tag color={v === 'LONG' ? 'green' : 'red'}>{v}</Tag>
                    ),
                  },
                  { title: 'Confidence', dataIndex: 'conf', width: 80, render: (v) => (v * 100).toFixed(0) + '%' },
                  { title: 'Status', dataIndex: 'status', width: 80 },
                  { title: 'P&L', dataIndex: 'pnl', width: 80 },
                  { title: 'Reason', dataIndex: 'reason' },
                ]}
              />
            ) : (
              <div style={{ color: '#999', textAlign: 'center', padding: '20px' }}>
                No signal history yet
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
