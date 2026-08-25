# API e armadilhas

Referência para quem for estender o painel, e os comportamentos que confundem na operação.

## Rotas

| Método | Caminho | Corpo | Resposta |
|---|---|---|---|
| GET | `/` | — | HTML do painel |
| GET | `/events` | — | `text/event-stream`, fluxo infinito |
| GET | `/api/pipeline/status` | — | `{pipeline, stream}` |
| POST | `/api/pipeline/start` | `{}` ou `{"stream_path": "..."}` | `{ok, pipeline, stream}` |
| POST | `/api/pipeline/stop` | `{}` | `{ok, pipeline, stream}` |

`GET /events` só aceita GET — outros métodos devolvem `405`.

O `stream_path` enviado passa por `.strip().lstrip("/")`, então `/live/x` vira `live/x`. Tipo errado devolve `422` do Pydantic.

!!! note "Falha não usa código HTTP de erro"
    Um start que falha responde **200 com `ok: false`**. Quem consumir a API precisa checar o campo, não o status.

Os dois POST rodam em threadpool, porque `pipeline.start` e `pipeline.stop` são bloqueantes.

## O payload

`GET /api/pipeline/status` e cada emissão do SSE devolvem **o mesmo objeto** — compartilham a função `_state()`. A única diferença é que os POST acrescentam a chave `ok`.

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

`rtsp_url` e `hls_url` são strings **construídas**, não verificações — continuam preenchidas com tudo parado.

### Formato do SSE

Cada emissão é `data: <json>` seguida de linha em branco. Sem `event:`, `id:` ou `retry:`.

```
cache-control: no-cache
x-accel-buffering: no
content-type: text/event-stream; charset=utf-8
```

O servidor checa `request.is_disconnected()` a cada volta e encerra o gerador quando o cliente some — detecção em até ~2 s.

## Reconciliação

O painel não persiste nada. Toda resposta é medida no sistema:

| O que | Como |
|---|---|
| Container | `docker inspect -f '{{.State.Running}}' mtx` |
| API | `GET /v3/paths/list`, timeout 1,5 s |
| Túnel | `pgrep -f "bore local"` |
| Endereço | última ocorrência de `listening at (\S+?):(\d+)` em `/tmp/bore.log` |

Usar a **última** ocorrência é o que permite o log acumular entre reinícios. O passo 3 do start zera o arquivo antes de subir o bore novo, para que uma falha no passo 4 não deixe o painel exibindo endereço antigo como atual.

O log só é lido quando o `pgrep` confirma o processo vivo — túnel morto resulta em `rtmp_url: null` mesmo com o log cheio.

---

## Armadilhas

### O endereço RTMP fica verde com o MediaMTX morto

`rtmp_url` depende **apenas do túnel**. Com bore vivo e container morto, o campo continua verde e o botão de copiar habilitado.

Não é imprecisão — o túnel de fato escuta naquele endereço. O que falta é quem consuma do outro lado. O operador percebe pelo cartão MediaMTX vermelho e pelo semáforo, mas nada no próprio campo indica o problema.

### O path pode estar errado após reconciliação

Se o pipeline foi iniciado pelo `start.sh` com `STREAM_PATH` diferente do padrão, o painel reconstrói o `rtmp_url` usando **o padrão dele**, não o que está realmente publicando.

O endereço do túnel estará certo; o sufixo, não. Como o sufixo é a credencial do endpoint, isso significa colar no FlightHub um endereço que não bate com o que o script configurou.

Para evitar: use sempre o painel **ou** sempre o script, ou exporte o mesmo `STREAM_PATH` nos dois.

### A mensagem de colisão se perde

Numa chamada concorrente, o painel monta `{"ok": False, "error": "pipeline já está em operação", **snapshot()}` — e como `snapshot()` também traz uma chave `error`, ela sobrescreve a mensagem.

Resultado: `ok: false` com `error: null`. O cliente sabe que falhou, mas não por quê.

**Correção:** inverter a ordem das chaves, colocando o `error` depois do spread.

### `busy: true` quase nunca chega à tela

Um start leva ~1,6 s, menos que o intervalo de 2 s do SSE — a maioria dos frames não captura a janela ocupada. Por isso o JS mantém uma flag local para desabilitar os botões durante o POST.

Se você for consumir a API de fora, **não confie em `busy` para detectar operação em andamento**.

### `pkill` e `docker rm` não distinguem dono

O start e o stop matam qualquer processo com `bore local` na linha de comando e removem qualquer container chamado `mtx` — tenham sido criados pelo painel ou não.

É intencional, é o mesmo comportamento do `start.sh`. Mas significa que dois painéis na mesma máquina brigam entre si, e que um bore de outro projeto seria derrubado junto.

### Sem autenticação

O `run.sh` publica em `0.0.0.0`. Qualquer um que alcance a porta pode iniciar ou parar o pipeline.

Mais relevante: `GET /api/pipeline/status` devolve o endereço RTMP completo — e o path do stream é a **única credencial** do endpoint de publicação. Quem lê essa rota consegue publicar no seu servidor.

!!! danger "Não exponha a porta do painel publicamente"
    No Codespaces, mantenha a porta do painel como **Private**. A porta 8888 (HLS) pode ser pública para compartilhar visualização; a do painel, não.

    Antes de qualquer uso além de desenvolvimento, isso precisa de autenticação.

### A resolução exige `tracks2[]`

Em versões do MediaMTX que só expõem `tracks[]` (lista de nomes de codec), a resolução sai nula e o rótulo vira `Recebendo — resolução desconhecida · X Mbps`. A imagem `bluenviron/mediamtx:latest` expõe `tracks2` com dimensões.

### Sem persistência

Reiniciar o painel zera `steps`, `error` e `stream_path`. Não há banco — isso chega na fatia 4.
