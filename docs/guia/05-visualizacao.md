# 5. Visualização

Três formas de ver o vídeo, da mais simples à mais útil.

## Quadro isolado

O script grava `frame.jpg` a cada 30 quadros. No VS Code, clique no arquivo na árvore lateral. Clique fora e volte para recarregar.

Serve para conferir enquadramento e qualidade rapidamente.

## HLS no navegador

O MediaMTX já serve um player pronto.

**Em Codespaces:**

1. Aba **PORTS** → **Forward a Port** → `8888`
2. Botão direito na linha → **Port Visibility** → **Public**
3. Abra a URL gerada acrescentando o path:

```
https://<seu-codespace>-8888.app.github.dev/live/m4td
```

**Em VM:** `http://IP:8888/live/m4td`

Vídeo original, sem processamento. Latência de 3 a 6 segundos — natural do HLS, que empacota em segmentos.

!!! note "Avisos de part duration nos logs"
    Mensagens como `part duration changed from 225ms to 245ms — this will cause an error in iOS clients` são normais quando o encoder da DJI tem taxa variável. Afetam apenas players iOS nativos. Chrome e Firefox ignoram.

## MJPEG com a saída da rede neural

Esta é a que importa em operação: mostra o quadro **depois** do processamento, com caixas e labels desenhados.

```python
"""Servidor MJPEG — mostra o quadro processado no navegador."""
import os, time, threading
import cv2
from flask import Flask, Response

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay"
)
URL = os.environ.get("STREAM_URL", "rtsp://localhost:8554/live/m4td")
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "75"))

app = Flask(__name__)
state = {"jpg": None, "fps": 0.0}


def worker():
    cap = cv2.VideoCapture(URL, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    n, t0 = 0, time.time()

    while True:
        ok, frame = cap.read()
        if not ok:
            cap.release()
            time.sleep(2)
            cap = cv2.VideoCapture(URL, cv2.CAP_FFMPEG)
            continue

        # ---- inferência ----
        # results = model(frame)
        # frame = results[0].plot()

        n += 1
        if n % 10 == 0:
            state["fps"] = n / (time.time() - t0)

        cv2.putText(frame, f"{state['fps']:.1f} fps", (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        ok, buf = cv2.imencode(".jpg", frame,
                               [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if ok:
            state["jpg"] = buf.tobytes()


threading.Thread(target=worker, daemon=True).start()


@app.route("/")
def index():
    return """<!doctype html><meta charset=utf-8>
    <title>Stream</title>
    <body style="margin:0;background:#0e0e10;display:grid;place-items:center;height:100vh">
    <img src="/stream" style="max-width:100%;max-height:100vh">
    </body>"""


@app.route("/stream")
def stream():
    def gen():
        while True:
            if state["jpg"]:
                yield (b"--f\r\nContent-Type: image/jpeg\r\n\r\n"
                       + state["jpg"] + b"\r\n")
            time.sleep(0.03)
    return Response(gen(),
                    mimetype="multipart/x-mixed-replace; boundary=f")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
```

```bash
python3 -m pip install flask
python3 viewer.py
```

O Codespaces detecta a porta 5000 e oferece abrir no navegador.

## Comparação

| Método | Latência extra | Mostra inferência | Uso |
|---|---|---|---|
| `frame.jpg` | — | Sim | Conferência pontual |
| HLS | 3–6 s | Não | Compartilhar com quem só quer ver |
| MJPEG | ~0,1 s | Sim | Operação e depuração |

→ [Próximo: reduzir latência](latencia.md)
