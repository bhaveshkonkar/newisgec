/**
 * Parse dispatch.
 *
 * A document row is created 'uploaded' and then handed to the Python
 * parser out of band. The request never waits for a parse: a 200-page RFQ
 * takes tens of seconds and would blow past any proxy timeout.
 *
 * Because this runs after the HTTP response, nothing re-queues it if the
 * Node process dies mid-parse. recoverStaleDocuments() runs at boot for
 * exactly that case, so an interrupted parse is retried rather than
 * stranded in 'processing' forever.
 */

import { markProcessing, markParsed, markFailed, listStaleProcessing } from "./repos/documents";
import { pythonParsePdf } from "./python";

/** Largest excerpt kept per document. Enough for grounding, bounded for storage. */
const MAX_TEXT_CHARS = 400_000;

const inFlight = new Set<string>();

export async function dispatchParse(
  documentId: string,
  projectId: string,
  storagePath: string,
): Promise<void> {
  if (inFlight.has(documentId)) return;
  inFlight.add(documentId);

  const { fileName } = await documentName(documentId);

  try {
    await markProcessing(documentId);
    const res = await pythonParsePdf(projectId, storagePath, fileName);

    if (!res.ok) {
      await markFailed(documentId, res.error);
      return;
    }

    const { text, pages, page_count, metadata, parser_version } = res.data;
    await markParsed(documentId, {
      extractedText: (text ?? "").slice(0, MAX_TEXT_CHARS),
      metadata: metadata ?? {},
      pageCount: page_count ?? null,
      parserVersion: parser_version ?? "unknown",
      // Page text is what makes a citation possible, so it is stored rather
      // than only concatenated into `extractedText`. If the parser predates
      // per-page output the array is undefined and the document parses without
      // page rows -- detected and repaired by listDocumentsMissingPages.
      pages: pages ?? [],
    });
  } catch (err) {
    await markFailed(documentId, err instanceof Error ? err.message : "parse failed").catch(
      () => {},
    );
  } finally {
    inFlight.delete(documentId);
  }
}

/**
 * Re-queue anything left mid-flight by a restart. Called once from the
 * instrumented server entry, not per request.
 */
export async function recoverStaleDocuments(): Promise<number> {
  const stale = await listStaleProcessing();
  if (stale.length === 0) return 0;

  console.warn(`[documents] re-queueing ${stale.length} interrupted parse(s)`);
  for (const row of stale) {
    if (!row.storage_path) {
      await markFailed(row.id, "parse interrupted and file path is unknown");
      continue;
    }
    void dispatchParse(row.id, row.project_id, row.storage_path).catch((e) =>
      console.error("[documents] recovery parse failed:", e),
    );
  }
  return stale.length;
}

// tiny helper kept local so dispatchParse does not need a second DB call
import { queryOne } from "./db";
async function documentName(id: string): Promise<{ fileName: string }> {
  const row = await queryOne<{ file_name: string }>(
    "SELECT file_name FROM isgec.documents WHERE id = $1",
    [id],
  );
  return { fileName: row?.file_name ?? "document.pdf" };
}