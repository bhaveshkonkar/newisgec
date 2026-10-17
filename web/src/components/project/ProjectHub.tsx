"use client";

import * as React from "react";
import Link from "next/link";
import { useState } from "react";
import { Trash2, FileText, ArrowLeft } from "lucide-react";
import { ModuleGrid, type ModuleTileData } from "@/components/project/ModuleGrid";
import { DocumentsPanel } from "@/components/project/DocumentsPanel";
import { DeleteProjectDialog } from "@/components/project/DeleteProjectDialog";
import { Button } from "@/components/ui/button";
import { formatDate, timeAgo } from "@/lib/utils";

export type HubProps = {
  project: {
    id: string;
    name: string;
    project_date: string | null;
    description: string | null;
    last_activity_at: string;
  };
  modules: ModuleTileData[];
  documents: Array<{
    id: string;
    file_name: string;
    status: string;
    error_detail: string | null;
    page_count: number | null;
  }>;
};

export function ProjectHub({ project, modules, documents }: HubProps) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const parsed = documents.filter((d) => d.status === "parsed").length;

  return (
    <div className="mx-auto w-full max-w-[1180px] px-5 py-8 md:px-8 md:py-11">
      <Link
        href="/projects"
        className="inline-flex items-center gap-1.5 text-[12.5px] text-white/40 transition-colors hover:text-white/75"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        All projects
      </Link>

      {/* ---- header ---- */}
      <div className="mt-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[26px] font-semibold tracking-[-0.025em] text-white md:text-[30px]">
            {project.name}
          </h1>
          <p className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12.5px] text-white/40">
            <span className="tabular-nums">{formatDate(project.project_date)}</span>
            <span className="text-white/15">·</span>
            <span>
              {documents.length} {documents.length === 1 ? "document" : "documents"}
            </span>
            {parsed > 0 && (
              <>
                <span className="text-white/15">·</span>
                <span>{parsed} parsed</span>
              </>
            )}
            <span className="text-white/15">·</span>
            <span>active {timeAgo(project.last_activity_at)}</span>
          </p>
          {project.description && (
            <p className="mt-3.5 max-w-2xl text-[13.5px] leading-relaxed text-white/50">
              {project.description}
            </p>
          )}
        </div>

        <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)}>
          <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
          Delete
        </Button>
      </div>

      {/* ---- modules ---- */}
      <div className="mt-12">
        <h2 className="text-[15px] font-medium tracking-[-0.01em] text-white/85">Modules</h2>
        <p className="mt-1 text-[12.5px] text-white/35">
          Each module has its own assistant and its own view of this project&apos;s documents.
        </p>
        <div className="mt-5">
          <ModuleGrid projectId={project.id} modules={modules} />
        </div>
      </div>

      {/* ---- documents ---- */}
      <div className="mt-14">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-white/35" strokeWidth={1.75} />
          <h2 className="text-[15px] font-medium tracking-[-0.01em] text-white/85">
            Project Documents
          </h2>
        </div>
        <p className="mt-1 mb-5 text-[12.5px] text-white/35">
          Visible to every module in this project. Nothing here leaks into other projects.
        </p>
        <DocumentsPanel projectId={project.id} documents={documents} />
      </div>

      <DeleteProjectDialog
        projectId={project.id}
        projectName={project.name}
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
      />
    </div>
  );
}