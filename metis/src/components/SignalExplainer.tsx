import { useState, useEffect } from 'react';
import { Card, Spin, Alert, Button, Tag, List, Collapse, Empty, Space } from 'antd';
import { ReloadOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import { invoke } from '@tauri-apps/api/core';
import { TradingSignal } from '../contexts/SignalContext';
import { ChatInterface } from './ChatInterface';

interface Citation {
  doc_id: string;
  title: string;
  source: string;
  excerpt: string;
}

interface Explanation {
  signal_id: string;
  market_analysis?: string;
  signal_drivers?: string;
  risks?: string;
  expected_outcome?: string;
  citations: Citation[];
  raw_text: string;
  confidence_score: number;
  generated_at: string;
}

interface SignalExplainerProps {
  signal: TradingSignal;
}

type ExplanationStatus = 'idle' | 'loading' | 'success' | 'timeout' | 'partial' | 'fallback' | 'error';

interface ExplanationResponse {
  status: ExplanationStatus;
  explanation?: Explanation;
  partial_explanation?: Explanation;
  retry_token?: string;
  error_message?: string;
}

export default function SignalExplainer({ signal }: SignalExplainerProps) {
  const [status, setStatus] = useState<ExplanationStatus>('idle');
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [retryToken, setRetryToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Generate explanation on component mount or signal change
  useEffect(() => {
    generateExplanation();
  }, [signal.id]);

  const generateExplanation = async () => {
    setStatus('loading');
    setError(null);

    try {
      // Prepare signal for backend - ensure all required fields are present
      const signalForBackend = {
        id: signal.id,
        signal_id: signal.signal_id,
        instrument: signal.instrument,
        direction: signal.direction,
        confidence: signal.confidence,
        timestamp: signal.timestamp,
        context: signal.context || {
          current_price: 0,
          grid_stress_index: 50,
          temperature_anomaly: 0,
          recent_policy_events: [],
          primary_region: 'ERCOT',
        },
      };

      const response: ExplanationResponse = await invoke('explain_trading_signal', {
        signal: signalForBackend,
      });

      setStatus(response.status);

      if (response.explanation) {
        setExplanation(response.explanation);
      } else if (response.partial_explanation) {
        setExplanation(response.partial_explanation);
      }

      if (response.retry_token) {
        setRetryToken(response.retry_token);
      }

      if (response.error_message) {
        setError(response.error_message);
      }
    } catch (err) {
      setStatus('error');
      setError(`Failed to generate explanation: ${err}`);
      console.error('Explanation generation error:', err);
    }
  };

  const handleRetry = async () => {
    if (!retryToken) return;

    setStatus('loading');
    setError(null);

    try {
      const signalForBackend = {
        id: signal.id,
        signal_id: signal.signal_id,
        instrument: signal.instrument,
        direction: signal.direction,
        confidence: signal.confidence,
        timestamp: signal.timestamp,
        context: signal.context || {
          current_price: 0,
          grid_stress_index: 50,
          temperature_anomaly: 0,
          recent_policy_events: [],
          primary_region: 'ERCOT',
        },
      };

      const response: ExplanationResponse = await invoke('retry_explanation', {
        signal: signalForBackend,
        retry_token: retryToken,
      });

      setStatus(response.status);

      if (response.explanation) {
        setExplanation(response.explanation);
      }

      if (response.error_message) {
        setError(response.error_message);
      }

      setRetryToken(response.retry_token || null);
    } catch (err) {
      setError(`Retry failed: ${err}`);
    }
  };

  const getStatusColor = (): string => {
    switch (status) {
      case 'success':
        return 'green';
      case 'timeout':
      case 'partial':
        return 'orange';
      case 'fallback':
        return 'blue';
      case 'error':
        return 'red';
      default:
        return 'default';
    }
  };

  const getStatusLabel = (): string => {
    switch (status) {
      case 'success':
        return 'Full Analysis';
      case 'timeout':
        return 'Timed Out';
      case 'partial':
        return 'Partial Analysis';
      case 'fallback':
        return 'Template Explanation';
      case 'error':
        return 'Error';
      case 'loading':
        return 'Generating...';
      default:
        return 'Ready';
    }
  };

  if (status === 'loading' && !explanation) {
    return (
      <Card title="Signal Explanation" bordered={false}>
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin size="large" tip="Generating explanation..." />
        </div>
      </Card>
    );
  }

  if (!explanation) {
    return (
      <Card title="Signal Explanation" bordered={false}>
        <Empty description="No explanation available" />
      </Card>
    );
  }

  const sections = [
    {
      key: 'drivers',
      label: 'Signal Drivers',
      children: explanation.signal_drivers || 'Not available',
    },
    {
      key: 'market',
      label: 'Market Analysis',
      children: explanation.market_analysis || 'Not available',
    },
    {
      key: 'outcomes',
      label: 'Expected Outcome',
      children: explanation.expected_outcome || 'Not available',
    },
    {
      key: 'risks',
      label: 'Risk Assessment',
      children: explanation.risks || 'Not available',
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Status Bar */}
      <Card size="small" bordered={false}>
        <Space direction="horizontal" style={{ width: '100%', justifyContent: 'space-between' }}>
          <div>
            <Tag color={getStatusColor()}>{getStatusLabel()}</Tag>
            <span style={{ marginLeft: 12, fontSize: 12, color: '#888' }}>
              Confidence: {(explanation.confidence_score * 100).toFixed(0)}%
            </span>
          </div>
          <div>
            {retryToken && (
              <Button
                icon={<ReloadOutlined />}
                onClick={handleRetry}
                loading={status === 'loading'}
              >
                Retry
              </Button>
            )}
            <Button
              icon={<ReloadOutlined />}
              onClick={generateExplanation}
              style={{ marginLeft: 8 }}
              loading={status === 'loading'}
            >
              Regenerate
            </Button>
          </div>
        </Space>
      </Card>

      {/* Error Alert */}
      {error && (
        <Alert
          message="Warning"
          description={error}
          type={status === 'error' ? 'error' : 'warning'}
          showIcon
          icon={<ExclamationCircleOutlined />}
        />
      )}

      {/* Main Explanation Card */}
      <Card title="Chain-of-Thought Analysis" bordered={false}>
        <Collapse items={sections} defaultActiveKey={['drivers']} />
      </Card>

      {/* Citations */}
      {explanation.citations.length > 0 && (
        <Card title={`Evidence Sources (${explanation.citations.length})`} bordered={false}>
          <List
            dataSource={explanation.citations}
            renderItem={(citation, index) => (
              <List.Item key={citation.doc_id}>
                <List.Item.Meta
                  avatar={
                    <Tag color="blue">
                      Doc {index + 1}
                    </Tag>
                  }
                  title={
                    <span>
                      <strong>{citation.title}</strong>
                      <Tag color="default" style={{ marginLeft: 8 }}>
                        {citation.source}
                      </Tag>
                    </span>
                  }
                  description={
                    <span style={{ fontSize: 13, color: '#666' }}>
                      "{citation.excerpt.substring(0, 100)}..."
                    </span>
                  }
                />
              </List.Item>
            )}
          />
        </Card>
      )}

      {/* Interactive Chat / Raw Analysis */}
      <ChatInterface
        sessionId={signal.id}
        conversationSummary={`Previous analysis for ${signal.instrument} ${signal.direction}\n${explanation.raw_text.substring(0, 300)}...`}
        title="Ask Follow-Up Questions"
        onStateChange={(state) => {
          if (state.tokenWarning) {
            console.warn('Token budget warning');
          }
        }}
      />

      {/* Metadata */}
      <div style={{ fontSize: 12, color: '#999', textAlign: 'right' }}>
        Generated: {new Date(explanation.generated_at).toLocaleString()}
      </div>
    </div>
  );
}
