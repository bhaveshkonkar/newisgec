import { NextResponse } from "next/server";
import { z } from "zod";
import { getCurrentUser } from "@/lib/auth";
import {
  requireProject,
  requireSession,
  assertModuleType,
  statusOf,
  NotFoundError,
  projectDocumentContext,
  vendorCatalogueDocumentContext,
} from "@/lib/permissions";
import { listMessages, appendTurn, deriveTitle } from "@/lib/repos/chat";
import { pythonSelect, pythonExplain, type SelectionResult } from "@/lib/python";

export const dynamic = "force-dynamic";
// the LLM leg can take a while
export const maxDuration = 300;

type Ctx = { params: Promise<{ projectId: string; sessionId: string }> };

const Send = z.object({
  message: z.string().trim().min(1, "Message cannot be empty").max(8000),
  module_type: z.string().default("gearbox"),
  /**
   * Optional structured requirement. When present the deterministic engine
   * runs first and its result is handed to the LLM as authoritative context,
   * so the model explains a real selection instead of inventing one.
   *
   * `.nullable()` as well as `.optional()`: a follow-up question has no
   * requirement, and the client sends an explicit `null` rather than
   * omitting the key. Without this, every plain-text question failed
   * validation with "Expected object, received null".
   */
  selection_request: z
    .object({
      // `.nullish()`, not `.optional()`: a blank field reaches this schema as
      // an explicit `null` (RequirementForm sends `numeric(ratio) ?? null`),
      // and `.optional()` only admits `undefined`. `null` therefore failed
      // with "Expected number, received null" and the whole turn -- selection,
      // explanation and persistence -- never ran. Every `??` below turns a
      // null we accept back into the documented default.
      pn: z
        .number({ message: "Required power (kW) is required and must be a number" })
        .positive({ message: "Required power (kW) must be a positive number" }),
      ratio_req: z.number().positive().nullish(),
      sf: z.number().positive().max(10).nullish(),
      // Not int(): real nameplate speeds are 1440, 1420, 960, 1780 rpm. The engine
      // snaps to the nearest catalogue rating speed and reports the shift.
      n1_rpm: z.number().positive().nullish(),
      cooling_type: z.string().nullish(),
      gear_type: z.enum(["any", "helical", "bevel_helical"]).nullish(),
      mounting_type: z.enum(["any", "foot", "torque_arm"]).nullish(),
      series: z.string().nullish(),
      vendor_id: z.number().int().positive().nullish(),
    })
    .nullable()
    .optional(),
});

/** GET -> the transcript for this session. */
export async function GET(_req: Request, { params }: Ctx) {
  try {
    const { projectId, sessionId } = await params;
    const user = await getCurrentUser();
    const moduleType = assertModuleType(
      new URL(_req.url).searchParams.get("module") ?? "gearbox",
    );
    await requireSession(sessionId, { projectId, moduleType }, user);
    const messages = await listMessages(sessionId, projectId, moduleType, user.id);
    return NextResponse.json({ messages });
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to load messages" },
      { status },
    );
  }
}

/**
 * POST -> one turn: user message in, assistant reply out.
 *
 * Order of operations matters:
 *   1. authorisation (session -> project -> owner)
 *   2. deterministic selection, if a requirement was supplied
 *   3. LLM explanation grounded on that selection + THIS project's documents
 *   4. persist both messages in one transaction
 *
 * If the LLM leg fails the turn is still saved, with the deterministic
 * result as the reply -- a Groq outage must not lose the user's question.
 */
export async function POST(req: Request, { params }: Ctx) {
  let projectId: string;
  let sessionId: string;
  let moduleType: string;
  let text: string;
  let selectionRequest: z.infer<typeof Send>["selection_request"];
  let userId: string;

  try {
    ({ projectId, sessionId } = await params);
    const user = await getCurrentUser();
    userId = user.id;

    const parsed = Send.safeParse(await req.json().catch(() => ({})));
    if (!parsed.success) {
      return NextResponse.json(
        { error: parsed.error.issues[0]?.message ?? "Invalid input" },
        { status: 400 },
      );
    }
    moduleType = assertModuleType(parsed.data.module_type);
    text = parsed.data.message;
    selectionRequest = parsed.data.selection_request;

    await requireSession(sessionId, { projectId, moduleType }, user);
  } catch (err) {
    const status = err instanceof NotFoundError ? 404 : statusOf(err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Request rejected" },
      { status },
    );
  }

  // ---- 2. deterministic selection -------------------------------------
  let selection: SelectionResult | null = null;
  let shortlist: SelectionResult[] = [];
  let selectionError: string | null = null;

  if (selectionRequest) {
    const res = await pythonSelect({
      pn: selectionRequest.pn,
      ratio_req: selectionRequest.ratio_req,
      sf: selectionRequest.sf ?? 1.0,
      n1_rpm: selectionRequest.n1_rpm ?? 1500,
      cooling_type: selectionRequest.cooling_type ?? "FAN",
      gear_type: selectionRequest.gear_type ?? "any",
      mounting_type: selectionRequest.mounting_type ?? "any",
      series: selectionRequest.series ?? null,
      vendor_id: selectionRequest.vendor_id ?? null,
    });
    if (res.ok && res.data.results.length > 0) {
      selection = res.data.results[0];
      // Keep the runners-up so the reply can show the alternatives that were
      // actually considered. The engine already ranks them, so the shortlist
      // is the real decision trail, not a fresh guess.
      shortlist = res.data.results.slice(0, 3);
    } else if (!res.ok) {
      selectionError = res.error;
    } else {
      selectionError = "No catalogue model matched that requirement.";
    }
  }

  // ---- 3. LLM explanation ---------------------------------------------
  // Imported contexts are stored as `system` rows and are ALWAYS carried
  // forward (that is what makes an imported conversation stay remembered),
  // while only the most recent user/assistant turns are kept for the token
  // budget.
  const allMessages = await import("@/lib/repos/chat").then((m) =>
    m.listMessages(sessionId, projectId, moduleType, userId),
  );
  const imports = allMessages.filter((m) => m.role === "system");
  const convo = allMessages.filter((m) => m.role !== "system").slice(-6);
  const history = [...imports, ...convo].map((m) => ({
    role: m.role as "user" | "assistant" | "system",
    content: m.content,
  }));

  // A follow-up question carries no new requirement, so `selection` is null
  // for it. Without this the model was asked "why not the smaller one?" with
  // no idea which model was being discussed, and answered about nothing.
  // Carry the most recent selection forward so a follow-up is grounded on the
  // same numbers as the message it follows.
  const priorSelection =
    selection ??
    (await import("@/lib/repos/chat").then((m) => m.latestSelection(
      sessionId,
      projectId,
      moduleType,
      userId,
    ))) ??
    null;

  const documents = await projectDocumentContext(projectId);

  // If a vendor was selected in the requirement, include their catalogue pages
  const vendorId = selectionRequest?.vendor_id ?? priorSelection?.vendor_id ?? null;
  if (vendorId) {
    const vendorDocs = await vendorCatalogueDocumentContext(vendorId);
    documents.push(...vendorDocs);
  }

  const explained = await pythonExplain({
    question: text,
    selection: priorSelection,
    documents,
    history,
  });

  let reply: string;
  let meta: Record<string, unknown> = {};

  if (explained.ok) {
    reply = explained.data.answer;
    if (explained.data.citations?.length) {
      meta.citations = explained.data.citations;
    }
    if (explained.data.degraded) {
      meta.degraded = true;
      meta.reason = explained.data.reason ?? "llm unavailable";
    }
  } else if (priorSelection) {
    // No LLM: still answer with the computed facts rather than an error.
    reply = fallbackWithSelection(priorSelection);
    meta = { degraded: true, reason: explained.error };
  } else {
    // Nothing to answer from. Say which it is: a requirement that could not
    // be run is a different problem from a question the catalogue cannot
    // answer, and "the assistant is unavailable" claims neither.
    reply = selectionError
      ? `I could not run that selection: ${selectionError}`
      : "I don't have that in the catalogue for this project. If it is a " +
        "specification question, upload the relevant catalogue page to this " +
        "project and I can read it. For a size, ratio or rating, run the " +
        "requirement form so I can give you a computed answer.";
    meta = { degraded: true, reason: explained.error };
  }

  if (selection) meta.selection = selection;
  if (shortlist.length > 1) meta.shortlist = shortlist;

  // ---- 4. persist ------------------------------------------------------
  const messages = await appendTurn({
    sessionId,
    userContent: text,
    userMetadata: selectionRequest ? { selection_request: selectionRequest } : null,
    assistantContent: reply,
    assistantMetadata: Object.keys(meta).length ? meta : null,
    sessionTitle: deriveTitle(text),
  });

  return NextResponse.json({ messages: messages.slice(-2), selection, degraded: !!meta.degraded });
}

function fallbackWithSelection(s: SelectionResult): string {
  const lines = [
    `Selected: ${s.model}`,
    "",
    `- Rated power: ${s.power_kw} kW (required ${s.required_kw} kW)`,
    `- Ratio: iN ${s.ratio_iN} at ${s.n1_rpm} rpm -> ${s.n2_actual} rpm output`,
  ];
  if (s.thermal_kw_effective != null) {
    lines.push(`- Thermal (derated): ${s.thermal_kw_effective} kW`);
  }
  if (s.warnings.length) {
    lines.push("", "Notes:");
    for (const w of s.warnings) lines.push(`- ${w}`);
  }
  return lines.join("\n");
}