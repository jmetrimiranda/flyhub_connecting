# Especificação: painel de controle do pipeline de drone

> Arquivo de briefing para o Claude Code. Abra o projeto e passe este arquivo como contexto.

## Contexto

Existe um pipeline funcionando que traz vídeo ao vivo de drones DJI (via FlightHub 2) para o OpenCV:

```
Matrice 4TD → FlightHub 2 → túnel (bore) → MediaMTX → RTSP → OpenCV
```

Hoje tudo é operado por linha de comando, em três terminais separados. O objetivo é um painel web que controle o que **não** exige entrar no portal da DJI, e que permita coletar dataset rotulado a partir dos voos.

O que continua manual no portal da DJI (fora de escopo): criar/editar o canal de encaminhamento, ligar o dispositivo, escolher a câmera.

## Stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn
- **Frontend:** HTML + JS puro em template Jinja2 — sem build step, sem npm
- **Estado:** SQLite (`sessions.db`) via `sqlite3` da stdlib
- **Processos externos:** `docker` e `bore` controlados por `subprocess`
- **Visão:** OpenCV headless, Ultralytics opcional

Prefira dependências mínimas. O painel roda em Codespace ou VM, não precisa escalar.

## Estrutura alvo

```
app/
├── main.py              FastAPI: rotas HTTP e SSE
├── pipeline.py          controle de MediaMTX e túnel
├── monitor.py           polling da API do MediaMTX
├── capture.py           leitor RTSP em thread + gravação de frames
├── dataset.py           split temporal e export
├── roboflow_sync.py     upload
├── db.py                schema e queries
├── templates/index.html
└── static/app.js, app.css
data/
└── sessions/<id>/frames/
```

---

## Funcionalidades

### 1. Estado do pipeline

Card no topo com três indicadores, atualizados a cada 2 s via **Server-Sent Events** (não polling do browser):

| Componente | Como verificar |
|---|---|
| MediaMTX | `docker inspect -f '{{.State.Running}}' mtx` |
| Túnel | processo `bore` vivo + endereço extraído do stdout |
| Stream | `GET http://localhost:9997/v3/paths/list` |

Do JSON do MediaMTX extraia e exiba: `name`, `ready`, resolução de `tracks2[].codecProps`, e **taxa de `bytesReceived`** — a derivada é o que distingue "conectado mas parado" de "recebendo vídeo".

**Semáforo de disponibilidade** — o operador precisa saber, antes de iniciar qualquer coisa, se há voo para ver:

- 🔴 Sem stream — nenhum path ativo
- 🟡 Path existe, `bytesReceived` estagnado há mais de 10 s
- 🟢 Recebendo — mostre resolução e taxa em Mbps

### 2. Controle do pipeline

**Botão "Iniciar pipeline"** executa em sequência, reportando cada passo:

1. Sobe o container do MediaMTX com o `mediamtx.yml` gerado (ver item 3)
2. Aguarda a API responder em `localhost:9997` (timeout 15 s)
3. Inicia `bore local 1935 --to bore.pub`
4. Captura o endereço do stdout com a regex `listening at (\S+):(\d+)`
5. Exibe o endereço RTMP completo em campo com **botão de copiar**

O passo 5 é a razão de existir do painel: o endereço muda a cada reinício e precisa ser colado no FlightHub. Mostre-o grande, junto com o lembrete de que o canal precisa ser reeditado e o toggle religado.

**Botão "Parar pipeline"** encerra bore e container, sem apagar dados.

### 3. Configurações antes de subir

Formulário que gera o `mediamtx.yml` e os parâmetros de captura:

| Campo | Opções | Padrão |
|---|---|---|
| Path do stream | texto, com botão "gerar aleatório" | `live/m4td-<hex6>` |
| Transporte RTSP | TCP / UDP | TCP |
| HLS | ligado / desligado | ligado |
| Resolução de captura | original / 1280×720 / 960×720 / 640×640 | original |
| FPS de processamento | 1 / 5 / 10 / 15 / 30 | 10 |
| Qualidade JPEG | 60–95 | 80 |

O botão "gerar aleatório" importa: o path é a única credencial do endpoint RTMP exposto.

Sobre a qualidade do vídeo em si — resolução e bitrate saem do encoder da DJI e **só podem ser mudados no portal**. Deixe isso explícito na interface com um link para o FlightHub, para o operador não procurar o controle no lugar errado.

### 4. Visualização ao vivo

MJPEG em `/stream`, `multipart/x-mixed-replace`, servindo o quadro **após** a inferência quando ela estiver ativa.

Sobreposição: FPS, resolução, contador de quadros, e — quando a coleta estiver ligada — quantos frames já foram salvos.

### 5. Coleta para rotulagem

**Toggle "Ativar coleta"**, o núcleo do sistema.

Ao ligar, cria uma sessão:

```
data/sessions/2026-08-24_143052_m4td/
├── frames/
│   ├── 000001_t0.00.jpg
│   ├── 000002_t2.00.jpg
│   └── ...
└── session.json
```

O timestamp relativo no nome do arquivo não é decorativo — é o que permite o split temporal do item 6 sem reabrir o banco.

`session.json`:

```json
{
  "id": "2026-08-24_143052_m4td",
  "started_at": "2026-08-24T14:30:52Z",
  "ended_at": null,
  "source_path": "live/m4td-a1b2c3",
  "resolution": [960, 720],
  "sample_interval_s": 2.0,
  "frame_count": 0,
  "notes": ""
}
```

**Parâmetros de amostragem:**

| Campo | Opções | Padrão |
|---|---|---|
| Intervalo | 0.5 / 1 / 2 / 5 s | 2 s |
| Limite de frames | número ou ilimitado | 500 |
| Pular quadros quase idênticos | on/off | on |

A deduplicação usa diferença média absoluta entre quadros consecutivos, com limiar configurável. Quando o drone paira, salvar 30 quadros por segundo do mesmo enquadramento infla o dataset sem adicionar informação — e pior, distorce a distribuição de treino.

Ao desligar o toggle, preencha `ended_at` e `frame_count`.

### 6. Split train/valid/test

**Aqui está a decisão técnica mais importante de todo o sistema. Não implemente split aleatório.**

Quadros consecutivos de vídeo são quase idênticos. Um split aleatório coloca o quadro *N* em treino e o *N+1* em validação — o modelo memoriza em vez de generalizar, e a métrica de validação sobe para valores que não se sustentam em voo novo. É vazamento de dados, e é silencioso: nada no treino indica que aconteceu.

Ofereça dois modos, ambos temporais:

**Modo A — por blocos contíguos (uma sessão)**

```
[──────── treino 70% ────────][─ val 15% ─][─ test 15% ─]
t=0                                                  t=fim
```

Cada partição é um intervalo contínuo de tempo. Aplique uma **margem de descarte** de N quadros nas fronteiras (padrão 5) para evitar que o último frame de treino e o primeiro de validação sejam vizinhos temporais.

**Modo B — por sessão (múltiplos voos) — preferível**

Sessões inteiras vão para uma partição. Voos diferentes têm iluminação, ângulo e condição atmosférica distintos, e é exatamente essa variação que a validação precisa medir.

```
voos 1,2,3,4,5 → treino
voo  6         → validação
voo  7         → teste
```

Com 3 ou mais sessões disponíveis, o modo B deve ser o padrão sugerido na interface.

Estrutura gerada:

```
data/exports/<nome>/
├── train/images/
├── valid/images/
├── test/images/
└── split_manifest.json
```

O manifesto registra qual estratégia foi usada, quais sessões entraram em cada partição e a margem aplicada — sem isso não há como reproduzir nem auditar o experimento depois.

### 7. Integração com Roboflow

Configuração: API key (via `.env`, nunca no código), workspace, projeto.

Ao enviar, **preserve a partição**. O Roboflow aceita o parâmetro `split` no upload — se você enviar tudo como `train` e deixar o Roboflow dividir, ele usa split aleatório e todo o cuidado do item 6 é desfeito.

```python
from roboflow import Roboflow

rf = Roboflow(api_key=os.environ["ROBOFLOW_API_KEY"])
project = rf.workspace(WORKSPACE).project(PROJECT)

for split in ("train", "valid", "test"):
    for img in sorted((export_dir / split / "images").glob("*.jpg")):
        project.upload(
            str(img),
            split=split,
            batch_name=session_id,        # rastreabilidade
            tag_names=[session_id, "drone", "m4td"],
        )
```

Use `batch_name` e `tag_names` com o id da sessão. Meses depois, quando alguém perguntar de qual voo veio determinada imagem, essa é a única resposta possível.

Exiba progresso de upload e permita cancelar. Envie em thread separada; nunca bloqueie o event loop do FastAPI.

---

## Rotas

```
GET  /                          painel
GET  /events                    SSE com estado
GET  /stream                    MJPEG

POST /api/pipeline/start        {config} → {rtmp_url, tunnel}
POST /api/pipeline/stop
GET  /api/pipeline/status

POST /api/collect/start         {interval, limit, dedup}
POST /api/collect/stop
GET  /api/sessions
GET  /api/sessions/{id}
DELETE /api/sessions/{id}

POST /api/export                {mode, ratios, margin, sessions[]}
GET  /api/exports

POST /api/roboflow/upload       {export_name}
GET  /api/roboflow/status
```

## Design da interface

Densa e operacional, não landing page. Escuro por padrão — vai ficar aberta ao lado de imagem aérea o dia inteiro.

Layout em duas colunas: vídeo à esquerda ocupando o máximo possível, controles à direita em coluna estreita. Estado do pipeline fixo no topo.

Estados precisam ser legíveis à distância — o operador vai olhar de relance enquanto acompanha o voo. Use cor **e** texto, nunca só cor.

Escreva os rótulos pelo que o operador controla, não pela implementação: "Coletar imagens do voo", não "Ativar frame dumper".

## Requisitos não funcionais

- Reconexão automática do RTSP com backoff exponencial (limite 10 s)
- Coleta nunca bloqueia a exibição — threads separadas
- Escrita de arquivos em thread pool, fora do loop de captura
- Se o disco passar de 90%, pare a coleta e avise na interface
- `.env` no `.gitignore`; nenhuma chave em código
- Sessão interrompida por queda deve ficar consistente: grave `session.json` incrementalmente

## Ordem de implementação

Entregue em fatias funcionais, validando cada uma antes de seguir:

1. FastAPI + status via SSE (ler a API do MediaMTX, sem controlar nada)
2. Start/stop do pipeline com exibição do endereço RTMP
3. MJPEG
4. Coleta de frames com sessões
5. Split temporal e export
6. Roboflow

As fatias 1 e 2 já justificam o painel sozinhas — copiar o endereço do túnel a cada reinício é a fricção diária atual.

## Testes

- Simule o stream com `ffmpeg -re -stream_loop -1 -i video.mp4 -c copy -f flv rtmp://localhost:1935/live/test`
- Verifique que o split temporal não coloca quadros adjacentes em partições diferentes
- Confirme que a interface se recupera de queda do MediaMTX no meio de uma coleta
