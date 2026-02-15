"use client";

import { useEffect, useMemo, useRef } from "react";
import {
  createChart,
  createSeriesMarkers,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type UTCTimestamp,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { useBotStore } from "@/stores/bot-store";
import { useChartHistoryStore } from "@/stores/chart-history-store";
import { chartOptions, eventMarkers } from "@/lib/chart-config";

interface Props {
  slug: string;
}

function buildMarkers(events: { type: string; ts: number; data?: { direction?: string; price?: number } }[]): SeriesMarker<Time>[] {
  return events
    .filter((e) => e.ts > 0)
    .sort((a, b) => a.ts - b.ts)
    .map((e) => {
      const evtType = e.type;
      let cfg: { color: string; shape: string; text: string } = eventMarkers.entry;
      let label = "BUY";

      if (evtType === "order_placed" || evtType === "order_submitted") {
        cfg = eventMarkers.entry;
        label = `BUY ${e.data?.direction ?? ""}`;
      } else if (evtType === "order_filled" || evtType === "fill") {
        cfg = eventMarkers.fill;
        label = `FILL ${e.data?.direction ?? ""} @${e.data?.price?.toFixed(2) ?? "?"}`;
      } else if (evtType === "hedge_complete" || evtType === "hedge") {
        cfg = eventMarkers.hedge;
        label = "HEDGED";
      } else if (evtType === "merge_complete" || evtType === "merge") {
        cfg = eventMarkers.merge;
        label = "MERGE";
      }

      return {
        time: e.ts as UTCTimestamp,
        position: "aboveBar",
        color: cfg.color,
        shape: cfg.shape,
        text: label,
      } as SeriesMarker<Time>;
    });
}

export function MarketBtcChart({ slug }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const openLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  const btc = useBotStore((s) => s.btc);
  const allTradeEvents = useBotStore((s) => s.tradeEvents);

  const tradeEvents = useMemo(
    () => allTradeEvents.filter((e) => (e.data?.slug ?? e.slug) === slug),
    [allTradeEvents, slug],
  );

  // Mount chart
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      ...chartOptions,
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    });

    const series = chart.addSeries(LineSeries, {
      color: "#f97316",
      lineWidth: 2,
      title: "BTC",
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });

    const openLine = chart.addSeries(LineSeries, {
      color: "#4a9eff",
      lineWidth: 1,
      lineStyle: 2,
      title: "Open",
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });

    chartRef.current = chart;
    seriesRef.current = series;
    openLineRef.current = openLine;
    markersRef.current = createSeriesMarkers(series);

    const observer = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      openLineRef.current = null;
      markersRef.current = null;
    };
  }, []);

  // Hydrate from history on mount
  useEffect(() => {
    if (!seriesRef.current || !openLineRef.current) return;
    const history = useChartHistoryStore.getState().btcSeries;
    seriesRef.current.setData(
      history.map((p) => ({ time: p.time as UTCTimestamp, value: p.price })),
    );
    openLineRef.current.setData(
      history.map((p) => ({ time: p.time as UTCTimestamp, value: p.open })),
    );
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Append BTC data — fires on every btc store update
  useEffect(() => {
    if (!seriesRef.current || !openLineRef.current || !btc || btc.price === 0) return;
    const time = Math.floor(Date.now() / 1000) as UTCTimestamp;
    seriesRef.current.update({ time, value: btc.price });
    if (btc.open > 0) {
      openLineRef.current.update({ time, value: btc.open });
    }
  }, [btc]);

  // Update markers
  useEffect(() => {
    if (!markersRef.current) return;
    markersRef.current.setMarkers(buildMarkers(tradeEvents));
  }, [tradeEvents]);

  return <div ref={containerRef} className="h-full w-full" />;
}
