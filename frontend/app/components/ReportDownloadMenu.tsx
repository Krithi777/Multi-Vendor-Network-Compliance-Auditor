"use client";

import { useState } from "react";
import { fetchDynamicReportPdf, getReportPdfUrl } from "@/lib/api";

type View = null | "picker" | "dynamic-form";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// Shared by the Report tab, the Reports list, and the Findings page so
// "Download PDF" behaves identically everywhere: one click opens a
// picker between the two report deliverables rather than three separate
// copies of the same fetch/blob/error-handling logic.
export default function ReportDownloadMenu({
  scanId,
  triggerLabel = "Download Report",
  triggerClassName,
}: {
  scanId: string;
  triggerLabel?: string;
  triggerClassName?: string;
}) {
  const [view, setView] = useState<View>(null);
  const [downloading, setDownloading] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [preparedBy, setPreparedBy] = useState("");
  const [comments, setComments] = useState("");

  const defaultTriggerClass =
    "rounded-full bg-ink text-paper px-5 py-2.5 text-sm font-medium hover:bg-ink/90 transition-colors disabled:opacity-60";

  async function downloadComplianceAuditReport() {
    setDownloading(true);
    setPdfError(null);
    try {
      const res = await fetch(getReportPdfUrl(scanId));
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `PDF generation failed (${res.status}).`);
      }
      const blob = await res.blob();
      downloadBlob(blob, `compliance-report-${scanId.slice(0, 8)}.pdf`);
      setView(null);
    } catch (err) {
      setPdfError(err instanceof Error ? err.message : "PDF generation failed.");
    } finally {
      setDownloading(false);
    }
  }

  async function downloadDynamicDeviceReport() {
    setDownloading(true);
    setPdfError(null);
    try {
      const blob = await fetchDynamicReportPdf(scanId, { preparedBy, comments });
      downloadBlob(blob, `device-report-${scanId.slice(0, 8)}.pdf`);
      setView(null);
      setPreparedBy("");
      setComments("");
    } catch (err) {
      setPdfError(err instanceof Error ? err.message : "PDF generation failed.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="inline-flex flex-col items-start gap-2">
      <button
        onClick={() => {
          setPdfError(null);
          setView("picker");
        }}
        disabled={downloading}
        className={triggerClassName ?? defaultTriggerClass}
      >
        {downloading ? "Generating…" : triggerLabel}
      </button>
      {pdfError && <p className="text-xs text-fail">Could not generate PDF: {pdfError}</p>}

      {view && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
          <div className="w-full max-w-md rounded-panel border border-line bg-panel shadow-xl overflow-hidden">
            {view === "picker" && (
              <div className="p-6 flex flex-col gap-4">
                <div>
                  <h3 className="text-sm font-semibold">Choose a report type</h3>
                  <p className="text-xs text-ink-soft mt-1">Both are generated from this scan's real findings.</p>
                </div>

                <button
                  onClick={downloadComplianceAuditReport}
                  disabled={downloading}
                  className="text-left rounded-lg border border-line-soft px-4 py-3 hover:border-ink/40 transition-colors disabled:opacity-60"
                >
                  <p className="text-sm font-medium">Compliance Audit Report</p>
                  <p className="text-xs text-ink-soft mt-1">
                    Full report: device identification, pass/fail findings with severity, and step-by-step CLI
                    remediation.
                  </p>
                </button>

                <button
                  onClick={() => setView("dynamic-form")}
                  disabled={downloading}
                  className="text-left rounded-lg border border-line-soft px-4 py-3 hover:border-ink/40 transition-colors disabled:opacity-60"
                >
                  <p className="text-sm font-medium">Dynamic Device-Specific Report</p>
                  <p className="text-xs text-ink-soft mt-1">
                    Customized by device model and software version, with an optional reviewer note.
                  </p>
                </button>

                <button
                  onClick={() => setView(null)}
                  className="self-end text-xs text-ink-soft hover:text-ink transition-colors"
                >
                  Cancel
                </button>
              </div>
            )}

            {view === "dynamic-form" && (
              <div className="p-6 flex flex-col gap-4">
                <div>
                  <h3 className="text-sm font-semibold">Dynamic Device-Specific Report</h3>
                  <p className="text-xs text-ink-soft mt-1">
                    Optional -- shown on the cover page as reviewer input, separate from the scan data.
                  </p>
                </div>

                <label className="flex flex-col gap-1 text-xs">
                  <span className="text-ink-soft">Prepared by</span>
                  <input
                    value={preparedBy}
                    onChange={(e) => setPreparedBy(e.target.value)}
                    placeholder="Reviewer name"
                    className="rounded-lg border border-line-soft bg-transparent px-3 py-2 text-sm outline-none focus:border-ink/40"
                  />
                </label>

                <label className="flex flex-col gap-1 text-xs">
                  <span className="text-ink-soft">Reviewer comments</span>
                  <textarea
                    value={comments}
                    onChange={(e) => setComments(e.target.value)}
                    placeholder="Any notes to include on the report"
                    rows={3}
                    className="rounded-lg border border-line-soft bg-transparent px-3 py-2 text-sm outline-none focus:border-ink/40 resize-none"
                  />
                </label>

                <div className="flex items-center justify-between gap-3 mt-1">
                  <button
                    onClick={() => setView("picker")}
                    className="text-xs text-ink-soft hover:text-ink transition-colors"
                  >
                    Back
                  </button>
                  <button
                    onClick={downloadDynamicDeviceReport}
                    disabled={downloading}
                    className="rounded-full bg-ink text-paper px-5 py-2 text-sm font-medium hover:bg-ink/90 transition-colors disabled:opacity-60"
                  >
                    {downloading ? "Generating…" : "Download"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}