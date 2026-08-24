# Vídeo ao vivo do drone dentro do OpenCV

Este guia documenta como capturar o vídeo de uma aeronave ou dock DJI gerenciado pelo **FlightHub 2** e entregá-lo a um script Python, quadro a quadro, para processamento por rede neural.

O resultado final é uma linha de código:

```python
cap = cv2.VideoCapture("rtsp://localhost:8554/live/m4td")
```

Tudo neste guia existe para tornar essa linha possível.

## O que você vai montar

```
Matrice 4TD  →  FlightHub 2  →  túnel  →  MediaMTX  →  OpenCV  →  rede neural
   (campo)       (nuvem DJI)   (público)  (servidor)   (Python)
```

## Pré-requisitos

- Conta no FlightHub 2 com papel de **Administrador da organização**
- Dispositivo (dock ou aeronave) vinculado e capaz de ficar online
- Um ambiente Linux com Docker — GitHub Codespaces serve para desenvolvimento
- Nenhum acesso administrativo à rede corporativa é necessário

!!! warning "A restrição que define a arquitetura"
    O FlightHub 2 **não tem API de pull de vídeo**. Todos os caminhos oficiais funcionam por *push*: a nuvem da DJI conecta no seu servidor. Isso significa que sempre haverá um endereço público alcançável no meio do caminho — não é limitação de ferramenta, é arquitetura.

## Caminho rápido

Se você só quer rodar, na ordem:

1. [Subir o MediaMTX](guia/01-mediamtx.md) — 2 minutos
2. [Abrir o túnel](guia/02-tunel.md) — 3 minutos
3. [Configurar o canal no FlightHub](guia/03-flighthub.md) — 5 minutos
4. [Rodar a captura](guia/04-captura.md) — 2 minutos

Se algo não funcionar, [solução de problemas](guia/troubleshooting.md) cobre os erros que aparecem na prática.

## Já configurou antes?

Com os scripts do repositório, as etapas 1 e 2 viram um comando:

```bash
./stop.sh && ./start.sh
```

Ele imprime o endereço RTMP novo, que você cola no FlightHub ([etapa 3](guia/03-flighthub.md)) antes de religar o toggle do canal.

Detalhes em [reiniciar o pipeline](guia/reiniciar.md) — inclui a tabela de qual comando usar para cada sintoma e onde retomar.

## Estado atual validado

Configuração testada e funcionando em 24/08/2026:

| Item | Valor |
|---|---|
| Origem | Matrice 4TD, câmera Carga-zoom |
| Codec | H.264, 960×720 |
| Áudio | AAC 44.1 kHz estéreo (descartado pelo OpenCV) |
| Transporte | RTMP para ingestão, RTSP para consumo |
| Latência ponta a ponta | 3–6 s (ver [redução de latência](guia/latencia.md)) |
