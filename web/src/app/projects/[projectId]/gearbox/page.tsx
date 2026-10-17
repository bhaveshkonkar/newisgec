import { redirect } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { Crumb } from "@/components/layout/TopBar";
import { GearboxAssistant } from "@/components/assistant/GearboxAssistant";
import { getCurrentUser } from "@/lib/auth";
import { requireProject, assertModuleType, NotFoundError } from "@/lib/permissions";
import { listModules } from "@/lib/repos/projects";
import { listDocuments } from "@/lib/repos/documents";
import { listSessions, listMessages, type MessageRow } from "@/lib/repos/chat";
import { query } from "@/lib/db";

export const dynamic = "force-dynamic";

export default async function GearboxPage({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ session?: string }>;
}) {
  const { projectId } = await params;
  const { session: wanted } = await searchParams;
  const user = await getCurrentUser();
  const project = await requireProject(projectId, user);
  const moduleType = assertModuleType("gearbox");

  // A module can exist as a row but be switched off. Sending the user to a
  // dead page would be worse than saying so plainly.
  const modules = await listModules(projectId, user.id);
  const mod = modules.find((m) => m.module_type === moduleType);
  if (!mod?.enabled) redirect(`/projects/${projectId}`);

  const [documents, sessions] = await Promise.all([
    listDocuments(projectId, user.id),
    listSessions(projectId, moduleType, user.id),
  ]);

  // No ?session= means "start a new conversation", not "resume the newest
  // one". Falling back to the most recent made the rail's New button a no-op:
  // it stripped the param, the loader picked the latest session right back,
  // and the next requirement landed inside the conversation the user was
  // trying to leave. Past conversations stay in the rail and untouched; this
  // one is materialised only when the first message is sent.
  const active = wanted ? sessions.find((s) => s.id === wanted) ?? null : null;

  let messages: MessageRow[] = [];
  if (active) {
    try {
      messages = await listMessages(active.id, projectId, moduleType, user.id);
    } catch (err) {
      // a session that vanished between the two queries is not worth a 500
      if (!(err instanceof NotFoundError)) throw err;
    }
  }

  const vendors = await query<{ id: number; code: string; name: string }>(
    "SELECT id, code, name FROM vendor WHERE is_active ORDER BY name",
  );

  return (
    <AppShell
      user={{ fullName: user.fullName, email: user.email }}
      fillHeight
      breadcrumb={
        <Crumb
          parentLabel={project.name}
          parentHref={`/projects/${projectId}`}
          midLabel="Gearbox"
          midHref={`/projects/${projectId}/gearbox`}
          current="Gearbox Assistant"
        />
      }
    >
      <GearboxAssistant
        projectId={projectId}
        sessions={sessions.map((s) => ({
          id: s.id,
          title: s.title,
          updated_at: s.updated_at,
        }))}
        activeSessionId={active?.id ?? null}
        initialMessages={messages}
        documents={documents.map((d) => ({
          id: d.id,
          file_name: d.file_name,
          status: d.status,
          error_detail: d.error_detail,
          page_count: d.page_count,
        }))}
        vendors={vendors}
      />
    </AppShell>
  );
}