/**
 * Research feature barrel export
 * Exports all types, API client functions, components, and hooks
 */

// Types
export {
  SignalType,
  type VolatilityRegime,
  type TradingSession,
  type ProbabilityBucket,
  type ProbabilitySurfaceMetadata,
  type ProbabilitySurface as ProbabilitySurfaceData,
  type SignalMetadata,
  type Signal,
  type TradingOpportunity,
  type LagStats,
  type EnrichedSnapshot,
  type BacktestTrade,
  type EquityCurvePoint,
  type BacktestMetrics,
  type BacktestResult,
  type ObservationStatus,
  type ResearchMetrics,
  type ResearchWebSocketMessageType,
  type ResearchWebSocketMessage,
  type SnapshotMessage,
  type SignalMessage,
  type OpportunityMessage,
  type SurfaceUpdateMessage,
  type ObservationStatusMessage,
} from './types/research.types';

// API Client
export {
  fetchProbabilitySurface,
  fetchSignals,
  fetchLagStats,
  fetchBacktestResults,
  fetchResearchMetrics,
  startObservation,
  stopObservation,
  getObservationStatus,
  createResearchWebSocket,
  ResearchWebSocket,
  type ResearchWebSocketCallbacks,
} from './api/research-client';

// Hooks
export {
  useResearchMetrics,
  useProbabilitySurface,
  useSignalStream,
  useLagAnalysis,
  type UseResearchMetricsReturn,
  type UseProbabilitySurfaceReturn,
  type SurfaceFilters,
  type UseSignalStreamReturn,
  type UseSignalStreamOptions,
  type UseLagAnalysisReturn,
} from './hooks';

// Components
export { ResearchDashboard } from './ResearchDashboard';
export { ProbabilitySurface } from './components/ProbabilitySurface';
export { SignalDetector } from './components/SignalDetector';
export { EdgeCalculator } from './components/EdgeCalculator';
export { LagAnalysis } from './components/LagAnalysis';
export { BacktestResults } from './components/BacktestResults';
export { LiveObserver } from './components/LiveObserver';
