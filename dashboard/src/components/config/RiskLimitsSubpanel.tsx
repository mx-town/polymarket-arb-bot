import { SubpanelCard, InlineValue, SECTION_COLORS, type SubpanelProps } from './shared';

export function RiskLimitsSubpanel({ config, onChange }: SubpanelProps) {
  return (
    <SubpanelCard title="Risk Limits" accentColor={SECTION_COLORS.risk}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>
        <InlineValue
          label="Max Consecutive Losses"
          value={config.risk.max_consecutive_losses}
          onChange={(v) => onChange('risk', 'max_consecutive_losses', v)}
          accentColor={SECTION_COLORS.risk}
        />
        <InlineValue
          label="Max Daily Loss"
          value={config.risk.max_daily_loss_usd}
          onChange={(v) => onChange('risk', 'max_daily_loss_usd', v)}
          suffix="$"
          accentColor={SECTION_COLORS.risk}
        />
        <InlineValue
          label="Cooldown After Loss"
          value={config.risk.cooldown_after_loss_sec}
          onChange={(v) => onChange('risk', 'cooldown_after_loss_sec', v)}
          suffix="s"
          accentColor={SECTION_COLORS.risk}
        />
      </div>
    </SubpanelCard>
  );
}
