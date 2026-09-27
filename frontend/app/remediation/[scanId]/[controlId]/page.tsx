"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Info } from "lucide-react";
import { getRemediation, getScan, ApiError, type RemediationResponse, type Scan } from "@/lib/api";

type LoadState = "loading" | "ready" | "error";

export default function RemediationPage({
  params,
}: {
  params: { scanId: string; controlId: string };
}) {
  const { scanId, controlId } = params;
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [remediation, setRemediation] = useState<RemediationResponse | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getRemediation(scanId, controlId), getScan(scanId)])
      .then(([remediationData, scanData]) => {
        if (cancelled) return;
        setRemediation(remediationData);
        setScan(scanData);
        setLoadState("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setErrorMessage(
          err instanceof ApiError ? err.message : "Could not load remediation. Is the backend running?"
        );
        setLoadState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [scanId, controlId]);

  if (loadState === "loading") {
    return <div className="font-mono text-sm text-ink-soft">Loading remediation…</div>;
  }

  if (loadState === "error" || !remediation) {
    return (
      <div className="max-w-md">
        <p className="font-mono text-xs uppercase tracking-wide text-fail mb-2">Could not load remediation</p>
        <p className="text-ink/90">{errorMessage}</p>
        <Link
          href={`/findings/${scanId}`}
          className="mt-4 inline-block text-sm text-ink-soft hover:text-ink underline underline-offset-4"
        >
          Back to findings
        </Link>
      </div>
    );
  }

  const copyAll = () => {
    const text = [
      `# ${remediation.control_id} -- ${remediation.canonical_field} (${remediation.vendor})`,
      "",
      "# Remediation",
      ...remediation.commands,
      "",
      ...(remediation.verification_command ? ["# Verify", remediation.verification_command] : []),
      ...(remediation.rollback_commands.length
        ? ["", "# Rollback", ...remediation.rollback_commands]
        : []),
    ].join("\n");
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  };

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="font-mono text-xs text-ink-soft mb-1">
          scan {scanId.slice(0, 8)}
          {scan?.filename ? ` · ${scan.filename}` : ""} · {remediation.vendor}
        </p>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="font-display text-[28px] font-semibold tracking-tight">Remediation plan</h1>
            <p className="text-ink-soft mt-2 max-w-xl">
              {remediation.control_id} — {remediation.canonical_field}
            </p>
          </div>
          <Link
            href={`/findings/${scanId}`}
            className="text-sm text-ink-soft hover:text-ink underline underline-offset-4 shrink-0"
          >
            ← Back to findings
          </Link>
        </div>
      </div>

      {/* Honest conflict-check status -- this capability doesn't exist yet, so
          it's stated plainly as a scope note rather than styled as an error. */}
      <div className="rounded-2xl border border-line bg-paper-dim px-5 py-4 flex items-start gap-3">
        <Info className="w-4 h-4 text-ink-soft shrink-0 mt-0.5" strokeWidth={2} />
        <p className="text-sm text-ink-soft leading-relaxed">
          <span className="font-medium text-ink">Conflict check not yet available.</span>{" "}
          Pre-remediation dependency and conflict checking isn&apos;t built yet, so this plan hasn&apos;t
          been simulated against other configuration on the device. This is a preview for review and
          copying only — nothing here runs automatically.
        </p>
      </div>

      <div className="rounded-panel border border-line bg-panel overflow-hidden">
        <div className="px-[22px] py-[18px] border-b border-line-soft flex items-center justify-between">
          <h2 className="text-sm font-semibold">Commands</h2>
          <button
            onClick={copyAll}
            className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink-soft hover:text-ink hover:border-ink-soft transition-colors"
          >
            {copied ? "Copied" : "Copy all"}
          </button>
        </div>

        <div className="p-[22px] flex flex-col gap-5">
          <CommandBlock label="Remediation" commands={remediation.commands} />
          {remediation.verification_command && (
            <CommandBlock label="Verify" commands={[remediation.verification_command]} />
          )}
          {remediation.rollback_commands.length > 0 && (
            <CommandBlock label="Rollback" commands={remediation.rollback_commands} />
          )}
        </div>
      </div>
    </div>
  );
}

function CommandBlock({ label, commands }: { label: string; commands: string[] }) {
  return (
    <div>
      <p className="text-[11px] font-mono uppercase tracking-wide text-ink-soft mb-2">{label}</p>
      <div className="rounded-lg bg-paper-dim border border-line-soft px-3.5 py-3 font-mono text-xs text-ink/85 overflow-x-auto">
        {commands.map((cmd, i) => (
          <div key={i} className="whitespace-pre">
            {cmd}
          </div>
        ))}
      </div>
    </div>
  );
}
