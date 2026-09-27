"use client";

// Scan-level remediation list. The actual remediation lookup (commands,
// verification, rollback) already exists per-control at
// /remediation/[scanId]/[controlId] — this tab is the missing piece that
// was flagged: nothing surfaced "here are the controls you can remediate
// on this scan" as a single list.
//
// Phase 8 (dependency-graph conflict simulation) does not exist yet —
// see the Phase 9 split plan's "Out of Scope" section — so this page
// says so plainly rather than implying a safety check that isn't there.

import Link from "next/link";
import { useState } from "react";
import { useScanWorkspace } from "../scan-context";
import Pagination, { usePagination } from "../../../components/Pagination";

const PAGE_SIZE = 4;

export default function RemediationListPage() {
  const { loadState, scan, findings, errorMessage } = useScanWorkspace();
  const [page, setPage] = useState(1);

  if (loadState === "loading" || loadState === "waiting") {
    return <p className="font-mono text-sm text-ink-soft">{loadState === "waiting" ? "Processing scan…" : "Loading…"}</p>;
  }
  if (loadState === "error" || !scan) {
    return <p className="text-ink/90">{errorMessage}</p>;
  }
  if (!findings) {
    return <p className="font-mono text-sm text-ink-soft">No findings yet.</p>;
  }

  const remediable = findings.results.filter((r) => r.state === "FAIL" || r.state === "MISSING");
  const { pageItems, pageCount, clampedPage } = usePagination(remediable, PAGE_SIZE, page);

  return (
    <div className="flex flex-col gap-5">
      <p className="text-[13px] text-ink-soft border-l-2 border-line pl-3">
        Proposed fixes only — review each command, its verify step and its rollback before applying it to a device.
      </p>

      {remediable.length > 0 && (
        <Pagination
          page={clampedPage}
          pageCount={pageCount}
          onChange={setPage}
          label={`${remediable.length} control${remediable.length === 1 ? "" : "s"} · page ${clampedPage} of ${pageCount}`}
        />
      )}

      {remediable.length === 0 ? (
        <p className="text-ink-soft text-sm italic">No failed or missing controls on this scan — nothing to remediate.</p>
      ) : (
        <div className="rounded-panel border border-line bg-panel divide-y divide-line overflow-hidden">
          {pageItems.map((r) => (
            <Link
              key={r.control_id}
              href={`/remediation/${scan.scan_id}/${r.control_id}`}
              className="flex items-center justify-between gap-3 p-4 hover:bg-paper-dim transition-colors"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-mono ${
                    r.state === "FAIL" ? "bg-fail-bg text-fail" : "bg-missing-bg text-missing"
                  }`}>
                    {r.state}
                  </span>
                  <span className="font-mono text-xs text-ink-soft">{r.control_id}</span>
                  <span className="text-sm font-medium truncate">{r.canonical_field}</span>
                </div>
                {r.description && <p className="text-xs text-ink-soft mt-1 truncate">{r.description}</p>}
              </div>
              <span className="text-xs text-ink-soft shrink-0">View fix →</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
