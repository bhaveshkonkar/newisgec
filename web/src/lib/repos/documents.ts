/**
 * Document repository.
 *
 * project_id is always a bound parameter and is always the *resolved*
 * project (from requireProject), never a raw client value.
 */

import { query, queryOne, tx } from "../db";

export type DocumentStatus = "uploaded" | "processing" | "parsed" | "failed";

export type DocRow = {
  id: string;
  project_id: string;
  module_id: string | null;
  file_name: string;
  storage_path: string | null;
  file_size: string | null;
  mime_type: string | null;
  status: DocumentStatus;
  extracted_text: string | null;
  metadata: Record<string, unknown> | null;
  page_count: number | null;
  parser_version: string | null;
  error_detail: string | null;
  uploaded_by: string | null;
  created_at: string;
  updated_at: string;
};

const COLS = `id, project_id, module_id, file_name, storage_path, file_size,
              mime_type, status, extracted_text, metadata, page_count,
              parser_version, error_detail, uploaded_by, created_at, updated_at`;

export async function listDocuments(
  projectId: string,
  ownerId: string,
): Promise<DocRow[]> {
  return query<DocRow>(
    `SELECT ${COLS.split(",").map((c) => "d." + c.trim()).join(", ")}
       FROM isgec.documents d
       JOIN isgec.projects p ON p.id = d.project_id
      WHERE d.project_id = $1 AND p.created_by = $2
      ORDER BY d.created_at DESC`,
    [projectId, ownerId],
  );
}

export async function createDocument(input: {
  projectId: string;
  moduleId?: string | null;
  fileName: string;
  storagePath: string;
  fileSize: number;
  mimeType: string;
  uploadedBy: string;
}): Promise<DocRow> {
  return queryOne<DocRow>(
    `INSERT INTO isgec.documents
       (project_id, module_id, file_name, storage_path, file_size, mime_type,
        status, uploaded_by)
     VALUES ($1, $2, $3, $4, $5, $6, 'uploaded', $7)
     RETURNING ${COLS}`,
    [
      input.projectId,
      input.moduleId ?? null,
      input.fileName,
      input.storagePath,
      input.fileSize,
      input.mimeType,
      input.uploadedBy,
    ],
  ) as Promise<DocRow>;
}

export async function markProcessing(id: string): Promise<void> {
  await query(
    "UPDATE isgec.documents SET status = 'processing', error_detail = NULL WHERE id = $1",
    [id],
  );
}

export async function markParsed(
  id: string,
  data: {
    extractedText: string;
    metadata: Record<string, unknown>;
    pageCount: number | null;
    parserVersion: string;
    /**
     * Per-page text, 1-based. Stored separately from `extractedText` so a
     * citation can name the page it came from. Replacing rather than merging:
     * a re-parse of a changed file must not leave pages from the previous
     * version behind, and orphaned page rows would cite content that is no
     * longer in the PDF.
     */
    pages?: Array<{ page_no: number; text: string }>;
  },
): Promise<void> {
  await tx(async (client) => {
    await client.query(
      `UPDATE isgec.documents
          SET status = 'parsed', extracted_text = $2, metadata = $3,
              page_count = $4, parser_version = $5, error_detail = NULL
        WHERE id = $1`,
      [id, data.extractedText, JSON.stringify(data.metadata), data.pageCount, data.parserVersion],
    );
    if (data.pages) {
      await client.query("DELETE FROM isgec.document_pages WHERE document_id = $1", [id]);
      for (const p of data.pages) {
        await client.query(
          `INSERT INTO isgec.document_pages (document_id, page_no, char_count, text)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (document_id, page_no) DO NOTHING`,
          [id, p.page_no, p.text.length, p.text],
        );
      }
    }
  });
}

export async function markFailed(id: string, detail: string): Promise<void> {
  // A failed re-parse invalidates the previous page rows: the file on disk may
  // be a different revision, so citing a page from it would point at content
  // that is no longer there. Drop them and let the document show as un-parsed
  // rather than confidently citing a stale page.
  await tx(async (client) => {
    await client.query(
      "UPDATE isgec.documents SET status = 'failed', error_detail = $2 WHERE id = $1",
      [id, detail.slice(0, 1000)],
    );
    await client.query("DELETE FROM isgec.document_pages WHERE document_id = $1", [id]);
  });
}

/**
 * Every page of every parsed document in the project, for retrieval and
 * citations. Ordered so page numbers stay ascending per document.
 */
export async function listDocumentPages(
  projectId: string,
  ownerId: string,
): Promise<Array<{ document_id: string; file_name: string; page_no: number; text: string }>> {
  return query<{ document_id: string; file_name: string; page_no: number; text: string }>(
    `SELECT p.document_id, d.file_name, p.page_no, p.text
       FROM isgec.document_pages p
       JOIN isgec.documents d ON d.id = p.document_id
       JOIN isgec.projects pr ON pr.id = d.project_id
      WHERE d.project_id = $1 AND pr.created_by = $2 AND d.status = 'parsed'
      ORDER BY p.document_id, p.page_no`,
    [projectId, ownerId],
  );
}

/** Parsed documents that have no stored pages: parsed by an older parser. */
export async function listDocumentsMissingPages(
  projectId: string,
  ownerId: string,
): Promise<Array<{ id: string; storage_path: string | null }>> {
  return query<{ id: string; storage_path: string | null }>(
    `SELECT d.id, d.storage_path
       FROM isgec.documents d
       JOIN isgec.projects p ON p.id = d.project_id
      WHERE d.project_id = $1 AND p.created_by = $2 AND d.status = 'parsed'
        AND NOT EXISTS (SELECT 1 FROM isgec.document_pages pg WHERE pg.document_id = d.id)
      ORDER BY d.created_at ASC`,
    [projectId, ownerId],
  );
}

export async function deleteDocument(id: string, projectId: string, ownerId: string) {
  return queryOne<{ id: string; storage_path: string | null }>(
    `DELETE FROM isgec.documents d USING isgec.projects p
      WHERE d.id = $1 AND d.project_id = $2 AND p.id = d.project_id AND p.created_by = $3
      RETURNING d.id, d.storage_path`,
    [id, projectId, ownerId],
  );
}

/**
 * Rows stuck in 'processing' after a restart. Re-queued on server boot so an
 * interrupted parse is not stranded forever.
 */
export async function listStaleProcessing(): Promise<
  Array<{ id: string; project_id: string; storage_path: string | null }>
> {
  return query(
    `SELECT id, project_id, storage_path FROM isgec.documents
      WHERE status = 'processing' ORDER BY created_at ASC`,
  );
}

export async function countParsedDocs(projectId: string): Promise<number> {
  const row = await queryOne<{ n: string }>(
    "SELECT COUNT(*)::text AS n FROM isgec.documents WHERE project_id = $1 AND status = 'parsed'",
    [projectId],
  );
  return row ? Number(row.n) : 0;
}