"use client";

import Link from "next/link";
import { useScanWorkspace } from "./scan-context";
import type { EvidenceState, Finding } from "@/lib/api";

const STATE_LABELS: Record<EvidenceState, string> = {
  PASS: "Pass",
  FAIL: "Fail",
  MISSING: "Missing",
  REVIEW: "Review",
  NOT_APPLICABLE: "N/A",
};

const STATE_BADGE: Record<EvidenceState, string> = {
  PASS: "bg-pass-bg text-pass",
  FAIL: "bg-fail-bg text-fail",
  MISSING: "bg-missing-bg text-missing",
  REVIEW: "bg-review-bg text-review",
  NOT_APPLICABLE: "bg-paper-dim text-ink-soft",
};

const FRAMEWORK_LABELS: Record<string, string> = {
  cis: "CIS",
  stig: "DISA STIG",
  iso_27001: "ISO/IEC 27001",
  nist_800_53: "NIST SP 800-53",
};

// Only a framework actually cited by at least one control appears here —
// fabricating a "0 controls" row for an uncited framework would overstate
// coverage (same principle phase9/report.py's tests enforce for the PDF).
function frameworkCoverage(results: Finding[]) {
  const byFramework: Record<string, { total: number; pass: number }> = {};
  for (const r of results) {
    for (const key of Object.keys(FRAMEWORK_LABELS)) {
      const refs = (r.frameworks as Record<string, unknown[] | undefined>)[key];
      if (refs && refs.length > 0) {
        byFramework[key] ??= { total: 0, pass: 0 };
        byFramework[key].total += 1;
        if (r.state === "PASS") byFramework[key].pass += 1;
      }
    }
  }
  return Object.entries(byFramework).map(([key, { total, pass }]) => ({
    key,
    label: FRAMEWORK_LABELS[key],
    total,
    pass,
    pct: total ? Math.round((100 * pass) / total) : 0,
  }));
}

export default function ScanOverviewPage() {
  const { loadState, scan, findings, errorMessage } = useScanWorkspace();

  if (loadState === "loading" || loadState === "waiting") {
    return <p className="font-mono text-sm text-ink-soft">{loadState === "waiting" ? "Processing scan…" : "Loading…"}</p>;
  }
  if (loadState === "error" || !scan) {
    return (
      <div className="max-w-md">
        <p className="font-mono text-xs uppercase tracking-wide text-fail mb-2">Scan unavailable</p>
        <p className="text-ink/90">{errorMessage}</p>
      </div>
    );
  }
  if (!findings) {
    return <p className="font-mono text-sm text-ink-soft">No findings yet.</p>;
  }

  const total = Object.values(findings.summary).reduce((a, b) => a + b, 0);
  const scoreable = total - findings.summary.NOT_APPLICABLE;
  const compliancePct = scoreable ? Math.round((100 * findings.summary.PASS) / scoreable) : 0;
  const criticalFails = findings.results.filter((r) => r.state === "FAIL" && r.severity === "high").length;
  const coverage = frameworkCoverage(findings.results);
  const device = scan.device;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Compliance score" value={`${compliancePct}%`} />
        <StatCard label="High-severity fails" value={String(criticalFails)} accent={criticalFails > 0 ? "text-fail" : undefined} />
        <StatCard label="Controls evaluated" value={String(total)} />
        <StatCard label="Vendor" value={scan.vendor} mono />
      </div>

      <div className="rounded-panel border border-line bg-panel p-5">
        <p className="text-xs font-mono uppercase tracking-wide text-ink-soft mb-3">Control status breakdown</p>
        <div className="flex flex-wrap gap-2">
          {(Object.keys(findings.summary) as EvidenceState[]).map((state) => (
            <Link
              key={state}
              href={`/findings/${scan.scan_id}?state=${state}`}
              className={`rounded-full px-3 py-1.5 text-xs font-mono ${STATE_BADGE[state]}`}
            >
              {STATE_LABELS[state]} {findings.summary[state]}
            </Link>
          ))}
        </div>
      </div>

      {coverage.length > 0 && (
        <div className="rounded-panel border border-line bg-panel p-5">
          <p className="text-xs font-mono uppercase tracking-wide text-ink-soft mb-3">Framework coverage</p>
          <div className="flex flex-col gap-3">
            {coverage.map((row) => (
              <Link
                key={row.key}
                href={`/findings/${scan.scan_id}?framework=${row.key}`}
                className="flex items-center gap-3 -mx-2 px-2 py-1 rounded-lg hover:bg-paper-dim/60 transition-colors"
              >
                <span className="w-32 shrink-0 text-sm font-medium">{row.label}</span>
                <div className="flex-1 h-2 rounded-full bg-paper-dim overflow-hidden">
                  <div className="h-full bg-pass" style={{ width: `${row.pct}%` }} />
                </div>
                <span className="w-20 shrink-0 text-right text-xs font-mono text-ink-soft">
                  {row.pass}/{row.total} pass
                </span>
              </Link>
            ))}
          </div>
          <p className="text-[11px] text-ink-soft mt-3">
            Every baseline control here happens to be cited by all four frameworks, so each row currently covers
            the same 20 controls -- click a row to view its findings filtered to that framework.
          </p>
        </div>
      )}

      {device && (device.hostname || device.model || device.serial_number || device.os_version) && (
        <div className="rounded-panel border border-line bg-panel p-5">
          <p className="text-xs font-mono uppercase tracking-wide text-ink-soft mb-3">Device metadata</p>
          <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
            <Field label="Hostname" value={device.hostname} />
            <Field label="Model" value={device.model} />
            <Field label="Serial number" value={device.serial_number} />
            <Field label="OS version" value={device.os_version} />
          </dl>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, accent, mono }: { label: string; value: string; accent?: string; mono?: boolean }) {
  return (
    <div className="rounded-panel border border-line bg-panel p-4">
      <p className="text-[11px] font-mono uppercase tracking-wide text-ink-soft mb-1.5">{label}</p>
      <p className={`text-2xl font-display font-semibold ${accent ?? ""} ${mono ? "font-mono text-base" : ""}`}>{value}</p>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-[11px] font-mono uppercase tracking-wide text-ink-soft mb-1">{label}</dt>
      <dd className={value ? "text-ink" : "text-ink-soft italic"}>{value || "unknown"}</dd>
    </div>
  );
}