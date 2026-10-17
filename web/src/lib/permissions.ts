/**
 * Authorisation -- the only door into project-scoped data.
 *
 * The invariant this file exists to enforce:
 *
 *   a project_id arriving from the browser is a CLAIM, never a fact.
 *
 * Every project-scoped route calls requireProject() before touching the
 * database. A client that edits projectId in the URL or in a JSON body
 * gets a 404/403 here, not somebody else's documents.
 *
 * This is deliberately not replaced by trusting the caller to filter.
 * The SQL in lib/repos/* takes the resolved owner id too, so a forgotten
 * WHERE clause would need to forget two things at once to leak.
 */

import { queryOne, query } from "./db";
import { AuthError, getCurrentUser, type CurrentUser } from "./auth";

export class ForbiddenError extends Error {
  readonly status = 403;
  constructor(message = "You do not have access to this project.") {
    super(message);
    this.name = "ForbiddenError";
  }
}

export class NotFoundError extends Error {
  readonly status = 404;
  constructor(message = "Not found.") {
    super(message);
    this.name = "NotFoundError";
  }
}

export type Project = {
  id: string;
  name: string;
  project_date: string | null;
  description: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  /**
   * Newest of: the project's own updated_at, any document upload/parse, any
   * chat message. projects.updated_at alone is NOT sufficient -- the touch
   * trigger fires on the projects row only, so an upload would not bump it.
   */
  last_activity_at: string;
};

/**
 * Resolve a project the current user is allowed to see.
 *
 * Throws rather than returning null so a caller cannot forget to check:
 * an ignored return value would silently become "no access enforced".
 */
export async function requireProject(
  projectId: string | undefined | null,
  user?: CurrentUser,
): Promise<Project> {
  const u = user ?? (await getCurrentUser());

  if (!projectId || !isUuid(projectId)) {
    // A malformed id cannot belong to anyone; do not disclose which.
    throw new NotFoundError("Project not found.");
  }

  const row = await queryOne<Project>(
    `SELECT p.id, p.name, p.project_date, p.description, p.created_by,
            p.created_at, p.updated_at,
            GREATEST(p.updated_at,
                     COALESCE((SELECT MAX(d.updated_at) FROM isgec.documents d
                                WHERE d.project_id = p.id), p.updated_at),
                     COALESCE((SELECT MAX(s.updated_at) FROM isgec.chat_sessions s
                                WHERE s.project_id = p.id), p.updated_at)
            ) AS last_activity_at
       FROM isgec.projects p
      WHERE p.id = $1 AND p.created_by = $2`,
    [projectId, u.id],
  );

  if (!row) {
    // 404 rather than 403 on purpose: saying "forbidden" would confirm the
    // project id exists to someone probing for it.
    throw new NotFoundError("Project not found.");
  }
  return row;
}

/** Non-throwing variant for page components that want to render "gone". */
export async function findProject(
  projectId: string | undefined | null,
  user?: CurrentUser,
): Promise<Project | null> {
  try {
    return await requireProject(projectId, user);
  } catch {
    return null;
  }
}

/**
 * Verify a chat session sits inside the given project AND module.
 *
 * sessionId is equally untrusted from the browser: the join back to
 * chat_sessions is what proves the pair belongs together.
 */
export async function requireSession(
  sessionId: string | undefined | null,
  opts: { projectId: string; moduleType: string },
  user?: CurrentUser,
): Promise<{ id: string; project_id: string; module_type: string; title: string }> {
  const u = user ?? (await getCurrentUser());
  // ownership of the project is proven first
  await requireProject(opts.projectId, u);

  if (!sessionId || !isUuid(sessionId)) {
    throw new NotFoundError("Conversation not found.");
  }

  const row = await queryOne<{
    id: string;
    project_id: string;
    module_type: string;
    title: string;
  }>(
    `SELECT s.id, s.project_id, s.module_type, s.title
       FROM isgec.chat_sessions s
       JOIN isgec.projects p ON p.id = s.project_id
      WHERE s.id = $1 AND s.project_id = $2 AND s.module_type = $3
        AND p.created_by = $4`,
    [sessionId, opts.projectId, opts.moduleType, u.id],
  );

  if (!row) {
    throw new NotFoundError("Conversation not found.");
  }
  return row;
}

/** Verify a document belongs to the given project before reading it. */
export async function requireDocument(
  documentId: string | undefined | null,
  projectId: string,
  user?: CurrentUser,
) {
  const u = user ?? (await getCurrentUser());
  await requireProject(projectId, u);

  if (!documentId || !isUuid(documentId)) {
    throw new NotFoundError("Document not found.");
  }
  const row = await queryOne(
    `SELECT d.* FROM isgec.documents d
       JOIN isgec.projects p ON p.id = d.project_id
      WHERE d.id = $1 AND d.project_id = $2 AND p.created_by = $3`,
    [documentId, projectId, u.id],
  );
  if (!row) throw new NotFoundError("Document not found.");
  return row;
}

/** Module type must be one of the six the schema allows. */
export function assertModuleType(value: string): string {
  const MODULES = [
    "gearbox",
    "motor",
    "pump",
    "mechanical_equipment",
    "rfq_analysis",
    "general_chat",
  ] as const;
  if (!MODULES.includes(value as (typeof MODULES)[number])) {
    throw new NotFoundError(`Unknown module "${value}".`);
  }
  return value;
}

export function isUuid(v: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
}

/**
 * Only documents of THIS project ever reach the LLM context builder.
 * Called from the chat route; moduleId is optional scoping.
 * Returns only metadata (id, name, page_count) -- page text is loaded by
 * the Python side directly from the DB, so a 400-page RFQ does not travel
 * over the wire.
 */
export async function projectDocumentContext(
  projectId: string,
  user?: CurrentUser,
): Promise<Array<{ document_id: string; file_name: string; page_count: number | null }>> {
  const u = user ?? (await getCurrentUser());
  await requireProject(projectId, u);
  return query<{ document_id: string; file_name: string; page_count: number | null }>(
    `SELECT id AS document_id, file_name, page_count
       FROM isgec.documents
      WHERE project_id = $1 AND status = 'parsed'
      ORDER BY created_at ASC`,
    [projectId],
  );
}

/**
 * Vendor catalogue documents (from the system project) for a given vendor.
 * Returns metadata for parsed vendor catalogue PDFs.
 */
export async function vendorCatalogueDocumentContext(
  vendorId: number,
  user?: CurrentUser,
): Promise<Array<{ document_id: string; file_name: string; page_count: number | null }>> {
  const u = user ?? (await getCurrentUser());
  // System project for vendor catalogues
  const sysProjectId = '00000000-0000-0000-0000-000000000001';
  await requireProject(sysProjectId, u);
  return query<{ document_id: string; file_name: string; page_count: number | null }>(
    `SELECT id AS document_id, file_name, page_count
       FROM isgec.documents
      WHERE project_id = $1 AND status = 'parsed' AND metadata->>'vendor_id' = $2
      ORDER BY created_at ASC`,
    [sysProjectId, String(vendorId)],
  );
}

/** Map a thrown error to an HTTP status for route handlers. */
export function statusOf(err: unknown): number {
  if (err instanceof ForbiddenError || err instanceof NotFoundError) return err.status;
  if (err instanceof AuthError) return err.status;
  return 500;
}