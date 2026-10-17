"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-medium " +
    "transition-all duration-200 disabled:pointer-events-none disabled:opacity-45 " +
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/45",
  {
    variants: {
      variant: {
        // the one accent-filled button on any screen
        primary:
          "bg-accent text-[#1A0E00] hover:bg-accent/90 active:bg-accent/85 shadow-[0_1px_0_rgba(255,255,255,0.18)_inset]",
        secondary:
          "border border-hair bg-panel-raised text-white/85 hover:bg-panel-hover hover:border-hair-strong",
        ghost: "text-white/60 hover:text-white hover:bg-white/[0.05]",
        outline:
          "border border-hair-strong bg-transparent text-white/80 hover:bg-white/[0.04]",
        danger:
          "border border-red-500/25 bg-red-500/10 text-red-300 hover:bg-red-500/15",
      },
      size: {
        sm: "h-8 px-3 text-[13px]",
        md: "h-10 px-4",
        lg: "h-11 px-5",
        icon: "h-9 w-9",
        "icon-sm": "h-8 w-8",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { buttonVariants };