"use client";

import * as React from "react";
import { AppSidebar, SidebarDrawer } from "./AppSidebar";
import { TopBar } from "./TopBar";
import { cn } from "@/lib/utils";

/**
 * The one shell. Every screen renders inside it, so the sidebar, top bar
 * and collapse behaviour cannot drift between pages.
 */
export function AppShell({
  user,
  breadcrumb,
  children,
  /** module pages manage their own scroll (chat fills the viewport) */
  fillHeight = false,
}: {
  user: { fullName: string; email: string | null };
  breadcrumb?: React.ReactNode;
  children: React.ReactNode;
  fillHeight?: boolean;
}) {
  const [collapsed, setCollapsed] = React.useState(false);
  const [drawerOpen, setDrawerOpen] = React.useState(false);

  // tablet: collapse the rail automatically, desktop: honour stored pref
  React.useEffect(() => {
    const stored = window.localStorage.getItem("isgec.sidebar");
    if (stored === "collapsed") setCollapsed(true);
    const mq = window.matchMedia("(max-width: 1279px)");
    const apply = () => {
      if (mq.matches) setCollapsed(true);
      else setCollapsed(stored === "collapsed");
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const toggle = () => {
    setCollapsed((c) => {
      const next = !c;
      window.localStorage.setItem("isgec.sidebar", next ? "collapsed" : "expanded");
      return next;
    });
  };

  return (
    <div className="flex h-dvh overflow-hidden bg-[#0a0d14] relative text-white">
      {/* Subtle background glow */}
      <div className="pointer-events-none absolute left-[40%] top-0 h-[1000px] w-[800px] -translate-x-1/2 -translate-y-1/4 rotate-[25deg] rounded-full bg-white/[0.03] blur-[120px]" />

      <div className="hidden lg:block relative z-10">
        <AppSidebar collapsed={collapsed} onCollapse={toggle} />
      </div>

      <SidebarDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />

      <div className="flex min-w-0 flex-1 flex-col relative z-10">
        <TopBar user={user} onMenuClick={() => setDrawerOpen(true)} breadcrumb={breadcrumb} />
        <main
          className={cn(
            "min-h-0 flex-1",
            fillHeight ? "overflow-hidden" : "overflow-y-auto",
          )}
        >
          {children}
        </main>
      </div>
    </div>
  );
}

/** Centred content column used by Projects Home and the Project Hub. */
export function PageContainer({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mx-auto w-full max-w-[1180px] px-5 py-8 md:px-8 md:py-11", className)}>
      {children}
    </div>
  );
}