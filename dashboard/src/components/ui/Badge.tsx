"use client";

import { cn } from "@/lib/format";

type BadgeVariant = "success" | "danger" | "warning" | "info" | "neutral";

interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
}

const variantStyles: Record<BadgeVariant, string> = {
  success: "bg-accent-green/15 text-accent-green",
  danger: "bg-accent-red/15 text-accent-red",
  warning: "bg-accent-yellow/15 text-accent-yellow",
  info: "bg-accent-blue/15 text-accent-blue",
  neutral: "bg-bg-tertiary text-text-secondary",
};

export function Badge({ variant = "neutral", children }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        variantStyles[variant],
      )}
    >
      {children}
    </span>
  );
}
