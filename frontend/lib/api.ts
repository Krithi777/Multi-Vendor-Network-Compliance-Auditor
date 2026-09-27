// lib/api.ts
// Thin, typed wrapper over the Phase 9 FastAPI contract (see
// Phase_9_Implementation_Plan_2_Person_Split.md, Section 4). Types here
// are the contract -- if the backend response shape changes, this is
// the one file to update; every page imports from here rather than
// calling fetch() directly.

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export type ScanStatus = "processing" | "done" | "error";
export type Vendor = "cisco_ios" | "juniper_junos" | "fortios" | "panos" | "arista_eos" | "unknown";
export type EvidenceState = "PASS" | "FAIL" | "MISSING" | "REVIEW" | "NOT_APPLICABLE";

// Milestone 11, Section 6A. Every field is optional/nullable -- a
// running-config upload usually only yields a hostname; model/serial/
// os_version are legitimately null when the config doesn't carry them,
// not a sign something's broken.
export interface DeviceInfo {
  hostname: string | null;
  vendor: string | null;
  model: string | null;
  serial_number: string | null;
  os_version: string | null;
}

export interface Scan {
  scan_id: string;
  status: ScanStatus;
  vendor: Vendor;
  // Added alongside the manual vendor-override flow: "confirmed" once a
  // human (or a retry with ?vendor=) picks the vendor, otherwise the
  // detector's own "high" | "low" | "ambiguous" | "undetected". null only
  // before detection has run at all.
  vendor_confidence: string | null;
  // Non-empty only when confidence is "ambiguous" -- the detector's tied
  // top candidates, meant to be offered to the user first, not auto-picked.
  vendor_candidates: string[];
  // The real reason a scan has status "error" (vendor undetected/ambiguous,
  // or any other pipeline exception) -- null unless status is "error".
  error_message: string | null;
  filename: string;
  uploaded_at: string;
  batch_id: string | null;
  device?: DeviceInfo;
  // Which of the 4 frameworks this scan was actually run against (New
  // Scan page selector). Defaults to all four server-side if the scan
  // predates this field or no selection was made.
  frameworks_scanned?: FrameworkKey[];
}

export type FrameworkKey = "cis" | "stig" | "iso_27001" | "nist_800_53";

// Not in the original Section 4 contract -- added for the milestone 8
// dashboard (GET /api/scans), which needs a way to list/aggregate across
// scans that the original contract didn't provide.
export interface ScanListEntry extends Scan {
  summary: FindingsSummary;
}

export interface FrameworkRef {
  vendor?: string;
  rec_id?: string | null;
  stig_id?: string | null;
  benchmark?: string;
  note?: string;
}

export interface Finding {
  control_id: string;
  canonical_field: string;
  state: EvidenceState;
  description: string | null;
  severity: "low" | "medium" | "high";
  expected_value: unknown;
  observed_value: unknown;
  evidence_line: string | null;
  evidence_line_number: number | null;
  context_category: string | null;
  frameworks: {
    cis?: FrameworkRef[];
    stig?: FrameworkRef[];
    iso_27001?: string[];
    nist_800_53?: string[];
  };
  linked_controls: string[];
  notes: string | null;
}

export interface FindingsSummary {
  PASS: number;
  FAIL: number;
  MISSING: number;
  REVIEW: number;
  NOT_APPLICABLE: number;
}

export interface FindingsResponse {
  scan_id: string;
  vendor: Vendor;
  summary: FindingsSummary;
  results: Finding[];
}

export interface RemediationResponse {
  control_id: string;
  canonical_field: string;
  vendor: Vendor;
  commands: string[];
  verification_command: string | null;
  rollback_commands: string[];
  conflict_check: "not_available";
}

// Not in the original Section 4 contract -- backs the milestone 10
// Training Studio's canonical_field picker (GET /api/controls).
export interface ControlRef {
  control_id: string;
  canonical_field: string;
  description: string | null;
}

// Milestone 10 (Training Studio). Unmatched lines are grouped into
// clusters server-side (phase9.unmatched_clustering) so the UI shows
// "14 lines look like this one" instead of a flat unordered list -- this
// shape replaces the original Section 4 sketch's flat `unmatched_lines`
// array, which the backend never actually needed to keep flat.
export interface SampleLine {
  raw_line: string;
  line_number: number | null;
  context_path: string | null;
  resolved: boolean;
}

// Component scores are the real, individual phase7 fusion signals
// (0-1). `context` can be null -- some vendors' unmatched lines carry no
// context_path (see the Phase 9 plan's Juniper/PAN-OS note), and the
// signal is honestly omitted rather than faked as 0.
export interface ClusterSuggestion {
  canonical_field: string;
  control_id: string | null;
  matched_example: string;
  template: string | null;
  fused_confidence: number;
  confidence_bucket: "HIGH" | "MEDIUM" | "LOW";
  component_scores: {
    syntax: number;
    context: number | null;
    value_semantics: number;
    framework_fit: number;
    precedent: number;
  };
  generalized_count: number;
  remaining_count: number;
  evaluated_count: number;
}

export type ClusterState = "untaught" | "waiting_for_admin" | "teaching" | "generalizing" | "completed";

export interface UnmatchedCluster {
  cluster_id: string;
  context_category: string;
  representative_line: string;
  count: number;
  resolved_count: number;
  state: ClusterState;
  sample_lines: SampleLine[];
  suggestion: ClusterSuggestion | null;
}

export interface DecisionLogEntry {
  type: "accepted" | "edited" | "rejected";
  raw_line: string;
  cluster_id: string;
  canonical_field: string | null;
  at: number; // unix seconds
}

export interface UnmatchedResponse {
  scan_id: string;
  vendor: Vendor;
  coverage_before_pct: number | null;
  total_unresolved: number;
  clusters: UnmatchedCluster[];
  decision_log: DecisionLogEntry[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new ApiError(res.status, detail.detail || res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function ingestFile(
  file: File,
  vendor?: string,
  frameworks?: string[]
): Promise<{ scan_id: string; status: ScanStatus }> {
  const form = new FormData();
  form.append("file", file);
  const params = new URLSearchParams();
  if (vendor) params.set("vendor", vendor);
  if (frameworks && frameworks.length > 0) params.set("frameworks", frameworks.join(","));
  const qs = params.toString() ? `?${params.toString()}` : "";
  return request(`/api/ingest${qs}`, { method: "POST", body: form });
}

// New Scan page pre-check. POST /api/detect-vendor (phase9/api.py) runs
// the same regex detector as /api/ingest but is read-only -- no scan_id
// is created, so it's safe to call on every file drop/pick before the
// person has committed to a scan.
export interface VendorDetection {
  vendor: Vendor | null;
  confidence: "high" | "low" | "ambiguous" | "undetected";
  candidates: string[];
  scores: Record<string, number>;
}

export async function detectVendor(file: File): Promise<VendorDetection> {
  const form = new FormData();
  form.append("file", file);
  return request(`/api/detect-vendor`, { method: "POST", body: form });
}

// Was already imported by the Findings page but never actually defined
// here -- that import would fail to compile. GET /api/reports/{scan_id}/pdf
// (phase9/api.py) streams the PDF directly, so this is just the URL, not
// a fetch wrapper; callers that need to detect a failed render (e.g. the
// Reports page) should fetch() it themselves rather than link straight to it.
export function getReportPdfUrl(scanId: string): string {
  return `${API_BASE}/api/reports/${scanId}/pdf`;
}

// Second reporting engine (phase9/dynamic_report.py, ReportLab): the
// PDF "customized based on the device's specific model and software
// version". Unlike getReportPdfUrl this is POST (prepared_by/comments
// are reviewer-entered free text, not query-string safe) and returns
// the PDF bytes directly, since callers here always need blob + error
// handling rather than just a link.
export async function fetchDynamicReportPdf(
  scanId: string,
  options?: { preparedBy?: string; comments?: string }
): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/reports/${scanId}/dynamic-pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prepared_by: options?.preparedBy || null,
      comments: options?.comments || null,
    }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new ApiError(res.status, detail.detail || res.statusText);
  }
  return res.blob();
}

// Milestone 11, Section 6B. Same multipart shape as ingestFile, just
// several "file" parts in one form -- FastAPI's `files: list[UploadFile]`
// on the other end expects the field repeated, not a single array value.
export async function ingestBulk(
  files: File[],
  vendor?: string,
  frameworks?: string[]
): Promise<{ batch_id: string; scan_ids: string[]; status: ScanStatus }> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  const params = new URLSearchParams();
  if (vendor) params.set("vendor", vendor);
  if (frameworks && frameworks.length > 0) params.set("frameworks", frameworks.join(","));
  const qs = params.toString() ? `?${params.toString()}` : "";
  return request(`/api/ingest/bulk${qs}`, { method: "POST", body: form });
}

export async function getScan(scanId: string): Promise<Scan> {
  return request(`/api/scans/${scanId}`);
}

export async function listScans(vendor?: string, batchId?: string): Promise<{ scans: ScanListEntry[] }> {
  const params = new URLSearchParams();
  if (vendor) params.set("vendor", vendor);
  if (batchId) params.set("batch_id", batchId);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return request(`/api/scans${qs}`);
}

export async function getFindings(scanId: string): Promise<FindingsResponse> {
  return request(`/api/findings/${scanId}`);
}

export async function getRemediation(scanId: string, controlId: string): Promise<RemediationResponse> {
  return request(`/api/remediation/${scanId}/${controlId}`);
}

export async function getUnmatched(scanId: string): Promise<UnmatchedResponse> {
  return request(`/api/unmatched/${scanId}`);
}

export async function getControls(): Promise<{ controls: ControlRef[] }> {
  return request(`/api/controls`);
}

export interface TrainingDecisionUpdate {
  session_id: string;
  state: string;
  confirmed_count: number;
  cluster_id: string;
  suggestion: ClusterSuggestion | null;
}

export async function postTrainingDecision(
  scanId: string,
  body: { raw_line: string; canonical_field: string; decision: "accept" | "modify" | "reject"; cluster_id: string }
): Promise<{ status: string; updated_mapping: TrainingDecisionUpdate | null }> {
  return request(`/api/training/${scanId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Polls GET /api/scans/{id} until status is "done" or "error". */
export async function pollScanUntilDone(
  scanId: string,
  { intervalMs = 1500, timeoutMs = 60000 }: { intervalMs?: number; timeoutMs?: number } = {}
): Promise<Scan> {
  const start = Date.now();
  while (true) {
    const scan = await getScan(scanId);
    if (scan.status !== "processing") return scan;
    if (Date.now() - start > timeoutMs) {
      throw new Error(`Scan ${scanId} still processing after ${timeoutMs}ms`);
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}