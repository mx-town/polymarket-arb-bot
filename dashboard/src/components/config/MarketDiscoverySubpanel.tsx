import {
  SubpanelCard,
  SegmentedControl,
  MultiSelectDropdown,
  InlineValue,
  SECTION_COLORS,
  type SubpanelProps,
} from './shared';

const TIME_WINDOWS = [
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '1h', label: '1h' },
];

const MARKET_TYPES = [
  { value: 'btc-updown', label: 'BTC' },
  { value: 'eth-updown', label: 'ETH' },
];

export function MarketDiscoverySubpanel({ config, onChange }: SubpanelProps) {
  return (
    <SubpanelCard title="Market Discovery" accentColor={SECTION_COLORS.discovery}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {/* Primary selectors row */}
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <MultiSelectDropdown
            values={config.filters.market_types}
            options={MARKET_TYPES}
            onChange={(v) => onChange('filters', 'market_types', v)}
            label="Markets"
          />
          <div>
            <SegmentedControl
              value={config.lag_arb.candle_interval}
              options={TIME_WINDOWS}
              onChange={(v) => onChange('lag_arb', 'candle_interval', v)}
              label="Candle"
            />
            <div
              style={{
                fontSize: '0.625rem',
                color:
                  config.lag_arb.candle_interval === '1h'
                    ? 'var(--accent-green)'
                    : 'var(--accent-amber)',
                marginTop: '0.25rem',
                textAlign: 'center',
              }}
            >
              Fee: {config.lag_arb.candle_interval === '1h' ? '0%' : '~3%'}
            </div>
          </div>
        </div>

        {/* Divider */}
        <div style={{ borderTop: '1px solid var(--border-subtle)', margin: '0.25rem 0' }} />

        {/* Filter values */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>
          <InlineValue
            label="Refresh Interval"
            value={config.polling.market_refresh_interval}
            onChange={(v) => onChange('polling', 'market_refresh_interval', v)}
            suffix="s"
            accentColor={SECTION_COLORS.discovery}
          />
          <InlineValue
            label="Max Market Age"
            value={config.filters.max_market_age_hours}
            onChange={(v) => onChange('filters', 'max_market_age_hours', v)}
            suffix="h"
            accentColor={SECTION_COLORS.discovery}
          />
          <InlineValue
            label="Fallback Age"
            value={config.filters.fallback_age_hours}
            onChange={(v) => onChange('filters', 'fallback_age_hours', v)}
            suffix="h"
            accentColor={SECTION_COLORS.discovery}
          />
          <InlineValue
            label="Min Volume (24h)"
            value={config.filters.min_volume_24h}
            onChange={(v) => onChange('filters', 'min_volume_24h', v)}
            suffix="$"
            accentColor={SECTION_COLORS.discovery}
          />
          <InlineValue
            label="Min Liquidity"
            value={config.filters.min_liquidity_usd}
            onChange={(v) => onChange('filters', 'min_liquidity_usd', v)}
            suffix="$"
            accentColor={SECTION_COLORS.discovery}
          />
          <InlineValue
            label="Min Book Depth"
            value={config.filters.min_book_depth}
            onChange={(v) => onChange('filters', 'min_book_depth', v)}
            suffix="$"
            accentColor={SECTION_COLORS.discovery}
          />
          <InlineValue
            label="Max Spread"
            value={config.filters.max_spread_pct}
            onChange={(v) => onChange('filters', 'max_spread_pct', v)}
            suffix="%"
            accentColor={SECTION_COLORS.discovery}
          />
        </div>
      </div>
    </SubpanelCard>
  );
}
