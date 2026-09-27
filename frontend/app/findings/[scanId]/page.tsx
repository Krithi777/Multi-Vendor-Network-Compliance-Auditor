"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import {
  getScan,
  getFindings,
  getUnmatched,
  getReportPdfUrl,
  pollScanUntilDone,
  ApiError,
  type Scan,
  type FindingsResponse,
  type EvidenceState,
  type Finding,
  type DeviceInfo,
} from "@/lib/api";
import Pagination, { usePagination } from "../../components/Pagination";

const PAGE_SIZE = 4;

const VENDOR_LABELS: Record<string, string> = {
  cisco_ios: "Cisco IOS",
  juniper_junos: "Juniper Junos",
  fortios: "FortiOS",
  panos: "PAN-OS",
  arista_eos: "Arista EOS",
  unknown: "Unknown vendor",
};

// SentinelGrid-style soft tint chips -- each state gets a background tint
// plus a matching text color, so a row reads at a glance without needing
// to parse the label text.
const STATE_BADGE: Record<EvidenceState, string> = {
  PASS: "bg-pass-bg text-pass",
  FAIL: "bg-fail-bg text-fail",
  MISSING: "bg-missing-bg text-missing",
  REVIEW: "bg-review-bg text-review",
  NOT_APPLICABLE: "bg-paper-dim text-ink-soft",
};

const SEVERITY_STYLES: Record<string, string> = {
  high: "border-fail/40 text-fail",
  critical: "border-fail/40 text-fail",
  medium: "border-review/40 text-review",
  low: "border-line text-ink-soft",
};

const FRAMEWORK_LABELS: Record<string, string> = {
  cis: "CIS",
  stig: "DISA STIG",
  iso_27001: "ISO/IEC 27001",
  nist_800_53: "NIST SP 800-53",
};

type LoadState = "loading" | "waiting" | "ready" | "error";

export default function FindingsPage({
  params,
  searchParams,
}: {
  params: { scanId: string };
  searchParams?: { state?: string; framework?: string };
}) {
  const { scanId } = params;
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [scan, setScan] = useState<Scan | null>(null);
  const [findings, setFindings] = useState<FindingsResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const initialState = searchParams?.state as EvidenceState | undefined;
  const initialFramework = searchParams?.framework;
  const [activeFilter, setActiveFilter] = useState<EvidenceState | "ALL">(
    initialState && ["PASS", "FAIL", "MISSING", "REVIEW", "NOT_APPLICABLE"].includes(initialState)
      ? initialState
      : "ALL"
  );
  const [frameworkFilter, setFrameworkFilter] = useState<string>(
    initialFramework && initialFramework in FRAMEWORK_LABELS ? initialFramework : "ALL"
  );
  const [unmatchedCount, setUnmatchedCount] = useState(0);
  const [page, setPage] = useState(1);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const initialScan = await getScan(scanId);
        if (cancelled) return;

        let finalScan = initialScan;
        if (initialScan.status === "processing") {
          setLoadState("waiting");
          finalScan = await pollScanUntilDone(scanId);
        }
        if (cancelled) return;
        setScan(finalScan);

        if (finalScan.status === "error") {
          setLoadState("error");
          setErrorMessage("This scan failed before findings could be produced.");
          return;
        }

        const data = await getFindings(scanId);
        if (cancelled) return;
        setFindings(data);
        setLoadState("ready");

        // Best-effort -- the teaching queue is a bonus banner, not core
        // to the findings page, so a failure here shouldn't block it.
        getUnmatched(scanId)
          .then((u) => {
            if (!cancelled) setUnmatchedCount(u.total_unresolved);
          })
          .catch(() => {});
      } catch (err) {
        if (cancelled) return;
        setLoadState("error");
        setErrorMessage(
          err instanceof ApiError ? err.message : "Could not load findings. Is the backend running?"
        );
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [scanId]);

  if (loadState === "loading" || loadState === "waiting") {
    return (
      <div className="font-mono text-sm text-ink-soft">
        {loadState === "waiting" ? "Scan still processing…" : "Loading findings…"}
      </div>
    );
  }

  if (loadState === "error" || !findings) {
    return (
      <div className="max-w-md">
        <p className="font-mono text-xs uppercase tracking-wide text-fail mb-2">Could not load findings</p>
        <p className="text-ink/90">{errorMessage}</p>
        <Link
          href="/"
          className="mt-4 inline-block text-sm text-ink-soft hover:text-ink underline underline-offset-4"
        >
          Back to ingest
        </Link>
      </div>
    );
  }

  const stateFiltered =
    activeFilter === "ALL" ? findings.results : findings.results.filter((r) => r.state === activeFilter);
  // NOTE: every one of the 20 locked controls has at least one reference
  // in all 4 frameworks (verified against controls/control_schema_cis_stig_iso27001.json --
  // cis/stig/iso_27001/nist_800_53 are all non-empty on every control), so
  // filtering out whole finding rows by framework can never remove a
  // single one -- it silently did nothing before this fix. What the
  // framework toggle *can* honestly change is which framework's
  // reference badges are visible per finding, so that's what it does now.
  const results = stateFiltered;
  const { pageItems, pageCount, clampedPage } = usePagination(results, PAGE_SIZE, page);
  const scannedFrameworks = scan?.frameworks_scanned;

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-center justify-between gap-4">
        <Link
          href={`/scan/${findings.scan_id}`}
          className="inline-flex items-center gap-1.5 text-sm text-ink-soft hover:text-ink w-fit"
        >
          <ArrowLeft className="w-4 h-4" strokeWidth={2} />
          Back to scan
        </Link>
        {/* Same fix as the /scan/[scanId] workspace header: a bulk upload
            with no way back to its sibling files once you'd clicked into
            one. */}
        {scan?.batch_id && (
          <Link
            href={`/batch/${scan.batch_id}`}
            className="text-xs font-medium text-ink-soft hover:text-ink underline underline-offset-4"
          >
            ← Back to batch (other files)
          </Link>
        )}
      </div>

      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-mono text-xs text-ink-soft mb-1">
            scan {findings.scan_id.slice(0, 8)} · {VENDOR_LABELS[findings.vendor] ?? findings.vendor}
            {scan?.filename ? ` · ${scan.filename}` : ""}
          </p>
          <h1 className="font-display text-[28px] font-semibold tracking-tight">Compliance findings</h1>
          <DeviceInfoLine device={scan?.device} />
          {scannedFrameworks && scannedFrameworks.length < 4 && (
            <p className="font-mono text-xs text-ink-soft mt-1.5">
              Audited against: {scannedFrameworks.map((f) => FRAMEWORK_LABELS[f] ?? f).join(", ")}
              {" "}(all 20 controls apply to every framework, so this narrows report scope/labeling, not the control count)
            </p>
          )}
        </div>
        <a
          href={getReportPdfUrl(findings.scan_id)}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 rounded-xl border border-line px-4 py-2 text-sm font-medium text-ink hover:border-ink-soft transition-colors"
        >
          Download PDF report
        </a>
      </div>

      {unmatchedCount > 0 && (
        <Link
          href={`/training/${findings.scan_id}`}
          className="flex items-center justify-between rounded-2xl border border-review/40 bg-review-bg px-5 py-3.5 text-sm text-ink hover:border-review transition-colors"
        >
          <span>
            <span className="font-medium">{unmatchedCount}</span> line{unmatchedCount === 1 ? "" : "s"} the parser
            couldn&apos;t place -- teach the mapping in Training Studio.
          </span>
          <span className="text-review font-mono text-xs">Open →</span>
        </Link>
      )}

      <SummaryBar
        summary={findings.summary}
        activeFilter={activeFilter}
        onFilter={(s) => {
          setActiveFilter(s);
          setPage(1);
        }}
      />

      <FrameworkFilterBar
        active={frameworkFilter}
        onFilter={(f) => {
          setFrameworkFilter(f);
          setPage(1);
        }}
      />

      {results.length > 0 && (
        <Pagination
          page={clampedPage}
          pageCount={pageCount}
          onChange={setPage}
          label={`${results.length} control${results.length === 1 ? "" : "s"} · page ${clampedPage} of ${pageCount}`}
        />
      )}

      <div className="flex flex-col gap-3">
        {results.length === 0 && <p className="text-ink-soft text-sm">No controls match this filter.</p>}
        {pageItems.map((finding) => (
          <FindingRow
            key={finding.control_id}
            finding={finding}
            scanId={findings.scan_id}
            frameworkFilter={frameworkFilter}
          />
        ))}
      </div>
    </div>
  );
}

// Milestone 11 -- only renders fields device_info.py actually found;
// a config with no extractable metadata renders nothing at all rather
// than a row of empty dashes.
function DeviceInfoLine({ device }: { device?: DeviceInfo }) {
  if (!device) return null;
  const parts = [
    device.hostname && `host ${device.hostname}`,
    device.model && `model ${device.model}`,
    device.serial_number && `serial ${device.serial_number}`,
    device.os_version && `os ${device.os_version}`,
  ].filter(Boolean);
  if (parts.length === 0) return null;
  return <p className="font-mono text-xs text-ink-soft mt-1.5">{parts.join(" · ")}</p>;
}

function FrameworkFilterBar({ active, onFilter }: { active: string; onFilter: (key: string) => void }) {
  const options: { key: string; label: string }[] = [{ key: "ALL", label: "All frameworks" }, ...Object.entries(FRAMEWORK_LABELS).map(([key, label]) => ({ key, label }))];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-ink-soft mr-1">Framework:</span>
      {options.map((opt) => (
        <button
          key={opt.key}
          onClick={() => onFilter(opt.key)}
          className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
            active === opt.key
              ? "border-ink bg-ink text-paper"
              : "border-line text-ink-soft hover:border-ink-soft hover:text-ink"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function SummaryBar({
  summary,
  activeFilter,
  onFilter,
}: {
  summary: FindingsResponse["summary"];
  activeFilter: EvidenceState | "ALL";
  onFilter: (state: EvidenceState | "ALL") => void;
}) {
  const total = Object.values(summary).reduce((a, b) => a + b, 0);
  const cells: { key: EvidenceState | "ALL"; label: string; value: number; className: string }[] = [
    { key: "ALL", label: "Total", value: total, className: "text-ink" },
    { key: "FAIL", label: "Fail", value: summary.FAIL, className: "text-fail" },
    { key: "MISSING", label: "Missing", value: summary.MISSING, className: "text-missing" },
    { key: "REVIEW", label: "Review", value: summary.REVIEW, className: "text-review" },
    { key: "PASS", label: "Pass", value: summary.PASS, className: "text-pass" },
    { key: "NOT_APPLICABLE", label: "N/A", value: summary.NOT_APPLICABLE, className: "text-ink-soft" },
  ];

  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-[1px] bg-line border border-line rounded-panel overflow-hidden">
      {cells.map((cell) => (
        <button
          key={cell.key}
          onClick={() => onFilter(cell.key === activeFilter ? "ALL" : cell.key)}
          className={`bg-panel px-4 py-4 text-left transition-colors
            ${activeFilter === cell.key ? "bg-paper-dim" : "hover:bg-paper-dim/60"}`}
        >
          <p className={`font-display text-2xl font-semibold ${cell.className}`}>{cell.value}</p>
          <p className="text-xs text-ink-soft mt-1">{cell.label}</p>
        </button>
      ))}
    </div>
  );
}

function FindingRow({
  finding,
  scanId,
  frameworkFilter,
}: {
  finding: Finding;
  scanId: string;
  frameworkFilter: string;
}) {
  const frameworkGroups = buildFrameworkGroups(finding.frameworks, frameworkFilter);
  const remediable = finding.state === "FAIL" || finding.state === "MISSING";

  return (
    <div className="rounded-2xl border border-line bg-panel p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-mono text-xs text-ink-soft">
            {finding.control_id} · {finding.canonical_field}
          </p>
          <p className="text-ink/90 mt-1 font-medium">{finding.description ?? finding.canonical_field}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span
            className={`rounded-md border px-2 py-0.5 text-[11px] font-mono uppercase ${
              SEVERITY_STYLES[finding.severity] ?? "border-line text-ink-soft"
            }`}
          >
            {finding.severity}
          </span>
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-mono font-medium ${STATE_BADGE[finding.state]}`}>
            {finding.state}
          </span>
        </div>
      </div>

      {finding.evidence_line && (
        <div className="rounded-lg bg-paper-dim border border-line-soft px-3.5 py-2.5 font-mono text-xs text-ink/80 break-all">
          {finding.evidence_line_number != null && (
            <span className="text-ink-soft mr-2">L{finding.evidence_line_number}</span>
          )}
          {finding.evidence_line}
        </div>
      )}

      {(finding.expected_value != null || finding.observed_value != null) && (
        <div className="flex gap-6 text-xs font-mono text-ink-soft">
          <span>
            expected: <span className="text-ink/70">{formatValue(finding.expected_value)}</span>
          </span>
          <span>
            observed: <span className="text-ink/70">{formatValue(finding.observed_value)}</span>
          </span>
        </div>
      )}

      {frameworkGroups.length > 0 && (
        <div className="flex flex-col gap-1.5 rounded-lg bg-paper-dim/60 px-3 py-2.5">
          {frameworkGroups.map((group) => (
            <div key={group.label} className="flex items-start gap-2 text-[11px] font-mono">
              <span className="shrink-0 w-[74px] whitespace-nowrap text-ink-soft/80 uppercase tracking-wide pt-0.5">
                {group.label}
              </span>
              <div className="flex flex-wrap gap-1.5">
                {group.refs.map((ref) => (
                  <span
                    key={ref}
                    className="rounded-md border border-line bg-panel px-2 py-0.5 text-ink-soft"
                  >
                    {ref}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {finding.linked_controls.length > 0 && (
        <p className="text-xs text-ink-soft">
          🔗 Shares evidence with: <span className="font-mono">{finding.linked_controls.join(", ")}</span>
        </p>
      )}

      {finding.notes && <p className="text-xs text-ink-soft italic">{finding.notes}</p>}

      {remediable && (
        <Link
          href={`/remediation/${scanId}/${finding.control_id}`}
          className="self-start text-xs text-ink-soft hover:text-ink underline underline-offset-4"
        >
          View remediation →
        </Link>
      )}
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

// Grouped by framework (one labeled row per framework) instead of a flat
// wall of pills -- a control cited by a dozen benchmarks used to render
// as one long wrapping strip that was hard to scan; grouping keeps each
// framework's references together and visually separate.
function buildFrameworkGroups(
  frameworks: Finding["frameworks"],
  frameworkFilter: string = "ALL"
): { label: string; refs: string[] }[] {
  const groups: { label: string; refs: string[] }[] = [];

  if (frameworkFilter === "ALL" || frameworkFilter === "cis") {
    const cis = (frameworks.cis ?? []).map((ref) => ref.rec_id ?? ref.benchmark ?? "CIS");
    if (cis.length) groups.push({ label: "CIS", refs: cis });
  }

  if (frameworkFilter === "ALL" || frameworkFilter === "stig") {
    const stig = (frameworks.stig ?? []).map((ref) => ref.stig_id ?? ref.rec_id ?? "STIG");
    if (stig.length) groups.push({ label: "STIG", refs: stig });
  }

  if (frameworkFilter === "ALL" || frameworkFilter === "iso_27001") {
    const iso = frameworks.iso_27001 ?? [];
    if (iso.length) groups.push({ label: "ISO 27001", refs: iso });
  }

  if (frameworkFilter === "ALL" || frameworkFilter === "nist_800_53") {
    const nist = frameworks.nist_800_53 ?? [];
    if (nist.length) groups.push({ label: "NIST 800-53", refs: nist });
  }

  return groups;
}