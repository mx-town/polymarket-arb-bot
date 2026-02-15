"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSessionStore } from "@/stores/session-store";
import { fetchSessions, fetchSessionDetail } from "@/lib/api";
import { cn, formatUsd, formatCountdown } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";
import type { SessionSummary } from "@/lib/types";

function formatDateTime(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatDuration(startedAt: number, endedAt: number | null): string {
  const end = endedAt ?? Date.now() / 1000;
  const seconds = Math.max(0, Math.floor(end - startedAt));
  if (seconds >= 3600) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${h}h ${m}m`;
  }
  const m = Math.floor(seconds / 60);
  return `${m}m`;
}

export default function SessionsPage() {
  const router = useRouter();
  const { setSessions, startReplay, goLive } = useSessionStore();
  const [sessions, setLocalSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  useEffect(() => {
    fetchSessions(50)
      .then((data) => {
        setLocalSessions(data);
        setSessions(data);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [setSessions]);

  const handleReplay = async (session: SessionSummary) => {
    setLoadingId(session.id);
    try {
      const detail = await fetchSessionDetail(session.id);
      startReplay(session.id, detail);
      router.push("/overview");
    } catch {
      setLoadingId(null);
    }
  };

  const handleLive = () => {
    goLive();
    router.push("/overview");
  };

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="text-center">
          <div className="mx-auto mb-4 h-3 w-3 animate-pulse rounded-full bg-accent-blue" />
          <p className="text-sm text-text-secondary">Loading sessions...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Sessions</h1>
          <p className="mt-1 text-sm text-text-secondary">
            Browse past sessions or connect to the live bot
          </p>
        </div>
        <button
          type="button"
          onClick={handleLive}
          className="rounded-md bg-accent-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-blue/80"
        >
          Connect to Live Bot
        </button>
      </div>

      {sessions.length === 0 ? (
        <div className="flex h-48 items-center justify-center rounded-lg border border-border-primary bg-bg-secondary">
          <p className="text-sm text-text-muted">
            No sessions recorded yet. Start the bot to create a session.
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          {sessions.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => handleReplay(s)}
              disabled={loadingId === s.id}
              className={cn(
                "flex items-center gap-4 rounded-lg border border-border-primary bg-bg-secondary p-4 text-left transition-colors hover:bg-bg-hover",
                loadingId === s.id && "opacity-60",
              )}
            >
              {/* Mode badge + session ID */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Badge variant={s.mode === "live" ? "danger" : "info"}>
                    {s.mode.toUpperCase()}
                  </Badge>
                  <span className="font-mono text-sm text-text-primary">
                    {s.id}
                  </span>
                </div>
                <p className="mt-1 text-xs text-text-muted">
                  {formatDateTime(s.started_at)}
                  {" \u2192 "}
                  {s.ended_at ? formatDateTime(s.ended_at) : "running"}
                  {" \u00b7 "}
                  {formatDuration(s.started_at, s.ended_at)}
                </p>
              </div>

              {/* Stats */}
              <div className="text-right">
                <p className="text-xs text-text-muted">Trades</p>
                <p className="font-mono text-sm text-text-primary">
                  {s.trade_count}
                </p>
              </div>
              <div className="text-right">
                <p className="text-xs text-text-muted">Merges</p>
                <p className="font-mono text-sm text-text-primary">
                  {s.merge_count}
                </p>
              </div>
              <div className="w-24 text-right">
                <p className="text-xs text-text-muted">PnL</p>
                <p
                  className={cn(
                    "font-mono text-sm font-semibold",
                    s.final_pnl === null
                      ? "text-text-muted"
                      : s.final_pnl >= 0
                        ? "text-profit"
                        : "text-loss",
                  )}
                >
                  {s.final_pnl !== null ? formatUsd(s.final_pnl) : "--"}
                </p>
              </div>

              {/* Loading indicator */}
              {loadingId === s.id && (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-accent-blue border-t-transparent" />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
