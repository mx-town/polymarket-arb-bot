import { useEffect, useState } from 'react';
import type { BotConfig } from '../api/client';
import { getConfig, updateConfig } from '../api/client';

interface SectionProps {
  title: string;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

function Section({ title, expanded, onToggle, children }: SectionProps) {
  return (
    <div style={{
      background: '#16213e',
      borderRadius: '8px',
      marginBottom: '0.5rem',
    }}>
      <button
        onClick={onToggle}
        style={{
          width: '100%',
          padding: '0.75rem 1rem',
          background: 'transparent',
          border: 'none',
          color: 'white',
          textAlign: 'left',
          cursor: 'pointer',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontWeight: 'bold',
        }}
      >
        {title}
        <span>{expanded ? '▼' : '▶'}</span>
      </button>
      {expanded && (
        <div style={{ padding: '0 1rem 1rem 1rem' }}>
          {children}
        </div>
      )}
    </div>
  );
}

interface FieldProps {
  label: string;
  value: unknown;
  onChange: (value: unknown) => void;
  type?: 'number' | 'boolean' | 'string' | 'array';
}

function Field({ label, value, onChange, type = 'string' }: FieldProps) {
  if (type === 'boolean') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '0.5rem' }}>
        <input
          type="checkbox"
          checked={value as boolean}
          onChange={(e) => onChange(e.target.checked)}
          style={{ marginRight: '0.5rem' }}
        />
        <label style={{ fontSize: '0.9rem' }}>{label}</label>
      </div>
    );
  }

  if (type === 'array') {
    return (
      <div style={{ marginBottom: '0.5rem' }}>
        <label style={{ fontSize: '0.8rem', color: '#888' }}>{label}</label>
        <input
          type="text"
          value={(value as string[]).join(', ')}
          onChange={(e) => onChange(e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
          style={{
            width: '100%',
            padding: '0.5rem',
            background: '#0f0f1a',
            border: '1px solid #333',
            borderRadius: '4px',
            color: 'white',
            marginTop: '0.25rem',
          }}
        />
      </div>
    );
  }

  return (
    <div style={{ marginBottom: '0.5rem' }}>
      <label style={{ fontSize: '0.8rem', color: '#888' }}>{label}</label>
      <input
        type={type === 'number' ? 'number' : 'text'}
        value={value as string | number}
        onChange={(e) => onChange(type === 'number' ? parseFloat(e.target.value) : e.target.value)}
        step={type === 'number' ? 'any' : undefined}
        style={{
          width: '100%',
          padding: '0.5rem',
          background: '#0f0f1a',
          border: '1px solid #333',
          borderRadius: '4px',
          color: 'white',
          marginTop: '0.25rem',
        }}
      />
    </div>
  );
}

export function ConfigPanel() {
  const [config, setConfig] = useState<BotConfig | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['trading']));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    getConfig().then(setConfig).catch(console.error);
  }, []);

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      return next;
    });
  };

  const updateField = (section: keyof BotConfig, field: string, value: unknown) => {
    if (!config) return;
    setConfig({
      ...config,
      [section]: {
        ...config[section],
        [field]: value,
      },
    });
  };

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    setMessage(null);
    try {
      await updateConfig(config);
      setMessage('Configuration saved! Restart the bot to apply changes.');
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (!config) {
    return <div>Loading configuration...</div>;
  }

  return (
    <div style={{
      background: '#1a1a2e',
      padding: '1.5rem',
      borderRadius: '8px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h2 style={{ margin: 0 }}>Configuration</h2>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            background: '#4ecdc4',
            border: 'none',
            color: '#0f0f1a',
            padding: '0.5rem 1rem',
            borderRadius: '4px',
            cursor: saving ? 'not-allowed' : 'pointer',
            fontWeight: 'bold',
          }}
        >
          {saving ? 'Saving...' : 'Save Config'}
        </button>
      </div>

      {message && (
        <p style={{
          padding: '0.5rem',
          background: '#16213e',
          borderRadius: '4px',
          fontSize: '0.9rem',
          marginBottom: '1rem',
        }}>
          {message}
        </p>
      )}

      <Section title="Trading" expanded={expandedSections.has('trading')} onToggle={() => toggleSection('trading')}>
        <Field label="Dry Run" value={config.trading.dry_run} onChange={(v) => updateField('trading', 'dry_run', v)} type="boolean" />
        <Field label="Min Spread" value={config.trading.min_spread} onChange={(v) => updateField('trading', 'min_spread', v)} type="number" />
        <Field label="Min Net Profit" value={config.trading.min_net_profit} onChange={(v) => updateField('trading', 'min_net_profit', v)} type="number" />
        <Field label="Max Position Size" value={config.trading.max_position_size} onChange={(v) => updateField('trading', 'max_position_size', v)} type="number" />
        <Field label="Fee Rate" value={config.trading.fee_rate} onChange={(v) => updateField('trading', 'fee_rate', v)} type="number" />
      </Section>

      <Section title="Polling" expanded={expandedSections.has('polling')} onToggle={() => toggleSection('polling')}>
        <Field label="Interval" value={config.polling.interval} onChange={(v) => updateField('polling', 'interval', v)} type="number" />
        <Field label="Batch Size" value={config.polling.batch_size} onChange={(v) => updateField('polling', 'batch_size', v)} type="number" />
        <Field label="Max Markets" value={config.polling.max_markets} onChange={(v) => updateField('polling', 'max_markets', v)} type="number" />
        <Field label="Refresh Interval" value={config.polling.market_refresh_interval} onChange={(v) => updateField('polling', 'market_refresh_interval', v)} type="number" />
      </Section>

      <Section title="WebSocket" expanded={expandedSections.has('websocket')} onToggle={() => toggleSection('websocket')}>
        <Field label="Ping Interval" value={config.websocket.ping_interval} onChange={(v) => updateField('websocket', 'ping_interval', v)} type="number" />
        <Field label="Reconnect Delay" value={config.websocket.reconnect_delay} onChange={(v) => updateField('websocket', 'reconnect_delay', v)} type="number" />
      </Section>

      <Section title="Conservative Strategy" expanded={expandedSections.has('conservative')} onToggle={() => toggleSection('conservative')}>
        <Field label="Max Combined Price" value={config.conservative.max_combined_price} onChange={(v) => updateField('conservative', 'max_combined_price', v)} type="number" />
        <Field label="Min Time to Resolution (sec)" value={config.conservative.min_time_to_resolution_sec} onChange={(v) => updateField('conservative', 'min_time_to_resolution_sec', v)} type="number" />
        <Field label="Exit on Pump Threshold" value={config.conservative.exit_on_pump_threshold} onChange={(v) => updateField('conservative', 'exit_on_pump_threshold', v)} type="number" />
      </Section>

      <Section title="Lag Arb Strategy" expanded={expandedSections.has('lag_arb')} onToggle={() => toggleSection('lag_arb')}>
        <Field label="Enabled" value={config.lag_arb.enabled} onChange={(v) => updateField('lag_arb', 'enabled', v)} type="boolean" />
        <Field label="Candle Interval" value={config.lag_arb.candle_interval} onChange={(v) => updateField('lag_arb', 'candle_interval', v)} type="string" />
        <Field label="Momentum Window (sec)" value={config.lag_arb.spot_momentum_window_sec} onChange={(v) => updateField('lag_arb', 'spot_momentum_window_sec', v)} type="number" />
        <Field label="Move Threshold %" value={config.lag_arb.spot_move_threshold_pct} onChange={(v) => updateField('lag_arb', 'spot_move_threshold_pct', v)} type="number" />
        <Field label="Max Combined Price" value={config.lag_arb.max_combined_price} onChange={(v) => updateField('lag_arb', 'max_combined_price', v)} type="number" />
        <Field label="Expected Lag (ms)" value={config.lag_arb.expected_lag_ms} onChange={(v) => updateField('lag_arb', 'expected_lag_ms', v)} type="number" />
        <Field label="Max Lag Window (ms)" value={config.lag_arb.max_lag_window_ms} onChange={(v) => updateField('lag_arb', 'max_lag_window_ms', v)} type="number" />
        <Field label="Fee Rate" value={config.lag_arb.fee_rate} onChange={(v) => updateField('lag_arb', 'fee_rate', v)} type="number" />
        <Field label="Momentum Trigger %" value={config.lag_arb.momentum_trigger_threshold_pct} onChange={(v) => updateField('lag_arb', 'momentum_trigger_threshold_pct', v)} type="number" />
        <Field label="Pump Exit %" value={config.lag_arb.pump_exit_threshold_pct} onChange={(v) => updateField('lag_arb', 'pump_exit_threshold_pct', v)} type="number" />
        <Field label="Max Hold Time (sec)" value={config.lag_arb.max_hold_time_sec} onChange={(v) => updateField('lag_arb', 'max_hold_time_sec', v)} type="number" />
      </Section>

      <Section title="Risk" expanded={expandedSections.has('risk')} onToggle={() => toggleSection('risk')}>
        <Field label="Max Consecutive Losses" value={config.risk.max_consecutive_losses} onChange={(v) => updateField('risk', 'max_consecutive_losses', v)} type="number" />
        <Field label="Max Daily Loss (USD)" value={config.risk.max_daily_loss_usd} onChange={(v) => updateField('risk', 'max_daily_loss_usd', v)} type="number" />
        <Field label="Cooldown After Loss (sec)" value={config.risk.cooldown_after_loss_sec} onChange={(v) => updateField('risk', 'cooldown_after_loss_sec', v)} type="number" />
        <Field label="Max Total Exposure" value={config.risk.max_total_exposure} onChange={(v) => updateField('risk', 'max_total_exposure', v)} type="number" />
      </Section>

      <Section title="Filters" expanded={expandedSections.has('filters')} onToggle={() => toggleSection('filters')}>
        <Field label="Min Liquidity (USD)" value={config.filters.min_liquidity_usd} onChange={(v) => updateField('filters', 'min_liquidity_usd', v)} type="number" />
        <Field label="Min Book Depth" value={config.filters.min_book_depth} onChange={(v) => updateField('filters', 'min_book_depth', v)} type="number" />
        <Field label="Max Spread %" value={config.filters.max_spread_pct} onChange={(v) => updateField('filters', 'max_spread_pct', v)} type="number" />
        <Field label="Max Market Age (hours)" value={config.filters.max_market_age_hours} onChange={(v) => updateField('filters', 'max_market_age_hours', v)} type="number" />
        <Field label="Fallback Age (hours)" value={config.filters.fallback_age_hours} onChange={(v) => updateField('filters', 'fallback_age_hours', v)} type="number" />
        <Field label="Min 24h Volume" value={config.filters.min_volume_24h} onChange={(v) => updateField('filters', 'min_volume_24h', v)} type="number" />
        <Field label="Market Types" value={config.filters.market_types} onChange={(v) => updateField('filters', 'market_types', v)} type="array" />
      </Section>
    </div>
  );
}
