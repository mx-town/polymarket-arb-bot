import { useEffect, useState } from 'react';
import type { BotConfig } from '../api/client';
import { getConfig, updateConfig } from '../api/client';

// Toggle switch component
function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '0.75rem',
        cursor: 'pointer',
      }}
    >
      <div
        onClick={() => onChange(!checked)}
        style={{
          width: '36px',
          height: '20px',
          borderRadius: '10px',
          background: checked ? 'var(--accent-green)' : 'var(--border)',
          position: 'relative',
          transition: 'background 0.15s',
        }}
      >
        <div
          style={{
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            background: 'white',
            position: 'absolute',
            top: '2px',
            left: checked ? '18px' : '2px',
            transition: 'left 0.15s',
            boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
          }}
        />
      </div>
      <span style={{ fontSize: '0.8125rem', color: 'var(--text-primary)' }}>{label}</span>
    </label>
  );
}

// Inline editable value
function InlineValue({
  label,
  value,
  onChange,
  suffix = '',
  type = 'number',
}: {
  label: string;
  value: string | number;
  onChange: (v: string | number) => void;
  suffix?: string;
  type?: 'number' | 'text';
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
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
        <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', minWidth: '60px' }}>
          {label}
        </span>
        <input
          type={type}
          value={tempValue}
          onChange={(e) => setTempValue(e.target.value)}
          onBlur={handleSave}
          onKeyDown={(e) => e.key === 'Enter' && handleSave()}
          autoFocus
          style={{
            width: '80px',
            padding: '0.25rem 0.375rem',
            fontSize: '0.8125rem',
          }}
        />
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{suffix}</span>
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
        gap: '0.25rem',
        cursor: 'pointer',
        padding: '0.25rem 0',
        borderRadius: 'var(--radius-sm)',
        transition: 'background 0.1s',
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-elevated)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
    >
      <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', minWidth: '60px' }}>
        {label}
      </span>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.8125rem',
          color: 'var(--accent-blue)',
        }}
      >
        {value}
        {suffix}
      </span>
    </div>
  );
}

// Value group
function ValueGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div
        style={{
          fontSize: '0.625rem',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          color: 'var(--text-muted)',
          marginBottom: '0.5rem',
          paddingBottom: '0.25rem',
          borderBottom: '1px solid var(--border-subtle)',
        }}
      >
        {title}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>{children}</div>
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
          padding: '0.75rem 1rem',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--bg-elevated)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span style={{ fontSize: '1rem' }}>⚙</span>
          <span
            style={{
              fontSize: '0.75rem',
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
                fontSize: '0.625rem',
                padding: '0.125rem 0.5rem',
                background: 'var(--accent-amber-dim)',
                color: 'var(--accent-amber)',
                borderRadius: '9999px',
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
            color: dirty ? 'black' : 'var(--text-muted)',
            padding: '0.375rem 0.75rem',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.75rem',
            fontWeight: 600,
          }}
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>

      {/* Message */}
      {message && (
        <div
          style={{
            padding: '0.5rem 1rem',
            background:
              message.type === 'success' ? 'var(--accent-green-dim)' : 'var(--accent-red-dim)',
            color: message.type === 'success' ? 'var(--accent-green)' : 'var(--accent-red)',
            fontSize: '0.75rem',
            borderBottom: '1px solid var(--border)',
          }}
        >
          {message.text}
        </div>
      )}

      {/* Quick Toggles */}
      <div
        style={{
          padding: '1rem',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          gap: '1.5rem',
          flexWrap: 'wrap',
        }}
      >
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

      {/* Config Values Grid */}
      <div
        style={{
          padding: '1rem',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '1.25rem',
        }}
      >
        {/* Entry Thresholds */}
        <ValueGroup title="Entry">
          <InlineValue
            label="Min Spread"
            value={config.trading.min_spread}
            onChange={(v) => updateField('trading', 'min_spread', v)}
          />
          <InlineValue
            label="Min Profit"
            value={config.trading.min_net_profit}
            onChange={(v) => updateField('trading', 'min_net_profit', v)}
          />
          <InlineValue
            label="Max Price"
            value={config.lag_arb.max_combined_price}
            onChange={(v) => updateField('lag_arb', 'max_combined_price', v)}
          />
        </ValueGroup>

        {/* Position */}
        <ValueGroup title="Position">
          <InlineValue
            label="Max Size"
            value={config.trading.max_position_size}
            onChange={(v) => updateField('trading', 'max_position_size', v)}
            suffix="$"
          />
          <InlineValue
            label="Exposure"
            value={config.risk.max_total_exposure}
            onChange={(v) => updateField('risk', 'max_total_exposure', v)}
            suffix="$"
          />
          <InlineValue
            label="Fee Rate"
            value={config.trading.fee_rate}
            onChange={(v) => updateField('trading', 'fee_rate', v)}
          />
        </ValueGroup>

        {/* Timing */}
        <ValueGroup title="Timing">
          <InlineValue
            label="Hold Max"
            value={config.lag_arb.max_hold_time_sec}
            onChange={(v) => updateField('lag_arb', 'max_hold_time_sec', v)}
            suffix="s"
          />
          <InlineValue
            label="Lag Window"
            value={config.lag_arb.max_lag_window_ms}
            onChange={(v) => updateField('lag_arb', 'max_lag_window_ms', v)}
            suffix="ms"
          />
          <InlineValue
            label="Refresh"
            value={config.polling.market_refresh_interval}
            onChange={(v) => updateField('polling', 'market_refresh_interval', v)}
            suffix="s"
          />
        </ValueGroup>

        {/* Risk */}
        <ValueGroup title="Risk">
          <InlineValue
            label="Max Losses"
            value={config.risk.max_consecutive_losses}
            onChange={(v) => updateField('risk', 'max_consecutive_losses', v)}
          />
          <InlineValue
            label="Daily Loss"
            value={config.risk.max_daily_loss_usd}
            onChange={(v) => updateField('risk', 'max_daily_loss_usd', v)}
            suffix="$"
          />
          <InlineValue
            label="Cooldown"
            value={config.risk.cooldown_after_loss_sec}
            onChange={(v) => updateField('risk', 'cooldown_after_loss_sec', v)}
            suffix="s"
          />
        </ValueGroup>

        {/* Momentum */}
        <ValueGroup title="Momentum">
          <InlineValue
            label="Trigger"
            value={config.lag_arb.momentum_trigger_threshold_pct}
            onChange={(v) => updateField('lag_arb', 'momentum_trigger_threshold_pct', v)}
            suffix="%"
          />
          <InlineValue
            label="Move Thr"
            value={config.lag_arb.spot_move_threshold_pct}
            onChange={(v) => updateField('lag_arb', 'spot_move_threshold_pct', v)}
            suffix="%"
          />
          <InlineValue
            label="Pump Exit"
            value={config.lag_arb.pump_exit_threshold_pct}
            onChange={(v) => updateField('lag_arb', 'pump_exit_threshold_pct', v)}
            suffix="%"
          />
        </ValueGroup>

        {/* Filters */}
        <ValueGroup title="Filters">
          <InlineValue
            label="Min Vol"
            value={config.filters.min_volume_24h}
            onChange={(v) => updateField('filters', 'min_volume_24h', v)}
            suffix="$"
          />
          <InlineValue
            label="Min Liq"
            value={config.filters.min_liquidity_usd}
            onChange={(v) => updateField('filters', 'min_liquidity_usd', v)}
            suffix="$"
          />
          <InlineValue
            label="Max Age"
            value={config.filters.max_market_age_hours}
            onChange={(v) => updateField('filters', 'max_market_age_hours', v)}
            suffix="h"
          />
        </ValueGroup>
      </div>
    </div>
  );
}
