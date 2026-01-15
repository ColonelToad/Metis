import { Card, Row, Col, Progress, Statistic, Table, Tag } from 'antd';

// Mock data for Grid Status
const loadReserves = [
  { label: 'Current Load', value: 42500, max: 55000, unit: 'MW' },
  { label: 'Operating Reserves', value: 3200, max: 4500, unit: 'MW' },
  { label: 'Spinning Reserves', value: 1800, max: 2500, unit: 'MW' },
];

const generationMix = [
  { source: 'Natural Gas', percent: 42, color: '#1890ff' },
  { source: 'Wind', percent: 28, color: '#52c41a' },
  { source: 'Solar', percent: 12, color: '#faad14' },
  { source: 'Coal', percent: 10, color: '#8c8c8c' },
  { source: 'Nuclear', percent: 8, color: '#722ed1' },
];

const lmpData = [
  { zone: 'North Hub', lmp: 32.50, status: 'Normal', congestion: 'None' },
  { zone: 'South Hub', lmp: 45.20, status: 'Elevated', congestion: 'Moderate' },
  { zone: 'West Zone', lmp: 38.10, status: 'Normal', congestion: 'None' },
  { zone: 'East Zone', lmp: 52.80, status: 'High', congestion: 'Severe' },
];

const curtailmentTracking = [
  { date: '2025-01-15', wind: 450, solar: 120, reason: 'Oversupply' },
  { date: '2025-01-14', wind: 320, solar: 90, reason: 'Transmission' },
  { date: '2025-01-13', wind: 180, solar: 50, reason: 'Oversupply' },
];

export default function GridStatusScreen() {
  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16}>
        <Col span={12}>
          <Card title="Load & Reserves" bordered={false}>
            {loadReserves.map(item => (
              <div key={item.label} style={{ marginBottom: 24 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <span style={{ fontWeight: 600 }}>{item.label}</span>
                  <span>{item.value} / {item.max} {item.unit}</span>
                </div>
                <Progress 
                  percent={Math.round((item.value / item.max) * 100)} 
                  status={item.value / item.max > 0.85 ? 'exception' : 'active'}
                  strokeColor={item.value / item.max > 0.85 ? '#ff4d4f' : '#52c41a'}
                />
              </div>
            ))}
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Generation Mix" bordered={false}>
            {generationMix.map(item => (
              <div key={item.source} style={{ marginBottom: 20 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <span style={{ fontWeight: 600 }}>{item.source}</span>
                  <span>{item.percent}%</span>
                </div>
                <Progress 
                  percent={item.percent} 
                  strokeColor={item.color}
                  showInfo={false}
                />
              </div>
            ))}
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title="LMP Heatmap" bordered={false}>
            <Table
              size="small"
              dataSource={lmpData}
              rowKey="zone"
              pagination={false}
              columns={[
                { title: 'Zone', dataIndex: 'zone', render: v => <strong>{v}</strong> },
                { 
                  title: 'LMP ($/MWh)', 
                  dataIndex: 'lmp',
                  render: v => `$${v.toFixed(2)}`
                },
                { 
                  title: 'Status', 
                  dataIndex: 'status',
                  render: v => {
                    const color = v === 'Normal' ? 'green' : v === 'Elevated' ? 'gold' : 'red';
                    return <Tag color={color}>{v}</Tag>;
                  }
                },
                { 
                  title: 'Congestion', 
                  dataIndex: 'congestion',
                  render: v => {
                    const color = v === 'None' ? 'default' : v === 'Moderate' ? 'gold' : 'red';
                    return <Tag color={color}>{v}</Tag>;
                  }
                },
              ]}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Curtailment Tracking" bordered={false}>
            <Table
              size="small"
              dataSource={curtailmentTracking}
              rowKey="date"
              pagination={false}
              columns={[
                { title: 'Date', dataIndex: 'date' },
                { title: 'Wind (MW)', dataIndex: 'wind' },
                { title: 'Solar (MW)', dataIndex: 'solar' },
                { title: 'Reason', dataIndex: 'reason' },
              ]}
            />
            <div style={{ marginTop: 16, padding: 12, background: '#0a0a0a', borderRadius: 4 }}>
              <Statistic
                title="Total Curtailment (Last 7 Days)"
                value={3420}
                suffix="MW"
                valueStyle={{ color: '#faad14' }}
              />
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
