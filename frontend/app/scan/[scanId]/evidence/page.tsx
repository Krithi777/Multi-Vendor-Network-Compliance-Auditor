"use client";

// Flaws doc item #9: evidence was real (findings already carried
// evidence_line/evidence_line_number) but only ever shown buried inside
// a findings card. This tab surfaces it as its own experience: one row
// per control that has a concrete config line behind it, with the exact
// line, line number, canonical field, matched control and the framework
// references that line's compliance state feeds into.

import { useState } from "react";
import Link from "next/link";
import { useScanWorkspace } from "../scan-context";
import type { EvidenceState, Finding } from "@/lib/api";
import Pagination, { usePagination } from "../../../components/Pagination";

const PAGE_SIZE = 4;

const STATE_BADGE: Record<EvidenceState, string> = {
  PASS: "bg-pass-bg text-pass",
  FAIL: "bg-fail-bg text-fail",
  MISSING: "bg-missing-bg text-missing",
  REVIEW: "bg-review-bg text-review",
  NOT_APPLICABLE: "bg-paper-dim text-ink-soft",
};

function frameworkGroups(f: Finding["frameworks"]): { label: string; refs: string[] }[] {
  const groups: { label: string; refs: string[] }[] = [];
  const cis = (f.cis ?? []).map((ref) => ref.rec_id ?? "CIS").filter(Boolean);
  if (cis.length) groups.push({ label: "CIS", refs: cis });
  const stig = (f.stig ?? []).map((ref) => ref.stig_id ?? "STIG").filter(Boolean);
  if (stig.length) groups.push({ label: "STIG", refs: stig });
  const iso = f.iso_27001 ?? [];
  if (iso.length) groups.push({ label: "ISO 27001", refs: iso });
  const nist = f.nist_800_53 ?? [];
  if (nist.length) groups.push({ label: "NIST 800-53", refs: nist });
  return groups;
}

export default function EvidencePage() {
  const { loadState, scan, findings, errorMessage } = useScanWorkspace();
  const [filter, setFilter] = useState<EvidenceState | "ALL">("ALL");
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

  const withEvidence = findings.results.filter((r) => r.evidence_line);
  const withoutEvidence = findings.results.length - withEvidence.length;
  const rows = filter === "ALL" ? withEvidence : withEvidence.filter((r) => r.state === filter);
  const { pageItems, pageCount, clampedPage } = usePagination(rows, PAGE_SIZE, page);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-ink-soft text-sm max-w-lg">
          The exact configuration line behind every evaluated control — {withEvidence.length} of{" "}
          {findings.results.length} controls have a concrete line of evidence.
          {withoutEvidence > 0 && ` The remaining ${withoutEvidence} are MISSING or NOT_APPLICABLE, so there's nothing to show a line for.`}
        </p>
        <div className="flex flex-wrap gap-1.5">
          {(["ALL", "PASS", "FAIL", "REVIEW"] as const).map((s) => (
            <button
              key={s}
              onClick={() => {
                setFilter(s);
                setPage(1);
              }}
              className={`rounded-full border px-3 py-1.5 text-xs font-mono transition-colors ${
                filter === s ? "border-ink bg-ink text-paper" : "border-line bg-panel text-ink-soft hover:border-ink-soft"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {rows.length > 0 && (
        <Pagination
          page={clampedPage}
          pageCount={pageCount}
          onChange={setPage}
          label={`${rows.length} row${rows.length === 1 ? "" : "s"} · page ${clampedPage} of ${pageCount}`}
        />
      )}

      {rows.length === 0 ? (
        <p className="text-ink-soft text-sm italic">No evidence rows match this filter.</p>
      ) : (
        <div className="rounded-panel border border-line bg-panel divide-y divide-line overflow-hidden">
          {pageItems.map((r) => {
            const groups = frameworkGroups(r.frameworks);
            return (
              <div key={r.control_id} className="p-4 flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-mono ${STATE_BADGE[r.state]}`}>{r.state}</span>
                  <span className="font-mono text-xs text-ink-soft">{r.control_id}</span>
                  <span className="text-sm font-medium">{r.canonical_field}</span>
                  {r.linked_controls.length > 0 && (
                    <span className="text-[11px] font-mono text-ink-soft" title="Shares this evidence line with another control">
                      shared with {r.linked_controls.join(", ")}
                    </span>
                  )}
                </div>

                <div className="flex items-start gap-3 rounded-lg bg-paper-dim px-3 py-2">
                  <span className="font-mono text-xs text-ink-soft shrink-0 pt-0.5">
                    {r.evidence_line_number != null ? `L${r.evidence_line_number}` : "—"}
                  </span>
                  <code className="font-mono text-sm text-ink break-all">{r.evidence_line}</code>
                </div>

                {groups.length > 0 && (
                  <div className="flex flex-col gap-1.5 rounded-lg bg-paper-dim/60 px-3 py-2">
                    {groups.map((group) => (
                      <div key={group.label} className="flex items-start gap-2 text-[11px] font-mono">
                        <span className="shrink-0 w-[74px] whitespace-nowrap text-ink-soft/80 uppercase tracking-wide pt-0.5">
                          {group.label}
                        </span>
                        <div className="flex flex-wrap gap-1.5">
                          {group.refs.map((ref) => (
                            <span key={ref} className="rounded-md border border-line bg-panel px-2 py-0.5 text-ink-soft">
                              {ref}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {r.notes && <p className="text-xs text-ink-soft italic">{r.notes}</p>}

                <Link
                  href={`/findings/${scan.scan_id}?control=${r.control_id}`}
                  className="text-xs text-ink-soft hover:text-ink underline underline-offset-4 w-fit"
                >
                  View in findings
                </Link>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
