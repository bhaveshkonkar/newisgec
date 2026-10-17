import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import {
  requireSession,
  assertModuleType,
  statusOf,
  NotFoundError,
} from "@/lib/permissions";
import { deleteSession } from "@/lib/repos/chat";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ projectId: string; sessionId: string }> };

export async function DELETE(req: Request, { params }: Ctx) {
  try {
    const { projectId, sessionId } = await params;
    const user = await getCurrentUser();
    const moduleType = assertModuleType(
      new URL(req.url).searchParams.get("module") ?? "gearbox",
    );
    await requireSession(sessionId, { projectId, moduleType }, user);

    const deleted = await deleteSession(sessionId, projectId, moduleType, user.id);
    if (!deleted) {
      return NextResponse.json({ error: "Conversation not found" }, { status: 404 });
    }
    return NextResponse.json({ deleted: true, id: sessionId });
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to delete conversation" },
      { status },
    );
  }
}