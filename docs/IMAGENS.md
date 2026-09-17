# Imagens da V1

Versões pinadas em 17/09/2026. Atualizações exigem revisão manual e Pull Request.

| Componente | Imagem/tag |
|---|---|
| Tailscale | `tailscale/tailscale:v1.102.4` |
| Traefik | `traefik:v3.7.13` |
| PostgreSQL | `postgres:17.11-alpine` |
| Redis | `redis:8.6.6-alpine` |
| Grafana | `grafana/grafana:13.2.2` |
| Prometheus | `prom/prometheus:v3.14.0` |
| Loki | `grafana/loki:3.7.7` |
| Alloy | `grafana/alloy:v1.19.2` |
| Alertmanager | `prom/alertmanager:v0.34.0` |
| Node Exporter | `prom/node-exporter:v1.12.1` |
| cAdvisor | `ghcr.io/google/cadvisor:v0.60.5` |
| PostgreSQL Exporter | `prometheuscommunity/postgres-exporter:v0.20.1` |
| Redis Exporter | `oliver006/redis_exporter:v1.91.1` |

Frontend e backend usam as versões SemVer informadas no `.env`; os defaults do
bootstrap são `0.1.0`. Nenhum serviço usa a tag `latest`.
