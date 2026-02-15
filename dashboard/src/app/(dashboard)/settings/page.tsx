"use client";

import { useBotStore } from "@/stores/bot-store";
import { cn } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";

// ─── Placeholder API key data ───

const mockApiKeys = [
  {
    id: "1",
    name: "Production Bot",
    prefix: "pk_live_••••3aF9",
    created: "2026-01-15",
    lastUsed: "2026-02-15",
    status: "active" as const,
  },
  {
    id: "2",
    name: "Development",
    prefix: "pk_test_••••x7Qm",
    created: "2026-02-01",
    lastUsed: "2026-02-10",
    status: "active" as const,
  },
  {
    id: "3",
    name: "Old Integration",
    prefix: "pk_live_••••bR2k",
    created: "2025-11-20",
    lastUsed: "2025-12-30",
    status: "revoked" as const,
  },
];

// ─── Section card wrapper ───

function Section({
  title,
  description,
  children,
  danger,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  danger?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border bg-bg-secondary",
        danger ? "border-accent-red/30" : "border-border-primary",
      )}
    >
      <div
        className={cn(
          "border-b px-6 py-4",
          danger ? "border-accent-red/30" : "border-border-primary",
        )}
      >
        <h2
          className={cn(
            "text-sm font-semibold",
            danger ? "text-accent-red" : "text-text-primary",
          )}
        >
          {title}
        </h2>
        {description && (
          <p className="mt-1 text-xs text-text-secondary">{description}</p>
        )}
      </div>
      <div className="px-6 py-4">{children}</div>
    </div>
  );
}

// ─── Config row ───

function ConfigRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm text-text-secondary">{label}</span>
      <span className="font-mono text-sm text-text-primary">{value}</span>
    </div>
  );
}

export default function SettingsPage() {
  const config = useBotStore((s) => s.config);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Settings</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Manage your account and bot configuration
        </p>
      </div>

      {/* ─── Bot Configuration ─── */}
      <Section
        title="Bot Configuration"
        description="Current bot parameters (read-only, configured via config.yaml)"
      >
        {config ? (
          <div className="divide-y divide-border-secondary">
            <ConfigRow
              label="Mode"
              value={
                <Badge variant={config.dry_run ? "warning" : "success"}>
                  {config.dry_run ? "Dry Run" : "Live"}
                </Badge>
              }
            />
            <ConfigRow
              label="Bankroll"
              value={`$${config.bankroll_usd.toFixed(2)}`}
            />
            <ConfigRow
              label="Min Edge"
              value={`${(config.min_edge * 100).toFixed(1)}%`}
            />
            <ConfigRow
              label="Assets"
              value={
                <div className="flex flex-wrap gap-1.5">
                  {config.assets.map((asset) => (
                    <Badge key={asset} variant="info">
                      {asset}
                    </Badge>
                  ))}
                </div>
              }
            />
          </div>
        ) : (
          <p className="text-sm text-text-muted">
            Bot not connected. Configuration will appear when the bot is online.
          </p>
        )}
      </Section>

      {/* ─── API Keys ─── */}
      <Section
        title="API Keys"
        description="Manage API keys for external integrations"
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border-secondary text-xs font-medium uppercase tracking-wider text-text-muted">
                <th className="pb-2 pr-4">Name</th>
                <th className="pb-2 pr-4">Key</th>
                <th className="pb-2 pr-4">Created</th>
                <th className="pb-2 pr-4">Last Used</th>
                <th className="pb-2 pr-4">Status</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border-secondary">
              {mockApiKeys.map((key) => (
                <tr key={key.id}>
                  <td className="py-3 pr-4 text-text-primary">{key.name}</td>
                  <td className="py-3 pr-4 font-mono text-text-secondary">
                    {key.prefix}
                  </td>
                  <td className="py-3 pr-4 text-text-secondary">
                    {key.created}
                  </td>
                  <td className="py-3 pr-4 text-text-secondary">
                    {key.lastUsed}
                  </td>
                  <td className="py-3 pr-4">
                    <Badge
                      variant={key.status === "active" ? "success" : "neutral"}
                    >
                      {key.status}
                    </Badge>
                  </td>
                  <td className="py-3 text-right">
                    {key.status === "active" && (
                      <button
                        type="button"
                        className="text-xs text-accent-red hover:underline"
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-4 border-t border-border-secondary pt-4">
          <button
            type="button"
            className="rounded-md bg-accent-blue px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            Generate New Key
          </button>
        </div>
      </Section>

      {/* ─── Account ─── */}
      <Section title="Account" description="Your account details">
        <div className="divide-y divide-border-secondary">
          <div className="flex items-center justify-between py-3">
            <div>
              <p className="text-sm text-text-secondary">Email</p>
              <p className="text-sm text-text-primary">user@example.com</p>
            </div>
          </div>
          <div className="flex items-center justify-between py-3">
            <div>
              <p className="text-sm text-text-secondary">Password</p>
              <p className="text-xs text-text-muted">
                Last changed 30 days ago
              </p>
            </div>
            <button
              type="button"
              className="rounded-md border border-border-primary bg-bg-tertiary px-3 py-1.5 text-sm text-text-primary transition-colors hover:bg-bg-hover"
            >
              Change Password
            </button>
          </div>
          <div className="flex items-center justify-between py-3">
            <div>
              <p className="text-sm text-text-secondary">Session</p>
              <p className="text-xs text-text-muted">
                Signed in since Feb 15, 2026
              </p>
            </div>
            <button
              type="button"
              className="rounded-md border border-border-primary bg-bg-tertiary px-3 py-1.5 text-sm text-text-primary transition-colors hover:bg-bg-hover"
            >
              Sign Out
            </button>
          </div>
        </div>
      </Section>

      {/* ─── Danger Zone ─── */}
      <Section
        title="Danger Zone"
        description="Irreversible and destructive actions"
        danger
      >
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-text-primary">Delete Account</p>
            <p className="text-xs text-text-secondary">
              Permanently delete your account and all associated data. This
              action cannot be undone.
            </p>
          </div>
          <button
            type="button"
            className="shrink-0 rounded-md border border-accent-red/50 bg-accent-red/10 px-4 py-2 text-sm font-medium text-accent-red transition-colors hover:bg-accent-red/20"
          >
            Delete Account
          </button>
        </div>
      </Section>
    </div>
  );
}
