import { NextResponse } from "next/server";
import { z } from "zod";
import { getCurrentUser, AuthError } from "@/lib/auth";
import { requireProject, statusOf, NotFoundError } from "@/lib/permissions";
import {
  getProject,
  updateProject,
  deleteProject,
  listModules,
} from "@/lib/repos/projects";
import { listDocuments } from "@/lib/repos/documents";
import { listSessions } from "@/lib/repos/chat";
import { deleteProjectDir } from "@/lib/storage";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ projectId: string }> };

const Patch = z.object({
  name: z.string().trim().min(1).max(120).optional(),
  project_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).or(z.literal("")).optional(),
  description: z.string().trim().max(2000).optional(),
});

/** GET /api/projects/:id -> project + modules + document + session counts */
export async function GET(_req: Request, { params }: Ctx) {
  try {
    const { projectId } = await params;
    const user = await getCurrentUser();
    const project = await requireProject(projectId, user);

    const [modules, documents, sessions] = await Promise.all([
      listModules(projectId, user.id),
      listDocuments(projectId, user.id),
      listSessions(projectId, "gearbox", user.id),
    ]);

    return NextResponse.json({
      project,
      modules,
      documentCount: documents.length,
      sessionCount: sessions.length,
    });
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to load project" },
      { status },
    );
  }
}

export async function PATCH(req: Request, { params }: Ctx) {
  try {
    const { projectId } = await params;
    const user = await getCurrentUser();
    await requireProject(projectId, user);

    const parsed = Patch.safeParse(await req.json().catch(() => ({})));
    if (!parsed.success) {
      return NextResponse.json(
        { error: parsed.error.issues[0]?.message ?? "Invalid input" },
        { status: 400 },
      );
    }

    const { name, project_date, description } = parsed.data;
    const project = await updateProject(projectId, user.id, {
      name,
      project_date: project_date === "" ? null : project_date,
      description: description === "" ? null : description,
    });

    if (!project) {
      return NextResponse.json({ error: "Project not found" }, { status: 404 });
    }
    return NextResponse.json({ project });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to update project" },
      { status: statusOf(err) },
    );
  }
}

export async function DELETE(_req: Request, { params }: Ctx) {
  try {
    const { projectId } = await params;
    const user = await getCurrentUser();
    await requireProject(projectId, user);

    // documents + chats are removed by ON DELETE CASCADE; the on-disk
    // folder has no such safety net, so sweep it explicitly afterwards.
    const removed = await deleteProject(projectId, user.id);
    if (!removed) {
      return NextResponse.json({ error: "Project not found" }, { status: 404 });
    }
    await deleteProjectDir(projectId).catch((e) =>
      console.error("[projects] storage sweep failed:", e.message),
    );

    return NextResponse.json({ deleted: true, id: projectId });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to delete project" },
      { status: statusOf(err) },
    );
  }
}