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

## Comandos de subida

```bash
# servidor de mídia
docker run -d --name mtx --restart unless-stopped \
  -v $PWD/mediamtx.yml:/mediamtx.yml \
  -p 1935:1935 -p 8554:8554 -p 8888:8888 -p 9997:9997 \
  bluenviron/mediamtx:latest

# túnel (terminal separado)
bore local 1935 --to bore.pub

# captura (terminal separado)
python3 capture.py
```
