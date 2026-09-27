"use client";

// Training Studio (Phase 9, milestone 10). Layout follows the density of
// SentinelGrid's own Training Studio wireframe (p-train): a cluster list
// on the left, the selected cluster's evidence + teaching controls in the
// center, and a fusion-signal breakdown + decision log on the right --
// rather than the flat "one line at a time" list this page used to be.
//
// Every number here comes straight off GET/POST /api/unmatched|training --
// there is no client-side fusion-score math. A cluster's "suggestion"
// panel is null (and the UI says so) until >=3 confirmed examples have
// actually made phase7 generalize; nothing is estimated ahead of that.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, LayoutList, Layers } from "lucide-react";
import {
  getUnmatched,
  getControls,
  postTrainingDecision,
  ApiError,
  type UnmatchedCluster,
  type ClusterSuggestion,
  type DecisionLogEntry,
  type ControlRef,
  type SampleLine,
} from "@/lib/api";
import FieldSelect from "../../components/FieldSelect";

type LoadState = "loading" | "ready" | "error";
type ViewMode = "list" | "flashcards";

const BUCKET_STYLE: Record<string, string> = {
  HIGH: "text-pass",
  MEDIUM: "text-review",
  LOW: "text-missing",
};

const COMPONENT_LABELS: { key: keyof ClusterSuggestion["component_scores"]; label: string }[] = [
  { key: "syntax", label: "Syntax" },
  { key: "context", label: "Context" },
  { key: "value_semantics", label: "Semantics" },
  { key: "framework_fit", label: "Framework" },
  { key: "precedent", label: "Precedent" },
];

export default function TrainingStudioPage({ params }: { params: { scanId: string } }) {
  const { scanId } = params;
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [controls, setControls] = useState<ControlRef[]>([]);
  const [clusters, setClusters] = useState<UnmatchedCluster[]>([]);
  const [decisionLog, setDecisionLog] = useState<DecisionLogEntry[]>([]);
  const [coveragePct, setCoveragePct] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [fieldByCluster, setFieldByCluster] = useState<Record<string, string>>({});
  const [rowBusy, setRowBusy] = useState<string | null>(null); // `${clusterId}:${raw_line}`
  const [rowError, setRowError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [flashcardIndex, setFlashcardIndex] = useState(0);
  // Which resolved row (by rowKey) is currently open for editing, and the
  // canonical_field a mapped row actually last resolved to -- SampleLine
  // itself only carries `resolved: boolean`, so this is tracked client-side
  // from what each accept/modify call was actually submitted with.
  const [editingRow, setEditingRow] = useState<string | null>(null);
  const [mappedFieldByLine, setMappedFieldByLine] = useState<Record<string, string>>({});
  const [modifyDraft, setModifyDraft] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [unmatched, controlList] = await Promise.all([getUnmatched(scanId), getControls()]);
        if (cancelled) return;
        setControls(controlList.controls);
        setClusters(unmatched.clusters);
        setDecisionLog(unmatched.decision_log);
        setCoveragePct(unmatched.coverage_before_pct);
        // Hydrate mappedFieldByLine from the persisted decision log so rows
        // resolved in a *previous* session still show their real canonical
        // field (and "Modify" opens pre-filled) instead of falling back to
        // the cluster's generic suggestion, which is empty/wrong for that
        // row and made "Modify" look like it did nothing.
        setMappedFieldByLine((prev) => {
          const next = { ...prev };
          for (const entry of unmatched.decision_log) {
            if (entry.type === "rejected" || !entry.canonical_field) continue;
            const key = `${entry.cluster_id}:${entry.raw_line}`;
            if (!(key in next)) next[key] = entry.canonical_field;
          }
          return next;
        });
        setSelectedId(unmatched.clusters[0]?.cluster_id ?? null);
        setLoadState("ready");
      } catch (err) {
        if (cancelled) return;
        setLoadState("error");
        setErrorMessage(
          err instanceof ApiError ? err.message : "Could not load the teaching queue. Is the backend running?"
        );
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [scanId]);

  const selected = clusters.find((c) => c.cluster_id === selectedId) ?? null;
  const totalUnresolved = clusters.reduce((sum, c) => sum + (c.count - c.resolved_count), 0);
  const openClusters = useMemo(() => clusters.filter((c) => c.resolved_count < c.count), [clusters]);
  const fieldOptions = useMemo(
    () => controls.map((c) => ({ value: c.canonical_field, label: `${c.control_id} · ${c.canonical_field}` })),
    [controls]
  );

  function patchCluster(clusterId: string, patch: Partial<UnmatchedCluster>) {
    setClusters((prev) => prev.map((c) => (c.cluster_id === clusterId ? { ...c, ...patch } : c)));
  }

  async function decide(
    cluster: UnmatchedCluster,
    line: SampleLine,
    decision: "accept" | "reject" | "modify",
    explicitField?: string
  ) {
    const rowKey = `${cluster.cluster_id}:${line.raw_line}`;
    const canonicalField =
      decision === "modify"
        ? explicitField ?? modifyDraft[rowKey] ?? mappedFieldByLine[rowKey] ?? ""
        : fieldByCluster[cluster.cluster_id] ?? cluster.suggestion?.canonical_field ?? "";
    if (decision !== "reject" && !canonicalField) {
      setRowError(rowKey);
      return;
    }
    setRowBusy(rowKey);
    setRowError(null);
    try {
      const res = await postTrainingDecision(scanId, {
        raw_line: line.raw_line,
        canonical_field: canonicalField,
        decision,
        cluster_id: cluster.cluster_id,
      });
      // A "modify" re-maps a line that was already counted as resolved --
      // don't double-count it against the cluster's resolved_count.
      const resolvedDelta = decision === "reject" || decision === "modify" ? 0 : 1;
      patchCluster(cluster.cluster_id, {
        resolved_count: cluster.resolved_count + resolvedDelta,
        sample_lines: cluster.sample_lines.map((sl) =>
          sl.raw_line === line.raw_line ? { ...sl, resolved: decision !== "reject" ? true : sl.resolved } : sl
        ),
        suggestion: res.updated_mapping?.suggestion ?? cluster.suggestion,
        state: (res.updated_mapping?.state.toLowerCase() as UnmatchedCluster["state"]) ?? cluster.state,
      });
      if (decision !== "reject") {
        setMappedFieldByLine((prev) => ({ ...prev, [rowKey]: canonicalField }));
      }
      if (decision === "modify") {
        setEditingRow(null);
      }
      setDecisionLog((prev) => [
        {
          type: decision === "reject" ? "rejected" : decision === "modify" ? "edited" : "accepted",
          raw_line: line.raw_line,
          cluster_id: cluster.cluster_id,
          canonical_field: decision !== "reject" ? canonicalField : null,
          at: Date.now() / 1000,
        },
        ...prev,
      ]);
    } catch (err) {
      setRowError(rowKey);
    } finally {
      setRowBusy(null);
    }
  }

  if (loadState === "loading") {
    return <div className="font-mono text-sm text-ink-soft">Loading teaching queue…</div>;
  }

  if (loadState === "error") {
    return (
      <div className="max-w-md">
        <p className="font-mono text-xs uppercase tracking-wide text-fail mb-2">Could not load training studio</p>
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

  return (
    <div className="flex flex-col gap-6">
      <Link
        href={`/scan/${scanId}`}
        className="inline-flex items-center gap-1.5 text-sm text-ink-soft hover:text-ink w-fit"
      >
        <ArrowLeft className="w-4 h-4" strokeWidth={2} />
        Back to scan
      </Link>

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="font-mono text-xs text-ink-soft mb-1.5">scan {scanId.slice(0, 8)} · automated teaching loop</p>
          <h1 className="font-display text-[28px] font-semibold tracking-tight">Training studio</h1>
          <p className="text-sm text-ink-soft mt-2.5 max-w-2xl leading-relaxed">
            Configuration lines the parser couldn&apos;t confidently classify, grouped by structural similarity.
            Confirming <span className="text-ink/80 font-medium">3</span> examples in a cluster lets the system
            learn a syntax template, evaluate every remaining line against five weighted signals, and apply the
            mapping automatically.
          </p>
        </div>
        <div className="flex items-center gap-5 shrink-0">
          <div className="flex gap-5 text-sm font-mono">
            <span className="text-ink-soft">
              clusters: <span className="text-ink">{clusters.length}</span>
            </span>
            <span className="text-ink-soft">
              unresolved: <span className="text-ink">{totalUnresolved}</span>
            </span>
          </div>
          {clusters.length > 0 && (
            <div className="flex items-center gap-1 rounded-full border border-line p-1 shrink-0">
              <button
                onClick={() => setViewMode("list")}
                className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  viewMode === "list" ? "bg-ink text-paper" : "text-ink-soft hover:text-ink"
                }`}
              >
                <LayoutList className="w-3.5 h-3.5" strokeWidth={2} />
                List
              </button>
              <button
                onClick={() => {
                  setViewMode("flashcards");
                  setFlashcardIndex(0);
                }}
                className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  viewMode === "flashcards" ? "bg-ink text-paper" : "text-ink-soft hover:text-ink"
                }`}
              >
                <Layers className="w-3.5 h-3.5" strokeWidth={2} />
                Flashcards
              </button>
            </div>
          )}
        </div>
      </div>

      {clusters.length === 0 ? (
        <div className="rounded-2xl border border-line bg-panel p-6 text-sm text-ink-soft">
          Nothing to teach for this scan -- every line matched deterministically.
        </div>
      ) : (
        <>
          {viewMode === "flashcards" ? (
            <FlashcardReview
              clusters={openClusters}
              index={flashcardIndex}
              onIndexChange={setFlashcardIndex}
              fieldOptions={fieldOptions}
              fieldByCluster={fieldByCluster}
              onFieldChange={(clusterId, field) =>
                setFieldByCluster((prev) => ({ ...prev, [clusterId]: field }))
              }
              rowBusy={rowBusy}
              rowError={rowError}
              onAccept={(cluster, line) => decide(cluster, line, "accept")}
              onReject={(cluster, line) => decide(cluster, line, "reject")}
            />
          ) : (
            // Fixed-height studio pane: each column scrolls internally
            // instead of the page growing/shrinking (and jumping) every
            // time a cluster with a different number of sample lines is
            // selected. This is what was reported as the page "sliding".
            <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr_300px] gap-5 items-stretch lg:h-[calc(100vh-320px)] lg:min-h-[520px]">
              <div className="min-h-0 lg:h-full lg:overflow-y-auto pr-0.5">
                <ClusterList
                  clusters={clusters}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  coveragePct={coveragePct}
                />
              </div>

              <div className="min-h-0 lg:h-full lg:overflow-y-auto pr-0.5">
                {selected ? (
                  <ClusterDetail
                    cluster={selected}
                    fieldOptions={fieldOptions}
                    selectedField={fieldByCluster[selected.cluster_id] ?? selected.suggestion?.canonical_field ?? ""}
                    onFieldChange={(field) =>
                      setFieldByCluster((prev) => ({ ...prev, [selected.cluster_id]: field }))
                    }
                    rowBusy={rowBusy}
                    rowError={rowError}
                    onAccept={(line) => decide(selected, line, "accept")}
                    onReject={(line) => decide(selected, line, "reject")}
                    mappedFieldByLine={mappedFieldByLine}
                    editingRow={editingRow}
                    modifyDraft={modifyDraft}
                    onModifyStart={(rowKey, currentField) => {
                      setModifyDraft((prev) => ({ ...prev, [rowKey]: currentField }));
                      setEditingRow(rowKey);
                    }}
                    onModifyDraftChange={(rowKey, field) =>
                      setModifyDraft((prev) => ({ ...prev, [rowKey]: field }))
                    }
                    onModifyCancel={() => setEditingRow(null)}
                    onModifySave={(line) => decide(selected, line, "modify")}
                  />
                ) : (
                  <div className="rounded-2xl border border-line bg-panel p-6 text-sm text-ink-soft">
                    Select a cluster on the left.
                  </div>
                )}
              </div>

              <div className="min-h-0 lg:h-full lg:overflow-y-auto flex flex-col gap-5 pr-0.5">
                <FusionPanel suggestion={selected?.suggestion ?? null} />
                <DecisionLogPanel entries={decisionLog} />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function FlashcardReview({
  clusters,
  index,
  onIndexChange,
  fieldOptions,
  fieldByCluster,
  onFieldChange,
  rowBusy,
  rowError,
  onAccept,
  onReject,
}: {
  clusters: UnmatchedCluster[];
  index: number;
  onIndexChange: (i: number) => void;
  fieldOptions: { value: string; label: string }[];
  fieldByCluster: Record<string, string>;
  onFieldChange: (clusterId: string, field: string) => void;
  rowBusy: string | null;
  rowError: string | null;
  onAccept: (cluster: UnmatchedCluster, line: SampleLine) => void;
  onReject: (cluster: UnmatchedCluster, line: SampleLine) => void;
}) {
  const [flipped, setFlipped] = useState(false);

  if (clusters.length === 0) {
    return (
      <div className="rounded-2xl border border-line bg-panel p-8 text-center text-sm text-ink-soft">
        Every cluster is resolved -- nothing left to flip through.
      </div>
    );
  }

  const safeIndex = Math.min(index, clusters.length - 1);
  const cluster = clusters[safeIndex];
  const remaining = cluster.count - cluster.resolved_count;
  const nextUnresolved = cluster.sample_lines.find((l) => !l.resolved) ?? null;
  const suggestion = cluster.suggestion;
  const selectedField = fieldByCluster[cluster.cluster_id] ?? suggestion?.canonical_field ?? "";
  const rowKey = nextUnresolved ? `${cluster.cluster_id}:${nextUnresolved.raw_line}` : "";
  const busy = rowBusy === rowKey;
  const errored = rowError === rowKey;

  function go(delta: number) {
    setFlipped(false);
    onIndexChange(Math.max(0, Math.min(clusters.length - 1, safeIndex + delta)));
  }

  return (
    <div className="flex flex-col items-center gap-5">
      <p className="font-mono text-xs text-ink-soft">
        Card {safeIndex + 1} of {clusters.length}
      </p>

      <div
        onClick={() => setFlipped((f) => !f)}
        className="w-full max-w-xl min-h-[280px] rounded-2xl border border-line bg-panel p-7 flex flex-col justify-between cursor-pointer select-none shadow-sm hover:border-ink-soft transition-colors"
      >
        {!flipped ? (
          <>
            <div>
              <p className="text-[11px] font-mono uppercase tracking-wide text-ink-soft mb-3">
                {cluster.context_category || "no context"} · {cluster.count} line{cluster.count === 1 ? "" : "s"}
              </p>
              <p className="font-mono text-base text-ink leading-relaxed break-words">
                {cluster.representative_line}
              </p>
            </div>
            <p className="text-xs text-ink-soft mt-6">Click to reveal the suggested mapping →</p>
          </>
        ) : (
          <>
            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <p className="text-[11px] font-mono uppercase tracking-wide text-ink-soft">Suggested mapping</p>
                {suggestion && (
                  <span className={`font-mono text-xs font-semibold ${BUCKET_STYLE[suggestion.confidence_bucket]}`}>
                    {suggestion.confidence_bucket} · {suggestion.fused_confidence.toFixed(2)}
                  </span>
                )}
              </div>

              {suggestion ? (
                <p className="text-sm text-ink">
                  <span className="font-mono text-ink/90">{suggestion.canonical_field}</span>
                  {suggestion.control_id ? ` (${suggestion.control_id})` : ""}
                </p>
              ) : (
                <p className="text-sm text-ink-soft">
                  Not enough confirmed examples yet -- pick a canonical field below to teach this cluster.
                </p>
              )}

              <div onClick={(e) => e.stopPropagation()}>
                <FieldSelect
                  value={selectedField}
                  onChange={(field) => onFieldChange(cluster.cluster_id, field)}
                  options={fieldOptions}
                  placeholder="Select canonical field…"
                />
              </div>

              {nextUnresolved && (
                <div className="rounded-lg border border-line-soft bg-paper-dim px-3.5 py-2.5">
                  <p className="font-mono text-xs text-ink/80 break-words">
                    {nextUnresolved.line_number != null && (
                      <span className="text-ink-soft mr-2">L{nextUnresolved.line_number}</span>
                    )}
                    {nextUnresolved.raw_line}
                  </p>
                  {errored && <p className="text-[11px] text-fail mt-1">Pick a field, or the request failed.</p>}
                </div>
              )}
            </div>

            <p className="text-xs text-ink-soft mt-4">Click to flip back</p>
          </>
        )}
      </div>

      {flipped && nextUnresolved && (
        <div className="flex gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onAccept(cluster, nextUnresolved);
            }}
            disabled={busy}
            className="rounded-lg bg-ink text-paper px-4 py-2 text-sm font-medium hover:bg-ink/90 disabled:opacity-60"
          >
            {busy ? "…" : "Confirm"}
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onReject(cluster, nextUnresolved);
            }}
            disabled={busy}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink-soft hover:text-ink disabled:opacity-60"
          >
            Reject
          </button>
        </div>
      )}

      <p className="font-mono text-[11px] text-ink-soft">
        {cluster.resolved_count} / {cluster.count} resolved in this cluster
        {remaining === 0 ? " · complete" : ""}
      </p>

      <div className="flex items-center gap-3">
        <button
          onClick={() => go(-1)}
          disabled={safeIndex === 0}
          className="rounded-full border border-line px-4 py-2 text-sm text-ink-soft hover:text-ink disabled:opacity-30"
        >
          ← Prev
        </button>
        <button
          onClick={() => go(1)}
          disabled={safeIndex === clusters.length - 1}
          className="rounded-full border border-line px-4 py-2 text-sm text-ink-soft hover:text-ink disabled:opacity-30"
        >
          Next →
        </button>
      </div>
    </div>
  );
}

function ClusterList({
  clusters,
  selectedId,
  onSelect,
  coveragePct,
}: {
  clusters: UnmatchedCluster[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  coveragePct: number | null;
}) {
  return (
    <div className="rounded-2xl border border-line bg-panel p-4 flex flex-col gap-3 h-full">
      <div className="flex items-center justify-between px-1">
        <h3 className="text-xs font-mono uppercase tracking-wide text-ink-soft">Unmatched clusters</h3>
        <span className="text-[11px] font-mono text-ink-soft">{clusters.length}</span>
      </div>

      <div className="flex flex-col gap-1 pr-0.5">
        {clusters.map((c) => {
          const active = c.cluster_id === selectedId;
          const remaining = c.count - c.resolved_count;
          return (
            <button
              key={c.cluster_id}
              onClick={() => onSelect(c.cluster_id)}
              className={`text-left rounded-xl px-3 py-2.5 transition-colors border ${
                active ? "bg-paper-dim border-line" : "border-transparent hover:bg-paper-dim/60"
              }`}
            >
              <p className="font-mono text-xs text-ink/90 truncate">{c.representative_line}</p>
              <p className="text-[11px] text-ink-soft mt-0.5 truncate">
                {c.count} line{c.count === 1 ? "" : "s"} · {c.context_category}
                {remaining === 0 && <span className="text-pass"> · resolved</span>}
              </p>
            </button>
          );
        })}
      </div>

      {coveragePct != null && (
        <div className="pt-3 border-t border-line-soft px-1">
          <p className="text-[11px] text-ink-soft mb-1.5">Coverage before teaching</p>
          <div className="h-1.5 rounded-full bg-line overflow-hidden">
            <div className="h-full bg-review rounded-full" style={{ width: `${coveragePct}%` }} />
          </div>
          <p className="text-[11px] font-mono text-ink-soft mt-1">{coveragePct}% of lines matched deterministically</p>
        </div>
      )}
    </div>
  );
}

function ClusterDetail({
  cluster,
  fieldOptions,
  selectedField,
  onFieldChange,
  rowBusy,
  rowError,
  onAccept,
  onReject,
  mappedFieldByLine,
  editingRow,
  modifyDraft,
  onModifyStart,
  onModifyDraftChange,
  onModifyCancel,
  onModifySave,
}: {
  cluster: UnmatchedCluster;
  fieldOptions: { value: string; label: string }[];
  selectedField: string;
  onFieldChange: (field: string) => void;
  rowBusy: string | null;
  rowError: string | null;
  onAccept: (line: SampleLine) => void;
  onReject: (line: SampleLine) => void;
  mappedFieldByLine: Record<string, string>;
  editingRow: string | null;
  modifyDraft: Record<string, string>;
  onModifyStart: (rowKey: string, currentField: string) => void;
  onModifyDraftChange: (rowKey: string, field: string) => void;
  onModifyCancel: () => void;
  onModifySave: (line: SampleLine) => void;
}) {
  const suggestion = cluster.suggestion;
  const remaining = cluster.count - cluster.resolved_count;

  return (
    <div className="rounded-2xl border border-line bg-panel p-5 flex flex-col gap-4">
      <div>
        <h3 className="text-sm font-semibold">
          Cluster: <code className="font-mono text-xs bg-paper-dim px-1.5 py-0.5 rounded">{cluster.representative_line}</code>
        </h3>
        <p className="text-xs text-ink-soft mt-1">
          {cluster.count} line{cluster.count === 1 ? "" : "s"} · {cluster.context_category} · confirm 3 to
          generalize
        </p>
      </div>

      <FieldSelect
        value={selectedField}
        onChange={onFieldChange}
        options={fieldOptions}
        placeholder="Select canonical field for this cluster…"
      />

      <div className="flex flex-col gap-2.5 max-h-[380px] overflow-y-auto pr-0.5">
        {cluster.sample_lines.map((line) => {
          const rowKey = `${cluster.cluster_id}:${line.raw_line}`;
          const busy = rowBusy === rowKey;
          const errored = rowError === rowKey;
          const isEditing = editingRow === rowKey;
          const mappedField = mappedFieldByLine[rowKey] ?? suggestion?.canonical_field ?? "";
          return (
            <div
              key={rowKey}
              className={`rounded-lg border px-3.5 py-2.5 flex flex-col gap-2.5 ${
                line.resolved ? "border-line-soft bg-paper-dim/50" : "border-line-soft bg-paper-dim"
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  {line.context_path && <p className="text-[10px] font-mono text-ink-soft/70">{line.context_path}</p>}
                  <p className="font-mono text-xs text-ink/80 truncate">
                    {line.line_number != null && <span className="text-ink-soft mr-2">L{line.line_number}</span>}
                    {line.raw_line}
                  </p>
                  {errored && <p className="text-[11px] text-fail mt-1">Pick a field, or the request failed.</p>}
                </div>
                {line.resolved ? (
                  !isEditing && (
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-[11px] font-mono text-pass truncate max-w-[140px]">
                        ✓ {mappedField || "mapped"}
                      </span>
                      <button
                        onClick={() => onModifyStart(rowKey, mappedField)}
                        className="rounded-lg border border-line px-2.5 py-1 text-[11px] font-medium text-ink-soft hover:text-ink hover:border-ink-soft"
                      >
                        Modify
                      </button>
                    </div>
                  )
                ) : (
                  <div className="flex gap-1.5 shrink-0">
                    <button
                      onClick={() => onAccept(line)}
                      disabled={busy}
                      className="rounded-lg bg-ink text-paper px-3 py-1.5 text-[11px] font-medium hover:bg-ink/90 disabled:opacity-60"
                    >
                      {busy ? "…" : "Confirm"}
                    </button>
                    <button
                      onClick={() => onReject(line)}
                      disabled={busy}
                      className="rounded-lg border border-line px-3 py-1.5 text-[11px] font-medium text-ink-soft hover:text-ink disabled:opacity-60"
                    >
                      Reject
                    </button>
                  </div>
                )}
              </div>

              {line.resolved && isEditing && (
                <div className="flex items-center gap-2">
                  <FieldSelect
                    value={modifyDraft[rowKey] ?? mappedField}
                    onChange={(field) => onModifyDraftChange(rowKey, field)}
                    options={fieldOptions}
                    placeholder="Select canonical field…"
                    className="flex-1"
                  />
                  <button
                    onClick={() => onModifySave(line)}
                    disabled={busy}
                    className="rounded-lg bg-ink text-paper px-3 py-1.5 text-[11px] font-medium hover:bg-ink/90 disabled:opacity-60 shrink-0"
                  >
                    {busy ? "…" : "Save"}
                  </button>
                  <button
                    onClick={onModifyCancel}
                    disabled={busy}
                    className="rounded-lg border border-line px-3 py-1.5 text-[11px] font-medium text-ink-soft hover:text-ink disabled:opacity-60 shrink-0"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {suggestion && (
        <div className="flex items-center justify-between gap-4 px-4 py-3 rounded-lg bg-paper-dim border border-line-soft">
          <div>
            <p className="text-xs font-semibold text-ink">
              This mapping also covers {suggestion.evaluated_count} more line
              {suggestion.evaluated_count === 1 ? "" : "s"}
            </p>
            <p className="text-[11px] text-ink-soft mt-0.5">
              {suggestion.generalized_count} auto-applied · {suggestion.remaining_count} still need review ·
              template <code className="font-mono">{suggestion.template}</code>
            </p>
          </div>
        </div>
      )}

      <div>
        <div className="h-1.5 rounded-full bg-line overflow-hidden">
          <div
            className="h-full bg-pass rounded-full transition-[width]"
            style={{ width: `${cluster.count ? (cluster.resolved_count / cluster.count) * 100 : 0}%` }}
          />
        </div>
        <p className="text-[11px] font-mono text-ink-soft mt-1">
          {cluster.resolved_count} / {cluster.count} lines resolved{remaining === 0 ? " · cluster complete" : ""}
        </p>
      </div>
    </div>
  );
}

function FusionPanel({ suggestion }: { suggestion: ClusterSuggestion | null }) {
  return (
    <div className="rounded-2xl border border-line bg-panel p-5">
      <h3 className="text-xs font-mono uppercase tracking-wide text-ink-soft mb-1">Fusion signal breakdown</h3>
      {!suggestion ? (
        <p className="text-xs text-ink-soft mt-2">
          Confirm 3 examples in this cluster to compute a real fusion score -- nothing is estimated before then.
        </p>
      ) : (
        <>
          <div className="flex items-baseline justify-between mt-2 mb-3">
            <span className="font-mono text-2xl font-semibold text-ink">{suggestion.fused_confidence.toFixed(2)}</span>
            <span className={`font-mono text-xs font-semibold ${BUCKET_STYLE[suggestion.confidence_bucket]}`}>
              {suggestion.confidence_bucket}
            </span>
          </div>
          <div className="flex flex-col gap-2.5">
            {COMPONENT_LABELS.map(({ key, label }) => {
              const value = suggestion.component_scores[key];
              return (
                <div key={key}>
                  <div className="flex justify-between text-[11px] font-mono text-ink-soft mb-1">
                    <span>{label}</span>
                    <span>{value == null ? "n/a" : value.toFixed(2)}</span>
                  </div>
                  <div className="h-1 rounded-full bg-line overflow-hidden">
                    <div
                      className="h-full bg-ink/70 rounded-full"
                      style={{ width: value == null ? "0%" : `${value * 100}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          <p className="text-[11px] text-ink-soft mt-3">
            Mapped to <span className="font-mono text-ink/80">{suggestion.canonical_field}</span>
            {suggestion.control_id ? ` (${suggestion.control_id})` : ""}
          </p>
        </>
      )}
    </div>
  );
}

function DecisionLogPanel({ entries }: { entries: DecisionLogEntry[] }) {
  return (
    <div className="rounded-2xl border border-line bg-panel p-5">
      <h3 className="text-xs font-mono uppercase tracking-wide text-ink-soft mb-3">Decision log</h3>
      {entries.length === 0 ? (
        <p className="text-xs text-ink-soft">No decisions yet this session.</p>
      ) : (
        <div className="flex flex-col gap-3 max-h-[280px] overflow-y-auto pr-0.5">
          {entries.map((e, i) => (
            <div key={i} className="flex items-start gap-2.5">
              <span
                className={`mt-1 w-1.5 h-1.5 rounded-full shrink-0 ${
                  e.type === "accepted" ? "bg-pass" : e.type === "edited" ? "bg-review" : "bg-fail"
                }`}
              />
              <div className="min-w-0">
                <p className="text-xs text-ink/90">
                  <span className="font-medium capitalize">{e.type}</span>
                  {e.canonical_field ? (
                    <>
                      {" "}
                      → <span className="font-mono text-ink-soft">{e.canonical_field}</span>
                    </>
                  ) : null}
                </p>
                <p className="text-[11px] text-ink-soft/80 font-mono truncate">{relativeTime(e.at)}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function relativeTime(unixSeconds: number): string {
  const deltaSec = Math.max(0, Date.now() / 1000 - unixSeconds);
  if (deltaSec < 60) return "just now";
  if (deltaSec < 3600) return `${Math.floor(deltaSec / 60)} min ago`;
  if (deltaSec < 86400) return `${Math.floor(deltaSec / 3600)}h ago`;
  return `${Math.floor(deltaSec / 86400)}d ago`;
}