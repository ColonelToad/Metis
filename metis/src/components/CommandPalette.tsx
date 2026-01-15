import { useState, useEffect } from 'react';
import { Modal, Input, List } from 'antd';
import {
  AppstoreOutlined,
  BulbOutlined,
  WalletOutlined,
  SearchOutlined,
  StockOutlined,
  ThunderboltOutlined,
  CloudOutlined,
  FileProtectOutlined,
  ExperimentOutlined,
  SettingOutlined,
  ReloadOutlined,
  GlobalOutlined,
} from '@ant-design/icons';

export interface Command {
  id: string;
  label: string;
  icon?: React.ReactNode;
  keywords?: string[];
  action: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  commands: Command[];
}

export default function CommandPalette({ open, onClose, commands }: CommandPaletteProps) {
  const [searchText, setSearchText] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Filter commands based on search text
  const filteredCommands = commands.filter(cmd => {
    const searchLower = searchText.toLowerCase();
    const matchesLabel = cmd.label.toLowerCase().includes(searchLower);
    const matchesKeywords = cmd.keywords?.some(kw => kw.toLowerCase().includes(searchLower));
    return matchesLabel || matchesKeywords;
  });

  // Reset selection when search changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [searchText]);

  // Reset search when modal closes
  useEffect(() => {
    if (!open) {
      setSearchText('');
      setSelectedIndex(0);
    }
  }, [open]);

  // Handle keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => Math.min(prev + 1, filteredCommands.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => Math.max(prev - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filteredCommands[selectedIndex]) {
        filteredCommands[selectedIndex].action();
        onClose();
      }
    }
  };

  const handleCommandClick = (cmd: Command) => {
    cmd.action();
    onClose();
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      closable={false}
      width={600}
      styles={{
        body: { padding: 0 },
      }}
      style={{ top: 100 }}
    >
      <div onKeyDown={handleKeyDown}>
        <Input
          autoFocus
          size="large"
          placeholder="Type a command or search..."
          value={searchText}
          onChange={e => setSearchText(e.target.value)}
          style={{
            borderRadius: 0,
            borderLeft: 'none',
            borderRight: 'none',
            borderTop: 'none',
          }}
          aria-label="Command palette search"
        />
        <List
          dataSource={filteredCommands}
          style={{ maxHeight: 400, overflowY: 'auto' }}
          renderItem={(cmd, idx) => (
            <List.Item
              key={cmd.id}
              onClick={() => handleCommandClick(cmd)}
              style={{
                cursor: 'pointer',
                background: idx === selectedIndex ? '#1890ff20' : 'transparent',
                padding: '12px 24px',
                borderLeft: idx === selectedIndex ? '3px solid #1890ff' : '3px solid transparent',
              }}
              onMouseEnter={() => setSelectedIndex(idx)}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                {cmd.icon && <span style={{ fontSize: 16 }}>{cmd.icon}</span>}
                <span style={{ fontWeight: idx === selectedIndex ? 600 : 400 }}>{cmd.label}</span>
              </div>
            </List.Item>
          )}
        />
        {filteredCommands.length === 0 && (
          <div style={{ padding: 24, textAlign: 'center', color: '#8c8c8c' }}>
            No commands found
          </div>
        )}
        <div style={{ padding: '8px 24px', borderTop: '1px solid #303030', fontSize: 12, color: '#8c8c8c' }}>
          <span style={{ marginRight: 16 }}>↑↓ Navigate</span>
          <span style={{ marginRight: 16 }}>↵ Select</span>
          <span>Esc Close</span>
        </div>
      </div>
    </Modal>
  );
}

export const createNavigationCommands = (navigate: (key: string) => void): Command[] => [
  { id: 'nav-overview', label: 'Go to Overview', icon: <AppstoreOutlined />, keywords: ['home', 'dashboard'], action: () => navigate('overview') },
  { id: 'nav-signals', label: 'Go to Signals', icon: <BulbOutlined />, keywords: ['trade', 'ai', 'recommendations'], action: () => navigate('signals') },
  { id: 'nav-portfolio', label: 'Go to Portfolio', icon: <WalletOutlined />, keywords: ['positions', 'holdings', 'pnl'], action: () => navigate('portfolio') },
  { id: 'nav-explainer', label: 'Go to Explainer', icon: <SearchOutlined />, keywords: ['rag', 'analysis', 'reasoning'], action: () => navigate('explainer') },
  { id: 'nav-markets', label: 'Go to Markets', icon: <StockOutlined />, keywords: ['watchlist', 'prices', 'charts'], action: () => navigate('markets') },
  { id: 'nav-grid', label: 'Go to Grid Status', icon: <ThunderboltOutlined />, keywords: ['power', 'electricity', 'load'], action: () => navigate('grid') },
  { id: 'nav-climate', label: 'Go to Climate', icon: <CloudOutlined />, keywords: ['weather', 'temperature', 'alerts'], action: () => navigate('climate') },
  { id: 'nav-policy', label: 'Go to Policy', icon: <FileProtectOutlined />, keywords: ['bills', 'legislation', 'congress'], action: () => navigate('policy') },
  { id: 'nav-backtest', label: 'Go to Backtest', icon: <ExperimentOutlined />, keywords: ['test', 'simulation', 'historical'], action: () => navigate('backtest') },
  { id: 'nav-settings', label: 'Go to Settings', icon: <SettingOutlined />, keywords: ['config', 'preferences'], action: () => navigate('settings') },
];

export const createUtilityCommands = (setLocale: (locale: 'en-US' | 'zh-CN') => void): Command[] => [
  { id: 'refresh', label: 'Refresh Page', icon: <ReloadOutlined />, keywords: ['reload'], action: () => window.location.reload() },
  { id: 'lang-en', label: 'Switch to English', icon: <GlobalOutlined />, keywords: ['language', 'locale'], action: () => setLocale('en-US') },
  { id: 'lang-zh', label: 'Switch to Chinese', icon: <GlobalOutlined />, keywords: ['language', 'locale', '中文'], action: () => setLocale('zh-CN') },
];
