import cv2, os, time

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer"
URL = "rtsp://localhost:8554/live/m4td"

def connect():
    c = cv2.VideoCapture(URL, cv2.CAP_FFMPEG)
    c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return c

cap = connect()
if not cap.isOpened():
    raise SystemExit("nao conectou")

print("conectado")
n = 0
while True:
    ok, frame = cap.read()
    if not ok:
        print("reconectando...")
        cap.release(); time.sleep(2); cap = connect()
        continue

    # >>> SUA REDE NEURAL AQUI <
    # results = model(frame)

    n += 1
    if n % 30 == 0:
        cv2.imwrite("frame.jpg", frame)
        print(f"frame {n} — {frame.shape}")
