# Fluxo de informação

Como um quadro viaja do sensor da câmera até virar linha num dataset.

## O caminho de um quadro

```
 1. Câmera captura                     Matrice 4TD
 2. Encode H.264                       encoder da aeronave
 3. Enlace de rádio                    aeronave → dock
 4. Upload                             dock → nuvem DJI
 5. Encaminhamento RTMP                FlightHub → seu IP:1935
 6. Ingestão                           MediaMTX
 7. Republicação RTSP                  MediaMTX :8554
 8. Decode                             video.py, thread do leitor
 9. Slot de 1 quadro                   sobrescreve o anterior
10. Inferência                         inference.py (se houver pesos)
11. Overlay + encode JPEG              video.py, thread do worker
12. Slot de 1 JPEG                     sobrescreve o anterior
13. Entrega                            /stream → navegador
```

Em paralelo, quando a coleta está ativa, uma thread separada espia o slot do passo 9 — **sem consumir** — e grava em disco.

## Latência por etapa

| Etapa | Típico | Você controla? |
|---|---|---|
| 1–3 Captura e rádio | 300–1100 ms | Não |
| 4 Nuvem DJI | 500–1500 ms | Não |
| 5 Rede até sua casa | 20–80 ms | Parcialmente |
| 6–7 MediaMTX | 10–50 ms | Sim |
| 8–13 Aplicação | 2–400 ms | **Sim** |

As quatro primeiras somam 1 a 2,5 segundos e são intocáveis. O trabalho útil está nas últimas.

Com IP direto você já economiza o salto do relay, que num túnel público custava 100–600 ms.

## As duas correntes do painel

O estado que aparece na tela vem de duas fontes com cadências diferentes:

```
┌─────────────────────────────────────┐
│           NAVEGADOR                 │
│   EventSource ◄─── data: {...}      │
└─────────▲───────────────────────────┘
          │ a cada 2 s
┌─────────┴───────────────────────────┐
│         FastAPI  _state()           │
└────┬───────────────────────┬────────┘
     │                       │
┌────▼──────────┐   ┌────────▼────────┐
│  monitor.py   │   │  pipeline.py    │
│ thread, 2 s   │   │ medido na hora  │
│ cache         │   │ docker + pgrep  │
└────┬──────────┘   └────────┬────────┘
     │                       │
GET /v3/paths/list      docker inspect
```

O bloco `stream` vem de cache e pode ter até 2 s de idade além do intervalo do SSE. O bloco `pipeline` é medido a cada emissão.

Na prática: um dado de `stream` pode estar 4 s atrasado no pior caso. Irrelevante para operação, mas explica por que o semáforo às vezes demora um piscar a mudar.

## Da coleta ao dataset

```
Coleta ativa
     │
     │ a cada N segundos
     ▼
 espia o slot ──► dedup? ──► fila de escrita (máx 20)
                              │
                              │ 2 workers, nice 10
                              ▼
                    data/datasets/v0.3/raw/
                        000001_t0.00.jpg
                        000002_t2.00.jpg
                        ...
     │
     │ botão Salvar
     ▼
 1. para a amostragem
 2. espera a fila esvaziar        ← barreira
 3. conta os arquivos
 4. calcula os cortes
 5. copia para train/valid/test
 6. grava o manifesto
```

A **barreira do passo 2** não é zelo: sem ela, um arquivo ainda na fila sairia calado do manifesto.

O **timestamp no nome** vem do instante de captura que acompanha o quadro no slot, não de um relógio consultado na hora de gravar. Isso sobrevive a reconexões do RTSP, que rezeram contadores relativos.

## Proteções de performance

Exibir o vídeo é a função principal. A coleta é secundária e nunca pode degradá-la.

| Mecanismo | O que evita |
|---|---|
| Espiar sem consumir | Roubar quadro dos clientes MJPEG |
| Fila limitada a 20 | Crescimento sem limite quando o disco atrasa |
| Descarte contabilizado | Perda silenciosa de quadros |
| `nice 10` nos workers | Disputa de CPU com o encode do MJPEG |
| Inferência 1× por quadro | Custo dobrar com dois navegadores abertos |
| Split em thread única | Congelar o vídeo durante o particionamento |

Medido em coleta de 2 minutos a 0,5 s de intervalo: **0,0% de variação** no FPS de captura e de inferência.
