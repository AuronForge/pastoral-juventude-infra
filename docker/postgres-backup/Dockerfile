FROM postgres:17.11-alpine

COPY docker/postgres-backup/backup.sh /usr/local/bin/pastoral-postgres-backup
RUN chmod 0555 /usr/local/bin/pastoral-postgres-backup

USER postgres

HEALTHCHECK --interval=30m --timeout=5s --start-period=5m --retries=2 \
  CMD find /tmp/last-backup-success -mmin -1560 -print -quit | grep -q .

ENTRYPOINT ["/usr/local/bin/pastoral-postgres-backup"]
