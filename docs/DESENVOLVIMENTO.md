# Entrega contínua — ambiente de desenvolvimento

## Fluxo e escopo

`feature/*` → PR → CI → merge em `develop` → CI do merge → imagens GHCR
identificadas pelo SHA completo → dispatch na infraestrutura → validação da
origem → Ubuntu → backup → migrations → containers → healthchecks → smoke E2E.

Frontend e backend são entregues independentemente. O manifesto persistente
mantém a imagem do outro componente. O primeiro deploy exige imagens válidas
dos dois componentes e a imagem de migrations correspondente ao backend.
Não se usa `latest`. A promoção de `release` e `main` não está automatizada nesta
entrega. O login visual continua apenas no Storybook, sem rota de login na aplicação.

`compose.development.yaml` é independente do Compose existente: projeto
`pastoral-dev`, redes e volumes próprios. Sobe Traefik, frontend, backend,
PostgreSQL e Redis. Observabilidade completa, Funnel e backup diário do Compose
original não são iniciados por este workflow. Nesta etapa os backups são feitos
antes de cada deploy; o backup diário e a observabilidade de desenvolvimento
precisam de uma configuração específica antes de sua ativação.

## Docker Desktop no Ubuntu

Para visualizar a implantação no Docker Desktop, seguir
[DOCKER-DESKTOP.md](DOCKER-DESKTOP.md): inclui acesso persistente do runner,
seleção explícita do daemon, cópia dos volumes, backup, validação e retorno.
O Desktop usa VM e volumes diferentes do Engine. A migração não acontece
somente por merge nem por mudança de contexto do usuário.

## Preparar Ubuntu

Pré-requisitos: Docker Engine, Compose v2 com `up --wait`, Git, Bash, OpenSSL,
`flock`, pacote `acl` e saída HTTPS para GitHub, GHCR, Docker Hub e npm.
O deploy não requer Node ou Playwright instalados no host. Python 3 é usado para a evidência de recursos.

Crie um usuário exclusivo, por exemplo `pastoral-runner`, e prepare:

```bash
sudo install -d -o pastoral-runner -g pastoral-runner -m 0700 /opt/pastoral/dev
sudo apt-get install acl
sudo bash scripts/init-secrets.sh /opt/pastoral/dev/secrets
# O backend executa como UID 1001; o runner precisa atravessar o diretório.
sudo setfacl -m u:pastoral-runner:rx /opt/pastoral/dev/secrets
sudo setfacl -m u:1001:r /opt/pastoral/dev/secrets/postgres_password /opt/pastoral/dev/secrets/redis_password /opt/pastoral/dev/secrets/jwt_private_key.pem /opt/pastoral/dev/secrets/jwt_public_key.pem
sudo install -o pastoral-runner -g pastoral-runner -m 0600 .env.development.example /opt/pastoral/dev/development.env
```

Complete `development.env` com os SHAs das imagens já publicadas. Os valores são
lidos pelo Bash: use atribuições simples e aspas para valores que necessitem delas.
Não coloque comandos neste arquivo. Nunca versione os secrets ou esse arquivo.
Não reutilize credenciais nem volumes de produção. A inicialização não substitui
secrets existentes. Não gere nova senha para um volume PostgreSQL já inicializado.

O acesso inicial fica em `http://localhost:8080`. Para acessar pela LAN, defina
`DEV_BIND_ADDRESS` com o IP LAN do Ubuntu e `DEV_PUBLIC_URL` com a URL exata.
Se habilitar HTTPS posteriormente, configure `COOKIE_SECURE=true`.
Os bancos e rotas técnicas permanecem internos; `/api/*` e `/` passam pelo Traefik.

## Versionamento no Traefik

O gateway tem um router explícito `backend-api-v1`, com regra
`Path("/api/v1") || PathPrefix("/api/v1/")`, nos arquivos
`traefik/dynamic.development.yml` e `traefik/dynamic.yml`.
A versão faz parte do contrato de entrada do gateway e o caminho completo
é preservado até o backend; não há StripPrefix nem reescrita de versão.

Somente v1 está habilitada hoje. `/api`, `/api/v2/...`, `/api/v10/...`
e versões não declaradas retornam HTTP 404 do Traefik. O router do frontend
exclui `/api` e `/api/...`, impedindo que a SPA responda a uma API desconhecida.
`/api/v10` não corresponde a v1.

Para habilitar v2, implementar e testar primeiro o contrato no backend.
Adicionar depois um router `backend-api-v2` com regra
`Path("/api/v2") || PathPrefix("/api/v2/")`, prioridade e middlewares explícitos.
Ele pode apontar para o mesmo serviço se a API implementar ambas as versões,
ou para um serviço/container específico da v2. Não publicar uma rota v2 que
apenas entregue o contrato v1. Repetir o procedimento para cada versão aprovada.

A CI executa Traefik real com serviços HTTP de teste para verificar v1,
preservação de caminho/query, rejeição de versões ausentes e roteamento web.
Esse teste não substitui os testes dos contratos da API.
Após merge na infra, aguardar sua CI e solicitar um novo deploy de desenvolvimento
com o HEAD publicado de um componente. Alterações somente na infra não são
disparadas pelos workflows de publicação de backend/frontend.

## Túnel público exclusivo da API e frontend no Vercel

A entrada `api-public` do Traefik escuta em 8082 dentro do container e é
publicada **somente em 127.0.0.1** no Ubuntu, pela variável
`DEV_API_TUNNEL_PORT` (padrão 8082). O router `backend-api-v1` aceita
`web` e `api-public`; o frontend aceita somente `web`.

Após o merge e uma nova implantação, no Ubuntu:

```bash
# Conferir que a API-only entrypoint não atende a SPA.
curl -i http://127.0.0.1:8082/
# Deve retornar HTTP 404.
cloudflared tunnel --url http://127.0.0.1:8082
```

Compartilhar a URL HTTPS gerada com o caminho completo `/api/v1/...`.
A raiz, rotas do frontend, healthchecks internos e versões não configuradas
retornam 404 nessa entrada. A exceção pública é o healthcheck descrito abaixo. O serviço HTTP da API permanece no backend:3000 dentro
do Docker. Não publicar diretamente a porta 3000.

Quick Tunnel fornece um hostname temporário sem domínio próprio. O processo
deve permanecer ativo; recriá-lo muda a URL. Isso atende desenvolvimento e
demonstrações, não configura um endereço estável de produção. Para uso contínuo,
preparar domínio e túnel nomeado. Não versionar URLs temporárias como destino
definitivo da aplicação.

O frontend público será hospedado no Vercel. O frontend Docker desta entrega
continua disponível para a suíte smoke interna e não é publicado pelo túnel
da API. Remover esse container exige adaptar separadamente o manifesto e E2E.

Para chamadas diretas do navegador à API, configurar `DEV_CORS_ORIGINS`
no arquivo do host com as origens exatas autorizadas, separadas por vírgula.
Exemplo: `http://localhost:5173,https://PROJETO.vercel.app`, substituindo o
placeholder pelo domínio real. Origem não inclui caminho nem barra final.
Não permitir indiscriminadamente todos os previews Vercel.

O Compose de desenvolvimento acrescenta automaticamente `http://traefik` às
origens configuradas: é a origem usada pelo navegador do E2E na rede Docker
interna. Isso também é necessário para a validação de Origin da renovação de
sessão, mesmo sem cookie. As origens públicas de `DEV_CORS_ORIGINS` (ou o
fallback `DEV_PUBLIC_URL`) são preservadas; não há wildcard.
Essa inclusão é exclusiva deste ambiente e não libera origens desconhecidas.

Se o smoke real mostrar “Não foi possível restaurar sua sessão” e a chamada
`POST /api/v1/autenticacao/renovar-token` retornar 403 em `http://traefik`,
verifique se a implantação usa esta configuração. Foi o bloqueio observado
na execução 37131928653; os testes controlados passaram porque simulam a API.
Após o merge, aguarde a CI da infra e inicie **uma nova execução** de
`Deploy development` em `develop`, com componente `frontend` e o SHA
publicado atual. O deploy aplica a configuração também ao backend.
Não é necessário editar o arquivo privado no Ubuntu nem resetar as contas.
A validação final continua sendo o smoke real do deploy.

O backend atual usa refresh cookie HttpOnly com SameSite=Lax. Para manter
as chamadas do navegador na mesma origem, a opção recomendada é um rewrite
do Vercel para a API externa, preservando `/api/v1/...`. O proxy do Vite é
somente para desenvolvimento e não é utilizado pelo build no Vercel.
Com destino HTTPS, configurar `COOKIE_SECURE=true` no host e executar novo
deploy. Validar login/cookies quando a integração funcional estiver disponível.
Chamadas diretas entre domínios diferentes exigem revisão específica de
SameSite, CSRF e comportamento de cookies do navegador; somente CORS não resolve.

Antes de configurar o rewrite definitivo, obter a URL atual do túnel e o
domínio do projeto Vercel. Nunca colocar tokens de autenticação em variáveis
`VITE_*`, pois elas são públicas no build.

## Healthcheck público da API

Na entrada exclusiva do túnel, `GET /api/v1/health` usa o router
`backend-public-health-v1`, prioridade 200, reescrita exata para
`/health/ready` e `Cache-Control: no-store`. O caminho externo permanece
versionado. A resposta saudável é HTTP 200:

```json
{"status":"ok","checks":{"database":"up","cache":"up"}}
```

Quando PostgreSQL ou Redis falha, retorna HTTP 503 com `status: error` e
o componente em `down`. O serviço `backend-health` não usa o healthcheck
do pool da aplicação: permite receber o diagnóstico mesmo quando o pool
`backend` foi removido pelo Traefik. As outras rotas continuam usando
o pool com readiness. Backend inacessível pode gerar 502; o endpoint
não pode diagnosticar dependências se o próprio backend não responde.

```bash
curl -i http://127.0.0.1:8082/api/v1/health
curl -i https://URL-ATUAL.trycloudflare.com/api/v1/health
```

A resposta pública não contém credenciais, mensagens de exceção ou métricas
de recursos. `/health/live`, `/health/ready` e `/metrics` permanecem internos.
O liveness interno mantém o contrato mínimo de processo ativo. A CI usa
Traefik real para testar a reescrita, HTTP 503, ausência de cache e isolamento.

## Diagnóstico de recursos no Ubuntu

Executar no **host Ubuntu**, com Python 3 e acesso ao Docker local, após
o deploy da revisão que inclui o script:

```bash
sudo -u pastoral-runner python3 /opt/pastoral/dev/current/scripts/health-development.py
```

O script é somente de leitura, identifica containers pelas labels Compose
do projeto `pastoral-dev` e produz JSON sem carregar arquivos de secrets
ou emitir o conteúdo de `docker inspect`. Não requer variáveis de imagem
nem publica portas. Não executar em um container ou contra um Docker remoto,
pois as métricas de `/proc` seriam de outra máquina.

| Campo | Significado |
| --- | --- |
| `readiness` | HTTP e corpo do backend, incluindo estado do PostgreSQL e Redis |
| `host.memory` | RAM total, disponível, usada (total menos disponível), percentual e swap, em bytes |
| `host.loadAverage` / `cpuCount` | Carga média em 1, 5 e 15 minutos e CPUs lógicas; carga não é percentual de CPU |
| `host.disk` | Espaço do filesystem que contém /opt/pastoral/dev, em bytes; não é tamanho do banco |
| `host.uptimeSeconds` | Tempo desde o boot do Ubuntu |
| `containers.postgres.stats.MemUsage` | Memória de todo o container PostgreSQL, incluindo seus processos |
| `containers.*.stats` | CPU, memória, processos, I/O de bloco e rede, no formato do Docker CLI |
| `containers.*.configuredMemoryLimitBytes` | Limite explícito do container; zero significa sem limite configurado |
| `containers.*.health` / `restartCount` / `oomKilled` | Healthcheck Docker, reinícios e estado OOM da execução atual |
| `errors` | Coletas indisponíveis; os dados obtidos permanecem no relatório |

No Linux, `docker stats` desconta cache recuperável da memória apresentada.
`MemUsage` e `MemPerc` seguem a formatação e o denominador do Docker; um
limite exibido pelo Docker pode refletir o host quando não há limite explícito.
A memória de um container é diferente de seu heap ou da configuração
`shared_buffers` do PostgreSQL. Não somar RSS dos processos PostgreSQL,
pois regiões compartilhadas poderiam ser contadas repetidamente.

Código de saída 0 significa coleta completa, containers em execução e
readiness HTTP 200; 1 indica falha ou coleta parcial. Valores altos de memória,
CPU ou disco são apresentados para diagnóstico e não mudam sozinhos esse
estado: limiares/alertas de capacidade exigem observabilidade contínua.
`oomKilled` não é um histórico completo de OOMs e `restartCount` recomeça
ao recriar o container. Não há novo serviço de monitoramento nem alertas nesta
entrega. Os testes do coletor simulam Docker; validar também no Ubuntu real.

## Runner e permissões

Registre um runner Linux x64 com label `pastoral-dev`, como serviço sob o usuário
dedicado. O usuário precisa de acesso ao Docker; esse acesso permite controlar
o host, portanto o runner é exclusivo de implantação.

O repositório infra é público. Antes de registrar um runner com acesso ao host,
use um runner group restrito ao workflow
`AuronForge/pastoral-juventude-infra/.github/workflows/deploy-development.yml@refs/heads/develop`.
Se o plano do GitHub não oferecer restrição por workflow, não conecte um runner
com Docker do host a este repositório público: use uma infraestrutura privada de
deploy ou um executor isolado dedicado, revisando o fluxo antes de ativá-lo.
Uma label sozinha não impede outro workflow de selecionar o runner.

Crie o GitHub Environment `desenvolvimento` na infra e permita somente a branch
`develop`. Proteja `develop` com PR e CI obrigatórios; limite quem pode alterar
workflows e secrets. PRs, builds e testes de qualidade executam nos runners do
GitHub; somente a implantação validada usa o Ubuntu.

| Local            | Configuração                                    | Finalidade                                                   |
| ---------------- | ----------------------------------------------- | ------------------------------------------------------------ |
| Backend/frontend | variável `DEV_AUTO_DEPLOY=true`                 | Dispatch após publicação aprovada                            |
| Backend/frontend | secret `INFRA_DISPATCH_TOKEN`                   | Token com Actions: write somente na infra                    |
| Infra            | variável `DEV_DEPLOY_ENABLED=true`              | Habilitar a implantação após bootstrap                       |
| Infra            | secret `SOURCE_READ_TOKEN`, quando necessário   | Contents/Actions: read nos repositórios de origem privados   |
| Infra            | variável `DEV_GHCR_PRIVATE=true`, se necessário | Autenticar para baixar imagens privadas                      |
| Infra            | variável `GHCR_USER` e secret `GHCR_READ_TOKEN` | Usuário/token com read:packages, sem permissão de publicação |

## Seleção automática da revisão E2E

Cada deploy resolve o HEAD de `develop` do repositório E2E e exige uma execução
`CI` de evento `push`, nessa branch e nesse mesmo SHA, concluída com sucesso.
O SHA aprovado é fixado na saída `e2e_sha` da validação e usado no checkout;
novos merges durante a implantação não trocam os testes dessa execução.

Não é necessário criar ou atualizar `DEV_E2E_REF`. Uma variável antiga com esse
nome pode permanecer: o workflow não a utiliza. O acesso utiliza o mesmo
`SOURCE_READ_TOKEN` já usado para ler os repositórios privados; não exige novo
secret nem permissão de escrita.

Se a CI do HEAD E2E estiver pendente, falhar ou não existir, a validação interrompe
o deploy antes de acessar o Ubuntu. Não escolhe silenciosamente uma revisão
anterior. Aguarde a CI e inicie uma nova execução. Uma falha de leitura da API
também interrompe a validação. O SHA escolhido aparece no checkout do job.

Depois do merge desta automação, aguardar a CI da infra e iniciar uma nova execução
de `Deploy development` na branch `develop`, usando o SHA atual publicado do
componente. Reexecutar um job antigo mantém o workflow antigo. Esta alteração
não dispara um deploy nem altera os containers por si só.

## Ordem de bootstrap

1. Revisar e fazer merge dos PRs de backend, frontend, E2E e infra em `develop`.
2. Promover os novos workflows para a branch padrão por PR. `workflow_run` e
   `workflow_dispatch` dependem da existência do arquivo na branch padrão.
   Não promova essas mudanças com deploy de produção; esta entrega atua só em `develop`.
3. Manter `DEV_AUTO_DEPLOY` e `DEV_DEPLOY_ENABLED` desativados durante a preparação.
4. Executar push/merge em `develop` de backend e frontend e aguardar CI/publicação.
5. Preencher o arquivo do host com as duas imagens e migrations desse backend.
6. Configurar runner, environment e tokens; aguardar a CI de `develop` do E2E.
7. Habilitar `DEV_DEPLOY_ENABLED`; executar `Deploy development` na branch `develop`
   informando componente e SHA publicado. A CI da infra nesse SHA também deve ter passado.
8. Conferir containers, frontend pela URL configurada, backup e artefatos E2E.
9. Habilitar `DEV_AUTO_DEPLOY` nos dois repositórios de aplicação.

O workflow recusa um SHA de aplicação que já não seja o HEAD da `develop`.
Se surgir um novo merge enquanto uma publicação aguarda, a entrega antiga falha
na validação e a publicação do novo HEAD deve iniciar uma nova implantação.

## Verificação e evidências

O deploy serializa execuções com concurrency do GitHub e `flock` no host. Cada
execução copia configurações e scripts para um diretório persistente; os volumes
bind não dependem do checkout temporário do runner. Aplica `prisma migrate deploy`
com uma imagem específica contendo schema, migrations e CLI.

A CI do backend testa o carregamento de Argon2/Prisma na imagem e constrói a
imagem de migrations. O deploy verifica `/health/ready` e executa o Playwright
em container na rede interna. A suíte atual cobre a página inicial, processo vivo
e dependências prontas; não comprova login ou outros fluxos ainda não implementados.

Relatórios Playwright/JUnit e manifesto de versões ficam em artefatos do GitHub
por 14 dias e em `/opt/pastoral/dev/reports`. Backup e release ficam em
`/opt/pastoral/dev/backups` e `/opt/pastoral/dev/releases`. Nesta primeira entrega
a limpeza desses diretórios é manual: acompanhe espaço em disco.
Dados para login não são criados pelo deploy; preparar usuários/seeds é uma etapa
separada. O reset de regressão atual só altera usuários que já existem.

## Falha e rollback

Falha em pull ou migration interrompe as próximas etapas. Depois de atualizar os
containers, falha em healthcheck/E2E pode deixar a versão candidata em execução.
O job fica vermelho, preserva o manifesto anterior e registra o diretório da
candidata. Não há rollback automático de banco ou aplicação.

`current-images.env` e o link `current` representam a última entrega validada;
`previous-images.env` preserva a entrega validada anterior. Após uma falha, use
`current-images.env` para recuperar as imagens. Após um deploy bem-sucedido que
precisa ser revertido, use `previous-images.env`.

Antes de reverter, verifique a compatibilidade das imagens antigas com o schema
atual. Se compatíveis, no host, como usuário do runner:

```bash
set -a
source /opt/pastoral/dev/development.env
# Em caso de falha da candidata; use previous-images.env para reverter um sucesso.
source /opt/pastoral/dev/current-images.env
set +a
docker compose --project-name pastoral-dev -f /opt/pastoral/dev/current/compose.development.yaml pull backend frontend
docker compose --project-name pastoral-dev -f /opt/pastoral/dev/current/compose.development.yaml up -d --wait backend frontend traefik
```

Reexecute healthchecks e E2E e registre as versões recuperadas no incidente.
O Prisma não desfaz migrations por esse procedimento. Restaurar um dump exige
manutenção, interrupção do backend, banco de destino controlado e validação;
consulte `OPERACAO.md`. Não execute `down -v` nem remova volumes para corrigir deploy.

## Redis unhealthy no primeiro deploy

O Redis inicia como usuário `redis`. A configuração gerada em
`/tmp/pastoral-redis.conf` contém a senha e deve ter modo `0600` e pertencer a
esse usuário antes de o entrypoint oficial reduzir os privilégios. Uma
configuração `root:root` com modo `0600` impede o processo de abrir o arquivo.

A CI sobe somente o Redis em um projeto isolado, verifica healthcheck,
autenticação obrigatória, proprietário/modo do arquivo, processo sem root e
reinício. Os volumes descartáveis desse teste são removidos; os volumes do host
de desenvolvimento são preservados.

Para diagnosticar no Ubuntu sem exibir os secrets:

```bash
sudo -u pastoral-runner docker logs --tail 80 pastoral-dev-redis-1
sudo -u pastoral-runner docker inspect --format '{{json .State.Health}}' pastoral-dev-redis-1
```

Após o merge de uma correção na infra, aguarde a CI da `develop` e inicie
**uma nova execução** de `Deploy development` nessa branch. Reexecutar o job
antigo continua usando o SHA antigo da infra. Use o mesmo SHA publicado da
aplicação se ele ainda for o HEAD da `develop`. Não remova os volumes para
recuperar o deploy.

## Validação desta entrega

As verificações locais cobrem sintaxe Bash/SH e estrutura YAML. As validações
Docker, imagens, migrations e Playwright são responsabilidade das CIs dos PRs
e do primeiro deploy no Ubuntu. O ambiente não é considerado iniciado até
essas execuções passarem. Integração do login na aplicação, massa funcional,
observabilidade de desenvolvimento e promoção de ambientes são próximas entregas.



## Relatório de recursos em `/api/v1/health`

O health público nas portas web e API, inclusive pelo túnel de backend, retorna
o relatório de `scripts/health-development.py`: `timestamp`, `dockerHost`,
`host`, `containers`, `readiness`, `errors` e `status`. O caminho correto é
`/api/v1/health`. O frontend não participa desta rota.

A coleta roda no Ubuntu como `pastoral-runner`. O serviço `health-report` serve
a última amostra publicada no volume `pastoral-dev_health-report-data`, montado
somente para leitura. Backend e serviço HTTP não recebem o socket Docker.
O volume pertence ao daemon selecionado em `/opt/pastoral/dev/docker-host`;
a publicação funciona tanto no Engine quanto na VM do Desktop, sem bind mounts.

Após o primeiro deploy desta versão, instalar uma vez no Ubuntu:

```bash
sudo bash /opt/pastoral/dev/current/scripts/install-health-reporter.sh
systemctl status pastoral-health-report.timer --no-pager
sudo journalctl -u pastoral-health-report.service -n 30 --no-pager
curl -i http://127.0.0.1:8082/api/v1/health
```

O timer executa uma nova coleta 30 segundos após a anterior terminar; os cinco
containers são consultados em paralelo. A unidade acompanha o link `current`
a cada execução, usando os scripts do último deploy validado. Cada deploy
publica também uma amostra inicial antes do E2E. A migração para Desktop gera
uma nova amostra no daemon de destino, sem reutilizar as métricas do Engine.

`timestamp` marca o início da coleta. `snapshot.collectedAt` marca sua conclusão;
`snapshot.ageSeconds` informa a idade, `maxAgeSeconds` é 180 e `stale` indica
amostra vencida ou com data futura. Memória, CPU e disco são métricas periódicas;
`readiness` consulta o backend com timeout de quatro segundos e compartilha a
resposta por até cinco segundos entre solicitações concorrentes.

HTTP 200 exige coleta íntegra, recente e readiness saudável. HTTP 503 preserva
os dados disponíveis, define `status: error` e informa erros da coleta,
`resource_snapshot_stale`, `resource_snapshot_unavailable` ou
`readiness_unavailable`. Uma amostra ausente não gera métricas fictícias.
`/health/live` interno permanece independente da coleta; os healthchecks do
backend e do pool Traefik continuam usando a readiness original.

`host.memory`, `host.disk` e `host.loadAverage` são do Ubuntu. `containers.*.stats`
são do daemon selecionado; no Desktop o denominador de `MemUsage` é a memória
disponível na VM (não os 16 GB do Ubuntu). `configuredMemoryLimitBytes: 0`
significa ausência de limite explícito no container. `MemUsage` de Postgres é
uso do container, não uma decomposição dos buffers internos do banco. Este
endpoint público inclui metadados operacionais como caminho do socket e disco,
mas não publica senhas, chaves ou variáveis de ambiente dos containers.

Se apenas o coletor parar, o último relatório fica disponível e passa a 503
após vencer. Se o Desktop parar, os containers e o endpoint ficam indisponíveis.
Reativar o Desktop e conferir o journal; o timer tenta outra vez automaticamente. Para uma coleta manual sem aguardar o timer:

```bash
sudo systemctl start pastoral-health-report.service
```

Validação: testes Node do contrato HTTP e falhas; testes Python do coletor e
publicador; CI com imagem real, volume gravado atomicamente e leitura por UID
1001, além dos testes de roteamento Traefik e runtime Desktop. A instalação do
timer e o retorno público no Ubuntu requerem validação operacional após merge.

### Seleção conjunta das imagens de desenvolvimento

O deploy automático valida o HEAD de develop de backend e frontend, exigindo
CI de push aprovada e publicação bem-sucedida das duas imagens. Aguarda até
60 tentativas com intervalos de cinco segundos pela publicação do outro
componente. Se a revisão mudar ou a publicação não for aprovada, interrompe
antes de executar o job no host. O E2E continua fixado no HEAD aprovado.

As duas revisões são enviadas ao script de deploy e substituem as imagens
anteriores juntas; a imagem de migrations corresponde ao backend selecionado.
A chamada manual sem essas duas revisões mantém o comportamento anterior.
Uma seleção parcial, inválida ou divergente do componente disparador é rejeitada.

No incidente de 03/10/2026, a publicação do frontend falhou no smoke Vercel
com HTTP 404 transitório e o deploy do backend executou o E2E novo contra a
interface anterior. Para retomar, mergear primeiro esta correção de infraestrutura
e aguardar sua CI em develop; depois mergear a correção do smoke no frontend.
A publicação aprovada do frontend dispara o deploy automático com o par validado.

Em falha de E2E, current-images.env e a referência current não são promovidos.
Os containers podem já estar executando imagens candidatas: o script não
realiza rollback automático. Só considerar a implantação validada após o E2E
e a promoção das referências concluírem.

