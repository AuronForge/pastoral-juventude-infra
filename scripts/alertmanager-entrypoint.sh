#!/bin/sh
set -eu

for variable in ALERT_SMTP_SMARTHOST ALERT_SMTP_FROM ALERT_SMTP_USERNAME ALERT_EMAIL_TO; do
  eval "value=\${$variable:-}"
  if [ -z "$value" ]; then
    echo "A variável $variable é obrigatória." >&2
    exit 1
  fi
done

yaml_quote() {
  printf "%s" "$1" | sed "s/'/''/g"
}

smtp_smarthost="$(yaml_quote "$ALERT_SMTP_SMARTHOST")"
smtp_from="$(yaml_quote "$ALERT_SMTP_FROM")"
smtp_username="$(yaml_quote "$ALERT_SMTP_USERNAME")"
email_to="$(yaml_quote "$ALERT_EMAIL_TO")"

cat > /tmp/alertmanager.yml <<EOF
global:
  resolve_timeout: 5m
  smtp_smarthost: '$smtp_smarthost'
  smtp_from: '$smtp_from'
  smtp_auth_username: '$smtp_username'
  smtp_auth_password_file: /run/secrets/smtp_password
  smtp_require_tls: true

route:
  receiver: email-operacao
  group_by: [alertname, severity]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: email-operacao
    email_configs:
      - to: '$email_to'
        send_resolved: true
EOF

/bin/amtool check-config /tmp/alertmanager.yml
exec /bin/alertmanager \
  --config.file=/tmp/alertmanager.yml \
  --storage.path=/alertmanager
