"""Debug: does ?vendor=<x> on /api/ingest actually bypass detection?"""
import json
import time
import requests

API_BASE = "http://localhost:8000"
FILE_PATH = "configs/real/real_data/juniper_junos/batfish__testconfigs__pre-defined-junos-applications-converted.cfg"
VENDOR = "juniper_junos"

url = f"{API_BASE}/api/ingest?vendor={VENDOR}"
print(f"POST {url}")
with open(FILE_PATH, "rb") as f:
    resp = requests.post(url, files={"file": (FILE_PATH.split('/')[-1], f)}, timeout=30)

print("ingest status_code:", resp.status_code)
print("ingest raw body:", resp.text)

scan_id = resp.json()["scan_id"]

for _ in range(30):
    time.sleep(1.5)
    r2 = requests.get(f"{API_BASE}/api/scans/{scan_id}", timeout=15)
    scan = r2.json()
    if scan["status"] != "processing":
        break

print("\nfinal GET /api/scans/{scan_id} raw body:")
print(json.dumps(scan, indent=2))