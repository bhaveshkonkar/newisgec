"use client";

import * as React from "react";
import { useEffect, useRef, useState } from "react";
import {
  Send,
  Loader2,
  Sparkles,
  FileText,
  ExternalLink,
  FolderOpen,
  MessageSquare,
  X,
  ChevronLeft,
  ChevronDown,
  ChevronUp,
  Import as ImportIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/assistant/Markdown";
import type {
  ChatMessage,
  SelectionResult,
  AssistantMeta,
  ImportTarget,
} from "@/components/assistant/types";

/** Minimal project row for the `/` palette (GET /api/projects). */
type ImportProject = { id: string; name: string };
/** Session row for the palette (GET /api/projects/:id/sessions). */
type SessionOption = { id: string; title: string };


/**
 * Transcript view.
 *
 * Assistant replies are rendered as markdown (see Markdown) so a comparison
 * arrives as a real table and conclusions as real bold. User messages are
 * rendered as plain text: they are literal input, and echoing markdown syntax
 * back at someone is just noise.
 */
export function ChatLog({
  messages,
  onSend,
  busy,
  projectId: pid,
  onSourceClick,
}: {
  messages: ChatMessage[];
  /**
   * `importTarget` is set when the user picked a conversation in the `/`
   * palette; the parent persists that import before posting the turn so the
   * imported context is on the transcript the model will read.
   */
  onSend?: (text: string, importTarget?: ImportTarget | null) => void;
  busy?: boolean;
  /** Project ID for source links -- each message also carries it, but this is the fallback. */
  projectId: string;
  /** Called when a citation button is clicked */
  onSourceClick?: (docId: string, fileName: string, pageNo: number | null) => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState("");
  const projectId = pid;

  // ---- `/` import palette -------------------------------------------------
  const [importTarget, setImportTarget] = useState<ImportTarget | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [stage, setStage] = useState<"project" | "session">("project");
  const [chosen, setChosen] = useState<ImportProject | null>(null);
  const [projects, setProjects] = useState<ImportProject[] | null>(null);
  const [sessions, setSessions] = useState<SessionOption[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [highlight, setHighlight] = useState(0);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  // The draft doubles as the palette's search query while the menu is open:
  // everything after the leading "/" filters the current list.
  const query = menuOpen ? draft.replace(/^\//, "").trim().toLowerCase() : "";
  const projectList = (projects ?? []).filter(
    (p) => !query || p.name.toLowerCase().includes(query),
  );
  const sessionList = (sessions ?? []).filter(
    (s) => !query || s.title.toLowerCase().includes(query),
  );
  const options = stage === "project" ? projectList : sessionList;
  const hi = options.length ? Math.min(highlight, options.length - 1) : 0;

  async function openMenu() {
    setMenuOpen(true);
    setStage("project");
    setChosen(null);
    setSessions(null);
    setHighlight(0);
    if (projects) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/projects?recent=all`);
      const json = await res.json().catch(() => ({}));
      setProjects(json.projects ?? []);
    } finally {
      setLoading(false);
    }
  }

  function closeMenu() {
    setMenuOpen(false);
    setChosen(null);
    setSessions(null);
  }

  async function pickProject(p: ImportProject) {
    setChosen(p);
    setStage("session");
    setSessions(null);
    setHighlight(0);
    setDraft("/");
    setLoading(true);
    try {
      const res = await fetch(`/api/projects/${p.id}/sessions?module=gearbox`);
      const json = await res.json().catch(() => ({}));
      setSessions(json.sessions ?? []);
    } finally {
      setLoading(false);
    }
  }

  function pickSession(s: SessionOption) {
    if (!chosen) return;
    setImportTarget({
      projectId: chosen.id,
      projectName: chosen.name,
      sessionId: s.id,
      sessionTitle: s.title,
    });
    setDraft("");
    closeMenu();
  }

  function backToProjects() {
    setStage("project");
    setChosen(null);
    setSessions(null);
    setHighlight(0);
    setDraft("/");
  }

  function onDraftChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const v = e.target.value;
    // Opening on the very first "/" of an (otherwise empty) box keeps "/" as a
    // real character to type, not a mode: a message may still start with "/".
    if (v === "/" && !importTarget) {
      setDraft(v);
      void openMenu();
      return;
    }
    setDraft(v);
    if (menuOpen && !v.startsWith("/")) closeMenu();
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (menuOpen) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight((h) => (options.length ? (h + 1) % options.length : 0));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight((h) => (options.length ? (h - 1 + options.length) % options.length : 0));
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        closeMenu();
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const picked = options[hi];
        if (!picked) return;
        if (stage === "project") void pickProject(picked as ImportProject);
        else pickSession(picked as SessionOption);
        return;
      }
      if (e.key === "Backspace" && draft === "/") {
        e.preventDefault();
        closeMenu();
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function send() {
    const t = draft.trim();
    if (!t || busy || !onSend) return;
    onSend(t, importTarget);
    setDraft("");
    setImportTarget(null);
    closeMenu();
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-5">
        {messages.map((m) =>
          m.role === "system" ? (
            <ImportNotice key={m.id} message={m} />
          ) : (
            <Bubble key={m.id} message={m} projectId={projectId} onSourceClick={onSourceClick} />
          ),
        )}

        {busy && (
          <div className="flex items-center gap-2 pl-1 text-[12.5px] text-white/35">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Working on it
          </div>
        )}
        <div ref={endRef} />
      </div>

      {onSend && (
        <div className="shrink-0 border-t border-hair p-3">
          {importTarget && (
            <div className="mb-2 flex items-center gap-1.5">
              <span className="flex min-w-0 items-center gap-1.5 rounded-lg border border-accent/25 bg-accent/[0.08] px-2 py-1 text-[11.5px] text-white/70">
                <ImportIcon className="h-3 w-3 shrink-0 text-accent/80" />
                <span className="min-w-0 truncate">
                  {importTarget.projectName} / {importTarget.sessionTitle}
                </span>
                <button
                  type="button"
                  aria-label="Remove imported conversation"
                  onClick={() => setImportTarget(null)}
                  className="ml-0.5 shrink-0 text-white/40 hover:text-white/80"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
              <span className="text-[11px] text-white/25">will be remembered from here on</span>
            </div>
          )}
          <div className="relative">
            {menuOpen && (
              <SlashMenu
                stage={stage}
                loading={loading}
                query={query}
                options={options}
                highlight={hi}
                chosenName={chosen?.name ?? null}
                onHover={setHighlight}
                onPickProject={(p) => void pickProject(p)}
                onPickSession={pickSession}
                onBack={backToProjects}
              />
            )}
            <div className="flex items-end gap-2">
              <textarea
                value={draft}
                onChange={onDraftChange}
                onKeyDown={onKeyDown}
                rows={1}
                placeholder='Ask about this selection, or type "/" to import another chat...'
                className="max-h-32 min-h-[38px] flex-1 resize-none rounded-xl border border-hair
                           bg-white/[0.03] px-3.5 py-2.5 text-[13px] text-white/90
                           placeholder:text-white/25 outline-none transition-colors
                           focus:border-white/20"
              />
              <button
                type="button"
                onClick={send}
                disabled={!draft.trim() || busy}
                aria-label="Send"
                className="grid h-[38px] w-[38px] shrink-0 place-items-center rounded-xl
                           bg-accent text-white transition-opacity
                           disabled:cursor-not-allowed disabled:opacity-30"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
          <p className="mt-2 px-1 text-[11px] text-white/20">
            Selection numbers come from the catalogue engine. Type{" "}
            <span className="text-white/40">/</span> to import a conversation from any project.
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * The `/` palette. Stage 1 lists every project; the second stage lists the
 * chosen project's chat logs. Keyboard-driven (arrows + Enter) with a back
 * control, and it floats above the composer rather than replacing it.
 */
function SlashMenu({
  stage,
  loading,
  query,
  options,
  highlight,
  chosenName,
  onHover,
  onPickProject,
  onPickSession,
  onBack,
}: {
  stage: "project" | "session";
  loading: boolean;
  query: string;
  options: Array<ImportProject | SessionOption>;
  highlight: number;
  chosenName: string | null;
  onHover: (i: number) => void;
  onPickProject: (p: ImportProject) => void;
  onPickSession: (s: SessionOption) => void;
  onBack: () => void;
}) {
  return (
    <div className="absolute bottom-[calc(100%+8px)] left-0 right-0 z-20 overflow-hidden rounded-xl border border-hair bg-panel/95 shadow-2xl backdrop-blur-xl">
      <div className="flex items-center gap-1.5 border-b border-hair px-3 py-2 text-[11px] text-white/45">
        {stage === "session" ? (
          <>
            <button
              type="button"
              onClick={onBack}
              className="flex items-center gap-1 text-white/45 hover:text-white/80"
            >
              <ChevronLeft className="h-3 w-3" /> Projects
            </button>
            <span className="text-white/20">/</span>
            <span className="min-w-0 truncate text-white/60">{chosenName}</span>
            <span className="ml-auto shrink-0 text-white/25">pick a chat log</span>
          </>
        ) : (
          <>
            <ImportIcon className="h-3 w-3" />
            <span>Import a conversation from any project</span>
            <span className="ml-auto shrink-0 text-white/25">
              {query ? `\u201c${query}\u201d` : "type to filter"}
            </span>
          </>
        )}
      </div>
      <div className="max-h-64 overflow-y-auto p-1.5">
        {loading ? (
          <div className="flex items-center gap-2 px-2.5 py-3 text-[12px] text-white/35">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading
          </div>
        ) : options.length === 0 ? (
          <p className="px-2.5 py-3 text-[12px] text-white/30">
            {stage === "project" ? "No projects found." : "No conversations in this project."}
          </p>
        ) : (
          <ul className="space-y-0.5">
            {options.map((o, i) => {
              const active = i === highlight;
              const isProject = stage === "project";
              const label = isProject
                ? (o as ImportProject).name
                : (o as SessionOption).title;
              return (
                <li key={o.id}>
                  <button
                    type="button"
                    onMouseEnter={() => onHover(i)}
                    onClick={() =>
                      isProject
                        ? onPickProject(o as ImportProject)
                        : onPickSession(o as SessionOption)
                    }
                    className={cn(
                      "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[12.5px] transition-colors",
                      active
                        ? "bg-white/[0.08] text-white/90"
                        : "text-white/60 hover:bg-white/[0.04]",
                    )}
                  >
                    {isProject ? (
                      <FolderOpen className="h-3.5 w-3.5 shrink-0 opacity-60" />
                    ) : (
                      <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-50" />
                    )}
                    <span className="min-w-0 truncate">{label}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

/**
 * Renders an imported-context row as a collapsible notice instead of a chat
 * bubble: it is grounding the model reads, not something the assistant "said".
 */
function ImportNotice({ message }: { message: ChatMessage }) {
  const [open, setOpen] = useState(false);
  const imp = (message.metadata?.import ?? {}) as {
    project_name?: string | null;
    session_title?: string | null;
    message_count?: number;
  };
  return (
    <div className="flex justify-center">
      <div className="w-full max-w-[92%] rounded-xl border border-dashed border-hair bg-white/[0.015]">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-[11.5px] text-white/45 hover:text-white/65"
        >
          <ImportIcon className="h-3.5 w-3.5 shrink-0 text-accent/70" />
          <span className="min-w-0 truncate">
            Imported conversation
            {imp.session_title ? ` \u201c${imp.session_title}\u201d` : ""}
            {imp.project_name ? ` from ${imp.project_name}` : ""}
            {imp.message_count ? ` (${imp.message_count} messages)` : ""}
          </span>
          {open ? (
            <ChevronUp className="ml-auto h-3.5 w-3.5 shrink-0" />
          ) : (
            <ChevronDown className="ml-auto h-3.5 w-3.5 shrink-0" />
          )}
        </button>
        {open && (
          <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap border-t border-hair/60 px-3 py-2 text-[11.5px] leading-relaxed text-white/50">
            {message.content}
          </pre>
        )}
      </div>
    </div>
  );
}

function Bubble({ message, projectId, onSourceClick }: { message: ChatMessage; projectId: string; onSourceClick?: (docId: string, fileName: string, pageNo: number | null) => void }) {
  const isUser = message.role === "user";
  const meta = (message.metadata ?? {}) as AssistantMeta;
  // The alternatives table belongs to this reply, so it renders inside this
  // bubble. It used to be a separate card pinned above the transcript, which
  // meant the numbers a sentence referred to sat somewhere else on screen.
  const table =
    !isUser && meta.shortlist && meta.shortlist.length > 1
      ? meta.shortlist
      : null;

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          // Wide enough for the comparison table; without this the assistant
          // column was capped at 85% and the table squeezed into a sliver.
          "max-w-full rounded-2xl px-4 py-3 sm:max-w-[92%]",
          isUser
            ? "bg-white/[0.07] text-white/90"
            : "border border-hair bg-white/[0.02] text-white/80",
        )}
      >
        {!isUser && (
          <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-accent/80">
            <Sparkles className="h-3 w-3" />
            Assistant
            {meta.degraded && (
              <span className="ml-1 normal-case tracking-normal text-amber-400/70">
                {meta.reason ? `(${meta.reason})` : '(assistant degraded)'}
              </span>
            )}
          </div>
        )}
        {isUser ? (
          <span className="whitespace-pre-wrap text-[13px] leading-relaxed">
            {message.content}
          </span>
        ) : (
          <Markdown>{message.content}</Markdown>
        )}
        {table && <ShortlistTable rows={table} />}
        {meta.citations && meta.citations.length > 0 && (
          <SourceButtons citations={meta.citations} projectId={message.projectId ?? projectId} onSourceClick={onSourceClick} />
        )}
      </div>
    </div>
  );
}

interface Citation {
  document_id: string;
  file_name: string;
  page_no: number | null;
}

function SourceButtons({ citations, projectId, onSourceClick }: { citations: Citation[]; projectId: string; onSourceClick?: (docId: string, fileName: string, pageNo: number | null) => void }) {
  return (
    <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
      {citations.map((c, i) => (
        <button
          key={`${c.document_id}-${c.page_no}-${i}`}
          type="button"
          onClick={() => {
            if (onSourceClick) {
              onSourceClick(c.document_id, c.file_name, c.page_no ?? 1);
            } else {
              const url = `/api/projects/${projectId}/documents/${c.document_id}/file`;
              const target = c.page_no ? `${url}#page=${c.page_no}` : url;
              window.open(target, "_blank", "noopener,noreferrer");
            }
          }}
          className="flex items-center gap-1.5 rounded-lg bg-white/[0.05] px-2.5 py-1.5 text-white/70 hover:bg-white/[0.1] transition-colors border border-hair/40"
          aria-label={c.page_no ? `Open ${c.file_name} page ${c.page_no}` : `Open ${c.file_name}`}
        >
          <FileText className="h-3 w-3 shrink-0 text-white/40" strokeWidth={1.8} />
          <span className="truncate max-w-[180px]">{c.file_name}</span>
          {c.page_no && (
            <>
              <span className="mx-1 text-white/25">/</span>
              <span className="font-mono tabular-nums">p.{c.page_no}</span>
            </>
          )}
          <ExternalLink className="h-2.5 w-2.5 shrink-0 text-white/30" strokeWidth={2} />
        </button>
      ))}
    </div>
  );
}

/**
 * The shortlisted models for the selection just described, best first.
 *
 * Rendered as part of the reply rather than as a separate panel, so the prose
 * and the numbers it refers to are read together.
 */
function ShortlistTable({ rows }: { rows: SelectionResult[] }) {
  return (
    <div className="mt-3.5 overflow-x-auto rounded-xl border border-hair">
      <table className="w-full min-w-[520px] border-collapse text-left">
        <thead>
          <tr className="border-b border-hair bg-white/[0.03]">
            <Th>Model</Th>
            <Th>Rated</Th>
            <Th>PN</Th>
            <Th>Ratio</Th>
            <Th>Out</Th>
            <Th>Thermal</Th>
            <Th>Wt</Th>
            <Th>Est. cost</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const best = i === 0;
            return (
              <tr
                key={r.model}
                className={cn(
                  "border-b border-hair/60 last:border-0",
                  best && "bg-emerald-400/[0.05]",
                )}
              >
                <Td>
                  <span className={cn(best ? "text-white" : "text-white/75")}>{r.model}</span>
                  {best && (
                    <span className="ml-1.5 text-[10px] uppercase tracking-wide text-emerald-300/80">
                      best
                    </span>
                  )}
                </Td>
                <Td>{r.power_kw} kW</Td>
                <Td>
                  <span className={r.power_ok ? "text-white/70" : "text-amber-300/90"}>
                    {r.required_kw} kW{r.power_ok ? "" : " !"}
                  </span>
                </Td>
                <Td>
                  iN {r.ratio_iN}
                  {Math.abs(r.ratio_dev) > 0.15 && (
                    <span className="ml-1 text-amber-300/80">
                      {r.ratio_dev > 0 ? "+" : ""}
                      {Math.round(r.ratio_dev * 100)}%
                    </span>
                  )}
                </Td>
                <Td>{r.n2_actual}</Td>
                <Td>
                  {r.thermal_kw_effective != null ? `${r.thermal_kw_effective} kW` : "n/p"}
                </Td>
                <Td muted={r.weight_published === false}>
                  {r.weight_kg != null ? `${r.weight_published ? "" : "~"}${r.weight_kg} kg` : "n/a"}
                </Td>
                <Td muted={r.weight_published === false}>
                  {r.est_price_inr != null
                    ? `₹${Math.round(r.est_price_inr).toLocaleString("en-IN")}`
                    : "n/a"}
                </Td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="border-t border-hair px-3 py-1.5 text-[10.5px] leading-relaxed text-white/25">
        PN = required power after S/F. "~" = estimated weight, not published. n/p = not
        published. "!" = below required power. Est. cost = net weight × steel rate,
        steel content only, not a price quote.
      </p>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="whitespace-nowrap px-3 py-2 text-[10.5px] font-medium uppercase tracking-[0.06em] text-white/35">
      {children}
    </th>
  );
}

function Td({
  children,
  muted,
}: {
  children: React.ReactNode;
  muted?: boolean;
}) {
  return (
    <td
      className={cn(
        "whitespace-nowrap px-3 py-2 text-[12px] tabular-nums",
        muted ? "text-white/40" : "text-white/70",
      )}
    >
      {children}
    </td>
  );
}