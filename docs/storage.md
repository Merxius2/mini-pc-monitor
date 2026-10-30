# RAID storage, Samba, torrents, ClamAV

Dashboard page: **RAID storage** (`/storage`) on [http://192.168.1.30:8080/storage](http://192.168.1.30:8080/storage)

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
- Completed files: `/mnt/storage/downloads/complete`
- Upload `.torrent` files or magnet links on the dashboard.
- RPC password: `/etc/mini-pc-monitor/transmission-rpc-password` (readable by `sylvester`).

## ClamAV

- `clamav-daemon.service` scans each completed torrent via `/usr/local/sbin/minipc-clamscan-download.sh`
- Log: `/mnt/storage/logs/clamav-scan.log`
- Infected files are moved to `/mnt/storage/quarantine`

## Sudo

`scripts/minipc-monitor-sudoers` is installed to `/etc/sudoers.d/mini-pc-monitor-storage` by the stack installer (Samba admin + service toggles).
