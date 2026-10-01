#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$EUID" == 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
test -f /opt/pastoral/dev/current/scripts/publish-health-report.py
cat > /etc/systemd/system/pastoral-health-report.service <<'UNIT'
[Unit]
Description=Pastoral development host and container health snapshot
After=network-online.target

[Service]
Type=oneshot
User=pastoral-runner
Group=pastoral-runner
ExecStart=/usr/bin/python3 /opt/pastoral/dev/current/scripts/publish-health-report.py
TimeoutStartSec=180
UMask=0077
UNIT
cat > /etc/systemd/system/pastoral-health-report.timer <<'UNIT'
[Unit]
Description=Refresh Pastoral development health snapshot

[Timer]
OnBootSec=30s
OnUnitInactiveSec=30s
AccuracySec=5s
Unit=pastoral-health-report.service

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now pastoral-health-report.timer
systemctl start pastoral-health-report.service
