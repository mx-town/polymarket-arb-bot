"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
  ColorType,
  CrosshairMode,
  LineStyle,
} from "lightweight-charts";
import { useBotStore } from "@/stores/bot-store";
import { chartOptions, candlestickSeriesOptions } from "@/lib/chart-config";
import { ChartContainer } from "./chart-container";

interface CandleData {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
}

export function BtcCandleChart() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lastCandleTimeRef = useRef<number>(0);

  const btc = useBotStore((s) => s.btc);
  const tradeEvents = useBotStore((s) => s.tradeEvents);

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      ...chartOptions,
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    });

    const series = chart.addSeries(CandlestickSeries, candlestickSeriesOptions);

    chartRef.current = chart;
    seriesRef.current = series;

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    };

    const observer = new ResizeObserver(handleResize);
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Update with live BTC data
  useEffect(() => {
    if (!seriesRef.current || !btc || btc.price === 0) return;

    const now = Math.floor(Date.now() / 1000);
    // Align to 60s boundary for 1m candles
    const candleTime = (now - (now % 60)) as UTCTimestamp;

    if (candleTime === lastCandleTimeRef.current) {
      // Update current candle
      seriesRef.current.update({
        time: candleTime,
        open: btc.open || btc.price,
        high: Math.max(btc.high || btc.price, btc.price),
        low: Math.min(btc.low || btc.price, btc.price),
        close: btc.price,
      });
    } else {
      // New candle
      lastCandleTimeRef.current = candleTime;
      seriesRef.current.update({
        time: candleTime,
        open: btc.price,
        high: btc.price,
        low: btc.price,
        close: btc.price,
      });
    }
  }, [btc]);

  return (
    <ChartContainer title="BTC/USD" height={350}>
      <div ref={containerRef} className="h-full w-full" />
    </ChartContainer>
  );
}
