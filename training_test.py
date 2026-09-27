"""
Phase 7 Training (unmatched-line clustering + human confirmation) test,
one real config per vendor.

Run from repo root, backend already running on localhost:8000:

    python training_test.py

What it does per vendor:
  1. Ingests the real config (with an explicit vendor override, so we
     skip the detect/ambiguous step entirely -- that's already proven).
  2. GET /api/unmatched/{scan_id} -- prints coverage_before_pct and how
     many clusters/unresolved lines exist.
  3. If any cluster exists, submits ONE training decision (accept) on
     its first unresolved sample line, using the first canonical_field
     from /api/controls (this is just to exercise the API path, not a
     semantically correct mapping -- don't read meaning into which
     field it picked).
  4. Re-fetches /api/unmatched/{scan_id} and checks the cluster's state
     changed and resolved_count went up.

After all 5 vendors run once, it pauses and asks you to save any .py
file in the backend (to trigger a uvicorn --reload) before continuing,
then re-checks the LAST vendor's cluster state to see whether the
cluster_id -> session_id link (in-memory, per phase9/api.py) survived
the restart or reset back to "untaught".
"""

import sys
import time
from pathlib import Path

import requests

API_BASE = "http://localhost:8000"

CASES = [
    ("cisco_ios",     "configs/real/real_data/cisco_ios/batfish__testconfigs__aaaAuthenticationIos.cfg"),
    ("juniper_junos", "configs/real/real_data/juniper_junos/batfish__testconfigs__pre-defined-junos-applications-converted.cfg"),
    ("fortios",       "configs/real/real_data/fortios/batfish__testconfigs__fortios_ignored.cfg"),
    ("panos",         "configs/real/real_data/panos/batfish__testconfigs__ipsec-tunnel.cfg"),
    ("arista_eos",    "configs/real/real_data/arista_eos/batfish__arista-bgp-default-originate__configs__arista-originator.cfg"),
]


def ingest(file_path: str, vendor: str) -> str:
    url = f"{API_BASE}/api/ingest?vendor={vendor}"
    with open(file_path, "rb") as f:
        resp = requests.post(url, files={"file": (Path(file_path).name, f)}, timeout=30)
    resp.raise_for_status()
    return resp.json()["scan_id"]


def poll(scan_id: str, timeout_s: int = 60) -> dict:
    start = time.time()
    while time.time() - start < timeout_s:
        r = requests.get(f"{API_BASE}/api/scans/{scan_id}", timeout=15)
        r.raise_for_status()
        scan = r.json()
        if scan["status"] in ("done", "error"):
            return scan
        time.sleep(1.5)
    raise TimeoutError(f"scan {scan_id} not finished after {timeout_s}s")


def get_unmatched(scan_id: str) -> dict:
    r = requests.get(f"{API_BASE}/api/unmatched/{scan_id}", timeout=15)
    r.raise_for_status()
    return r.json()


def get_first_canonical_field() -> str:
    r = requests.get(f"{API_BASE}/api/controls", timeout=15)
    r.raise_for_status()
    controls = r.json()["controls"]
    if not controls:
        raise RuntimeError("no controls returned by /api/controls")
    return controls[0]["canonical_field"]


def submit_decision(scan_id: str, raw_line: str, cluster_id: str, canonical_field: str) -> dict:
    body = {
        "raw_line": raw_line,
        "canonical_field": canonical_field,
        "decision": "accept",
        "cluster_id": cluster_id,
    }
    r = requests.post(f"{API_BASE}/api/training/{scan_id}/decision", json=body, timeout=15)
    r.raise_for_status()
    return r.json()


def main():
    if not Path("configs").exists():
        print("ERROR: run this from the repo root (the folder containing `configs/`).")
        sys.exit(1)

    canonical_field = get_first_canonical_field()
    print(f"Using canonical_field={canonical_field!r} for test decisions (not semantically meaningful, just exercising the API)\n")

    last_scan_id = None
    last_cluster_id = None
    last_raw_line = None

    for vendor, path in CASES:
        if not Path(path).exists():
            print(f"SKIP {vendor} -- file not found: {path}")
            continue

        print(f"--- {vendor} ---")
        scan_id = ingest(path, vendor)
        scan = poll(scan_id)
        if scan["status"] == "error":
            print(f"  SCAN ERROR: {scan.get('error_message')} (skipping training check)")
            continue

        unmatched = get_unmatched(scan_id)
        n_clusters = len(unmatched["clusters"])
        print(f"  scan_id={scan_id}  coverage_before_pct={unmatched['coverage_before_pct']}  "
              f"clusters={n_clusters}  total_unresolved={unmatched['total_unresolved']}")

        if n_clusters == 0:
            print("  no unmatched clusters for this file -- nothing to train on, skipping.\n")
            continue

        cluster = unmatched["clusters"][0]
        sample = cluster["sample_lines"][0]
        print(f"  cluster_id={cluster['cluster_id']}  state={cluster['state']}  "
              f"sample_raw_line={sample['raw_line']!r}")

        result = submit_decision(scan_id, sample["raw_line"], cluster["cluster_id"], canonical_field)
        print(f"  decision result: {result['updated_mapping']}")

        unmatched2 = get_unmatched(scan_id)
        cluster2 = next(c for c in unmatched2["clusters"] if c["cluster_id"] == cluster["cluster_id"])
        print(f"  after decision: state={cluster2['state']}  resolved_count={cluster2['resolved_count']}\n")

        last_scan_id, last_cluster_id, last_raw_line = scan_id, cluster["cluster_id"], sample["raw_line"]

    if last_scan_id is None:
        print("No vendor produced an unmatched cluster to test the reload behavior with. Done.")
        return

    print("=" * 60)
    print("Now: save any .py file under phase9/ or phase7/ (even just adding")
    print("a blank line and saving) to trigger uvicorn --reload, wait for")
    print("'Application startup complete.' in the backend log, THEN press Enter here.")
    input("Press Enter once the backend has finished reloading... ")

    unmatched3 = get_unmatched(last_scan_id)
    cluster3 = next((c for c in unmatched3["clusters"] if c["cluster_id"] == last_cluster_id), None)
    if cluster3 is None:
        print("  cluster no longer present after reload (unexpected).")
    else:
        print(f"  AFTER RELOAD: state={cluster3['state']}  resolved_count={cluster3['resolved_count']}")
        if cluster3["state"] == "untaught" or cluster3["resolved_count"] == 0:
            print("  -> Progress was LOST on reload. The cluster_id -> session_id link is "
                  "in-memory only and did not survive the restart, even though the underlying "
                  "phase7 data may still exist in Postgres.")
        else:
            print("  -> Progress SURVIVED the reload.")


if __name__ == "__main__":
    main()