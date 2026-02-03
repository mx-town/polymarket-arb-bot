import { useState } from 'react';
import type { VolatilityRegime, TradingSession } from '../../types/research.types';

export type VolatilityFilter = VolatilityRegime | 'all';
export type SessionFilter = TradingSession | 'all';
export type ZoomLevel = 'narrow' | 'wide';

export interface SurfaceControlsProps {
  /** Current volatility filter */
  volatilityFilter: VolatilityFilter;
  /** Callback when volatility filter changes */
  onVolatilityChange: (value: VolatilityFilter) => void;
  /** Current session filter */
  sessionFilter: SessionFilter;
  /** Callback when session filter changes */
  onSessionChange: (value: SessionFilter) => void;
  /** Current zoom level */
  zoomLevel: ZoomLevel;
  /** Callback when zoom level changes */
  onZoomChange: (value: ZoomLevel) => void;
}

const VOLATILITY_OPTIONS: { value: VolatilityFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Med' },
  { value: 'high', label: 'High' },
];

const SESSION_OPTIONS: { value: SessionFilter; label: string }[] = [
  { value: 'all', label: 'All Sessions' },
  { value: 'asia', label: 'Asia' },
  { value: 'europe', label: 'Europe' },
  { value: 'us', label: 'US' },
  { value: 'overlap', label: 'Overlap' },
];

/**
 * Controls for filtering the probability surface
 * Includes volatility regime selector, session filter, and zoom toggle
 */
export function SurfaceControls({
  volatilityFilter,
  onVolatilityChange,
  sessionFilter,
  onSessionChange,
  zoomLevel,
  onZoomChange,
}: SurfaceControlsProps) {
  const [sessionDropdownOpen, setSessionDropdownOpen] = useState(false);

  const selectedSessionLabel =
    SESSION_OPTIONS.find((opt) => opt.value === sessionFilter)?.label || 'All Sessions';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '1rem',
        padding: '0.5rem 0',
        flexWrap: 'wrap',
      }}
    >
      {/* Volatility Regime Toggle Group */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
        <span
          style={{
            fontSize: '0.5625rem',
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            color: 'var(--text-muted)',
          }}
        >
          Volatility
        </span>
        <div
          style={{
            display: 'flex',
            background: 'var(--bg-primary)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)',
            padding: '2px',
            gap: '2px',
          }}
        >
          {VOLATILITY_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => onVolatilityChange(opt.value)}
              style={{
                padding: '0.25rem 0.5rem',
                borderRadius: '3px',
                fontSize: '0.6875rem',
                fontFamily: 'var(--font-mono)',
                fontWeight: 600,
                border: 'none',
                background:
                  volatilityFilter === opt.value ? 'var(--accent-blue)' : 'transparent',
                color:
                  volatilityFilter === opt.value ? '#0a0a0f' : 'var(--text-muted)',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Session Filter Dropdown */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '0.375rem',
          position: 'relative',
        }}
      >
        <span
          style={{
            fontSize: '0.5625rem',
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            color: 'var(--text-muted)',
          }}
        >
          Session
        </span>
        <button
          onClick={() => setSessionDropdownOpen(!sessionDropdownOpen)}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '0.5rem',
            padding: '0.375rem 0.625rem',
            background: 'var(--bg-primary)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            cursor: 'pointer',
            minWidth: '110px',
          }}
        >
          <span
            style={{
              fontSize: '0.6875rem',
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-primary)',
            }}
          >
            {selectedSessionLabel}
          </span>
          <svg
            width="10"
            height="10"
            viewBox="0 0 12 12"
            fill="none"
            style={{
              transform: sessionDropdownOpen ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 0.2s',
              color: 'var(--text-muted)',
            }}
          >
            <path
              d="M2.5 4.5L6 8L9.5 4.5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>

        {/* Dropdown menu */}
        {sessionDropdownOpen && (
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              right: 0,
              marginTop: '4px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              zIndex: 100,
              boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
              overflow: 'hidden',
            }}
          >
            {SESSION_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => {
                  onSessionChange(opt.value);
                  setSessionDropdownOpen(false);
                }}
                style={{
                  display: 'block',
                  width: '100%',
                  padding: '0.5rem 0.625rem',
                  fontSize: '0.6875rem',
                  fontFamily: 'var(--font-mono)',
                  color:
                    sessionFilter === opt.value
                      ? 'var(--accent-blue)'
                      : 'var(--text-primary)',
                  background:
                    sessionFilter === opt.value
                      ? 'var(--accent-blue-dim)'
                      : 'transparent',
                  border: 'none',
                  borderBottom: '1px solid var(--border-subtle)',
                  cursor: 'pointer',
                  textAlign: 'left',
                  transition: 'background 0.1s',
                }}
                onMouseEnter={(e) => {
                  if (sessionFilter !== opt.value) {
                    e.currentTarget.style.background = 'var(--bg-elevated)';
                  }
                }}
                onMouseLeave={(e) => {
                  if (sessionFilter !== opt.value) {
                    e.currentTarget.style.background = 'transparent';
                  }
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Zoom Toggle */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
        <span
          style={{
            fontSize: '0.5625rem',
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            color: 'var(--text-muted)',
          }}
        >
          Zoom
        </span>
        <div
          style={{
            display: 'flex',
            background: 'var(--bg-primary)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)',
            padding: '2px',
            gap: '2px',
          }}
        >
          <button
            onClick={() => onZoomChange('narrow')}
            style={{
              padding: '0.25rem 0.5rem',
              borderRadius: '3px',
              fontSize: '0.6875rem',
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              border: 'none',
              background: zoomLevel === 'narrow' ? 'var(--accent-amber)' : 'transparent',
              color: zoomLevel === 'narrow' ? '#0a0a0f' : 'var(--text-muted)',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            ±0.5%
          </button>
          <button
            onClick={() => onZoomChange('wide')}
            style={{
              padding: '0.25rem 0.5rem',
              borderRadius: '3px',
              fontSize: '0.6875rem',
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              border: 'none',
              background: zoomLevel === 'wide' ? 'var(--accent-amber)' : 'transparent',
              color: zoomLevel === 'wide' ? '#0a0a0f' : 'var(--text-muted)',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            ±2%
          </button>
        </div>
      </div>
    </div>
  );
}

export default SurfaceControls;
