# Operação da infraestrutura

## Princípios

- Todas as imagens usam versões explícitas; `latest` é proibido.
- Atualizações são planejadas e manuais; Watchtower não é utilizado.
- PostgreSQL, Redis, Prometheus, Loki e Alertmanager não publicam portas no host.
- O Grafana é vinculado somente ao IP configurado em `GRAFANA_BIND_ADDRESS`.
- Secrets permanecem fora do Git em `/opt/pastoral/secrets`.
- Logs técnicos seguem `stdout`/`stderr`; auditoria de negócio permanece no PostgreSQL.

## Inicialização

1. Copie `.env.example` para `.env` e ajuste imagens, IP LAN e e-mail.
2. Execute `sudo ./scripts/init-secrets.sh /opt/pastoral/secrets`.
3. Preencha `tailscale_auth_key` e `smtp_password` sem quebra de linha adicional.
4. Prepare o HDD em `/mnt/pastoral-backup/postgres` para o UID `70`.
5. Execute `./scripts/validate.sh`.
6. Execute `docker compose pull` e `docker compose build redis postgres-backup`.
7. Execute `docker compose up -d` e acompanhe `docker compose ps`.

O auth key do Tailscale é usado somente para registrar o nó. A configuração do
Funnel criada com `--bg` persiste no volume `tailscale-state` e volta após
reinicializações.

## Verificações após implantação

```bash
docker compose ps
docker compose logs --since=10m backend
docker compose logs --since=10m tailscale
docker exec pastoral-tailscale tailscale funnel status
curl --fail http://127.0.0.1:3001/api/health
```

Valide externamente a URL `https://<hostname>.<tailnet>.ts.net/` e uma rota
`/api/*`. `/metrics`, `/health/*` e os bancos não devem estar publicamente
acessíveis.

## Backup e restauração

O container `pastoral-postgres-backup` cria imediatamente um dump customizado e
comprimido e repete o processo a cada 24 horas. Os arquivos temporários usam o
sufixo `.tmp` e só são promovidos após conclusão do `pg_dump`.

Retenção:

| Classe | Quantidade |
|---|---:|
| Diários | 7 |
| Semanais | 4 |
| Mensais | 12 |

Para restaurar:

1. coloque o sistema em manutenção e interrompa o backend;
2. selecione e valide o dump desejado com `pg_restore --list`;
3. crie um banco vazio ou recrie o banco de destino;
4. execute a restauração;
5. suba o backend e valide `/health/ready` e fluxos essenciais.

Exemplo controlado:

```bash
docker compose stop backend
docker exec pastoral-postgres dropdb --username pastoral --if-exists pastoral_restore
docker exec pastoral-postgres createdb --username pastoral pastoral_restore
docker exec -i pastoral-postgres pg_restore \
  --username pastoral \
  --dbname pastoral_restore \
  --clean \
  --if-exists \
  < /mnt/pastoral-backup/postgres/daily/ARQUIVO.dump
```

Faça o teste de restauração periodicamente. A existência do arquivo não comprova
sozinha que o backup é restaurável. Metas: RPO de 24 horas e RTO de 4 horas.

## Atualizações

1. revise release notes e vulnerabilidades;
2. altere somente a versão necessária;
3. execute a CI e teste em ambiente controlado;
4. gere backup antes da atualização de componentes com estado;
5. aplique `docker compose pull` e `docker compose up -d`;
6. confirme healthchecks, métricas, logs e alertas;
7. mantenha documentado o caminho de rollback.

Nunca execute atualização automática de imagens em produção.

## Observabilidade

- Prometheus e Loki mantêm 7 dias de dados.
- Alloy coleta logs dos containers pelo socket Docker.
- `correlationId` é enviado ao Loki como metadado estruturado, não como label.
- O Alertmanager lê a senha SMTP diretamente de `/run/secrets/smtp_password`.
- O `AUDIT_LOG` no PostgreSQL não deve ser substituído por logs técnicos.
