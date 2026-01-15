import { Card, Row, Col, Table, Tag } from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons';

// Mock data for Markets
const watchlist = [
  { symbol: 'NG_MAR26', name: 'Natural Gas Mar 26', price: 3.48, change: '+2.1%', volume: '1.2M', trend: 'up' },
  { symbol: 'WTI_FEB26', name: 'WTI Crude Feb 26', price: 71.95, change: '-0.2%', volume: '3.4M', trend: 'down' },
  { symbol: 'TSLA', name: 'Tesla Inc', price: 387.00, change: '+0.5%', volume: '89M', trend: 'up' },
  { symbol: 'SPY', name: 'SPDR S&P 500 ETF', price: 475.30, change: '+0.3%', volume: '45M', trend: 'up' },
];

const correlationMatrix = [
  { asset: 'NG', ng: 1.0, wti: 0.65, tsla: -0.12, spy: 0.08 },
  { asset: 'WTI', ng: 0.65, wti: 1.0, tsla: -0.05, spy: 0.15 },
  { asset: 'TSLA', ng: -0.12, wti: -0.05, tsla: 1.0, spy: 0.72 },
  { asset: 'SPY', ng: 0.08, wti: 0.15, tsla: 0.72, spy: 1.0 },
];

const orderBook = [
  { side: 'bid', price: 3.475, size: 1200, orders: 5 },
  { side: 'bid', price: 3.474, size: 850, orders: 3 },
  { side: 'bid', price: 3.473, size: 2100, orders: 7 },
  { side: 'ask', price: 3.481, size: 900, orders: 4 },
  { side: 'ask', price: 3.482, size: 1500, orders: 6 },
  { side: 'ask', price: 3.483, size: 700, orders: 2 },
];

export default function MarketsScreen() {
  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16}>
        <Col span={12}>
          <Card title="Watchlist" bordered={false}>
            <Table
              size="small"
              dataSource={watchlist}
              rowKey="symbol"
              pagination={false}
              columns={[
                { title: 'Symbol', dataIndex: 'symbol', render: v => <strong>{v}</strong> },
                { title: 'Name', dataIndex: 'name' },
                { 
                  title: 'Price', 
                  dataIndex: 'price',
                  render: (v, record) => (
                    <span>
                      ${v.toFixed(2)}
                      {record.trend === 'up' ? <ArrowUpOutlined style={{ color: '#52c41a', marginLeft: 4 }} /> : <ArrowDownOutlined style={{ color: '#ff4d4f', marginLeft: 4 }} />}
                    </span>
                  )
                },
                { 
                  title: 'Change', 
                  dataIndex: 'change',
                  render: v => <span style={{ color: v.startsWith('+') ? '#52c41a' : '#ff4d4f' }}>{v}</span>
                },
                { title: 'Volume', dataIndex: 'volume' },
              ]}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Order Book (NG_MAR26)" bordered={false}>
            <Table
              size="small"
              dataSource={orderBook}
              rowKey={(r, i) => `${r.side}-${i}`}
              pagination={false}
              columns={[
                { 
                  title: 'Side', 
                  dataIndex: 'side',
                  render: v => <Tag color={v === 'bid' ? 'green' : 'red'}>{v.toUpperCase()}</Tag>
                },
                { title: 'Price', dataIndex: 'price', render: v => `$${v.toFixed(3)}` },
                { title: 'Size', dataIndex: 'size' },
                { title: 'Orders', dataIndex: 'orders' },
              ]}
            />
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title="Price Chart (Placeholder)" bordered={false}>
            <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0a0a0a', borderRadius: 4 }}>
              <div style={{ textAlign: 'center', color: '#666' }}>
                <div style={{ fontSize: 48, marginBottom: 8 }}>📈</div>
                <div>TradingView Lightweight Charts integration</div>
                <div style={{ fontSize: 12, marginTop: 4 }}>Coming soon</div>
              </div>
            </div>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Correlation Matrix" bordered={false}>
            <Table
              size="small"
              dataSource={correlationMatrix}
              rowKey="asset"
              pagination={false}
              columns={[
                { title: 'Asset', dataIndex: 'asset', render: v => <strong>{v}</strong> },
                { 
                  title: 'NG', 
                  dataIndex: 'ng',
                  render: v => (
                    <span style={{ 
                      color: v > 0.5 ? '#52c41a' : v < -0.5 ? '#ff4d4f' : '#d9d9d9',
                      fontWeight: v === 1.0 ? 'bold' : 'normal'
                    }}>
                      {v.toFixed(2)}
                    </span>
                  )
                },
                { 
                  title: 'WTI', 
                  dataIndex: 'wti',
                  render: v => (
                    <span style={{ 
                      color: v > 0.5 ? '#52c41a' : v < -0.5 ? '#ff4d4f' : '#d9d9d9',
                      fontWeight: v === 1.0 ? 'bold' : 'normal'
                    }}>
                      {v.toFixed(2)}
                    </span>
                  )
                },
                { 
                  title: 'TSLA', 
                  dataIndex: 'tsla',
                  render: v => (
                    <span style={{ 
                      color: v > 0.5 ? '#52c41a' : v < -0.5 ? '#ff4d4f' : '#d9d9d9',
                      fontWeight: v === 1.0 ? 'bold' : 'normal'
                    }}>
                      {v.toFixed(2)}
                    </span>
                  )
                },
                { 
                  title: 'SPY', 
                  dataIndex: 'spy',
                  render: v => (
                    <span style={{ 
                      color: v > 0.5 ? '#52c41a' : v < -0.5 ? '#ff4d4f' : '#d9d9d9',
                      fontWeight: v === 1.0 ? 'bold' : 'normal'
                    }}>
                      {v.toFixed(2)}
                    </span>
                  )
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
