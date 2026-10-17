import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { requireProject, statusOf, NotFoundError } from "@/lib/permissions";
import { queryOne } from "@/lib/db";
import { readFileFromStorage } from "@/lib/storage";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ projectId: string; documentId: string }> };

/**
 * Serve a stored document for inline viewing.
 *
 * The `#page=N` fragment is only honoured by the browser's native PDF viewer;
 * the assistant's own viewer renders pages with PDF.js and ignores it. Only
 * PDFs are served inline; other types are rejected with 415 so the caller does
 * not get a corrupted viewer.
 */
export async function GET(_req: Request, { params }: Ctx) {
  try {
    const { projectId, documentId } = await params;
    const user = await getCurrentUser();

    // Authorization is always against the project named in the URL. Vendor
    // catalogue PDFs live in the system project, so callers pass that id and
    // the scope check below still applies to them.
    await requireProject(projectId, user);

    const row = await queryOne<{
      mime_type: string;
      storage_path: string | null;
      file_name: string;
      project_id: string;
    }>(
      `SELECT mime_type, storage_path, file_name, project_id
         FROM isgec.documents
        WHERE id = $1
          AND project_id = $2`,
      [documentId, projectId],
    );

    if (!row) {
      return NextResponse.json({ error: "Document not found" }, { status: 404 });
    }
    if (!row.storage_path) {
      return NextResponse.json({ error: "File not stored" }, { status: 404 });
    }
    if (row.mime_type !== "application/pdf") {
      return NextResponse.json(
        { error: "Only PDF documents can be viewed inline" },
        { status: 415 },
      );
    }

    const bytes = await readFileFromStorage(projectId, row.storage_path);

    const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
    return new NextResponse(ab, {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Length": String(bytes.length),
        "Content-Disposition": `inline; filename="${encodeURIComponent(row.file_name)}"`,
        // Prevent MIME-sniffing a non-PDF into a PDF viewer.
        "X-Content-Type-Options": "nosniff",
        // Same-origin only. The in-panel viewer fetches this as a plain
        // same-origin request via PDF.js, so it never needs to be framed.
        "X-Frame-Options": "SAMEORIGIN",
      },
    });
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to open document" },
      { status },
    );
  }
}