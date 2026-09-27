"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, XCircle, HelpCircle, Eye, MinusCircle, ScanSearch, ShieldHalf, ArrowRight } from "lucide-react";
import {
  listScans,
  getFindings,
  getUnmatched,
  ApiError,
  type ScanListEntry,
  type FindingsSummary,
  type Finding,
  type Vendor,
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

const VENDOR_FILTERS: (Vendor | "ALL")[] = [
  "ALL",
  "cisco_ios",
  "juniper_junos",
  "fortios",
  "panos",
  "arista_eos",
  "unknown",
];

const STATUS_STYLES: Record<string, string> = {
  done: "text-pass",
  processing: "text-review",
  error: "text-fail",
};

const FRAMEWORKS: { key: "cis" | "stig" | "iso_27001" | "nist_800_53"; label: string }[] = [
  { key: "cis", label: "CIS benchmark" },
  { key: "nist_800_53", label: "NIST SP 800-53" },
  { key: "stig", label: "DISA STIG" },
  { key: "iso_27001", label: "ISO/IEC 27001" },
];

const SEVERITY_ORDER: Finding["severity"][] = ["high", "medium", "low"];

type LoadState = "loading" | "ready" | "error";
type DetailState = "idle" | "loading" | "ready" | "partial-error";

interface FrameworkStat {
  label: string;
  pct: number | null;
  passed: number;
  total: number;
}

export default function DashboardPage() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [scans, setScans] = useState<ScanListEntry[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [vendorFilter, setVendorFilter] = useState<Vendor | "ALL">("ALL");
  const [page, setPage] = useState(1);

  // Second, slower pass: framework/severity/unresolved-mapping numbers
  // need every completed scan's findings + unmatched clusters, which the
  // /api/scans list doesn't carry. Fetched once after the scan list
  // arrives so the fast KPI tiles below aren't blocked on it.
  const [detailState, setDetailState] = useState<DetailState>("idle");
  const [allFindings, setAllFindings] = useState<Finding[]>([]);
  const [unresolvedCount, setUnresolvedCount] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    listScans()
      .then((data) => {
        if (cancelled) return;
        setScans(data.scans);
        setLoadState("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setErrorMessage(err instanceof ApiError ? err.message : "Could not load scans. Is the backend running?");
        setLoadState("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (loadState !== "ready") return;
    const doneScanIds = scans.filter((s) => s.status === "done").map((s) => s.scan_id);
    if (doneScanIds.length === 0) {
      setDetailState("ready");
      return;
    }

    let cancelled = false;
    setDetailState("loading");

    Promise.allSettled(doneScanIds.map((id) => getFindings(id))).then((findingsResults) => {
      if (cancelled) return;
      const findings: Finding[] = [];
      let anyFailed = false;
      findingsResults.forEach((r) => {
        if (r.status === "fulfilled") findings.push(...r.value.results);
        else anyFailed = true;
      });
      setAllFindings(findings);

      Promise.allSettled(doneScanIds.map((id) => getUnmatched(id))).then((unmatchedResults) => {
        if (cancelled) return;
        let total = 0;
        unmatchedResults.forEach((r) => {
          if (r.status === "fulfilled") total += r.value.total_unresolved;
          else anyFailed = true;
        });
        setUnresolvedCount(total);
        setDetailState(anyFailed ? "partial-error" : "ready");
      });
    });

    return () => {
      cancelled = true;
    };
  }, [loadState, scans]);

  const visibleScans = useMemo(
    () => (vendorFilter === "ALL" ? scans : scans.filter((s) => s.vendor === vendorFilter)),
    [scans, vendorFilter]
  );

  const fleetTotals = useMemo(() => sumSummaries(scans.map((s) => s.summary)), [scans]);

  const overallCompliancePct = useMemo(() => {
    const denom = fleetTotals.PASS + fleetTotals.FAIL + fleetTotals.MISSING + fleetTotals.REVIEW;
    return denom > 0 ? Math.round((fleetTotals.PASS / denom) * 100) : null;
  }, [fleetTotals]);

  const vendorCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    scans.forEach((s) => {
      counts[s.vendor] = (counts[s.vendor] ?? 0) + 1;
    });
    return counts;
  }, [scans]);

  const frameworkStats = useMemo<FrameworkStat[]>(
    () =>
      FRAMEWORKS.map(({ key, label }) => {
        const applicable = allFindings.filter((f) => {
          const ref = f.frameworks[key];
          return Array.isArray(ref) && ref.length > 0 && f.state !== "NOT_APPLICABLE";
        });
        const passed = applicable.filter((f) => f.state === "PASS").length;
        return {
          label,
          passed,
          total: applicable.length,
          pct: applicable.length > 0 ? Math.round((passed / applicable.length) * 100) : null,
        };
      }),
    [allFindings]
  );

  const severityStats = useMemo(() => {
    const needsAttention = allFindings.filter((f) => f.state === "FAIL" || f.state === "MISSING" || f.state === "REVIEW");
    const counts: Record<string, number> = { high: 0, medium: 0, low: 0 };
    needsAttention.forEach((f) => {
      counts[f.severity] = (counts[f.severity] ?? 0) + 1;
    });
    return counts;
  }, [allFindings]);

  if (loadState === "loading") {
    return <div className="font-mono text-sm text-ink-soft">Loading security posture…</div>;
  }

  if (loadState === "error") {
    return (
      <div className="max-w-md">
        <p className="font-mono text-xs uppercase tracking-wide text-fail mb-2">Could not load dashboard</p>
        <p className="text-ink/90">{errorMessage}</p>
      </div>
    );
  }

  const distinctVendors = Object.keys(vendorCounts).length;

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-display text-[28px] font-semibold tracking-tight">Security compliance overview</h1>
        <p className="text-ink-soft mt-2">
          {scans.length} scan{scans.length === 1 ? "" : "s"} across {distinctVendors || 0} vendor
          {distinctVendors === 1 ? "" : "s"}
        </p>
      </div>
      {/* The standalone "New scan" button that used to live here duplicated
          the "New scan" entry already in the top nav bar -- removed rather
          than kept as a second, redundant call-to-action. */}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <QuickAccessCard
          icon={ScanSearch}
          label="Recent scans"
          value={`${scans.length} scan${scans.length === 1 ? "" : "s"}`}
          href="/reports"
        />
        <QuickAccessCard
          icon={ShieldHalf}
          label="Security posture summary"
          value={overallCompliancePct === null ? "No data yet" : `${overallCompliancePct}% compliant`}
          href="#posture-summary"
        />
      </div>

      <div className="flex gap-4 flex-wrap items-stretch">
        <div className="rounded-panel border border-line bg-panel px-7 py-5 flex items-center gap-5 min-w-[220px]">
          <ComplianceRing pct={overallCompliancePct} />
          <div>
            <p className={`font-display text-[30px] font-semibold leading-none ${complianceColor(overallCompliancePct)}`}>
              {overallCompliancePct === null ? "—" : `${overallCompliancePct}%`}
            </p>
            <p className="text-xs text-ink-soft mt-1.5">Overall compliance</p>
          </div>
        </div>
        <div className="flex-1 min-w-[280px]">
          <FleetSummary summary={fleetTotals} />
        </div>
      </div>

      <div id="posture-summary" className="grid grid-cols-1 lg:grid-cols-2 gap-4 scroll-mt-24">
        <Panel title="Framework compliance">
          {detailState === "loading" ? (
            <DetailLoading />
          ) : (
            <div className="flex flex-col gap-4">
              {frameworkStats.map((f) => (
                <div key={f.label}>
                  <div className="flex justify-between text-xs mb-1.5">
                    <span className="text-ink-soft">{f.label}</span>
                    <span className="font-mono text-ink-soft">
                      {f.pct === null ? "no data" : `${f.pct}% · ${f.passed}/${f.total}`}
                    </span>
                  </div>
                  <div className="h-[6px] rounded-full bg-paper-dim overflow-hidden">
                    <div
                      className="h-full bg-accent rounded-full"
                      style={{ width: f.pct === null ? "0%" : `${f.pct}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Findings by severity">
          {detailState === "loading" ? (
            <DetailLoading />
          ) : (
            <>
              <div className="flex flex-col gap-3">
                {SEVERITY_ORDER.map((sev) => {
                  const value = severityStats[sev] ?? 0;
                  const maxVal = Math.max(1, ...SEVERITY_ORDER.map((s) => severityStats[s] ?? 0));
                  return (
                    <div key={sev}>
                      <div className="flex justify-between text-xs mb-1.5">
                        <span className="capitalize text-ink-soft">{sev}</span>
                        <span className="font-mono font-medium text-ink">{value}</span>
                      </div>
                      <div className="h-[6px] rounded-full bg-paper-dim overflow-hidden">
                        <div
                          className={`h-full rounded-full ${severityDotClass(sev)}`}
                          style={{ width: `${(value / maxVal) * 100}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="mt-4 pt-4 border-t border-line-soft text-xs text-ink-soft">
                {unresolvedCount} unresolved training pattern{unresolvedCount === 1 ? "" : "s"}
                {detailState === "partial-error" && (
                  <span className="text-fail"> · some scans could not be included</span>
                )}
              </div>
            </>
          )}
        </Panel>
      </div>

      <Panel title="Vendor distribution">
        <div className="flex flex-wrap gap-2">
          {Object.entries(vendorCounts).map(([vendor, count]) => (
            <span
              key={vendor}
              className="inline-flex items-center gap-2 rounded-full border border-line bg-paper-dim px-3 py-1.5 text-xs text-ink-soft"
            >
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${vendorDotClass(vendor)}`} />
              {VENDOR_LABELS[vendor] ?? vendor} <span className="text-ink font-medium">{count}</span>
            </span>
          ))}
        </div>
      </Panel>

      <div className="flex flex-wrap gap-2">
        {VENDOR_FILTERS.filter((v) => v === "ALL" || vendorCounts[v]).map((v) => (
          <button
            key={v}
            onClick={() => {
              setVendorFilter(v);
              setPage(1);
            }}
            className={`rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors
              ${vendorFilter === v ? "border-ink bg-ink text-paper" : "border-line bg-panel text-ink-soft hover:border-ink-soft"}`}
          >
            {v === "ALL" ? "All vendors" : VENDOR_LABELS[v] ?? v}
            {v !== "ALL" && <span className="opacity-60 ml-1.5">{vendorCounts[v] ?? 0}</span>}
          </button>
        ))}
      </div>

      <div className="rounded-panel border border-line bg-panel overflow-hidden">
        <div className="px-[22px] py-[18px] border-b border-line-soft flex items-center justify-between">
          <h2 className="text-sm font-semibold">Recent scans</h2>
          <span className="text-[11px] font-mono border border-line rounded-full px-2.5 py-1 text-ink-soft">
            {visibleScans.length} total
          </span>
        </div>
        {visibleScans.length === 0 ? (
          <p className="text-ink-soft text-sm px-[22px] py-6">No scans for this vendor yet.</p>
        ) : (
          <ScanTable scans={visibleScans} page={page} onPageChange={setPage} />
        )}
      </div>
    </div>
  );
}

function QuickAccessCard({
  icon: Icon,
  label,
  value,
  href,
}: {
  icon: typeof ScanSearch;
  label: string;
  value: string;
  href: string;
}) {
  // Internal anchors (posture summary, same page) use a plain <a> so the
  // browser handles the scroll; everything else is an app route via
  // next/link.
  const isAnchor = href.startsWith("#");
  const content = (
    <div className="group flex items-center gap-4 rounded-panel border border-line bg-panel px-5 py-4 transition-all duration-150 hover:-translate-y-0.5 hover:shadow-md hover:border-ink-soft cursor-pointer">
      <div className="w-11 h-11 rounded-xl bg-paper-dim flex items-center justify-center shrink-0">
        <Icon className="w-5 h-5 text-ink" strokeWidth={2} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-ink-soft font-medium">{label}</p>
        <p className="font-display text-[17px] font-semibold leading-tight mt-0.5 truncate">{value}</p>
      </div>
      <ArrowRight className="w-4 h-4 text-ink-soft shrink-0 transition-transform group-hover:translate-x-0.5" strokeWidth={2} />
    </div>
  );
  return isAnchor ? (
    <a href={href}>{content}</a>
  ) : (
    <Link href={href}>{content}</Link>
  );
}

function ScanTable({
  scans,
  page,
  onPageChange,
}: {
  scans: ScanListEntry[];
  page: number;
  onPageChange: (page: number) => void;
}) {
  const { pageItems, pageCount, clampedPage } = usePagination(scans, PAGE_SIZE, page);
  return (
    <>
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="text-left text-[11px] font-medium text-ink-soft px-[22px] pb-3 pt-4 border-b border-line-soft">
              File
            </th>
            <th className="text-left text-[11px] font-medium text-ink-soft px-[22px] pb-3 pt-4 border-b border-line-soft">
              Vendor
            </th>
            <th className="text-left text-[11px] font-medium text-ink-soft px-[22px] pb-3 pt-4 border-b border-line-soft">
              Result
            </th>
            <th className="text-left text-[11px] font-medium text-ink-soft px-[22px] pb-3 pt-4 border-b border-line-soft">
              Controls
            </th>
          </tr>
        </thead>
        <tbody>
          {pageItems.map((scan) => (
            <ScanRow key={scan.scan_id} scan={scan} />
          ))}
        </tbody>
      </table>
      <div className="px-[22px] py-4 border-t border-line-soft">
        <Pagination
          page={clampedPage}
          pageCount={pageCount}
          onChange={onPageChange}
          label={`page ${clampedPage} of ${pageCount}`}
        />
      </div>
    </>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-panel border border-line bg-panel p-5">
      <h2 className="text-xs font-medium text-ink-soft mb-4">{title}</h2>
      {children}
    </div>
  );
}

function DetailLoading() {
  return <p className="font-mono text-xs text-ink-soft">Aggregating across completed scans…</p>;
}

function complianceColor(pct: number | null): string {
  if (pct === null) return "text-ink-soft";
  if (pct >= 80) return "text-pass";
  if (pct >= 50) return "text-review";
  return "text-fail";
}

function severityDotClass(severity: Finding["severity"]): string {
  if (severity === "high") return "bg-fail";
  if (severity === "medium") return "bg-review";
  return "bg-missing";
}

const VENDOR_DOT_CLASSES: Record<string, string> = {
  cisco_ios: "bg-accent",
  juniper_junos: "bg-pass",
  fortios: "bg-review",
  panos: "bg-fail",
  arista_eos: "bg-ink-soft",
  unknown: "bg-missing",
};

function vendorDotClass(vendor: string): string {
  return VENDOR_DOT_CLASSES[vendor] ?? "bg-missing";
}

function ComplianceRing({ pct }: { pct: number | null }) {
  const safePct = pct ?? 0;
  const ringColor = pct === null ? "#E4E7EB" : pct >= 80 ? "#0A7A4C" : pct >= 50 ? "#B4590A" : "#B3261E";
  return (
    <div
      className="relative w-14 h-14 rounded-full shrink-0"
      style={{
        background: `conic-gradient(${ringColor} ${safePct * 3.6}deg, #E4E7EB 0deg)`,
      }}
    >
      <div className="absolute inset-[3px] rounded-full bg-panel" />
    </div>
  );
}

function FleetSummary({ summary }: { summary: FindingsSummary }) {
  const cells: {
    label: string;
    value: number;
    className: string;
    bg: string;
    bar: string;
    border: string;
    Icon: typeof CheckCircle2;
  }[] = [
    { label: "Pass", value: summary.PASS, className: "text-pass", bg: "bg-pass-bg", bar: "bg-pass", border: "border-pass/15", Icon: CheckCircle2 },
    { label: "Fail", value: summary.FAIL, className: "text-fail", bg: "bg-fail-bg", bar: "bg-fail", border: "border-fail/15", Icon: XCircle },
    { label: "Missing", value: summary.MISSING, className: "text-missing", bg: "bg-missing-bg", bar: "bg-missing", border: "border-line", Icon: HelpCircle },
    { label: "Review", value: summary.REVIEW, className: "text-review", bg: "bg-review-bg", bar: "bg-review", border: "border-review/15", Icon: Eye },
    { label: "N/A", value: summary.NOT_APPLICABLE, className: "text-ink-soft", bg: "bg-paper-dim", bar: "bg-ink-soft/40", border: "border-line", Icon: MinusCircle },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 h-full">
      {cells.map((cell) => (
        <div
          key={cell.label}
          className={`group relative overflow-hidden rounded-2xl border ${cell.border} bg-panel px-5 py-4 transition-all duration-150 hover:-translate-y-0.5 hover:shadow-md`}
        >
          <span className={`absolute inset-x-0 top-0 h-[3px] ${cell.bar}`} />
          <div className={`w-9 h-9 rounded-xl ${cell.bg} flex items-center justify-center mb-3`}>
            <cell.Icon className={`w-[18px] h-[18px] ${cell.className}`} strokeWidth={2} />
          </div>
          <p className={`font-display text-[28px] font-semibold leading-none ${cell.className}`}>{cell.value}</p>
          <p className="text-xs text-ink-soft mt-2 font-medium">{cell.label}</p>
        </div>
      ))}
    </div>
  );
}

function ScanRow({ scan }: { scan: ScanListEntry }) {
  const router = useRouter();
  const total = Object.values(scan.summary).reduce((a, b) => a + b, 0);
  const clickable = scan.status === "done";

  return (
    <tr
      onClick={() => clickable && router.push(`/scan/${scan.scan_id}`)}
      className={`transition-colors ${clickable ? "cursor-pointer hover:bg-paper-dim" : "opacity-70"}`}
    >
      <td className="px-[22px] py-[15px] border-b border-line-soft min-w-0">
        <p className="truncate max-w-xs">{scan.filename}</p>
        <p className="font-mono text-[11px] text-ink-soft mt-0.5">{new Date(scan.uploaded_at).toLocaleString()}</p>
      </td>
      <td className="px-[22px] py-[15px] border-b border-line-soft font-mono text-xs text-ink-soft">
        {VENDOR_LABELS[scan.vendor] ?? scan.vendor}
      </td>
      <td className="px-[22px] py-[15px] border-b border-line-soft">
        {clickable ? (
          <MiniTally summary={scan.summary} />
        ) : (
          <span className={`text-xs font-mono uppercase ${STATUS_STYLES[scan.status] ?? "text-ink-soft"}`}>
            {scan.status}
          </span>
        )}
      </td>
      <td className="px-[22px] py-[15px] border-b border-line-soft text-xs text-ink-soft">{total}</td>
    </tr>
  );
}

function MiniTally({ summary }: { summary: FindingsSummary }) {
  const parts: { label: string; value: number; className: string }[] = [
    { label: "F", value: summary.FAIL, className: "text-fail" },
    { label: "M", value: summary.MISSING, className: "text-missing" },
    { label: "R", value: summary.REVIEW, className: "text-review" },
    { label: "P", value: summary.PASS, className: "text-pass" },
  ];
  return (
    <div className="flex items-center gap-3 font-mono text-xs">
      {parts.map((p) => (
        <span key={p.label} className={p.className}>
          {p.value}
          <span className="text-ink-soft">{p.label}</span>
        </span>
      ))}
    </div>
  );
}

function sumSummaries(summaries: FindingsSummary[]): FindingsSummary {
  const total: FindingsSummary = { PASS: 0, FAIL: 0, MISSING: 0, REVIEW: 0, NOT_APPLICABLE: 0 };
  summaries.forEach((s) => {
    total.PASS += s.PASS;
    total.FAIL += s.FAIL;
    total.MISSING += s.MISSING;
    total.REVIEW += s.REVIEW;
    total.NOT_APPLICABLE += s.NOT_APPLICABLE;
  });
  return total;
}