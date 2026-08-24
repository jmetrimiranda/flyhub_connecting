# SPEC_ATUAL — o que existe hoje (fatias 1 e 2)

Estado do código em `app/` na branch `interface`. Todos os JSON deste documento
foram capturados em execução real, não escritos à mão.

Escopo entregue: **fatia 1** (FastAPI + status via SSE) e **fatia 2** (start/stop
do pipeline com exibição do endereço RTMP e botão de copiar).
Fora de escopo, ainda não implementado: MJPEG (`/stream`), coleta de frames,
split temporal, export e Roboflow — nenhuma dessas rotas existe.

Arquivos:

| Arquivo | Papel |
|---|---|
| `app/main.py` | rotas HTTP e SSE |
| `app/pipeline.py` | controle do container MediaMTX e do túnel bore |
| `app/monitor.py` | thread de polling da API do MediaMTX e semáforo |
| `app/templates/index.html` | painel |
| `app/static/app.js`, `app/static/app.css` | comportamento e tema |
| `run.sh` | sobe o uvicorn |

---

## 1. Rotas

Cinco rotas de aplicação, mais os estáticos em `/static/*` (`StaticFiles`).

| Método | Caminho | Corpo da requisição | Resposta |
|---|---|---|---|
| GET | `/` | — | HTML do painel (`200 text/html; charset=utf-8`) |
| GET | `/events` | — | `200 text/event-stream; charset=utf-8`, fluxo infinito (ver §2) |
| GET | `/api/pipeline/status` | — | `200 application/json` — `{pipeline, stream}` |
| POST | `/api/pipeline/start` | `{}`, `{"stream_path": "..."}` ou sem corpo | `200 application/json` — `{ok, pipeline, stream}` |
| POST | `/api/pipeline/stop` | `{}` ou sem corpo | `200 application/json` — `{ok, pipeline, stream}` |

`GET /events` responde apenas a GET — qualquer outro método devolve `405` com
header `allow: GET`.

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
  }
}
```

Campos de `pipeline` (montados por `pipeline.snapshot()`):

| Campo | Tipo | Significado |
|---|---|---|
| `busy` | bool | há um start/stop em execução neste instante |
| `error` | string \| null | mensagem do último start/stop que falhou; zerada no início de cada start/stop |
| `steps` | lista | relatório do último start/stop (ver §5). `[]` antes do primeiro |
| `stream_path` | string | path em uso, já sem `/` inicial |
| `mediamtx.running` | bool | `docker inspect` do container |
| `mediamtx.container` | string | sempre `"mtx"` (constante `CONTAINER`) |
| `tunnel.running` | bool | há processo `bore local` vivo |
| `tunnel.address` | string \| null | `host:porta` do túnel; `null` se o túnel não estiver vivo |
| `rtmp_url` | string \| null | `rtmp://{address}/{stream_path}`; `null` sem endereço |
| `rtsp_url` | string | sempre montado, mesmo com pipeline parado |
| `hls_url` | string | idem |

`rtsp_url` e `hls_url` são strings construídas a partir de `stream_path`, não
verificações — continuam preenchidas com tudo parado.

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
`GET /api/pipeline/status`.

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

**Duas cadências independentes.** O `stream` vem de uma thread que faz polling da
API do MediaMTX a cada `POLL_INTERVAL_S = 2.0` s e guarda o último resultado em
memória; o SSE apenas lê esse cache. Já o bloco `pipeline` é medido na hora, a
cada emissão. Consequência: um dado de `stream` pode ter até ~2 s de idade além
do intervalo do SSE.

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
| `resolution` | primeiro `tracks2[]` que tenha `codecProps.width` e `.height`, formatado `W×H` (separador é `×`, U+00D7); `null` se nenhum tiver |
| `codecs` | `tracks2[].codec`; se `tracks2` estiver vazio, cai para `tracks[]` (MediaMTX antigo, sem dimensões) |
| `bytes_received` | `bytesReceived` |
| `mbps` | derivada calculada localmente (ver §4) |
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
preenchido — ver §8.

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

### Barra de estado (topo, `position: sticky`)

Quatro cartões, cada um com uma bolinha colorida e dois textos. **Nenhum é
clicável.** A cor nunca aparece sozinha — sempre acompanhada de texto.

| Cartão | Rótulo fixo | Valor exibido | Cor da bolinha |
|---|---|---|---|
| Disponibilidade | `Disponibilidade` | `stream.label` (ver §4). Antes do primeiro frame: `conectando…` | `stream.level` |
| MediaMTX | `MediaMTX` | `Parado` / `No ar` / `Container no ar, API muda` | vermelho se container parado; verde se container no ar **e** `api_ok`; amarelo se container no ar e API não responde |
| Túnel | `Túnel` | `Parado` / o endereço (`bore.pub:49934`) / `Subindo…` | vermelho se sem processo; verde se processo e endereço; amarelo se processo sem endereço ainda |
| Stream | `Stream` | nomes dos paths separados por `, ` — ou `Nenhum path ativo` | igual a `stream.level` |

No canto direito, fora dos cartões: `SSE: conectando` (estado inicial no HTML),
`SSE: conectado`, `SSE: reconectando…`.

Antes do primeiro frame do SSE, as bolinhas ficam cinza (sem classe de cor) e os
valores em `—`.

### Elementos clicáveis

Existem quatro. Não há nenhum campo de formulário — a escolha de path,
transporte, resolução e FPS é do item 3 da especificação original, fatia ainda
não implementada.

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

**4. `Abrir FlightHub 2`** (link, no painel "Ainda no portal da DJI")

- Abre `https://www.dji.com/flighthub-2` em nova aba (`target="_blank"`,
  `rel="noopener"`). Está ali junto do texto que explica que resolução e bitrate
  saem do encoder da aeronave e não têm controle no painel.

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

Placeholder com o título `Visualização ao vivo` e a nota de que chega na fatia 3
(MJPEG em `/stream`), mostrando enquanto isso os URLs de HLS e RTSP para conferir
o vídeo por fora.

Abaixo, uma tabela de paths que fica **oculta quando não há path ativo** e
aparece assim que houver, com as colunas: `Path`, `Pronto` (`sim`/`não`),
`Resolução`, `Taxa` (`0.34 Mbps`), `Codecs`, `Parado há` (`—` quando zero).

### Tema

Escuro fixo (`#0d1117` de fundo), sem alternador. Layout em duas colunas
(`1fr 380px`) que colapsa para uma coluna abaixo de 900 px de largura.

---

## 4. Semáforo

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

## 5. Passos do start

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
executar nada (mas veja a limitação em §8 sobre a mensagem perdida).

---

## 6. Variáveis de ambiente

Nenhuma é obrigatória. Todas são lidas **na importação do módulo** — mudar depois
exige reiniciar o painel. O `.env` do repositório **não** é carregado pelo painel
(não há chamada a `load_dotenv` em `app/`).

| Variável | Padrão | Lida em | Efeito |
|---|---|---|---|
| `STREAM_PATH` | `live/m4td` | `app/pipeline.py` | Path usado no `rtmp_url`, `rtsp_url` e `hls_url` enquanto nenhum start passar `stream_path` explícito. É o mesmo nome de variável que o `start.sh` já usava. |
| `MEDIAMTX_API` | `http://localhost:9997` | `app/pipeline.py` | Base da API do MediaMTX. `PATHS_LIST_URL` é essa base + `/v3/paths/list`, e vale tanto para o passo `API` do start quanto para o polling do monitor. Não muda a porta publicada pelo `docker run`, que é fixa. |
| `BORE_TO` | `bore.pub` | `app/pipeline.py` | Destino do `bore local 1935 --to <BORE_TO>`. Permite apontar para um servidor bore próprio. |
| `PANEL_PORT` | `8080` | `run.sh` | Porta do uvicorn. O padrão é 8080 e não 8000 porque a 8000 costuma estar ocupada pelo `mkdocs serve` deste repositório. |

Valores fixos no código, sem variável de ambiente: nome do container (`mtx`),
imagem (`bluenviron/mediamtx:latest`), portas publicadas
(1935, 8554, 8888, 9997), caminho do config (`config/mediamtx.yml` relativo à
raiz do repositório), log do túnel (`/tmp/bore.log`), porta local do túnel
(1935), intervalos de 2 s e limiar de 10 s.

---

## 7. Reconciliação

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

**O que a reconciliação não recupera:** a lista `steps` começa vazia (`[]`) até o
primeiro start/stop feito pelo painel, e `stream_path` volta ao valor de
`STREAM_PATH` a cada reinício do painel. Se o pipeline em execução tiver sido
iniciado com outro path, o `rtmp_url` exibido apontará para o path errado — o
endereço do túnel estará certo, o sufixo não.

---

## 8. Limitações conhecidas

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

**Mensagem de colisão de start/stop se perde.** Numa chamada concorrente,
`start`/`stop` montam `{"ok": False, "error": "pipeline já está em operação",
**snapshot()}` — e como `snapshot()` também traz uma chave `error`, ela sobrescreve
a mensagem. Verificado: a resposta sai com `ok: false` e `error: null`. O cliente
sabe que falhou, mas não por quê. Correção é trocar a ordem das chaves.

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

**Sem persistência.** Reiniciar o painel zera `steps`, `error` e `stream_path`.
Não há banco — `sessions.db` é da fatia 4.

**O semáforo ignora paths não prontos.** Um path existente com `ready: false`
conta como "Sem stream" (vermelho), embora apareça na tabela de paths da esquerda
com `Pronto: não`.

**A resolução exige `tracks2[].codecProps`.** Em versões do MediaMTX que só
expõem `tracks[]` (lista de nomes de codec), `resolution` sai `null` e o rótulo
verde vira `Recebendo — resolução desconhecida · X Mbps`. A instalação atual
(`bluenviron/mediamtx:latest`) expõe `tracks2` com `width`/`height`.

**Não implementado nesta fatia:** `/stream` (MJPEG), `/api/collect/*`,
`/api/sessions*`, `/api/export`, `/api/exports`, `/api/roboflow/*`, o formulário
de configurações do item 3 da especificação (path com gerador aleatório,
transporte RTSP, HLS, resolução, FPS, qualidade JPEG) e a geração dinâmica do
`mediamtx.yml` — o arquivo `config/mediamtx.yml` é usado como está.
