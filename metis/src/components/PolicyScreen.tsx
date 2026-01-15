import { Card, Row, Col, Table, Tag, Progress, Timeline } from 'antd';

// Mock data for Policy
const billTracking = [
  { bill: 'HR-4521', title: 'Clean Energy Tax Credits Extension', status: 'Committee', momentum: 72, sponsor: 'Rep. Smith (D-CA)' },
  { bill: 'S-2847', title: 'Grid Modernization Act', status: 'Floor Vote', momentum: 85, sponsor: 'Sen. Johnson (R-WI)' },
  { bill: 'HR-3309', title: 'Renewable Portfolio Standards', status: 'Introduced', momentum: 48, sponsor: 'Rep. Garcia (D-TX)' },
  { bill: 'S-1923', title: 'Carbon Border Adjustment', status: 'Died in Committee', momentum: 12, sponsor: 'Sen. Warren (D-MA)' },
];

const policyLifecycle = [
  { stage: 'Introduced', count: 12, color: '#1890ff' },
  { stage: 'Committee', count: 8, color: '#52c41a' },
  { stage: 'Floor Vote', count: 3, color: '#faad14' },
  { stage: 'Passed', count: 2, color: '#722ed1' },
  { stage: 'Enacted', count: 1, color: '#13c2c2' },
];

const regimeProbabilities = [
  { regime: 'Pro-Fossil (Status Quo)', probability: 35, trend: 'stable' },
  { regime: 'Aggressive Decarbonization', probability: 28, trend: 'up' },
  { regime: 'Market-Driven Transition', probability: 25, trend: 'up' },
  { regime: 'Nuclear Renaissance', probability: 12, trend: 'down' },
];

export default function PolicyScreen() {
  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16}>
        <Col span={24}>
          <Card title="Bill Tracking" bordered={false}>
            <Table
              size="small"
              dataSource={billTracking}
              rowKey="bill"
              pagination={false}
              columns={[
                { title: 'Bill #', dataIndex: 'bill', render: v => <strong>{v}</strong> },
                { title: 'Title', dataIndex: 'title' },
                { 
                  title: 'Status', 
                  dataIndex: 'status',
                  render: v => {
                    let color = 'default';
                    if (v === 'Floor Vote') color = 'gold';
                    else if (v === 'Committee') color = 'blue';
                    else if (v === 'Died in Committee') color = 'red';
                    return <Tag color={color}>{v}</Tag>;
                  }
                },
                { 
                  title: 'Momentum Score', 
                  dataIndex: 'momentum',
                  render: v => (
                    <Progress 
                      percent={v} 
                      size="small" 
                      strokeColor={v > 70 ? '#52c41a' : v > 40 ? '#faad14' : '#ff4d4f'}
                    />
                  )
                },
                { title: 'Sponsor', dataIndex: 'sponsor' },
              ]}
            />
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title="Policy Lifecycle Tracker" bordered={false}>
            {policyLifecycle.map(item => (
              <div key={item.stage} style={{ marginBottom: 20 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <span style={{ fontWeight: 600 }}>{item.stage}</span>
                  <span>{item.count} bills</span>
                </div>
                <Progress 
                  percent={(item.count / 26) * 100} 
                  strokeColor={item.color}
                  showInfo={false}
                />
              </div>
            ))}
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Policy Regime Probabilities" bordered={false}>
            <Table
              size="small"
              dataSource={regimeProbabilities}
              rowKey="regime"
              pagination={false}
              columns={[
                { title: 'Regime', dataIndex: 'regime', render: v => <strong>{v}</strong> },
                { 
                  title: 'Probability', 
                  dataIndex: 'probability',
                  render: v => (
                    <Progress 
                      percent={v} 
                      size="small" 
                      format={percent => `${percent}%`}
                    />
                  )
                },
                { 
                  title: 'Trend', 
                  dataIndex: 'trend',
                  render: v => {
                    const color = v === 'up' ? 'green' : v === 'down' ? 'red' : 'default';
                    return <Tag color={color}>{v === 'up' ? '↑' : v === 'down' ? '↓' : '→'}</Tag>;
                  }
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="Recent Policy Events" bordered={false}>
            <Timeline
              items={[
                {
                  color: 'green',
                  children: (
                    <>
                      <p style={{ margin: 0, fontWeight: 600 }}>2025-01-15: Grid Modernization Act passes Senate committee</p>
                      <p style={{ margin: 0, color: '#8c8c8c', fontSize: 12 }}>Bipartisan support; floor vote expected Feb 2025</p>
                    </>
                  ),
                },
                {
                  color: 'blue',
                  children: (
                    <>
                      <p style={{ margin: 0, fontWeight: 600 }}>2025-01-10: IRA tax credit clarification issued by Treasury</p>
                      <p style={{ margin: 0, color: '#8c8c8c', fontSize: 12 }}>45V hydrogen credit guidance now finalized</p>
                    </>
                  ),
                },
                {
                  color: 'red',
                  children: (
                    <>
                      <p style={{ margin: 0, fontWeight: 600 }}>2025-01-05: Carbon border adjustment stalls in committee</p>
                      <p style={{ margin: 0, color: '#8c8c8c', fontSize: 12 }}>Opposition from manufacturing lobby</p>
                    </>
                  ),
                },
                {
                  color: 'blue',
                  children: (
                    <>
                      <p style={{ margin: 0, fontWeight: 600 }}>2024-12-20: FERC Order 2222 implementation deadline extended</p>
                      <p style={{ margin: 0, color: '#8c8c8c', fontSize: 12 }}>New deadline: June 2025</p>
                    </>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
