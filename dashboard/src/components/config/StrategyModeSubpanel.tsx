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
      </div>
      <div
        style={{
          marginTop: '0.75rem',
          paddingTop: '0.75rem',
          borderTop: '1px solid var(--border-subtle)',
        }}
      >
        <span
          style={{
            fontSize: '0.5625rem',
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            color: 'var(--text-muted)',
            display: 'block',
          }}
        >
          Strategy: Lag Arbitrage (momentum-first)
        </span>
      </div>
    </SubpanelCard>
  );
}
