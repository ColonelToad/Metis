import { Card, Row, Col, Form, Select, DatePicker, InputNumber, Button, Statistic, Table, Divider } from 'antd';

const { RangePicker } = DatePicker;

// Mock backtest results
const backtestResults = {
  totalReturn: '+42.3%',
  sharpeRatio: 1.68,
  maxDrawdown: '-12.4%',
  winRate: '58.2%',
  trades: 143,
  avgWin: '+$1,240',
  avgLoss: '-$680',
};

const tradeHistory = [
  { date: '2025-01-10', symbol: 'NG_MAR26', side: 'LONG', entry: 3.42, exit: 3.48, pnl: '+$600', duration: '2d' },
  { date: '2025-01-08', symbol: 'WTI_FEB26', side: 'SHORT', entry: 72.50, exit: 71.95, pnl: '+$550', duration: '1d' },
  { date: '2025-01-05', symbol: 'TSLA', side: 'LONG', entry: 390, exit: 385, pnl: '-$500', duration: '3d' },
  { date: '2025-01-03', symbol: 'NG_FEB26', side: 'LONG', entry: 3.35, exit: 3.40, pnl: '+$500', duration: '1d' },
];

const factorAttribution = [
  { factor: 'Temperature Anomaly', contribution: '+18.2%' },
  { factor: 'Policy Momentum', contribution: '+12.5%' },
  { factor: 'Grid Congestion', contribution: '+8.7%' },
  { factor: 'Sentiment (News)', contribution: '+3.9%' },
  { factor: 'Unexplained Alpha', contribution: '-1.0%' },
];

export default function BacktestScreen() {
  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16}>
        <Col span={24}>
          <Card title="Backtest Configuration" bordered={false}>
            <Form layout="inline">
              <Form.Item label="Strategy">
                <Select defaultValue="metis-v1" style={{ width: 180 }}>
                  <Select.Option value="metis-v1">Metis v1.0</Select.Option>
                  <Select.Option value="baseline">Baseline MA</Select.Option>
                  <Select.Option value="sentiment">Sentiment Only</Select.Option>
                </Select>
              </Form.Item>
              <Form.Item label="Date Range">
                <RangePicker />
              </Form.Item>
              <Form.Item label="Initial Capital">
                <InputNumber defaultValue={100000} prefix="$" style={{ width: 140 }} />
              </Form.Item>
              <Form.Item label="Slippage (bps)">
                <InputNumber defaultValue={0.5} step={0.1} style={{ width: 100 }} />
              </Form.Item>
              <Form.Item>
                <Button type="primary" aria-label="Run backtest with current configuration">Run Backtest</Button>
              </Form.Item>
            </Form>
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={6}>
          <Card bordered={false}>
            <Statistic title="Total Return" value={backtestResults.totalReturn} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false}>
            <Statistic title="Sharpe Ratio" value={backtestResults.sharpeRatio} precision={2} />
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false}>
            <Statistic title="Max Drawdown" value={backtestResults.maxDrawdown} valueStyle={{ color: '#ff4d4f' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false}>
            <Statistic title="Win Rate" value={backtestResults.winRate} />
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={16}>
          <Card title="Equity Curve" bordered={false}>
            <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0a0a0a', borderRadius: 4 }}>
              <div style={{ textAlign: 'center', color: '#666' }}>
                <div style={{ fontSize: 48, marginBottom: 8 }}>📈</div>
                <div>Equity curve chart with drawdown overlay</div>
                <div style={{ fontSize: 12, marginTop: 4 }}>Coming soon</div>
              </div>
            </div>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="Factor Attribution" bordered={false}>
            <Table
              size="small"
              dataSource={factorAttribution}
              rowKey="factor"
              pagination={false}
              showHeader={false}
              columns={[
                { dataIndex: 'factor', render: v => <strong>{v}</strong> },
                { 
                  dataIndex: 'contribution',
                  align: 'right',
                  render: v => (
                    <span style={{ 
                      color: v.startsWith('+') ? '#52c41a' : '#ff4d4f',
                      fontWeight: 600
                    }}>
                      {v}
                    </span>
                  )
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="Trade History" bordered={false}>
            <Table
              size="small"
              dataSource={tradeHistory}
              rowKey={(r, i) => `${r.date}-${i}`}
              pagination={false}
              columns={[
                { title: 'Date', dataIndex: 'date' },
                { title: 'Symbol', dataIndex: 'symbol', render: v => <strong>{v}</strong> },
                { title: 'Side', dataIndex: 'side' },
                { title: 'Entry', dataIndex: 'entry', render: v => `$${v}` },
                { title: 'Exit', dataIndex: 'exit', render: v => `$${v}` },
                { 
                  title: 'P&L', 
                  dataIndex: 'pnl',
                  render: v => <span style={{ color: v.startsWith('+') ? '#52c41a' : '#ff4d4f' }}>{v}</span>
                },
                { title: 'Duration', dataIndex: 'duration' },
              ]}
            />
            <Divider />
            <div style={{ display: 'flex', gap: 32 }}>
              <Statistic title="Total Trades" value={backtestResults.trades} />
              <Statistic title="Avg Win" value={backtestResults.avgWin} valueStyle={{ color: '#52c41a' }} />
              <Statistic title="Avg Loss" value={backtestResults.avgLoss} valueStyle={{ color: '#ff4d4f' }} />
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
