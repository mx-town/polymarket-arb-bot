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

export function MarketProbabilityChart({ slug }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const upSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const downSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const slugRef = useRef<string>("");
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  const markets = useBotStore((s) => s.markets);
  const allTradeEvents = useBotStore((s) => s.tradeEvents);

  const market = markets.find((m) => m.slug === slug);
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
      rightPriceScale: {
        borderColor: "#30363d",
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
    });

    const upSeries = chart.addSeries(LineSeries, {
      color: "#2dc96f",
      lineWidth: 2,
      title: "UP",
      priceFormat: {
        type: "custom",
        formatter: (p: number) => `${p.toFixed(0)}%`,
      },
    });
    const downSeries = chart.addSeries(LineSeries, {
      color: "#ff4d4d",
      lineWidth: 2,
      title: "DOWN",
      priceFormat: {
        type: "custom",
        formatter: (p: number) => `${p.toFixed(0)}%`,
      },
    });

    chartRef.current = chart;
    upSeriesRef.current = upSeries;
    downSeriesRef.current = downSeries;
    markersRef.current = createSeriesMarkers(upSeries);

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
      upSeriesRef.current = null;
      downSeriesRef.current = null;
      markersRef.current = null;
    };
  }, []);

  // Hydrate from history on slug change (including initial mount)
  useEffect(() => {
    if (slug !== slugRef.current) {
      slugRef.current = slug;
      const history = useChartHistoryStore.getState().probSeries[slug] ?? [];
      upSeriesRef.current?.setData(
        history.map((p) => ({ time: p.time as UTCTimestamp, value: p.up_ask * 100 })),
      );
      downSeriesRef.current?.setData(
        history.map((p) => ({ time: p.time as UTCTimestamp, value: p.down_ask * 100 })),
      );
    }
  }, [slug]);

  // Append data points — fires on every `markets` array change (every tick)
  useEffect(() => {
    if (!upSeriesRef.current || !downSeriesRef.current || !market) return;
    const time = Math.floor(Date.now() / 1000) as UTCTimestamp;
    if (market.up_ask !== null) upSeriesRef.current.update({ time, value: market.up_ask * 100 });
    if (market.down_ask !== null) downSeriesRef.current.update({ time, value: market.down_ask * 100 });
  }, [markets]); // eslint-disable-line react-hooks/exhaustive-deps

  // Update markers
  useEffect(() => {
    if (!markersRef.current) return;
    markersRef.current.setMarkers(buildMarkers(tradeEvents));
  }, [tradeEvents]);

  return <div ref={containerRef} className="h-full w-full" />;
}
