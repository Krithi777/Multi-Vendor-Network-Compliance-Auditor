"use client";

// Shared numbered pager -- 1, 2, 3 ... N -- so long result lists (findings,
// evidence, remediation) render a handful of items at a time instead of
// one continuous scroll. Keeps at most a few page numbers visible plus
// first/last, with ellipses for the gap, and scrolls the list back into
// view on page change so the person isn't left looking at the old spot.

import { useEffect } from "react";

export function usePagination<T>(items: T[], pageSize: number, page: number) {
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const clampedPage = Math.min(Math.max(1, page), pageCount);
  const start = (clampedPage - 1) * pageSize;
  const pageItems = items.slice(start, start + pageSize);
  return { pageItems, pageCount, clampedPage };
}

export default function Pagination({
  page,
  pageCount,
  onChange,
  className = "",
  label,
}: {
  page: number;
  pageCount: number;
  onChange: (page: number) => void;
  className?: string;
  /** Optional "N items" caption shown inline, left of the page controls. */
  label?: string;
}) {
  useEffect(() => {
    if (page > pageCount) onChange(pageCount);
  }, [page, pageCount, onChange]);

  if (pageCount <= 1) return null;

  const numbers = buildPageList(page, pageCount);

  return (
    <div className={`flex items-center justify-between gap-3 flex-wrap ${className}`}>
      {label && <p className="text-[11px] font-mono text-ink-soft">{label}</p>}
      <div className="flex items-center gap-1.5 flex-wrap ml-auto">
      <button
        type="button"
        onClick={() => onChange(page - 1)}
        disabled={page <= 1}
        className="rounded-lg border border-line px-2.5 py-1.5 text-xs font-mono text-ink-soft hover:text-ink hover:border-ink-soft disabled:opacity-30 disabled:pointer-events-none"
      >
        Prev
      </button>
      {numbers.map((n, i) =>
        n === "…" ? (
          <span key={`gap-${i}`} className="px-1 text-xs text-ink-soft">
            …
          </span>
        ) : (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            className={`min-w-[32px] rounded-lg border px-2.5 py-1.5 text-xs font-mono transition-colors ${
              n === page
                ? "border-ink bg-ink text-paper"
                : "border-line text-ink-soft hover:text-ink hover:border-ink-soft"
            }`}
          >
            {n}
          </button>
        )
      )}
      <button
        type="button"
        onClick={() => onChange(page + 1)}
        disabled={page >= pageCount}
        className="rounded-lg border border-line px-2.5 py-1.5 text-xs font-mono text-ink-soft hover:text-ink hover:border-ink-soft disabled:opacity-30 disabled:pointer-events-none"
      >
        Next
      </button>
      </div>
    </div>
  );
}

function buildPageList(page: number, pageCount: number): (number | "…")[] {
  const window = 1;
  const pages = new Set<number>([1, pageCount]);
  for (let p = page - window; p <= page + window; p++) {
    if (p >= 1 && p <= pageCount) pages.add(p);
  }
  const sorted = Array.from(pages).sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  let prev = 0;
  for (const p of sorted) {
    if (prev && p - prev > 1) out.push("…");
    out.push(p);
    prev = p;
  }
  return out;
}
