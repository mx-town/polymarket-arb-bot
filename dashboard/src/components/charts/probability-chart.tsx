"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useBotStore } from "@/stores/bot-store";
import { useChartHistoryStore } from "@/stores/chart-history-store";
import { chartOptions } from "@/lib/chart-config";
import { ChartContainer } from "./chart-container";

export function ProbabilityChart() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const upSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const downSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const currentSlugRef = useRef<string>("");

  const markets = useBotStore((s) => s.markets);

  // Initialize chart
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
    };
  }, []);

  // Update with market data
  useEffect(() => {
    if (!upSeriesRef.current || !downSeriesRef.current || !markets.length)
      return;

    // Track the first active market
    const market = markets[0];
    if (!market) return;

    // Detect market rotation — hydrate from history
    if (market.slug !== currentSlugRef.current) {
      currentSlugRef.current = market.slug;
      const history = useChartHistoryStore.getState().probSeries[market.slug] ?? [];
      upSeriesRef.current.setData(
        history.map((p) => ({ time: p.time as UTCTimestamp, value: p.up_ask * 100 })),
      );
      downSeriesRef.current.setData(
        history.map((p) => ({ time: p.time as UTCTimestamp, value: p.down_ask * 100 })),
      );
    }

    const time = Math.floor(Date.now() / 1000) as UTCTimestamp;

    if (market.up_ask !== null) {
      upSeriesRef.current.update({
        time,
        value: market.up_ask * 100,
      });
    }
    if (market.down_ask !== null) {
      downSeriesRef.current.update({
        time,
        value: market.down_ask * 100,
      });
    }
  }, [markets]);

  return (
    <ChartContainer title="Probability" height={200}>
      <div ref={containerRef} className="h-full w-full" />
    </ChartContainer>
  );
}
