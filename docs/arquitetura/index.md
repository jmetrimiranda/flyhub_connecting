# Arquitetura

Tudo roda numa máquina só, com IP público direto. Não há túnel, relay, nuvem nem VM.

```
┌─────────────┐
│ Matrice 4TD │  câmera, H.264
└──────┬──────┘
       │ rádio / 4G
┌──────▼──────────┐
│  FlightHub 2    │  nuvem DJI
└──────┬──────────┘
       │ RTMP push ── a DJI inicia esta conexão
       │
   ════╪════ internet
       │
┌──────▼──────────────────────────────────────────┐
│  ROTEADOR    port forward 1935 → máquina local  │
└──────┬──────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────┐
│  MÁQUINA LOCAL                                  │
│                                                 │
│   ┌──────────┐   RTSP    ┌──────────────────┐  │
│   │ MediaMTX ├──────────►│   Aplicação      │  │
│   │ :1935    │           │   FastAPI :8080  │  │
│   │ :8554    │           │                  │  │
│   │ :8888    │           │  ┌────────────┐  │  │
│   │ :9997    │           │  │  video.py  │  │  │
│   └──────────┘           │  │  leitor    │  │  │
│                          │  └─────┬──────┘  │  │
│                          │        │         │  │
│                    ┌─────┴────────┴──────┐  │  │
│                    │                     │  │  │
│              ┌─────▼──────┐    ┌─────────▼─┐│  │
│              │inference.py│    │collect.py ││  │
│              │  YOLO/GPU  │    │  dataset  ││  │
│              └─────┬──────┘    └─────┬─────┘│  │
│                    │                 │      │  │
│               MJPEG /stream     data/datasets│  │
│                    │                 │      │  │
│                    ▼                 ▼      │  │
│              navegador          Roboflow    │  │
└─────────────────────────────────────────────┘  │
```

## As três camadas

### Ingestão

**MediaMTX** em container Docker. Recebe a publicação RTMP da nuvem da DJI e republica em RTSP, HLS e WebRTC ao mesmo tempo. Um publisher, vários consumidores, sem multiplicar carga na origem.

Portas: `1935` (RTMP, exposta à internet), `8554` (RTSP), `8888` (HLS), `9997` (API de status).

### Processamento

**FastAPI** servindo três telas e as rotas de controle. Dentro dele, quatro módulos com responsabilidades separadas:

| Módulo | Papel |
|---|---|
| `video.py` | Lê RTSP em thread, mantém sempre o quadro mais recente |
| `inference.py` | Carrega YOLO se houver pesos; passthrough se não houver |
| `collect.py` | Máquina de estados da coleta, amostragem, escrita |
| `split.py` | Particionamento temporal em train/valid/test |
| `datasets.py` | Versionamento, varredura de disco |
| `roboflow_upload.py` | Envio preservando a partição |
| `monitor.py` | Polling da API do MediaMTX, semáforo |
| `pipeline.py` | Sobe e derruba container e túnel |

### Saída

**MJPEG** para o navegador, com as detecções desenhadas. **Arquivos** em `data/datasets/vX.Y/` para o dataset. **Roboflow** para anotação.

## A decisão que define tudo: sem fila

Entre cada estágio há um **slot de um quadro**, não uma fila.

```
RTSP ──► [1 quadro] ──► inferência ──► [1 JPEG] ──► N clientes
```

Quando o produtor é mais rápido que o consumidor, o quadro antigo é **sobrescrito e contabilizado como perdido**. Nunca acumula.

Sem isso, com a inferência a 3 fps e o stream a 30, a latência cresceria indefinidamente — depois de um minuto você estaria vendo imagem de 30 segundos atrás, com o vídeo aparentando fluidez normal.

Medições com o padrão de teste: captura 30 fps, latência 2 ms, ~12 quadros descartados por minuto.

## O modelo é opcional

A aplicação sobe sem torch, sem pesos e sem dataset. O `Detector` entra em **passthrough**: devolve o quadro intacto e uma lista vazia de detecções.

Isso não é tolerância a falha — é o estado inicial do projeto. Você precisa coletar imagens antes de existir um modelo, e a plataforma existe justamente para coletar.

A interface indica sempre qual modo está ativo, com cor e texto.

## Rede

Com IP público, o FlightHub aponta direto para a máquina. O endereço é fixo e não muda entre reinícios.

```bash
PUBLIC_HOST=177.184.48.79 ./start.sh
```

A variável faz o painel montar o `rtmp_url` com ela e pular a etapa do túnel.

!!! note "O túnel ainda existe, mas é opcional"
    Quando não há IP público — rede corporativa atrás de NAT — a aplicação pode subir um túnel reverso (`bore`). O cartão do túnel fica verde nesse caso.

    Com `PUBLIC_HOST` definida, o cartão fica cinza com "não usado (IP direto)" e a coleta continua liberada. O túnel nunca foi pré-condição para gravar imagens.

→ [Fluxo de informação](fluxo.md) · [Tecnologias](tecnologias.md)
