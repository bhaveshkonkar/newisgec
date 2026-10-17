import { Pool, types } from "pg";

/**
 * Postgres DATE (1082) has no timezone, but `pg` hands it back as a JS Date
 * at *local* midnight. Once that is JSON.stringify'd, toJSON() converts it
 * to UTC and a project dated 2023-11-17 leaves the API as 2023-11-16T18:30Z.
 * Returning the driver's own 'YYYY-MM-DD' string removes the round-trip.
 */
types.setTypeParser(types.builtins.DATE, (v) => v);

/**
 * Single shared pool.
 *
 * Next's dev server re-evaluates modules on hot reload, which would leak a
 * new Pool per edit until Postgres refuses connections -- so the pool is
 * parked on globalThis.
 */
const globalForPg = globalThis as unknown as { __isgecPool?: Pool };

export const pool: Pool =
  globalForPg.__isgecPool ??
  new Pool({
    connectionString:
      process.env.DATABASE_URL ??
      "postgresql://gearbox:gearbox@localhost:5433/gearbox",
    max: 10,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 10_000,
  });

if (process.env.NODE_ENV !== "production") {
  globalForPg.__isgecPool = pool;
}

pool.on("error", (err) => {
  // An idle client died (DB restart). Log and let the pool recycle.
  console.error("[db] idle client error:", err.message);
});

export type SqlParam = string | number | boolean | null | Date | object;

/** `query` for one-off reads; `tx` for anything multi-statement. */
export async function query<T = Record<string, unknown>>(
  text: string,
  params: SqlParam[] = [],
): Promise<T[]> {
  const res = await pool.query(text, params);
  return res.rows as T[];
}

export async function queryOne<T = Record<string, unknown>>(
  text: string,
  params: SqlParam[] = [],
): Promise<T | null> {
  const rows = await query<T>(text, params);
  return rows[0] ?? null;
}

/**
 * Run `fn` inside a transaction, rolling back on any throw.
 * Used by project creation (project row + 6 module rows must be atomic).
 */
export async function tx<T>(
  fn: (client: import("pg").PoolClient) => Promise<T>,
): Promise<T> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const out = await fn(client);
    await client.query("COMMIT");
    return out;
  } catch (err) {
    await client.query("ROLLBACK").catch(() => {});
    throw err;
  } finally {
    client.release();
  }
}