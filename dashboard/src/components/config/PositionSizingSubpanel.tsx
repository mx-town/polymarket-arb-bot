import { SubpanelCard, InlineValue, SECTION_COLORS, type SubpanelProps } from './shared';

export function PositionSizingSubpanel({ config, onChange }: SubpanelProps) {
  const isZeroFee = config.lag_arb.candle_interval === '1h';

  return (
    <SubpanelCard title="Position Sizing" accentColor={SECTION_COLORS.position}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>
        <InlineValue
          label="Max Position Size"
          value={config.trading.max_position_size}
          onChange={(v) => onChange('trading', 'max_position_size', v)}
          suffix="$"
          accentColor={SECTION_COLORS.position}
        />
        <InlineValue
          label="Max Total Exposure"
          value={config.risk.max_total_exposure}
          onChange={(v) => onChange('risk', 'max_total_exposure', v)}
          suffix="$"
          accentColor={SECTION_COLORS.position}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div style={{ flex: 1 }}>
            <InlineValue
              label="Fee Rate"
              value={config.trading.fee_rate}
              onChange={(v) => onChange('trading', 'fee_rate', v)}
              accentColor={SECTION_COLORS.position}
            />
          </div>
          {isZeroFee && (
            <span
              style={{
                fontSize: '0.5625rem',
                padding: '0.125rem 0.375rem',
                background: 'var(--accent-green-dim)',
                color: 'var(--accent-green)',
                borderRadius: '9999px',
                fontWeight: 600,
                letterSpacing: '0.05em',
              }}
            >
              0% ON 1H
            </span>
          )}
        </div>
      </div>
    </SubpanelCard>
  );
}
