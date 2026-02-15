"use client";

import { ReactNode } from "react";

interface ChartContainerProps {
  title: string;
  height?: number;
  toolbar?: ReactNode;
  children: ReactNode;
}

export function ChartContainer({
  title,
  height = 400,
  toolbar,
  children,
}: ChartContainerProps) {
  return (
    <div className="rounded-lg border border-border-primary bg-bg-secondary">
      <div className="flex items-center justify-between border-b border-border-secondary px-4 py-2">
        <h3 className="text-sm font-medium text-text-secondary">{title}</h3>
        {toolbar && <div className="flex gap-2">{toolbar}</div>}
      </div>
      <div style={{ height }} className="relative">
        {children}
      </div>
    </div>
  );
}
