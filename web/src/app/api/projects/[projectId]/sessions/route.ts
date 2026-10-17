import { NextResponse } from "next/server";
import { z } from "zod";
import { getCurrentUser, AuthError } from "@/lib/auth";
import { requireProject, statusOf, NotFoundError } from "@/lib/permissions";
import { listSessions, createSession } from "@/lib/repos/chat";
import { assertModuleType } from "@/lib/permissions";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ projectId: string }> };

const Create = z.object({
  module_type: z.string().default("gearbox"),
  title: z.string().trim().max(200).optional(),
});

/**
 * GET /api/projects/:id/sessions?module=gearbox
 *
 * module_type is filtered in SQL rather than in JS: a session from another
 * module must not even be counted, let alone listed.
 */
export async function GET(req: Request, { params }: Ctx) {
  try {
    const { projectId } = await params;
    const user = await getCurrentUser();
    await requireProject(projectId, user);

    const moduleType = assertModuleType(
      new URL(req.url).searchParams.get("module") ?? "gearbox",
    );
    const sessions = await listSessions(projectId, moduleType, user.id);
    return NextResponse.json({ sessions });
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to list conversations" },
      { status },
    );
  }
}

export async function POST(req: Request, { params }: Ctx) {
  try {
    const { projectId } = await params;
    const user = await getCurrentUser();
    await requireProject(projectId, user);

    const body = await req.json().catch(() => ({}));
    const parsed = Create.safeParse(body);
    const moduleType = assertModuleType(parsed.success ? parsed.data.module_type : "gearbox");

    const session = await createSession(
      projectId,
      moduleType,
      parsed.success ? (parsed.data.title ?? "New conversation") : "New conversation",
      user.id,
    );
    return NextResponse.json({ session }, { status: 201 });
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to create conversation" },
      { status },
    );
  }
}