/**
 * Transform pipeline signals to RAG signal format
 * Converts between the orchestrator's signal schema and what the RAG backend expects
 */

export interface PipelineSignal {
  signal_id: string;
  timestamp: string;
  symbol: string;
  direction: string;
  confidence: number;
  target_quantity?: number;
  horizon_minutes?: number;
  metadata?: Record<string, any>;
}

export interface RagSignal {
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

/**
 * Transform a pipeline signal to RAG format
 * Handles field name mapping and context data extraction
 */
export function transformSignalForRag(pipelineSignal: PipelineSignal): RagSignal {
  const metadata = pipelineSignal.metadata || {};
  
  return {
    // ID fields - use signal_id as both id and signal_id for consistency
    id: pipelineSignal.signal_id,
    signal_id: pipelineSignal.signal_id,
    
    // Instrument fields - use symbol for both
    instrument: pipelineSignal.symbol,
    symbol: pipelineSignal.symbol,
    
    // Direction - ensure it's LONG or SHORT format
    direction: normalizDirection(pipelineSignal.direction),
    
    // Price and confidence
    confidence: pipelineSignal.confidence,
    timestamp: pipelineSignal.timestamp,
    
    // Optional fields
    target_quantity: pipelineSignal.target_quantity,
    horizon_minutes: pipelineSignal.horizon_minutes,
    
    // Context - extract from metadata or provide reasonable defaults
    context: {
      current_price: metadata.current_price || 0,
      grid_stress_index: metadata.grid_stress_index || 50,
      temperature_anomaly: metadata.temperature_anomaly || 0,
      recent_policy_events: metadata.recent_policy_events || [],
      primary_region: metadata.primary_region || 'ERCOT',
    },
    
    // Preserve any additional metadata
    metadata: pipelineSignal.metadata,
  };
}

/**
 * Normalize direction to LONG/SHORT format
 */
function normalizDirection(direction: string): 'LONG' | 'SHORT' {
  const normalized = direction?.toUpperCase() || 'LONG';
  if (normalized === 'BUY' || normalized === 'LONG') {
    return 'LONG';
  }
  if (normalized === 'SELL' || normalized === 'SHORT') {
    return 'SHORT';
  }
  return 'LONG'; // Default
}

/**
 * Validate RAG signal has required fields
 */
export function isValidRagSignal(signal: RagSignal): boolean {
  return !!(
    signal.id &&
    signal.signal_id &&
    signal.instrument &&
    signal.direction &&
    typeof signal.confidence === 'number' &&
    signal.timestamp
  );
}
