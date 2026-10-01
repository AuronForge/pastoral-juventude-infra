# Migrar desenvolvimento do Engine Ubuntu para Docker Desktop

## Resultado e limites

Docker Desktop Linux tem um daemon e armazenamento próprios. A GUI não mostra
containers do Engine em /var/run/docker.sock. Esta migração coloca somente
`pastoral-dev` no Desktop, preservando PostgreSQL/Redis e as imagens da última
release validada. Aquatrack e outros projetos continuam no Engine. O serviço
Docker Engine não é desabilitado nem seus volumes são removidos.

A migração causa indisponibilidade temporária. O Desktop deve permanecer ativo;
ao encerrá-lo, a aplicação fica indisponível. Em Settings → General, habilitar
inicialização ao entrar na sessão. Isso não equivale a um daemon de sistema
iniciado antes do login. Validar também o comportamento após reiniciar Ubuntu.

O Desktop informado neste host tem aproximadamente 3,57 GiB e 4 CPUs.
Conferir espaço disponível no disco do Ubuntu e na VM antes de migrar:
há cópia das imagens, arquivos de volume e backups. Não reduzir o tamanho
do disk image para liberar espaço: isso pode remover dados do Desktop.

## Preparação após merge e CI

No checkout da infra:

```bash
git switch develop
git pull --ff-only
sudo bash scripts/install-desktop-access.sh eduardo-marques-server
```

O instalador concede ao runner travessia dos três diretórios e acesso rw ao
socket Desktop. Instala uma unidade systemd path para reaplicar a ACL quando
o socket é recriado. O runner recebe leitura dos quatro secrets existentes
para transmitir uma cópia à VM; secrets não são impressos nem alterados.
Os arquivos instalados em /usr/local/libexec e /etc/systemd/system pertencem
ao root. Não se adiciona o runner ao grupo do usuário pessoal.

Solicitar novo deploy pelo fluxo aprovado **ainda no Engine**, antes da migração.
Isso entrega a revisão portátil e corrige a cópia de scripts à release:
o deploy antigo copiava apenas backend-entrypoint.sh, deixando o diagnóstico
ausente apesar do merge. O novo deploy também registra resources.json junto
às evidências. Só avançar quando esse deploy estiver aprovado.

```bash
sudo -u pastoral-runner python3 /opt/pastoral/dev/current/scripts/health-development.py
sudo -u pastoral-runner bash /opt/pastoral/dev/current/scripts/migrate-development-desktop.sh check unix:///home/eduardo-marques-server/.docker/desktop/docker.sock
```

`check` somente verifica pré-condições (e serializa com o lock do deploy):
daemons distintos, secrets legíveis, release e imagem E2E disponíveis,
destino sem containers Pastoral nem volumes PostgreSQL/Redis existentes.
Não copia nem interrompe serviços. Recusa sobrescrever volumes no destino.

## Migração

Depois do preflight, em uma janela sem uso da aplicação:

```bash
sudo -u pastoral-runner bash /opt/pastoral/dev/current/scripts/migrate-development-desktop.sh migrate unix:///home/eduardo-marques-server/.docker/desktop/docker.sock
```

O script mantém o mesmo lock do deploy e:

1. Transfere as imagens exatas do Engine ao Desktop, sem depender de novo login
   GHCR. Mantém PostgreSQL 17.11 e não executa migrations nessa transferência.
2. Transmite configuração da release e secrets para volumes internos do daemon.
   Não usa bind mounts de /opt no Desktop, evitando dependência de VirtioFS/UID.
   Os secrets ficam root:1001, 0440, disponíveis somente nos serviços necessários.
3. Gera pg_dump e para os cinco containers de origem com encerramento gracioso.
4. Copia os dois volumes parados para arquivos tar privados de backup e extrai
   no destino, preservando ownership e dados. Mantém os volumes originais.
5. Inicia o destino em portas temporárias loopback 18081/18082, mantendo o túnel
   em 8082 indisponível durante a validação. Executa smoke E2E interno, como UID
   1001, copiando os relatórios ao host por Docker cp.
6. Após smoke aprovado, grava /opt/pastoral/dev/docker-host com o endpoint
   Desktop e desktop-runtime.env na release. Esse é o ponto de transferência
   de responsabilidade: a origem fica parada e seus dados passam a ser antigos.
7. Recria o Traefik nas portas originais 8081/8082 (ou valores do ambiente)
   e verifica /api/v1/health no host. O túnel ativo pode continuar com a mesma URL.

Antes do ponto de transferência, uma falha tenta parar o destino e reiniciar
a origem. Verificar que essa recuperação passou; não há garantia caso o daemon
de origem falhe. Backups e volumes do destino são mantidos para investigação.
Uma nova tentativa recusa volumes existentes. Para a falha anterior ao ponto
de transferência, depois de corrigir o código e implantar no Engine:

```bash
sudo -u pastoral-runner bash /opt/pastoral/dev/current/scripts/prepare-desktop-retry.sh unix:///home/eduardo-marques-server/.docker/desktop/docker.sock
```

O preparo recusa execução se docker-host já apontar ao Desktop, se o backend
de origem não estiver pronto ou se qualquer container da candidata estiver
em execução. Arquiva os dois volumes da candidata parada em backups privados,
e só então remove os containers parados do projeto e esses volumes **no
Desktop**, liberando os nomes para nova migração. Mantém o Engine e seus
volumes, runtime/secrets do Desktop e todas as imagens. Não é um procedimento
para apagar uma implantação Desktop já aceita ou dados recebidos após cutover.
Após sucesso, repetir check e migrate. Avaliar os arquivos de backup antes
de qualquer limpeza posterior.

Após esse ponto não há retorno automático para dados antigos. Se publicar
as portas falhar, corrigir o destino; o arquivo docker-host já aponta para ele.
Se for necessário voltar depois de receber escritas no Desktop, fazer novo
dump/restauração da base atual em vez de iniciar uma cópia antiga.

## Deploys seguintes e diagnóstico

Workflow seleciona o endpoint **antes** do login GHCR. Deploy, builds,
migrations, backup e E2E usam o mesmo daemon. Sem docker-host, o padrão é o
Engine. Com Desktop configurado e indisponível, falha: não volta silenciosamente
ao Engine nem cria outro ambiente vazio.

Cada release Desktop tem um volume runtime próprio; secrets ficam em
pastoral-dev_runtime-secrets. E2E prepara diretórios no container, executa
testes como UID 1001 e copia relatórios ao usuário runner. O processo de testes
não ganha acesso ao filesystem do Ubuntu. Volumes runtime antigos não são
removidos automaticamente; limpar só os que não estejam ligados a containers
ou necessários para recuperação.

```bash
sudo -u pastoral-runner python3 /opt/pastoral/dev/current/scripts/health-development.py
sudo -u pastoral-runner docker --host unix:///home/eduardo-marques-server/.docker/desktop/docker.sock ps --filter label=com.docker.compose.project=pastoral-dev
curl -i http://127.0.0.1:8082/api/v1/health
```

O diagnóstico informa dockerHost. host.memory/disco/uptime continuam sendo
do Ubuntu que executa Python; stats dos containers e seus limites pertencem
ao Desktop/VM. Não confundir limite de memória da VM com RAM total do Ubuntu.

Backups em /opt/pastoral/dev/backups/desktop-DATA e relatórios em
/opt/pastoral/dev/reports/desktop-DATA não são enviados automaticamente ao GitHub.
O próximo deploy normal publica suas próprias evidências.

Para manutenção manual do Compose Desktop, carregar development.env,
current-images.env e current/desktop-runtime.env e usar os dois arquivos
compose.development.yaml + compose.development.desktop.yaml com o endpoint
explícito. Usar só o Compose base tentaria bind mounts do Engine.

## Validação e retorno

A CI valida os dois Composes, seleção do daemon sem fallback, cópia de
configuração/secrets e leitura como UID 1001, tar entre volumes, execução E2E
sem bind mounts, extração de relatório e propagação de falha. A CI usa Engine,
não a VM Desktop. Preflight, migração, reinício do Desktop e acesso externo
precisam ser comprovados no Ubuntu real; até lá a migração não está validada.

Para retorno anterior a qualquer uso do destino, parar o projeto Desktop
com o Compose correto e endpoint explícito, colocar unix:///var/run/docker.sock
em docker-host e reiniciar a release original no Engine. Depois de escritas,
preservar/restaurar os dados novos primeiro. Não usar down -v nem system prune.

Fontes:
- https://docs.docker.com/desktop/setup/install/linux/
- https://docs.docker.com/desktop/setup/install/linux/ubuntu/
- https://docs.docker.com/desktop/troubleshoot-and-support/faqs/linuxfaqs/
