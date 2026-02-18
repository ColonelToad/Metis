
import { useState, useEffect } from 'react';
import { Layout, Menu, ConfigProvider, theme as antdTheme, App as AntApp } from 'antd';
import OverviewScreen from './components/OverviewScreen';
import SignalsScreen from './components/SignalsScreen';
import PortfolioScreen from './components/PortfolioScreen';
import ExplainerScreen from './components/ExplainerScreen';
import SettingsScreen from './components/SettingsScreen';
import MarketsScreen from './components/MarketsScreen';
import GridStatusScreen from './components/GridStatusScreen';
import ClimateScreen from './components/ClimateScreen';
import PolicyScreen from './components/PolicyScreen';
import BacktestScreen from './components/BacktestScreen';
import AdminScreen from './components/AdminScreen';
import {
  AppstoreOutlined,
  BulbOutlined,
  WalletOutlined,
  SearchOutlined,
  SettingOutlined,
  StockOutlined,
  ThunderboltOutlined,
  CloudOutlined,
  FileProtectOutlined,
  ExperimentOutlined,
  FormatPainterOutlined
} from '@ant-design/icons';
import { IntlProvider } from 'react-intl';
import enUS from 'antd/locale/en_US';
import { LocaleProvider, useLocale } from './contexts/LocaleContext';
import { SignalProvider } from './contexts/SignalContext';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';
import CommandPalette, { createNavigationCommands, createUtilityCommands } from './components/CommandPalette';
import './App.css';

const { Header, Sider, Content } = Layout;

const menuItems = [
  { key: 'overview', icon: <AppstoreOutlined />, label: 'Overview' },
  { key: 'signals', icon: <BulbOutlined />, label: 'Signals' },
  { key: 'portfolio', icon: <WalletOutlined />, label: 'Portfolio' },
  { key: 'explainer', icon: <SearchOutlined />, label: 'Explainer' },
  { key: 'markets', icon: <StockOutlined />, label: 'Markets' },
  { key: 'grid', icon: <ThunderboltOutlined />, label: 'Grid Status' },
  { key: 'climate', icon: <CloudOutlined />, label: 'Climate' },
  { key: 'policy', icon: <FileProtectOutlined />, label: 'Policy' },
  { key: 'backtest', icon: <ExperimentOutlined />, label: 'Backtest' },
  { key: 'admin', icon: <FormatPainterOutlined />, label: 'Admin' },
  { key: 'settings', icon: <SettingOutlined />, label: 'Settings' },
];

function AppContent() {
  const [collapsed, setCollapsed] = useState(false);
  const [selectedKey, setSelectedKey] = useState('overview');
  const [mode] = useState<'DEV' | 'REAL'>('DEV');
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [currentTime, setCurrentTime] = useState(new Date());
  const { locale, messages, setLocale } = useLocale();

  // Update clock every second
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Setup keyboard shortcuts
  useKeyboardShortcuts([
    { key: '1', ctrlKey: true, handler: () => setSelectedKey('overview'), description: 'Go to Overview' },
    { key: '2', ctrlKey: true, handler: () => setSelectedKey('signals'), description: 'Go to Signals' },
    { key: '3', ctrlKey: true, handler: () => setSelectedKey('portfolio'), description: 'Go to Portfolio' },
    { key: '4', ctrlKey: true, handler: () => setSelectedKey('explainer'), description: 'Go to Explainer' },
    { key: '5', ctrlKey: true, handler: () => setSelectedKey('markets'), description: 'Go to Markets' },
    { key: '6', ctrlKey: true, handler: () => setSelectedKey('grid'), description: 'Go to Grid Status' },
    { key: '7', ctrlKey: true, handler: () => setSelectedKey('climate'), description: 'Go to Climate' },
    { key: '8', ctrlKey: true, handler: () => setSelectedKey('policy'), description: 'Go to Policy' },
    { key: '9', ctrlKey: true, handler: () => setSelectedKey('backtest'), description: 'Go to Backtest' },
    { key: '0', ctrlKey: true, handler: () => setSelectedKey('settings'), description: 'Go to Settings' },
    { key: 'k', ctrlKey: true, handler: () => setCommandPaletteOpen(true), description: 'Command Palette' },
    { key: 'r', ctrlKey: true, handler: () => window.location.reload(), description: 'Refresh' },
  ]);

  // Build command list for palette
  const commands = [
    ...createNavigationCommands(setSelectedKey),
    ...createUtilityCommands(setLocale),
  ];

  // Render Ant Design-based screens for Overview and Signals
  const renderContent = () => {
    switch (selectedKey) {
      case 'overview':
        return <OverviewScreen />;
      case 'signals':
        return <SignalsScreen onNavigate={setSelectedKey} />;
      case 'portfolio':
        return <PortfolioScreen />;
      case 'explainer':
        return <ExplainerScreen />;
      case 'markets':
        return <MarketsScreen />;
      case 'grid':
        return <GridStatusScreen />;
      case 'climate':
        return <ClimateScreen />;
      case 'policy':
        return <PolicyScreen />;
      case 'backtest':
        return <BacktestScreen />;
      case 'admin':
        return <AdminScreen />;
      case 'settings':
        return <SettingsScreen />;
      default:
        return <div style={{ padding: 24 }}>Welcome to Metis</div>;
    }
  };

  return (
    <ConfigProvider
      locale={enUS}
      theme={{ algorithm: antdTheme.darkAlgorithm }}
    >
      <AntApp>
        <IntlProvider locale={locale} messages={messages}>
          <CommandPalette
            open={commandPaletteOpen}
            onClose={() => setCommandPaletteOpen(false)}
            commands={commands}
          />
          <Layout style={{ minHeight: '100vh' }}>
            <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="dark">
              <div style={{ height: 48, margin: 16, color: '#fff', fontWeight: 'bold', fontSize: 20, textAlign: 'center', letterSpacing: 2 }} role="banner">
                METIS
              </div>
              <Menu
                theme="dark"
                mode="inline"
                selectedKeys={[selectedKey]}
                onClick={({ key }) => setSelectedKey(key)}
                items={menuItems}
                style={{ fontSize: 16 }}
                role="navigation"
                aria-label="Main navigation"
              />
            </Sider>
            <Layout>
              <Header style={{ background: '#18181c', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }} role="banner">
                <div style={{ color: '#fff', fontSize: 22, fontWeight: 600 }}>
                  Metis Platform
                  <span style={{ marginLeft: 16, fontSize: 14, color: '#00ff88', background: '#222', borderRadius: 4, padding: '2px 8px', marginRight: 8 }} role="status" aria-live="polite">
                    {mode} MODE
                  </span>
                </div>
                <div style={{ color: '#aaa', fontSize: 14 }} role="timer" aria-live="off">
                  {currentTime.toLocaleString()}
                </div>
              </Header>
              <Content style={{ margin: 0, background: '#18181c', minHeight: 0, overflowY: 'auto', height: 'calc(100vh - 64px)' }} role="main" aria-label="Main content">
                {renderContent()}
              </Content>
            </Layout>
          </Layout>
        </IntlProvider>
      </AntApp>
    </ConfigProvider>
  );
}

function App() {
  return (
    <LocaleProvider>
      <SignalProvider>
        <AppContent />
      </SignalProvider>
    </LocaleProvider>
  );
}

export default App;
