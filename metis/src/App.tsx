import { useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { TrendingUp, Activity, Database, AlertCircle } from 'lucide-react';
import PriceChart from './components/PriceChart';
import DataGrid from './components/DataGrid';
import NewsFeed from './components/NewsFeed';
import './App.css';

interface MarketData {
  timestamp: string;
  price: number;
  spread: number;
  volume: number;
}

function App() {
  const [mode, setMode] = useState<'DEV' | 'REAL'>('DEV');
  const [marketData, setMarketData] = useState<MarketData[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<string>('');

  // Simulate fetching data from backend
  const fetchMarketData = async () => {
    setLoading(true);
    try {
      // In DEV mode, use synthetic data
      // Later we'll wire this to invoke() Rust commands
      const syntheticData: MarketData[] = Array.from({ length: 100 }, (_, i) => ({
        timestamp: new Date(Date.now() - (100 - i) * 60000).toISOString(),
        price: 2.5 + Math.sin(i / 10) * 0.3 + Math.random() * 0.1,
        spread: 0.02 + Math.random() * 0.01,
        volume: 10000 + Math.random() * 5000
      }));
      
      setMarketData(syntheticData);
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (error) {
      console.error('Failed to fetch data:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMarketData();
    const interval = setInterval(fetchMarketData, 30000); // Update every 30s
    return () => clearInterval(interval);
  }, [mode]);

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-left">
          <h1 className="title">
            <Activity size={24} />
            Metis Natural Gas Platform
          </h1>
          <span className="mode-badge" data-mode={mode.toLowerCase()}>
            {mode} MODE
          </span>
        </div>
        <div className="header-right">
          <button 
            className="refresh-btn"
            onClick={fetchMarketData}
            disabled={loading}
          >
            {loading ? 'Loading...' : 'Refresh Data'}
          </button>
          <span className="last-update">Last update: {lastUpdate}</span>
        </div>
      </header>

      {/* Main Grid Layout */}
      <div className="main-grid">
        {/* Left Panel - Price Chart */}
        <div className="panel chart-panel">
          <div className="panel-header">
            <TrendingUp size={18} />
            <h2>Natural Gas Spot Price (Henry Hub)</h2>
          </div>
          <PriceChart data={marketData} />
        </div>

        {/* Right Panel - News/Signals */}
        <div className="panel news-panel">
          <div className="panel-header">
            <AlertCircle size={18} />
            <h2>Market Signals & News</h2>
          </div>
          <NewsFeed mode={mode} />
        </div>

        {/* Bottom Panel - Data Table */}
        <div className="panel data-panel">
          <div className="panel-header">
            <Database size={18} />
            <h2>Recent Trades & Analytics</h2>
          </div>
          <DataGrid data={marketData.slice(-20)} />
        </div>
      </div>
    </div>
  );
}

export default App;
