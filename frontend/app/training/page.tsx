"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  listScans,
  getUnmatched,
  getFindings,
  ApiError,
  type ScanListEntry,
  type UnmatchedCluster,
  type Finding,
} from "@/lib/api";
import Pagination, { usePagination } from "../components/Pagination";

const PAGE_SIZE = 5;

const VENDOR_LABELS: Record<string, string> = {
  cisco_ios: "Cisco IOS",
  juniper_junos: "Juniper Junos",
  fortios: "FortiOS",
  panos: "PAN-OS",
  arista_eos: "Arista EOS",
  unknown: "Unknown vendor",
};

// A cluster only carries a confidence_bucket once phase7 has fused a
// real suggestion for it (>=3 confirmed examples). Everything else is
// "untaught" -- not a fourth confidence tier, just "no signal yet".
type BucketKey = "HIGH" | "MEDIUM" | "LOW" | "UNTAUGHT";

interface BucketCounts {
  HIGH: number;
  MEDIUM: number;
  LOW: number;
  UNTAUGHT: number;
}

function emptyCounts(): BucketCounts {
  return { HIGH: 0, MEDIUM: 0, LOW: 0, UNTAUGHT: 0 };
}

function countClustersByBucket(clusters: UnmatchedCluster[]): BucketCounts {
  const counts = emptyCounts();
  for (const c of clusters) {
    if (c.resolved_count >= c.count) continue; // fully resolved, not part of the backlog
    const key: BucketKey = c.suggestion ? c.suggestion.confidence_bucket : "UNTAUGHT";
    counts[key] += 1;
  }
  return counts;
}

// "High risk" here means an actual open compliance gap, not a training
// backlog item -- a high-severity control that isn't PASS/NOT_APPLICABLE
// for this scan's vendor. Independent of whether its unmatched lines
// have been taught yet, so it stays meaningful even on day one when
// every cluster is still UNTAUGHT.
function countHighRiskFindings(findings: Finding[]): number {
  return findings.filter((f) => f.severity === "high" && f.state !== "PASS" && f.state !== "NOT_APPLICABLE").length;
}

interface TrainingRow {
  scan: ScanListEntry;
  totalUnresolved: number;
  coverageBeforePct: number | null;
  buckets: BucketCounts;
  highRiskFindings: number;
}

type LoadState = "loading" | "ready" | "error";

const BUCKET_META: { key: BucketKey; label: string; dot: string; text: string }[] = [
  { key: "HIGH", label: "High confidence", dot: "bg-pass", text: "text-pass" },
  { key: "MEDIUM", label: "Medium confidence", dot: "bg-review", text: "text-review" },
  { key: "LOW", label: "Low confidence", dot: "bg-fail", text: "text-fail" },
  { key: "UNTAUGHT", label: "Untaught", dot: "bg-missing", text: "text-missing" },
];

export default function TrainingIndexPage() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [rows, setRows] = useState<TrainingRow[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const { scans } = await listScans();
        const completed = scans.filter((s) => s.status === "done");

        // No bulk "unresolved + high-risk counts across scans" endpoint
        // exists yet -- this is 2N per-scan calls rather than a
        // fabricated/estimated count. Fine at hackathon scale; would
        // need backend aggregate endpoints if this list grows into the
        // hundreds.
        const [unmatchedSettled, findingsSettled] = await Promise.all([
          Promise.allSettled(completed.map((scan) => getUnmatched(scan.scan_id))),
          Promise.allSettled(completed.map((scan) => getFindings(scan.scan_id))),
        ]);

        if (cancelled) return;
        const withUnresolved: TrainingRow[] = [];
        completed.forEach((scan, i) => {
          const unmatched = unmatchedSettled[i];
          if (unmatched.status !== "fulfilled" || unmatched.value.total_unresolved <= 0) return;
          const findings = findingsSettled[i];
          withUnresolved.push({
            scan,
            totalUnresolved: unmatched.value.total_unresolved,
            coverageBeforePct: unmatched.value.coverage_before_pct,
            buckets: countClustersByBucket(unmatched.value.clusters),
            highRiskFindings: findings.status === "fulfilled" ? countHighRiskFindings(findings.value.results) : 0,
          });
        });
        withUnresolved.sort((a, b) => b.totalUnresolved - a.totalUnresolved);
        setRows(withUnresolved);
        setLoadState("ready");
      } catch (err) {
        if (cancelled) return;
        setErrorMessage(err instanceof ApiError ? err.message : "Could not load training queue. Is the backend running?");
        setLoadState("error");
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loadState === "loading") {
    return <div className="font-mono text-sm text-ink-soft">Loading training queue…</div>;
  }

  if (loadState === "error") {
    return (
      <div className="max-w-md">
        <p className="font-mono text-xs uppercase tracking-wide text-fail mb-2">Could not load training queue</p>
        <p className="text-ink/90">{errorMessage}</p>
      </div>
    );
  }

  const totals = rows.reduce<BucketCounts>((acc, r) => {
    acc.HIGH += r.buckets.HIGH;
    acc.MEDIUM += r.buckets.MEDIUM;
    acc.LOW += r.buckets.LOW;
    acc.UNTAUGHT += r.buckets.UNTAUGHT;
    return acc;
  }, emptyCounts());

  const totalUnresolvedLines = rows.reduce((sum, r) => sum + r.totalUnresolved, 0);
  const totalHighRisk = rows.reduce((sum, r) => sum + r.highRiskFindings, 0);
  const coveragePctValues = rows.map((r) => r.coverageBeforePct).filter((v): v is number => v != null);
  const avgCoveragePct =
    coveragePctValues.length > 0 ? coveragePctValues.reduce((a, b) => a + b, 0) / coveragePctValues.length : null;
  const highRiskScanCount = rows.filter((r) => r.highRiskFindings > 0).length;

  // The four "at a glance" cards -- what actually needs a decision made
  // right now, not the raw confidence-bucket breakdown (kept further
  // down for anyone drilling in).
  const KPI_CARDS: { label: string; value: string; sub: string; tone: "fail" | "review" | "ink" | "pass" }[] = [
    {
      label: "Unresolved lines",
      value: String(totalUnresolvedLines),
      sub: rows.length > 0 ? `across ${rows.length} scan${rows.length === 1 ? "" : "s"}` : "nothing queued",
      tone: totalUnresolvedLines > 0 ? "review" : "pass",
    },
    {
      label: "High risk findings",
      value: String(totalHighRisk),
      sub: highRiskScanCount > 0 ? `in ${highRiskScanCount} scan${highRiskScanCount === 1 ? "" : "s"}` : "none open",
      tone: totalHighRisk > 0 ? "fail" : "pass",
    },
    {
      label: "Scans awaiting training",
      value: String(rows.length),
      sub: "with unresolved lines",
      tone: "ink",
    },
    {
      label: "Avg. coverage before training",
      value: avgCoveragePct != null ? `${avgCoveragePct.toFixed(0)}%` : "—",
      sub: "auto-mapped, pre-teaching",
      tone: avgCoveragePct != null && avgCoveragePct < 50 ? "review" : "ink",
    },
  ];

  const TONE_CLASSES: Record<string, string> = {
    fail: "text-fail",
    review: "text-review",
    ink: "text-ink",
    pass: "text-pass",
  };

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-display text-[28px] sm:text-[32px] font-semibold tracking-tight leading-tight">
          Training
        </h1>
        <p className="text-ink-soft mt-3 max-w-xl leading-relaxed">
          Configuration lines the parser couldn&apos;t confidently place. Confirm a mapping once and the fused
          syntax/context/value/framework/precedent signals generalize it across the rest of that scan.
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {KPI_CARDS.map((card) => (
          <div key={card.label} className="rounded-2xl border border-line bg-panel px-4 py-4">
            <p className="text-[11px] font-mono uppercase tracking-wide text-ink-soft">{card.label}</p>
            <p className={`font-mono text-3xl font-semibold mt-1.5 ${TONE_CLASSES[card.tone]}`}>{card.value}</p>
            <p className="text-xs text-ink-soft mt-1">{card.sub}</p>
          </div>
        ))}
      </div>

      {rows.length > 0 && <ConfidenceSummary totals={totals} />}

      {rows.length === 0 ? (
        <p className="text-ink-soft text-sm">
          Nothing waiting on human review right now -- every completed scan is fully mapped.
        </p>
      ) : (
        <TrainingQueue rows={rows} page={page} onPageChange={setPage} />
      )}
    </div>
  );
}

// The "trained" buckets (HIGH/MEDIUM/LOW) only carry a number once at
// least one cluster fleet-wide has a fused suggestion; on a fresh
// install (or right after onboarding a batch of new scans) every one of
// them reads 0 and the four-tile breakdown is just noise on top of the
// per-scan badges already shown below. Collapse to a single compact
// line in that case instead of four mostly-empty tiles.
function ConfidenceSummary({ totals }: { totals: BucketCounts }) {
  const trained = totals.HIGH + totals.MEDIUM + totals.LOW;
  const total = trained + totals.UNTAUGHT;

  if (trained === 0) {
    return (
      <div className="rounded-2xl border border-line-soft bg-paper-dim px-4 py-3 flex items-center justify-between gap-3 flex-wrap">
        <span className="flex items-center gap-2 text-xs text-ink-soft">
          <span className="w-2 h-2 rounded-full shrink-0 bg-missing" />
          {total} cluster{total === 1 ? "" : "s"} untaught -- no confidence signal yet
        </span>
        <span className="text-[11px] font-mono text-ink-soft">Confirm 3 examples in a cluster to start scoring it</span>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-line-soft bg-paper-dim p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[11px] font-mono uppercase tracking-wide text-ink-soft">Clusters by confidence</h3>
        <span className="text-[11px] font-mono text-ink-soft">{total} total</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {BUCKET_META.map((b) => (
          <div key={b.key} className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full shrink-0 ${b.dot}`} />
            <span className="text-xs text-ink-soft">{b.label}</span>
            <span className={`ml-auto font-mono text-sm font-medium ${b.text}`}>{totals[b.key]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TrainingQueue({
  rows,
  page,
  onPageChange,
}: {
  rows: TrainingRow[];
  page: number;
  onPageChange: (page: number) => void;
}) {
  const { pageItems, pageCount, clampedPage } = usePagination(rows, PAGE_SIZE, page);
  return (
    <div className="flex flex-col gap-4">
      <Pagination
        page={clampedPage}
        pageCount={pageCount}
        onChange={onPageChange}
        label={`${rows.length} scan${rows.length === 1 ? "" : "s"} · page ${clampedPage} of ${pageCount}`}
      />
      <div className="flex flex-col gap-3">
        {pageItems.map(({ scan, totalUnresolved, coverageBeforePct, buckets, highRiskFindings }) => {
          // Flagged when either the pre-training coverage was genuinely
          // low, or the scan has open high-severity findings -- most
          // rows here are routine teaching backlog, not a problem.
          const isUrgent = (coverageBeforePct != null && coverageBeforePct < 50) || highRiskFindings > 0;
          return (
            <Link
              key={scan.scan_id}
              href={`/training/${scan.scan_id}`}
              className={`relative rounded-2xl border px-5 py-4 flex items-center justify-between gap-4 transition-colors ${
                isUrgent
                  ? "border-line bg-panel hover:border-fail/40"
                  : "border-line bg-panel hover:border-ink-soft"
              }`}
            >
              {isUrgent && (
                <span className="absolute -top-2.5 left-4 flex items-center gap-1 rounded-full bg-fail text-paper px-2.5 py-0.5 text-[10px] font-mono font-semibold uppercase tracking-wide shadow-sm">
                  <span className="w-1.5 h-1.5 rounded-full bg-paper" />
                  {highRiskFindings > 0 ? "High risk" : "Low coverage"}
                </span>
              )}
              <div className="min-w-0">
                <p className="text-ink font-medium truncate">{scan.filename}</p>
                <p className="font-mono text-xs text-ink-soft mt-1">
                  {VENDOR_LABELS[scan.vendor] ?? scan.vendor}
                  {coverageBeforePct != null ? ` · ${coverageBeforePct.toFixed(0)}% coverage before training` : ""}
                </p>
                <div className="flex items-center gap-3 mt-1.5 font-mono text-[11px] text-ink-soft flex-wrap">
                  {highRiskFindings > 0 && (
                    <span className="flex items-center gap-1 text-fail">
                      <span className="w-1.5 h-1.5 rounded-full bg-fail" />
                      {highRiskFindings} high-risk finding{highRiskFindings === 1 ? "" : "s"}
                    </span>
                  )}
                  {BUCKET_META.filter((b) => buckets[b.key] > 0).map((b) => (
                    <span key={b.key} className="flex items-center gap-1">
                      <span className={`w-1.5 h-1.5 rounded-full ${b.dot}`} />
                      {buckets[b.key]} {b.label.replace(" confidence", "").toLowerCase()}
                    </span>
                  ))}
                </div>
              </div>
              <span className={`shrink-0 font-mono text-xs ${isUrgent ? "text-fail" : "text-ink-soft"}`}>
                {totalUnresolved} unresolved →
              </span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}