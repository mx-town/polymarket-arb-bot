"use client";
import dynamic from "next/dynamic";
import { ChartSkeleton } from "@/components/ui/Skeleton";

export const LazyBtcCandleChart = dynamic(
  () => import("./btc-candle-chart").then((m) => ({ default: m.BtcCandleChart })),
  { loading: () => <ChartSkeleton height={350} />, ssr: false }
);

export const LazyProbabilityChart = dynamic(
  () => import("./probability-chart").then((m) => ({ default: m.ProbabilityChart })),
  { loading: () => <ChartSkeleton height={200} />, ssr: false }
);

export const LazyPnlChart = dynamic(
  () => import("./pnl-chart").then((m) => ({ default: m.PnlChart })),
  { loading: () => <ChartSkeleton height={200} />, ssr: false }
);
