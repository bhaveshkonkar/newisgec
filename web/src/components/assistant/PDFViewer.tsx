"use client";

import * as React from "react";
import {
  X,
  ChevronLeft,
  ChevronRight,
  Download,
  RotateCcw,
  Minus,
  Plus,
  ExternalLink,
} from "lucide-react";

interface PDFViewerProps {
  projectId: string;
  documentId: string;
  fileName: string;
  initialPage: number;
  totalPages: number;
  onClose: () => void;
  onPageChange: (page: number) => void;
  fileProjectId?: string;
}

const MIN_ZOOM = 50;
const MAX_ZOOM = 300;

/**
 * Shows catalogue pages as server-rendered PNGs.
 *
 * An earlier version embedded the PDF in an iframe and a later one drew it with
 * PDF.js. Both still depend on something the browser controls: the PDF plugin,
 * or the ability to run the viewer script and fetch the file. Privacy-focused
 * browsers such as Ulaa block those outright, so the panel went blank and the
 * only fallback was a new-tab link.
 *
 * Requesting a rendered image removes the PDF from the request path entirely,
 * which is the only version of this that does not depend on the browser
 * allowing a PDF viewer at all.
 */
export function PDFViewer({
  projectId,
  documentId,
  fileName,
  initialPage,
  totalPages,
  onClose,
  onPageChange,
  fileProjectId,
}: PDFViewerProps) {
  const scope = fileProjectId ?? projectId;
  const [page, setPage] = React.useState(initialPage);
  const [numPages, setNumPages] = React.useState(totalPages);
  const [zoom, setZoom] = React.useState(100);
  const [rotation, setRotation] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const imgRef = React.useRef<HTMLImageElement>(null);
  const rootRef = React.useRef<HTMLDivElement>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  // Width in CSS pixels the page will occupy, used to request a raster with one
  // image pixel per real screen pixel. Measuring the scroller (not the window)
  // keeps this correct inside the overlay on any display.
  const [cssWidth, setCssWidth] = React.useState(0);

  React.useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const measure = () => {
      const available = el.clientWidth - 24;
      if (available > 0) setCssWidth(Math.round(available));
    };

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Device pixels actually needed: CSS width times the device pixel ratio, so a
  // HiDPI screen gets a genuinely sharper raster instead of an upscaled blur.
  const targetWidth = React.useMemo(() => {
    if (cssWidth <= 0) return undefined;
    const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
    // Cap so a 3x phone or an ultrawide monitor cannot ask for a giant render.
    const wanted = Math.round(cssWidth * dpr * (zoom / 100));
    return Math.max(640, Math.min(wanted, 4000));
  }, [cssWidth, zoom]);

  const imageUrl =
    targetWidth === undefined
      ? `/api/projects/${scope}/documents/${documentId}/page?page=${page}&dpi=220`
      : `/api/projects/${scope}/documents/${documentId}/page?page=${page}&w=${targetWidth}`;

  const fileUrl = `/api/projects/${scope}/documents/${documentId}/file`;

  React.useEffect(() => {
    setPage(initialPage);
    setError(null);
    // Focus the viewer so arrow-key paging works without a prior click.
    rootRef.current?.focus();
  }, [documentId, initialPage]);

  React.useEffect(() => {
    setLoading(true);
    const img = new Image();
    let cancelled = false;

    img.onload = () => {
      if (cancelled) return;
      setLoading(false);
      setError(null);
    };
    img.onerror = () => {
      if (cancelled) return;
      setLoading(false);
      setError(
        page > 1 && page > totalPages
          ? `Page ${page} is past the end of this document.`
          : "This page could not be rendered.",
      );
    };
    img.src = imageUrl;

    return () => {
      cancelled = true;
      img.onload = null;
      img.onerror = null;
    };
  }, [imageUrl]);

  const goToPage = React.useCallback(
    (next: number) => {
      const clamped = Math.max(1, Math.min(numPages, next));
      setPage(clamped);
      onPageChange(clamped);
    },
    [numPages, onPageChange],
  );

  // Arrow keys page through the document, but only while focus is inside the
  // viewer. Listening on window unconditionally meant a stray arrow press
  // anywhere on the page flipped the catalogue page.
  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const root = rootRef.current;
      if (!root || !root.contains(document.activeElement)) return;

      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setPage((p) => {
          const next = Math.max(1, p - 1);
          onPageChange(next);
          return next;
        });
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        setPage((p) => {
          const next = Math.min(numPages, p + 1);
          onPageChange(next);
          return next;
        });
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [numPages, onPageChange]);

  const header = (
    <div className="shrink-0 border-b border-hair px-3 py-2 flex items-center gap-2">
      <button onClick={onClose} className="p-1 text-white/50 hover:text-white" aria-label="Close PDF viewer">
        <X className="h-4 w-4" />
      </button>
      <span className="text-[12px] font-medium text-white/90 truncate flex-1" title={fileName}>
        {fileName}
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => goToPage(page - 1)}
          disabled={page <= 1}
          className="p-1.5 rounded border border-hair bg-white/[0.05] text-white/70 hover:bg-white/[0.1] disabled:opacity-30 disabled:cursor-not-allowed"
          aria-label="Previous page"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <span className="text-[11px] text-white/60 font-mono tabular-nums px-1 whitespace-nowrap">
          {page} / {numPages}
        </span>
        <button
          onClick={() => goToPage(page + 1)}
          disabled={page >= numPages}
          className="p-1.5 rounded border border-hair bg-white/[0.05] text-white/70 hover:bg-white/[0.1] disabled:opacity-30 disabled:cursor-not-allowed"
          aria-label="Next page"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
        <div className="w-px h-6 bg-hair mx-1" />
        <button
          onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z - 25))}
          className="p-1.5 rounded border border-hair bg-white/[0.05] text-white/70 hover:bg-white/[0.1]"
          aria-label="Zoom out"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <span className="text-[11px] text-white/60 font-mono tabular-nums w-12 text-center">
          {zoom}%
        </span>
        <button
          onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z + 25))}
          className="p-1.5 rounded border border-hair bg-white/[0.05] text-white/70 hover:bg-white/[0.1]"
          aria-label="Zoom in"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => setRotation((r) => (r + 90) % 360)}
          className="p-1.5 rounded border border-hair bg-white/[0.05] text-white/70 hover:bg-white/[0.1]"
          aria-label="Rotate 90 degrees"
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
        <div className="w-px h-6 bg-hair mx-1" />
        <a
          href={fileUrl}
          download={fileName}
          className="p-1.5 rounded border border-hair bg-white/[0.05] text-white/70 hover:bg-white/[0.1]"
          aria-label="Download PDF"
          title="Download PDF"
        >
          <Download className="h-3.5 w-3.5" />
        </a>
        <a
          href={`${fileUrl}#page=${page}`}
          target="_blank"
          rel="noopener noreferrer"
          className="p-1.5 rounded border border-hair bg-white/[0.05] text-white/70 hover:bg-white/[0.1]"
          aria-label="Open the original PDF in a new tab"
          title="Open the original PDF in a new tab"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>
    </div>
  );

  return (
    <div
      ref={rootRef}
      tabIndex={-1}
      className="flex h-full flex-col overflow-hidden outline-none"
    >
      {header}
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-auto bg-black/25 p-3 relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-white/50 text-sm">
            Loading page {page}...
          </div>
        )}
        {error ? (
          <div className="h-full flex flex-col items-center justify-center gap-3 p-6 text-center">
            <p className="text-white/70 text-sm">{error}</p>
            {page > 1 && (
              <button
                onClick={() => goToPage(1)}
                className="px-3 py-1.5 rounded-lg border border-hair bg-white/[0.05] text-white/90 hover:bg-white/[0.1] text-sm"
              >
                Back to first page
              </button>
            )}
          </div>
        ) : (
          <div className="flex justify-center">
            <img
              ref={imgRef}
              key={`${page}-${rotation}-${targetWidth}`}
              src={imageUrl}
              alt={`${fileName} page ${page}`}
              className="rounded-lg shadow-2xl bg-white"
              style={{
                transform: `rotate(${rotation}deg)`,
                // Laid out at the CSS width the raster was requested for, so one
                // image pixel maps to one screen pixel. Scaling this with a
                // percentage instead is what made the page look soft.
                width: cssWidth > 0 ? `${Math.round((cssWidth * zoom) / 100)}px` : undefined,
                maxWidth: "none",
              }}
              onLoad={() => setLoading(false)}
              onError={() => {
                setLoading(false);
                setError("This page could not be rendered.");
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}