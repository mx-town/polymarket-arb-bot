"use client";

import { useState, useEffect } from "react";
import { cn, formatCountdown } from "@/lib/format";

interface CountdownTimerProps {
  seconds_to_end: number;
}

export function CountdownTimer({ seconds_to_end }: CountdownTimerProps) {
  const [remaining, setRemaining] = useState(seconds_to_end);

  useEffect(() => {
    setRemaining(seconds_to_end);
  }, [seconds_to_end]);

  useEffect(() => {
    const interval = setInterval(() => {
      setRemaining((prev) => Math.max(0, prev - 1));
    }, 1_000);
    return () => clearInterval(interval);
  }, []);

  const color =
    remaining < 60
      ? "text-accent-red"
      : remaining < 120
        ? "text-accent-yellow"
        : "text-text-primary";

  return (
    <span className={cn("font-mono text-sm tabular-nums", color)}>
      {formatCountdown(remaining)}
    </span>
  );
}
