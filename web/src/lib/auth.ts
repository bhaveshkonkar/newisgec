/**
 * Current-user identity.
 *
 * Phase 2 runs single-user: the id comes from DEV_USER_ID and is checked
 * against isgec.profiles on every request, so an unknown id fails closed
 * instead of silently acting as nobody.
 *
 * Phase 14 swaps `getCurrentUser()` to Supabase Auth. Nothing else in the
 * codebase reads the identity directly -- every request-scoped handler
 * goes through here, so the swap is confined to this file.
 */

export type CurrentUser = {
  id: string;
  email: string | null;
  fullName: string;
  initials: string;
  isAdmin: boolean;
};

export class AuthError extends Error {
  readonly status: number;
  constructor(message: string, status = 401) {
    super(message);
    this.name = "AuthError";
    this.status = status;
  }
}

import { queryOne } from "./db";
import { initialsOf } from "./utils";

export async function getCurrentUser(): Promise<CurrentUser> {
  const id = process.env.DEV_USER_ID?.trim();

  if (!id) {
    throw new AuthError(
      "No user identity configured. Set DEV_USER_ID in .env.local " +
        "(Phase 14 replaces this with Supabase Auth).",
      500,
    );
  }

  const row = await queryOne<{
    id: string;
    email: string | null;
    full_name: string;
    initials: string | null;
    is_admin: boolean;
  }>("SELECT id, email, full_name, initials, is_admin FROM isgec.profiles WHERE id = $1", [
    id,
  ]);

  if (!row) {
    // fail closed: a configured-but-missing profile must never read as
    // "no user, allow anonymous"
    throw new AuthError(
      `Profile ${id} is not in isgec.profiles. Run scripts/migrate_isgec.py.`,
      401,
    );
  }

  return {
    id: row.id,
    email: row.email,
    fullName: row.full_name,
    initials: row.initials ?? initialsOf(row.full_name),
    isAdmin: row.is_admin,
  };
}