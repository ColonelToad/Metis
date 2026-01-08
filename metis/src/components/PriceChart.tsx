import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

interface MarketData {
  timestamp: string;
  price: number;
  spread: number;
  volume: number;
}

interface Props {
  data: MarketData[];
}

export default function PriceChart({ data }: Props) {
  const chartData = data.map(d => ({
    time: new Date(d.timestamp).toLocaleTimeString(),
    price: d.price.toFixed(3),
    spread: (d.spread * 100).toFixed(2)
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="#333" />
        <XAxis 
          dataKey="time" 
          stroke="#888"
          tick={{ fontSize: 12 }}
          interval="preserveStartEnd"
        />
        <YAxis 
          stroke="#888"
          tick={{ fontSize: 12 }}
          domain={['auto', 'auto']}
        />
        <Tooltip 
          contentStyle={{ 
            backgroundColor: '#1a1a1a', 
            border: '1px solid #333',
            borderRadius: '4px'
          }}
        />
        <Legend />
        <Line 
          type="monotone" 
          dataKey="price" 
          stroke="#00ff88" 
          strokeWidth={2}
          dot={false}
          name="Price ($/MMBtu)"
        />
        <Line 
          type="monotone" 
          dataKey="spread" 
          stroke="#ff6b6b" 
          strokeWidth={2}
          dot={false}
          name="Spread (bps)"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
