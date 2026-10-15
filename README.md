# Lab Novatec: service graphs por jornada

Lab local em kind para avaliar o plugin oficial
[Novatec Service Dependency Graph](https://github.com/NovatecConsulting/novatec-service-dependency-graph-panel).

**Resultado:** foi possivel filtrar componentes e arestas por jornada, com
latencia nas arestas, sem eBPF. O filtro e implementado pelas consultas PromQL
e variaveis Grafana; o plugin renderiza os dados resultantes.

## Acessar

Dashboard: <http://localhost:3000/d/novatec-journeys>

Nao precisa de login para visualizar. No topo, altere **Jornada** e **Tenant**.

| Jornada | Fluxo real | O que deve aparecer |
|---|---|---|
| Entrada normal de WhatsApp | app-a -> app-b -> Redis | 3 componentes e 2 arestas |
| Notificacao ativa | app-a -> app-b | 2 componentes e 1 aresta; Redis desaparece |
| All | Uniao das jornadas | 3 componentes e 2 arestas |

Esses nomes representam casos de uso sinteticos, nao uma integracao real com
WhatsApp. Ha somente duas apps Python e um Redis de teste.

## Dois modos lado a lado

**Esquerda: metricas DA jornada.**
Origem, destino, sucesso, erro e duracao sao filtrados pela label `journey`,
alem de `tenant` e `cluster`.

**Direita: componentes da jornada, metricas GLOBAIS.**
As arestas sao selecionadas pela jornada, mas suas metricas agregam TODAS as
jornadas dentro do tenant selecionado. Esse e o modo inicial discutido:
mostrar apenas os componentes do caso de uso mesmo quando o numero da
comunicacao A -> B ainda representa todas as jornadas.

Valores observados em uma execucao, nao valores fixos do painel:

| Aresta app-a -> app-b | Latencia media |
|---|---|
| WhatsApp | aproximadamente 36 ms |
| Notificacao ativa | aproximadamente 165 ms |
| Agregada entre jornadas | aproximadamente 102 ms |

A app-b acrescenta 30 ms no fluxo WhatsApp e 160 ms no fluxo de notificacao,
para tornar a diferenca visivel. Os tempos medidos incluem a chamada HTTP.
Redis e acessado de verdade, por `INCR`, somente na jornada WhatsApp.

**Importante:** o painel da direita NAO mede a latencia exclusiva da jornada.
Nao usar seus valores como SLI da jornada.

## Arquitetura

```text
load-generator
  +--> app-a /whatsapp --> app-b /handle --> Redis
  +--> app-a /notify   --> app-b /handle
          |                   |
          +---- /metrics -----+
                    |
                Prometheus
                    |
          PromQL + variaveis Grafana
                    |
             Novatec panel
```

- Cluster independente: `novatec-lab`; a POC Coroot permanece parada.
- Namespaces: `demo` e `observability`.
- Grafana 12.2.0, plugin oficial 4.2.0, assinatura verificada pelo Grafana.
- Prometheus 3.2.1 com scrape a cada 5 segundos.
- Nao foi necessario alterar/forkar o plugin nem permitir plugins sem assinatura.
- Nao foram instalados Istio, Tempo, Loki ou agentes eBPF neste lab.
- Geracao de dados ficticios do plugin esta desabilitada.

## De onde vem a label

A app-a identifica a jornada pelo endpoint e propaga `X-Journey` para a app-b.
O tenant vem de `X-Tenant`, limitado a `tenant-a` ou `tenant-b` no laboratorio.
As duas apps registram chamadas de saida com:

```text
cluster, source, target, journey, tenant
```

Metricas:

```text
lab_calls_total{...,status="ok|error"}
lab_call_duration_seconds_sum{...}
lab_call_duration_seconds_count{...}
lab_edge_last_seen_seconds{...}
```

A ultima metrica guarda o timestamp da ultima chamada real da jornada na
aresta. Ela e atualizada ao observar trafego, nao por um mapa estatico.

O gerador alterna endpoints e tenants. A cada 23 chamadas injeta uma falha:
app-b retorna 503 e app-a retorna 502. Falhas de infraestrutura ou respostas
inesperadas sao registradas nos logs do gerador.

## Como o filtro funciona

O dashboard usa tres consultas por grafo:

1. Taxa de chamadas com sucesso.
2. Duracao media em ms: `1000 * rate(sum) / rate(count)`.
3. Taxa de erros, preenchendo com zero as arestas conhecidas sem erros.

As consultas sao instantaneas em formato Table. O plugin faz o mapeamento das
colunas de origem/destino e das colunas `Value #A`, `Value #B`, `Value #C`.
Configuramos os campos de metricas de saida para que os tempos aparecam nas
arestas, e `sumTimings=false` porque a media ja foi calculada no PromQL.

No modo agregado, removemos `journey` da agregacao das metricas e fazemos
intersecao com as arestas observadas da jornada:

```promql
metricas_agregadas_por_cluster_source_target
and on (cluster, source, target)
arestas_observadas_da_jornada
```

O conjunto de arestas considera `lab_edge_last_seen_seconds` e o intervalo
selecionado no dashboard. As expressoes completas ficam em `build_dashboard.py`.

**Nao existe descoberta automatica da semantica de negocio.** Para filtrar
"notificacao ativa", essa associacao precisa existir em alguma fonte:
instrumentacao, atributos derivados de traces, rota ou cadastro de jornadas.
Se as metricas nao carregam `journey`, ainda e possivel o modo agregado,
desde que exista uma fonte separada com a associacao jornada -> aresta.

## O que foi verificado

Os testes de `tests/verify.py` usam endpoints reais e as consultas do dashboard
contra o Prometheus via Grafana. `tests/browser.mjs` abre Chrome headless,
interage com os seletores e inspeciona os grafos efetivamente renderizados.

- Fluxos HTTP e Redis, propagacao do tenant, erro intencional e entrada invalida.
- Diferenca entre latencia por jornada e agregada.
- Mesma metrica global em selecoes de jornadas diferentes, quando a aresta e compartilhada.
- Redis removido em notificacao ativa nos dois paines.
- Redis restaurado ao selecionar All ou WhatsApp.
- Trocas repetidas sem manter componentes da selecao anterior.
- Tenant alterando as consultas; nao apenas a legenda do painel.
- Jornada inexistente retornando vazio, sem fallback para todos os servicos.
- Latencias numericas no grafo e ausencia de erros JavaScript nao tratados.

Capturas e dados dos grafos ficam em `artifacts/` apos rodar o teste de browser.
`browser-results.json` registra as metricas efetivamente recebidas pelo painel.
As capturas nao representam trafego de producao.

## Executar

Requisitos: Linux, Docker, kind, kubectl, Python 3, curl e git.
Node/npm e Chrome sao usados apenas nos testes de navegador.
As portas 3000 e 8082 devem estar livres.

```bash
git clone https://github.com/mario-valente/novatec-kind-lab.git
cd novatec-kind-lab
bash up.sh
```

Aguarde cerca de um minuto para haver amostras suficientes para `rate()`.
O script usa `.kubeconfig` local e nao troca o contexto Kubernetes global.

```bash
curl -sS http://localhost:8082/whatsapp
curl -sS http://localhost:8082/notify
curl -sS -H 'X-Tenant: tenant-b' http://localhost:8082/whatsapp
curl -sS 'http://localhost:8082/notify?scenario=error'

python3 tests/verify.py
npm ci --no-audit --no-fund
npm run test:browser
```

O teste usa `/usr/bin/google-chrome`; outra instalacao pode ser indicada por
`CHROME_PATH`. Nao usa o perfil pessoal do navegador.

## Limites e cuidados para adocao

- O plugin e uma visualizacao, nao um backend APM ou um mecanismo de autorizacao.
- `tenant` neste lab e apenas um filtro. Um Viewer pode consultar outros dados
  do datasource; nao usar isso como isolamento entre clientes.
- Foi testado um cluster real e dois tenants sinteticos, nao multi-cluster.
  Para agregar clusters, incluir cluster/namespace na identidade dos nos para
  evitar colisoes entre servicos homonimos.
- O grafo e agregado por intervalo; nao prova a ordem de uma requisicao
  individual. Tracing distribuido continua necessario para esse objetivo.
- O painel mostra media, nao p95/p99. Taxas abaixo de 1 podem aparecer como
  `800 m` no formatador do plugin: isso representa 0,8 por segundo, nao minutos.
- O plugin mostra nos sem metricas recebidas em cinza. app-a e origem das
  chamadas medidas; neste lab nao fornecemos suas metricas de entrada.
- Este teste NAO comprova integracao direta com Tempo. Para usa-lo como fonte
  indireta, gerar metricas de service graph com as dimensoes necessarias e
  adaptar as consultas ao seu schema real.
- Nao usar IDs de mensagem, usuario ou requisicao como labels Prometheus.
  Controlar cardinalidade de tenants/jornadas antes de aplicar em producao.
- Apps usam um worker Gunicorn por pod para compartilhar o registry Prometheus
  entre threads. Multiplos processos exigiriam configurar coleta multiprocess.

## Persistencia e seguranca local

Os dados sao descartaveis. Prometheus usa `emptyDir`: recriar seu pod apaga o
historico. Contadores das apps reiniciam com seus processos. A retencao maxima
configurada e 24 horas. Grafana recebe datasource e dashboard por provisioning.
`up.sh` reinicia deployments para carregar imagens/configuracoes atualizadas.

Portas publicadas somente em `127.0.0.1`. Grafana tem acesso anonimo Viewer,
senha de admin aleatoria em Secret e estatisticas de uso desabilitadas.
Redis nao tem senha e nao esta publicado no host. Nao expor este lab em rede
nem reutilizar sua configuracao de acesso em producao.

## Parar ou remover

```bash
# Para somente o node/container deste lab, preservando o cluster.
bash stop.sh

# Retoma o node parado sem reiniciar deployments.
docker start novatec-lab-control-plane

# Exclui apenas o cluster novatec-lab e os dados dentro dele.
bash down.sh
```

Fontes:
[plugin](https://github.com/NovatecConsulting/novatec-service-dependency-graph-panel),
[catalogo Grafana](https://grafana.com/grafana/plugins/novatec-sdg-panel/).
