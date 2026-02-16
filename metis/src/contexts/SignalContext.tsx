import { createContext, useContext, useState, ReactNode } from 'react';

export interface TradingSignal {
  id: string;
  signal_id: string;
  instrument: string;
  symbol: string;
  direction: 'LONG' | 'SHORT';
  confidence: number;
  timestamp: string;
  target_quantity?: number;
  horizon_minutes?: number;
  context?: {
    current_price?: number;
    grid_stress_index?: number;
    temperature_anomaly?: number;
    recent_policy_events?: string[];
    primary_region?: string;
  };
  metadata?: Record<string, any>;
}

interface SignalContextType {
  activeSignal: TradingSignal | null;
  setActiveSignal: (signal: TradingSignal | null) => void;
}

const SignalContext = createContext<SignalContextType | undefined>(undefined);

export function SignalProvider({ children }: { children: ReactNode }) {
  const [activeSignal, setActiveSignal] = useState<TradingSignal | null>(null);

  return (
    <SignalContext.Provider value={{ activeSignal, setActiveSignal }}>
      {children}
    </SignalContext.Provider>
  );
}

export function useSignal() {
  const context = useContext(SignalContext);
  if (!context) {
    throw new Error('useSignal must be used within SignalProvider');
  }
  return context;
}
