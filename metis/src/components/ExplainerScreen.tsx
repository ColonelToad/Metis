import SignalExplainer from './SignalExplainer';
import { useSignal } from '../contexts/SignalContext';
import { Empty, Card } from 'antd';
import { TradingSignal } from '../contexts/SignalContext';

export default function ExplainerScreen() {
  const { activeSignal } = useSignal();

  // Example signal for demonstration if none is selected
  const exampleSignal: TradingSignal = activeSignal || {
    id: 'ng_mar26_001',
    signal_id: 'ng_mar26_001',
    symbol: 'NG_MAR26',
    instrument: 'NG_MAR26',
    direction: 'LONG',
    confidence: 0.82,
    timestamp: new Date().toISOString(),
    target_quantity: 100,
    horizon_minutes: 30,
    context: {
      current_price: 3.45,
      grid_stress_index: 73,
      temperature_anomaly: -22,
      recent_policy_events: ['H.R. 1234 (Clean Energy Tax Credits) advancing through Congress'],
      primary_region: 'ERCOT',
    },
  };

  return (
    <div style={{ padding: 24 }}>
      {!activeSignal && (
        <Card style={{ marginBottom: 24 }}>
          <Empty 
            description="No signal selected"
            style={{ padding: '20px' }}
          >
            <p style={{ color: '#999', marginTop: 12 }}>
              Click "🤖 Full Explanation" on the Signals tab to generate an explanation for a trading signal.
              <br />
              Or scroll down to see an example explanation using demo data.
            </p>
          </Empty>
        </Card>
      )}
      <SignalExplainer signal={exampleSignal} />
    </div>
  );
}
