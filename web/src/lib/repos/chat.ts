/**
 * Chat repository.
 *
 * A session id from the client is never trusted on its own: every read of
 * messages goes through a join back to chat_sessions that re-checks both
 * project_id and module_type. That join is the isolation boundary.
 */

import { query, queryOne, tx } from "../db";
import type { SelectionResult } from "@/components/assistant/types";

export type SessionRow = {
  id: string;
  project_id: string;
  module_type: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type MessageRow = {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
  /** The project this message belongs to -- injected by the route. */
  projectId?: string;
};

export async function listSessions(
  projectId: string,
  moduleType: string,
  ownerId: string,
): Promise<SessionRow[]> {
  return query<SessionRow>(
    `SELECT s.id, s.project_id, s.module_type, s.title, s.created_at, s.updated_at
       FROM isgec.chat_sessions s
       JOIN isgec.projects p ON p.id = s.project_id
      WHERE s.project_id = $1 AND s.module_type = $2 AND p.created_by = $3
      ORDER BY s.updated_at DESC`,
    [projectId, moduleType, ownerId],
  );
}

export async function createSession(
  projectId: string,
  moduleType: string,
  title: string,
  createdBy: string,
): Promise<SessionRow> {
  return queryOne<SessionRow>(
    `INSERT INTO isgec.chat_sessions (project_id, module_type, title, created_by)
          VALUES ($1, $2, $3, $4)
      RETURNING id, project_id, module_type, title, created_at, updated_at`,
    [projectId, moduleType, title.trim() || "New conversation", createdBy],
  ) as Promise<SessionRow>;
}

export async function deleteSession(
  sessionId: string,
  projectId: string,
  moduleType: string,
  ownerId: string,
): Promise<boolean> {
  const row = await queryOne<{ id: string }>(
    `DELETE FROM isgec.chat_sessions s USING isgec.projects p
      WHERE s.id = $1 AND s.project_id = $2 AND s.module_type = $3
        AND p.id = s.project_id AND p.created_by = $4
      RETURNING s.id`,
    [sessionId, projectId, moduleType, ownerId],
  );
  return row !== null;
}

/**
 * Messages for a session. projectId/moduleType are re-verified in the same
 * statement rather than trusted from a prior check, so a TOCTOU or a
 * forgotten parameter cannot widen the result set.
 */
export async function listMessages(
  sessionId: string,
  projectId: string,
  moduleType: string,
  ownerId: string,
): Promise<MessageRow[]> {
  return query<MessageRow>(
    `SELECT m.id, m.session_id, m.role, m.content, m.metadata, m.created_at,
            $1 AS projectId
       FROM isgec.chat_messages m
       JOIN isgec.chat_sessions s ON s.id = m.session_id
       JOIN isgec.projects p      ON p.id = s.project_id
      WHERE m.session_id = $2 AND s.project_id = $3
        AND s.module_type = $4 AND p.created_by = $5
      ORDER BY m.created_at ASC, m.id ASC`,
    [projectId, sessionId, projectId, moduleType, ownerId],
  );
}

/**
 * The most recent computed selection stored in this session, or null.
 *
 * A follow-up question ("why not the smaller one?") arrives with no
 * requirement attached, so the server would otherwise have no idea which model
 * the conversation is about. This is what lets the assistant answer about the
 * selection the user can actually see.
 *
 * Scoped by project + module + owner exactly like listMessages, so a selection
 * can never leak across projects.
 */
export async function latestSelection(
  sessionId: string,
  projectId: string,
  moduleType: string,
  ownerId: string,
): Promise<SelectionResult | null> {
  const rows = await query<MessageRow>(
    `SELECT m.metadata
       FROM isgec.chat_messages m
       JOIN isgec.chat_sessions s ON s.id = m.session_id
       JOIN isgec.projects p      ON p.id = s.project_id
      WHERE m.session_id = $1 AND s.project_id = $2
        AND s.module_type = $3 AND p.created_by = $4
        AND m.metadata ? 'selection'
      ORDER BY m.created_at DESC, m.id DESC
      LIMIT 1`,
    [sessionId, projectId, moduleType, ownerId],
  );
  const meta = rows[0]?.metadata as { selection?: SelectionResult } | null | undefined;
  // Guard on model rather than trusting the row: a hand-edited or partial
  // metadata blob must not reach the prompt as if it were a real selection.
  return meta?.selection?.model ? meta.selection : null;
}

/** Append a user message + assistant reply atomically so a crash cannot
 *  leave a session with half a turn. */
export async function appendTurn(input: {
  sessionId: string;
  userContent: string;
  userMetadata?: Record<string, unknown> | null;
  assistantContent: string;
  assistantMetadata?: Record<string, unknown> | null;
  sessionTitle?: string | null;
}): Promise<MessageRow[]> {
  return tx(async (client) => {
    const user = await client.query(
      `INSERT INTO isgec.chat_messages (session_id, role, content, metadata)
            VALUES ($1, 'user', $2, $3)
        RETURNING id, session_id, role, content, metadata, created_at`,
      [
        input.sessionId,
        input.userContent,
        input.userMetadata ? JSON.stringify(input.userMetadata) : null,
      ],
    );
    const assistant = await client.query(
      `INSERT INTO isgec.chat_messages (session_id, role, content, metadata)
            VALUES ($1, 'assistant', $2, $3)
        RETURNING id, session_id, role, content, metadata, created_at`,
      [
        input.sessionId,
        input.assistantContent,
        input.assistantMetadata ? JSON.stringify(input.assistantMetadata) : null,
      ],
    );
    // Only the *first* message titles the conversation. The CASE has to guard
    // on the existing title rather than letting the new one win, otherwise
    // every follow-up renames the thread and the rail ends up listing
    // "Why not the K3?" instead of what the conversation is about.
    await client.query(
      `UPDATE isgec.chat_sessions
          SET updated_at = now(),
              title = CASE
                        WHEN title IS NULL OR btrim(title) = ''
                             OR title = 'New conversation'
                          THEN COALESCE(NULLIF($2, ''), left($3, 60), 'New conversation')
                        ELSE title
                      END
        WHERE id = $1`,
      [input.sessionId, input.sessionTitle ?? "", input.userContent],
    );
    return [...user.rows, ...assistant.rows] as MessageRow[];
  });
}

/**
 * Imported-context messages for a session.
 *
 * An import is stored as a normal `system` row whose metadata carries an
 * `import` block (source project/session). Every later turn re-reads these and
 * feeds them to the model, which is what makes an imported conversation stay
 * "remembered" for the rest of the thread.
 */
export async function listImportContext(
  sessionId: string,
  projectId: string,
  moduleType: string,
  ownerId: string,
): Promise<MessageRow[]> {
  return query<MessageRow>(
    `SELECT m.id, m.session_id, m.role, m.content, m.metadata, m.created_at,
            $1 AS projectId
       FROM isgec.chat_messages m
       JOIN isgec.chat_sessions s ON s.id = m.session_id
       JOIN isgec.projects p      ON p.id = s.project_id
      WHERE m.session_id = $2 AND s.project_id = $3
        AND s.module_type = $4 AND p.created_by = $5
        AND m.role = 'system' AND m.metadata ? 'import'
      ORDER BY m.created_at ASC, m.id ASC`,
    [projectId, sessionId, projectId, moduleType, ownerId],
  );
}

/** Persist one imported-context message into the target session. */
export async function appendImportMessage(input: {
  sessionId: string;
  content: string;
  metadata: Record<string, unknown>;
}): Promise<MessageRow> {
  return tx(async (client) => {
    const { rows } = await client.query(
      `INSERT INTO isgec.chat_messages (session_id, role, content, metadata)
            VALUES ($1, 'system', $2, $3)
        RETURNING id, session_id, role, content, metadata, created_at`,
      [input.sessionId, input.content, JSON.stringify(input.metadata)],
    );
    await client.query(
      `UPDATE isgec.chat_sessions SET updated_at = now() WHERE id = $1`,
      [input.sessionId],
    );
    return rows[0] as MessageRow;
  });
}

/** Derive a session title from the first user message. */
export function deriveTitle(text: string): string {
  const line = text.trim().split("\n")[0];
  return line.length > 60 ? `${line.slice(0, 57)}...` : line || "New conversation";
}