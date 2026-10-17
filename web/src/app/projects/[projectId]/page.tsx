import { notFound } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { Crumb } from "@/components/layout/TopBar";
import { ProjectHub } from "@/components/project/ProjectHub";
import { getCurrentUser } from "@/lib/auth";
import { requireProject } from "@/lib/permissions";
import { listModules } from "@/lib/repos/projects";
import { listDocuments } from "@/lib/repos/documents";

export const dynamic = "force-dynamic";

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;

  // requireProject is the authorisation boundary: it 404s (does not 403)
  // when the project belongs to someone else, so the response does not
  // confirm that the id exists.
  const user = await getCurrentUser();
  const project = await requireProject(projectId, user);

  const [modules, documents] = await Promise.all([
    listModules(projectId, user.id),
    listDocuments(projectId, user.id),
  ]);

  return (
    <AppShell
      user={{ fullName: user.fullName, email: user.email }}
      breadcrumb={<Crumb parentLabel="Projects" parentHref="/projects" current={project.name} />}
    >
      <ProjectHub
        project={{
          id: project.id,
          name: project.name,
          project_date: project.project_date,
          description: project.description,
          last_activity_at: project.last_activity_at,
        }}
        modules={modules}
        documents={documents.map((d) => ({
          id: d.id,
          file_name: d.file_name,
          status: d.status,
          error_detail: d.error_detail,
          page_count: d.page_count,
        }))}
      />
    </AppShell>
  );
}