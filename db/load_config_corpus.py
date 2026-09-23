# db/load_config_corpus.py -- Phase 3 (903 real) + Phase 4 (195 synthetic) manifests -> config_corpus
import os
from sqlalchemy import text
from common import read_jsonl, get_engine, is_dry_run, ROOT

# Where your friend put the two manifests inside the repo; override with env vars if different.
REAL_MANIFEST  = os.environ.get("REAL_MANIFEST",  "metadata/phase3/dataset_manifest.jsonl")
SYNTH_MANIFEST = os.environ.get("SYNTH_MANIFEST", "metadata/phase4/synthetic_manifest.jsonl")

def _need(row, keys, where):
    miss = [k for k in keys if k not in row]
    if miss:
        raise SystemExit(f"{where}: manifest row missing {miss}: {row}")

def build_real_rows(manifest):
    rows = []
    for m in manifest:
        _need(m, ["vendor", "source", "sanitized_path"], "phase3")
        # manifest paths are Windows-style: configs\sanitized\<vendor>\<file>  ->  configs/real/<vendor>/<file>
        base = m["sanitized_path"].replace("\\", "/").split("/")[-1]
        rows.append(dict(
            fp=f"configs/real/{m['vendor']}/{base}", vendor=m["vendor"], st="real",
            src=m["source"], cid=None, state=None,
            sha=m.get("sanitize_report", {}).get("sha256_sanitized"),
            conf=m.get("label_confidence", "silver"),      # real values: silver / fixture / snippet
            at=m.get("collected_at"),
        ))
    return rows

def build_synthetic_rows(manifest):
    rows = []
    for m in manifest:
        _need(m, ["vendor", "control_id", "state", "file_path"], "phase4")
        rows.append(dict(
            fp=m["file_path"].replace("\\", "/"), vendor=m["vendor"], st="synthetic",
            src="synthetic_mutation", cid=m["control_id"], state=m["state"],
            sha=m.get("sha256"),            # NB: Phase 4 hashes are truncated to 16 hex chars
            conf="exact", at=None,          # no collection timestamp exists for generated files
        ))
    return rows

SQL = text("""
    INSERT INTO config_corpus
      (file_path, vendor, source_type, source, control_id, state, sha256, label_confidence, collected_at)
    VALUES (:fp, :vendor, :st, :src, :cid, :state, :sha, :conf, CAST(:at AS TIMESTAMPTZ))
    ON CONFLICT (file_path) DO UPDATE SET
      vendor = EXCLUDED.vendor, source_type = EXCLUDED.source_type, source = EXCLUDED.source,
      control_id = EXCLUDED.control_id, state = EXCLUDED.state, sha256 = EXCLUDED.sha256,
      label_confidence = EXCLUDED.label_confidence, collected_at = EXCLUDED.collected_at
""")

def load():
    real  = build_real_rows(read_jsonl(REAL_MANIFEST))
    synth = build_synthetic_rows(read_jsonl(SYNTH_MANIFEST))
    rows = real + synth
    paths = [r["fp"] for r in rows]
    assert len(paths) == len(set(paths)), "duplicate file_path across manifests"
    absent = [p for p in paths if not (ROOT / p).exists()]
    if absent:
        print(f"WARNING: {len(absent)} corpus files not found on disk under repo root "
              f"(e.g. {absent[0]}). Rows still load; Phase 6 needs the files copied in.")
    if is_dry_run():
        print(f"[dry-run] {len(real)} real + {len(synth)} synthetic = {len(rows)} rows ok"); return
    with get_engine().begin() as conn:
        for r in rows:
            conn.execute(SQL, r)
        n = conn.execute(text("SELECT source_type, count(*) FROM config_corpus GROUP BY 1 ORDER BY 1")).all()
    print(f"loaded {len(rows)} rows; table: {dict(n)}")

if __name__ == "__main__":
    load()
