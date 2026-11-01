# RAID storage, Samba, torrents, ClamAV

Dashboard pages:

- **RAID storage** (`/storage`) — [http://192.168.1.30:8080/storage](http://192.168.1.30:8080/storage)
- **Torrents** (`/torrents`) — [http://192.168.1.30:8080/torrents](http://192.168.1.30:8080/torrents)

If the **dashboard** shows a storage alert (read-only or degraded RAID), fix the array before using torrents or Samba. Boot uses `minipc-ensure-storage.sh`, which re-assembles `md0` by UUID from `/etc/mdadm/mdadm.conf` if the mirror was left in a **broken** state after disk reorder.

## One-time install (mini-PC)

```bash
cd ~/mini-pc-monitor
bash scripts/install-storage-raid.sh    # if not already done
bash scripts/install-storage-stack.sh   # Samba, Transmission, ClamAV
bash scripts/install-dashboard-service.sh  # restart dashboard after pull
```

## Samba

- Share name: `storage`
- UNC: `//192.168.1.30/storage`
- Connect URL (QR on dashboard): `smb://192.168.1.30/storage` — **RAID storage** page shows a scannable PNG at `/storage/samba-qr.png`
- Users are created on the **RAID storage** page (Samba-only accounts, no SSH login).

## Torrents

- Client: `transmission-daemon.service` (toggle on **Services**)
- Completed files: `/mnt/storage/shared/Downloads` (visible on the Samba share as the **Downloads** folder)
- Incomplete data stays outside the share: `/mnt/storage/downloads/incomplete`
- Upload `.torrent` files or magnet links on the dashboard.
- RPC password: `/etc/mini-pc-monitor/transmission-rpc-password` (readable by `sylvester`).

## ClamAV

- `clamav-daemon.service` scans each completed torrent via `/usr/local/sbin/minipc-clamscan-download.sh`
- Log: `/mnt/storage/logs/clamav-scan.log`
- AppArmor must allow the hook: `scripts/apparmor-transmission-daemon-local` → `/etc/apparmor.d/local/transmission-daemon` (re-run `install-storage-stack.sh` if scans never log)
- Manual scans from the dashboard use `/usr/local/sbin/minipc-clamscan-admin` (`downloads` or `shared`); install via `install-storage-stack.sh` (sudoers in `minipc-monitor-sudoers`)
- `clamd` reads files as user `clamav` — member of `storage-apps`, and AppArmor local rule `apparmor-clamd-local` allows read under `/mnt/storage`
- Directory scans use `find` + `clamdscan` (`clamdscan` alone does **not** recurse into folders). Large libraries take a long time; the log shows `OK: clean (N files scanned)` when done
- Ubuntu’s default `MaxFileSize 25M` skips most video files instantly — `install-storage-stack.sh` raises this to **4096M** so torrents are actually read
- Infected files are moved to `/mnt/storage/quarantine`

## Sudo

`scripts/minipc-monitor-sudoers` is installed to `/etc/sudoers.d/mini-pc-monitor-storage` by the stack installer (Samba admin + service toggles).
