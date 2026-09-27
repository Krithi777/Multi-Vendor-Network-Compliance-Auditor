"use client";

// Milestone 11, Section 6B. Landed on right after POST /api/ingest/bulk
// returns -- polls GET /api/scans?batch_id=... every couple seconds
// until every file in the batch is out of "processing", same polling
// pattern pollScanUntilDone uses for a single scan.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { listScans, ApiError, type ScanListEntry } from "@/lib/api";

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

export default function BatchPage({ params }: { params: { batchId: string } }) {
  const { batchId } = params;
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [scans, setScans] = useState<ScanListEntry[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const data = await listScans(undefined, batchId);
        if (cancelled) return;
        setScans(data.scans);
        setLoadState("ready");
        const stillProcessing = data.scans.some((s) => s.status === "processing");
        if (stillProcessing) {
          pollRef.current = setTimeout(poll, 1800);
        }
      } catch (err) {
        if (cancelled) return;
        setErrorMessage(err instanceof ApiError ? err.message : "Could not load this batch. Is the backend running?");
        setLoadState("error");
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [batchId]);

  if (loadState === "error") {
    return (
      <div className="max-w-md">
        <p className="font-mono text-xs uppercase tracking-wide text-fail mb-2">Could not load batch</p>
        <p className="text-ink/90">{errorMessage}</p>
        <Link href="/" className="mt-4 inline-block text-sm text-ink-soft hover:text-ink underline underline-offset-4">
          Back to ingest
        </Link>
      </div>
    );
  }

  const doneCount = scans.filter((s) => s.status === "done").length;
  const errorCount = scans.filter((s) => s.status === "error").length;
  const processingCount = scans.filter((s) => s.status === "processing").length;

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="font-mono text-xs text-ink-soft mb-1">batch {batchId.slice(0, 8)}</p>
        <h1 className="font-display text-[28px] font-semibold tracking-tight">Bulk upload</h1>
        <p className="text-ink-soft mt-3 text-sm">
          {loadState === "loading" && "Loading batch…"}
          {loadState === "ready" &&
            `${doneCount} done · ${errorCount} error${errorCount === 1 ? "" : "s"}${
              processingCount > 0 ? ` · ${processingCount} still processing…` : ""
            }`}
        </p>
      </div>

      <div className="rounded-panel border border-line bg-panel overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-soft">
              <th className="px-5 py-3 font-medium">File</th>
              <th className="px-5 py-3 font-medium">Vendor</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 font-medium">Findings</th>
            </tr>
          </thead>
          <tbody>
            {scans.map((scan) => (
              <tr key={scan.scan_id} className="border-b border-line last:border-0">
                <td className="px-5 py-3.5 font-mono text-xs truncate max-w-[220px]">{scan.filename}</td>
                <td className="px-5 py-3.5 text-ink-soft">{VENDOR_LABELS[scan.vendor] ?? scan.vendor}</td>
                <td className={`px-5 py-3.5 font-mono text-xs ${STATUS_STYLES[scan.status] ?? ""}`}>
                  {scan.status}
                </td>
                <td className="px-5 py-3.5">
                  {scan.status === "done" ? (
                    <Link
                      href={`/scan/${scan.scan_id}`}
                      className="text-ink-soft hover:text-ink underline underline-offset-4"
                    >
                      {scan.summary.PASS} pass · {scan.summary.FAIL} fail · {scan.summary.MISSING} missing →
                    </Link>
                  ) : (
                    <span className="text-ink-soft">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Link href="/" className="text-sm text-ink-soft hover:text-ink underline underline-offset-4 w-fit">
        Upload more
      </Link>
    </div>
  );
}
