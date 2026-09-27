"use client";

// One fetch of the scan + its findings, shared across every tab in the
// /scan/[scanId] workspace (Overview, Evidence, Remediation) via context,
// so switching tabs doesn't re-poll or re-fetch from scratch. Findings
// and Training keep their own existing standalone routes/fetches for
// now (see frontend/app/findings/[scanId], frontend/app/training/[scanId])
// — this context is not wired into those yet.

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getFindings, getScan, pollScanUntilDone, ApiError, type Scan, type FindingsResponse } from "@/lib/api";

type LoadState = "loading" | "waiting" | "ready" | "error";

interface ScanWorkspaceValue {
  scanId: string;
  loadState: LoadState;
  scan: Scan | null;
  findings: FindingsResponse | null;
  errorMessage: string | null;
}

const ScanWorkspaceContext = createContext<ScanWorkspaceValue | null>(null);

export function ScanWorkspaceProvider({ scanId, children }: { scanId: string; children: ReactNode }) {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [scan, setScan] = useState<Scan | null>(null);
  const [findings, setFindings] = useState<FindingsResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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
          setErrorMessage(finalScan.error_message ?? "This scan failed before findings could be produced.");
          return;
        }

        const data = await getFindings(scanId);
        if (cancelled) return;
        setFindings(data);
        setLoadState("ready");
      } catch (err) {
        if (cancelled) return;
        setErrorMessage(err instanceof ApiError ? err.message : "Could not load this scan. Is the backend running?");
        setLoadState("error");
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [scanId]);

  return (
    <ScanWorkspaceContext.Provider value={{ scanId, loadState, scan, findings, errorMessage }}>
      {children}
    </ScanWorkspaceContext.Provider>
  );
}

export function useScanWorkspace(): ScanWorkspaceValue {
  const ctx = useContext(ScanWorkspaceContext);
  if (!ctx) {
    throw new Error("useScanWorkspace must be used within a ScanWorkspaceProvider (/scan/[scanId]/layout.tsx)");
  }
  return ctx;
}
