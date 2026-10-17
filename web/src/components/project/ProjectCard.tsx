import Link from "next/link";
import { ArrowRight, FileText, Building2, Landmark, Factory } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils";

export type ProjectCardData = {
  id: string;
  name: string;
  project_date: string | null;
  description: string | null;
  document_count: number;
  parsed_count: number;
  last_activity_at: string;
};

/**
 * Deliberately contains nothing module-specific. A project card knows its
 * name, date and how many documents it holds -- nothing about gearboxes.
 */
export function ProjectCard({ project }: { project: ProjectCardData }) {
  // Add some visual variety to the icons just like the design
  const Icon = project.name.length % 3 === 0 ? Factory : project.name.length % 2 === 0 ? Landmark : Building2;
  const iconColor = project.name.length % 3 === 0 ? "text-emerald-500" : project.name.length % 2 === 0 ? "text-blue-500" : "text-gray-300";
  
  return (
    <Link
      href={`/projects/${project.id}`}
      className={cn(
        "group relative flex flex-col rounded-[20px] border border-white/5 bg-white/[0.02] p-6",
        "backdrop-blur-md overflow-hidden transition-all duration-300 min-h-[220px]",
        "hover:border-white/10 hover:bg-white/[0.04] hover:shadow-2xl",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/20",
      )}
    >
      {/* Light flare effect on hover (matching "ADANI MAHAN" card) */}
      <div className="pointer-events-none absolute -right-20 -top-20 h-48 w-48 rounded-full bg-white/5 blur-3xl transition-opacity group-hover:bg-white/10" />

      {/* Icon Box */}
      <div className="mb-8 flex h-[46px] w-[46px] items-center justify-center rounded-[14px] bg-white/[0.04] border border-white/5 shadow-sm">
        <Icon className={cn("h-5 w-5", iconColor)} strokeWidth={1.5} />
      </div>

      <div className="mt-auto">
        <h3 className="min-w-0 truncate text-[17px] font-semibold text-white tracking-wide">
          {project.name.toUpperCase()}
        </h3>
        <p className="mt-1 text-[13px] text-white/50">
          {formatDate(project.project_date)}
        </p>
      </div>

      <div className="mt-8 flex items-center justify-between">
        <span className="flex items-center gap-2 text-[13px] font-medium text-white/40">
          <FileText className="h-[15px] w-[15px]" strokeWidth={1.75} />
          {project.document_count} {project.document_count === 1 ? "document" : "documents"}
        </span>
        <div className="flex h-[38px] w-[38px] items-center justify-center rounded-full bg-white/[0.05] transition-colors group-hover:bg-white/[0.1] border border-white/5">
          <ArrowRight className="h-4 w-4 text-white/70 group-hover:text-white transition-transform group-hover:translate-x-0.5" strokeWidth={2} />
        </div>
      </div>
    </Link>
  );
}