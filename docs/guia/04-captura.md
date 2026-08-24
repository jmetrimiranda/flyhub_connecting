# 4. Captura no OpenCV

**Onde:** no servidor, terminal separado.

## Confirmar que há vídeo

```bash
curl -s localhost:9997/v3/paths/list | python3 -m json.tool
```

Resposta com stream ativo:

```json
{
  "items": [
    {
      "name": "live/m4td",
      "ready": true,
      "tracks": ["H264", "MPEG-4 Audio"],
      "tracks2": [
        {"codec": "H264", "codecProps": {"width": 960, "height": 720}}
      ],
      "bytesReceived": 34170356
    }
  ]
}
```

`"ready": true` e `bytesReceived` crescendo confirmam que o vídeo está chegando. Se vier `items: []`, veja [solução de problemas](troubleshooting.md).

## Dependências

```bash
python3 -m pip uninstall -y opencv-python opencv-python-headless
python3 -m pip install opencv-python-headless numpy
```

!!! warning "Nunca instale as duas variantes"
    `opencv-python` e `opencv-python-headless` instalam o mesmo módulo `cv2`. Se ambas estiverem presentes, uma sobrescreve a outra e você recebe `ImportError: libGL.so.1`. Em servidor sem tela, use **apenas** a headless.

## Script mínimo

```python
import cv2, os, time

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer"
URL = "rtsp://localhost:8554/live/m4td"

cap = cv2.VideoCapture(URL, cv2.CAP_FFMPEG)
if not cap.isOpened():
    raise SystemExit("nao conectou")

n = 0
while True:
    ok, frame = cap.read()
    if not ok:
        time.sleep(2)
        cap = cv2.VideoCapture(URL, cv2.CAP_FFMPEG)
        continue
    n += 1
    if n % 30 == 0:
        cv2.imwrite("frame.jpg", frame)
        print(f"frame {n} — {frame.shape}")
```

Funciona, mas acumula latência quando a inferência é mais lenta que a taxa de quadros. Para produção, use a versão abaixo.

## Script recomendado

Leitor em thread separada que sempre descarta quadros antigos, mantendo latência constante.

```python
"""Captura RTSP com leitor desacoplado — latência não acumula."""
import os, time, threading
import cv2

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp"
    "|fflags;nobuffer"
    "|flags;low_delay"
    "|reorder_queue_size;0"
    "|max_delay;0"
)

URL = os.environ.get("STREAM_URL", "rtsp://localhost:8554/live/m4td")


class Stream:
    """Mantém sempre o quadro mais recente disponível."""

    def __init__(self, url):
        self.url = url
        self._frame = None
        self._lock = threading.Lock()
        self._running = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _open(self):
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _loop(self):
        cap = self._open()
        fails = 0
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
                self._frame = frame          # descarta o anterior
        cap.release()

    def read(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self):
        self._running = False
        self._t.join(timeout=3)


if __name__ == "__main__":
    stream = Stream(URL)

    print("aguardando primeiro quadro...")
    while stream.read() is None:
        time.sleep(0.2)
    print("conectado")

    n, t0 = 0, time.time()
    try:
        while True:
            frame = stream.read()
            if frame is None:
                time.sleep(0.05)
                continue

            # ---- inferência entra aqui ----
            # results = model(frame)
            # frame = results[0].plot()

            n += 1
            if n % 30 == 0:
                fps = n / (time.time() - t0)
                cv2.imwrite("frame.jpg", frame)
                print(f"{n} quadros | {fps:.1f} fps | {frame.shape}")
    except KeyboardInterrupt:
        stream.stop()
```

## A diferença entre os dois

No script mínimo, `cap.read()` entrega quadros na ordem em que chegaram. Se sua rede neural leva 200 ms e o stream produz 30 fps, a fila cresce indefinidamente — depois de um minuto você está processando imagem de meio minuto atrás.

Na versão com thread, a leitura roda no ritmo da rede e sobrescreve o buffer. O laço principal sempre pega o quadro mais recente. Você perde quadros intermediários, o que para detecção de objeto é irrelevante, e ganha latência constante.

→ [Próximo: visualização](05-visualizacao.md)
