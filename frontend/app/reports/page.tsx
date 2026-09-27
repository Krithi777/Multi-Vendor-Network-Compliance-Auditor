"use client";

// This route was previously a stray copy of the /scan/[scanId] Overview
// page (importing "./scan-context", which only exists under
// /scan/[scanId]/ -- caused the "Module not found: Can't resolve
// './scan-context'" build error). /reports is linked from the Navbar
// and from the Dashboard's "Recent scans" quick-access card, so it's
// meant to be a list of scans/reports, not a single scan's workspace --
// rebuilt as that, reusing the same listScans() data the Dashboard uses.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { FileBarChart2 } from "lucide-react";
import { listScans, getReportPdfUrl, ApiError, type ScanListEntry, type FindingsSummary } from "@/lib/api";
import Pagination, { usePagination } from "../components/Pagination";

const PAGE_SIZE = 8;

const VENDOR_LABELS: Record<string, string> = {
  cisco_ios: "Cisco IOS",
  juniper_junos: "Juniper Junos",
  fortios: "FortiOS",
  panos: "PAN-OS",
  arista_eos: "Arista EOS",
  unknown: "Unknown vendor",
};

const STATUS_STYLES: Record<string, string> = {
  done: "text-pass",
  processing: "text-review",
  error: "text-fail",
};

type LoadState = "loading" | "ready" | "error";

export default function ReportsPage() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [scans, setScans] = useState<ScanListEntry[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [page, setPage] = useState(1);

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

  if (loadState === "loading") {
    return <div className="font-mono text-sm text-ink-soft">Loading reports…</div>;
  }

  if (loadState === "error") {
    return (
      <div className="max-w-md">
        <p className="font-mono text-xs uppercase tracking-wide text-fail mb-2">Could not load reports</p>
        <p className="text-ink/90">{errorMessage}</p>
      </div>
    );
  }

  const { pageItems, pageCount, clampedPage } = usePagination(scans, PAGE_SIZE, page);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-display text-[28px] font-semibold tracking-tight">Reports</h1>
        <p className="text-ink-soft mt-2">
          {scans.length} scan{scans.length === 1 ? "" : "s"} -- download the PDF for any completed one.
        </p>
      </div>

      {scans.length === 0 ? (
        <p className="text-ink-soft text-sm">No scans yet. Run one from the New Scan page.</p>
      ) : (
        <div className="rounded-panel border border-line bg-panel overflow-hidden">
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
                  Report
                </th>
              </tr>
            </thead>
            <tbody>
              {pageItems.map((scan) => (
                <ReportRow key={scan.scan_id} scan={scan} />
              ))}
            </tbody>
          </table>
          <div className="px-[22px] py-4 border-t border-line-soft">
            <Pagination
              page={clampedPage}
              pageCount={pageCount}
              onChange={setPage}
              label={`page ${clampedPage} of ${pageCount}`}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function ReportRow({ scan }: { scan: ScanListEntry }) {
  const router = useRouter();
  const done = scan.status === "done";

  return (
    <tr className="transition-colors hover:bg-paper-dim">
      <td
        className="px-[22px] py-[15px] border-b border-line-soft min-w-0 cursor-pointer"
        onClick={() => router.push(`/scan/${scan.scan_id}`)}
      >
        <p className="truncate max-w-xs">{scan.filename}</p>
        <p className="font-mono text-[11px] text-ink-soft mt-0.5">{new Date(scan.uploaded_at).toLocaleString()}</p>
      </td>
      <td className="px-[22px] py-[15px] border-b border-line-soft font-mono text-xs text-ink-soft">
        {VENDOR_LABELS[scan.vendor] ?? scan.vendor}
      </td>
      <td className="px-[22px] py-[15px] border-b border-line-soft">
        {done ? (
          <MiniTally summary={scan.summary} />
        ) : (
          <span className={`text-xs font-mono uppercase ${STATUS_STYLES[scan.status] ?? "text-ink-soft"}`}>
            {scan.status}
          </span>
        )}
      </td>
      <td className="px-[22px] py-[15px] border-b border-line-soft">
        {done ? (
          <a
            href={getReportPdfUrl(scan.scan_id)}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-ink hover:underline underline-offset-4"
          >
            <FileBarChart2 className="w-3.5 h-3.5" strokeWidth={2} />
            Download PDF
          </a>
        ) : (
          <span className="text-xs text-ink-soft">not ready</span>
        )}
      </td>
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