"use client";

import { useEffect, useRef, useCallback } from "react";
import { useBotStore } from "@/stores/bot-store";
import type { WsMessage, StateSnapshot, TickSnapshot, BtcPriceData, TradeEvent } from "@/lib/types";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/live";
const PING_INTERVAL_MS = 15_000;
const MAX_BACKOFF_MS = 30_000;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(1_000);
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const {
    setConnected,
    updateFromSnapshot,
    updateTick,
    updateBtc,
    addTradeEvent,
  } = useBotStore();

  const clearTimers = useCallback(() => {
    if (pingRef.current) {
      clearInterval(pingRef.current);
      pingRef.current = null;
    }
    if (reconnectRef.current) {
      clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      backoffRef.current = 1_000;

      // Start keepalive pings
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, PING_INTERVAL_MS);
    };

    ws.onmessage = (event) => {
      let msg: WsMessage;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }

      switch (msg.type) {
        case "initial_state":
          updateFromSnapshot(msg.data as StateSnapshot);
          break;
        case "tick_snapshot":
          updateTick(msg as unknown as TickSnapshot);
          break;
        case "btc_price":
          updateBtc(msg.data as BtcPriceData);
          break;
        case "pong":
          // Keepalive response, nothing to do
          break;
        default:
          // Trade events: entry, fill, hedge, merge, reduce, abandon, etc.
          if (msg.data?.slug) {
            addTradeEvent(msg as unknown as TradeEvent);
          }
          break;
      }
    };

    ws.onclose = () => {
      setConnected(false);
      clearTimers();

      // Exponential backoff reconnect
      const delay = backoffRef.current;
      backoffRef.current = Math.min(delay * 2, MAX_BACKOFF_MS);
      reconnectRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // onclose will fire after onerror, triggering reconnect
      ws.close();
    };
  }, [setConnected, updateFromSnapshot, updateTick, updateBtc, addTradeEvent, clearTimers]);

  useEffect(() => {
    connect();

    return () => {
      clearTimers();
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent reconnect on intentional close
        wsRef.current.close();
        wsRef.current = null;
      }
      setConnected(false);
    };
  }, [connect, clearTimers, setConnected]);
}
