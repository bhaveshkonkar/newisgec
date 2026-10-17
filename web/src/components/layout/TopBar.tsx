"use client";

import * as React from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Bell, Menu, ChevronDown, User, Settings, LogOut } from "lucide-react";
import { cn, initialsOf } from "@/lib/utils";

export function TopBar({
  user,
  onMenuClick,
  breadcrumb,
}: {
  user: { fullName: string; email: string | null };
  onMenuClick: () => void;
  breadcrumb?: React.ReactNode;
}) {
  const initials = initialsOf(user.fullName);

  return (
    <header
      className="sticky top-0 z-30 flex h-20 shrink-0 items-center gap-4 border-b border-white/5
                 bg-transparent px-6 backdrop-blur-md lg:px-10"
    >
      <button
        type="button"
        onClick={onMenuClick}
        aria-label="Open navigation"
        className="rounded-lg p-2 text-white/60 transition-colors hover:bg-white/[0.05] hover:text-white lg:hidden"
      >
        <Menu className="h-5 w-5" />
      </button>

      {breadcrumb ? <div className="min-w-0 flex-1">{breadcrumb}</div> : <div className="flex-1" id="topbar-search-portal" />}

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          aria-label="Notifications"
          className="relative rounded-lg p-2 text-white/50 transition-colors hover:bg-white/[0.05] hover:text-white/85"
        >
          <Bell className="h-[18px] w-[18px]" strokeWidth={1.75} />
          <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-accent ring-2 ring-base-950" />
        </button>

        <div className="mx-1 h-5 w-px bg-hair" />

        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button
              type="button"
              className="flex items-center gap-2.5 rounded-xl py-1.5 pl-1.5 pr-2.5 transition-colors
                         hover:bg-white/[0.05] data-[state=open]:bg-white/[0.06]"
            >
              <span
                className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-hair
                           bg-panel-raised text-[12px] font-semibold tracking-tight text-white/85"
              >
                {initials}
              </span>
              <span className="hidden text-left sm:block">
                <span className="block text-[13px] font-medium leading-tight text-white/90">
                  {user.fullName}
                </span>
              </span>
              <ChevronDown className="h-3.5 w-3.5 text-white/30" />
            </button>
          </DropdownMenu.Trigger>

          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="end"
              sideOffset={8}
              className="glass-raised z-50 min-w-[232px] p-1.5 shadow-pop animate-fade-in"
            >
              <div className="px-2.5 py-2">
                <div className="text-[13px] font-medium text-white">{user.fullName}</div>
                {user.email && (
                  <div className="mt-0.5 text-[11.5px] text-white/40">{user.email}</div>
                )}
              </div>
              <div className="my-1 h-px bg-hair" />
              {[
                { label: "Profile", icon: User },
                { label: "Settings", icon: Settings },
                { label: "Sign out", icon: LogOut },
              ].map((item) => (
                <DropdownMenu.Item
                  key={item.label}
                  className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2
                             text-[13px] text-white/65 outline-none transition-colors
                             hover:bg-white/[0.05] hover:text-white"
                >
                  <item.icon className="h-4 w-4" strokeWidth={1.75} />
                  {item.label}
                </DropdownMenu.Item>
              ))}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </header>
  );
}

/** "ADANI MAHAN / Gearbox / Gearbox Assistant" style trail, used by the project pages. */
export function Crumb({
  parentLabel,
  parentHref,
  midLabel,
  midHref,
  current,
  meta,
}: {
  parentLabel: string;
  parentHref?: string;
  /** Optional middle hop, for a page whose title sits under a module name. */
  midLabel?: string;
  midHref?: string;
  current: string;
  meta?: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 items-center gap-2 text-[13px]">
      {parentHref ? (
        <a
          href={parentHref}
          className="truncate text-white/50 transition-colors hover:text-white/85"
        >
          {parentLabel}
        </a>
      ) : (
        <span className="truncate text-white/50">{parentLabel}</span>
      )}
      <span className="text-white/20">/</span>
      {midLabel && (
        <>
          {midHref ? (
            <a
              href={midHref}
              className="truncate text-white/50 transition-colors hover:text-white/85"
            >
              {midLabel}
            </a>
          ) : (
            <span className="truncate text-white/50">{midLabel}</span>
          )}
          <span className="text-white/20">/</span>
        </>
      )}
      <span className="truncate font-medium text-white/90">{current}</span>
      {meta && <span className="hidden text-white/35 sm:inline">{meta}</span>}
    </div>
  );
}