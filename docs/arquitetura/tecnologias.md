# Tecnologias

O que cada peça faz e por que foi escolhida.

## Ingestão de vídeo

| Tecnologia | Papel |
|---|---|
| **MediaMTX** | Servidor de mídia. Recebe RTMP, republica em RTSP/HLS/WebRTC |
| **Docker** | Isola o MediaMTX; um comando sobe, um comando derruba |
| **RTMP** | Protocolo que o FlightHub 2 publica |
| **RTSP** | Protocolo que o OpenCV consome bem |
| **FFmpeg** | Gerador de stream de teste; gravação de trechos |

O MediaMTX resolve a incompatibilidade de protocolo: a DJI só publica RTMP ou RTSP, e o OpenCV lê RTSP com muito menos atrito. Ele também permite vários consumidores simultâneos sem multiplicar carga na origem.

## Aplicação

| Tecnologia | Papel |
|---|---|
| **FastAPI** | Rotas HTTP, SSE, threadpool para operações bloqueantes |
| **Uvicorn** | Servidor ASGI |
| **Jinja2** | Templates das três telas |
| **JS puro** | Frontend sem build step, sem npm |
| **SSE** | Estado empurrado para o navegador a cada 2 s |
| **MJPEG** | Vídeo processado no navegador, latência ~0,1 s |

A escolha de JS puro em vez de React é deliberada: o painel tem três telas e roda numa máquina só. Um build step adicionaria dependências e uma etapa de deploy sem ganho proporcional.

## Visão computacional

| Tecnologia | Papel |
|---|---|
| **OpenCV** (headless) | Decode RTSP, encode JPEG, desenho |
| **NumPy** | Arrays de imagem |
| **Ultralytics YOLO** | Detecção e segmentação |
| **PyTorch + CUDA** | Backend de GPU |

!!! warning "Apenas a variante headless do OpenCV"
    `opencv-python` e `opencv-python-headless` fornecem o mesmo módulo `cv2`. Com as duas instaladas, uma sobrescreve a outra e o import quebra com `ImportError: libGL.so.1`.

    O `ultralytics` declara dependência de `opencv-python`, mas funciona normalmente com o headless. Ignore o aviso do pip.

O `ultralytics` e o `torch` **não estão no `requirements.txt` principal**. Arrastam ~2,5 GB e a aplicação roda sem eles, em passthrough. Ficam em `train/requirements.txt`.

A importação de `ultralytics` é preguiçosa — acontece dentro da função de carga, não no topo do módulo. Assim a aplicação sobe em máquina sem torch.

## Dataset e treino

| Tecnologia | Papel |
|---|---|
| **Roboflow** | Anotação manual e assistida, versionamento |
| **Roboflow SDK** | Upload preservando partição, download do dataset |
| **Ultralytics** | Treino, validação, export |

## Versões travadas

```
opencv-python-headless==5.0.0.93
numpy<2.4
```

O OpenCV está travado porque instalações posteriores do `ultralytics` tendem a puxar a variante com GUI. O NumPy está abaixo de 2.4 porque o `roboflow` não aceita versões mais novas.

## Versões da máquina de referência

| Componente | Versão |
|---|---|
| Python | 3.14.4 |
| PyTorch | 2.11.0+cu128 |
| Ultralytics | 8.4.130 |
| OpenCV | 5.0.0 |
| MediaMTX | latest |
| Docker | 29.1.3 |
| Node (Claude Code) | 22.23.2 |
| Driver NVIDIA | 595.84 |

## O que não é usado

**Nuvem.** Nem Databricks, nem VM, nem serviço gerenciado. Vídeo ao vivo não se encaixa bem em Spark, que é orientado a batch e não mantém conexão RTSP contínua.

**Túnel reverso.** Existe como opção para redes sem IP público, mas com port forward não é usado.

**Banco de dados.** O estado vive em arquivos JSON ao lado dos datasets. Menos peça para manter, e o dataset fica autocontido — dá para copiar a pasta e ter tudo.
