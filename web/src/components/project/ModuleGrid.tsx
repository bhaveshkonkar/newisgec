"use client";

import Link from "next/link";
import { Lock } from "lucide-react";
import { cn } from "@/lib/utils";
import { MODULES, type ModuleDef } from "@/lib/modules";
import { moduleIcon } from "@/components/project/moduleIcons";

export type ModuleTileData = {
  module_type: string;
  enabled: boolean;
};

/**
 * Six tiles, fixed order, no per-project customisation. A module that has
 * no implementation yet is shown rather than hidden -- the user asked to
 * see the intended structure -- but it is visually inert and cannot be
 * clicked, so it cannot become a dead-end route.
 */
export function ModuleGrid({
  projectId,
  modules,
}: {
  projectId: string;
  modules: ModuleTileData[];
}) {
  const byType = new Map(modules.map((m) => [m.module_type, m]));

  return (
    <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
      {MODULES.map((def) => {
        const row = byType.get(def.type);
        const enabled = row?.enabled ?? false;
        const usable = def.live && enabled;

        return (
          <ModuleTile
            key={def.type}
            def={def}
            projectId={projectId}
            enabled={enabled}
            usable={usable}
          />
        );
      })}
    </div>
  );
}

function ModuleTile({
  def,
  projectId,
  enabled,
  usable,
}: {
  def: ModuleDef;
  projectId: string;
  enabled: boolean;
  usable: boolean;
}) {
  const Icon = moduleIcon(def.icon);

  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <span
          className={cn(
            "grid h-9 w-9 shrink-0 place-items-center rounded-xl border transition-colors duration-300",
            usable
              ? "border-hair-strong bg-white/[0.04] text-white/80"
              : "border-hair bg-white/[0.02] text-white/25",
          )}
        >
          <Icon className="h-[18px] w-[18px]" strokeWidth={1.6} />
        </span>

        {!usable && (
          <span className="rounded-full border border-hair px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.07em] text-white/25">
            {def.live ? "Disabled" : "Coming soon"}
          </span>
        )}
      </div>

      <h3
        className={cn(
          "mt-3.5 text-[14.5px] font-medium tracking-[-0.01em]",
          usable ? "text-white" : "text-white/45",
        )}
      >
        {def.label}
      </h3>
      <p className="mt-1 text-[12.5px] leading-relaxed text-white/35">{def.description}</p>
    </>
  );

  const shell = cn(
    "relative flex flex-col rounded-2xl border border-hair bg-panel/70 p-4.5 text-left backdrop-blur-xl",
    "shadow-card transition-all duration-300",
    usable &&
      "hover:border-hair-strong hover:bg-panel-raised/80 hover:shadow-lift focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/45",
    !usable && "cursor-not-allowed opacity-70",
  );

  if (!usable) {
    return (
      <div className={shell} aria-disabled="true">
        {body}
        <span className="mt-3 flex items-center gap-1.5 text-[11px] text-white/20">
          <Lock className="h-3 w-3" strokeWidth={1.75} />
          {def.live ? "Enable in project settings" : "Not implemented yet"}
        </span>
      </div>
    );
  }

  return (
    <Link href={`/projects/${projectId}/${def.segment}`} className={shell}>
      {body}
    </Link>
  );
}