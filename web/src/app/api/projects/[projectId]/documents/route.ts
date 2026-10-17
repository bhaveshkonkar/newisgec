import { NextResponse } from "next/server";
import { getCurrentUser, AuthError } from "@/lib/auth";
import { requireProject, statusOf, NotFoundError, isUuid } from "@/lib/permissions";
import { listDocuments, createDocument } from "@/lib/repos/documents";
import { queryOne } from "@/lib/db";
import { putFile, deleteFile, MAX_UPLOAD_BYTES } from "@/lib/storage";
import { dispatchParse, recoverStaleDocuments } from "@/lib/parse-dispatch";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ projectId: string }> };

const OK_MIME = new Set([
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "text/csv",
  "text/plain",
]);

/**
 * One-shot boot recovery.
 *
 * A PDF whose parse was interrupted by a restart stays 'processing' forever,
 * and the Documents panel would show it as such indefinitely with no error to
 * explain why. Nothing else is going to notice that row.
 *
 * This runs from the first documents request rather than from
 * `instrumentation.ts`. Instrumentation is compiled for the Edge runtime as
 * well as Node, and the recovery path reaches `pg`, which cannot be bundled
 * for Edge -- the build failed on pg's optional native dependency. The
 * documents route is Node-only by construction, so there is no edge graph to
 * satisfy and no behaviour is lost: the recovery happens on first use, which
 * for a single-user app is as good as at boot.
 */
let recovery: Promise<number> | null = null;

function recoverOnce(): Promise<number> {
  recovery ??= recoverStaleDocuments().catch((e) => {
    console.error("[documents] stale recovery failed:", e);
    // let a later request retry rather than caching the failure forever
    recovery = null;
    return 0;
  });
  return recovery;
}

/**
 * GET -> every document in the project.
 *
 * module_id is an optional *filter* for a module view. A null module_id
 * means "attached to the project, visible everywhere" -- that is the
 * default for uploads made from the Project Hub. It is never a permission
 * boundary on its own: every read is still scoped to the project.
 */
export async function GET(_req: Request, { params }: Ctx) {
  try {
    const { projectId } = await params;
    const user = await getCurrentUser();
    await requireProject(projectId, user);

    await recoverOnce();

    const docs = await listDocuments(projectId, user.id);
    return NextResponse.json({ documents: docs });
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to list documents" },
      { status },
    );
  }
}

/**
 * POST -> multipart upload. Bytes land on disk first, then the row.
 *
 * Order matters: a row is only written after the file is safely stored, so
 * there is never a 'uploaded' row pointing at a missing file. If the row
 * insert fails we sweep the orphaned file rather than leave it behind.
 */
export async function POST(req: Request, { params }: Ctx) {
  const { projectId } = await params;
  let user;
  try {
    user = await getCurrentUser();
    await requireProject(projectId, user);
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Not allowed" },
      { status },
    );
  }

  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return NextResponse.json({ error: "Expected multipart/form-data" }, { status: 400 });
  }

  const files = form.getAll("files").filter((f): f is File => f instanceof File);
  const moduleIdRaw = form.get("module_id");
  const moduleId = typeof moduleIdRaw === "string" && moduleIdRaw ? moduleIdRaw : null;

  if (files.length === 0) {
    return NextResponse.json({ error: "No files provided" }, { status: 400 });
  }

  // A client-supplied module_id is a claim, not a fact. Accepting it unchecked
  // would let a document be attached to another project's module, or to a
  // module type this project does not have. Verify it belongs to *this*
  // project before writing anything.
  if (moduleId) {
    if (!isUuid(moduleId)) {
      return NextResponse.json({ error: "module_id is not a valid id" }, { status: 400 });
    }
    const owned = await queryOne<{ module_type: string }>(
      `SELECT module_type FROM isgec.project_modules
        WHERE id = $1 AND project_id = $2`,
      [moduleId, projectId],
    );
    if (!owned) {
      return NextResponse.json(
        { error: "module_id does not belong to this project" },
        { status: 400 },
      );
    }
  }

  // one bad file must not reject the whole batch, so collect per-file
  const created: Array<{ id: string; file_name: string; status: string }> = [];
  const rejected: Array<{ file_name: string; reason: string }> = [];

  for (const file of files) {
    if (file.size > MAX_UPLOAD_BYTES) {
      rejected.push({
        file_name: file.name,
        reason: `larger than ${Math.round(MAX_UPLOAD_BYTES / 1024 / 1024)} MB`,
      });
      continue;
    }
    if (file.size === 0) {
      rejected.push({ file_name: file.name, reason: "file is empty" });
      continue;
    }
    if (file.type && !OK_MIME.has(file.type)) {
      rejected.push({ file_name: file.name, reason: `unsupported type ${file.type}` });
      continue;
    }

    let storagePath: string | null = null;
    try {
      const bytes = Buffer.from(await file.arrayBuffer());
      const stored = await putFile(projectId, file.name, bytes);
      storagePath = stored.storagePath;

      const doc = await createDocument({
        projectId,
        moduleId,
        fileName: file.name,
        storagePath: stored.storagePath,
        fileSize: stored.fileSize,
        mimeType: file.type || "application/octet-stream",
        uploadedBy: user.id,
      });
      created.push({ id: doc.id, file_name: doc.file_name, status: doc.status });

      // parsing is out of band; never await it inside the request
      void dispatchParse(doc.id, projectId, stored.storagePath).catch((e) =>
        console.error("[documents] parse dispatch failed:", e),
      );
    } catch (err) {
      if (storagePath) await deleteFile(projectId, storagePath).catch(() => {});
      rejected.push({
        file_name: file.name,
        reason: err instanceof Error ? err.message : "storage failed",
      });
    }
  }

  if (created.length === 0) {
    return NextResponse.json(
      { error: rejected[0]?.reason ?? "Upload failed", rejected },
      { status: 400 },
    );
  }

  return NextResponse.json({ documents: created, rejected }, { status: 201 });
}