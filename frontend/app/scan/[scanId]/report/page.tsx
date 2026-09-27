"use client";

import ReportDownloadMenu from "../../../components/ReportDownloadMenu";
import { useScanWorkspace } from "../scan-context";

export default function ReportTabPage() {
  const { loadState, scan, findings, errorMessage } = useScanWorkspace();

  if (loadState === "loading" || loadState === "waiting") {
    return <p className="font-mono text-sm text-ink-soft">{loadState === "waiting" ? "Processing scan…" : "Loading…"}</p>;
  }
  if (loadState === "error" || !scan) {
    return <p className="text-ink/90">{errorMessage}</p>;
  }

  const total = findings ? Object.values(findings.summary).reduce((a, b) => a + b, 0) : 0;

  const tallyCells: { label: string; value: number; className: string }[] = findings
    ? [
        { label: "Pass", value: findings.summary.PASS, className: "text-pass" },
        { label: "Fail", value: findings.summary.FAIL, className: "text-fail" },
        { label: "Missing", value: findings.summary.MISSING, className: "text-missing" },
        { label: "Review", value: findings.summary.REVIEW, className: "text-review" },
      ]
    : [];

  return (
    <div className="rounded-panel border border-line bg-panel overflow-hidden">
      <div className="p-6 flex flex-col gap-2 border-b border-line-soft max-w-2xl">
        <h2 className="text-sm font-semibold">Compliance report</h2>
        <p className="text-ink-soft text-sm leading-relaxed">
          Generates a PDF covering device metadata, the compliance summary, framework mappings, every finding
          with its evidence, and a remediation summary for failed or missing controls.
        </p>
      </div>

      {findings && (
        <div className="grid grid-cols-3 sm:grid-cols-5 gap-[1px] bg-line border-b border-line-soft">
          <div className="bg-panel px-5 py-4">
            <p className="font-display text-xl font-semibold text-ink">{total}</p>
            <p className="text-xs text-ink-soft mt-0.5">Controls evaluated</p>
          </div>
          {tallyCells.map((cell) => (
            <div key={cell.label} className="bg-panel px-5 py-4">
              <p className={`font-display text-xl font-semibold ${cell.className}`}>{cell.value}</p>
              <p className="text-xs text-ink-soft mt-0.5">{cell.label}</p>
            </div>
          ))}
        </div>
      )}

      <div className="p-6 flex items-center gap-4 flex-wrap">
        <ReportDownloadMenu scanId={scan.scan_id} triggerLabel="Download Report" />
      </div>
    </div>
  );
}