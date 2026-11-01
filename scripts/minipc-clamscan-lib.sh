# Shared ClamAV scan helpers (sourced by minipc-clamscan-*.sh).

minipc_clam_progress_write() {
  local progress_file="$1"
  local payload_json="${2:-}"
  if [ -z "$payload_json" ]; then
    return 1
  fi
  PROGRESS_PATH="$progress_file" PROGRESS_JSON="$payload_json" python3 <<'PY'
import json
import os
from datetime import datetime, timezone

path = os.environ["PROGRESS_PATH"]
payload = json.loads(os.environ["PROGRESS_JSON"])
payload["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
if payload.get("total_files") and int(payload["total_files"]) > 0:
    scanned = int(payload.get("scanned_files") or 0)
    total = int(payload["total_files"])
    payload["percent"] = min(100, int(scanned * 100 / total))
else:
    payload["percent"] = 0
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(payload, fh)
    fh.write("\n")
os.replace(tmp, path)
PY
}

minipc_clam_progress_init() {
  local progress_file="$1"
  local scope="$2"
  local target="$3"
  local started_at
  started_at="$(date -Iseconds)"
  python3 - "$progress_file" "$scope" "$target" "$started_at" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

path, scope, target, started_at = sys.argv[1:5]
payload = {
    "active": True,
    "state": "starting",
    "scope": scope,
    "target": target,
    "started_at": started_at,
    "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "total_files": 0,
    "scanned_files": 0,
    "infected": 0,
    "errors": 0,
    "percent": 0,
    "current_file": None,
    "message": "Starting scan…",
}
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(payload, fh)
    fh.write("\n")
os.replace(tmp, path)
PY
}

minipc_clam_progress_finish() {
  local progress_file="$1"
  local state="$2"
  local message="$3"
  local scanned="$4"
  local infected="$5"
  local errors="$6"
  local total="$7"
  python3 - "$progress_file" "$state" "$message" "$scanned" "$infected" "$errors" "$total" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
state, message = sys.argv[2], sys.argv[3]
scanned, infected, errors, total = (int(x) for x in sys.argv[4:8])
data = {}
if path.is_file():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
data.update(
    {
        "active": False,
        "state": state,
        "message": message,
        "scanned_files": scanned,
        "infected": infected,
        "errors": errors,
        "total_files": total,
        "percent": 100 if total and scanned >= total else data.get("percent", 0),
        "current_file": None,
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
)
path.write_text(json.dumps(data) + "\n", encoding="utf-8")
PY
}

minipc_clamdscan_flush_batch() {
  local quarantine="$1"
  local tmp="$2"
  local batch_tmp
  batch_tmp="$(mktemp)"
  printf '%s\0' "${@:3}" | xargs -0 -r clamdscan --multiscan --move="$quarantine" 2>&1 | tee -a "$tmp" >"$batch_tmp"
  local batch_rc="${PIPESTATUS[0]}"
  local ok found err
  ok="$(grep -cE ': OK$' "$batch_tmp" 2>/dev/null || true)"
  found="$(grep -cE ': FOUND$' "$batch_tmp" 2>/dev/null || true)"
  err="$(grep -cE ' ERROR$|Access denied\. ERROR$' "$batch_tmp" 2>/dev/null || true)"
  rm -f "$batch_tmp"
  MINIPC_BATCH_SCANNED=$((ok + found + err))
  MINIPC_BATCH_INFECTED=$found
  MINIPC_BATCH_ERRORS=$err
  MINIPC_BATCH_RC=$batch_rc
}

minipc_clamdscan_run() {
  local target="$1"
  local quarantine="$2"
  local tmp="$3"
  local progress="${4:-}"

  if [ -d "$target" ] && [ -n "$progress" ]; then
    minipc_clamdscan_run_tree "$target" "$quarantine" "$tmp" "$progress" "${5:-scan}"
    return $?
  fi

  if [ -d "$target" ]; then
    find "$target" -xdev \( -type f -o -type l \) -print0 |
      xargs -0 -r -n 32 clamdscan --multiscan --move="$quarantine" 2>&1 | tee "$tmp"
    return "${PIPESTATUS[1]}"
  fi

  clamdscan --move="$quarantine" "$target" 2>&1 | tee "$tmp"
  return "${PIPESTATUS[0]}"
}

minipc_clamdscan_run_tree() {
  local target="$1"
  local quarantine="$2"
  local tmp="$3"
  local progress="$4"
  local scope="${5:-scan}"

  : >"$tmp"
  minipc_clam_progress_write "$progress" "$(
    python3 - "$scope" "$target" <<'PY'
import json, sys
scope, target = sys.argv[1:3]
print(json.dumps({
    "active": True,
    "state": "counting",
    "scope": scope,
    "target": target,
    "total_files": 0,
    "scanned_files": 0,
    "infected": 0,
    "errors": 0,
    "message": "Counting files…",
    "current_file": None,
}))
PY
  )"

  local total
  total="$(find "$target" -xdev \( -type f -o -type l \) | wc -l | tr -d ' ')"
  total="${total:-0}"

  local scanned=0 infected=0 errors=0
  local -a batch=()
  local batch_size=32
  local file

  minipc_clam_progress_write "$progress" "$(
    python3 - "$scope" "$target" "$total" <<'PY'
import json, sys
scope, target, total = sys.argv[1:4]
print(json.dumps({
    "active": True,
    "state": "scanning",
    "scope": scope,
    "target": target,
    "total_files": int(total),
    "scanned_files": 0,
    "infected": 0,
    "errors": 0,
    "message": "Scanning…",
    "current_file": None,
}))
PY
  )"

  while IFS= read -r -d '' file; do
    batch+=("$file")
    if [ "${#batch[@]}" -ge "$batch_size" ]; then
      minipc_clamdscan_flush_batch "$quarantine" "$tmp" "${batch[@]}"
      scanned=$((scanned + MINIPC_BATCH_SCANNED))
      infected=$((infected + MINIPC_BATCH_INFECTED))
      errors=$((errors + MINIPC_BATCH_ERRORS))
      batch=()
      local base
      base="$(basename "$file")"
      minipc_clam_progress_write "$progress" "$(
        python3 - "$scope" "$target" "$total" "$scanned" "$infected" "$errors" "$base" <<'PY'
import json, sys
scope, target, total, scanned, infected, errors, current = sys.argv[1:8]
print(json.dumps({
    "active": True,
    "state": "scanning",
    "scope": scope,
    "target": target,
    "total_files": int(total),
    "scanned_files": int(scanned),
    "infected": int(infected),
    "errors": int(errors),
    "message": "Scanning…",
    "current_file": current,
}))
PY
      )"
    fi
  done < <(find "$target" -xdev \( -type f -o -type l \) -print0)

  if [ "${#batch[@]}" -gt 0 ]; then
    minipc_clamdscan_flush_batch "$quarantine" "$tmp" "${batch[@]}"
    scanned=$((scanned + MINIPC_BATCH_SCANNED))
    infected=$((infected + MINIPC_BATCH_INFECTED))
    errors=$((errors + MINIPC_BATCH_ERRORS))
  fi

  if [ "$total" -eq 0 ] && [ "$scanned" -eq 0 ]; then
    return 2
  fi
  if [ "$errors" -gt 0 ]; then
    return 2
  fi
  if [ "$infected" -gt 0 ]; then
    return 1
  fi
  return 0
}

# Sets MINIPC_CLAM_INFECTED, MINIPC_CLAM_ERRORS, MINIPC_CLAM_SCANNED from clamdscan output.
minipc_clamdscan_parse_summary() {
  local tmp="$1"
  MINIPC_CLAM_INFECTED=0
  MINIPC_CLAM_ERRORS=0
  MINIPC_CLAM_SCANNED=0
  if grep -q 'Infected files:' "$tmp"; then
    MINIPC_CLAM_INFECTED="$(grep 'Infected files:' "$tmp" | tail -1 | awk '{print $3}')"
  fi
  if grep -q 'Total errors:' "$tmp"; then
    MINIPC_CLAM_ERRORS="$(grep 'Total errors:' "$tmp" | tail -1 | awk '{print $3}')"
  fi
  if grep -q 'Scanned files:' "$tmp"; then
    MINIPC_CLAM_SCANNED="$(grep 'Scanned files:' "$tmp" | tail -1 | awk '{print $3}')"
  fi
  local per_file_ok per_file_found per_file_err
  per_file_ok="$(grep -cE ': OK$' "$tmp" 2>/dev/null || true)"
  per_file_found="$(grep -cE ': FOUND$' "$tmp" 2>/dev/null || true)"
  per_file_err="$(grep -cE ' ERROR$|Access denied\. ERROR$' "$tmp" 2>/dev/null || true)"
  if [ "$MINIPC_CLAM_SCANNED" -eq 0 ]; then
    MINIPC_CLAM_SCANNED=$((per_file_ok + per_file_found + per_file_err))
  fi
  if [ "$MINIPC_CLAM_INFECTED" -eq 0 ] && [ "$per_file_found" -gt 0 ]; then
    MINIPC_CLAM_INFECTED="$per_file_found"
  fi
  if [ "$MINIPC_CLAM_ERRORS" -eq 0 ] && [ "$per_file_err" -gt 0 ]; then
    MINIPC_CLAM_ERRORS="$per_file_err"
  fi
  MINIPC_CLAM_INFECTED="${MINIPC_CLAM_INFECTED:-0}"
  MINIPC_CLAM_ERRORS="${MINIPC_CLAM_ERRORS:-0}"
  MINIPC_CLAM_SCANNED="${MINIPC_CLAM_SCANNED:-0}"
}

# Echo human-readable result lines. Exit status: 0 clean, 1 infected, 2 error.
minipc_clamdscan_finish() {
  local tmp="$1"
  local scan_rc="$2"
  minipc_clamdscan_parse_summary "$tmp"

  if grep -qi 'permission denied' "$tmp"; then
    echo "ERROR: ClamAV cannot read files (permission denied). Add user clamav to group storage-apps and restart clamav-daemon."
    return 2
  fi
  if [ "$MINIPC_CLAM_ERRORS" -gt 0 ]; then
    echo "Scan errors: $MINIPC_CLAM_ERRORS (see summary above)"
    return 2
  fi
  if [ "$scan_rc" -eq 1 ] || [ "$MINIPC_CLAM_INFECTED" -gt 0 ]; then
    echo "INFECTED: see scan summary above (infected files moved to quarantine)"
    return 1
  fi
  if [ "$scan_rc" -ge 2 ] && [ "$MINIPC_CLAM_INFECTED" -eq 0 ]; then
    echo "Scan error (clamdscan exit $scan_rc)"
    return 2
  fi
  if [ "$MINIPC_CLAM_SCANNED" -eq 0 ]; then
    echo "WARNING: 0 files scanned — empty path or clamdscan skipped files"
    return 2
  fi
  echo "OK: clean ($MINIPC_CLAM_SCANNED files scanned)"
  return 0
}
