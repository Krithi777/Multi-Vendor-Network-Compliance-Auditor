"use client";

// Flaws doc item #2/#3: a completed scan used to drop the user straight
// into /findings/{id} with no way back to a scan-level view — every
// other capability (evidence, remediation, training, report) lived on
// unrelated routes. This is the single entry point: one header (device
// identity + status) plus a left-hand tab rail, so every scan capability
// reads as one connected workspace instead of disconnected pages.
//
// Findings and Training keep their existing standalone routes for this
// pass (linked from the tab rail below) rather than being moved wholesale
// into this shell in the same change — see the module comment in
// scan-context.tsx.

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  ListChecks,
  FileSearch,
  Wrench,
  GraduationCap,
  FileBarChart2,
} from "lucide-react";
import { ScanWorkspaceProvider, useScanWorkspace } from "./scan-context";

const VENDOR_LABELS: Record<string, string> = {
  cisco_ios: "Cisco IOS",
  juniper_junos: "Juniper Junos",
  fortios: "FortiOS",
  panos: "PAN-OS",
  arista_eos: "Arista EOS",
  unknown: "Unknown vendor",
};

const STATUS_STYLES: Record<string, string> = {
  processing: "bg-review-bg text-review",
  done: "bg-pass-bg text-pass",
  error: "bg-fail-bg text-fail",
};

function TABS(scanId: string) {
  return [
    { href: `/scan/${scanId}`, label: "Overview", icon: LayoutDashboard, exact: true },
    { href: `/findings/${scanId}`, label: "Findings", icon: ListChecks, exact: true },
    { href: `/scan/${scanId}/evidence`, label: "Evidence", icon: FileSearch, exact: true },
    { href: `/scan/${scanId}/remediation`, label: "Remediation", icon: Wrench, exact: false },
    { href: `/training/${scanId}`, label: "Training", icon: GraduationCap, exact: true },
    { href: `/scan/${scanId}/report`, label: "Report", icon: FileBarChart2, exact: true },
  ];
}

function WorkspaceChrome({ children }: { children: React.ReactNode }) {
  const { scanId, scan, loadState } = useScanWorkspace();
  const pathname = usePathname();
  const tabs = TABS(scanId);

  const hostname = scan?.device?.hostname || scan?.filename || scanId.slice(0, 8);
  const vendorLabel = scan ? VENDOR_LABELS[scan.vendor] ?? scan.vendor : "—";
  const status = scan?.status ?? (loadState === "error" ? "error" : "processing");

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-panel border border-line bg-panel px-6 py-5 flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h1 className="font-display text-xl font-semibold tracking-tight truncate">{hostname}</h1>
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-mono uppercase tracking-wide ${STATUS_STYLES[status] ?? "bg-paper-dim text-ink-soft"}`}>
              {status}
            </span>
          </div>
          <p className="text-ink-soft text-[13px] font-mono mt-1.5">
            {vendorLabel} · scan {scanId.slice(0, 8)}
            {scan?.uploaded_at && ` · ${new Date(scan.uploaded_at).toLocaleString()}`}
          </p>
        </div>
        {/* Previously the only way back to the other files from a bulk
            upload was the browser's Back button -- clicking into one
            scan from /batch/[batchId] left no in-app link back to the
            batch, so the rest of the files were effectively unreachable
            once you'd navigated into one. scan.batch_id is already
            fetched by scan-context.tsx; this just surfaces it. */}
        {scan?.batch_id && (
          <Link
            href={`/batch/${scan.batch_id}`}
            className="shrink-0 text-xs font-medium text-ink-soft hover:text-ink underline underline-offset-4"
          >
            ← Back to batch (other files)
          </Link>
        )}
      </div>

      {/* Left-hand tab rail: an icon-only rail on tablet/desktop (pinned to
          the top-left corner of the workspace, sticky while the content
          column scrolls) so it stays narrow -- each icon reveals its label
          in a small tooltip on hover/focus/tap, rather than spelling every
          name out inline. Collapses to a horizontal icon scroller only on
          narrow phone widths where a sidebar can't fit. */}
      <div className="flex flex-col lg:flex-row items-start gap-6">
        <nav
          className="flex lg:flex-col gap-1.5 w-full lg:w-auto shrink-0 overflow-x-auto lg:overflow-visible
            border-b lg:border-b-0 lg:border-r border-line pb-2 lg:pb-0 lg:pr-3 lg:sticky lg:top-20"
        >
          {tabs.map((tab) => {
            const active = tab.exact ? pathname === tab.href : pathname.startsWith(tab.href);
            const Icon = tab.icon;
            return (
              <Link
                key={tab.href}
                href={tab.href}
                aria-label={tab.label}
                className={`group relative flex items-center justify-center shrink-0 w-11 h-11 rounded-xl transition-colors ${
                  active ? "bg-ink text-paper" : "text-ink-soft hover:bg-paper-dim hover:text-ink"
                }`}
              >
                <Icon className="w-4.5 h-4.5 shrink-0" strokeWidth={2} />
                <span
                  role="tooltip"
                  className="pointer-events-none absolute z-20 whitespace-nowrap rounded-lg bg-ink px-2.5 py-1.5
                    text-xs font-medium text-paper opacity-0 shadow-lg transition-opacity duration-100
                    group-hover:opacity-100 group-focus-visible:opacity-100 group-active:opacity-100
                    top-full mt-2 left-1/2 -translate-x-1/2
                    lg:top-1/2 lg:left-full lg:mt-0 lg:ml-2 lg:-translate-x-0 lg:-translate-y-1/2"
                >
                  {tab.label}
                </span>
              </Link>
            );
          })}
        </nav>

        <div className="flex-1 min-w-0 w-full">{children}</div>
      </div>
    </div>
  );
}

export default function ScanWorkspaceLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { scanId: string };
}) {
  return (
    <ScanWorkspaceProvider scanId={params.scanId}>
      <WorkspaceChrome>{children}</WorkspaceChrome>
    </ScanWorkspaceProvider>
  );
}