import { Card, Statistic, Row, Col, Table, Tag, List, Button } from 'antd';

// Mock data for Signals
const activeSignal = {
  direction: 'LONG',
  instrument: 'NG_MAR26',
  confidence: 0.84,
  generated: '2026-01-14 09:15:32',
  entry: 3.45,
  target: 3.72,
  stop: 3.28,
  rr: '2.3:1',
  reasoning: [
    'Grid Stress: ERCOT at 73/100 (high demand) → Natural gas generation dispatch increasing',
    'Weather: Polar vortex 70% probability (7-day) → Heating demand spike expected',
    'Storage: 18% below 5-year average (bullish) → Supply deficit supports higher prices',
    'Technical: Futures curve in backwardation → Market pricing near-term shortage',
  ],
};
const signalHistory = [
  { time: '09:15 AM', instrument: 'NG_MAR26', dir: 'LONG', conf: 0.84, status: 'ACTIVE', pnl: 'N/A', reason: 'Grid+Wx' },
  { time: '08:42 AM', instrument: 'WTI_FEB26', dir: 'SHORT', conf: 0.71, status: 'EXECUTED', pnl: '-$120', reason: 'Storage' },
  { time: '07:30 AM', instrument: 'TSLA', dir: 'LONG', conf: 0.68, status: 'REJECTED', pnl: 'N/A', reason: 'Risk Lim' },
  { time: '06:15 AM', instrument: 'XLE', dir: 'LONG', conf: 0.62, status: 'CLOSED', pnl: '+$280', reason: 'Policy' },
];
const perfStats = [
  { label: 'Win Rate', value: '54.2%' },
  { label: 'Avg Win', value: '$340' },
  { label: 'Avg Loss', value: '$180' },
  { label: 'Sharpe', value: '1.42' },
  { label: 'Max DD', value: '-$1,240' },
];

export default function SignalsScreen() {
  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16}>
        <Col span={12}>
          <Card title="Active Signal" bordered={false}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <Tag color={activeSignal.direction === 'LONG' ? 'green' : 'red'} style={{ fontSize: 16 }}>{activeSignal.direction}</Tag>
                <span style={{ fontWeight: 600, fontSize: 18, marginLeft: 8 }}>{activeSignal.instrument}</span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span style={{ fontSize: 22, fontWeight: 700, color: '#00ff88' }}>{(activeSignal.confidence * 100).toFixed(0)}%</span>
                <div style={{ fontSize: 12, color: '#aaa' }}>Confidence</div>
              </div>
            </div>
            <div style={{ marginTop: 12, fontSize: 14 }}>
              Generated: {activeSignal.generated}<br />
              Entry: ${activeSignal.entry}  Target: ${activeSignal.target}  Stop: ${activeSignal.stop}  R/R: {activeSignal.rr}
            </div>
            <Card type="inner" title="Reasoning" style={{ marginTop: 16 }}>
              <List
                size="small"
                dataSource={activeSignal.reasoning}
                renderItem={(item, idx) => (
                  <List.Item>
                    <span style={{ fontWeight: 600 }}>{idx + 1}.</span> {item}
                  </List.Item>
                )}
              />
            </Card>
            <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
              <Button type="default" aria-label="View supporting data for this signal">📊 View Supporting Data</Button>
              <Button type="primary" aria-label="View full RAG-powered explanation">🤖 Full Explanation</Button>
              <Button type="dashed" aria-label="Execute signal and create position">✓ Execute</Button>
            </div>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Signal Performance (Last 30 Days)" bordered={false}>
            <Row gutter={8}>
              {perfStats.map(stat => (
                <Col span={12} key={stat.label}>
                  <Statistic title={stat.label} value={stat.value} />
                </Col>
              ))}
            </Row>
            <div style={{ marginTop: 16, color: '#aaa', fontSize: 13 }}>
              [Chart: Cumulative P&L] (mock)
            </div>
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="Signal History" bordered={false}>
            <Table
              size="small"
              dataSource={signalHistory}
              rowKey={r => r.time + r.instrument}
              pagination={false}
              columns={[
                { title: 'Time', dataIndex: 'time' },
                { title: 'Instrument', dataIndex: 'instrument' },
                { title: 'Dir', dataIndex: 'dir', render: v => <Tag color={v === 'LONG' ? 'green' : 'red'}>{v}</Tag> },
                { title: 'Conf', dataIndex: 'conf', render: v => (v * 100).toFixed(0) + '%' },
                { title: 'Status', dataIndex: 'status' },
                { title: 'P&L', dataIndex: 'pnl' },
                { title: 'Reasoning', dataIndex: 'reason' },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
