import { create } from "zustand";
import type { SessionSummary, SessionDetail } from "@/lib/types";

type SessionMode = "picker" | "live" | "replay";

interface SessionState {
  mode: SessionMode;
  activeSessionId: string | null;
  sessions: SessionSummary[];
  replayData: SessionDetail | null;
}

interface SessionActions {
  setMode: (mode: SessionMode) => void;
  setSessions: (sessions: SessionSummary[]) => void;
  startReplay: (sessionId: string, data: SessionDetail) => void;
  goLive: () => void;
  goToPicker: () => void;
}

export const useSessionStore = create<SessionState & SessionActions>((set) => ({
  mode: "picker",
  activeSessionId: null,
  sessions: [],
  replayData: null,

  setMode: (mode) => set({ mode }),

  setSessions: (sessions) => set({ sessions }),

  startReplay: (sessionId, data) =>
    set({
      mode: "replay",
      activeSessionId: sessionId,
      replayData: data,
    }),

  goLive: () =>
    set({
      mode: "live",
      activeSessionId: null,
      replayData: null,
    }),

  goToPicker: () =>
    set({
      mode: "picker",
      activeSessionId: null,
      replayData: null,
    }),
}));
