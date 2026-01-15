import React from 'react';
import { Card, List, Tag, Button } from 'antd';

// Mock data for Explainer
const analysis = [
  {
    step: 1,
    title: 'Market Condition Analysis',
    content: 'Natural gas futures (NG_MAR26) were trading at $3.45/MMBtu as of 9:15 AM on January 14, 2026. The market exhibited backwardation (Feb contract at $3.52), signaling near-term supply concerns [Doc 3: EIA Storage Report]. Storage levels were 18% below the 5-year average at 2,450 Bcf, down from 2,980 Bcf last year [Doc 3]. This deficit has historically preceded price increases of 10-15% within 2 weeks [Doc 7: Historical Analysis].'
  },
  {
    step: 2,
    title: 'Weather & Climate Drivers',
    content: "NOAA's GFS ensemble model shows 70% probability of a polar vortex dipping into the central US on January 16-18 [Doc 1: NOAA Forecast]. Expected temperatures are 20-30°F below seasonal averages across Texas and the Midwest. Historical data shows that similar cold snaps increased NG demand by 30-45% [Doc 4: Climate Analysis]. Given current storage deficits, this demand spike could strain supply."
  },
  {
    step: 3,
    title: 'Grid Stress Indicators',
    content: 'ERCOT grid stress index reached 73/100 at 9:00 AM, with reserves at 73% of target [Doc 2: GridStatus Data]. High demand combined with wind generation underperformance (15% below forecast) required increased natural gas dispatch. When ERCOT stress exceeds 70/100, NG prices historically correlate +0.68 with grid demand [Doc 5: Correlation Study].'
  },
  {
    step: 4,
    title: 'Policy & Structural Factors',
    content: 'No immediate policy catalysts identified. However, H.R. 1234 (Clean Energy Tax Credits) advancing through Congress may increase renewable penetration long-term, creating structural support for NG as backup generation [Doc 6: Congressional Tracker].'
  },
  {
    step: 5,
    title: 'Expected Outcome & Risk Assessment',
    content: 'Probabilistic Scenarios: Base Case (60%): Cold snap materializes, NG rises to $3.70-3.80 (+7-10%) within 5 days. Upside (25%): Severe cold + supply disruptions → $4.00+ (+16%). Downside (15%): Warm reversal, NG drops to $3.30 (-4%). Expected Value: +6.1%. Risk/Reward: 2.3:1 (favorable). Risk Factors: Weather forecast uncertainty (30% chance polar vortex fails to materialize), storage report Thursday could show surprise build.'
  }
];
const documents = [
  { id: 1, title: 'NOAA GFS Ensemble Forecast (Jan 14, 2026)' },
  { id: 2, title: 'GridStatus ERCOT Real-Time Data (Jan 14, 9:00 AM)' },
  { id: 3, title: 'EIA Natural Gas Storage Report (Jan 9, 2026)' },
  { id: 4, title: 'Historical Climate-Energy Correlation Study (2023)' },
  { id: 5, title: 'Grid Stress-Price Correlation Analysis (Internal)' },
  { id: 6, title: 'Congressional Bill Tracker (H.R. 1234)' },
  { id: 7, title: 'NG Storage Deficit Historical Analysis (2020-2025)' },
];

export default function ExplainerScreen() {
  return React.createElement(
    'div',
    { style: { padding: 24 } },
    React.createElement(
      Card,
      { title: 'Chain-of-Thought Analysis', bordered: false },
      React.createElement(List, {
        dataSource: analysis,
        renderItem: function (item: any) {
          return React.createElement(
            List.Item,
            null,
            React.createElement(
              'div',
              null,
              React.createElement('span', { style: { fontWeight: 600 } }, 'Step ' + item.step + ': ' + item.title),
              React.createElement('div', { style: { marginTop: 4 } }, item.content)
            )
          );
        }
      })
    ),
    React.createElement(
      Card,
      { title: 'Supporting Documents (Retrieved)', bordered: false, style: { marginTop: 16 } },
      React.createElement(List, {
        dataSource: documents,
        renderItem: function (item: any) {
          return React.createElement(
            List.Item,
            null,
            React.createElement(Tag, { color: 'blue' }, 'Doc ' + item.id),
            React.createElement('span', null, item.title)
          );
        }
      }),
      React.createElement(
        'div',
        { style: { marginTop: 16, display: 'flex', gap: 8 } },
        React.createElement(Button, null, '💾 Save Analysis'),
        React.createElement(Button, null, '📄 Export PDF'),
        React.createElement(Button, null, '🔄 Regenerate'),
        React.createElement(Button, null, '❓ Ask Follow-up')
      )
    )
  );
}
