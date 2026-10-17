"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

/**
 * Renders the assistant's reply as markdown.
 *
 * The reply is LLM output about engineering numbers, so it is rendered as
 * React elements and never as raw HTML: a catalogue PDF containing
 * "<script>" or a stray HTML tag must not become markup. react-markdown does
 * not enable raw HTML unless explicitly told to, and we do not tell it to.
 *
 * Why this exists at all: the assistant answers comparisons as a table and
 * flags conclusions in bold. Rendered as plain pre-wrapped text that came out
 * as literal "**bold**" and an unaligned wall of pipes, which is unusable for
 * the one job it has -- letting an engineer compare two models.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="text-[13px] leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Headings carry the structure of the answer, so each level gets a
          // distinct colour rather than all reading as the same grey text.
          h1: ({ children }) => (
            <h1 className="mt-3 mb-1.5 text-[14px] font-semibold tracking-[-0.01em] text-white first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mt-3.5 mb-1.5 flex items-center gap-1.5 text-[13.5px] font-semibold text-accent first:mt-0">
              <span className="inline-block h-3 w-[2px] rounded-full bg-accent/70" />
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mt-3 mb-1 text-[13px] font-semibold text-emerald-300/90 first:mt-0">
              {children}
            </h3>
          ),
          h4: ({ children }) => (
            <h4 className="mt-2.5 mb-1 text-[12.5px] font-semibold uppercase tracking-[0.06em] text-amber-300/80 first:mt-0">
              {children}
            </h4>
          ),

          p: ({ children }) => (
            <p className="my-1.5 whitespace-pre-wrap first:mt-0 last:mb-0">{children}</p>
          ),

          // Strong carries the conclusion inside a sentence, so it has to be
          // visibly stronger than the surrounding prose.
          strong: ({ children }) => (
            <strong className="font-semibold text-white">{children}</strong>
          ),
          em: ({ children }) => <em className="text-white/70 italic">{children}</em>,
          del: ({ children }) => (
            <del className="text-white/35 line-through">{children}</del>
          ),

          ul: ({ children }) => (
            <ul className="my-1.5 space-y-1 pl-1">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="my-1.5 list-decimal space-y-1 pl-5 marker:text-white/30">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="relative pl-3.5 before:absolute before:left-0 before:top-[0.55em] before:h-1 before:w-1 before:rounded-full before:bg-white/25">
              {children}
            </li>
          ),

          table: ({ children }) => (
            <div className="my-2.5 overflow-x-auto rounded-xl border border-hair">
              <table className="w-full min-w-[440px] border-collapse text-left">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="border-b border-hair bg-white/[0.04]">{children}</thead>
          ),
          tbody: ({ children }) => <tbody>{children}</tbody>,
          // Header cells are the one place a colour is genuinely useful: they
          // label the columns, and tinting them keeps a 7-column comparison
          // readable when it has to scroll.
          th: ({ children }) => (
            <th className="whitespace-nowrap px-3 py-2 text-[10.5px] font-semibold uppercase tracking-[0.06em] text-accent/90">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-t border-hair/60 px-3 py-2 align-top text-[12px] text-white/70">
              {children}
            </td>
          ),

          code: ({ className, children }) => {
            const block = /language-/.test(className ?? "");
            return block ? (
              <code className="my-2 block overflow-x-auto rounded-lg border border-hair bg-black/30 px-3 py-2 text-[12px] text-white/80">
                {children}
              </code>
            ) : (
              <code className="rounded bg-white/[0.07] px-1 py-0.5 text-[12px] text-white/85">
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            <pre className="overflow-x-auto rounded-lg border border-hair bg-black/30 p-3">
              {children}
            </pre>
          ),

          a: ({ children, href }) => (
            <a
              href={href}
              className="text-accent underline underline-offset-2 hover:text-white"
              rel="noreferrer noopener"
              target="_blank"
            >
              {children}
            </a>
          ),
          hr: () => <hr className="my-3 border-hair" />,
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-2 border-accent/40 pl-3 text-white/50">
              {children}
            </blockquote>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

/** Plain-text preview of a reply, for places that cannot render markdown. */
export function stripMarkdown(md: string): string {
  return md
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/\|/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export const _cn = cn;