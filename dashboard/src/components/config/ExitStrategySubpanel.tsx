import { SubpanelCard, InlineValue, SECTION_COLORS, type SubpanelProps } from './shared';

export function ExitStrategySubpanel({ config, onChange }: SubpanelProps) {
  const isLagArb = config.lag_arb.enabled;

  return (
    <SubpanelCard title="Exit Strategy" accentColor={SECTION_COLORS.exit}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>
        {isLagArb ? (
          <>
            <InlineValue
              label="Max Hold Time"
              value={config.lag_arb.max_hold_time_sec}
              onChange={(v) => onChange('lag_arb', 'max_hold_time_sec', v)}
              suffix="s"
              accentColor={SECTION_COLORS.exit}
            />
            <InlineValue
              label="Pump Exit Threshold"
              value={config.lag_arb.pump_exit_threshold_pct}
              onChange={(v) => onChange('lag_arb', 'pump_exit_threshold_pct', v)}
              suffix="%"
              accentColor={SECTION_COLORS.risk}
            />

            <div
              style={{
                borderTop: '1px solid var(--border-subtle)',
                margin: '0.375rem 0 0.25rem',
                paddingTop: '0.25rem',
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
                Lag Window
              </span>
            </div>
            <InlineValue
              label="Expected Lag"
              value={config.lag_arb.expected_lag_ms}
              onChange={(v) => onChange('lag_arb', 'expected_lag_ms', v)}
              suffix="ms"
              accentColor={SECTION_COLORS.exit}
            />
            <InlineValue
              label="Max Lag Window"
              value={config.lag_arb.max_lag_window_ms}
              onChange={(v) => onChange('lag_arb', 'max_lag_window_ms', v)}
              suffix="ms"
              accentColor={SECTION_COLORS.exit}
            />
            <InlineValue
              label="Momentum Window"
              value={config.lag_arb.spot_momentum_window_sec}
              onChange={(v) => onChange('lag_arb', 'spot_momentum_window_sec', v)}
              suffix="s"
              accentColor={SECTION_COLORS.exit}
            />
          </>
        ) : (
          <>
            <InlineValue
              label="Exit on Pump"
              value={config.conservative.exit_on_pump_threshold}
              onChange={(v) => onChange('conservative', 'exit_on_pump_threshold', v)}
              accentColor={SECTION_COLORS.risk}
            />
            <InlineValue
              label="Min Time to Resolution"
              value={config.conservative.min_time_to_resolution_sec}
              onChange={(v) => onChange('conservative', 'min_time_to_resolution_sec', v)}
              suffix="s"
              accentColor={SECTION_COLORS.exit}
            />
          </>
        )}
      </div>
    </SubpanelCard>
  );
}
