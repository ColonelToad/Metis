import { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, AlertTriangle, FileText } from 'lucide-react';

interface NewsItem {
  id: string;
  type: 'signal' | 'news' | 'alert';
  title: string;
  timestamp: string;
  sentiment: 'bullish' | 'bearish' | 'neutral';
}

interface Props {
  mode: 'DEV' | 'REAL';
}

export default function NewsFeed({ mode }: Props) {
  const [news, setNews] = useState<NewsItem[]>([]);

  useEffect(() => {
    // In DEV mode, generate synthetic news
    const syntheticNews: NewsItem[] = [
      {
        id: '1',
        type: 'alert',
        title: 'High correlation detected: NG price vs. EIA storage (0.85)',
        timestamp: new Date(Date.now() - 300000).toISOString(),
        sentiment: 'neutral'
      },
      {
        id: '2',
        type: 'signal',
        title: 'Congress.gov: New energy infrastructure bill introduced',
        timestamp: new Date(Date.now() - 1800000).toISOString(),
        sentiment: 'bullish'
      },
      {
        id: '3',
        type: 'news',
        title: 'EIA weekly storage report: +15 Bcf vs. expected +12 Bcf',
        timestamp: new Date(Date.now() - 3600000).toISOString(),
        sentiment: 'bearish'
      },
      {
        id: '4',
        type: 'signal',
        title: 'CAISO LMP spike detected in Northern California (+40%)',
        timestamp: new Date(Date.now() - 7200000).toISOString(),
        sentiment: 'bullish'
      },
      {
        id: '5',
        type: 'news',
        title: 'TomTom: Traffic congestion at Sabine Pass LNG terminal (95%)',
        timestamp: new Date(Date.now() - 10800000).toISOString(),
        sentiment: 'bullish'
      },
    ];

    setNews(syntheticNews);
  }, [mode]);

  const getIcon = (type: string, sentiment: string) => {
    if (type === 'alert') return <AlertTriangle size={16} color="#ff6b6b" />;
    if (sentiment === 'bullish') return <TrendingUp size={16} color="#00ff88" />;
    if (sentiment === 'bearish') return <TrendingDown size={16} color="#ff6b6b" />;
    return <FileText size={16} color="#888" />;
  };

  return (
    <div className="news-feed">
      {news.map(item => (
        <div key={item.id} className={`news-item ${item.type}`}>
          <div className="news-icon">
            {getIcon(item.type, item.sentiment)}
          </div>
          <div className="news-content">
            <div className="news-title">{item.title}</div>
            <div className="news-meta">
              <span className="news-time">
                {new Date(item.timestamp).toLocaleTimeString()}
              </span>
              <span className={`news-sentiment ${item.sentiment}`}>
                {item.sentiment.toUpperCase()}
              </span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
