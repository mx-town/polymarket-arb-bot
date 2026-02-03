import { SubpanelCard, InlineValue, SECTION_COLORS, type SubpanelProps } from './shared';

export function EntryConditionsSubpanel({ config, onChange }: SubpanelProps) {
  return (
    <SubpanelCard title="Entry Conditions" accentColor={SECTION_COLORS.entry}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>
        <InlineValue
          label="Max Combined Price"
          value={config.lag_arb.max_combined_price}
          onChange={(v) => onChange('lag_arb', 'max_combined_price', v)}
          accentColor={SECTION_COLORS.entry}
        />
        <InlineValue
          label="Min Spread"
          value={config.trading.min_spread}
          onChange={(v) => onChange('trading', 'min_spread', v)}
          accentColor={SECTION_COLORS.entry}
        />
        <InlineValue
          label="Min Net Profit"
          value={config.trading.min_net_profit}
          onChange={(v) => onChange('trading', 'min_net_profit', v)}
          accentColor={SECTION_COLORS.entry}
        />

        {/* Momentum Triggers */}
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
            Momentum Triggers
          </span>
        </div>
        <InlineValue
          label="Momentum Trigger"
          value={config.lag_arb.momentum_trigger_threshold_pct}
          onChange={(v) => onChange('lag_arb', 'momentum_trigger_threshold_pct', v)}
          suffix="%"
          accentColor="#b366ff"
        />
        <InlineValue
          label="Spot Move Threshold"
          value={config.lag_arb.spot_move_threshold_pct}
          onChange={(v) => onChange('lag_arb', 'spot_move_threshold_pct', v)}
          suffix="%"
          accentColor="#b366ff"
        />
      </div>
    </SubpanelCard>
  );
}
