import { Card, Statistic, Row, Col, Table, Tag, List, Progress, Button } from 'antd';

// Mock data for Portfolio
const portfolioSummary = [
  { label: 'NAV', value: '$125,340 (+2.1% today)' },
  { label: 'Daily P&L', value: '+$2,580' },
  { label: 'Positions', value: '3/5 used' },
  { label: 'Buying Power', value: '$45K' },
  { label: 'Margin', value: '0%' },
];
const openPositions = [
  { instrument: 'NG_MAR26', dir: 'LONG', qty: 100, entry: 3.45, current: 3.48, pnl: '+$300', risk: 'Med' },
  { instrument: 'WTI_FEB26', dir: 'SHORT', qty: 50, entry: 72.10, current: 71.95, pnl: '+$750', risk: 'Low' },
  { instrument: 'TSLA', dir: 'LONG', qty: 10, entry: 385, current: 387, pnl: '+$200', risk: 'High' },
];
const riskMetrics = [
  { label: 'VaR (99%, 1-day)', value: '-$1,240' },
  { label: 'Sharpe Ratio', value: '1.42' },
  { label: 'Max Drawdown', value: '-$2,100' },
  { label: 'Win Rate', value: '54.2%' },
  { label: 'Avg Win/Loss', value: '1.9:1' },
];
const positionRisk = [
  { instrument: 'NG_MAR26', percent: 30, risk: 'High' },
  { instrument: 'WTI_FEB26', percent: 20, risk: 'Medium' },
  { instrument: 'TSLA', percent: 10, risk: 'Low' },
];

export default function PortfolioScreen() {
  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16}>
        <Col span={24}>
          <Card title="Portfolio Summary" bordered={false}>
            <Row gutter={16}>
              {portfolioSummary.map(stat => (
                <Col span={8} key={stat.label}>
                  <Statistic title={stat.label} value={stat.value} />
                </Col>
              ))}
            </Row>
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="Open Positions" bordered={false}>
            <Table
              size="small"
              dataSource={openPositions}
              rowKey={r => r.instrument}
              pagination={false}
              columns={[
                { title: 'Instrument', dataIndex: 'instrument' },
                { title: 'Dir', dataIndex: 'dir', render: v => <Tag color={v === 'LONG' ? 'green' : 'red'}>{v}</Tag> },
                { title: 'Qty', dataIndex: 'qty' },
                { title: 'Entry', dataIndex: 'entry' },
                { title: 'Current', dataIndex: 'current' },
                { title: 'P&L', dataIndex: 'pnl' },
                { title: 'Risk', dataIndex: 'risk', render: v => <Tag color={v === 'High' ? 'red' : v === 'Medium' ? 'gold' : 'green'}>{v}</Tag> },
                { title: 'Action', render: (_, record) => <Button size="small" danger aria-label={`Close position ${record.instrument}`}>Close</Button> },
              ]}
            />
            <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
              <Button type="primary" aria-label="Add new position">Add Position</Button>
              <Button aria-label="Rebalance portfolio">Rebalance</Button>
              <Button danger aria-label="Emergency flatten all positions">Flatten All (Emergency)</Button>
            </div>
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title="Risk Metrics" bordered={false}>
            <List
              dataSource={riskMetrics}
              renderItem={item => (
                <List.Item>
                  <span style={{ minWidth: 120, display: 'inline-block' }}>{item.label}:</span>
                  <span>{item.value}</span>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Position Risk Breakdown" bordered={false}>
            <List
              dataSource={positionRisk}
              renderItem={item => (
                <List.Item>
                  <span style={{ minWidth: 100, display: 'inline-block' }}>{item.instrument}:</span>
                  <Progress percent={item.percent} status={item.risk === 'High' ? 'exception' : item.risk === 'Medium' ? 'active' : 'normal'} showInfo />
                  <Tag color={item.risk === 'High' ? 'red' : item.risk === 'Medium' ? 'gold' : 'green'}>{item.risk}</Tag>
                </List.Item>
              )}
            />
            <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
              <Button>Stress Test</Button>
              <Button>Greeks Analysis</Button>
              <Button>Scenario P&L →</Button>
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
