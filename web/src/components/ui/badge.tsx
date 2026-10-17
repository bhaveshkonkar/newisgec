import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-lg border px-2 py-0.5 text-[11px] font-medium tracking-[0.01em]",
  {
    variants: {
      tone: {
        neutral: "border-hair bg-white/[0.04] text-white/60",
        accent: "border-accent/25 bg-accent/10 text-accent",
        ok: "border-emerald-500/25 bg-emerald-500/10 text-emerald-300",
        warn: "border-amber-500/25 bg-amber-500/10 text-amber-300",
        err: "border-red-500/25 bg-red-500/10 text-red-300",
        info: "border-sky-500/25 bg-sky-500/10 text-sky-300",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

/** Small pulsing dot for live status. */
export function Dot({ className, tone = "ok" }: { className?: string; tone?: "ok" | "warn" | "err" }) {
  const color =
    tone === "ok" ? "bg-emerald-400" : tone === "warn" ? "bg-amber-400" : "bg-red-400";
  return (
    <span className={cn("relative inline-flex h-1.5 w-1.5", className)}>
      <span className={cn("absolute inline-flex h-full w-full rounded-full opacity-60", color, "animate-ping")} />
      <span className={cn("relative inline-flex h-1.5 w-1.5 rounded-full", color)} />
    </span>
  );
}

export { badgeVariants };