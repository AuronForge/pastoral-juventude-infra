#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$EUID" == 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
desktop_user="${1:?Desktop user}"
[[ "$desktop_user" =~ ^[a-z_][a-z0-9_-]*$ ]]
desktop_home="$(getent passwd "$desktop_user" | cut -d: -f6)"
[[ "$desktop_home" == "/home/$desktop_user" ]]
command -v setfacl >/dev/null
install -d -m 0755 /usr/local/libexec
cat > /usr/local/libexec/pastoral-desktop-access <<EOF
#!/usr/bin/env bash
set -euo pipefail
for directory in "$desktop_home" "$desktop_home/.docker" "$desktop_home/.docker/desktop"; do
  [[ -d "\$directory" && ! -L "\$directory" ]] || exit 1
  getfacl -cp "\$directory" | grep -qx 'user:pastoral-runner:--x' || setfacl -m u:pastoral-runner:--x "\$directory"
done
socket="$desktop_home/.docker/desktop/docker.sock"
if [[ -S "\$socket" && ! -L "\$socket" ]]; then
  getfacl -cp "\$socket" | grep -qx 'user:pastoral-runner:rw-' || setfacl -m u:pastoral-runner:rw- "\$socket"
fi
EOF
chmod 0755 /usr/local/libexec/pastoral-desktop-access
cat > /etc/systemd/system/pastoral-desktop-access.service <<EOF
[Unit]
Description=Grant deployment runner access to Docker Desktop socket
[Service]
Type=oneshot
ExecStart=/usr/local/libexec/pastoral-desktop-access
EOF
cat > /etc/systemd/system/pastoral-desktop-access.path <<EOF
[Unit]
Description=Watch Docker Desktop socket recreation
[Path]
PathChanged=$desktop_home/.docker/desktop
Unit=pastoral-desktop-access.service
[Install]
WantedBy=multi-user.target
EOF
# The runner already controls Docker, and must stream the secrets to the VM.
setfacl -m u:pastoral-runner:r /opt/pastoral/dev/secrets/postgres_password /opt/pastoral/dev/secrets/redis_password /opt/pastoral/dev/secrets/jwt_private_key.pem /opt/pastoral/dev/secrets/jwt_public_key.pem
systemctl daemon-reload
systemctl enable --now pastoral-desktop-access.path
systemctl start pastoral-desktop-access.service
