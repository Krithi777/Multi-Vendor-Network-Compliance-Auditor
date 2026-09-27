#!/usr/bin/env bash
# demo/run_5vendor_demo.sh — milestone 13 rehearsal.
# Run from the project root. Requires the API running:
#   uvicorn phase9.api:app --port 8000
#
# Files below were picked by actually running vendor_detect +
# normalize_config + run_compliance_diff against every file in
# configs/real/real_data/<vendor>/ and keeping the highest-confidence,
# highest-signal (most non-MISSING states) match per vendor -- not
# picked blind. juniper_junos has no fuller sample in the repo right
# now; every Juniper file that vendor-detects comes back all-MISSING
# because the real_data fixtures are narrow Batfish test snippets, not
# full device configs. That's correct MISSING behavior on this input,
# not a parser bug -- swap in a fuller Junos config here if you have one
# before demoing that vendor.
set -euo pipefail
BASE="http://localhost:8000"
declare -A FILES=(
  [cisco_ios]="configs/real/real_data/cisco_ios/github__ciscoconfparse2__sample_07.ios"
  [juniper_junos]="configs/real/real_data/juniper_junos/batfish__testconfigs__authentication-order.cfg"
  [fortios]="configs/real/real_data/fortios/batfish__testconfigs__fortios_system_recovery.cfg"
  [panos]="configs/real/real_data/panos/batfish__testconfigs__ignored-lines.cfg"
  [arista_eos]="configs/real/real_data/arista_eos/batfish__nat-source-static__configs__r1.cfg"
)

for vendor in "${!FILES[@]}"; do
  file="${FILES[$vendor]}"
  echo "=== $vendor :: $file ==="
  scan_id=$(curl -s -F "file=@${file}" "$BASE/api/ingest" | python3 -c "import sys,json;print(json.load(sys.stdin)['scan_id'])")

  status="processing"
  for i in $(seq 1 20); do
    status=$(curl -s "$BASE/api/scans/$scan_id" | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])")
    [ "$status" = "done" ] && break
    [ "$status" = "error" ] && { echo "ERROR:"; curl -s "$BASE/api/scans/$scan_id"; break; }
    sleep 0.5
  done
  echo "status=$status scan_id=$scan_id"

  if [ "$status" = "done" ]; then
    curl -s "$BASE/api/findings/$scan_id" | python3 -c "import sys,json;d=json.load(sys.stdin);print('summary:',d['summary'])"
    curl -s "$BASE/api/reports/$scan_id/pdf" -o "/tmp/report_${vendor}.pdf"
    echo "report -> /tmp/report_${vendor}.pdf"
  fi
  echo
done
