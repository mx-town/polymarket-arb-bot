import { useEffect, useState } from 'react';
import type { BotConfig } from '../api/client';
import { getConfig, updateConfig } from '../api/client';
import {
  StrategyModeSubpanel,
  MarketDiscoverySubpanel,
  EntryConditionsSubpanel,
  PositionSizingSubpanel,
  ExitStrategySubpanel,
  RiskLimitsSubpanel,
} from './config';

export function ConfigPanel() {
  const [config, setConfig] = useState<BotConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  useEffect(() => {
    getConfig().then(setConfig).catch(console.error);
  }, []);

  const handleChange = (section: keyof BotConfig, field: string, value: unknown) => {
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
        display: 'flex',
        flexDirection: 'column',
        gap: '0.75rem',
      }}
    >
      {/* Header */}
      <div
        style={{
          background: 'var(--bg-card)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border)',
          padding: '0.625rem 0.75rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
          <span style={{ fontSize: '0.875rem' }}>&#9881;</span>
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
            border: 'none',
            cursor: dirty ? 'pointer' : 'default',
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
            borderRadius: 'var(--radius-sm)',
          }}
        >
          {message.text}
        </div>
      )}

      {/* Strategy Mode - Full width */}
      <StrategyModeSubpanel config={config} onChange={handleChange} />

      {/* Two-column grid for main panels */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: '0.75rem',
        }}
      >
        <MarketDiscoverySubpanel config={config} onChange={handleChange} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <EntryConditionsSubpanel config={config} onChange={handleChange} />
          <PositionSizingSubpanel config={config} onChange={handleChange} />
        </div>
        <ExitStrategySubpanel config={config} onChange={handleChange} />
        <RiskLimitsSubpanel config={config} onChange={handleChange} />
      </div>
    </div>
  );
}
