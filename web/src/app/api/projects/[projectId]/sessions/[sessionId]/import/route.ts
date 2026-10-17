import { NextResponse } from "next/server";
import { z } from "zod";
import { getCurrentUser } from "@/lib/auth";
import {
  requireSession,
  assertModuleType,
  statusOf,
  NotFoundError,
} from "@/lib/permissions";
import {
  listMessages,
  appendImportMessage,
} from "@/lib/repos/chat";
import { getProject } from "@/lib/repos/projects";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ projectId: string; sessionId: string }> };

const Import = z.object({
  source_project_id: z.string().uuid(),
  source_session_id: z.string().uuid(),
  module_type: z.string().default("gearbox"),
});

/** Keep the imported transcript inside the grounding budget. */
const MAX_IMPORT_CHARS = 8000;

/**
 * POST -> import another conversation's transcript into this session.
 *
 * The imported chat is persisted as a `system` message carrying an `import`
 * metadata block, so every later turn re-reads it (see listImportContext) and
 * the model keeps the imported context "remembered" for the thread. Both the
 * target and the source are verified against the caller via requireSession, so
 * a client cannot import another user's conversation by guessing an id.
 */
export async function POST(req: Request, { params }: Ctx) {
  try {
    const { projectId, sessionId } = await params;
    const user = await getCurrentUser();

    const parsed = Import.safeParse(await req.json().catch(() => ({})));
    if (!parsed.success) {
      return NextResponse.json(
        { error: parsed.error.issues[0]?.message ?? "Invalid input" },
        { status: 400 },
      );
    }
    const moduleType = assertModuleType(parsed.data.module_type);
    const { source_project_id, source_session_id } = parsed.data;

    // target: proves this conversation belongs to the caller
    await requireSession(sessionId, { projectId, moduleType }, user);
    // source: proves the conversation being imported also belongs to the caller
    const source = await requireSession(
      source_session_id,
      { projectId: source_project_id, moduleType },
      user,
    );

    const sourceMessages = await listMessages(
      source_session_id,
      source_project_id,
      moduleType,
      user.id,
    );
    const transcript = buildTranscript(sourceMessages, MAX_IMPORT_CHARS);
    if (!transcript) {
      return NextResponse.json(
        { error: "That conversation has no messages to import." },
        { status: 400 },
      );
    }

    const sourceProject = await getProject(source_project_id, user.id);

    const content = [
      `Imported conversation: "${source.title}"`,
      `from project "${sourceProject?.name ?? "unknown"}"`,
      "(treated as prior context for this thread).",
      "",
      transcript,
    ].join("\n");

    const message = await appendImportMessage({
      sessionId,
      content,
      metadata: {
        import: {
          project_id: source_project_id,
          project_name: sourceProject?.name ?? null,
          session_id: source_session_id,
          session_title: source.title,
          message_count: sourceMessages.length,
        },
      },
    });

    return NextResponse.json({ message }, { status: 201 });
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to import conversation" },
      { status },
    );
  }
}

/** Compact, most-recent-first-trimmed transcript the model can read. */
function buildTranscript(
  messages: Array<{ role: string; content: string }>,
  maxChars: number,
): string {
  const turns = messages.filter(
    (m) => (m.role === "user" || m.role === "assistant") && m.content.trim(),
  );
  if (turns.length === 0) return "";

  const lines: string[] = [];
  for (const m of turns) {
    const who = m.role === "user" ? "USER" : "ASSISTANT";
    lines.push(`${who}: ${m.content.trim()}`);
  }

  let text = lines.join("\n\n");
  if (text.length <= maxChars) return text;

  // Over budget: keep the tail (most recent) and mark the cut.
  text = text.slice(text.length - maxChars);
  // Do not start mid-token: drop the first partial line.
  const nl = text.indexOf("\n");
  if (nl > 0 && nl < 80) text = text.slice(nl + 1);
  return "(earlier messages trimmed)\n\n" + text;
}
