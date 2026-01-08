interface MarketData {
  timestamp: string;
  price: number;
  spread: number;
  volume: number;
}

interface Props {
  data: MarketData[];
}

export default function DataGrid({ data }: Props) {
  return (
    <div className="data-grid-container">
      <table className="data-grid">
        <thead>
          <tr>
            <th>Time</th>
            <th>Price</th>
            <th>Spread (bps)</th>
            <th>Volume</th>
            <th>Change</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row, idx) => {
            const prevPrice = idx > 0 ? data[idx - 1].price : row.price;
            const change = ((row.price - prevPrice) / prevPrice) * 100;
            const isPositive = change >= 0;

            return (
              <tr key={row.timestamp}>
                <td>{new Date(row.timestamp).toLocaleTimeString()}</td>
                <td className="price">${row.price.toFixed(3)}</td>
                <td>{(row.spread * 10000).toFixed(1)}</td>
                <td>{Math.round(row.volume).toLocaleString()}</td>
                <td className={isPositive ? 'positive' : 'negative'}>
                  {isPositive ? '+' : ''}{change.toFixed(2)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
