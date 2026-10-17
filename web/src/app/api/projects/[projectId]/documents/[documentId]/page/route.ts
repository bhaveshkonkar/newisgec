import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { requireProject, statusOf, NotFoundError } from "@/lib/permissions";
import { queryOne } from "@/lib/db";
import { pythonRenderPdfPage } from "@/lib/python";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ projectId: string; documentId: string }> };

/** Raster DPI tiers. The viewer picks one; the cap is enforced in Python too. */
const ALLOWED_DPI = new Set([130, 220, 300]);

/** Device pixels the rendered page may occupy. Bounded so a caller cannot ask
 *  for an unbounded raster. */
const MAX_TARGET_WIDTH = 4000;

/**
 * Serve one catalogue page as a PNG.
 *
 * This exists because embedding the PDF in an iframe hands rendering to the
 * browser's built-in PDF plugin, which privacy-focused browsers (Ulaa and
 * similar) block outright. Nothing a page serves can override that. Shipping a
 * rendered image removes the PDF viewer from the picture entirely: there is no
 * plugin to block and no PDF MIME type for a blocker to match.
 *
 * Authorization and scoping mirror the file route -- the caller must have
 * access to the project named in the URL, and the document must belong to it.
 * Only the project id and storage path go to Python; no file bytes and no
 * caller-chosen path ever cross that hop.
 */
export async function GET(req: Request, { params }: Ctx) {
  try {
    const { projectId, documentId } = await params;
    const user = await getCurrentUser();
    await requireProject(projectId, user);

    const row = await queryOne<{
      storage_path: string | null;
      mime_type: string;
      file_name: string;
      page_count: number | null;
    }>(
      `SELECT storage_path, mime_type, file_name, page_count
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
        { error: "Only PDF documents can be viewed" },
        { status: 415 },
      );
    }

    const url = new URL(req.url);
    const pageNo = Number(url.searchParams.get("page") ?? "1");
    if (!Number.isInteger(pageNo) || pageNo < 1) {
      return NextResponse.json({ error: "Invalid page" }, { status: 400 });
    }
    if (row.page_count && pageNo > row.page_count) {
      return NextResponse.json(
        { error: `Page ${pageNo} is past the end of this document` },
        { status: 404 },
      );
    }

    const requested = Number(url.searchParams.get("dpi") ?? "220");
    const dpi = ALLOWED_DPI.has(requested) ? requested : 220;

    // `w` is how many device pixels the viewer will give the page. Preferred
    // over a fixed DPI tier because it keeps the raster 1:1 with the screen at
    // any panel size and device pixel ratio.
    const rawWidth = Number(url.searchParams.get("w") ?? "0");
    const targetWidth =
      Number.isFinite(rawWidth) && rawWidth >= 320 && rawWidth <= MAX_TARGET_WIDTH
        ? Math.round(rawWidth)
        : undefined;

    const rendered = await pythonRenderPdfPage(projectId, row.storage_path, pageNo, {
      targetWidth,
      dpi,
    });

    if (!rendered.ok) {
      const status = rendered.status === 404 ? 404 : rendered.status === 400 ? 400 : 502;
      return NextResponse.json({ error: rendered.error }, { status });
    }

    const headers: Record<string, string> = {
      "Content-Type": "image/png",
      "Content-Length": String(rendered.data.byteLength),
      "X-Content-Type-Options": "nosniff",
      // Authenticated catalogue pages: never let a shared cache keep them.
      "Cache-Control": "private, max-age=300",
    };

    return new NextResponse(Buffer.from(rendered.data), { headers });
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to render page" },
      { status },
    );
  }
}