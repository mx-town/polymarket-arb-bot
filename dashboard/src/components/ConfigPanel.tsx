import { useEffect, useState } from 'react';
import type { BotConfig } from '../api/client';
import { getConfig, updateConfig } from '../api/client';

// Section accent colors for visual differentiation
const SECTION_COLORS = {
  entry: '#4a9eff', // Blue - entry decisions
  position: '#00d4aa', // Green - money/sizing
  timing: '#ffaa00', // Amber - time-based
  risk: '#ff4757', // Red - risk/danger
  momentum: '#b366ff', // Purple - momentum/triggers
  filters: '#8888a0', // Gray - filtering
} as const;

// Time window options
const TIME_WINDOWS = [
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '1h', label: '1h' },
] as const;

// Toggle switch component
function Toggle({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <label
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '0.625rem',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      <div
        onClick={() => !disabled && onChange(!checked)}
        style={{
          width: '32px',
          height: '18px',
          borderRadius: '9px',
          background: checked ? 'var(--accent-green)' : 'var(--border)',
          position: 'relative',
          transition: 'background 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            width: '14px',
            height: '14px',
            borderRadius: '50%',
            background: 'white',
            position: 'absolute',
            top: '2px',
            left: checked ? '16px' : '2px',
            transition: 'left 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
            boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
          }}
        />
      </div>
      <span style={{ fontSize: '0.75rem', color: 'var(--text-primary)', fontWeight: 500 }}>
        {label}
      </span>
    </label>
  );
}

// Time window selector - segmented control style
function TimeWindowSelector({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
      <span
        style={{
          fontSize: '0.625rem',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          color: 'var(--text-muted)',
        }}
      >
        Candle Interval
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
        {TIME_WINDOWS.map((window) => (
          <button
            key={window.value}
            onClick={() => onChange(window.value)}
            style={{
              flex: 1,
              padding: '0.375rem 0.75rem',
              borderRadius: '3px',
              fontSize: '0.75rem',
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              border: 'none',
              background: value === window.value ? 'var(--accent-amber)' : 'transparent',
              color: value === window.value ? '#0a0a0f' : 'var(--text-muted)',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            {window.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// Inline editable value
function InlineValue({
  label,
  value,
  onChange,
  suffix = '',
  type = 'number',
  accentColor = 'var(--accent-blue)',
}: {
  label: string;
  value: string | number;
  onChange: (v: string | number) => void;
  suffix?: string;
  type?: 'number' | 'text';
  accentColor?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [tempValue, setTempValue] = useState(String(value));

  const handleSave = () => {
    setEditing(false);
    const newValue = type === 'number' ? parseFloat(tempValue) || 0 : tempValue;
    if (newValue !== value) {
      onChange(newValue);
    }
  };

  if (editing) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.25rem 0',
        }}
      >
        <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', minWidth: '70px' }}>
          {label}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
          <input
            type={type}
            value={tempValue}
            onChange={(e) => setTempValue(e.target.value)}
            onBlur={handleSave}
            onKeyDown={(e) => e.key === 'Enter' && handleSave()}
            autoFocus
            style={{
              width: '70px',
              padding: '0.25rem 0.375rem',
              fontSize: '0.75rem',
              textAlign: 'right',
            }}
          />
          <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', minWidth: '16px' }}>
            {suffix}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      onClick={() => {
        setTempValue(String(value));
        setEditing(true);
      }}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        cursor: 'pointer',
        padding: '0.25rem 0',
        borderRadius: 'var(--radius-sm)',
        transition: 'background 0.1s',
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-elevated)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
    >
      <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>{label}</span>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.75rem',
          color: accentColor,
          fontWeight: 500,
        }}
      >
        {value}
        {suffix && <span style={{ color: 'var(--text-muted)', marginLeft: '1px' }}>{suffix}</span>}
      </span>
    </div>
  );
}

// Collapsible section component
function CollapsibleSection({
  title,
  accentColor,
  defaultOpen = true,
  children,
}: {
  title: string;
  accentColor: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div
      style={{
        borderBottom: '1px solid var(--border-subtle)',
      }}
    >
      <button
        onClick={() => setIsOpen(!isOpen)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.625rem 0.75rem',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          transition: 'background 0.15s',
        }}
        onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-elevated)')}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div
            style={{
              width: '3px',
              height: '12px',
              borderRadius: '2px',
              background: accentColor,
              opacity: 0.8,
            }}
          />
          <span
            style={{
              fontSize: '0.625rem',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              color: 'var(--text-secondary)',
              fontWeight: 600,
            }}
          >
            {title}
          </span>
        </div>
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          style={{
            transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
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
      <div
        style={{
          overflow: 'hidden',
          maxHeight: isOpen ? '500px' : '0',
          opacity: isOpen ? 1 : 0,
          transition: 'max-height 0.25s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease',
        }}
      >
        <div style={{ padding: '0 0.75rem 0.75rem' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

export function ConfigPanel() {
  const [config, setConfig] = useState<BotConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  useEffect(() => {
    getConfig().then(setConfig).catch(console.error);
  }, []);

  const updateField = (section: keyof BotConfig, field: string, value: unknown) => {
    if (!config) return;
    setConfig({
      ...config,
      [section]: {
        ...config[section],
        [field]: value,
      },
    });
    setDirty(true);
    setMessage(null);
  };

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await updateConfig(config);
      setMessage({ text: 'Saved. Restart bot to apply.', type: 'success' });
      setDirty(false);
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : 'Failed to save', type: 'error' });
    } finally {
      setSaving(false);
    }
  };

  if (!config) {
    return (
      <div
        style={{
          background: 'var(--bg-card)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border)',
          padding: '2rem',
          textAlign: 'center',
          color: 'var(--text-muted)',
        }}
      >
        Loading config...
      </div>
    );
  }

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '0.625rem 0.75rem',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--bg-elevated)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
          <span style={{ fontSize: '0.875rem' }}>⚙</span>
          <span
            style={{
              fontSize: '0.6875rem',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-secondary)',
            }}
          >
            Configuration
          </span>
          {dirty && (
            <span
              style={{
                fontSize: '0.5625rem',
                padding: '0.125rem 0.375rem',
                background: 'var(--accent-amber-dim)',
                color: 'var(--accent-amber)',
                borderRadius: '9999px',
                fontWeight: 600,
                letterSpacing: '0.05em',
              }}
            >
              UNSAVED
            </span>
          )}
        </div>
        <button
          onClick={handleSave}
          disabled={saving || !dirty}
          style={{
            background: dirty ? 'var(--accent-green)' : 'var(--border)',
            color: dirty ? '#0a0a0f' : 'var(--text-muted)',
            padding: '0.3125rem 0.625rem',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.6875rem',
            fontWeight: 600,
          }}
        >
          {saving ? '...' : 'Save'}
        </button>
      </div>

      {/* Message */}
      {message && (
        <div
          style={{
            padding: '0.5rem 0.75rem',
            background:
              message.type === 'success' ? 'var(--accent-green-dim)' : 'var(--accent-red-dim)',
            color: message.type === 'success' ? 'var(--accent-green)' : 'var(--accent-red)',
            fontSize: '0.6875rem',
            borderBottom: '1px solid var(--border)',
          }}
        >
          {message.text}
        </div>
      )}

      {/* Strategy Mode Section - Always visible */}
      <div
        style={{
          padding: '0.75rem',
          borderBottom: '1px solid var(--border)',
          background: 'rgba(255,255,255,0.01)',
        }}
      >
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '0.75rem',
          }}
        >
          {/* Toggles row */}
          <div style={{ display: 'flex', gap: '1.25rem', flexWrap: 'wrap' }}>
            <Toggle
              checked={config.trading.dry_run}
              onChange={(v) => updateField('trading', 'dry_run', v)}
              label="Dry Run"
            />
            <Toggle
              checked={config.lag_arb.enabled}
              onChange={(v) => updateField('lag_arb', 'enabled', v)}
              label="Lag Arb"
            />
          </div>

          {/* Time window selector */}
          <TimeWindowSelector
            value={config.lag_arb.candle_interval}
            onChange={(v) => updateField('lag_arb', 'candle_interval', v)}
          />
        </div>
      </div>

      {/* Collapsible Sections */}
      <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
        {/* Entry Criteria */}
        <CollapsibleSection title="Entry Criteria" accentColor={SECTION_COLORS.entry}>
          <InlineValue
            label="Min Spread"
            value={config.trading.min_spread}
            onChange={(v) => updateField('trading', 'min_spread', v)}
            accentColor={SECTION_COLORS.entry}
          />
          <InlineValue
            label="Min Profit"
            value={config.trading.min_net_profit}
            onChange={(v) => updateField('trading', 'min_net_profit', v)}
            accentColor={SECTION_COLORS.entry}
          />
          <InlineValue
            label="Max Price"
            value={config.lag_arb.max_combined_price}
            onChange={(v) => updateField('lag_arb', 'max_combined_price', v)}
            accentColor={SECTION_COLORS.entry}
          />
        </CollapsibleSection>

        {/* Position Sizing */}
        <CollapsibleSection title="Position Sizing" accentColor={SECTION_COLORS.position}>
          <InlineValue
            label="Max Size"
            value={config.trading.max_position_size}
            onChange={(v) => updateField('trading', 'max_position_size', v)}
            suffix="$"
            accentColor={SECTION_COLORS.position}
          />
          <InlineValue
            label="Exposure"
            value={config.risk.max_total_exposure}
            onChange={(v) => updateField('risk', 'max_total_exposure', v)}
            suffix="$"
            accentColor={SECTION_COLORS.position}
          />
          <InlineValue
            label="Fee Rate"
            value={config.trading.fee_rate}
            onChange={(v) => updateField('trading', 'fee_rate', v)}
            accentColor={SECTION_COLORS.position}
          />
        </CollapsibleSection>

        {/* Timing & Windows */}
        <CollapsibleSection title="Timing & Windows" accentColor={SECTION_COLORS.timing}>
          <InlineValue
            label="Hold Max"
            value={config.lag_arb.max_hold_time_sec}
            onChange={(v) => updateField('lag_arb', 'max_hold_time_sec', v)}
            suffix="s"
            accentColor={SECTION_COLORS.timing}
          />
          <InlineValue
            label="Lag Window"
            value={config.lag_arb.max_lag_window_ms}
            onChange={(v) => updateField('lag_arb', 'max_lag_window_ms', v)}
            suffix="ms"
            accentColor={SECTION_COLORS.timing}
          />
          <InlineValue
            label="Expected Lag"
            value={config.lag_arb.expected_lag_ms}
            onChange={(v) => updateField('lag_arb', 'expected_lag_ms', v)}
            suffix="ms"
            accentColor={SECTION_COLORS.timing}
          />
          <InlineValue
            label="Momentum Window"
            value={config.lag_arb.spot_momentum_window_sec}
            onChange={(v) => updateField('lag_arb', 'spot_momentum_window_sec', v)}
            suffix="s"
            accentColor={SECTION_COLORS.timing}
          />
          <InlineValue
            label="Refresh"
            value={config.polling.market_refresh_interval}
            onChange={(v) => updateField('polling', 'market_refresh_interval', v)}
            suffix="s"
            accentColor={SECTION_COLORS.timing}
          />
        </CollapsibleSection>

        {/* Risk Management */}
        <CollapsibleSection title="Risk Management" accentColor={SECTION_COLORS.risk}>
          <InlineValue
            label="Max Losses"
            value={config.risk.max_consecutive_losses}
            onChange={(v) => updateField('risk', 'max_consecutive_losses', v)}
            accentColor={SECTION_COLORS.risk}
          />
          <InlineValue
            label="Daily Loss"
            value={config.risk.max_daily_loss_usd}
            onChange={(v) => updateField('risk', 'max_daily_loss_usd', v)}
            suffix="$"
            accentColor={SECTION_COLORS.risk}
          />
          <InlineValue
            label="Cooldown"
            value={config.risk.cooldown_after_loss_sec}
            onChange={(v) => updateField('risk', 'cooldown_after_loss_sec', v)}
            suffix="s"
            accentColor={SECTION_COLORS.risk}
          />
        </CollapsibleSection>

        {/* Momentum Triggers */}
        <CollapsibleSection
          title="Momentum Triggers"
          accentColor={SECTION_COLORS.momentum}
          defaultOpen={false}
        >
          <InlineValue
            label="Trigger Threshold"
            value={config.lag_arb.momentum_trigger_threshold_pct}
            onChange={(v) => updateField('lag_arb', 'momentum_trigger_threshold_pct', v)}
            suffix="%"
            accentColor={SECTION_COLORS.momentum}
          />
          <InlineValue
            label="Spot Move Threshold"
            value={config.lag_arb.spot_move_threshold_pct}
            onChange={(v) => updateField('lag_arb', 'spot_move_threshold_pct', v)}
            suffix="%"
            accentColor={SECTION_COLORS.momentum}
          />
          <InlineValue
            label="Pump Exit"
            value={config.lag_arb.pump_exit_threshold_pct}
            onChange={(v) => updateField('lag_arb', 'pump_exit_threshold_pct', v)}
            suffix="%"
            accentColor={SECTION_COLORS.momentum}
          />
        </CollapsibleSection>

        {/* Market Filters */}
        <CollapsibleSection
          title="Market Filters"
          accentColor={SECTION_COLORS.filters}
          defaultOpen={false}
        >
          <InlineValue
            label="Min Volume (24h)"
            value={config.filters.min_volume_24h}
            onChange={(v) => updateField('filters', 'min_volume_24h', v)}
            suffix="$"
            accentColor={SECTION_COLORS.filters}
          />
          <InlineValue
            label="Min Liquidity"
            value={config.filters.min_liquidity_usd}
            onChange={(v) => updateField('filters', 'min_liquidity_usd', v)}
            suffix="$"
            accentColor={SECTION_COLORS.filters}
          />
          <InlineValue
            label="Min Book Depth"
            value={config.filters.min_book_depth}
            onChange={(v) => updateField('filters', 'min_book_depth', v)}
            suffix="$"
            accentColor={SECTION_COLORS.filters}
          />
          <InlineValue
            label="Max Spread"
            value={config.filters.max_spread_pct}
            onChange={(v) => updateField('filters', 'max_spread_pct', v)}
            suffix="%"
            accentColor={SECTION_COLORS.filters}
          />
          <InlineValue
            label="Max Age"
            value={config.filters.max_market_age_hours}
            onChange={(v) => updateField('filters', 'max_market_age_hours', v)}
            suffix="h"
            accentColor={SECTION_COLORS.filters}
          />
        </CollapsibleSection>
      </div>
    </div>
  );
}
