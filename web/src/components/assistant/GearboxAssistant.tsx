"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { MessageSquare, Plus, Trash2, ChevronLeft } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { ChatLog } from "@/components/assistant/ChatLog";
import { RequirementForm } from "@/components/assistant/RequirementForm";
import { PDFViewer } from "@/components/assistant/PDFViewer";
import type {
  ChatMessage,
  ModuleDoc,
  SelectionRequest,
  SelectionResult,
  SessionSummary,
  ImportTarget,
} from "@/components/assistant/types";

/**
 * The Gearbox Assistant.
 *
 * One job: turn a requirement into a defensible selection and explain it.
 *
 * The requirement panel is a real form rather than a chat message -- engineers
 * type numbers, and a form makes the values explicit and reproducible. The
 * transcript is for follow-ups ("why not S3?", "what is the thermal margin?")
 * and is grounded on this project's documents and on the deterministic result,
 * never on the model's own arithmetic.
 *
 * The selected session lives in the URL (?session=...) rather than in React
 * state, so a reload, a bookmark or a shared link opens the same conversation
 * and the back button behaves.
 */
export function GearboxAssistant({
  projectId,
  sessions,
  activeSessionId,
  initialMessages,
  documents,
  vendors,
}: {
  projectId: string;
  sessions: SessionSummary[];
  activeSessionId: string | null;
  initialMessages: ChatMessage[];
  documents: ModuleDoc[];
  vendors: Array<{ id: number; code: string; name: string }>;
}) {
  const router = useRouter();
  const params = useSearchParams();

  const [messages, setMessages] = React.useState<ChatMessage[]>(initialMessages);
  const [selection, setSelection] = React.useState<SelectionResult | null>(
    latestSelection(initialMessages),
  );
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const SYS_PROJECT_ID = '00000000-0000-0000-0000-000000000001';

  const [pdfViewer, setPdfViewer] = React.useState<{
    documentId: string;
    fileName: string;
    page: number;
    totalPages: number;
    fileProjectId: string;
  } | null>(null);

  async function openPdfViewer(documentId: string, fileName: string, pageNo: number | null) {
    // Find the document in the project documents to get total pages
    const doc = documents.find((d) => d.id === documentId);
    let totalPages = doc?.page_count ?? pageNo ?? 1;
    // Vendor documents live in the system project
    const fileProjectId = doc ? projectId : SYS_PROJECT_ID;

    // Vendor catalogue documents are not in the project document list, so ask
    // the system project (the same scope the file route reads) for the page
    // count. PDF.js reports the real total anyway once the file loads.
    if (!doc) {
      try {
        const res = await fetch(`/api/projects/${fileProjectId}/documents/${documentId}/meta`);
        if (res.ok) {
          const meta = await res.json();
          totalPages = meta.page_count ?? pageNo ?? 1;
        }
      } catch {
        // ignore, fallback to pageNo or 1
      }
    }

    setPdfViewer({
      documentId,
      fileName,
      page: pageNo ?? 1,
      totalPages,
      fileProjectId,
    });
  }

  function closePdfViewer() {
    setPdfViewer(null);
  }

  function onPdfPageChange(page: number) {
    setPdfViewer((prev) => (prev ? { ...prev, page } : null));
  }

  const pdfOpen = pdfViewer !== null;

  // Escape closes the overlay, and the page behind it must not scroll under
  // the viewer while it is open.
  React.useEffect(() => {
    if (!pdfOpen) return;

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setPdfViewer(null);
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [pdfOpen]);

  // a router.refresh() delivers new props; fold them in without losing the
  // optimistic messages the user is still looking at. activeSessionId is a
  // dependency too: without it, switching conversations can leave the
  // previous transcript on screen for a frame.
  React.useEffect(() => {
    setMessages(initialMessages);
    setSelection(latestSelection(initialMessages));
  }, [initialMessages, activeSessionId]);

  const goto = React.useCallback(
    (sessionId: string | null) => {
      const qs = sessionId ? `?session=${sessionId}` : "";
      router.push(`/projects/${projectId}/gearbox${qs}`);
      router.refresh();
    },
    [router, projectId],
  );

  async function startSession(): Promise<string | null> {
    const res = await fetch(`/api/projects/${projectId}/sessions?module=gearbox`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ module_type: "gearbox" }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(json.error ?? "Could not start a conversation");
      return null;
    }
    return json.session.id as string;
  }

  /**
   * POST one turn and fold the returned messages into local state.
   * Never creates a session implicitly for a follow-up: a question asked in
   * conversation N belongs to conversation N.
   *
   * When `importTarget` is set, the other conversation is imported into this
   * session FIRST (persisted as grounding) so the turn being sent is answered
   * with that context already present.
   */
  async function send(
    text: string,
    req?: SelectionRequest,
    importTarget?: ImportTarget | null,
  ) {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);

    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content: text,
      metadata: null,
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, optimistic]);

    try {
      let sid = activeSessionId;
      if (!sid) {
        sid = await startSession();
        if (!sid) {
          setMessages((m) => m.filter((x) => x.id !== optimistic.id));
          return;
        }
      }

      // Persist the import before the turn so the transcript read by the
      // model already contains it. The notice is slotted above the question.
      if (importTarget) {
        const impRes = await fetch(
          `/api/projects/${projectId}/sessions/${sid}/import?module=gearbox`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              source_project_id: importTarget.projectId,
              source_session_id: importTarget.sessionId,
              module_type: "gearbox",
            }),
          },
        );
        const impJson = await impRes.json().catch(() => ({}));
        if (!impRes.ok) throw new Error(impJson.error ?? "Could not import that conversation");
        if (impJson.message) {
          const imported = impJson.message as ChatMessage;
          setMessages((m) => {
            const next = [...m];
            const at = next.findIndex((x) => x.id === optimistic.id);
            next.splice(at < 0 ? next.length : at, 0, imported);
            return next;
          });
        }
      }

      const res = await fetch(
        `/api/projects/${projectId}/sessions/${sid}/messages?module=gearbox`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text,
            module_type: "gearbox",
            selection_request: req ?? null,
          }),
        },
      );
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.error ?? "Request failed");

      // swap the optimistic bubble for the persisted pair
      setMessages((m) => [
        ...m.filter((x) => x.id !== optimistic.id),
        ...(json.messages ?? []),
      ]);
      if (json.selection) setSelection(json.selection);

      if (!activeSessionId) {
        router.replace(`/projects/${projectId}/gearbox?session=${sid}`);
      }
      router.refresh();
    } catch (err) {
      setMessages((m) => m.filter((x) => x.id !== optimistic.id));
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  async function removeSession(id: string) {
    const res = await fetch(
      `/api/projects/${projectId}/sessions/${id}?module=gearbox`,
      { method: "DELETE" },
    );
    if (!res.ok) return;
    if (id === activeSessionId) {
      setMessages([]);
      setSelection(null);
    }
    router.refresh();
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-[1400px] flex-col px-5 pb-6 md:px-8">
      {/* The title and its description live in the top bar breadcrumb now, so
          there is no page header between the bar and the panes: the transcript
          and the session rail both start at the top of the content area. */}

      {/* Layout: session rail + chat area. When a source is opened the PDF
          viewer takes over as a large overlay above this, with the chat blurred
          out behind it -- a catalogue page needs far more room than a 320px
          side column can give, and the conversation is not being read while
          the page is on screen. */}
      <div className="grid min-h-0 flex-1 gap-5 lg:grid-cols-[212px_minmax(0,1fr)]">
        <div className="flex min-h-0 flex-col">
          <SessionRail
            sessions={sessions}
            activeId={activeSessionId}
            onSelect={goto}
            onNew={() => goto(null)}
            onDelete={removeSession}
          />
        </div>
        <div className="flex min-h-0 flex-col gap-4 lg:col-span-1">
          {error && (
            <div className="shrink-0 rounded-xl border border-red-500/25 bg-red-500/10 px-3.5 py-2.5 text-[12.5px] text-red-300">
              {error}
            </div>
          )}

          {/* No SelectionCard above the transcript any more. The shortlisted
              models render inside the reply that discusses them, so the
              numbers and the reasoning are read together. */}
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-hair bg-panel/50 shadow-card backdrop-blur-xl">
            <ChatLog
              messages={messages}
              onSend={(t, imp) => send(t, undefined, imp)}
              busy={busy}
              projectId={projectId}
              onSourceClick={openPdfViewer}
            />
            <RequirementForm
              vendors={vendors}
              busy={busy}
              onRun={(req) =>
                send(
                  `Select a gearbox for ${req.pn} kW at ratio ${req.ratio_req ?? "any"}` +
                    (req.mounting_type && req.mounting_type !== "any"
                      ? `, ${req.mounting_type.replace("_", " ")} mounted`
                      : "") +
                    `, S/F ${req.sf}.`,
                  req,
                )
              }
            />
          </div>
        </div>
      </div>

      {pdfViewer && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
          role="dialog"
          aria-modal="true"
          aria-label={`${pdfViewer.fileName} page ${pdfViewer.page}`}
        >
          {/* Clicking the backdrop closes, matching how the reader expects a
              modal to behave. */}
          <button
            type="button"
            aria-label="Close PDF viewer"
            onClick={closePdfViewer}
            className="absolute inset-0 h-full w-full cursor-default bg-black/70 backdrop-blur-md"
          />
          <div className="relative flex h-full w-full max-w-[1400px] flex-col overflow-hidden rounded-2xl border border-white/10 bg-panel/95 shadow-2xl">
            <PDFViewer
              projectId={projectId}
              documentId={pdfViewer.documentId}
              fileName={pdfViewer.fileName}
              initialPage={pdfViewer.page}
              totalPages={pdfViewer.totalPages}
              onClose={closePdfViewer}
              onPageChange={onPdfPageChange}
              fileProjectId={pdfViewer.fileProjectId}
            />
          </div>
        </div>
      )}
    </div>
  );
}

/** Rehydrate the selection card from the transcript. */
function latestSelection(messages: ChatMessage[]): SelectionResult | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const sel = messages[i]?.metadata?.selection as SelectionResult | undefined;
    if (sel && sel.model) return sel;
  }
  return null;
}

function SessionRail({
  sessions,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: {
  sessions: SessionSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-hair bg-panel/40">
      <div className="shrink-0 border-b border-hair p-2.5">
        <button
          type="button"
          onClick={onNew}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-hair
                     px-2 py-1.5 text-[12px] text-white/60 transition-colors
                     hover:border-white/20 hover:text-white/85"
        >
          <Plus className="h-3.5 w-3.5" />
          New
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {/* activeId === null means an unsaved draft. Without this the rail
            looks identical whether you are mid-conversation or starting a new
            one, and "New" reads as if it did nothing. */}
        {!activeId && (
          <div className="mb-1 flex items-center gap-1.5 rounded-lg bg-white/[0.07] px-2.5 py-2 text-[12px] text-white/90">
            <MessageSquare className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">New conversation</span>
          </div>
        )}
        {sessions.length === 0 ? (
          <p className="px-2 py-3 text-[11.5px] leading-relaxed text-white/25">
            No saved conversations yet. Run a selection to start one.
          </p>
        ) : (
          <p className="px-2 py-2 text-[11px] leading-relaxed text-white/25">
            {sessions.length} saved. Starting a new one keeps these.
          </p>
        )}
        <ul className="space-y-0.5">
          {sessions.map((s) => {
            const active = s.id === activeId;
            return (
              <li key={s.id} className="group relative">
                <button
                  type="button"
                  onClick={() => onSelect(s.id)}
                  className={cn(
                    "w-full rounded-lg px-2.5 py-2 pr-7 text-left transition-colors",
                    active
                      ? "bg-white/[0.07] text-white/90"
                      : "text-white/50 hover:bg-white/[0.035] hover:text-white/75",
                  )}
                >
                  <span className="flex items-center gap-1.5">
                    <MessageSquare className="h-3 w-3 shrink-0 opacity-50" />
                    <span className="min-w-0 truncate text-[12px]">{s.title}</span>
                  </span>
                  <span className="mt-0.5 block pl-4.5 text-[10.5px] text-white/25">
                    {timeAgo(s.updated_at)}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(s.id)}
                  aria-label={`Delete ${s.title}`}
                  className="absolute right-1.5 top-1.5 rounded p-1 text-white/25 opacity-0
                             transition-opacity hover:text-red-400 group-hover:opacity-100"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}