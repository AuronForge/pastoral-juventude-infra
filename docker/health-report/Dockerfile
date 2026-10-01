FROM node:24.8.0-bookworm-slim
WORKDIR /app
COPY --chmod=0444 docker/health-report/server.mjs ./server.mjs
USER 1001:1001
EXPOSE 8080
CMD ["node", "server.mjs"]
