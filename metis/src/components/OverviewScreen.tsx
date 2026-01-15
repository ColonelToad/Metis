import { Card, Statistic, Row, Col, Table, Tag, List } from 'antd';

// Mock data for Overview
const systemStatus = [
  { name: 'Data Feeds', status: 'Online', color: 'green', value: '12/12 Online' },
  { name: 'Signal Gen', status: 'Running', color: 'green', value: '8.2ns' },
  { name: 'RAG Engine', status: 'Ready', color: 'green', value: 'Llama-3.1' },
  { name: 'Risk Monitor', status: '80% Limit', color: 'gold', value: '80%' },
];
const quickStats = [
  { title: 'Daily P&L', value: 2400, prefix: '$', color: 'green' },
  { title: 'Sharpe', value: 1.42 },
  { title: 'Win Rate', value: '54.2%' },
  { title: 'Open Pos', value: '3/5' },
];
const activeSignals = [
  { time: '09:15 AM', instrument: 'NG_MAR26', signal: 'LONG', conf: 0.84, status: 'EXECUTED', pnl: '+$340' },
  { time: '08:42 AM', instrument: 'WTI_FEB26', signal: 'SHORT', conf: 0.71, status: 'EXECUTED', pnl: '-$120' },
  { time: '07:30 AM', instrument: 'TSLA', signal: 'LONG', conf: 0.68, status: 'REJECTED', pnl: 'N/A' },
];
const heatmap = [
  { symbol: 'NG', change: 2.3, color: 'green' },
  { symbol: 'WTI', change: -1.1, color: 'red' },
  { symbol: 'TSLA', change: 0.8, color: 'green' },
  { symbol: 'XLE', change: 1.5, color: 'green' },
];
const riskFactors = [
  { name: 'Grid Stress', value: 67, color: 'gold' },
  { name: 'Weather Risk', value: 'High', color: 'red' },
  { name: 'Policy Momentum', value: 42, color: 'gold' },
  { name: 'Storage Deficit', value: -18, color: 'green' },
];
const explanations = [
  {
    time: '09:15 AM',
    summary: 'ERCOT grid stress at 73/100 (high demand) combined with polar vortex forecast (70% prob next 7 days) suggests NG prices will spike. Storage 18% below 5yr avg supports...'
  }
];

export default function OverviewScreen() {
  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16}>
        <Col span={12}>
          <Card title="System Status" bordered={false}>
            <List
              dataSource={systemStatus}
              renderItem={item => (
                <List.Item>
                  <Tag color={item.color}>{item.status}</Tag>
                  <span style={{ minWidth: 120, display: 'inline-block' }}>{item.name}:</span>
                  <span>{item.value}</span>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Quick Stats" bordered={false}>
            <Row gutter={16}>
              {quickStats.map(stat => (
                <Col span={12} key={stat.title}>
                  <Statistic
                    title={stat.title}
                    value={stat.value}
                    prefix={stat.prefix}
                    valueStyle={{ color: stat.color === 'green' ? '#00ff88' : undefined }}
                  />
                </Col>
              ))}
            </Row>
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="Active Signals (Last 24h)" bordered={false}>
            <Table
              size="small"
              dataSource={activeSignals}
              rowKey={r => r.time + r.instrument}
              pagination={false}
              columns={[
                { title: 'Time', dataIndex: 'time' },
                { title: 'Instrument', dataIndex: 'instrument' },
                { title: 'Signal', dataIndex: 'signal', render: v => <Tag color={v === 'LONG' ? 'green' : 'red'}>{v}</Tag> },
                { title: 'Conf', dataIndex: 'conf', render: v => (v * 100).toFixed(0) + '%' },
                { title: 'Status', dataIndex: 'status' },
                { title: 'P&L', dataIndex: 'pnl' },
              ]}
            />
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title="Market Heatmap" bordered={false}>
            <List
              dataSource={heatmap}
              renderItem={item => (
                <List.Item>
                  <Tag color={item.color}>{item.symbol}</Tag>
                  <span style={{ color: item.color === 'green' ? '#00ff88' : '#ff6b6b' }}>{item.change > 0 ? '+' : ''}{item.change}%</span>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Risk Factors" bordered={false}>
            <List
              dataSource={riskFactors}
              renderItem={item => (
                <List.Item>
                  <span style={{ minWidth: 120, display: 'inline-block' }}>{item.name}:</span>
                  <Tag color={item.color}>{item.value}</Tag>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="Recent Explanations (RAG)" bordered={false}>
            <List
              dataSource={explanations}
              renderItem={item => (
                <List.Item>
                  <span style={{ fontWeight: 600 }}>{item.time} NG Long Signal:</span>
                  <span style={{ marginLeft: 8 }}>{item.summary}</span>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
