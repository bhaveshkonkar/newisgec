"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { Search, Plus, FolderOpen, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ProjectCard, type ProjectCardData } from "@/components/project/ProjectCard";
import { CreateProjectModal } from "@/components/project/CreateProjectModal";

export function ProjectsHome({
  projects,
  userName,
  loadError,
}: {
  projects: ProjectCardData[];
  userName: string;
  loadError?: string | null;
}) {
  const [query, setQuery] = React.useState("");
  const [tab, setTab] = React.useState<"recent" | "all">("recent");
  const [open, setOpen] = React.useState(false);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => setMounted(true), []);

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.description ?? "").toLowerCase().includes(q),
    );
  }, [projects, query]);

  const sorted = React.useMemo(() => {
    const copy = [...filtered];
    if (tab === "recent") {
      copy.sort((a, b) => +new Date(b.last_activity_at) - +new Date(a.last_activity_at));
    } else {
      copy.sort((a, b) => a.name.localeCompare(b.name));
    }
    return copy;
  }, [filtered, tab]);

  const greeting = React.useMemo(() => {
    const h = new Date().getHours();
    if (h < 12) return "Good Morning";
    if (h < 17) return "Good Afternoon";
    return "Good Evening";
  }, []);

  const firstName = userName.split(/\s+/)[0];

  const searchPortalTarget = mounted ? document.getElementById("topbar-search-portal") : null;
  const searchInput = searchPortalTarget ? createPortal(
    <div className="relative w-full max-w-sm transition-all">
      <Search
        className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40"
        strokeWidth={2}
      />
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search projects..."
        className="h-[38px] w-full rounded-[10px] border border-white/10 bg-white/[0.03] pl-10 pr-4 text-[13px] text-white placeholder:text-white/30 hover:bg-white/[0.05] focus:border-white/20 focus:bg-white/[0.05] focus:outline-none focus:ring-0 transition-colors"
        aria-label="Search projects"
      />
    </div>,
    searchPortalTarget
  ) : null;

  return (
    <div className="mx-auto w-full max-w-[1080px] px-6 py-10 md:px-10 md:py-16">
      {searchInput}

      {/* ---- greeting & new project ---- */}
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-6">
        <div>
          <h1 className="text-4xl font-semibold tracking-tight text-white md:text-[44px] leading-[1.15]">
            {greeting},<br />
            {firstName}.
          </h1>
          <p className="mt-5 text-[15px] leading-relaxed text-white/60">
            Your engineering AI workspace.<br />
            Create or select a project to continue.
          </p>
        </div>
        
        <button 
          onClick={() => setOpen(true)} 
          className="mt-2 flex h-10 shrink-0 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-5 text-[13.5px] font-medium text-white transition-colors hover:bg-white/[0.08]"
        >
          <Plus className="h-4 w-4 text-white/70" strokeWidth={2} />
          New Project
        </button>
      </div>

      {/* ---- section + toggle ---- */}
      <div className="mt-16 flex items-center justify-between gap-4 border-b border-white/5 pb-4">
        <h2 className="text-[17px] font-semibold tracking-tight text-white">Your Projects</h2>

        <div className="flex items-center gap-1 rounded-full bg-white/[0.03] p-1 border border-white/5">
          {(["recent", "all"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={cn(
                "rounded-full px-5 py-1.5 text-[12px] font-medium capitalize transition-all duration-200",
                tab === t
                  ? "bg-white/[0.08] text-white shadow-sm"
                  : "text-white/40 hover:text-white/70 hover:bg-white/[0.03]",
              )}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* ---- grid ---- */}
      <div className="mt-8">
        {loadError && (
          <div className="rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-3 text-[13px] text-red-300">
            {loadError}
          </div>
        )}

        {!loadError && sorted.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 bg-white/[0.01] px-6 py-20 text-center">
            <FolderOpen className="h-8 w-8 text-white/20" strokeWidth={1.5} />
            <p className="mt-4 text-[14px] font-medium text-white/70">
              {query ? "No projects match that search." : "No projects yet."}
            </p>
            <p className="mt-1.5 text-[13px] text-white/40">
              {query ? "Try a different term." : "Create your first project to get started."}
            </p>
            {!query && (
              <button 
                onClick={() => setOpen(true)} 
                className="mt-6 flex h-9 items-center gap-2 rounded-lg bg-white/10 px-4 text-[13px] font-medium text-white transition-colors hover:bg-white/20"
              >
                <Plus className="h-3.5 w-3.5" />
                New Project
              </button>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {sorted.map((p) => (
            <ProjectCard key={p.id} project={p} />
          ))}
        </div>

        {loadingMore && (
          <div className="mt-8 flex justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-white/30" />
          </div>
        )}
      </div>

      <CreateProjectModal open={open} onOpenChange={setOpen} />
    </div>
  );
}