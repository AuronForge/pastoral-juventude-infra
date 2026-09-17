FROM redis:8.6.6-alpine

COPY docker/redis/entrypoint.sh /usr/local/bin/pastoral-redis-entrypoint
RUN chmod 0555 /usr/local/bin/pastoral-redis-entrypoint

ENTRYPOINT ["/usr/local/bin/pastoral-redis-entrypoint"]
