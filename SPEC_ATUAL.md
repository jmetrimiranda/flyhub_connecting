# SPEC_ATUAL — o que existe hoje

Estado do código em `app/` na branch `plataforma`. Todos os JSON deste documento
foram capturados em execução real, não escritos à mão.

Escopo entregue:

- **painel** — FastAPI + status via SSE, start/stop do pipeline com exibição do
  endereço RTMP e botão de copiar;
- **fatia 1 da plataforma** — MJPEG em `/stream` com a inferência aplicada,
  detector abstraído (funciona sem pesos e sem torch) e painel de informações de
  conexão;
- **fatias 2 e 3** — coleta de quadros com guarda de pré-condição, modais,
  máquina de estados e gravação em `raw/`; e o split temporal por blocos
  contíguos disparado ao salvar, com `split_manifest.json`;
- **fatias 4 e 5** — tela de datasets com lista, galeria por partição, exclusão
  de imagens e do dataset, refazer o split; e upload ao Roboflow preservando a
  partição, com retomada de falha parcial.

Fora de escopo, ainda não implementado: a tela de modelo (`/api/model/samples`)
e a pasta `train/`. A navegação do topo mostra `Modelo` desabilitado, marcado
`em breve`.

Arquivos:

| Arquivo | Papel |
|---|---|
| `app/main.py` | rotas HTTP, SSE e MJPEG |
| `app/pipeline.py` | controle do container MediaMTX e do túnel bore |
| `app/monitor.py` | thread de polling da API do MediaMTX e semáforo |
| `app/video.py` | leitura do RTSP, worker de inferência, contadores e MJPEG |
| `app/inference.py` | `Detector` — inferência ou passthrough, sem quebrar |
| `app/collect.py` | máquina de estados da coleta, amostragem, fila de escrita e `session.json` |
| `app/split.py` | split temporal por blocos contíguos e `split_manifest.json` |
| `app/datasets.py` | versionamento, layout em disco, leitura, divergência, exclusão e miniaturas |
| `app/roboflow_upload.py` | envio ao Roboflow em thread, com retomada e cancelamento |
| `app/templates/index.html` | tela Home |
| `app/templates/datasets.html`, `app/templates/dataset.html` | lista e detalhe dos datasets |
| `app/templates/_nav.html` | navegação, incluída pelas três telas |
| `app/static/app.js` | comportamento da Home |
| `app/static/datasets.js`, `app/static/dataset.js` | lista e detalhe |
| `app/static/app.css` | tema, compartilhado pelas telas |
| `run.sh` | sobe o uvicorn |
| `tools/fake_stream.sh` | publica um `testsrc` no MediaMTX, para trabalhar sem drone |

---

## 1. Rotas

Trinta e uma rotas de aplicação, mais os estáticos em `/static/*` (`StaticFiles`).

| Método | Caminho | Corpo da requisição | Resposta |
|---|---|---|---|
| GET | `/` | — | HTML do painel (`200 text/html; charset=utf-8`) |
| GET | `/events` | — | `200 text/event-stream; charset=utf-8`, fluxo infinito (ver §2) |
| GET | `/stream` | — | `200 multipart/x-mixed-replace; boundary=frame`, fluxo infinito (ver §4) |
| GET | `/api/pipeline/status` | — | `200 application/json` — `{pipeline, stream, video, model}` |
| POST | `/api/pipeline/start` | `{}`, `{"stream_path": "..."}` ou sem corpo | `200 application/json` — `{ok, pipeline, stream, video, model}` |
| POST | `/api/pipeline/stop` | `{}` ou sem corpo | `200 application/json` — `{ok, pipeline, stream, video, model}` |
| GET | `/api/stream/stats` | — | `200 application/json` — só o bloco `video` (ver §4) |
| GET | `/api/model` | — | `200 application/json` — só o bloco `model` (ver §5) |
| POST | `/api/model/reload` | — | `200 application/json` — o bloco `model` depois de forçar a recarga |
| GET | `/api/collect/preflight` | — | `200 application/json` — as cinco pré-condições (ver §6) |
| POST | `/api/collect/start` | `{interval, limit, dedup}` ou sem corpo | `200 application/json` — `{ok, collect}`; em recusa, `{ok:false, collect, preflight, error}` |
| POST | `/api/collect/pause` | — | `200 application/json` — `{ok, collect}` |
| POST | `/api/collect/resume` | — | `200 application/json` — `{ok, collect}` |
| POST | `/api/collect/save` | — | `200 application/json` — `{ok, collect}` com `state: "salvando"`; o split roda depois da resposta |
| POST | `/api/collect/dismiss` | — | `200 application/json` — `{ok, collect}`, volta de `salvo` a `ocioso` |
| GET | `/api/collect/status` | — | `200 application/json` — só o bloco `collect` (ver §6) |
| GET | `/datasets` | — | HTML da lista de datasets |
| GET | `/datasets/{version}` | — | HTML do detalhe; a versão é injetada em `body[data-version]` |
| GET | `/api/datasets` | — | `200 application/json` — `{datasets: [...]}`, da mais recente para a mais antiga (ver §8) |
| GET | `/api/datasets/{version}` | — | `200 application/json` — resumo + `session`, `manifest`, `edits`, `images` |
| GET | `/api/datasets/{version}/images/{split}` | — | `200 application/json` — `{version, split, count, images[]}` |
| GET | `/api/datasets/{version}/image/{split}/{filename}` | — | `200 image/jpeg` — o arquivo original |
| GET | `/api/datasets/{version}/thumb/{split}/{filename}` | — | `200 image/jpeg` — miniatura de 240 px, cacheada |
| POST | `/api/datasets/{version}/images/preview-delete` | `{split, filenames[]}` | `200 application/json` — o que a exclusão faria |
| DELETE | `/api/datasets/{version}/images` | `{split, filenames[]}` | `200 application/json` — `{ok, removed, removed_from_raw, counts, drift, event}` |
| DELETE | `/api/datasets/{version}` | `{confirm: "v0.3"}` | `200 application/json`; `400` se a confirmação não bater |
| POST | `/api/datasets/{version}/resplit` | `{margin?}` ou sem corpo | `200 application/json` — `{ok, counts, drift, manifest}` |
| GET | `/api/roboflow/config` | — | `200 application/json` — se há SDK e se há chave; **nunca** a chave (ver §9) |
| POST | `/api/roboflow/upload` | `{version, workspace, project, api_key?, batch_name?, tags?}` | `200 application/json` — `{ok, upload}` |
| POST | `/api/roboflow/cancel` | — | `200 application/json` — `{ok, upload}` |
| GET | `/api/roboflow/status` | — | `200 application/json` — estado, progresso e `config` |

`GET /events` responde apenas a GET — qualquer outro método devolve `405` com
header `allow: GET`.

As rotas de dataset devolvem `404` para versão malformada e para versão
inexistente, sem distinguir as duas: separá-las com códigos diferentes só
ajudaria quem estivesse sondando o disco de fora. Erros de validação em ação
(confirmação errada, nenhuma imagem válida, split que falhou) são `400`.

### GET /api/pipeline/status

Sem corpo de requisição. A resposta é exatamente o mesmo objeto empurrado pelo
SSE — os dois compartilham a função `_state()` em `app/main.py`, então o JS tem
um único renderizador. **Não** traz o campo `ok`.

```json
{
  "pipeline": {
    "busy": false,
    "error": null,
    "steps": [
      {"name": "MediaMTX", "status": "ok", "detail": "container mtx no ar"},
      {"name": "API", "status": "ok", "detail": "respondendo em :9997"},
      {"name": "Túnel", "status": "ok", "detail": "bore local 1935 --to bore.pub"},
      {"name": "Endereço", "status": "ok", "detail": "bore.pub:49934"}
    ],
    "stream_path": "live/m4td",
    "configured_path": "live/m4td",
    "path_detected": false,
    "mediamtx": {"running": true, "container": "mtx"},
    "tunnel": {"running": true, "address": "bore.pub:49934"},
    "rtmp_url": "rtmp://bore.pub:49934/live/m4td",
    "rtsp_url": "rtsp://localhost:8554/live/m4td",
    "hls_url": "http://localhost:8888/live/m4td"
  },
  "stream": {
    "api_ok": true,
    "error": null,
    "paths": [],
    "level": "red",
    "label": "Sem stream"
  },
  "video": { "...": "ver §4" },
  "model": { "...": "ver §5" }
}
```

Campos de `pipeline` (montados por `pipeline.snapshot()`):

| Campo | Tipo | Significado |
|---|---|---|
| `busy` | bool | há um start/stop em execução neste instante |
| `error` | string \| null | mensagem do último start/stop que falhou; zerada no início de cada start/stop |
| `steps` | lista | relatório do último start/stop (ver §11). `[]` antes do primeiro |
| `stream_path` | string | path **efetivo**: o nome real do path ativo no MediaMTX quando houver um; senão o configurado |
| `configured_path` | string | o que `STREAM_PATH` ou o último start definiu |
| `path_detected` | bool | `true` quando os dois divergem — o painel está exibindo um path que não foi ele quem escolheu |
| `mediamtx.running` | bool | `docker inspect` do container |
| `mediamtx.container` | string | sempre `"mtx"` (constante `CONTAINER`) |
| `tunnel.running` | bool | há processo `bore local` vivo |
| `tunnel.address` | string \| null | `host:porta` do túnel; `null` se o túnel não estiver vivo |
| `rtmp_url` | string \| null | `rtmp://{address}/{stream_path}`; `null` sem endereço |
| `rtsp_url` | string | sempre montado, mesmo com pipeline parado |
| `hls_url` | string | idem |

`rtsp_url` e `hls_url` são strings construídas a partir de `stream_path`, não
verificações — continuam preenchidas com tudo parado.

Os três URLs usam o path **efetivo**, não o configurado: com um path publicando
sob outro nome, é o nome real que aparece. O sufixo do path é a única credencial
do endpoint RTMP, e exibir o sufixo errado é exibir um endereço que não funciona.
Ver §13.

### POST /api/pipeline/start

Corpo opcional. O modelo é `StartRequest` com um único campo:

```json
{"stream_path": "live/m4td-a1b2c3"}
```

- Corpo ausente, `{}` ou `{"stream_path": null}` → usa `STREAM_PATH` (padrão `live/m4td`).
- O valor passa por `.strip().lstrip("/")`: enviar `"/live/m4td-a1b2c3"` grava `live/m4td-a1b2c3`.
- Tipo errado devolve `422` do Pydantic:
  ```json
  {"detail":[{"type":"string_type","loc":["body","stream_path"],"msg":"Input should be a valid string","input":123}]}
  ```

Resposta real de um start bem-sucedido com `{"stream_path":"/live/m4td-a1b2c3"}`:

```json
{
  "ok": true,
  "pipeline": {
    "busy": false,
    "error": null,
    "steps": [
      {"name": "MediaMTX", "status": "ok", "detail": "container mtx no ar"},
      {"name": "API", "status": "ok", "detail": "respondendo em :9997"},
      {"name": "Túnel", "status": "ok", "detail": "bore local 1935 --to bore.pub"},
      {"name": "Endereço", "status": "ok", "detail": "bore.pub:57671"}
    ],
    "stream_path": "live/m4td-a1b2c3",
    "mediamtx": {"running": true, "container": "mtx"},
    "tunnel": {"running": true, "address": "bore.pub:57671"},
    "rtmp_url": "rtmp://bore.pub:57671/live/m4td-a1b2c3",
    "rtsp_url": "rtsp://localhost:8554/live/m4td-a1b2c3",
    "hls_url": "http://localhost:8888/live/m4td-a1b2c3"
  },
  "stream": {
    "api_ok": true, "error": null, "paths": [],
    "level": "red", "label": "Sem stream"
  }
}
```

Resposta real de um start que falhou (config inexistente):

```json
{
  "ok": false,
  "pipeline": {
    "busy": false,
    "error": "config não encontrado: /nao/existe.yml",
    "steps": [
      {"name": "MediaMTX", "status": "error", "detail": "config não encontrado: /nao/existe.yml"},
      {"name": "API", "status": "skipped", "detail": ""},
      {"name": "Túnel", "status": "skipped", "detail": ""},
      {"name": "Endereço", "status": "skipped", "detail": ""}
    ],
    "stream_path": "live/m4td",
    "mediamtx": {"running": true, "container": "mtx"},
    "tunnel": {"running": true, "address": "bore.pub:49934"},
    "rtmp_url": "rtmp://bore.pub:49934/live/m4td",
    "rtsp_url": "rtsp://localhost:8554/live/m4td",
    "hls_url": "http://localhost:8888/live/m4td"
  },
  "stream": { "...": "igual acima" }
}
```

Falha **não** devolve status HTTP de erro: é sempre `200`, com `ok: false`.
A verificação do arquivo de config acontece antes do `docker rm -f`, então esse
erro específico não derruba um container que já estava rodando.

Duração medida de um start completo bem-sucedido: **1,6 s** (`docker run` com a
imagem já em cache local).

### POST /api/pipeline/stop

Sem campos. Resposta real:

```json
{
  "ok": true,
  "pipeline": {
    "busy": false,
    "error": null,
    "steps": [
      {"name": "Túnel", "status": "ok", "detail": "encerrado"},
      {"name": "MediaMTX", "status": "ok", "detail": "encerrado"}
    ],
    "stream_path": "live/m4td",
    "mediamtx": {"running": false, "container": "mtx"},
    "tunnel": {"running": false, "address": null},
    "rtmp_url": null,
    "rtsp_url": "rtsp://localhost:8554/live/m4td",
    "hls_url": "http://localhost:8888/live/m4td"
  },
  "stream": {
    "api_ok": false,
    "error": "MediaMTX não responde (ConnectError)",
    "paths": [],
    "level": "red",
    "label": "MediaMTX não responde"
  }
}
```

O `detail` de cada passo do stop é `"encerrado"` quando o comando devolveu
código 0, e `"já estava parado"` quando não havia o que matar — parar duas vezes
é seguro e continua devolvendo `ok: true`.

Ambos os POST rodam em threadpool (`run_in_threadpool`), porque `pipeline.start`
e `pipeline.stop` são bloqueantes e chamam `subprocess`.

---

## 2. SSE — `/events`

**Formato.** Cada emissão é uma linha `data: <json>` seguida de linha em branco.
Não há `event:`, `id:` nem `retry:`. O JSON é exatamente o mesmo objeto de
`GET /api/pipeline/status`, com cinco blocos: `pipeline`, `stream`, `video`
(§4), `model` (§5) e `collect` (§6).

**Headers da resposta** (capturados):

```
status: 200
cache-control: no-cache
x-accel-buffering: no
content-type: text/event-stream; charset=utf-8
transfer-encoding: chunked
```

**Periodicidade.** `SSE_INTERVAL_S = 2.0` em `app/main.py`. O laço emite e depois
dorme 2 s, então o intervalo real é 2 s mais o tempo de montar o payload (que
inclui `docker inspect` e `pgrep`). Intervalos medidos entre emissões
consecutivas: **2,033 s / 2,036 s / 2,040 s**.

O primeiro frame sai imediatamente na conexão — não há espera de 2 s inicial.

**Cadências independentes.** O `stream` vem de uma thread que faz polling da
API do MediaMTX a cada `POLL_INTERVAL_S = 2.0` s e guarda o último resultado em
memória; o SSE apenas lê esse cache. Já o bloco `pipeline` é medido na hora, a
cada emissão. Consequência: um dado de `stream` pode ter até ~2 s de idade além
do intervalo do SSE.

`collect` também é lido de contadores em memória, com uma única exceção: o
sub-bloco `disk` faz um `statvfs` a cada emissão, porque o disco é a única das
cinco pré-condições que não chega ao cliente por outro bloco.

**A coleta não acelera o SSE.** Durante uma sessão aberta, os contadores da
gravação viriam com até 2 s de atraso. Em vez de encurtar o intervalo do SSE —
o que dobraria a frequência dos `docker inspect` do `pipeline.snapshot()` no
meio do voo — o JS liga um `setInterval` de 1 s sobre `GET /api/collect/status`
enquanto `collect.state` for diferente de `ocioso`, e o desliga ao voltar a
`ocioso`. O SSE continua a 2 s e permanece a fonte de verdade para uma segunda
aba que abra no meio da gravação.

`video` é lido de contadores em memória, sem I/O — a idade dele é a do próprio
frame do SSE. `model` chama `detector.poll()`, que pode tocar o disco e, se
houver pesos novos, carregá-los; por isso vai para o threadpool junto com o
`pipeline.snapshot()`.

**Três origens no mesmo payload.** A resolução aparece em dois lugares e eles
podem divergir: `stream.paths[].resolution` é o que o MediaMTX leu do
`codecProps` do encoder, e `video.resolution` é o que o OpenCV de fato
decodificou. Quando divergem, a interface mostra os dois separados por `→`.

### Estado A — sem stream (pipeline no ar, ninguém publicando)

```json
{
  "pipeline": {
    "busy": false,
    "error": null,
    "steps": [
      {"name": "MediaMTX", "status": "ok", "detail": "container mtx no ar"},
      {"name": "API", "status": "ok", "detail": "respondendo em :9997"},
      {"name": "Túnel", "status": "ok", "detail": "bore local 1935 --to bore.pub"},
      {"name": "Endereço", "status": "ok", "detail": "bore.pub:25069"}
    ],
    "stream_path": "live/m4td",
    "mediamtx": {"running": true, "container": "mtx"},
    "tunnel": {"running": true, "address": "bore.pub:25069"},
    "rtmp_url": "rtmp://bore.pub:25069/live/m4td",
    "rtsp_url": "rtsp://localhost:8554/live/m4td",
    "hls_url": "http://localhost:8888/live/m4td"
  },
  "stream": {
    "api_ok": true,
    "error": null,
    "paths": [],
    "level": "red",
    "label": "Sem stream"
  }
}
```

### Estado B — recebendo (publicador H264 960×720 ativo)

```json
{
  "pipeline": {
    "busy": false,
    "error": null,
    "steps": [
      {"name": "MediaMTX", "status": "ok", "detail": "container mtx no ar"},
      {"name": "API", "status": "ok", "detail": "respondendo em :9997"},
      {"name": "Túnel", "status": "ok", "detail": "bore local 1935 --to bore.pub"},
      {"name": "Endereço", "status": "ok", "detail": "bore.pub:25069"}
    ],
    "stream_path": "live/m4td",
    "mediamtx": {"running": true, "container": "mtx"},
    "tunnel": {"running": true, "address": "bore.pub:25069"},
    "rtmp_url": "rtmp://bore.pub:25069/live/m4td",
    "rtsp_url": "rtsp://localhost:8554/live/m4td",
    "hls_url": "http://localhost:8888/live/m4td"
  },
  "stream": {
    "api_ok": true,
    "error": null,
    "paths": [
      {
        "name": "live/m4td",
        "ready": true,
        "ready_for": 8.0,
        "resolution": "960×720",
        "codecs": ["H264"],
        "bytes_received": 398906,
        "mbps": 0.34,
        "stalled_for": 0.0,
        "readers": 0,
        "source": "rtmpConn"
      }
    ],
    "level": "green",
    "label": "Recebendo — 960×720 · 0.34 Mbps"
  }
}
```

Origem de cada campo de `paths[]`, sobre o item de `/v3/paths/list`:

| Campo | Origem |
|---|---|
| `name` | `name` |
| `ready` | `ready` |
| `ready_for` | segundos desde que o path ficou `ready`; zera quando ele deixa de estar pronto e `null` enquanto não estiver. É o "Tempo de stream" do painel |
| `resolution` | primeiro `tracks2[]` que tenha `codecProps.width` e `.height`, formatado `W×H` (separador é `×`, U+00D7); `null` se nenhum tiver |
| `codecs` | `tracks2[].codec`; se `tracks2` estiver vazio, cai para `tracks[]` (MediaMTX antigo, sem dimensões) |
| `bytes_received` | `bytesReceived` |
| `mbps` | derivada calculada localmente (ver §10) |
| `stalled_for` | segundos desde a última variação de `bytesReceived` |
| `readers` | `len(readers)` |
| `source` | `source.type` (ex.: `"rtmpConn"`) |

### Estado C — MediaMTX caído (`docker stop mtx`, túnel ainda vivo)

```json
{
  "pipeline": {
    "busy": false,
    "error": null,
    "steps": [
      {"name": "MediaMTX", "status": "ok", "detail": "container mtx no ar"},
      {"name": "API", "status": "ok", "detail": "respondendo em :9997"},
      {"name": "Túnel", "status": "ok", "detail": "bore local 1935 --to bore.pub"},
      {"name": "Endereço", "status": "ok", "detail": "bore.pub:25069"}
    ],
    "stream_path": "live/m4td",
    "mediamtx": {"running": false, "container": "mtx"},
    "tunnel": {"running": true, "address": "bore.pub:25069"},
    "rtmp_url": "rtmp://bore.pub:25069/live/m4td",
    "rtsp_url": "rtsp://localhost:8554/live/m4td",
    "hls_url": "http://localhost:8888/live/m4td"
  },
  "stream": {
    "api_ok": false,
    "error": "MediaMTX não responde (ConnectError)",
    "paths": [],
    "level": "red",
    "label": "MediaMTX não responde"
  }
}
```

Note que `steps` continua mostrando `ok` nos quatro passos: é o relatório do
último start, um registro histórico, não o estado atual. Quem informa o estado
atual é `mediamtx.running` e `api_ok`. Note também que `rtmp_url` segue
preenchido — ver §14.

O texto entre parênteses em `stream.error` é o nome da classe da exceção httpx
(`ConnectError`, `ReadTimeout`, `ConnectTimeout`…).

### Quando a conexão cai

Do lado do servidor: a cada volta do laço, antes de emitir, verifica
`await request.is_disconnected()` e encerra o gerador se o cliente sumiu. A
detecção acontece no máximo ~2 s depois da desconexão.

Do lado do cliente: usa `EventSource`, que **reconecta sozinho** — o código não
implementa retry próprio. Como o servidor não envia diretiva `retry:`, vale o
padrão do navegador (~3 s). No `onerror` o painel só reflete a queda: o
indicador no canto direito da barra passa a `SSE: reconectando…` e ganha a
classe `down` (cor vermelha). No `onopen` volta a `SSE: conectado`. O objeto
`EventSource` nunca é fechado nem recriado pelo JS.

Enquanto a conexão está caída, a última tela renderizada permanece congelada —
não há indicação de idade do dado além do rótulo `SSE: reconectando…`.

Se o servidor voltar, a reconexão traz o estado atual: não há replay de eventos
perdidos (não usamos `id:`/`Last-Event-ID`).

---

## 3. Interface

### Navegação (topo, acima da barra de estado)

Uma faixa com a marca `M4TD` e três entradas: **Home**, **Datasets** e
**Modelo**. As duas primeiras são links, e a atual fica sublinhada em azul.
**Modelo** ainda não é link — é um `<span>` a 50% de opacidade com o selo
`em breve`, porque a tela não existe e um link que devolve 404 é pior que uma aba
apagada.

A faixa vive em `app/templates/_nav.html` e é incluída pelas três telas, com a
variável `current` vinda do handler de cada rota. A barra de estado do voo (os
quatro cartões e o indicador de SSE) fica **só na Home**: as telas de dataset não
são de tempo real e não abrem `EventSource`.

### Barra de estado (topo, `position: sticky`)

Quatro cartões, cada um com uma bolinha colorida e dois textos. **Nenhum é
clicável.** A cor nunca aparece sozinha — sempre acompanhada de texto.

| Cartão | Rótulo fixo | Valor exibido | Cor da bolinha |
|---|---|---|---|
| Disponibilidade | `Disponibilidade` | `stream.label` (ver §10). Antes do primeiro frame: `conectando…` | `stream.level` |
| MediaMTX | `MediaMTX` | `Parado` / `No ar` / `Container no ar, API muda` | vermelho se container parado; verde se container no ar **e** `api_ok`; amarelo se container no ar e API não responde |
| Túnel | `Túnel` | `Parado` / o endereço (`bore.pub:49934`) / `Subindo…` | vermelho se sem processo; verde se processo e endereço; amarelo se processo sem endereço ainda |
| Stream | `Stream` | nomes dos paths separados por `, ` — ou `Nenhum path ativo` | igual a `stream.level` |

No canto direito, fora dos cartões: `SSE: conectando` (estado inicial no HTML),
`SSE: conectado`, `SSE: reconectando…`.

Antes do primeiro frame do SSE, as bolinhas ficam cinza (sem classe de cor) e os
valores em `—`.

### Elementos clicáveis

Existem doze, contando os do painel de coleta e os dos dois modais. Fora dos
modais não há campo de formulário — a escolha de path, transporte, resolução e
FPS é do item 3 da especificação original, fatia ainda não implementada.

**1. `Iniciar pipeline`** (`#btn-start`, botão azul)

- Dispara `POST /api/pipeline/start` com corpo `{}`. A interface não envia
  `stream_path` — sempre usa o padrão do servidor.
- Enquanto a requisição está em voo: os dois botões de pipeline ficam
  desabilitados (opacidade 0,45, cursor `not-allowed`).
- Ao chegar a resposta, a tela é redesenhada com o payload retornado — a lista de
  passos aparece preenchida.
- Desabilitado quando: há um POST em voo (flag `pending` no JS) **ou**
  `pipeline.busy` é `true` no último estado recebido.
- Hover (quando habilitado): borda azul.

**2. `Parar pipeline`** (`#btn-stop`, botão vermelho-escuro)

- Dispara `POST /api/pipeline/stop` com corpo `{}`.
- Mesmas regras de desabilitação do botão de iniciar. Não há confirmação.
- Não há proteção contra parar com stream ativo.

**3. `Copiar`** (`#btn-copy`, ao lado do endereço RTMP)

- Copia `pipeline.rtmp_url` para a área de transferência.
- **Desabilitado sempre que `rtmp_url` for `null`** — ou seja, sem túnel vivo.
- Estados do rótulo: `Copiar` (normal) → `Copiado` por **1800 ms**, com fundo
  verde-escuro e borda verde, e depois volta a `Copiar`. Em falha vira `Falhou` e
  **não** se recupera sozinho — só volta a `Copiar` quando o endereço muda.
- O botão é reposto para `Copiar`/habilitado toda vez que o valor de `rtmp_url`
  muda; enquanto o valor for o mesmo, o DOM não é tocado.

**4. `Recarregar pesos`** (`#btn-model-reload`, no painel "Modelo")

- Dispara `POST /api/model/reload` e redesenha o badge e o texto do painel com a
  resposta. Fica desabilitado enquanto a requisição está em voo.
- Serve para o caso de um `best.pt` reescrito com o mesmo mtime; a detecção
  automática já cobre o caso normal (§5).

**5. `Abrir FlightHub 2`** (link, no painel "Ainda no portal da DJI")

- Abre `https://www.dji.com/flighthub-2` em nova aba (`target="_blank"`,
  `rel="noopener"`). Está ali junto do texto que explica que resolução e bitrate
  saem do encoder da aeronave e não têm controle no painel.

**6 a 12** são do painel de coleta e dos modais — `Coletar imagens do voo`,
`Pausar`, `Continuar`, `Salvar`, `Fechar`, `Confirmar`/`Cancelar` e `Entendi`.
Descritos abaixo.

### Painel "Coleta de imagens" (topo da coluna da direita)

É o primeiro painel da coluna, acima do de pipeline: durante o voo é o que o
operador usa, e os painéis de preparação ficam abaixo. Tem três aparências
mutuamente exclusivas, escolhidas por `collect.state`.

**Ocioso.** O botão azul `Coletar imagens do voo` — rótulo pelo que o operador
controla, não pela implementação — e uma linha de guarda abaixo:

- tudo verde: `Pré-condições atendidas. A coleta grava em data/datasets/ e
  particiona ao salvar.`
- algo vermelho ou amarelo: `Bloqueado: disponibilidade, stream. Clique para ver
  o que falta.`, em âmbar, e o botão ganha borda amarela.

O botão **continua clicável quando bloqueado**, de propósito. A especificação
pede as duas coisas — modal de erro ao clicar com algum indicador fora do verde,
e nada de "botão clicável e falhando depois" — e as duas convivem porque o clique
bloqueado não dispara requisição nenhuma: `localChecks()` decide no cliente e
abre o modal de erro direto. Um botão desabilitado não teria como explicar o
motivo.

**Gravando / pausado / salvando.** Uma faixa de estado com bolinha e a palavra em
maiúsculas (`GRAVANDO` com bolinha verde pulsante, `PAUSADO` e `SALVANDO` em
âmbar), a versão à direita, e:

- até três caixas de aviso: o motivo da pausa (limite atingido, disco cheio), o
  aviso de degradação do vídeo (§6) e a última mensagem de erro de escrita;
- quatro contadores em grade 2×2: `Quadros salvos` (`40 / 500` quando há limite,
  só o número quando ilimitado), `Tempo decorrido`, `Espaço usado`, `Fila de
  escrita` (`0 / 20`);
- uma linha de descartados: `Descartados: 29 quase idênticos · 3 sem quadro novo`,
  em âmbar quando há descarte por I/O ou erro de escrita, e `Nenhum quadro
  descartado` quando não há;
- os botões. `Pausar` aparece só em `gravando`, `Continuar` só em `pausado`,
  `Salvar` sempre. Em `salvando` os três ficam desabilitados e o de salvar vira
  `Salvando…`;
- uma linha de aviso: `Salvar encerra a sessão e dispara o split temporal — não
  dá para voltar a gravar nesta versão.`

**Salvo.** Faixa verde `SALVO` com a versão, os avisos do split em destaque, a
tabela de contagens (`train`, `valid`, `test`, `descartados na margem`, `total em
raw/` — com o valor em vermelho quando uma das três partições ficou em zero), uma
linha de detalhe com a margem aplicada, a duração da gravação, o `gap_s` de cada
fronteira e o caminho do manifesto, e o botão `Fechar`, que faz o `dismiss`.

Os avisos do split são renderizados aqui, não só no manifesto: os de `level:
error` em caixa vermelha com `✕`, os de `warn` em amarelo com `!`. Quem gravou 8
quadros por engano lê na tela que o dataset não tem valid nem test.

### Modais

Dois `<dialog>` nativos, sem biblioteca. Fundo escurecido por `::backdrop`.

**Modal de erro** — abre ao clicar em `Coletar imagens do voo` com alguma
pré-condição fora do verde. Título `Não é possível iniciar a coleta` e a lista
das cinco checagens, **as que falharam primeiro**: as que passaram ficam a 50% de
opacidade com `✓`, e as que falharam trazem `✕`, o rótulo em vermelho, o detalhe
e, embaixo, o que fazer:

```
✕ Stream — nenhum path ativo
  Confira o endereço no FlightHub e religue o toggle do canal.

✕ Disponibilidade — Sem stream
  Nenhum stream chegando. Suba o pipeline e publique o endereço RTMP no FlightHub.

✓ MediaMTX
✓ Túnel
✓ Disco
```

A lista vem de `localChecks()` no caso normal, e da resposta do servidor quando
é o `POST /api/collect/start` que recusa — as duas têm o mesmo formato, então o
renderizador é um só.

**Modal de confirmação** — abre quando o `GET /api/collect/preflight` confirma
que tudo está verde. Mostra a versão que será criada (`Será criada a versão
v0.3`, em verde e destacada) e três campos, todos vindos de `preflight.defaults`:

| Campo | Controle | Padrão |
|---|---|---|
| Intervalo de amostragem | `<select>` com 0.5 / 1 / 2 / 5 s | 2 s |
| Limite de quadros | `<input type=number>` mais caixa `ilimitado`, que desabilita o número | 500 |
| Descartar quadros quase idênticos | caixa de seleção | ligado |

Abaixo, uma nota fixa explica o que vai acontecer ao salvar: partição em blocos
contíguos 70/15/15 com margem de 5 quadros, e por que não é aleatória. Os botões
são `Cancelar` e `Confirmar`; `Confirmar` dispara o `POST /api/collect/start` com
os três valores.

### Campo do endereço RTMP

`#rtmp-url` não é um `input`, é um `<code>` com `user-select: all` — um clique e
`Ctrl+C` também funcionam. Texto grande (17 px, negrito).

- Sem endereço: texto `pipeline parado`, em cinza.
- Com endereço: o URL completo, em verde, com borda esverdeada (classe `live`).

Abaixo dele, aviso permanente em amarelo, sempre visível: o endereço muda a cada
reinício, é preciso **reeditar o canal de encaminhamento** e **desligar e religar
o toggle** no FlightHub.

### Relatório de passos

Lista sob os botões, alimentada por `pipeline.steps`. Cada linha é
`marcador · nome · detalhe`, com o detalhe alinhado à direita em fonte
monoespaçada. Marcadores e aparência:

| `status` | Marcador | Aparência |
|---|---|---|
| `ok` | `✓` | marcador verde |
| `error` | `✕` | marcador vermelho |
| `running` | `…` | marcador amarelo |
| `pending` | `·` | linha inteira a 45% de opacidade |
| `skipped` | `·` | linha inteira a 45% de opacidade |

Abaixo da lista, uma caixa de erro vermelha aparece quando `pipeline.error` ou
`stream.error` estiver preenchido (o do pipeline tem precedência); fica oculta
quando ambos são nulos.

### Área da esquerda

**Vídeo.** Um `<img src="/stream">` de largura total, dentro de moldura escura.
O navegador cuida do multipart sozinho; não há JS envolvido na exibição. Enquanto
não há sinal, o próprio servidor emite o quadro `Aguardando stream` (§4), então
não existe estado de imagem quebrada.

No canto inferior esquerdo do vídeo, um badge com bolinha e texto, sempre com cor
**e** palavra:

| Estado do modelo | Badge |
|---|---|
| carregado | verde — `MODELO ATIVO — best.pt · 3 classes` |
| sem arquivo de pesos | amarelo — `SEM MODELO — vídeo cru, sem detecções` |
| falhou ao carregar | vermelho — `MODELO NÃO CARREGOU — vídeo cru, sem detecções` |

**Aviso de resolução.** Acima do vídeo, faixa amarela com borda esquerda grossa,
oculta quando `video.resolution_change` é `null`. O texto traz a hora local da
troca, `de → para` e a instrução: costuma ser a qualidade do canal em
"Automático" no FlightHub, e convém fixar a resolução antes de coletar. **Não tem
botão de fechar** — some sozinho 5 minutos depois da última troca (§4).

**Painel "Conexão".** Grade de oito células, uma por campo, com rótulo pequeno em
maiúsculas e valor em fonte monoespaçada:

| Campo | Origem |
|---|---|
| Resolução do stream | `stream.paths[].resolution`; se o leitor decodificou outra, mostra `1280×720 → 640×480` |
| Taxa | `stream.paths[].mbps`, duas casas |
| FPS de captura | `video.capture_fps` |
| FPS de inferência | `video.infer_fps` |
| Latência estimada | `video.latency_ms`, arredondada para inteiro |
| Quadros perdidos | `video.dropped` |
| Tempo de stream | `stream.paths[].ready_for`, formatado `45 s` / `3 min 20 s` / `1 h 04 min` |
| Modelo | `model.weights_name` em verde, ou `nenhum modelo carregado` em cinza |

Os campos medidos no leitor mostram `—` enquanto `video.connected` for `false` —
número velho num painel de tempo real é pior que travessão.

Abaixo da grade, uma linha em fonte monoespaçada diz o que o leitor está fazendo:
`lendo rtsp://… · 221 quadros`, ou `leitor ocioso — nenhum cliente de vídeo e
nenhuma coleta ativa`, ou o erro com a contagem regressiva da próxima tentativa.
Reconexões acumuladas aparecem no fim da linha.

**Tabela de paths.** Continua embaixo, **oculta quando não há path ativo**, com
as colunas: `Path`, `Pronto` (`sim`/`não`), `Resolução`, `Taxa` (`0.34 Mbps`),
`Codecs`, `Parado há` (`—` quando zero).

### Painel "Modelo" (coluna da direita)

Entre o endereço RTMP e o lembrete do portal da DJI. Uma linha de texto com o
estado por extenso — as classes e o limiar quando há modelo, o caminho onde
largar os pesos quando não há, a mensagem de erro quando a carga falhou — e o
botão `Recarregar pesos`.

### Tela 2 — lista de datasets (`/datasets`)

Uma tabela, da versão mais recente para a mais antiga, com colunas `Versão`,
`Data`, `Duração`, `Imagens`, `Distribuição`, `Disco` e `Roboflow`.

A distribuição é uma barra empilhada de três cores (train azul, valid verde, test
âmbar) **com os números embaixo**: só a barra obrigaria o operador a estimar de
olho quantas imagens tem cada partição.

Sob a versão aparecem selos quando algo precisa de atenção — e só então:

| Selo | Quando |
|---|---|
| `manifesto desatualizado` | `drift.stale` (§8) |
| `sessão gravando` | a coleta foi interrompida e a versão nunca foi particionada |
| `divergente do Roboflow` | `divergence.any` (§9) |

Sem nenhum dataset, o lugar da tabela é ocupado por um estado vazio que explica
que datasets nascem da coleta na Home, com um botão para lá — em vez de uma
tabela de zero linhas.

### Tela 2b — detalhe de um dataset (`/datasets/{version}`)

Duas colunas (`1fr 380px`), como a Home.

**Faixas de aviso**, no topo, quando existirem:

- *Manifesto desatualizado* — a tabela `manifesto → disco` por partição com a
  diferença destacada, as duas proporções lado a lado, e um botão
  `Refazer o split a partir de raw/` dentro da própria faixa.
- *Divergência com o Roboflow* — as contagens dos três casos de §9 e a frase que
  fecha o assunto: excluir aqui não remove de lá.

**Galeria.** Três abas com a contagem ao lado do nome. Grade de miniaturas de
150 px mínimos, `loading="lazy"`, cada uma com caixa de seleção no canto
superior esquerdo e, quando a imagem já subiu, o selo verde `enviada` no direito.
Clicar na imagem abre o tamanho real num `<dialog>`; clicar fora fecha.

A barra acima da grade tem `Selecionar tudo`, a contagem de selecionadas e o
botão `Excluir N`, desabilitado com zero selecionadas. **A seleção não atravessa
partições**: trocar de aba zera a lista, porque a exclusão é por partição.

**Coluna da direita**, quatro painéis e uma zona de perigo: `Gravação` (dados do
`session.json`), `Split` (manifesto resumido, avisos do split renderizados como
na fatia 3 e o botão de refazer), `Enviar ao Roboflow` (formulário e progresso),
`Histórico` (o `edits.json`, do mais recente para o mais antigo) e
`Excluir dataset`, esta com borda vermelha.

**Modais**, todos `<dialog>` nativos:

| Modal | Confirmação |
|---|---|
| Excluir imagens | conta, aviso de que sai de `raw/` junto, aviso de quantas já subiram ao Roboflow, contagens e proporções depois |
| Excluir dataset | exige digitar a versão exata; o botão só habilita com o texto igual |
| Refazer o split | diz quantos quadros de `raw/` serão reparticionados e que as excluídas não voltam |
| Enviar ao Roboflow | workspace, projeto, batch, tags, contagem por partição e quantas serão puladas |

**Formulário de envio.** Workspace, projeto, batch (padrão: a versão) e tags
(padrão: `versão, drone`). O campo de chave é `type="password"` e **só aparece
quando não há chave configurada**; havendo, o lugar dele traz "Chave lida de
.env. Não é exibida nem gravada em disco.". Durante o envio, o formulário dá
lugar a uma barra de progresso, à linha de contagem (`137 de 205 enviadas · 2
falharam · train/000138_t68.51.jpg · ~30 s restantes`) e ao botão de cancelar.

### Tema

Escuro fixo (`#0d1117` de fundo), sem alternador. Layout em duas colunas
(`1fr 380px`) que colapsa para uma coluna abaixo de 900 px de largura na Home e
de 1000 px no detalhe do dataset. A lista de datasets é de coluna única, com
largura máxima de 1280 px.

---

## 4. Vídeo ao vivo — `/stream`

### Arquitetura

Três estágios desacoplados em `app/video.py`, cada um no seu ritmo:

```
RTSP ──► leitor (thread) ──► slot ──► worker (thread) ──► slot ──► N clientes
         sempre o último     de 1     detect + overlay    de 1     /stream
         quadro decodificado  quadro   + imencode          JPEG
```

Entre os estágios há um **slot de um quadro**, não uma fila. Publicar sobrescreve
o que estiver lá e incrementa `dropped`; o worker sempre pega o mais recente. É
isso que impede a latência de acumular quando a inferência é mais lenta que o
stream — com fila, nada se perderia e a latência cresceria sem teto.

Medido com inferência artificialmente lenta (200 ms/quadro) contra um stream de
30 fps, por 65 s: captura estável em 30,0 fps, inferência em 4,9 fps, latência
oscilando entre **208 e 236 ms** sem tendência de alta, e `dropped` crescendo
~25/s. A latência estabiliza em torno de um intervalo de inferência, que é o
mínimo teórico do arranjo.

A inferência roda **uma vez por quadro, não uma vez por cliente**: dois
navegadores abertos não dobram o custo, os dois leem do mesmo slot de saída.

### Consumidores

O RTSP só é consumido quando alguém precisa dele. A classe `Consumers` registra
quem precisa, com dois tipos:

| `kind` | Quem registra | Quando |
|---|---|---|
| `mjpeg` | o gerador de `GET /stream` | enquanto a resposta multipart estiver aberta |
| `collect` | a coleta da fatia 2 | enquanto uma sessão de gravação estiver aberta |

A decisão de fechar olha o **total**, nunca a contagem de clientes HTTP: durante
uma coleta pode não haver nenhum navegador aberto, e mesmo assim o leitor tem que
continuar. O tipo `collect` já é aceito pelo registro, mas nada o usa ainda.

Sem nenhum consumidor por `IDLE_CLOSE_S = 10.0` s, o leitor libera o
`VideoCapture` e o worker passa a dormir. Verificado: fechado o cliente MJPEG, o
`connected` vai a `false` e o path do MediaMTX perde o leitor.

### Reconexão

Backoff exponencial começando em `RECONNECT_MIN_S = 1.0` s e dobrando até o teto
de `RECONNECT_MAX_S = 10.0` s, zerado a cada conexão bem-sucedida. Durante a
espera, `retry_in_s` traz os segundos que faltam.

O gerador MJPEG **não** encerra quando não há sinal: emite um quadro sintético
(640×360, fundo `#121212`) com o título `Aguardando stream` e o motivo em até
três linhas, a ~1 fps. Verificado: com o publicador morto e depois religado, o
mesmo cliente MJPEG passou de quadros de ~9 kB (placeholder) para ~37 kB (vídeo
960×720) **sem reconectar**.

### Formato da resposta

```
status: 200
content-type: multipart/x-mixed-replace; boundary=frame
cache-control: no-cache, no-store
x-accel-buffering: no
```

Cada parte:

```
--frame
Content-Type: image/jpeg
Content-Length: <n>

<bytes do JPEG>
```

Qualidade do JPEG: `JPEG_QUALITY`, padrão 80.

### Sobreposição no quadro

Desenhada pelo worker, faixa preta de 26 px no topo:

- à esquerda, `30.0 fps  960×720  #906` — FPS de captura, resolução e contador
  de quadros da sessão;
- à direita, `sem modelo` em azul, ou `modelo ativo  N det` em verde;
- as caixas das detecções, com classe e confiança, quando houver (§5).

A sobreposição existe só para o operador olhar. O quadro cru fica preservado em
`Rendered.frame.image` — é ele que a coleta da fatia 2 vai gravar.

### O instante de captura viaja com o quadro

`Frame` carrega, além da imagem:

| Campo | Origem | Para quê |
|---|---|---|
| `captured_at` | `time.monotonic()` no `retrieve` | medir a latência de ponta a ponta |
| `captured_epoch` | `time.time()` | datar o quadro em disco |
| `session_started_at` | monotonic de quando esta conexão RTSP abriu | base do tempo relativo |
| `elapsed` (propriedade) | `captured_at - session_started_at` | nomear `000123_t12.50.jpg` na fatia 2 |

O tempo relativo no nome do arquivo é o que permite o split temporal por blocos
contíguos sem reabrir o banco. Por isso ele nasce aqui, junto com o quadro, e não
é recalculado na hora de gravar.

### Bloco `video` do payload

Capturado com um cliente MJPEG aberto e o `testsrc` publicando:

```json
{
  "connected": true,
  "source": "rtsp://localhost:8554/live/m4td",
  "error": null,
  "reconnects": 0,
  "retry_in_s": null,
  "consumers": {"mjpeg": 1, "collect": 0, "total": 1},
  "capture_fps": 30.0,
  "infer_fps": 30.0,
  "latency_ms": 1.9,
  "dropped": 38,
  "frames": 221,
  "capture_uptime_s": 6.5,
  "resolution": "960×720",
  "resolution_change": null,
  "detections": 0
}
```

| Campo | Como é medido |
|---|---|
| `connected` | há um `VideoCapture` aberto e entregando |
| `source` | URL RTSP em uso, montada com o path efetivo (§13) |
| `error` | motivo da última desconexão; `null` quando conectado |
| `reconnects` | quedas depois de uma conexão que já tinha funcionado |
| `retry_in_s` | segundos até a próxima tentativa; `null` fora da espera |
| `consumers` | contagem por tipo, mais `total` |
| `capture_fps` | quadros entregues pelo leitor, janela deslizante de 3 s |
| `infer_fps` | quadros que completaram detect + overlay + encode, mesma janela |
| `latency_ms` | do `captured_at` até o JPEG pronto, último quadro |
| `dropped` | quadros sobrescritos no slot sem ninguém consumir, desde a última conexão |
| `frames` | quadros decodificados nesta sessão |
| `capture_uptime_s` | segundos desde que esta conexão RTSP abriu |
| `resolution` | dimensões do último quadro **decodificado**, `W×H` (`×` é U+00D7) |
| `resolution_change` | ver abaixo |
| `detections` | detecções no último quadro renderizado |

Os dois primeiros segundos de uma conexão mostram `capture_fps` bem acima do
real (chegou a 249 fps num stream de 30) — o decoder drena de uma vez o backlog
que o MediaMTX tinha em buffer. Converge dentro da janela de 3 s, e é o mesmo
backlog que aparece como `dropped` inicial (~30 a 60 quadros).

`capture_fps` é medido no leitor e `infer_fps` no worker; com modelo carregado,
o segundo cai e o primeiro não — a diferença entre os dois é exatamente o que
vira `dropped`.

### Aviso de mudança de resolução

`resolution_change` fica preenchido quando a resolução decodificada muda:

```json
{"from": "1280×720", "to": "640×480", "at": 1787688213.69}
```

`at` é epoch em segundos. Três decisões:

- **A comparação atravessa reconexões.** `_resolution` não é zerada ao abrir uma
  conexão nova, de propósito: no FlightHub, trocar a qualidade do canal **derruba**
  a sessão RTSP, e a resolução nova só aparece na reconexão seguinte. Zerar ali
  apagaria o aviso justamente no caso que ele existe para pegar. Verificado
  matando o publicador em 1280×720 e religando em 640×480: o aviso apareceu.
- **Não é dispensável.** Não há botão de fechar. Enquanto a resolução oscila o
  problema segue ativo, e um dataset coletado nesse intervalo sai com resoluções
  misturadas.
- **Some sozinho** após `RESOLUTION_WARNING_S = 300.0` s sem nova troca. Quem
  decide é o servidor, em `stats()`; o cliente só reflete. Verificado: com 4 min
  o aviso ainda vem, com 5 min e 1 s vem `null`.

O campo interno `at_monotonic`, usado para essa expiração, nunca sai no payload.

---

## 5. Detector — `app/inference.py`

### O modelo é opcional

A aplicação precisa subir e funcionar sem nenhum modelo treinado: no começo do
projeto não existem pesos, e o objetivo da coleta é justamente criar o dataset
para treinar o primeiro. `Detector.detect(frame)` devolve `(frame, [])` — quadro
intacto, lista vazia — em vez de levantar.

Três estados, todos visíveis em `status()`:

| `loaded` | `error` | Significado | O que a tela mostra |
|---|---|---|---|
| `true` | `null` | inferindo de verdade | `MODELO ATIVO — best.pt · N classes` (verde) |
| `false` | `null` | não há arquivo de pesos — estado inicial do projeto | `SEM MODELO — vídeo cru, sem detecções` (amarelo) |
| `false` | string | havia pesos, mas a carga falhou | `MODELO NÃO CARREGOU — vídeo cru, sem detecções` (vermelho) |

O terceiro caso é o que acontece hoje se alguém largar um `best.pt` numa máquina
sem torch. Verificado — o vídeo continuou a 30 fps e a mensagem foi:

```json
{
  "loaded": false,
  "weights_path": "/workspaces/flyhub_connecting/data/models/best.pt",
  "weights_name": "best.pt",
  "weights_exists": true,
  "classes": [],
  "conf": 0.25,
  "error": "ultralytics indisponível (ModuleNotFoundError: No module named 'ultralytics')",
  "loaded_at": null,
  "mode": "passthrough"
}
```

`mode` é `"inferência"` ou `"passthrough"`, e existe para a interface não ter que
inferir o estado a partir de dois booleanos.

### Import preguiçoso

`from ultralytics import YOLO` acontece **dentro** de `_load()`, nunca no topo do
módulo. A aplicação importa e sobe numa máquina sem torch instalado — que é o
caso da máquina de desenvolvimento atual. Falha no import vira `error` e o modo
continua passthrough.

### Carga e recarga

- A primeira tentativa acontece na primeira checagem, não na importação.
- A checagem compara o **mtime** dos pesos com o da carga vigente, no máximo uma
  vez por segundo (`MTIME_CHECK_EVERY_S = 1.0`). Arquivo que aparece, muda ou
  some dispara recarga; sem mudança, o custo é um `stat()` por segundo.
- `_load` revalida o mtime **dentro** do lock, para que duas threads não
  carreguem o mesmo arquivo duas vezes.
- Uma exceção durante `predict()` derruba o detector para passthrough e registra
  o motivo. O vídeo não para; o operador vê o badge mudar de cor.

Dois pontos chamam a checagem:

| Quem | Quando |
|---|---|
| `detect()`, no worker de vídeo | a cada quadro, respeitando o intervalo de 1 s |
| `poll()`, no `_state()` do painel | a cada emissão do SSE (2 s) |

O segundo existe porque com o leitor ocioso ninguém chama `detect()`, e a tela
ficaria mostrando um estado velho enquanto o operador copia o `best.pt` para a
pasta. `poll()` pode carregar o modelo, que é lento, então roda em
`run_in_threadpool` — nunca no event loop. Verificado com o leitor ocioso: criar
o arquivo mudou o payload do SSE em ~2 s, e removê-lo voltou ao estado limpo.

`POST /api/model/reload` força a carga mesmo sem mudança de mtime (`force=True`),
para o caso de um arquivo reescrito com o mesmo timestamp.

### Detecções

`detect()` devolve uma lista de `Detection(name, conf, box)`, com `box` em pixels
`(x1, y1, x2, y2)`. `Detector.draw()` desenha as caixas no quadro recebido,
modificando no lugar — o worker sempre passa uma cópia, nunca o quadro cru.

Nomes de classe vêm de `model.names`. `MODEL_CONF` (padrão 0,25) é o limiar
passado ao `predict`.

---

## 6. Coleta — `app/collect.py`

Gravação de quadros do voo em `data/datasets/<versão>/raw/`, com o split (§7)
disparado ao salvar. Um único objeto global, `collect`, guarda o estado; não há
banco — o SQLite continua sem entrar.

### Máquina de estados

Cinco estados. Toda transição passa por um método que valida a origem sob um
`RLock`; não há transição implícita.

```
   ocioso ─start─► gravando ⇄ pausado ─save─► salvando ─► salvo ─dismiss─► ocioso
                       │ pause/resume │                       │
                       └──────────────┘                  (ou start direto)
```

| Estado | `state_label` | Significado |
|---|---|---|
| `ocioso` | `Ocioso` | nenhuma sessão. `session` é `null` |
| `gravando` | `Gravando` | a amostradora está salvando quadros |
| `pausado` | `Pausado` | sessão aberta, nada sendo salvo; o vídeo continua |
| `salvando` | `Salvando` | amostragem parada, fila escoando, split em execução |
| `salvo` | `Salvo` | split concluído; o resumo fica na tela até o `dismiss` |

| De | Evento | Para | Guarda |
|---|---|---|---|
| `ocioso`, `salvo` | `start` | `gravando` | as cinco pré-condições revalidadas no servidor |
| `gravando` | `pause` | `pausado` | — |
| `pausado` | `resume` | `gravando` | disco abaixo do limite |
| `gravando`, `pausado` | `save` | `salvando` | — |
| `salvando` | interno | `salvo` | split terminou (com ou sem erro) |
| `salvo` | `dismiss` | `ocioso` | — |

`salvando` não estava no diagrama da especificação e foi acrescentado porque o
split leva tempo: sem ele, ou a interface mentiria durante a cópia dos arquivos,
ou o `POST /api/collect/save` bloquearia o event loop.

Qualquer outro par (estado, evento) é recusado com `200` e `ok: false` — mesma
convenção do pipeline. Respostas reais:

```json
{"ok": false, "collect": {"state": "gravando", "...": "..."}, "error": "não é possível continuar em gravando"}
{"ok": false, "collect": {"state": "gravando", "...": "..."}, "error": "não é possível dispensar em gravando"}
{"ok": false, "collect": {"state": "gravando", "...": "..."}, "error": "já existe uma coleta em andamento (gravando)"}
```

A chave `error` vem **depois** de `collect` no dicionário: invertida, o `error`
do próprio status apagaria a mensagem da recusa. É o mesmo cuidado do
`pipeline.start`.

### Guarda de pré-condição

`GET /api/collect/preflight` avalia cinco checagens. As quatro primeiras são os
indicadores que já existiam na barra de estado; a quinta é o disco, incluída
porque a especificação já exige parar a coleta acima de 90% e começar uma
gravação que vai morrer em seguida não ajuda ninguém.

| Chave | Verde quando |
|---|---|
| `availability` | `stream.level == "green"` |
| `mediamtx` | container no ar **e** API respondendo |
| `tunnel` | processo `bore` vivo **e** endereço lido do log |
| `stream` | há ao menos um path com `ready: true` |
| `disk` | uso abaixo de `DISK_LIMIT_PCT` (90%) |

Resposta real com tudo verde (recortada):

```json
{
  "ok": true,
  "checks": [
    {"key": "availability", "label": "Disponibilidade", "ok": true, "level": "green",
     "detail": "Recebendo — 960×720 · 0.38 Mbps", "fix": null},
    {"key": "mediamtx", "label": "MediaMTX", "ok": true, "level": "green",
     "detail": "no ar, API respondendo", "fix": null},
    {"key": "tunnel", "label": "Túnel", "ok": true, "level": "green",
     "detail": "bore.pub:18473", "fix": null},
    {"key": "stream", "label": "Stream", "ok": true, "level": "green",
     "detail": "live/m4td", "fix": null},
    {"key": "disk", "label": "Disco", "ok": true, "level": "green",
     "detail": "41% usado · 16.8 GB livres", "fix": null}
  ],
  "failed": [],
  "next_version": "v0.0",
  "disk": {"ok": true, "percent": 41.2, "free_bytes": 18051837952, "free_human": "16.8 GB",
           "total_bytes": 33636024320, "limit_pct": 90.0, "over_limit": false},
  "defaults": {
    "interval": 2.0, "interval_options": [0.5, 1.0, 2.0, 5.0],
    "limit": 500, "dedup": true, "dedup_mad": 2.0,
    "margin": 5, "ratios": {"train": 0.7, "valid": 0.15, "test": 0.15}
  }
}
```

Com o publicador desligado (medido, 12 s depois do `kill`):

```json
{
  "ok": false,
  "checks": [
    {"key": "availability", "ok": false, "level": "red", "detail": "Sem stream",
     "fix": "Nenhum stream chegando. Suba o pipeline e publique o endereço RTMP no FlightHub."},
    {"key": "mediamtx", "ok": true,  "detail": "no ar, API respondendo"},
    {"key": "tunnel",    "ok": true,  "detail": "bore.pub:18473"},
    {"key": "stream", "ok": false, "level": "red", "detail": "nenhum path ativo",
     "fix": "Confira o endereço no FlightHub e religue o toggle do canal."},
    {"key": "disk", "ok": true, "detail": "41% usado · 16.8 GB livres"}
  ]
}
```

**Validação dupla.** O JS reimplementa as mesmas cinco checagens sobre o último
payload do SSE (`localChecks()`) e abre o modal de erro sem ir ao servidor — é o
que garante que o botão nunca dispare um start que vai falhar. O servidor
revalida dentro do `start`, porque o payload do cliente pode ter dois segundos
de idade e o disco pode ter enchido nesse intervalo. Resposta real de um start
recusado:

```json
{
  "ok": false,
  "collect": {"state": "ocioso", "...": "..."},
  "preflight": {"ok": false, "failed": [{"label": "Disponibilidade"}, {"label": "Stream"}]},
  "error": "pré-condições não atendidas: Disponibilidade, Stream"
}
```

Um start recusado **não cria diretório**: a versão só é criada depois de o
preflight passar. Verificado — depois da recusa acima, `data/datasets/` continha
apenas as versões anteriores.

### Versionamento — `app/datasets.py`

`vMAJOR.MINOR` com MINOR de 0 a 9 rolando para o próximo MAJOR:
`v0.0 → v0.1 → … → v0.9 → v1.0`.

A fonte da verdade é o disco, não um contador em memória: `next_version()` varre
`data/datasets/` a cada chamada, aceita apenas diretórios que casem com
`^v(\d+)\.(\d)$`, pega o maior par `(major, minor)` e incrementa. Sem nenhum
diretório, devolve `v0.0`. Depois de calcular, ainda incrementa em laço enquanto
o destino existir — uma pasta com nome fora do padrão é ignorada na varredura, e
sem esse laço a coleta poderia começar a escrever dentro de um dataset alheio.

`create_version()` usa `mkdir(exist_ok=False)`: duas coletas simultâneas na mesma
versão falham em vez de se misturarem.

### Amostragem

Uma thread (`collect-sampler`) com laço de `TICK_S = 0.1 s` que acumula três
cadências independentes: a amostragem no `interval` escolhido, as métricas de
impacto a cada 1 s, a checagem de disco a cada 5 s e o flush do `session.json` a
cada 2 s. O instante da próxima amostra é `next_sample += interval` — acumulado,
não `now + interval`, para não derivar; se o atraso passar de um intervalo
inteiro, ressincroniza.

A cada amostragem:

1. `video.latest()` — um **peek** no slot de saída do `video.py`, não um `take`.
   Peek não marca o quadro como consumido, então a coleta não rouba quadros dos
   clientes MJPEG nem infla o contador `dropped` do painel de conexão.
2. Se não há quadro novo (`frame.seq` igual ao da última amostra), conta
   `stale_skipped` e volta. É o que acontece com o RTSP caído ou reconectando: a
   sessão fica aberta e volta a gravar sozinha quando o vídeo voltar.
3. Deduplicação, quando ligada (abaixo).
4. Atribui o índice, monta o nome e **submete** para a fila. A amostradora nunca
   codifica nem escreve.

**O quadro salvo é o cru.** `rendered.frame.image` — sem a sobreposição de FPS,
resolução e caixas de detecção, que existe só para o operador olhar. Um dataset
com HUD queimado nos pixels ensinaria o modelo a ler o HUD.

**O tempo do nome vem do slot.** `t = frame.captured_at - captured_at do primeiro
quadro salvo`. Deliberadamente **não** é `frame.elapsed`: `elapsed` é relativo a
`session_started_at`, que o leitor rezera a cada reconexão do RTSP (§4), e uma
reconexão no meio do voo faria os nomes voltarem para `t0.00` — quebrando o split
temporal justamente no caso que a qualidade de canal em "Automático" torna comum.
`captured_at` é monotônico e não rezera. Nenhum timestamp é gerado na hora de
gravar.

O nome é `{índice:06d}_t{t:.2f}.jpg` — `000001_t0.00.jpg`, `000241_t120.10.jpg`.
O índice com seis dígitos faz a ordem lexicográfica coincidir com a temporal, o
que permite ao split trabalhar com um `sorted(os.listdir())`.

### Deduplicação

Comparação com o último quadro **aceito para escrita**: converte para cinza,
reduz para 128×128 com `INTER_AREA` e mede a diferença média absoluta
(`cv2.absdiff(...).mean()`). Abaixo de `DEDUP_MAD = 2.0` (escala 0–255), o quadro
é descartado e contado em `dedup_skipped`.

A redução para tamanho fixo não é só economia: sem ela, uma troca de resolução no
meio do voo faria o `absdiff` estourar por incompatibilidade de shape.

O último quadro de referência só é atualizado quando o quadro entra na fila. Se
a fila estiver cheia e o quadro for descartado, a referência continua sendo a do
último que realmente foi gravado.

Medido com cena parada (`color=c=blue`, o equivalente ao drone pairando), 15 s a
0,5 s de intervalo: **1 quadro salvo, 29 descartados** em 30 amostragens. Com
`testsrc` animado, 120 s a 0,5 s: **241 salvos, 0 descartados**.

### A coleta não compete com o vídeo

Exibir o vídeo é a função principal da tela. Quatro mecanismos garantem que a
coleta seja secundária, e o quarto mede se garantiram.

**1. A amostradora não faz I/O.** Decide, indexa e entrega. Encode e escrita são
dos workers.

**2. Fila limitada.** `queue.Queue(maxsize=WRITE_QUEUE_MAX)`, padrão 20. A
submissão é `put_nowait`; em `queue.Full` o quadro é descartado na hora e contado
em `io_dropped`, exibido na interface. Nunca bloqueia a amostragem e nunca cresce
sem teto — cada item da fila é um quadro decodificado inteiro (a 960×720, ~2 MB),
então uma fila ilimitada trocaria um problema de latência por um de memória.
O índice **não** é consumido no descarte: o próximo quadro aceito reaproveita o
mesmo número, e a numeração continua densa.

Medido com a fila artificialmente cheia e sem workers: 50 amostragens em
**0,8 ms**, `io_dropped = 50`, `next_index` intacto em 1, fila estável em 20/20.

**3. Workers com prioridade rebaixada.** Duas threads fixas (`WRITE_WORKERS = 2`,
constante, não configurável), cada uma chamando `os.nice(WRITER_NICE)` — padrão
`+10` — na primeira linha do laço. No Linux, `nice()` vale para a thread que
chama, não para o processo: medido, as threads de escrita ficam em `nice 10` e o
processo principal segue em `0`. Na disputa por CPU com o encode do MJPEG, quem
cede é a coleta.

**4. Medição do impacto.** No `start`, o FPS de captura e de inferência é lido de
`video.stats()` — a janela de taxa do leitor é de 3 s, então o valor já é a média
do vídeo *antes* de a coleta existir. Durante a gravação, uma amostra por segundo
alimenta uma janela de 15. Com pelo menos 5 amostras, `impact` compara a média
atual com a referência; acima de `IMPACT_THRESHOLD_PCT = 20%` de queda,
`degraded: true` acende um aviso amarelo no painel de coleta.

Se não havia vídeo ativo no início (nenhum navegador aberto e nenhuma coleta), a
referência não existe e o bloco diz isso em vez de inventar um número:

```json
{"available": false, "reason": "não havia vídeo ativo quando a coleta começou", "degraded": false}
```

**Medição de referência.** Coleta de 2 minutos a 0,5 s de intervalo, dedup ligada,
sobre `testsrc` 960×720 a 30 fps, com um cliente MJPEG aberto o tempo todo e o
detector em passthrough. Cada linha é a média de uma amostra por segundo de
`GET /api/stream/stats`:

| Janela | Amostras | FPS de captura | FPS de inferência | Latência |
|---|---|---|---|---|
| antes | 30 | 30,01 | 30,01 | 2,3 ms |
| durante | 120 | 30,00 | 30,01 | 2,5 ms |
| depois | 30 | 30,00 | 30,00 | 2,2 ms |

Variação de **0,0%** nos dois FPS, contra o limite de 20%. O `peak_drop_pct`
registrado pelo próprio servidor durante a coleta foi de **0,4%**. A sessão saiu
com 241 quadros salvos, 10,2 MB, e **zero** descartes por I/O ou erros de escrita
— a fila de escrita nunca passou de 0 de profundidade.

O custo por quadro é um `imencode` a cada 0,5 s contra 30 por segundo do MJPEG:
a 30 fps, a coleta responde por ~1,6% dos encodes. O resultado acima é o
esperado; a instrumentação existe para o caso em que não seja — inferência real
com torch, resolução maior, disco lento.

### Escrita

Cada job codifica em JPEG com `COLLECT_JPEG_QUALITY = 92` — mais alto que o 80 do
MJPEG, porque o MJPEG é para olhar e isto vai virar dataset — e grava em
`arquivo.jpg.tmp` seguido de `os.replace`. Um `kill -9` no meio nunca deixa um
JPEG truncado em `raw/`; deixa, no máximo, um arquivo a menos.

Falha de encode ou de escrita conta `write_errors` e registra a última mensagem
em `session.error`, visível na interface. O índice já foi consumido, então
sobra um buraco na numeração — inofensivo, porque o split lista os arquivos que
existem e só exige que o índice seja crescente.

### Limite e disco

Ambos **pausam**, não salvam. Salvar dispara o split, e essa decisão é do
operador; pausando, a sessão fica aberta e ele pode continuar se quiser.

- Limite atingido: `paused_reason = "limite de 500 quadros atingido"`. A contagem
  é por quadros aceitos para escrita (`next_index - 1`), não por `saved` — este é
  incrementado pelos workers e chegaria atrasado ao limite.
- Disco acima de 90%: `paused_reason = "disco acima de 90% — coleta interrompida"`.
  O `resume` também recusa enquanto o disco não baixar.

### `session.json`

Gravado incrementalmente a cada 2 s e em toda transição de estado, sempre por
`session.json.tmp` + `os.replace`. Uma queda no meio da escrita deixa o arquivo
anterior intacto, nunca um JSON truncado.

**O `session.json` é registro de auditoria, não fonte da verdade.** Tudo que o
split precisa — índice e tempo relativo — está no nome de cada arquivo em `raw/`.
Perder o último flush não compromete o dataset.

Verificado com `kill -9` durante uma gravação: **25 arquivos em `raw/`, nenhum
`.tmp` órfão**, `session.json` válido com `status: "gravando"` e 24 registros — o
25º ainda não tinha entrado no flush. O `split.run()` rodado depois, direto sobre
`raw/` e sem a aplicação no ar, recuperou os 25.

Documento completo de uma sessão salva (o array `frames` foi cortado; ele traz um
objeto `{index, file, t, epoch, seq, bytes}` por quadro):

```json
{
  "version": "v0.0",
  "status": "salvo",
  "started_at": 1787743488.7434304,
  "started_at_iso": "2026-08-26T11:24:48",
  "ended_at": 1787743609.1316772,
  "ended_at_iso": "2026-08-26T11:26:49",
  "duration_s": 120.39,
  "params": {"interval_s": 0.5, "limit": null, "dedup": true, "dedup_mad": 2.0, "jpeg_quality": 92},
  "time_base": "t = frame.captured_at - captured_at do primeiro quadro salvo (relógio monotônico do leitor, imune a reconexão do RTSP)",
  "counts": {"saved": 241, "dedup_skipped": 0, "stale_skipped": 0, "io_dropped": 0, "write_errors": 0},
  "bytes": 10734645,
  "paused_reason": null,
  "error": null,
  "impact": {
    "available": true, "reason": null,
    "baseline": {"available": true, "capture_fps": 30.1, "infer_fps": 30.0, "at": 1787743488.743511},
    "current": {"capture_fps": 30.0, "infer_fps": 30.0},
    "capture_drop_pct": 0.3, "infer_drop_pct": -0.0,
    "worst_drop_pct": 0.3, "peak_drop_pct": 0.4,
    "threshold_pct": 20.0, "degraded": false, "samples": 15
  },
  "stream": {"path": "live/m4td", "rtsp_url": "rtsp://localhost:8554/live/m4td", "resolution": "960×720"},
  "model": {"loaded": false, "weights": null},
  "frames": ["…241 registros…"]
}
```

### Consumidor de vídeo

O `start` registra a coleta em `video.consumers` com `kind="collect"`, e o
`_finalize` a remove no fim. É o que mantém o RTSP aberto durante uma gravação
sem nenhum navegador aberto.

Verificado: com zero clientes MJPEG e o leitor já desconectado
(`consumers.total == 0`, `connected: false`), iniciar a coleta reabriu o RTSP e
gravou 25 quadros em 14 s, com `consumers = {"mjpeg": 0, "collect": 1, "total": 1}`.
Os 3 `stale_skipped` do começo são o tempo de reabertura da conexão.

### Bloco `collect` do payload

Presente em `/events`, `/api/pipeline/status`, nas respostas de start/stop do
pipeline e, sozinho, em `GET /api/collect/status`. Capturado durante uma
gravação real:

```json
{
  "state": "gravando",
  "state_label": "Gravando",
  "active": true,
  "queue": {"depth": 0, "max": 20},
  "workers": 2,
  "disk": {"ok": true, "error": null, "percent": 41.3, "free_bytes": 18023632896,
           "free_human": "16.8 GB", "total_bytes": 33636024320,
           "limit_pct": 90.0, "over_limit": false},
  "limits": {"interval_options": [0.5, 1.0, 2.0, 5.0], "dedup_mad": 2.0, "margin": 5,
             "disk_limit_pct": 90.0, "impact_threshold_pct": 20.0},
  "session": {
    "version": "v0.4",
    "dir": "/workspaces/flyhub_connecting/data/datasets/v0.4",
    "started_at": 1787744004.2063031,
    "started_at_iso": "2026-08-26T11:33:24",
    "elapsed_s": 20.0,
    "interval_s": 0.5,
    "limit": 500,
    "dedup": true,
    "saved": 40,
    "bytes": 1775831,
    "bytes_human": "1.7 MB",
    "dedup_skipped": 0,
    "stale_skipped": 0,
    "io_dropped": 0,
    "write_errors": 0,
    "last_file": "000040_t19.54.jpg",
    "paused_reason": null,
    "error": null,
    "impact": {"...": "ver acima"},
    "result": null
  }
}
```

| Campo | Significado |
|---|---|
| `active` | `true` em `gravando`, `pausado` e `salvando` — há sessão em andamento |
| `queue.depth` | itens esperando escrita neste instante; chegar perto de `max` é o sinal de que `io_dropped` vai começar |
| `disk` | `statvfs` do sistema de arquivos de `data/datasets/` (ou do ancestral existente mais próximo) |
| `session.saved` | quadros efetivamente gravados, incrementado pelos workers |
| `session.stale_skipped` | amostragens sem quadro novo — leitor ocioso, RTSP caído ou reconectando |
| `session.io_dropped` | quadros descartados por fila cheia |
| `session.result` | `null` até o split terminar; depois, o resumo do manifesto (§7) |

Com a sessão em `ocioso`, `session` é `null` e o resto do bloco continua
presente — a interface precisa de `disk` e `limits` antes de qualquer coleta
existir.

---

## 7. Split temporal — `app/split.py`

### Por que não aleatório

Quadros consecutivos de vídeo são quase idênticos. Um split aleatório coloca o
quadro *N* em treino e o *N+1* em validação: o modelo memoriza em vez de
generalizar, e a métrica de validação sobe para valores que não se sustentam em
voo novo. É vazamento de dados, e é silencioso — nada no treino indica que
aconteceu.

A partição é por blocos contíguos de tempo, com uma margem de quadros descartados
em cada fronteira:

```
[────────── train ──────────][── valid ──][── test ──]
t=0                                               t=fim
                            ↑            ↑
                    margem: os N quadros de cada lado do corte
                    saem das três partições e ficam só em raw/
```

### Onde o split acontece

Em exatamente um lugar: `CollectService._finalize()`, na thread
`collect-finalizer`. Nenhum outro ponto do sistema chama `split.run()`.

```
POST /api/collect/save          event loop — responde na hora, com state "salvando"
  └─ collect.save()             gravando|pausado → salvando
       └─ thread _finalize():
            1. _stop_sampler.set() + sampler.join()      nenhum quadro novo entra
            2. queue.join() + _stop_writers()         ◄── BARREIRA
            3. session.json (status "salvando")
            4. split.run(base, session=resumo)        ◄── AQUI
            5. session.json (status "salvo") + resultado em memória
            6. state → salvo; libera o consumidor "collect" do vídeo
```

A barreira do passo 2 é requisito de correção, não zelo: `split.run()` monta a
partição a partir de `os.listdir(raw/)`, e um arquivo ainda na fila de escrita
sairia calado do manifesto — presente em `raw/`, ausente das três partições.

O passo 4 roda **em uma thread só, sem paralelismo**. O split acontece depois do
Salvar, quando o operador já não depende do vídeo em tempo real; não vale
disputar CPU com o encode do MJPEG por alguns segundos de cópia. Medido: **0,55 s
para 241 quadros** (10,2 MB).

`split.py` não importa `video` nem `collect`. Recebe um `Path` de versão e opera
sobre o que está em `raw/` — é o que torna o `resplit` da fatia 4 um reuso de uma
linha, permite reprocessar um dataset antigo e permite testar a regra sem drone,
sem servidor e sem OpenCV.

### O algoritmo

Sobre `sorted(os.listdir(raw))`, filtrado por `^(\d+)_t(-?\d+\.\d+)\.jpg$` — o
índice com seis dígitos faz a ordem lexicográfica ser a temporal. Arquivos fora
do padrão são ignorados e viram um aviso.

```
c1 = int(n·0.70 + 0.5)              c2 = c1 + int(n·0.15 + 0.5)
train = [0, c1−M)     valid = [c1+M, c2−M)     test = [c2+M, n)
descartados = [c1−M, c1+M) ∪ [c2−M, c2+M)
```

`int(x + 0.5)` em vez de `round()`: `round()` arredonda 0,5 para o par mais
próximo, e `round(2.5) == 2` deslocaria o corte de um quadro sem motivo.

**Encolhimento da margem.** Toda partição precisa de ao menos um quadro depois de
descontada a margem. `M` começa em `DEFAULT_MARGIN = 5` e desce até caber. Se nem
`M = 0` couber, ou se houver menos de `MIN_FRAMES_FOR_SPLIT = 10` quadros, tudo
vai para `train` e o manifesto registra um aviso de nível `error`. Nunca levanta
exceção por dataset pequeno, e nunca entrega uma partição vazia em silêncio.

Comportamento medido, com a proporção padrão:

| n | M aplicada | train | valid | test | descartados | avisos |
|---|---|---|---|---|---|---|
| 8 | — | 8 | 0 | 0 | 0 | `dataset_curto` (error) |
| 10 | 0 | 7 | 2 | 1 | 0 | `margem_reduzida` |
| 25 | 1 | 17 | 2 | 2 | 4 | `margem_reduzida`, 3× `proporcao_desviada_*` |
| 50 | 3 | 32 | 2 | 4 | 12 | `margem_reduzida`, 2× `proporcao_desviada_*` |
| 240 | 5 | 163 | 26 | 31 | 20 | nenhum |
| 1000 | 5 | 695 | 140 | 145 | 20 | nenhum |
| 5000 | 5 | 3495 | 740 | 745 | 20 | nenhum |

**Invariante verificado:** com `M > 0`, nenhum par de quadros de índice
consecutivo cai em partições diferentes. Com `M = 0` isso deixa de valer — é
exatamente o que o aviso `margem_reduzida` diz na tela, com essas palavras:
"Com margem 0, o último quadro de treino e o primeiro de validação são vizinhos
temporais — colete mais tempo antes de treinar."

A margem custa proporção quando o dataset é pequeno: são sempre ~4·M quadros
descartados, um número fixo que pesa muito em 50 quadros e nada em 5000. Por isso
o desvio maior que 5 pontos percentuais em relação à proporção pedida também vira
aviso, em vez de passar despercebido.

### Avisos

Lista de objetos `{code, level, message}`, com `level` em `warn` ou `error`.
Vão para o manifesto **e** para a tela: o painel de "salvo" renderiza cada um,
os de `error` em caixa vermelha e os de `warn` em amarelo. Quem gravou 8 quadros
por engano vê na tela que não há valid nem test, sem precisar abrir o JSON.

| `code` | `level` | Quando |
|---|---|---|
| `dataset_curto` | error | menos de 10 quadros; tudo foi para train |
| `sem_particao_possivel` | error | nem com margem 0 cabem três partições |
| `particao_vazia_<split>` | error | uma partição ficou vazia |
| `margem_reduzida` | warn | a margem aplicada é menor que a pedida |
| `proporcao_desviada_<split>` | warn | a proporção real ficou a mais de 5 p.p. da pedida |
| `arquivos_ignorados` | warn | havia arquivos em `raw/` fora do padrão de nome |
| `falha_ao_copiar` | error | ao menos um quadro não pôde ser copiado |

### Escrita em disco

`train|valid|test` são **apagados e recriados** antes da cópia — sem isso, um
resplit deixaria órfãos da partição anterior. Os quadros são **copiados**, não
movidos: `raw/` é mantido íntegro, que é o que permite refazer o split depois de
excluir imagens na fatia 4.

Resultado em disco de uma coleta de 2 min a 0,5 s:

```
data/datasets/v0.0/
├── raw/               241 arquivos, de 000001_t0.00.jpg a 000241_t120.10.jpg
├── train/images/      164
├── valid/images/       26
├── test/images/        31
├── session.json
└── split_manifest.json     26.640 bytes
```

Só `images/` é criado. Não há `labels/`: as anotações vêm do Roboflow, na fatia 5.

### `split_manifest.json`

Escrito por `tmp` + `os.replace`. Campos de topo:

| Campo | Conteúdo |
|---|---|
| `version` | `v0.0` |
| `created_at`, `created_at_iso` | epoch e ISO local |
| `strategy` | sempre `"temporal_contiguous"` |
| `reason` | por que a estratégia é essa, em texto |
| `source` | `"raw"` |
| `ratios` | proporções pedidas, normalizadas |
| `margin_requested`, `margin_applied` | a margem pedida e a que coube |
| `total_raw`, `counts` | total em `raw/` e contagem por partição, mais `discarded` e `kept` |
| `time_span` | `first_t`, `last_t`, `duration_s` |
| `boundaries` | uma entrada por fronteira, com o índice do corte, o último arquivo antes, o primeiro depois e o `gap_s` entre eles |
| `warnings` | a lista acima |
| `copy_errors` | falhas de cópia, arquivo a arquivo |
| `session` | o `session.json` inteiro, menos o array `frames` |
| `files` | `train`, `valid`, `test` e `discarded`, cada um com `{file, index, t}` — e `reason` nos descartados |

As fronteiras do dataset de 241 quadros, com a margem cheia:

```json
"boundaries": [
  {"between": ["train", "valid"], "cut_index": 169, "discarded_frames": 10,
   "last_before": "000164_t81.50.jpg", "first_after": "000175_t87.07.jpg",
   "t_before": 81.5, "t_after": 87.07, "gap_s": 5.57},
  {"between": ["valid", "test"], "cut_index": 205, "discarded_frames": 10,
   "last_before": "000200_t99.50.jpg", "first_after": "000211_t105.05.jpg",
   "t_before": 99.5, "t_after": 105.05, "gap_s": 5.55}
]
```

`gap_s` é o que se audita depois: 5,57 s entre o último quadro de treino e o
primeiro de validação, num stream a 30 fps. Sem esse número, "o split foi
temporal" é afirmação sem prova.

Um descartado, com o motivo registrado:

```json
{"file": "000165_t82.03.jpg", "index": 165, "t": 82.03, "reason": "margem de fronteira train|valid"}
```

### Resumo na resposta da API

`collect.status().session.result` traz um recorte do manifesto — tudo menos o
mapeamento arquivo a arquivo, que num dataset grande dominaria o payload do SSE.
Capturado de uma sessão curta, com a margem encolhida:

```json
{
  "version": "v0.4",
  "strategy": "temporal_contiguous",
  "counts": {"train": 32, "valid": 2, "test": 4, "discarded": 12, "kept": 38},
  "total_raw": 50,
  "ratios": {"train": 0.7, "valid": 0.15, "test": 0.15},
  "margin_requested": 5,
  "margin_applied": 3,
  "time_span": {"first_t": 0.0, "last_t": 25.62, "duration_s": 25.62},
  "boundaries": [
    {"between": ["train", "valid"], "cut_index": 35, "discarded_frames": 6,
     "last_before": "000032_t15.53.jpg", "first_after": "000039_t19.06.jpg",
     "t_before": 15.53, "t_after": 19.06, "gap_s": 3.53},
    {"between": ["valid", "test"], "cut_index": 43, "discarded_frames": 6,
     "last_before": "000040_t19.54.jpg", "first_after": "000047_t24.09.jpg",
     "t_before": 19.54, "t_after": 24.09, "gap_s": 4.55}
  ],
  "warnings": [
    {"code": "margem_reduzida", "level": "warn",
     "message": "A margem de descarte caiu de 5 para 3 quadro(s): com 50 quadros, a margem pedida esvaziaria uma das partições. A separação entre as partições ficou menor que a pedida."},
    {"code": "proporcao_desviada_train", "level": "warn",
     "message": "train ficou com 84% dos quadros mantidos, não os 70% pedidos — a margem de descarte pesa mais quanto menor o dataset."},
    {"code": "proporcao_desviada_valid", "level": "warn",
     "message": "valid ficou com 5% dos quadros mantidos, não os 15% pedidos — a margem de descarte pesa mais quanto menor o dataset."}
  ],
  "manifest": "v0.4/split_manifest.json"
}
```

### Falha no split

Um `SplitError` ou um `OSError` durante o passo 4 não impede a transição para
`salvo`: a sessão **foi** salva — os quadros estão em `raw/` —, e o que falhou
foi a partição. `session.error` recebe a mensagem, `result` fica `null`, e o
painel mostra a caixa vermelha com o texto "O split não produziu manifesto. Os
quadros continuam em raw/ e o dataset pode ser reparticionado."

---

## 8. Datasets — `app/datasets.py`

Leitura, edição e exclusão do que a coleta gravou. Além do versionamento e do
uso de disco (§6), este módulo responde o que a tela de datasets precisa saber.

### Quatro arquivos, quatro perguntas

| Arquivo | Pergunta que responde | Quem escreve |
|---|---|---|
| `session.json` | como a gravação aconteceu | `app/collect.py` |
| `split_manifest.json` | o que o split **decidiu** | `app/split.py` |
| `edits.json` | o que mudou **depois** do split | `app/datasets.py` |
| `roboflow.json` | o que foi enviado ao Roboflow | `app/roboflow_upload.py` |

Cada um responde uma coisa e nenhum é reescrito para concordar com outro.

### O manifesto é imutável entre splits

**Nenhuma exclusão toca o `split_manifest.json`.** Só `split.run()` escreve nele.

A tentação óbvia seria reescrevê-lo a cada imagem excluída, para que as
contagens batessem com o disco. É a decisão errada: o manifesto deixaria de
registrar o que o split fez e passaria a registrar o que sobrou, e aí não dá
mais para reproduzir nem auditar o experimento — que é a única razão de ele
existir. O manifesto descreve um **evento**; a pasta descreve um **estado**. São
fatos diferentes.

Em consequência:

1. As contagens exibidas vêm sempre do disco, contadas na hora por
   `live_counts()`. A lista e o detalhe nunca leem contagem do manifesto para
   exibir.
2. A divergência é calculada em toda leitura por `drift()` e mostrada na tela,
   não escondida. Nada é gravado: `stale`, `by_split` e as proporções são
   derivados.
3. `edits.json` é append-only e explica a diferença. Sem ele, a distância entre
   os 82 do manifesto e os 68 do disco não teria explicação daqui a três meses.

Bloco `drift` real, depois de excluir 14 imagens de train:

```json
{
  "stale": true,
  "reason": "14 imagem(ns) excluída(s) depois do split",
  "by_split": {"train": -14, "valid": 0, "test": 0},
  "total": -14,
  "proportions": {"train": 75.6, "valid": 10.0, "test": 14.4},
  "manifest_proportions": {"train": 78.8, "valid": 8.7, "test": 12.5},
  "manifest_counts": {"train": 82, "valid": 9, "test": 13}
}
```

Sem manifesto — versão nunca particionada — `stale` é `true` com
`reason: "sem manifesto — o split ainda não rodou nesta versão"` e `by_split`
todo `null`.

### Exclusão de imagens

**Excluir apaga da partição e de `raw/`.** As duas coisas, sempre.

Apagar só da partição faria o botão "Refazer o split a partir de `raw/`" —
oferecido justamente porque as proporções mudaram — **ressuscitar todas as
imagens excluídas**. O operador apagaria catorze quadros tremidos, clicaria em
refazer o split para corrigir a proporção, e os catorze voltariam. Entre a
irreversibilidade e um botão que desfaz o trabalho do operador, a
irreversibilidade é o mal menor — e por isso o modal diz, em palavras, que não
dá para desfazer.

Verificado: 14 imagens excluídas de train saíram das duas pastas, e o resplit
seguinte não trouxe nenhuma de volta.

Quem quer outra distribuição não exclui imagem: refaz o split.

**Defesa contra travessia de diretório.** Nenhum nome vindo do corpo ou da URL
vira caminho diretamente. `preview_delete` intersecta a lista pedida com
`os.listdir()` da partição, e só o que a listagem confirma é apagado.
`image_path` rejeita nome que não seja basename, nome começado por ponto e
qualquer resolvido cujo diretório-pai não seja exatamente a pasta da partição.
`require_version` só aceita `^v\d+\.\d$`. Medido, todos devolvem `404`:

```
/api/datasets/v0.0/image/train/../../../../etc/passwd   404
/api/datasets/v0.0/image/train/..%2F..%2Fsession.json   404
/api/datasets/v0.0/image/train/.hidden                  404
/api/datasets/..%2F..%2Fetc                             404
/api/datasets/v0.0/images/raw                           404
```

### `POST /api/datasets/{version}/images/preview-delete`

Chamada antes de abrir o modal. Diz o que a exclusão faria, e principalmente
quantas das imagens já subiram ao Roboflow — informação que só o servidor tem,
porque é ele quem lê o `roboflow.json`.

```json
{
  "version": "v0.0", "split": "train",
  "requested": 14, "count": 14, "targets": ["000011_t5.02.jpg", "…"],
  "missing": [],
  "uploaded_count": 0, "uploaded_files": [],
  "counts_before": {"train": 82, "valid": 9, "test": 13, "raw": 124, "total": 104},
  "counts_after":  {"train": 68, "valid": 9, "test": 13, "raw": 110, "total": 90},
  "proportions_after": {"train": 75.6, "valid": 10.0, "test": 14.4}
}
```

`missing` traz os nomes pedidos que não existem na partição — nomes velhos de
uma aba aberta antes de outra exclusão. Eles não entram em `targets`, e a
exclusão segue com o resto em vez de falhar inteira.

### `edits.json`

Append-only, escrito por `tmp` + `os.replace` sob um lock de processo.

```json
{"events": [
  {"at": 1787747, "at_iso": "2026-08-26T12:22:59", "action": "delete_images",
   "split": "valid", "count": 5, "files": ["000097_t48.03.jpg", "…"],
   "removed_from_raw": 5,
   "uploaded_before": ["000097_t48.03.jpg", "…"],
   "errors": []},
  {"at": …, "action": "resplit", "counts_before": {…}, "counts_after": {…},
   "margin_requested": 5, "margin_applied": 5, "warnings": […]},
  {"at": …, "action": "upload", "state": "parcial", "workspace": "acme",
   "project": "drone-m4td", "batch_name": "v0.0", "tags": ["v0.0", "drone"],
   "uploaded_total": 300, "uploaded_nesta_execucao": 300, "falhas": 200,
   "error": "200 imagem(ns) falharam"}
]}
```

`uploaded_before` é o que registra quais das imagens excluídas já estavam no
Roboflow no momento da exclusão. É a única forma de explicar depois por que os
dois lados divergem.

### Refazer o split

`POST /api/datasets/{version}/resplit` chama o **mesmo** `split.run()` da fatia
3, sem variante nenhuma, sobre o `raw/` no estado atual. As partições são
apagadas e reescritas, o manifesto é substituído pela decisão nova, o cache de
miniaturas é descartado inteiro (as miniaturas são endereçadas por partição, e o
resplit muda a partição das imagens) e um evento `resplit` entra no `edits.json`.
Depois disso `drift.stale` volta a `false`.

Medido: 124 quadros → exclusão de 14 → resplit de 110 → train 72 / valid 7 /
test 11, `stale: false`, e nenhuma das 14 excluídas de volta.

### Miniaturas

`GET /api/datasets/{version}/thumb/{split}/{filename}` gera sob demanda e cacheia
em `<versão>/.thumbs/<split>/<arquivo>`, invalidando por mtime. Largura de
240 px, qualidade 72.

Medido: 47.331 → 7.790 bytes, 960×720 → 240×180; a segunda requisição do mesmo
arquivo responde em 17 ms. Mandar o JPEG inteiro duzentas vezes para montar uma
grade desperdiça banda; gerar a miniatura a cada requisição desperdiça CPU.

A escrita usa `cv2.imencode` + `write_bytes`, não `cv2.imwrite`: o `imwrite`
escolhe o codec pela extensão do caminho, e o arquivo temporário termina em
`.tmp` — com o `imwrite` ele falha com *could not find a writer for the
specified extension*.

`.thumbs` começa com ponto por dois motivos: `split.list_raw()` ignora nomes
começados por ponto, e `dir_size()` pula o diretório, para que o tamanho
exibido seja o do dataset e não o do cache.

### Exclusão e resplit durante um envio

Excluir imagens, excluir o dataset e refazer o split são recusados com `400`
enquanto houver um envio **daquela versão** ao Roboflow em andamento:

```
há um envio de v0.0 ao Roboflow em andamento — cancele antes de refazer o split
```

Sem a guarda, o resplit moveria arquivos entre partições com o uploader no meio
do caminho, e a exclusão do dataset deixaria o envio gravando um `roboflow.json`
dentro de uma pasta recém-apagada. Um envio de **outra** versão não bloqueia
nada.

### Exclusão do dataset inteiro

`DELETE /api/datasets/{version}` exige `{"confirm": "v0.3"}` com a versão
exata; qualquer outra coisa devolve `400` com
`para excluir, digite exatamente v0.0 — recebido 'v0.1'`. No cliente, o botão do
modal só habilita quando o texto digitado bate exatamente. A resposta diz o que
foi apagado:

```json
{"ok": true, "version": "v0.0",
 "removed_counts": {"train": 74, "valid": 16, "test": 15, "raw": 105, "total": 105},
 "removed_bytes": 9877988, "removed_human": "9.4 MB"}
```

### Bloco de resumo, um por versão

Capturado de uma coleta real de 45 s:

```json
{
  "version": "v0.0",
  "created_at": 1787747191.9027865,
  "created_at_iso": "2026-08-26T12:26:31",
  "duration_s": 45.04,
  "session_status": "salvo",
  "interval_s": 0.5,
  "counts": {"train": 58, "valid": 4, "test": 8, "raw": 90, "total": 70},
  "bytes": 7487917,
  "bytes_human": "7.1 MB",
  "has_manifest": true,
  "strategy": "temporal_contiguous",
  "margin_applied": 5,
  "drift": {"stale": false, "reason": null, "by_split": {"train": 0, "valid": 0, "test": 0},
            "total": 0,
            "proportions": {"train": 82.9, "valid": 5.7, "test": 11.4},
            "manifest_proportions": {"train": 82.9, "valid": 5.7, "test": 11.4},
            "manifest_counts": {"train": 58, "valid": 4, "test": 8}},
  "roboflow": {"state": "nunca enviado", "uploaded": 0, "total": 0, "project": null,
               "at": null, "at_iso": null, "resumable": false},
  "divergence": {"any": false, "deleted_after_upload": 0, "discarded_after_upload": 0,
                 "resplit_after_upload": 0, "deleted_files": [], "discarded_files": [],
                 "moved_files": []}
}
```

`session_status` diferente de `salvo` marca uma coleta interrompida — a versão
tem `raw/` íntegro e nenhuma partição. `GET /api/datasets/{version}` devolve o
mesmo bloco mais `session`, `manifest` (sem o mapeamento arquivo a arquivo),
`edits`, `images` por partição e `uploaded_files`.

---

## 9. Roboflow — `app/roboflow_upload.py`

Envio de um dataset para um projeto do Roboflow, preservando a partição.

### O parâmetro que importa

Cada imagem sobe com `split=` explícito:

```python
project.upload(
    str(path),
    split=split,          # o argumento que preserva a partição
    batch_name=batch,     # a versão do dataset
    tag_names=list(tags), # a versão + "drone"
)
```

Sem `split=`, o Roboflow reparticiona por conta própria — e o split dele é
aleatório, o que desfaz inteiro o trabalho da fatia 3: quadros vizinhos no tempo
voltariam a cair em partições diferentes e o vazamento de treino na validação
estaria de volta, agora invisível porque aconteceu do outro lado da rede.

Por isso, **se o SDK instalado recusar o argumento `split`, a execução aborta**
em vez de subir sem ele. Um `TypeError` cuja mensagem cite `split` vira
`_SplitUnsupported`, o envio para no primeiro arquivo e o registro fica com
`state: "erro"` e o texto que explica o que fazer. Um dataset com a partição
errada é pior que nenhum dataset: parece pronto e mente na métrica.

Verificado contra o SDK instalado — `roboflow 1.4.1`, assinatura de
`Project.upload`:

```
['self', 'image_path', 'annotation_path', 'hosted_image', 'image_id', 'split',
 'num_retry_uploads', 'batch_name', 'tag_names', 'is_prediction', 'metadata', 'kwargs']
```

`batch_name` e `tag_names` levam a versão porque, meses depois, quando alguém
perguntar de qual voo veio determinada imagem, é a única resposta possível.
O padrão de `batch_name` é a versão; o de `tag_names` é `[versão, "drone"]`.

### A chave

Nunca é gravada em disco, nunca volta numa resposta de API, nunca entra em log.
Ela entra pelo corpo do `POST /api/roboflow/upload`, atravessa para o SDK e
morre ali. O `roboflow.json` não tem campo para ela.

Ordem de resolução, medida:

| Origem | Vence quando |
|---|---|
| `formulário` | o corpo traz `api_key` não vazia |
| `ambiente` | existe `ROBOFLOW_API_KEY` em `os.environ` |
| `.env` | o arquivo tem a linha `ROBOFLOW_API_KEY=…` |

A leitura do `.env` é de **uma linha só**: o painel deliberadamente não chama
`load_dotenv()`, porque carregar o arquivo inteiro mudaria o valor de outras
variáveis já lidas na importação dos módulos (§12). `_key_from_dotenv()` procura
a chave, ignora comentários e tira aspas.

`GET /api/roboflow/config` informa se há SDK e se há chave — nunca a chave, nem
mascarada:

```json
{"sdk_available": true, "sdk_error": null, "install_hint": "pip install roboflow",
 "has_key": false, "key_source": null, "key_var": "ROBOFLOW_API_KEY",
 "default_tags": ["drone"]}
```

A interface esconde o campo de senha quando `has_key` é verdadeiro e mostra
"Chave lida de .env. Não é exibida nem gravada em disco.". O JS zera
`#rf-key.value` assim que o envio começa, para não deixar a chave no DOM.

A saída padrão do SDK é capturada com `contextlib.redirect_stdout` e descartada
durante a construção do cliente e durante cada upload — nada que ele imprima
chega ao log do painel.

Verificado com uma chave inválida: `grep` por ela em `data/` e no log do painel
não encontrou nenhuma ocorrência, e o `roboflow.json` gravado não a contém.

### Import preguiçoso

`import roboflow` acontece dentro da thread de envio, nunca no topo do módulo —
mesmo tratamento dado ao `ultralytics` (§5). Sem o pacote instalado a aplicação
sobe, a tela de datasets abre e o painel de envio explica:

> O pacote roboflow não está instalado — o envio fica indisponível. Instale com:
> pip install roboflow

`roboflow` está no `requirements.txt`. Ele declara `opencv-python-headless>=4.10`
e **não** arrasta `opencv-python` (a variante com GUI, que exige `libGL`) nem
torch: a variante desktop fica atrás do extra `[desktop]`, que não é instalado.

### Execução

Uma thread (`roboflow-upload`), um envio por vez em todo o processo. `start()`
recusa com `ok: false` se já houver um em andamento, se a versão não existir, se
faltar workspace ou projeto, se não houver chave ou se não houver imagem nas
três partições. Recusas medidas:

```
cancelar sem envio  → nenhum upload em andamento (ocioso)
versão inexistente  → dataset v9.9 não existe
sem workspace       → workspace e projeto são obrigatórios
sem chave           → nenhuma chave disponível — informe no formulário ou defina ROBOFLOW_API_KEY
```

A lista de alvos é montada na ordem train, valid, test. Arquivos já presentes no
`uploaded` do registro são pulados — é o que faz retomar.

**Progresso.** `GET /api/roboflow/status` traz o bloco `progress`, e a tela de
detalhe o consulta a cada segundo enquanto o envio estiver ativo:

```json
{"version": "v0.0", "total": 205, "pending": 205, "skipped": 0, "done": 137,
 "failed": 2, "current": "000138_t68.51.jpg", "current_split": "train",
 "started_at": 1787746986.2, "elapsed_s": 61.4, "eta_s": 30.5,
 "message": "enviando para acme/drone-m4td"}
```

**Cancelamento** é cooperativo: um `threading.Event` conferido antes de cada
arquivo. A imagem em voo termina, e o estado vira `cancelado` — retomável.

**Falha parcial.** Uma falha isolada é registrada em `failures` e a execução
continua. Dez falhas seguidas interrompem com `state: "erro"` e a última
mensagem: o problema deixou de ser do arquivo, e insistir 500 vezes só demora
mais. Se ao fim houver qualquer falha, o estado é `parcial`, e a lista de
datasets mostra `parcial — 300 de 500 enviadas`. Enviar de novo retoma de onde
parou.

Estados possíveis: `ocioso`, `enviando`, `concluído`, `parcial`, `cancelado`,
`erro`. Os três últimos são `resumable`.

### `roboflow.json`

Gravado a cada 5 imagens durante a execução e no fim, sempre atômico. Registro
real de uma tentativa com chave inválida:

```json
{
  "version": "v0.0",
  "workspace": "nao-existe-xyz",
  "project": "nao-existe-xyz",
  "batch_name": "v0.0",
  "tags": ["v0.0", "drone"],
  "state": "erro",
  "started_at": 1787746998.1,
  "finished_at": 1787746998.4,
  "error": "não foi possível abrir o projeto (RuntimeError: {\"error\":{\"message\":\"This API key does not exist (or has been revoked).\",\"status\":401,…}})",
  "uploaded": {},
  "failures": [],
  "totals": {"selected": 90, "uploaded": 0, "failed": 0, "skipped": 90},
  "runs": [{"at": 1787746998.4, "state": "erro", "uploaded_nesta_execucao": 0,
            "falhas": 0, "puladas": 0, "duracao_s": 0.0, "error": "…"}]
}
```

`uploaded` é um mapa `{arquivo: {"split", "at", "batch"}}`. **A chave é o nome do
arquivo, não `split/arquivo`**: um resplit pode mudar a partição de uma imagem, e
chavear por partição faria a retomada reenviá-la, criando duplicata no Roboflow.

`runs` acumula um resumo por execução — é o que permite ler a história de um
envio que foi parcial, retomado e concluído.

### Divergência com o Roboflow

Quando uma imagem sobe e depois é excluída aqui, os dois lados divergem em
silêncio: o `roboflow.json` continua listando um arquivo que não existe mais no
disco.

**Nada é sincronizado nem apagado por API.** O Roboflow é a fonte de verdade
para o que está lá; aqui só se torna visível que os dois lados deixaram de
bater. `roboflow_divergence()` compara o registro com o disco e classifica em
três casos, que têm causas bem diferentes:

| Contador | Significa |
|---|---|
| `deleted_after_upload` | não está em nenhuma partição **nem** em `raw/` — foi excluída |
| `discarded_after_upload` | não está em nenhuma partição **mas** continua em `raw/` — um resplit a jogou na margem de descarte |
| `resplit_after_upload` | está numa partição **diferente** daquela em que subiu |

Separar os dois primeiros não é preciosismo: contá-los juntos faria um resplit
rotineiro — que sempre descarta ~4·M quadros nas fronteiras — ser reportado como
exclusão em massa. Medido: depois de excluir 5 imagens já enviadas e refazer o
split, a contagem correta é 5 excluídas e 4 na margem, não 9 excluídas.

Três lugares mostram isso:

1. **No modal de exclusão**, antes de qualquer coisa ser apagada:
   > 5 destas já foram enviadas ao Roboflow. Excluir aqui não remove de lá —
   > faça isso pela interface do Roboflow se necessário.
2. **No `edits.json`**, no campo `uploaded_before` do evento.
3. **Na tela de detalhe**, numa faixa amarela com as contagens, e como selo
   `divergente do Roboflow` na lista.

Na galeria, cada miniatura já enviada leva o selo `enviada` no canto — a
divergência começa a ser visível antes de o operador clicar em excluir.

---

## 10. Semáforo

Calculado em `Monitor._traffic_light` (`app/monitor.py`), avaliado a cada ciclo
de polling (2 s). Constante única: `STALE_AFTER_S = 10.0`.

Ordem de avaliação — a primeira regra que casar decide:

| # | Condição | `level` | `label` |
|---|---|---|---|
| 1 | `api_ok` é `false` | `red` | `MediaMTX não responde` |
| 2 | nenhum path com `ready: true` (lista vazia ou todos não prontos) | `red` | `Sem stream` |
| 3 | existe path com `ready` **e** `stalled_for < 10.0` **e** `mbps > 0` | `green` | `Recebendo — {resolução} · {mbps} Mbps` |
| 4 | há path pronto mas nenhum satisfaz a regra 3 | `yellow` | `Conectado, sem dados há {N}s` |

Detalhes exatos:

- **Regra 3** escolhe, entre os paths que satisfazem a condição, o de **maior
  `mbps`**. A resolução vem desse path; se ele não expuser dimensões, o texto usa
  `resolução desconhecida`. O valor é formatado com **duas casas** (`0.34 Mbps`).
- **Regra 4** escolhe o path de **maior `stalled_for`** e formata **sem casas
  decimais** (`há 14s`).
- `api_ok` é `true` quando `GET {MEDIAMTX_API}/v3/paths/list` responde 2xx dentro
  de 1,5 s; qualquer `httpx.HTTPError` (conexão recusada, timeout, status ruim)
  torna a chamada falha, zera a lista de paths e limpa o histórico de bytes.

### Como `stalled_for` é medido

O campo comparado é **`bytesReceived`** do item do path, e o que importa é a
variação, não o valor. A cada ciclo o monitor guarda, por nome de path,
`{bytes, ts, changed_at, rate_bps}` usando `time.monotonic()`:

- `delta = max(bytesReceived_atual − bytesReceived_anterior, 0)`
- se `delta > 0`, `changed_at` vira o instante atual;
- `stalled_for = agora − changed_at`, arredondado a **1 casa decimal**.

Ou seja: `stalled_for` é o tempo desde o último ciclo em que chegaram bytes
novos, e não desde o início do path. Um path recém-descoberto entra com
`stalled_for = 0.0`.

Quando um path desaparece da listagem, sua entrada é removida do histórico;
quando a API cai, o histórico inteiro é limpo. Nos dois casos, se o path
reaparecer, ele volta a ser tratado como recém-descoberto.

### Como `mbps` é calculado

Não vem do MediaMTX — é derivada local, com suavização exponencial de fator 0,5:

```python
dt   = max(agora − ts_anterior, 1e-6)          # segundos, time.monotonic()
delta = max(bytes_atual − bytes_anterior, 0)   # bytes
rate_bps = 0.5 * rate_bps_anterior + 0.5 * (delta * 8 / dt)
mbps = round(rate_bps / 1e6, 2)                # divisor decimal: 1e6, não 2^20
```

Consequências práticas:

- Unidade: **megabits por segundo**, base decimal.
- O primeiro ciclo de um path sempre dá `mbps = 0.0` — não há amostra anterior
  para derivar.
- Por ser média exponencial de fator 0,5, o valor leva alguns ciclos (~4–6 s)
  para convergir depois de uma mudança de taxa, e não cai a zero instantaneamente
  quando o fluxo para: decai pela metade a cada ciclo.
- `delta` tem piso zero, então um reinício do MediaMTX (que zera o contador) não
  produz taxa negativa.

### Transição verde ⇄ amarelo

Um path que acabou de aparecer tem `mbps = 0.0` e `stalled_for = 0.0`, o que
falha a regra 3 e cai na regra 4 — o painel pode mostrar
`Conectado, sem dados há 0s` por um ciclo (~2 s) antes de ficar verde. Quando o
fluxo para de verdade, a passagem para amarelo não espera os 10 s: basta `mbps`
decair até `0.0` no arredondamento de duas casas. O limiar de 10 s importa no
sentido oposto — impede que uma oscilação momentânea de `mbps` derrube o verde
enquanto ainda chegam bytes.

---

## 11. Passos do start

Quatro passos, nesta ordem, com estes nomes exatos no relatório:

| # | Nome | O que faz | Timeout |
|---|---|---|---|
| 1 | `MediaMTX` | valida o arquivo de config; `docker rm -f mtx`; `docker run -d --name mtx --restart unless-stopped -v <config>:/mediamtx.yml -p 1935:1935 -p 8554:8554 -p 8888:8888 -p 9997:9997 bluenviron/mediamtx:latest` | 60 s no `rm`, **180 s** no `run` |
| 2 | `API` | tenta `GET {MEDIAMTX_API}/v3/paths/list` a cada 1 s até responder | **15 s** (`API_TIMEOUT_S`) |
| 3 | `Túnel` | `pkill -f "bore local"`, espera 0,5 s, zera `/tmp/bore.log` e sobe `bore local 1935 --to bore.pub` desanexado (`start_new_session`), com stdout e stderr no log | 15 s no `pkill`; o `Popen` não bloqueia |
| 4 | `Endereço` | relê `/tmp/bore.log` a cada 0,5 s procurando `listening at (\S+?):(\d+)` | **20 s** (`TUNNEL_TIMEOUT_S`) |

`detail` de cada passo quando dá certo:

| Passo | `detail` |
|---|---|
| `MediaMTX` | `container mtx no ar` |
| `API` | `respondendo em :9997` |
| `Túnel` | `bore local 1935 --to bore.pub` (o destino reflete `BORE_TO`) |
| `Endereço` | o endereço cru, ex. `bore.pub:49934` |

Mensagens de falha:

| Passo | Mensagem |
|---|---|
| `MediaMTX` | `config não encontrado: <caminho>` ou o stderr do `docker run`, truncado em 400 caracteres |
| `API` | `API não respondeu em 15s. Veja: docker logs mtx` |
| `Endereço` | `túnel não subiu. <últimas 3 linhas do /tmp/bore.log>`, truncado em 400 caracteres |

### O que acontece quando um passo falha

A sequência é interrompida na primeira exceção — não há retentativa nem passo
opcional. Então:

1. O passo que estava em `running` vira **`error`** e recebe a mensagem no `detail`.
2. Todos os passos ainda em `pending` viram **`skipped`**, com `detail` vazio.
3. `pipeline.error` recebe a mesma mensagem.
4. `busy` volta a `false` (o `finally` garante isso mesmo em falha).
5. A resposta HTTP é `200` com `ok: false`.

Nada é desfeito: se o passo 4 falhar, o container do passo 1 continua no ar e o
processo `bore` do passo 3 continua vivo. Não há rollback.

O passo 4 também aborta antes do timeout se descobrir que o processo `bore`
morreu — nesse caso não espera os 20 s inteiros.

### Passos do stop

Dois passos, ordem inversa: `Túnel` (`pkill -f "bore local"`, 15 s) e depois
`MediaMTX` (`docker rm -f mtx`, 60 s). `detail` é `encerrado` se o comando saiu
com código 0, `já estava parado` caso contrário. O stop não é abortado por um
passo que não encontrou nada para matar.

### Exclusão mútua

`start` e `stop` compartilham a flag `_busy` protegida por um `threading.Lock`.
Uma segunda chamada enquanto a primeira roda é recusada com `ok: false` sem
executar nada. A recusa devolve `{"ok": false, **snapshot(), "error": "pipeline
já está em operação"}` — nessa ordem, para que a chave `error` do snapshot não
sobrescreva a mensagem da colisão. A coleta segue a mesma convenção (§6).

---

## 12. Variáveis de ambiente

Nenhuma é obrigatória. Todas são lidas **na importação do módulo** — mudar depois
exige reiniciar o painel. O `.env` do repositório **não** é carregado pelo painel
(não há chamada a `load_dotenv` em `app/`); a única exceção é `ROBOFLOW_API_KEY`,
que `app/roboflow_upload.py` lê do arquivo linha a linha, no momento do uso, sem
tocar em `os.environ` — carregar o `.env` inteiro mudaria o valor das outras
variáveis já lidas na importação.

| Variável | Padrão | Lida em | Efeito |
|---|---|---|---|
| `STREAM_PATH` | `live/m4td` | `app/pipeline.py` | Path usado no `rtmp_url`, `rtsp_url` e `hls_url` enquanto nenhum start passar `stream_path` explícito. É o mesmo nome de variável que o `start.sh` já usava. |
| `MEDIAMTX_API` | `http://localhost:9997` | `app/pipeline.py` | Base da API do MediaMTX. `PATHS_LIST_URL` é essa base + `/v3/paths/list`, e vale tanto para o passo `API` do start quanto para o polling do monitor. Não muda a porta publicada pelo `docker run`, que é fixa. |
| `BORE_TO` | `bore.pub` | `app/pipeline.py` | Destino do `bore local 1935 --to <BORE_TO>`. Permite apontar para um servidor bore próprio. |
| `PANEL_PORT` | `8080` | `run.sh` | Porta do uvicorn. O padrão é 8080 e não 8000 porque a 8000 costuma estar ocupada pelo `mkdocs serve` deste repositório. |
| `MODEL_WEIGHTS` | `data/models/best.pt` (relativo à raiz) | `app/inference.py` | Arquivo de pesos. Não precisa existir: sem ele o detector fica em passthrough (§5). |
| `MODEL_CONF` | `0.25` | `app/inference.py` | Limiar de confiança passado ao `predict` do Ultralytics. |
| `JPEG_QUALITY` | `80` | `app/video.py` | Qualidade do JPEG do MJPEG, 0–100. |
| `DATASETS_DIR` | `data/datasets` (relativo à raiz) | `app/datasets.py` | Onde as versões são criadas. O `statvfs` do bloco `disk` mede o sistema de arquivos desta pasta — ou do ancestral existente mais próximo, quando ela ainda não existe. |
| `DISK_LIMIT_PCT` | `90` | `app/datasets.py` | Acima disto o preflight reprova, o `resume` recusa e uma coleta em andamento é pausada. |
| `DEDUP_MAD` | `2.0` | `app/collect.py` | Diferença média absoluta (escala 0–255, sobre o cinza reduzido a 128×128) abaixo da qual dois quadros são considerados o mesmo. |
| `WRITE_QUEUE_MAX` | `20` | `app/collect.py` | Tamanho da fila de escrita. Cheia, o quadro é descartado e contado em `io_dropped`. Cada item é um quadro decodificado — subir muito troca latência por memória. |
| `WRITER_NICE` | `10` | `app/collect.py` | Incremento de `nice` aplicado por cada thread de escrita a si mesma. |
| `COLLECT_JPEG_QUALITY` | `92` | `app/collect.py` | Qualidade do JPEG gravado no dataset. Mais alta que a do MJPEG de propósito: o MJPEG é para olhar, isto vira material de treino. |
| `ROBOFLOW_API_KEY` | — | `app/roboflow_upload.py` | Chave do Roboflow. Lida de `os.environ` e, se não estiver lá, de uma **única linha** do `.env`. Nunca é gravada, exibida nem logada (§9). |
| `OPENCV_FFMPEG_CAPTURE_OPTIONS` | `rtsp_transport;tcp\|stimeout;5000000` | `app/video.py` | Definida com `setdefault`, então um valor já exportado no ambiente vence. TCP evita perda de pacotes; o `stimeout` (5 s, em microssegundos) impede que um servidor morto deixe o `VideoCapture` pendurado na abertura. |

Valores fixos no código, sem variável de ambiente: nome do container (`mtx`),
imagem (`bluenviron/mediamtx:latest`), portas publicadas
(1935, 8554, 8888, 9997), caminho do config (`config/mediamtx.yml` relativo à
raiz do repositório), log do túnel (`/tmp/bore.log`), porta local do túnel
(1935), intervalos de 2 s e limiar de 10 s, além das constantes de vídeo
(`IDLE_CLOSE_S = 10.0`, `RECONNECT_MIN_S = 1.0`, `RECONNECT_MAX_S = 10.0`,
`RESOLUTION_WARNING_S = 300.0`, janela de taxa de 3 s) e de modelo
(`MTIME_CHECK_EVERY_S = 1.0`).

Da coleta e do split, também fixos: `WRITE_WORKERS = 2` (teto deliberado — mais
threads disputariam CPU com o encode do MJPEG), `TICK_S = 0.1`,
`METRICS_EVERY_S = 1.0`, `METRICS_WINDOW = 15`, `MIN_METRICS_SAMPLES = 5`,
`IMPACT_THRESHOLD_PCT = 20.0`, `MIN_BASELINE_FPS = 1.0`,
`DISK_CHECK_EVERY_S = 5.0`, `SESSION_FLUSH_EVERY_S = 2.0`, `DEDUP_SIZE = 128`,
as opções de intervalo `(0.5, 1.0, 2.0, 5.0)`, e no split
`DEFAULT_RATIOS = 70/15/15`, `DEFAULT_MARGIN = 5`,
`MIN_FRAMES_FOR_SPLIT = 10`, `PROPORTION_TOLERANCE_PP = 5.0` e `MAX_MINOR = 9`.

Dos datasets e do Roboflow: `THUMB_WIDTH = 240`, `THUMB_QUALITY = 72`,
`THUMBS_DIR = ".thumbs"`, `MAX_CONSECUTIVE_FAILURES = 10`, `FLUSH_EVERY = 5` e
`DEFAULT_TAGS = ("drone",)`.

---

## 13. Reconciliação

O painel **não guarda** o estado do pipeline em memória entre requisições. Toda
resposta de `snapshot()` é medida no sistema no momento da chamada, o que
significa que subir o painel com o pipeline já rodando — por `start.sh`, por
outra sessão, ou por um painel anterior — resulta na tela correta, sem precisar
clicar em nada.

| O que | Como é detectado |
|---|---|
| Container MediaMTX | `docker inspect -f '{{.State.Running}}' mtx` — considera no ar se o comando sai com código 0 **e** o stdout, sem espaços, é exatamente `true`. Timeout de 15 s. |
| API do MediaMTX | `GET {MEDIAMTX_API}/v3/paths/list` com timeout de 1,5 s (a thread do monitor; o campo é `stream.api_ok`) |
| Túnel | `pgrep -f "bore local"` — vivo se o código de saída for 0. Timeout de 10 s. |
| Endereço | lê `/tmp/bore.log` inteiro, aplica a regex `listening at (\S+?):(\d+)` e usa a **última** ocorrência, montada como `host:porta` |
| Path | `pipeline.effective_stream_path()` lê os paths do monitor: se o path configurado estiver entre os ativos, ele vence; senão vale o de maior `mbps`; sem nenhum path, cai no configurado |

O endereço RTMP é remontado a cada chamada como
`rtmp://{endereço do log}/{stream_path}` — não é memorizado em nenhum lugar.
O log só é lido quando `pgrep` confirma o processo vivo; se o túnel estiver
morto, `tunnel.address` e `rtmp_url` saem `null` mesmo com o log cheio de
endereços antigos.

Usar a última ocorrência da regex é o que torna o log acumulável entre reinícios.
Ainda assim, o passo 3 do start zera o arquivo antes de subir o `bore` novo, para
que uma falha no passo 4 não deixe o painel exibindo o endereço da execução
anterior como se fosse o atual.

Verificado em execução: com o container e o túnel já de pé (subidos pelo
`start.sh` antes do painel existir), o primeiro `GET /api/pipeline/status` já
devolveu `mediamtx.running: true`, `tunnel.running: true` e o `rtmp_url` correto
recuperado do log.

**Path em execução, recuperado.** `_stream_path` continua voltando ao valor de
`STREAM_PATH` a cada reinício do painel, mas isso não contamina mais o endereço:
`snapshot()` monta `rtmp_url`, `rtsp_url` e `hls_url` com o path **efetivo**, e
`app/video.py` lê o RTSP do mesmo lugar. Um pipeline iniciado por outra sessão
com `live/m4td-a1b2c3` aparece com o sufixo certo, e `path_detected: true` marca
que o nome veio do MediaMTX e não da configuração local.

O import de `monitor` dentro de `active_path_name()` é local de propósito:
`monitor` importa de `pipeline`, e no topo seria ciclo.

**O que a reconciliação não recupera:** a lista `steps` começa vazia (`[]`) até o
primeiro start/stop feito pelo painel. Ela é histórico do painel, não estado do
sistema, e não há de onde recuperá-la.

---

## 14. Limitações conhecidas

**Endereço RTMP continua visível com o MediaMTX parado.** `rtmp_url` depende
apenas do túnel: com `bore` vivo e container morto, o campo segue verde e o botão
de copiar habilitado — está no estado C de §2. Não é imprecisão: o túnel de fato
escuta naquele endereço; o que falta é quem consuma do outro lado. O operador
percebe pelo cartão MediaMTX em vermelho e pelo semáforo `MediaMTX não responde`,
mas nada no próprio campo RTMP indica o problema.

**Botão de copiar depende de contexto seguro.** O caminho normal é
`navigator.clipboard.writeText`, usado só quando `window.isSecureContext` é
verdadeiro. Num Codespace acessado por HTTP simples isso é falso, e o código cai
num fallback com `document.execCommand("copy")` sobre um `<textarea>` temporário
fora da tela — API obsoleta, que alguns navegadores podem remover. Se o fallback
também falhar, o botão vira `Falhou` e fica assim até o endereço mudar; a
alternativa é selecionar o texto do campo, que tem `user-select: all`.

**`busy: true` quase nunca chega à tela.** Um start completo leva ~1,6 s, menos
que o intervalo de 2 s do SSE, então na maioria das vezes nenhum frame captura a
janela ocupada. É por isso que o JS mantém uma flag local `pending` para
desabilitar os botões durante o POST — confiar só em `busy` deixaria os botões
clicáveis no meio da operação.

**`pkill -f "bore local"` e `docker rm -f mtx` não distinguem dono.** O start e o
stop matam qualquer processo cuja linha de comando contenha `bore local` e
removem qualquer container chamado `mtx`, tenham sido criados pelo painel ou não.
Isso é intencional — é o mesmo comportamento do `start.sh` —, mas significa que
dois painéis na mesma máquina brigam entre si, e que um `bore` de outro projeto
seria derrubado junto.

**Sem autenticação e sem CSRF.** O `run.sh` publica em `0.0.0.0` e qualquer um
que alcance a porta pode iniciar ou parar o pipeline. Como o path do stream é a
única credencial do endpoint RTMP, quem lê `GET /api/pipeline/status` obtém o
endereço completo de publicação.

**Falha de start não faz rollback.** Um erro no passo 4 deixa o container do
passo 1 no ar e o `bore` do passo 3 vivo. O caminho de recuperação é clicar em
parar e iniciar de novo.

**O relatório de passos é histórico, não estado.** `steps` descreve o último
start/stop e não é invalidado quando o container cai depois. Os quatro passos
podem estar `ok` com o MediaMTX morto, como no estado C de §2.

**Sem persistência.** Reiniciar o painel zera `steps`, `error`, o path
configurado e todos os contadores de vídeo (`dropped`, `reconnects`, o aviso de
resolução). Não há banco: o SQLite entra com a coleta.

**O semáforo ignora paths não prontos.** Um path existente com `ready: false`
conta como "Sem stream" (vermelho), embora apareça na tabela de paths da esquerda
com `Pronto: não`.

**A resolução exige `tracks2[].codecProps`.** Em versões do MediaMTX que só
expõem `tracks[]` (lista de nomes de codec), `resolution` sai `null` e o rótulo
verde vira `Recebendo — resolução desconhecida · X Mbps`. A instalação atual
(`bluenviron/mediamtx:latest`) expõe `tracks2` com `width`/`height`.

**A latência medida não é a latência real de ponta a ponta.** `latency_ms` conta
do instante em que o OpenCV entregou o quadro até o JPEG ficar pronto — mede o
que o painel controla. O que está antes (encoder da aeronave, rede, buffer do
MediaMTX) não é medido e é a maior parte do atraso percebido. O rótulo na tela é
"Latência estimada".

**`capture_fps` mente nos primeiros segundos.** O decoder drena o backlog do
MediaMTX assim que conecta, e a janela de 3 s registra isso como taxa real —
foram 249 fps num stream de 30. Converge sozinho.

**O aviso de resolução não distingue troca de encoder de troca de path.** Se o
path ativo mudar para outro publicador com resolução diferente, o aviso dispara
igual, dizendo que a resolução mudou. Do ponto de vista do dataset o efeito é o
mesmo, mas a explicação na tela cita o FlightHub, que pode não ser a causa.

**Um cliente MJPEG lento não é desconectado.** O gerador escreve no ritmo do
cliente; um navegador travado só faz o próprio `take` acumular timeouts, sem
afetar os outros nem o leitor — mas nada corta a conexão dele.

**Sem autenticação também no vídeo.** `GET /stream` não pede nada. Quem alcança a
porta vê o voo.

**O detector nunca tenta de novo sozinho depois de uma falha de carga.** Enquanto
o mtime não mudar, o `error` permanece; a saída é `POST /api/model/reload` ou
tocar no arquivo. É intencional — repetir um import de torch que falha, a cada
segundo, custa caro e não muda de resultado.

**A coleta não sobrevive ao reinício do painel.** O estado é só memória. Uma
sessão interrompida deixa `raw/` íntegro e um `session.json` com
`status: "gravando"` — consistente e reprocessável —, mas o painel volta em
`ocioso` e não oferece nada para retomar ou finalizar aquela versão. O caminho
hoje é rodar `split.run()` à mão sobre a pasta; a tela de datasets da fatia 4 é
o lugar natural para isso virar um botão. O mesmo vale para uma queda **durante**
o split: `raw/` fica íntegro, mas `train|valid|test` podem ficar com uma cópia
parcial e sem manifesto — o `split.run()` seguinte apaga e refaz as três pastas,
então rodá-lo de novo é o conserto completo.

**Uma coleta interrompida ocupa a versão.** `v0.2` com `status: "gravando"`
continua em disco e nunca é reaproveitada: a próxima coleta cria `v0.3`. Não há
limpeza automática, e sem a tela de datasets também não há como apagar pela
interface.

**Sem `interval`, `limit` e `dedup` por sessão salva no servidor.** Os três vêm
do modal a cada início e são registrados no `session.json`, mas não há
preferência persistida: toda coleta recomeça em 2 s / 500 / dedup ligada.

**A dedup compara com o último quadro salvo, não com todos.** Um voo que passa
duas vezes pelo mesmo enquadramento salva as duas — a comparação é sequencial, de
propósito, porque um índice de todos os quadros vistos custaria memória e tempo
crescentes durante a gravação.

**O limiar de dedup é absoluto.** `DEDUP_MAD = 2.0` foi calibrado contra um
publicador sintético. Ruído de sensor, compressão agressiva ou cena noturna
mudam a escala, e não há calibração automática nem exibição do valor medido —
só o contador de descartados na tela é que denuncia um limiar mal escolhido.

**A margem de descarte distorce a proporção em datasets pequenos.** São sempre
~4·M quadros fora, um número fixo: em 50 quadros isso é 24% do dataset e o
`valid` fica com 5% em vez de 15%. Os avisos `proporcao_desviada_*` dizem isso na
tela, mas o sistema não corrige sozinho nem sugere um `M` melhor.

**O impacto sobre o vídeo só é medido se houver vídeo antes.** Iniciar a coleta
sem nenhum navegador aberto deixa `impact.available: false` para a sessão
inteira, porque a referência é lida uma única vez, no `start`. Não há
recalibração posterior.

**O split não valida o conteúdo das imagens.** Confia no nome do arquivo para
índice e tempo. Um `raw/` montado à mão com tempos fora de ordem produziria um
manifesto coerente com nomes incoerentes — os arquivos são ordenados por
`(índice, t)`, e é o índice que manda.

**`train/`, `valid/` e `test/` são apagados a cada split.** É o que torna o
resplit idempotente, mas significa que qualquer coisa colocada dentro dessas
pastas entre um split e outro se perde. Só `raw/` é preservado.

**Sem autenticação também na coleta.** Como no resto do painel: quem alcança a
porta pode iniciar, pausar e salvar uma coleta, e `GET /api/collect/status`
devolve o caminho absoluto do dataset em disco.

**A exclusão de imagens é irreversível e não tem desfazer.** É uma escolha, não
um esquecimento: manter a imagem em `raw/` faria o "refazer o split"
ressuscitá-la (§8). O que existe é o registro no `edits.json`, que diz o que foi
apagado e quando — não o arquivo de volta.

**Não há exclusão de quadros descartados na margem.** A galeria mostra só as três
partições. Um quadro que o split jogou na margem continua em `raw/` e não tem
como ser apagado pela interface; ele volta a ser candidato no próximo resplit.

**A divergência com o Roboflow é detectada pelo nome do arquivo.** Se o mesmo
nome for reenviado depois de uma exclusão — o que só acontece recoletando na
mesma versão, hoje impossível —, os dois lados voltariam a "bater" sem que a
imagem seja a mesma. Nada consulta a API do Roboflow para conferir: lá é a fonte
de verdade, e aqui só se registra o que este lado fez.

**O envio não verifica se o projeto do Roboflow já tem as imagens.** A retomada
confia no `roboflow.json` local. Apagar esse arquivo e reenviar duplica tudo no
Roboflow; enviar o mesmo dataset de duas máquinas diferentes também.

**Um envio por processo, e ele não sobrevive ao reinício.** O estado do
`Uploader` é memória. Reiniciar o painel no meio de um envio deixa o
`roboflow.json` com `state: "enviando"` para sempre — a tela mostra `enviando`
sem nada acontecendo, e o conserto é clicar em enviar de novo, que retoma pelo
que já está registrado como enviado.

**O `roboflow.json` guarda o nome de cada arquivo enviado.** Num dataset de 5000
imagens são 5000 chaves; o arquivo passa de 1 MB e é reescrito inteiro a cada 5
uploads. Funciona, mas é O(n²) em escrita ao longo de um envio grande.

**Miniaturas são geradas na primeira visita.** Abrir a galeria de um dataset novo
de 500 imagens dispara 500 decodificações; elas vão para o threadpool e não
travam o event loop, mas a grade preenche devagar da primeira vez. Não há
pré-geração ao salvar a coleta.

**O cache de miniaturas não tem teto.** Cresce até ~8 KB por imagem e só é
limpo por um resplit ou pela exclusão do dataset.

**A lista relê o disco inteiro a cada carga.** `dir_size()` percorre a árvore de
todas as versões e `live_counts()` faz um `scandir` por partição. Com dezenas de
datasets grandes a tela começa a demorar; não há cache nem índice.

**Não implementado nestas fatias:** `/api/model/samples`, a tela de modelo, a
pasta `train/`, o formulário de configurações do item 3 da especificação
original (path com gerador aleatório, transporte RTSP, HLS, resolução, FPS,
qualidade JPEG) e a geração dinâmica do `mediamtx.yml` — o arquivo
`config/mediamtx.yml` é usado como está. As proporções do split e a margem
continuam constantes em `app/split.py`: `POST /resplit` expõe `margin`, mas
`ratios` só existe na assinatura de `split.run()`.
