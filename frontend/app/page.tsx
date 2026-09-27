"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ingestFile,
  ingestBulk,
  detectVendor,
  pollScanUntilDone,
  ApiError,
  type Vendor,
  type VendorDetection,
} from "@/lib/api";

// "confirm" is the new pre-scan step: a file has been read and detected,
// but no scan exists yet -- the person picks/confirms a vendor before
// anything is sent to /api/ingest.
type Stage = "idle" | "detecting" | "confirm" | "uploading" | "processing" | "error";

const VENDOR_LABELS: Record<string, string> = {
  cisco_ios: "Cisco IOS",
  juniper_junos: "Juniper Junos",
  fortios: "FortiOS",
  panos: "PAN-OS",
  arista_eos: "Arista EOS",
};

const ALL_VENDORS = Object.keys(VENDOR_LABELS) as Vendor[];

const FRAMEWORK_LABELS: Record<string, string> = {
  cis: "CIS Benchmark",
  stig: "DISA STIG",
  iso_27001: "ISO/IEC 27001",
  nist_800_53: "NIST SP 800-53",
};
const ALL_FRAMEWORKS = Object.keys(FRAMEWORK_LABELS);

// What the "Detected Vendor" box shows, per detect_vendor() confidence
// (phase9/vendor_detect.py) -- kept in one place so the badge text/color
// and the fallback prose below it always agree.
const CONFIDENCE_META: Record<
  VendorDetection["confidence"],
  { label: string; text: string; bg: string; icon: "check" | "warn" | "x" }
> = {
  high: { label: "High confidence", text: "text-pass", bg: "bg-pass-bg", icon: "check" },
  low: { label: "Low confidence", text: "text-review", bg: "bg-review-bg", icon: "warn" },
  ambiguous: { label: "Ambiguous", text: "text-review", bg: "bg-review-bg", icon: "warn" },
  undetected: { label: "Undetected", text: "text-fail", bg: "bg-fail-bg", icon: "x" },
};

function ConfidenceIcon({ icon }: { icon: "check" | "warn" | "x" }) {
  if (icon === "check") {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4">
        <path d="M20 6 9 17l-5-5" />
      </svg>
    );
  }
  if (icon === "warn") {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4">
        <path d="M12 9v4M12 17h.01" />
        <path d="M10.29 3.86 1.82 18a1.5 1.5 0 0 0 1.29 2.25h17.78A1.5 1.5 0 0 0 22.18 18L13.71 3.86a1.5 1.5 0 0 0-2.58 0Z" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

export default function IngestPage() {
  const router = useRouter();
  const [stage, setStage] = useState<Stage>("idle");
  const [fileName, setFileName] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [detection, setDetection] = useState<VendorDetection | null>(null);
  // "auto" defers to the backend's own detect_vendor() call at ingest
  // time; anything else is an explicit override sent as ?vendor=.
  const [selectedVendor, setSelectedVendor] = useState<Vendor | "auto" | null>(null);
  const [detectedVendor, setDetectedVendor] = useState<Vendor | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<string[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  // All 4 frameworks selected by default -- the scan audits against
  // every framework unless the person narrows it down before hitting
  // Start Scan.
  const [selectedFrameworks, setSelectedFrameworks] = useState<string[]>(ALL_FRAMEWORKS);
  const inputRef = useRef<HTMLInputElement>(null);

  const runUpload = useCallback(
    async (file: File, vendor?: string) => {
      setStage("uploading");
      setFileName(file.name);
      setPendingFile(file);
      setErrorMessage(null);
      setCandidates([]);
      setDetectedVendor(null);
      try {
        const { scan_id } = await ingestFile(file, vendor, selectedFrameworks);
        setStage("processing");
        const scan = await pollScanUntilDone(scan_id);
        if (scan.status === "error") {
          setStage("error");
          // Real per-scan reason, not a hardcoded string -- this is what
          // was actually wrong (undetected vendor, ambiguous candidates,
          // or any other pipeline exception), straight from the backend.
          setErrorMessage(scan.error_message ?? "Scan failed for an unknown reason.");
          setCandidates(scan.vendor_candidates ?? []);
          return;
        }
        setDetectedVendor(scan.vendor);
        // Land in the scan workspace (Overview tab) rather than jumping
        // straight to Findings, so the person sees the whole workspace
        // (Evidence/Remediation/Training/Report tabs) exists from the start.
        router.push(`/scan/${scan_id}`);
      } catch (err) {
        setStage("error");
        setErrorMessage(err instanceof ApiError ? err.message : "Upload failed. Is the backend running?");
        setCandidates([]);
      }
    },
    [router, selectedFrameworks]
  );

  // Milestone 11: two or more files in one drop/pick go through
  // /api/ingest/bulk instead -- there's no per-file vendor-confirm step
  // for a batch, so this skips straight past "confirm" the same way it
  // always has.
  const runBulkUpload = useCallback(
    async (files: File[]) => {
      setStage("uploading");
      setFileName(`${files.length} files`);
      setPendingFile(null);
      setErrorMessage(null);
      setCandidates([]);
      setDetectedVendor(null);
      try {
        const { batch_id } = await ingestBulk(files, undefined, selectedFrameworks);
        router.push(`/batch/${batch_id}`);
      } catch (err) {
        setStage("error");
        setErrorMessage(err instanceof ApiError ? err.message : "Bulk upload failed. Is the backend running?");
      }
    },
    [router, selectedFrameworks]
  );

  // A single file now goes to a detect-only preview first (POST
  // /api/detect-vendor -- read-only, no scan_id created) so the person
  // sees the vendor guess and can confirm or override it *before*
  // anything is ingested, instead of only finding out from a failed scan.
  const runDetect = useCallback(async (file: File) => {
    setStage("detecting");
    setFileName(file.name);
    setPendingFile(file);
    setErrorMessage(null);
    setCandidates([]);
    setDetectedVendor(null);
    try {
      const result = await detectVendor(file);
      setDetection(result);
      if (result.confidence === "high" || result.confidence === "low") {
        setSelectedVendor("auto");
      } else if (result.confidence === "ambiguous" && result.candidates.length > 0) {
        setSelectedVendor(result.candidates[0] as Vendor);
      } else {
        setSelectedVendor(null); // undetected -- force an explicit pick
      }
      setStage("confirm");
    } catch (err) {
      // Detection is best-effort -- if the preview call itself fails
      // (backend down, bad encoding), fall straight through to the
      // normal ingest flow so a single dependency doesn't block scanning.
      setDetection(null);
      setSelectedVendor(null);
      setStage("confirm");
    }
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragging(false);
      if (selectedFrameworks.length === 0) return;
      const files = Array.from(e.dataTransfer.files ?? []);
      if (files.length === 1) runDetect(files[0]);
      else if (files.length > 1) runBulkUpload(files);
    },
    [runDetect, runBulkUpload, selectedFrameworks]
  );

  const onPick = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (selectedFrameworks.length === 0) return;
      const files = Array.from(e.target.files ?? []);
      if (files.length === 1) runDetect(files[0]);
      else if (files.length > 1) runBulkUpload(files);
    },
    [runDetect, runBulkUpload, selectedFrameworks]
  );

  const reset = useCallback(() => {
    setStage("idle");
    setPendingFile(null);
    setDetection(null);
    setSelectedVendor(null);
    setErrorMessage(null);
    setCandidates([]);
  }, []);

  const busy = stage === "detecting" || stage === "uploading" || stage === "processing";
  const meta = detection ? CONFIDENCE_META[detection.confidence] : null;

  return (
    <div className="flex flex-col gap-8">
      <div>
        <div className="flex items-center gap-2 text-xs text-ink-soft mb-4">
          <span className="w-[6px] h-[6px] rounded-full bg-ink" />
          Multivendor network security compliance
        </div>
        <h1 className="font-display text-[28px] sm:text-[32px] font-semibold tracking-tight leading-tight">
          Check a device config
        </h1>
        <p className="text-ink-soft mt-3 max-w-xl leading-relaxed">
          Drop a config file from any of the five supported vendors. It&apos;s evaluated against all 20
          controls, with the raw config line kept as evidence for every result.
        </p>
      </div>

      {(stage === "idle" || stage === "confirm") && (
        <div className="rounded-panel border border-line bg-panel p-5">
          <div className="flex items-center justify-between gap-4 mb-3">
            <p className="text-[11px] font-mono uppercase tracking-wide text-ink-soft">
              Audit against these frameworks
            </p>
            <button
              type="button"
              onClick={() =>
                setSelectedFrameworks((prev) =>
                  prev.length === ALL_FRAMEWORKS.length ? [] : [...ALL_FRAMEWORKS]
                )
              }
              className="text-xs text-ink-soft hover:text-ink underline underline-offset-4 shrink-0"
            >
              {selectedFrameworks.length === ALL_FRAMEWORKS.length ? "Clear all" : "Select all"}
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {ALL_FRAMEWORKS.map((fw) => {
              const checked = selectedFrameworks.includes(fw);
              return (
                <button
                  key={fw}
                  type="button"
                  onClick={() =>
                    setSelectedFrameworks((prev) =>
                      prev.includes(fw) ? prev.filter((f) => f !== fw) : [...prev, fw]
                    )
                  }
                  className={`flex items-center gap-2 rounded-full border px-3.5 py-2 text-xs font-mono transition-colors
                    ${checked ? "border-ink bg-paper-dim text-ink" : "border-line bg-panel text-ink-soft hover:border-ink-soft"}`}
                >
                  <span
                    className={`w-3.5 h-3.5 rounded-[4px] border flex items-center justify-center shrink-0
                      ${checked ? "border-ink bg-ink" : "border-line"}`}
                  >
                    {checked && (
                      <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" className="w-2 h-2">
                        <path d="M20 6 9 17l-5-5" />
                      </svg>
                    )}
                  </span>
                  {FRAMEWORK_LABELS[fw]}
                </button>
              );
            })}
          </div>
          {selectedFrameworks.length === 0 && (
            <p className="text-xs text-fail mt-2.5">Pick at least one framework, or scanning is blocked.</p>
          )}
        </div>
      )}

      <div className="rounded-panel border border-line bg-panel overflow-hidden">
        {stage !== "confirm" && (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={onDrop}
            onClick={() => !busy && selectedFrameworks.length > 0 && inputRef.current?.click()}
            className={`m-[22px] rounded-2xl border-[1.5px] border-dashed px-8 py-14 text-center transition-colors cursor-pointer
              ${isDragging ? "border-pass bg-pass-bg" : "border-line bg-paper-dim"}
              ${busy || selectedFrameworks.length === 0 ? "cursor-wait opacity-80" : "hover:border-ink-soft"}`}
          >
            <input ref={inputRef} type="file" multiple className="hidden" onChange={onPick} disabled={busy} />

            {stage === "idle" && (
              <>
                <svg viewBox="0 0 24 24" fill="none" stroke="#6E6B5C" strokeWidth="1.4" className="w-8 h-8 mx-auto mb-4">
                  <path d="M12 3v12" />
                  <path d="m7 8 5-5 5 5" />
                  <path d="M4 18v1a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1" />
                </svg>
                <p className="text-[15px] font-medium">Drag one or more configuration files here, or browse</p>
                <p className="text-ink-soft text-sm mt-2 font-mono">
                  cisco_ios · juniper_junos · fortios · panos · arista_eos
                </p>
              </>
            )}

            {stage === "detecting" && (
              <PipelineStatus fileName={fileName} steps={[{ label: "Reading file, detecting vendor", done: false }]} />
            )}

            {stage === "uploading" && (
              <PipelineStatus fileName={fileName} steps={[{ label: "Uploading", done: false }]} />
            )}

            {stage === "processing" && (
              <PipelineStatus
                fileName={fileName}
                steps={[
                  { label: "Uploaded", done: true },
                  { label: "Sanitizing, evaluating 20 controls", done: false },
                ]}
              />
            )}

            {stage === "error" && (
              <div className="text-left max-w-md mx-auto" onClick={(e) => e.stopPropagation()}>
                <p className="font-mono text-xs uppercase tracking-wide text-fail mb-2">Scan failed</p>
                <p className="text-ink/90">{errorMessage}</p>

                {pendingFile && (
                  <div className="mt-5">
                    <p className="text-xs text-ink-soft mb-2">
                      {candidates.length > 0
                        ? "The detector narrowed it to these, but couldn't pick one confidently — confirm one, or choose another vendor:"
                        : "Pick the vendor manually to continue with this file:"}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {ALL_VENDORS.map((v) => (
                        <button
                          key={v}
                          onClick={() => runUpload(pendingFile, v)}
                          className={`rounded-full border px-3.5 py-2 text-xs font-mono transition-colors
                            ${
                              candidates.includes(v)
                                ? "border-review bg-review-bg text-review"
                                : "border-line bg-panel text-ink-soft hover:border-ink-soft"
                            }`}
                        >
                          {VENDOR_LABELS[v]}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <button
                  onClick={reset}
                  className="mt-5 text-sm text-ink-soft hover:text-ink underline underline-offset-4"
                >
                  Try a different file instead
                </button>
              </div>
            )}
          </div>
        )}

        {stage === "confirm" && pendingFile && (
          <div className="p-6 flex flex-col gap-6">
            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <p className="text-[11px] font-mono uppercase tracking-wide text-ink-soft">Upload configuration</p>
                <p className="text-ink font-medium truncate mt-0.5">{fileName}</p>
              </div>
              <button
                onClick={reset}
                className="shrink-0 text-xs text-ink-soft hover:text-ink underline underline-offset-4"
              >
                Choose a different file
              </button>
            </div>

            <div>
              <p className="text-[11px] font-mono uppercase tracking-wide text-ink-soft mb-2">Detected vendor</p>
              {meta && detection ? (
                <div className={`rounded-xl border border-line-soft ${meta.bg} px-4 py-3`}>
                  <div className={`flex items-center gap-2 font-mono text-xs uppercase tracking-wide ${meta.text}`}>
                    <ConfidenceIcon icon={meta.icon} />
                    {meta.label}
                  </div>
                  <p className="text-ink mt-1.5 text-[15px]">
                    {detection.confidence === "undetected"
                      ? "No vendor signature matched confidently — pick one below."
                      : detection.candidates.length > 1
                      ? detection.candidates.map((v) => VENDOR_LABELS[v] ?? v).join(" / ")
                      : VENDOR_LABELS[detection.vendor ?? ""] ?? detection.vendor}
                  </p>
                </div>
              ) : (
                <div className="rounded-xl border border-line-soft bg-missing-bg px-4 py-3">
                  <p className="text-missing text-sm">
                    Couldn&apos;t reach the detector — pick the vendor manually below.
                  </p>
                </div>
              )}
            </div>

            <div>
              <p className="text-[11px] font-mono uppercase tracking-wide text-ink-soft mb-2">Select vendor</p>
              <div className="flex flex-col gap-1.5">
                <VendorOption
                  label="Auto Detect"
                  sublabel={detection && detection.confidence !== "undetected" ? undefined : "Not reliable for this file"}
                  selected={selectedVendor === "auto"}
                  disabled={!detection || detection.confidence === "undetected" || detection.confidence === "ambiguous"}
                  onSelect={() => setSelectedVendor("auto")}
                />
                {ALL_VENDORS.map((v) => (
                  <VendorOption
                    key={v}
                    label={VENDOR_LABELS[v]}
                    sublabel={detection?.candidates.includes(v) ? "Detector candidate" : undefined}
                    selected={selectedVendor === v}
                    onSelect={() => setSelectedVendor(v)}
                  />
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between gap-4 pt-1">
              {!selectedVendor && (
                <p className="text-xs text-fail">Pick a vendor to continue.</p>
              )}
              <span className="flex-1" />
              <button
                disabled={!selectedVendor || selectedFrameworks.length === 0}
                onClick={() => runUpload(pendingFile, selectedVendor === "auto" ? undefined : selectedVendor ?? undefined)}
                className="rounded-full bg-ink text-paper px-5 py-2.5 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:opacity-90 transition-opacity"
              >
                Start Scan
              </button>
            </div>
          </div>
        )}
      </div>

      {detectedVendor && (
        <p className="text-sm text-ink-soft">
          Detected as <span className="text-ink font-medium">{VENDOR_LABELS[detectedVendor] ?? detectedVendor}</span>.
          Redirecting to findings…
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {Object.values(VENDOR_LABELS).map((label) => (
          <span
            key={label}
            className="rounded-full border border-line bg-panel px-3.5 py-2 text-xs font-mono text-ink-soft"
          >
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

function VendorOption({
  label,
  sublabel,
  selected,
  disabled,
  onSelect,
}: {
  label: string;
  sublabel?: string;
  selected: boolean;
  disabled?: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onSelect}
      className={`flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition-colors
        ${selected ? "border-ink bg-paper-dim" : "border-line bg-panel hover:border-ink-soft"}
        ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
    >
      <span className="flex items-center gap-3">
        <span
          className={`w-4 h-4 rounded-full border flex items-center justify-center shrink-0
            ${selected ? "border-ink" : "border-line"}`}
        >
          {selected && <span className="w-2 h-2 rounded-full bg-ink" />}
        </span>
        <span className="text-[14px] text-ink font-medium">{label}</span>
      </span>
      {sublabel && <span className="text-xs font-mono text-ink-soft shrink-0">{sublabel}</span>}
    </button>
  );
}

function PipelineStatus({
  fileName,
  steps,
}: {
  fileName: string | null;
  steps: { label: string; done: boolean }[];
}) {
  return (
    <div className="text-left max-w-md mx-auto font-mono text-sm">
      <p className="text-ink/90 mb-3 truncate">{fileName}</p>
      <ul className="flex flex-col gap-1.5">
        {steps.map((step) => (
          <li key={step.label} className="flex items-center gap-2 text-ink-soft">
            <span className={step.done ? "text-pass" : "animate-pulse"}>{step.done ? "done" : "···"}</span>
            <span className={step.done ? "text-ink/80" : ""}>{step.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}