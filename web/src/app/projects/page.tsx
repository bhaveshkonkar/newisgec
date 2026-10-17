import { AppShell } from "@/components/layout/AppShell";
import { ProjectsHome } from "@/components/project/ProjectsHome";
import { getCurrentUser } from "@/lib/auth";
import { listProjects } from "@/lib/repos/projects";

export const dynamic = "force-dynamic";

export default async function ProjectsPage() {
  let userName = "there";
  let projects: Awaited<ReturnType<typeof listProjects>> = [];
  let loadError: string | null = null;

  try {
    const user = await getCurrentUser();
    userName = user.fullName;
    projects = await listProjects(user.id);
  } catch (err) {
    loadError = err instanceof Error ? err.message : "Could not load projects";
  }

  return (
    <AppShell user={{ fullName: userName, email: null }}>
      <ProjectsHome
        projects={projects as Parameters<typeof ProjectsHome>[0]["projects"]}
        userName={userName}
        loadError={loadError}
      />
    </AppShell>
  );
}