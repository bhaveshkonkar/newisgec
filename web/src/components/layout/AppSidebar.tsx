"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FolderKanban,
  FileText,
  Settings,
  LifeBuoy,
  Home,
  LogOut,
  ChevronsLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The sidebar is identical on all three screens. It is desktop-first and
 * collapses to icons on tablet; on mobile it becomes an overlay drawer
 * (state owned by AppShell).
 */
const NAV = [
  { label: "Home", href: "/projects", icon: Home },
  { label: "Projects", href: "/projects", icon: FolderKanban },
  { label: "Documents", href: "/documents", icon: FileText },
  { label: "Settings", href: "/settings", icon: Settings },
];

export function AppSidebar({
  collapsed,
  onCollapse,
  onNavigate,
}: {
  collapsed: boolean;
  onCollapse: () => void;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "flex h-full flex-col border-r border-hair bg-base-900/60 backdrop-blur-xl",
        "transition-[width] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
        collapsed ? "w-[68px]" : "w-[248px]",
      )}
    >
      {/* ---- brand ---- */}
      <div className={cn("flex h-16 shrink-0 items-center gap-2.5 px-4", collapsed && "justify-center px-0")}>
        <div
          className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-accent/25
                     bg-accent/10 text-[13px] font-bold tracking-tight text-accent"
        >
          IS
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <div className="truncate text-[14px] font-semibold tracking-[-0.01em] text-white">
              ISGEC AI
            </div>
            <div className="truncate text-[11px] text-white/40">Engineering Assistant</div>
          </div>
        )}
      </div>

      {/* ---- nav ---- */}
      <nav className="flex-1 space-y-0.5 px-3 py-2">
        {!collapsed && (
          <div className="px-2.5 pb-1.5 pt-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-white/25">
            Workspace
          </div>
        )}
        {NAV.map((item) => {
          const active =
            item.label === "Projects"
              ? pathname === "/projects" || pathname.startsWith("/projects/")
              : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.label}
              href={item.href}
              onClick={onNavigate}
              title={collapsed ? item.label : undefined}
              className={cn(
                "group relative flex items-center gap-3 rounded-xl px-2.5 py-2.5 text-[13px] font-medium",
                "transition-colors duration-200",
                active
                  ? "bg-white/[0.055] text-white"
                  : "text-white/50 hover:bg-white/[0.035] hover:text-white/85",
                collapsed && "justify-center px-0",
              )}
            >
              {active && (
                <span className="accent-rule absolute left-0 top-1/2 h-5 w-[2.5px] -translate-y-1/2 rounded-r-full" />
              )}
              <Icon className="h-[17px] w-[17px] shrink-0" strokeWidth={1.75} />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* ---- bottom: help + collapse ---- */}
      <div className="space-y-0.5 border-t border-hair px-3 py-3">
        <button
          type="button"
          title={collapsed ? "Help & Support" : undefined}
          className={cn(
            "flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-[13px] font-medium",
            "text-white/45 transition-colors hover:bg-white/[0.035] hover:text-white/85",
            collapsed && "justify-center px-0",
          )}
        >
          <LifeBuoy className="h-[17px] w-[17px] shrink-0" strokeWidth={1.75} />
          {!collapsed && <span>Help & Support</span>}
        </button>

        <button
          type="button"
          onClick={onCollapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className={cn(
            "hidden w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-[13px] font-medium lg:flex",
            "text-white/30 transition-colors hover:bg-white/[0.035] hover:text-white/70",
            collapsed && "justify-center px-0",
          )}
        >
          <ChevronsLeft
            className={cn("h-[17px] w-[17px] shrink-0 transition-transform duration-300", collapsed && "rotate-180")}
            strokeWidth={1.75}
          />
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>
    </aside>
  );
}

/** Mobile drawer wrapper -- same component, different container. */
export function SidebarDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div
        className="absolute inset-0 bg-black/65 backdrop-blur-[2px] animate-fade-in"
        onClick={onClose}
      />
      <div className="absolute inset-y-0 left-0 w-[268px] animate-slide-in-right">
        <div className="h-full">
          <MobileSidebar onNavigate={onClose} />
        </div>
      </div>
    </div>
  );
}

function MobileSidebar({ onNavigate }: { onNavigate: () => void }) {
  const pathname = usePathname();
  return (
    <div className="flex h-full flex-col border-r border-hair bg-base-900">
      <div className="flex h-16 items-center gap-2.5 px-4">
        <div className="grid h-9 w-9 place-items-center rounded-xl border border-accent/25 bg-accent/10 text-[13px] font-bold text-accent">
          IS
        </div>
        <div>
          <div className="text-[14px] font-semibold text-white">ISGEC AI</div>
          <div className="text-[11px] text-white/40">Engineering Assistant</div>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 px-3 py-2">
        {NAV.map((item) => {
          const Icon = item.icon;
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.label}
              href={item.href}
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-3 rounded-xl px-2.5 py-2.5 text-[13px] font-medium transition-colors",
                active ? "bg-white/[0.055] text-white" : "text-white/50",
              )}
            >
              <Icon className="h-[17px] w-[17px]" strokeWidth={1.75} />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-hair px-3 py-3">
        <button className="flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-[13px] text-white/45">
          <LifeBuoy className="h-[17px] w-[17px]" strokeWidth={1.75} />
          Help & Support
        </button>
      </div>
    </div>
  );
}

export { LogOut };