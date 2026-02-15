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
import { chartOptions } from "@/lib/chart-config";
import { ChartContainer } from "./chart-container";

export function PnlChart() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const realizedRef = useRef<ISeriesApi<"Line"> | null>(null);
  const unrealizedRef = useRef<ISeriesApi<"Line"> | null>(null);
  const totalRef = useRef<ISeriesApi<"Line"> | null>(null);

  const pnl = useBotStore((s) => s.pnl);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      ...chartOptions,
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      rightPriceScale: {
        borderColor: "#30363d",
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
    });

    const realized = chart.addSeries(LineSeries, {
      color: "#2dc96f",
      lineWidth: 1,
      title: "Realized",
    });

    const unrealized = chart.addSeries(LineSeries, {
      color: "#fbbf24",
      lineWidth: 1,
      lineStyle: 2,
      title: "Unrealized",
    });

    const total = chart.addSeries(LineSeries, {
      color: "#4a9eff",
      lineWidth: 2,
      title: "Total",
    });

    chartRef.current = chart;
    realizedRef.current = realized;
    unrealizedRef.current = unrealized;
    totalRef.current = total;

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
    };
  }, []);

  useEffect(() => {
    if (!realizedRef.current || !pnl) return;
    const time = Math.floor(Date.now() / 1000) as UTCTimestamp;

    realizedRef.current.update({ time, value: pnl.realized });
    unrealizedRef.current?.update({ time, value: pnl.unrealized });
    totalRef.current?.update({ time, value: pnl.total });
  }, [pnl]);

  return (
    <ChartContainer title="P&L Trajectory" height={200}>
      <div ref={containerRef} className="h-full w-full" />
    </ChartContainer>
  );
}
