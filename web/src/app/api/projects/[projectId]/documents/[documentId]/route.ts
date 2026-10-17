import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { requireProject, statusOf, NotFoundError } from "@/lib/permissions";
import { deleteDocument } from "@/lib/repos/documents";
import { deleteFile } from "@/lib/storage";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ projectId: string; documentId: string }> };

/**
 * DELETE is scoped on three keys at once -- id, project, and owner. A
 * document id belonging to another project therefore matches nothing and
 * the row stays put, rather than being deleted through a guessed id.
 */
export async function DELETE(_req: Request, { params }: Ctx) {
  try {
    const { projectId, documentId } = await params;
    const user = await getCurrentUser();
    await requireProject(projectId, user);

    const row = await deleteDocument(documentId, projectId, user.id);
    if (!row) {
      return NextResponse.json({ error: "Document not found" }, { status: 404 });
    }

    // row is gone; the file on disk is now unreferenced
    if (row.storage_path) {
      await deleteFile(projectId, row.storage_path).catch((e) =>
        console.error("[documents] file sweep failed:", e.message),
      );
    }

    return NextResponse.json({ deleted: true, id: documentId });
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to delete document" },
      { status },
    );
  }
}