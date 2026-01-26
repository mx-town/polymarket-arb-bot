import { Toggle, SubpanelCard, SECTION_COLORS, type SubpanelProps } from './shared';

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
      </div>
    </SubpanelCard>
  );
}
