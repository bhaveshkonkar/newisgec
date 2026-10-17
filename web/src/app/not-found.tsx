import Link from "next/link";

export default function NotFound() {
  return (
    <main className="grid min-h-dvh place-items-center px-6">
      <div className="max-w-sm text-center">
        <p className="text-[11px] uppercase tracking-[0.14em] text-white/25">404</p>
        <h1 className="mt-3 text-[22px] font-semibold tracking-[-0.02em] text-white">
          Nothing here
        </h1>
        <p className="mt-2 text-[13px] leading-relaxed text-white/40">
          That page does not exist, or it belongs to a project you cannot open.
        </p>
        <Link
          href="/"
          className="mt-6 inline-flex items-center rounded-xl border border-hair px-4 py-2
                     text-[13px] text-white/70 transition-colors hover:border-white/20 hover:text-white"
        >
          Back to projects
        </Link>
      </div>
    </main>
  );
}