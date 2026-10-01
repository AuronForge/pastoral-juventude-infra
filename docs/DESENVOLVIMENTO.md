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

## Preparar Ubuntu

Pré-requisitos: Docker Engine, Compose v2 com `up --wait`, Git, Bash, OpenSSL,
`flock`, pacote `acl` e saída HTTPS para GitHub, GHCR, Docker Hub e npm.
O deploy não requer Node ou Playwright instalados no host.

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
`backend-public-health-v1` com prioridade 200 e reescrita exata para
`/health/live` no backend. O caminho externo permanece versionado.
A resposta saudável é HTTP 200 com `{"status":"ok"}` e
`Cache-Control: no-store`. Não requer autenticação nem expõe o estado
individual de PostgreSQL/Redis.

Após novo deploy:

```bash
curl -i http://127.0.0.1:8082/api/v1/health
# Externamente: substituir pela URL atual gerada pelo cloudflared.
curl -i https://URL-ATUAL.trycloudflare.com/api/v1/health
```

`/health/live` e `/health/ready` continuam sem roteamento público.
O readiness permanece sendo usado internamente pelo Traefik e pelo E2E.
O serviço do router público também está sujeito ao healthcheck interno
do load balancer: se não houver backend saudável disponível, o gateway
pode responder 503 mesmo com o processo vivo. Uma falha de conexão do túnel
pode gerar 502. Portanto, esse endpoint não diagnostica a causa da indisponibilidade.

A CI executa Traefik real para comprovar a reescrita exata, ausência de cache
e bloqueio dos caminhos internos. A validação externa exige túnel ativo.

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
| Infra            | variável `DEV_E2E_REF`                          | SHA completo aprovado deste PR E2E, após merge               |
| Infra            | secret `SOURCE_READ_TOKEN`, quando necessário   | Contents/Actions: read nos repositórios de origem privados   |
| Infra            | variável `DEV_GHCR_PRIVATE=true`, se necessário | Autenticar para baixar imagens privadas                      |
| Infra            | variável `GHCR_USER` e secret `GHCR_READ_TOKEN` | Usuário/token com read:packages, sem permissão de publicação |

## Ordem de bootstrap

1. Revisar e fazer merge dos PRs de backend, frontend, E2E e infra em `develop`.
2. Promover os novos workflows para a branch padrão por PR. `workflow_run` e
   `workflow_dispatch` dependem da existência do arquivo na branch padrão.
   Não promova essas mudanças com deploy de produção; esta entrega atua só em `develop`.
3. Manter `DEV_AUTO_DEPLOY` e `DEV_DEPLOY_ENABLED` desativados durante a preparação.
4. Executar push/merge em `develop` de backend e frontend e aguardar CI/publicação.
5. Preencher o arquivo do host com as duas imagens e migrations desse backend.
6. Configurar runner, environment, tokens e `DEV_E2E_REF` com o SHA aprovado.
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
