"""
5-vendor end-to-end acceptance test.

Run this from the ROOT of your repo (where the `configs/` folder lives),
with your backend already running on localhost:8000 and pointed at your
Supabase DB, e.g.:

    python vendor_matrix_test.py

It will, for each vendor, upload a synthetic baseline config (where one
exists) and one real-world config, poll until the scan finishes, then
print: detected vendor, confidence, control counts by state
(PASS/FAIL/MISSING/REVIEW), and whether the PDF report endpoint works.

It does NOT modify your DB in any destructive way -- it only creates
scans, same as using the UI.
"""

import json
import time
import sys
from pathlib import Path

import requests

API_BASE = "http://localhost:8000"

# (vendor_label, file_path, is_synthetic)
CASES = [
    ("cisco_ios",      "configs/synthetic/baseline/cisco_ios/baseline.cfg", True),
    ("cisco_ios",      "configs/real/real_data/cisco_ios/batfish__testconfigs__aaaAuthenticationIos.cfg", False),

    ("juniper_junos",  "configs/synthetic/baseline/juniper_junos/baseline.cfg", True),
    ("juniper_junos",  "configs/real/real_data/juniper_junos/batfish__testconfigs__pre-defined-junos-applications-converted.cfg", False),

    ("fortios",        "configs/synthetic/baseline/fortios/baseline.cfg", True),
    ("fortios",        "configs/real/real_data/fortios/batfish__testconfigs__fortios_ignored.cfg", False),

    ("panos",          "configs/synthetic/baseline/panos/baseline.cfg", True),
    ("panos",          "configs/real/real_data/panos/batfish__testconfigs__ipsec-tunnel.cfg", False),

    # No synthetic baseline shipped for Arista in this repo snapshot.
    ("arista_eos",     "configs/real/real_data/arista_eos/batfish__arista-bgp-default-originate__configs__arista-originator.cfg", False),
]


def ingest(file_path: str, vendor_hint: str | None = None) -> str:
    # The real frontend (lib/api.ts) sends the override as a query string
    # (?vendor=...), not a form field -- FastAPI reads `vendor: str | None`
    # as a query param here since it isn't wrapped in Form(). Match that.
    url = f"{API_BASE}/api/ingest"
    if vendor_hint:
        url += f"?vendor={vendor_hint}"
    with open(file_path, "rb") as f:
        files = {"file": (Path(file_path).name, f)}
        resp = requests.post(url, files=files, timeout=30)
    resp.raise_for_status()
    return resp.json()["scan_id"]


def poll(scan_id: str, timeout_s: int = 60) -> dict:
    start = time.time()
    while time.time() - start < timeout_s:
        resp = requests.get(f"{API_BASE}/api/scans/{scan_id}", timeout=15)
        resp.raise_for_status()
        scan = resp.json()
        if scan["status"] in ("done", "error"):
            return scan
        time.sleep(1.5)
    raise TimeoutError(f"scan {scan_id} did not finish in {timeout_s}s")


def get_findings(scan_id: str) -> dict:
    # Actual shape (checked against phase9/api.py get_findings):
    # {"scan_id", "vendor", "summary": {...}, "results": [ {...}, ... ]}
    resp = requests.get(f"{API_BASE}/api/findings/{scan_id}", timeout=15)
    resp.raise_for_status()
    body = resp.json()
    return {"summary": body.get("summary", {}), "count": len(body.get("results", []))}


def try_pdf(scan_id: str) -> str:
    try:
        resp = requests.get(f"{API_BASE}/api/reports/{scan_id}/pdf", timeout=30)
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/pdf"):
            return "OK"
        return f"FAIL (status={resp.status_code}, body={resp.text[:200]!r})"
    except Exception as e:
        return f"FAIL (exception: {e})"


def main():
    if not Path("configs").exists():
        print("ERROR: run this from the repo root (the folder containing `configs/`).")
        sys.exit(1)

    results = []
    for expected_vendor, path, is_synth in CASES:
        label = f"{expected_vendor} [{'synthetic' if is_synth else 'real'}] {Path(path).name}"
        if not Path(path).exists():
            print(f"SKIP  {label} -- file not found at {path}")
            continue

        print(f"\n--- {label} ---")
        try:
            scan_id = ingest(path)
        except Exception as e:
            print(f"  INGEST FAILED: {e}")
            results.append((label, "INGEST_FAILED", str(e)))
            continue

        try:
            scan = poll(scan_id)
        except TimeoutError as e:
            print(f"  POLL TIMEOUT: {e}")
            results.append((label, "TIMEOUT", str(e)))
            continue

        detected = scan.get("vendor")
        confidence = scan.get("vendor_confidence")
        status = scan["status"]
        print(f"  scan_id={scan_id}  status={status}  detected_vendor={detected}  confidence={confidence}")

        if status == "error":
            print(f"  auto-detect result: {scan.get('error_message')}")
            print(f"  -> retrying with explicit vendor override ({expected_vendor}), "
                  f"same as a human confirming the vendor in the UI...")
            try:
                scan_id2 = ingest(path, vendor_hint=expected_vendor)
                scan = poll(scan_id2)
                scan_id = scan_id2
                detected = scan.get("vendor")
                status = scan["status"]
                print(f"  retry: scan_id={scan_id}  status={status}  detected_vendor={detected}")
                if status == "error":
                    print(f"  RETRY STILL FAILED: {scan.get('error_message')}")
                    results.append((label, "SCAN_ERROR_EVEN_WITH_OVERRIDE", scan.get("error_message")))
                    continue
            except Exception as e:
                print(f"  RETRY FAILED: {e}")
                results.append((label, "RETRY_FAILED", str(e)))
                continue

        vendor_match = "MATCH" if detected == expected_vendor else f"MISMATCH (expected {expected_vendor})"
        print(f"  vendor check: {vendor_match}")

        try:
            f = get_findings(scan_id)
            print(f"  findings ({f['count']} total): {f['summary']}")
            counts = f["summary"]
        except Exception as e:
            print(f"  FINDINGS FETCH FAILED: {e}")
            counts = {"ERROR": str(e)}

        pdf_status = try_pdf(scan_id)
        print(f"  pdf report: {pdf_status}")

        results.append((label, status, {
            "vendor_match": vendor_match,
            "findings": counts,
            "pdf": pdf_status,
        }))

    print("\n\n================ SUMMARY ================")
    for label, status, detail in results:
        print(f"{label:70s} status={status:12s} detail={detail}")


if __name__ == "__main__":
    main()