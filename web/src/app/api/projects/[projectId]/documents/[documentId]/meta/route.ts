import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { requireProject, statusOf, NotFoundError } from "@/lib/permissions";
import { queryOne } from "@/lib/db";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ projectId: string; documentId: string }> };

export async function GET(_req: Request, { params }: Ctx) {
  try {
    const { projectId, documentId } = await params;
    const user = await getCurrentUser();

    // Scoped to the project named in the URL; vendor catalogue PDFs are read
    // through the system project id just like the file route.
    await requireProject(projectId, user);

    const row = await queryOne<{
      page_count: number | null;
      file_name: string;
    }>(
      `SELECT page_count, file_name
         FROM isgec.documents
        WHERE id = $1
          AND project_id = $2`,
      [documentId, projectId],
    );

    if (!row) {
      return NextResponse.json({ error: "Document not found" }, { status: 404 });
    }

    return NextResponse.json({
      page_count: row.page_count,
      file_name: row.file_name,
    });
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to get document metadata" },
      { status },
    );
  }
}