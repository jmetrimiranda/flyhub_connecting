# Arquivos de configuração

Todos prontos para copiar. A estrutura assumida:

```
flighthub-pipeline/
├── mediamtx.yml
├── capture.py
├── viewer.py
├── requirements.txt
├── .env
└── .gitignore
```

## `mediamtx.yml`

```yaml
logLevel: info

rtmp: yes
rtmpAddress: :1935

rtsp: yes
rtspAddress: :8554
rtspTransports: [tcp]

hls: yes
hlsAddress: :8888
hlsVariant: lowLatency
hlsPartDuration: 200ms
hlsSegmentDuration: 1s
hlsAlwaysRemux: no

api: yes
apiAddress: :9997

webrtc: no
srt: no

authInternalUsers:
  - user: any
    ips: []
    permissions:
      - action: publish
      - action: read
      - action: playback
      - action: api
      - action: metrics

paths:
  all_others:
```

## `requirements.txt`

```
opencv-python-headless>=4.10
numpy>=1.26
flask>=3.0
requests>=2.32
python-dotenv>=1.0
```

!!! warning
    Nunca inclua `opencv-python` junto com `opencv-python-headless`. As duas fornecem o módulo `cv2` e o conflito gera `ImportError: libGL.so.1`.

## `.env`

```bash
STREAM_URL=rtsp://localhost:8554/live/m4td
MEDIAMTX_API=http://localhost:9997
JPEG_QUALITY=75

# OpenAPI do FlightHub — opcional
FH2_ORG_KEY=
FH2_PROJECT_UUID=
```

## `.gitignore`

```
.venv/
__pycache__/
*.pyc
.env
*.jpg
*.mp4
datasets/
runs/
```

## `capture.py`

Ver [etapa 4](../guia/04-captura.md) para a versão comentada.

```python
import os, time, threading
import cv2

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay"
    "|reorder_queue_size;0|max_delay;0"
)
URL = os.environ.get("STREAM_URL", "rtsp://localhost:8554/live/m4td")


class Stream:
    def __init__(self, url):
        self.url = url
        self._frame = None
        self._lock = threading.Lock()
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _open(self):
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _loop(self):
        cap, fails = self._open(), 0
        while self._running:
            ok, frame = cap.read()
            if not ok:
                fails += 1
                cap.release()
                time.sleep(min(2 * fails, 10))
                cap = self._open()
                continue
            fails = 0
            with self._lock:
                self._frame = frame
        cap.release()

    def read(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self):
        self._running = False


if __name__ == "__main__":
    s = Stream(URL)
    while s.read() is None:
        time.sleep(0.2)
    print("conectado")

    n, t0 = 0, time.time()
    while True:
        frame = s.read()
        if frame is None:
            time.sleep(0.05)
            continue
        n += 1
        if n % 30 == 0:
            cv2.imwrite("frame.jpg", frame)
            print(f"{n} | {n/(time.time()-t0):.1f} fps | {frame.shape}")
```

## `start.sh`

Sobe MediaMTX e túnel de uma vez e imprime o endereço RTMP. Idempotente — remove o container anterior antes de criar.

```bash
#!/usr/bin/env bash
set -euo pipefail

PATH_NAME="${STREAM_PATH:-live/m4td}"

echo "==> MediaMTX"
docker rm -f mtx >/dev/null 2>&1 || true
docker run -d --name mtx --restart unless-stopped \
  -v "$PWD/config/mediamtx.yml:/mediamtx.yml" \
  -p 1935:1935 -p 8554:8554 -p 8888:8888 -p 9997:9997 \
  bluenviron/mediamtx:latest >/dev/null

for i in $(seq 1 15); do
  curl -sf localhost:9997/v3/paths/list >/dev/null 2>&1 && break
  sleep 1
done
curl -sf localhost:9997/v3/paths/list >/dev/null || {
  echo "ERRO: API não respondeu. Veja: docker logs mtx"; exit 1; }
echo "    API respondendo"

echo "==> Túnel"
pkill -f "bore local" 2>/dev/null || true
nohup bore local 1935 --to bore.pub > /tmp/bore.log 2>&1 &

ADDR=""
for i in $(seq 1 20); do
  ADDR=$(grep -oP 'listening at \K\S+' /tmp/bore.log 2>/dev/null | tail -1 || true)
  [ -n "$ADDR" ] && break
  sleep 1
done
[ -n "$ADDR" ] || { echo "ERRO: túnel não subiu. Veja /tmp/bore.log"; exit 1; }

cat <<EOF

  Cole no FlightHub → Endereço do servidor:

      rtmp://${ADDR}/${PATH_NAME}

  Depois: desligue e religue o toggle do canal.

  Consumo OpenCV : rtsp://localhost:8554/${PATH_NAME}
  Player HLS     : porta 8888, path /${PATH_NAME}

EOF
```

Para usar outro path: `STREAM_PATH=live/dock3 ./start.sh`

## `stop.sh`

```bash
#!/usr/bin/env bash
docker rm -f mtx 2>/dev/null && echo "MediaMTX parado"
pkill -f "bore local" 2>/dev/null && echo "Túnel parado"
echo "Pipeline encerrado."
```

## `.devcontainer/devcontainer.json`

Faz o Codespace se reconfigurar sozinho após rebuild.

```json
{
  "name": "flyhub-connecting",
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
  "features": {
    "ghcr.io/devcontainers/features/docker-in-docker:2": {}
  },
  "postCreateCommand": "bash .devcontainer/setup.sh",
  "forwardPorts": [8000, 8888, 5000],
  "portsAttributes": {
    "8000": { "label": "MkDocs" },
    "8888": { "label": "HLS", "visibility": "public" },
    "5000": { "label": "Viewer MJPEG" }
  }
}
```

## `.devcontainer/setup.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg libgl1 libglib2.0-0 >/dev/null

if ! command -v bore >/dev/null 2>&1; then
  URL=$(curl -s https://api.github.com/repos/ekzhang/bore/releases/latest \
    | grep browser_download_url | grep x86_64-unknown-linux-musl | cut -d '"' -f 4)
  curl -sL "$URL" | tar xz -C /tmp
  sudo mv /tmp/bore /usr/local/bin/
fi

python -m pip install --upgrade pip --quiet
[ -f requirements.txt ]      && python -m pip install -q -r requirements.txt
[ -f requirements-docs.txt ] && python -m pip install -q -r requirements-docs.txt

docker pull -q bluenviron/mediamtx:latest
chmod +x start.sh stop.sh 2>/dev/null || true
```

## `.gitattributes`

Sem isso, um script editado no Windows chega ao Linux com CRLF e falha com `bad interpreter: /bin/bash^M`.

```
* text=auto eol=lf
*.sh text eol=lf
*.py text eol=lf
*.yml text eol=lf
*.md text eol=lf
```

## Comandos de subida

Com os scripts:

```bash
./stop.sh && ./start.sh
python3 capture.py
```

Manualmente:

```bash
docker run -d --name mtx --restart unless-stopped \
  -v $PWD/config/mediamtx.yml:/mediamtx.yml \
  -p 1935:1935 -p 8554:8554 -p 8888:8888 -p 9997:9997 \
  bluenviron/mediamtx:latest

bore local 1935 --to bore.pub   # terminal separado
python3 capture.py              # terminal separado
```
