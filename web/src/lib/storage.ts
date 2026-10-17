/**
 * File storage.
 *
 * Local disk today, Supabase Storage in Phase 14. Every caller goes
 * through these four functions so the swap is confined to this file --
 * nothing else in the app knows what a "path" means.
 *
 * Paths are always relative and always namespaced by project id, so a
 * project can only ever address files inside its own folder even if a
 * client hands us a hostile path.
 */

import { createHash, randomUUID } from "node:crypto";
import { mkdir, rm, readFile, stat } from "node:fs/promises";
import path from "node:path";

const UPLOAD_ROOT =
  process.env.UPLOAD_DIR ?? "D:/gearbox-selector/data/uploads";

function projectDir(projectId: string): string {
  // projectId is a validated UUID by the time it reaches here; still refuse
  // anything that is not, rather than trusting the folder name.
  if (!/^[0-9a-f-]{36}$/i.test(projectId)) {
    throw new Error("invalid project id for storage path");
  }
  return path.join(UPLOAD_ROOT, projectId);
}

export function resolveInProject(projectId: string, relative: string): string {
  const base = projectDir(projectId);
  const full = path.resolve(base, relative);
  // containment check: the resolved path must stay inside the project folder
  if (full !== base && !full.startsWith(base + path.sep)) {
    throw new Error("path escapes project storage");
  }
  return full;
}

function safeName(fileName: string): string {
  // strip directory components and anything exotic
  const base = path.basename(fileName).replace(/[^\w.\- ]+/g, "_").trim();
  return base.slice(0, 120) || "document.pdf";
}

export async function putFile(
  projectId: string,
  fileName: string,
  bytes: Buffer,
): Promise<{ storagePath: string; fileSize: number }> {
  const dir = projectDir(projectId);
  await mkdir(dir, { recursive: true });

  const clean = safeName(fileName);
  const stamp = new Date().toISOString().slice(0, 10);
  const key = `${stamp}__${randomUUID().slice(0, 8)}__${clean}`;
  const full = path.join(dir, key);

  await import("node:fs/promises").then((fs) => fs.writeFile(full, bytes));
  return { storagePath: key, fileSize: bytes.length };
}

export async function readFileFromStorage(
  projectId: string,
  storagePath: string,
): Promise<Buffer> {
  return readFile(resolveInProject(projectId, storagePath));
}

export async function fileExists(projectId: string, storagePath: string): Promise<boolean> {
  try {
    await stat(resolveInProject(projectId, storagePath));
    return true;
  } catch {
    return false;
  }
}

export async function deleteFile(projectId: string, storagePath: string): Promise<void> {
  await rm(resolveInProject(projectId, storagePath), { force: true });
}

/** Called after the project row is gone (cascade already removed documents). */
export async function deleteProjectDir(projectId: string): Promise<void> {
  await rm(projectDir(projectId), { recursive: true, force: true });
}

/** Content hash used to skip re-parsing an identical upload. */
export function sha256(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

export const MAX_UPLOAD_BYTES = 64 * 1024 * 1024;

export function assertPdf(fileName: string, mimeType: string, size: number): void {
  if (!fileName.toLowerCase().endsWith(".pdf") && mimeType !== "application/pdf") {
    throw new Error("Only PDF uploads are supported.");
  }
  if (size === 0) throw new Error("File is empty.");
  if (size > MAX_UPLOAD_BYTES) {
    throw new Error(`File is larger than ${MAX_UPLOAD_BYTES / 1024 / 1024} MB.`);
  }
}