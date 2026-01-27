import { Toggle, SubpanelCard, InlineValue, SECTION_COLORS, type SubpanelProps } from './shared';

export function StrategyModeSubpanel({ config, onChange }: SubpanelProps) {
  return (
    <SubpanelCard title="Strategy Mode" accentColor={SECTION_COLORS.mode}>
      <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
        <Toggle
          checked={config.trading.dry_run}
          onChange={(v) => onChange('trading', 'dry_run', v)}
          label="Dry Run"
          activeColor="var(--accent-amber)"
        />
        <Toggle
          checked={config.lag_arb.enabled}
          onChange={(v) => onChange('lag_arb', 'enabled', v)}
          label="Lag Arb"
          activeColor="var(--accent-green)"
        />
        <Toggle
          checked={config.pure_arb?.enabled ?? false}
          onChange={(v) => onChange('pure_arb', 'enabled', v)}
          label="Pure Arb"
          activeColor="var(--accent-blue)"
        />
      </div>

      {/* Pure Arb settings */}
      {config.pure_arb?.enabled && (
        <div style={{ marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid var(--border-subtle)' }}>
          <span style={{ fontSize: '0.5625rem', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--text-muted)', marginBottom: '0.5rem', display: 'block' }}>
            Pure Arb (no momentum)
          </span>
          <InlineValue
            label="Max Combined"
            value={config.pure_arb.max_combined_price}
            onChange={(v) => onChange('pure_arb', 'max_combined_price', v)}
            accentColor="var(--accent-blue)"
          />
        </div>
      )}
    </SubpanelCard>
  );
}
