/**
 * Project repository.
 *
 * Every read/write carries the owner id, so isolation is enforced by the
 * WHERE clause rather than by remembering to check a return value.
 */

import { query, queryOne, tx, type SqlParam } from "../db";
import type { Project } from "../permissions";

type ProjectRow = Project;

export type ProjectSummary = {
  id: string;
  name: string;
  project_date: string | null;
  description: string | null;
  created_at: string;
  updated_at: string;
  document_count: number;
  parsed_count: number;
  last_activity_at: string;
};

export async function listProjects(
  ownerId: string,
  opts: { recent?: boolean; search?: string } = {},
): Promise<ProjectSummary[]> {
  const params: SqlParam[] = [ownerId];
  let where = "p.created_by = $1";
  if (opts.search?.trim()) {
    params.push(`%${opts.search.trim()}%`);
    where += ` AND (p.name ILIKE $${params.length} OR COALESCE(p.description,'') ILIKE $${params.length})`;
  }

  const rows = await query<ProjectRow & { document_count: string; parsed_count: string; last_activity_at: string }>(
    `SELECT p.id, p.name, p.project_date, p.description,
            p.created_at, p.updated_at,
            COUNT(d.id)::text                                     AS document_count,
            COUNT(d.id) FILTER (WHERE d.status = 'parsed')::text    AS parsed_count,
            GREATEST(p.updated_at, COALESCE(MAX(d.updated_at), p.updated_at)) AS last_activity_at
       FROM isgec.projects p
       LEFT JOIN isgec.documents d ON d.project_id = p.id
      WHERE ${where}
      GROUP BY p.id
      ORDER BY last_activity_at DESC`,
    params,
  );

  return rows.map((r) => ({
    id: r.id,
    name: r.name,
    project_date: r.project_date,
    description: r.description,
    created_at: r.created_at,
    updated_at: r.updated_at,
    document_count: Number(r.document_count),
    parsed_count: Number(r.parsed_count),
    last_activity_at: r.last_activity_at,
  }));
}

const PROJECT_COLS = `id, name, project_date, description, created_by, created_at, updated_at`;

export async function getProject(id: string, ownerId: string): Promise<ProjectRow | null> {
  return queryOne<ProjectRow>(
    `SELECT ${PROJECT_COLS},
            GREATEST(updated_at,
                     COALESCE((SELECT MAX(d.updated_at) FROM isgec.documents d
                                WHERE d.project_id = isgec.projects.id), updated_at),
                     COALESCE((SELECT MAX(s.updated_at) FROM isgec.chat_sessions s
                                WHERE s.project_id = isgec.projects.id), updated_at)
            ) AS last_activity_at
       FROM isgec.projects
      WHERE id = $1 AND created_by = $2`,
    [id, ownerId],
  );
}

export async function createProject(
  ownerId: string,
  input: { name: string; project_date?: string | null; description?: string | null },
): Promise<ProjectRow> {
  return tx(async (client) => {
    const { rows } = await client.query(
      `INSERT INTO isgec.projects (name, project_date, description, created_by)
            VALUES ($1, $2, $3, $4)
            RETURNING ${PROJECT_COLS}, updated_at AS last_activity_at`,
      [
        input.name.trim(),
        input.project_date || null,
        input.description?.trim() || null,
        ownerId,
      ],
    );
    const project = rows[0] as ProjectRow;

    // One logical workspace per module, created up front (see init/05).
    // In the same transaction so a project never exists half-wired.
    await client.query(
      `INSERT INTO isgec.project_modules (project_id, module_type, enabled)
       SELECT $1, m, (m = 'gearbox')
         FROM unnest(isgec.default_module_types()) AS m
       ON CONFLICT (project_id, module_type) DO NOTHING`,
      [project.id],
    );

    return project;
  });
}

/**
 * Partial update.
 *
 * Built dynamically rather than with COALESCE($n, column): COALESCE cannot
 * distinguish "field omitted" from "field explicitly set to null", so a
 * caller clearing a description or project_date would silently be ignored.
 * An omitted key means "leave alone"; an explicit null means "clear".
 */
export async function updateProject(
  id: string,
  ownerId: string,
  patch: { name?: string; project_date?: string | null; description?: string | null },
): Promise<ProjectRow | null> {
  const sets: string[] = [];
  const params: SqlParam[] = [id, ownerId];

  const push = (column: string, value: Exclude<SqlParam, undefined>) => {
    params.push(value);
    sets.push(`${column} = $${params.length}`);
  };

  if (patch.name !== undefined) push("name", patch.name.trim());
  if (patch.project_date !== undefined) {
    push("project_date", patch.project_date || null);
  }
  if (patch.description !== undefined) push("description", patch.description?.trim() || null);

  if (sets.length === 0) return getProject(id, ownerId);

  return queryOne<ProjectRow>(
    `UPDATE isgec.projects
        SET ${sets.join(", ")}
      WHERE id = $1 AND created_by = $2
      RETURNING ${PROJECT_COLS},
                GREATEST(updated_at,
                         COALESCE((SELECT MAX(d.updated_at) FROM isgec.documents d
                                    WHERE d.project_id = isgec.projects.id), updated_at),
                         COALESCE((SELECT MAX(s.updated_at) FROM isgec.chat_sessions s
                                    WHERE s.project_id = isgec.projects.id), updated_at)
                ) AS last_activity_at`,
    params,
  );
}

/**
 * Delete the project. Documents and chats go with it via ON DELETE CASCADE;
 * the files on disk are swept by the caller's storage.deleteProject.
 */
export async function deleteProject(id: string, ownerId: string): Promise<boolean> {
  const row = await queryOne<{ id: string }>(
    "DELETE FROM isgec.projects WHERE id = $1 AND created_by = $2 RETURNING id",
    [id, ownerId],
  );
  return row !== null;
}

export async function listModules(projectId: string, ownerId: string) {
  return query<{ id: string; module_type: string; enabled: boolean }>(
    `SELECT m.id, m.module_type, m.enabled
       FROM isgec.project_modules m
       JOIN isgec.projects p ON p.id = m.project_id
      WHERE m.project_id = $1 AND p.created_by = $2
      ORDER BY array_position(isgec.default_module_types(), m.module_type)`,
    [projectId, ownerId],
  );
}

/** Bumps project.updated_at so "Recent" reflects document/session activity. */
export async function touchProject(projectId: string, client?: import("pg").PoolClient) {
  const sql = "UPDATE isgec.projects SET updated_at = now() WHERE id = $1";
  if (client) await client.query(sql, [projectId]);
  else await query(sql, [projectId]);
}