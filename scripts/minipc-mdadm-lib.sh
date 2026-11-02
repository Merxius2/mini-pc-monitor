# Shared mdadm helpers (sourced by minipc-ensure-storage.sh and minipc-mdadm-sync-conf.sh).

minipc_md_array_uuid() {
  local conf="${1:-/etc/mdadm/mdadm.conf}"
  if [ -f "$conf" ]; then
    grep -oE 'UUID=[0-9a-f:]+' "$conf" 2>/dev/null | head -1 | cut -d= -f2
  fi
}

minipc_md_is_partition_symlink() {
  case "$1" in
    *-part*) return 0 ;;
    *) return 1 ;;
  esac
}

# List stable by-id paths for whole-disk members of the array UUID (never /dev/sdX).
# One symlink per physical disk (ata-* preferred over wwn-* for the same block device).
minipc_md_member_by_id() {
  local uuid="$1"
  local d canonical pattern
  declare -A seen_canonical=()
  local -a patterns=(
    '/dev/disk/by-id/ata-*'
    '/dev/disk/by-id/nvme-*'
    '/dev/disk/by-id/scsi-*'
    '/dev/disk/by-id/wwn-*'
  )
  for pattern in "${patterns[@]}"; do
    for d in $pattern; do
      [ -e "$d" ] || continue
      if minipc_md_is_partition_symlink "$d"; then
        continue
      fi
      canonical="$(readlink -f "$d")"
      if [ -n "${seen_canonical[$canonical]+x}" ]; then
        continue
      fi
      if mdadm --examine "$d" 2>/dev/null | grep -qF "Array UUID : $uuid"; then
        seen_canonical[$canonical]=1
        echo "$d"
      fi
    done
  done | sort -u
}

minipc_md_metadata_for_member() {
  local member="$1"
  mdadm --examine "$member" 2>/dev/null | awk -F': ' '/^[\t ]*Metadata Version/ { print $2; exit }'
}

minipc_md_write_conf() {
  local md_dev="$1"
  local uuid="$2"
  shift 2
  local members=("$@")
  local conf="/etc/mdadm/mdadm.conf"
  local metadata="1.2"
  if [ "${#members[@]}" -gt 0 ]; then
    local detected
    detected="$(minipc_md_metadata_for_member "${members[0]}")"
    if [ -n "$detected" ]; then
      metadata="$detected"
    fi
  fi
  MD_DEV="$md_dev" MD_UUID="$uuid" MD_METADATA="$metadata" MD_DEVICES="${members[*]}" \
    MDADM_CONF="$conf" python3 <<'PY'
import os
import re
from pathlib import Path

md_dev = os.environ["MD_DEV"]
uuid = os.environ["MD_UUID"]
metadata = os.environ["MD_METADATA"]
devices = [d for d in os.environ.get("MD_DEVICES", "").split() if d]
conf_path = Path(os.environ["MDADM_CONF"])
device_csv = ",".join(devices)

device_line = (
    "DEVICE /dev/disk/by-id/ata-* /dev/disk/by-id/nvme-* "
    "/dev/disk/by-id/scsi-* /dev/disk/by-id/wwn-*"
)

if conf_path.is_file():
    lines = conf_path.read_text(encoding="utf-8").splitlines()
else:
    lines = []

out: list[str] = []
has_device = False
replaced = False
skip = False
uuid_re = re.compile(re.escape(uuid))

for line in lines:
    if skip:
        if line.startswith(" ") or line.startswith("\t"):
            continue
        skip = False
    stripped = line.strip()
    if stripped.startswith("INCLUDE ") and "mdadm.d" in stripped:
        continue
    if stripped.startswith("DEVICE ") and "disk/by-id" in stripped:
        has_device = True
    if line.startswith("ARRAY ") and uuid_re.search(line):
        out.append(f"ARRAY {md_dev} metadata={metadata} UUID={uuid}")
        if device_csv:
            out.append(f"    devices={device_csv}")
        replaced = True
        skip = True
        continue
    out.append(line)

if not has_device:
    out.insert(0, device_line)
if not replaced:
    out.append(f"ARRAY {md_dev} metadata={metadata} UUID={uuid}")
    if device_csv:
        out.append(f"    devices={device_csv}")

conf_path.parent.mkdir(parents=True, exist_ok=True)
conf_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY
}
