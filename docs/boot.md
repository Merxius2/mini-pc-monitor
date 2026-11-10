# Boot process review (Mini-PC PN50)

This documents how the machine should boot, what broke in Nov 2026, and how the repo prevents repeats.

## Expected boot timeline

| Phase | What runs | Blocks login? |
|-------|-----------|---------------|
| UEFI | Internal **NVMe** → GRUB → kernel | Yes (firmware) |
| initramfs | Root on NVMe; **USB RAID not required** | Yes |
| `local-fs.target` | `/` on NVMe; `/mnt/storage` has **`noauto,nofail`** | No wait on RAID |
| `multi-user.target` | Docker, NetworkManager, enabled units | Dashboard can start |
| `minipc-storage.service` | Assemble **md0**, mount `/mnt/storage` | **No** (weak `WantedBy`; after multi-user) |
| `minipc-restore-services.service` | Apply saved **Services** page states | No |
| `mini-pc-monitor.service` | Dashboard `:8080` | No |

**Suspend/resume:** `minipc-storage` sleep hook runs `minipc-ensure-storage.sh` with a longer USB wait (45s).

**Nightly schedule (21:00–09:00):** `minipc-nightly-off` uses **`rtcwake -m mem`** (suspend to RAM + RTC wake). If the box is on but unreachable after wake, try a reboot; use Management to disable the timer for 24/7 uptime.

## Incidents we hit (and fixes)

### 1. Stuck at `minipc-storage` / emergency mode

**Cause:** Service used to run **before** `local-fs.target`, `mount` could hang with no timeout, fstab had no `nofail`, enclosure unplugged.

**Fix (repo):** Post-boot only (`After=multi-user.target`), **`noauto,nofail`** on `/mnt/storage`, early exit when no USB members, **20s** mount timeout, **`TimeoutStartSec=90`**, `local-fs` enable symlink removed.

### 2. Wrong UEFI boot device (USB enclosure)

**Cause:** Firmware tried to boot the RAID enclosure instead of NVMe.

**Mitigation:** OS is on NVMe only. In UEFI: put **internal SSD/NVMe first**; disable USB boot or keep enclosure **not** bootable. Storage mount is post-boot anyway.

### 3. `md127` / degraded `md0` with one disk

**Cause:** Kernel or slow USB assembled a **partial** array; script only managed **md0**.

**Fix:** `stop_foreign_md_arrays` before assemble; reassemble if mounted but **`[2/1]`**; dashboard **Repair RAID now**.

### 4. Long boot (~98s in `systemd-analyze blame`)

**Cause:** Old script waited **45s** for USB members on every boot (seen on 2026-11-07 15:27 boot).

**Fix:** Post-boot unit sets **`MINIPC_MEMBER_WAIT_MAX=12`**; resume keeps 45s.

### 5. Services wrong after reboot

**Cause:** `systemctl enable` restarted stopped services.

**Fix:** `service-desired-state.json`, snapshot on **Reboot now**, `minipc-restore-services.service` after storage.

## Install checklist (mini-PC)

Run after pulls that touch boot/storage:

```bash
cd ~/mini-pc-monitor
bash scripts/install-storage-raid.sh
bash scripts/install-service-state.sh
bash scripts/install-system-updates.sh   # when update helper changes
sudo systemctl restart mini-pc-monitor.service
```

## UEFI / hardware (manual, once)

1. **Boot order:** Windows Boot Manager / **Ubuntu on NVMe** first — not USB disks.
2. **USB RAID:** Data disk only; prefer **USB 3** port; same enclosure, port change is OK (`by-id` assembly).
3. After moving USB: if degraded, use **Repair RAID now** or one reboot.

## Diagnostics

```bash
systemd-analyze
systemd-analyze blame | head -20
systemd-analyze critical-chain minipc-storage.service
journalctl -u minipc-storage.service -b --no-pager
cat /proc/mdstat
findmnt /mnt/storage
efibootmgr -v          # boot order
```

Healthy storage:

- `md0 … [2/2] [UU]`
- `/mnt/storage` mounted
- `minipc-storage.service` **success** in under ~30s (with enclosure)

## Remaining risks (awareness)

| Risk | What happens | Action |
|------|----------------|--------|
| Enclosure unplugged at boot | No Samba/torrents; OS up in ~10s | Plug in + **Repair** or reboot |
| `minipc-storage` hits 90s timeout | Unit fails; restore still runs | Check USB power/cable; journals |
| Initramfs sees USB disks early | Rare partial `md127` | Fixed at post-boot; **Repair** |
| `NetworkManager-wait-online` ~5s | Slower HA/Docker chain | Optional: shorten NM wait (OS-wide) |
| Reboot not via dashboard | Last **Services** toggles still apply | Use **Reboot now** for full snapshot |

## Related docs

- [storage.md](storage.md) — RAID, Samba, install scripts  
- [mini-pc.md](mini-pc.md) — services, deploy, updates  
