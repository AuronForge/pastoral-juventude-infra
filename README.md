# Pastoral da Juventude — Infraestrutura

Infraestrutura Docker Compose do MVP da Pastoral da Juventude.

## Visão geral

- publicação HTTPS por Tailscale Funnel;
- Traefik como proxy reverso interno;
- frontend e backend sem portas públicas diretas;
- PostgreSQL e Redis isolados na rede `pastoral-data`;
- Grafana limitado ao endereço LAN configurado;
- métricas com Prometheus e exporters;
- logs com Alloy, Loki e Grafana;
- alertas por e-mail com Alertmanager;
- backup diário comprimido do PostgreSQL no HDD.

Tempo e OpenTelemetry Collector não fazem parte da V1.

## Pré-requisitos

- Ubuntu com Docker Engine e Docker Compose v2;
- Tailscale Funnel habilitado na tailnet;
- imagens versionadas de frontend e backend publicadas no GHCR;
- diretório `/opt/pastoral/secrets` preparado;
- HDD montado em `/mnt/pastoral-backup/postgres`.

## Preparação

```bash
cp .env.example .env
sudo ./scripts/init-secrets.sh /opt/pastoral/secrets
sudo mkdir -p /mnt/pastoral-backup/postgres
sudo chown -R 70:70 /mnt/pastoral-backup/postgres
```

Preencha manualmente `tailscale_auth_key` e `smtp_password`. Ajuste também os
campos `ALERT_*` e, para acesso ao Grafana pela LAN, defina
`GRAFANA_BIND_ADDRESS` com o IP LAN do host. O valor padrão `127.0.0.1` restringe
o Grafana ao próprio host.

## Validação e execução

```bash
./scripts/validate.sh
docker compose pull
docker compose build redis postgres-backup
docker compose up -d
docker compose ps
```

O Tailscale configura persistentemente o Funnel HTTPS na porta 443 para o
Traefik em `127.0.0.1:80`. Não é necessário abrir as portas 80/443 no roteador.

## Rotas

- `/` → frontend;
- `/api/*` → backend;
- métricas e healthchecks permanecem somente nas redes internas;
- Grafana → `http://<IP-LAN>:3001` quando o bind LAN for configurado.

## Backups

Os dumps usam formato customizado comprimido do `pg_dump` e são organizados em
`daily`, `weekly` e `monthly`. A retenção automática mantém os 7 últimos diários,
4 últimos semanais e 12 últimos mensais. RPO alvo: 24 horas. RTO alvo: 4 horas.

Consulte [docs/OPERACAO.md](docs/OPERACAO.md) para restauração, atualizações e
procedimentos operacionais.
