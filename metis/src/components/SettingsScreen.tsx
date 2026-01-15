import React from 'react';
import { Card, Row, Col, List, Tag, Button, Switch, Select, Divider } from 'antd';

const dataSources = [
  { name: 'EIA API', status: 'Connected', color: 'green' },
  { name: 'GridStatus.io', status: 'Connected', color: 'green' },
  { name: 'Congress.gov', status: 'Connected', color: 'green' },
  { name: 'Alpha Vantage', status: 'Rate Limit', color: 'red' },
];
const modelSettings = [
  { label: 'LLM', value: 'Llama 3.1 8B (Q4_K_M)' },
  { label: 'Temperature', value: 0.7 },
  { label: 'Max Tokens', value: 512 },
  { label: 'Signal Confidence Threshold', value: 0.65 },
  { label: 'Max Positions', value: 5 },
  { label: 'Risk per Trade', value: '20%' },
  { label: 'Backtest Slippage', value: '0.5 bps' },
  { label: 'Transaction Costs', value: '0.1 bps' },
];
const riskLimits = [
  { label: 'Max Position Size', value: '30% of portfolio' },
  { label: 'Daily Loss Limit', value: '$5,000' },
  { label: 'Portfolio VaR Limit', value: '$10,000 (99% confidence)' },
  { label: 'Max Portfolio Volatility', value: '25% annualized' },
];
const notifications = [
  { label: 'Email alerts', checked: true },
  { label: 'Desktop notifications', checked: true },
  { label: 'SMS (coming soon)', checked: false },
  { label: 'Alert on: New signals', checked: true },
  { label: 'Alert on: Risk limit breaches', checked: true },
  { label: 'Alert on: System errors', checked: true },
];

export default function SettingsScreen() {
  return React.createElement(
    'div',
    { style: { padding: 24 } },
    React.createElement(
      Row,
      { gutter: 16 },
      React.createElement(
        Col,
        { span: 12 },
        React.createElement(
          Card,
          { title: 'Data Sources', bordered: false },
          React.createElement(List, {
            dataSource: dataSources,
            renderItem: (item: any) =>
              React.createElement(
                List.Item,
                null,
                React.createElement(Tag, { color: item.color }, item.status),
                React.createElement('span', { style: { minWidth: 120, display: 'inline-block' } }, item.name),
                React.createElement(Button, { size: 'small', style: { marginLeft: 8 } }, 'Test'),
                React.createElement(Button, { size: 'small', style: { marginLeft: 4 } }, 'Edit Key')
              ),
          })
        )
      ),
      React.createElement(
        Col,
        { span: 12 },
        React.createElement(
          Card,
          { title: 'Model Settings', bordered: false },
          React.createElement(List, {
            dataSource: modelSettings,
            renderItem: (item: any) =>
              React.createElement(
                List.Item,
                null,
                React.createElement('span', { style: { minWidth: 180, display: 'inline-block' } }, `${item.label}:`),
                React.createElement('span', null, String(item.value))
              ),
          }),
          React.createElement(Button, { style: { marginTop: 8 } }, 'Advanced LLM Settings →')
        )
      )
    ),
    React.createElement(
      Row,
      { gutter: 16, style: { marginTop: 16 } },
      React.createElement(
        Col,
        { span: 12 },
        React.createElement(
          Card,
          { title: 'Risk Limits', bordered: false },
          React.createElement(List, {
            dataSource: riskLimits,
            renderItem: (item: any) =>
              React.createElement(
                List.Item,
                null,
                React.createElement('span', { style: { minWidth: 180, display: 'inline-block' } }, `${item.label}:`),
                React.createElement('span', null, String(item.value))
              ),
          }),
          React.createElement(Divider, null),
          React.createElement(Button, { danger: true }, '⚠️ Enable Kill Switch')
        )
      ),
      React.createElement(
        Col,
        { span: 12 },
        React.createElement(
          Card,
          { title: 'Notifications & Appearance', bordered: false },
          React.createElement(List, {
            dataSource: notifications,
            renderItem: (item: any) =>
              React.createElement(
                List.Item,
                null,
                React.createElement(Switch, { checked: item.checked, disabled: true }),
                React.createElement('span', { style: { marginLeft: 8 } }, item.label)
              ),
          }),
          React.createElement(Divider, null),
          React.createElement(
            'div',
            { style: { marginBottom: 8 } },
            'Theme: ',
            React.createElement(Select, {
              defaultValue: 'dark',
              style: { width: 120 },
              disabled: true,
              options: [
                { value: 'dark', label: 'Dark' },
                { value: 'light', label: 'Light' },
                { value: 'auto', label: 'Auto' },
              ],
            })
          ),
          React.createElement(
            'div',
            { style: { marginBottom: 8 } },
            'Chart Style: ',
            React.createElement(Select, {
              defaultValue: 'candlestick',
              style: { width: 140 },
              disabled: true,
              options: [{ value: 'candlestick', label: 'Candlestick' }],
            })
          ),
          React.createElement(
            'div',
            { style: { marginBottom: 8 } },
            'Refresh Rate: ',
            React.createElement(Select, {
              defaultValue: 1,
              style: { width: 100 },
              disabled: true,
              options: [
                { value: 1, label: '1s' },
                { value: 5, label: '5s' },
                { value: 10, label: '10s' },
              ],
            })
          ),
          React.createElement(
            'div',
            { style: { marginBottom: 8 } },
            'Timezone: ',
            React.createElement(Select, {
              defaultValue: 'EST',
              style: { width: 100 },
              disabled: true,
              options: [{ value: 'EST', label: 'EST' }],
            })
          ),
          React.createElement(Button, null, 'Keyboard Shortcuts →')
        )
      )
    )
  );
}
