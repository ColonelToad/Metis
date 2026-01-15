import { Card, Row, Col, Alert, Table, Tag, Progress } from 'antd';
import { WarningOutlined } from '@ant-design/icons';

// Mock data for Climate
const weatherAlerts = [
  { type: 'Heat Wave', region: 'Texas ERCOT', severity: 'High', impact: 'Demand spike expected', expires: '2025-01-20' },
  { type: 'Cold Front', region: 'MISO North', severity: 'Medium', impact: 'Wind gen may increase', expires: '2025-01-18' },
  { type: 'Hurricane', region: 'Gulf Coast', severity: 'Low', impact: 'Offshore platforms offline', expires: '2025-01-22' },
];

const temperatureAnomalies = [
  { region: 'Southwest', anomaly: '+8°F', deviation: 'Extreme' },
  { region: 'Midwest', anomaly: '+2°F', deviation: 'Moderate' },
  { region: 'Northeast', anomaly: '-1°F', deviation: 'Normal' },
  { region: 'Southeast', anomaly: '+5°F', deviation: 'High' },
];

const probabilisticForecasts = [
  { variable: 'HDD (Heating Degree Days)', p10: 520, p50: 580, p90: 640, current: 575 },
  { variable: 'CDD (Cooling Degree Days)', p10: 10, p50: 25, p90: 40, current: 22 },
  { variable: 'Wind Capacity Factor', p10: 28, p50: 35, p90: 42, current: 36 },
  { variable: 'Solar Capacity Factor', p10: 12, p50: 18, p90: 24, current: 19 },
];

const disasterTracker = [
  { event: 'California Wildfire', date: '2025-01-10', status: 'Active', impact: 'Transmission disruption' },
  { event: 'Texas Freeze', date: '2025-01-05', status: 'Resolved', impact: 'Gas supply shock' },
  { event: 'Hurricane Patricia', date: '2024-12-28', status: 'Resolved', impact: 'Offshore production offline' },
];

export default function ClimateScreen() {
  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16}>
        <Col span={24}>
          <Card title={<span><WarningOutlined style={{ color: '#faad14', marginRight: 8 }} />Active Weather Alerts</span>} bordered={false}>
            {weatherAlerts.map((alert, idx) => (
              <Alert
                key={idx}
                message={`${alert.type} - ${alert.region}`}
                description={`${alert.impact} | Expires: ${alert.expires}`}
                type={alert.severity === 'High' ? 'error' : alert.severity === 'Medium' ? 'warning' : 'info'}
                showIcon
                style={{ marginBottom: 12 }}
              />
            ))}
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card title="Temperature Anomaly Map" bordered={false}>
            <Table
              size="small"
              dataSource={temperatureAnomalies}
              rowKey="region"
              pagination={false}
              columns={[
                { title: 'Region', dataIndex: 'region', render: v => <strong>{v}</strong> },
                { 
                  title: 'Anomaly', 
                  dataIndex: 'anomaly',
                  render: v => (
                    <span style={{ 
                      color: v.startsWith('+') ? '#ff4d4f' : v.startsWith('-') ? '#1890ff' : '#d9d9d9',
                      fontWeight: 600
                    }}>
                      {v}
                    </span>
                  )
                },
                { 
                  title: 'Deviation', 
                  dataIndex: 'deviation',
                  render: v => {
                    const color = v === 'Extreme' ? 'red' : v === 'High' ? 'orange' : v === 'Moderate' ? 'gold' : 'green';
                    return <Tag color={color}>{v}</Tag>;
                  }
                },
              ]}
            />
            <div style={{ marginTop: 16, height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0a0a0a', borderRadius: 4 }}>
              <div style={{ textAlign: 'center', color: '#666' }}>
                <div style={{ fontSize: 48, marginBottom: 8 }}>🗺️</div>
                <div>Interactive Heatmap</div>
                <div style={{ fontSize: 12, marginTop: 4 }}>Coming soon</div>
              </div>
            </div>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Probabilistic Forecasts (7-Day)" bordered={false}>
            <Table
              size="small"
              dataSource={probabilisticForecasts}
              rowKey="variable"
              pagination={false}
              columns={[
                { title: 'Variable', dataIndex: 'variable' },
                { title: 'P10', dataIndex: 'p10' },
                { title: 'P50', dataIndex: 'p50', render: v => <strong>{v}</strong> },
                { title: 'P90', dataIndex: 'p90' },
                { 
                  title: 'Current', 
                  dataIndex: 'current',
                  render: (v, record) => {
                    const pct = ((v - record.p10) / (record.p90 - record.p10)) * 100;
                    return <Progress percent={Math.round(pct)} size="small" strokeColor="#52c41a" />;
                  }
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="Disaster Tracker" bordered={false}>
            <Table
              size="small"
              dataSource={disasterTracker}
              rowKey="event"
              pagination={false}
              columns={[
                { title: 'Event', dataIndex: 'event', render: v => <strong>{v}</strong> },
                { title: 'Date', dataIndex: 'date' },
                { 
                  title: 'Status', 
                  dataIndex: 'status',
                  render: v => <Tag color={v === 'Active' ? 'red' : 'green'}>{v}</Tag>
                },
                { title: 'Impact', dataIndex: 'impact' },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
