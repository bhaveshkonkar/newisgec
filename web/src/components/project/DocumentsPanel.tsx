"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Upload, FileText, X, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Uploaded = {
  id: string;
  file_name: string;
  status: string;
  error_detail: string | null;
};

const ACCEPT = ".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt";

/**
 * Dropzone + file list. Upload returns as soon as the bytes are stored;
 * parsing happens in the background, so this polls /status until every
 * document leaves 'uploaded'/'processing'.
 */
export function DocumentsPanel({
  projectId,
  moduleId,
  documents,
  canUpload = true,
}: {
  projectId: string;
  moduleId?: string | null;
  documents: Array<{
    id: string;
    file_name: string;
    status: string;
    error_detail: string | null;
    page_count: number | null;
  }>;
  canUpload?: boolean;
}) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const anyPending = documents.some(
    (d) => d.status === "uploaded" || d.status === "processing",
  );

  // poll while anything is still being parsed
  React.useEffect(() => {
    if (!anyPending) return;
    const t = setInterval(() => router.refresh(), 2000);
    return () => clearInterval(t);
  }, [anyPending, router]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      for (const f of Array.from(files)) fd.append("files", f);
      if (moduleId) fd.append("module_id", moduleId);

      const res = await fetch(`/api/projects/${projectId}/documents`, {
        method: "POST",
        body: fd,
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.error ?? "Upload failed");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      const res = await fetch(`/api/projects/${projectId}/documents/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const json = await res.json().catch(() => ({}));
        throw new Error(json.error ?? "Could not delete document");
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete document");
    }
  }

  return (
    <section className="space-y-4">
      {canUpload && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            void upload(e.dataTransfer.files);
          }}
          className={cn(
            "rounded-2xl border border-dashed p-6 text-center transition-colors duration-200",
            dragging
              ? "border-accent/60 bg-accent/[0.06]"
              : "border-hair-strong bg-panel/40 hover:border-white/20",
          )}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => void upload(e.target.files)}
          />
          <Upload className="mx-auto h-6 w-6 text-white/25" strokeWidth={1.5} />
          <p className="mt-3 text-[13px] text-white/50">
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="text-white/80 underline-offset-4 hover:underline"
            >
              Browse files
            </button>{" "}
            or drag and drop
          </p>
          <p className="mt-1.5 text-[11.5px] text-white/25">
            PDF, Word, Excel, CSV or TXT · up to 50 MB each
          </p>
          {busy && (
            <div className="mt-3 flex items-center justify-center gap-2 text-[12px] text-white/40">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Uploading…
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-red-500/25 bg-red-500/10 px-3.5 py-2.5 text-[12.5px] text-red-300">
          <AlertCircle className="mt-px h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {documents.length === 0 ? (
        <p className="py-6 text-center text-[13px] text-white/25">
          No documents yet.
        </p>
      ) : (
        <ul className="space-y-2">
          {documents.map((d) => (
            <li
              key={d.id}
              className="group flex items-center gap-3 rounded-xl border border-hair bg-panel/60 px-3.5 py-3"
            >
              <FileText className="h-4 w-4 shrink-0 text-white/30" strokeWidth={1.6} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] text-white/85">{d.file_name}</p>
                <p className="mt-0.5 text-[11.5px] text-white/30">
                  {d.page_count ? `${d.page_count} pages · ` : ""}
                  <StatusLabel doc={d} />
                </p>
              </div>

              {d.status === "parsing" || d.status === "processing" || d.status === "uploaded" ? (
                <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-white/30" />
              ) : d.status === "parsed" ? (
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400/70" strokeWidth={1.8} />
              ) : (
                <AlertCircle className="h-3.5 w-3.5 shrink-0 text-amber-400/70" strokeWidth={1.8} />
              )}

              <button
                type="button"
                onClick={() => void remove(d.id)}
                aria-label={`Remove ${d.file_name}`}
                className="rounded-lg p-1.5 text-white/25 opacity-0 transition hover:bg-white/[0.05] hover:text-white/70 focus-visible:opacity-100 group-hover:opacity-100"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function StatusLabel({ doc }: { doc: Uploaded | { status: string; error_detail: string | null } }) {
  switch (doc.status) {
    case "parsed":
      return <span className="text-emerald-400/70">parsed</span>;
    case "failed":
      return <span className="text-amber-400/80">{doc.error_detail ?? "parse failed"}</span>;
    case "processing":
      return <span>parsing…</span>;
    default:
      return <span>queued</span>;
  }
}