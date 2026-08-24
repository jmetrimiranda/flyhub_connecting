# Comandos rápidos

## Subir tudo

```bash
# 1 — servidor de mídia
docker run -d --name mtx --restart unless-stopped \
  -v $PWD/mediamtx.yml:/mediamtx.yml \
  -p 1935:1935 -p 8554:8554 -p 8888:8888 -p 9997:9997 \
  bluenviron/mediamtx:latest

# 2 — túnel (terminal separado, mantenha aberto)
bore local 1935 --to bore.pub

# 3 — captura (terminal separado)
python3 capture.py
```

## Verificar

```bash
# container de pé?
docker ps | grep mediamtx

# API viva?
curl -s localhost:9997/v3/paths/list

# formatado
curl -s localhost:9997/v3/paths/list | python3 -m json.tool

# só os nomes dos paths
curl -s localhost:9997/v3/paths/list \
  | python3 -c "import sys,json;[print(i['name'],i['ready']) for i in json.load(sys.stdin)['items']]"

# logs ao vivo
docker logs -f mtx

# últimas 50 linhas
docker logs --tail 50 mtx
```

## Testar sem drone

Alimente o servidor com um vídeo local — útil para desenvolver a rede neural sem depender de voo:

```bash
sudo apt install -y ffmpeg

ffmpeg -re -stream_loop -1 -i video.mp4 -c copy -f flv \
  rtmp://localhost:1935/live/m4td
```

O `capture.py` não distingue a origem. Todo o pipeline pode ser validado assim.

## Reiniciar

```bash
docker restart mtx

# limpo
docker rm -f mtx && docker run -d --name mtx --restart unless-stopped \
  -v $PWD/mediamtx.yml:/mediamtx.yml \
  -p 1935:1935 -p 8554:8554 -p 8888:8888 -p 9997:9997 \
  bluenviron/mediamtx:latest
```

## Gravar o stream

```bash
# trecho de 60 s
ffmpeg -i rtsp://localhost:8554/live/m4td -t 60 -c copy saida.mp4

# quadros a 1 fps
ffmpeg -i rtsp://localhost:8554/live/m4td -vf fps=1 frames/%05d.jpg
```

## Ambiente Python

```bash
python3 -m venv .venv

# Linux / macOS
source .venv/bin/activate
# Windows Git Bash
source .venv/Scripts/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

!!! tip
    Use sempre `python -m pip` em vez de `pip`. Antivírus corporativo frequentemente bloqueia o executável `pip.exe`, retornando `Permission denied`, enquanto o módulo passa.

## Diagnóstico de rede

```bash
# IP local
python -c "import socket;s=socket.socket();s.connect(('8.8.8.8',80));print(s.getsockname()[0])"

# IP público
curl -s https://api.ipify.org; echo

# porta alcançável de fora?
nc -zv HOST PORTA
```

## URLs

| Recurso | Endereço |
|---|---|
| Publicação (vai no FlightHub) | `rtmp://HOST:1935/live/m4td` |
| Consumo OpenCV | `rtsp://localhost:8554/live/m4td` |
| Player HLS | `http://HOST:8888/live/m4td` |
| API de status | `http://localhost:9997/v3/paths/list` |
