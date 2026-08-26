"""Leitura do RTSP, inferência e MJPEG.

Três estágios desacoplados, cada um no seu ritmo:

    RTSP ──► leitor (thread) ──► slot ──► worker (thread) ──► slot ──► N clientes
             sempre o último     de 1     detect + overlay    de 1     /stream
             quadro decodificado  quadro   + imencode          JPEG

Entre os estágios há um *slot de um quadro*, não uma fila. É isso que impede a
latência de acumular quando a inferência é mais lenta que o stream: o quadro
velho é sobrescrito e contabilizado como perdido, e o worker sempre pega o mais
recente. Uma fila daria o comportamento oposto — nada se perderia e a latência
cresceria sem teto.

A inferência roda uma vez por quadro, não uma vez por cliente: dois navegadores
abertos não dobram o custo.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from . import pipeline
from .inference import Detection, detector
from .monitor import monitor

# rtsp_transport=tcp evita perda de pacotes em UDP; stimeout impede que um
# servidor morto deixe o VideoCapture pendurado indefinidamente na abertura.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000"
)

JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "80"))
RECONNECT_MIN_S = 1.0
RECONNECT_MAX_S = 10.0          # teto do backoff exponencial
IDLE_CLOSE_S = 10.0             # sem consumidor por esse tempo => fecha o RTSP
NO_PATH_POLL_S = 1.0            # com o monitor dizendo que não há path, só relê memória
NO_PATH_MESSAGE = "nenhum path publicando no MediaMTX"
RESOLUTION_WARNING_S = 300.0    # o aviso de troca de resolução some sozinho
RATE_WINDOW_S = 3.0

BOUNDARY = "frame"


# --- medição ----------------------------------------------------------------


class _Rate:
    """Taxa por janela deslizante. Média de N segundos, não desde o início."""

    def __init__(self, window: float = RATE_WINDOW_S) -> None:
        self._window = window
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def tick(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._events.append(now)
            cutoff = now - self._window
            while self._events and self._events[0] < cutoff:
                self._events.popleft()

    def value(self) -> float:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self._window
            while self._events and self._events[0] < cutoff:
                self._events.popleft()
            if len(self._events) < 2:
                return 0.0
            span = self._events[-1] - self._events[0]
            return round((len(self._events) - 1) / span, 1) if span > 0 else 0.0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


# --- quadros ----------------------------------------------------------------


@dataclass
class Frame:
    """Um quadro decodificado e o instante em que foi capturado.

    O instante viaja junto com a imagem por dois motivos: medir a latência de
    ponta a ponta (captura → JPEG pronto) e, na fatia 2, nomear os arquivos com
    o tempo relativo ao início da captura — que é o que permite o split
    temporal por blocos contíguos sem reabrir o banco.
    """

    image: Any
    seq: int
    captured_at: float          # time.monotonic() — para medir intervalos
    captured_epoch: float       # time.time() — para datar em disco
    session_started_at: float   # monotonic de quando esta conexão RTSP abriu

    @property
    def elapsed(self) -> float:
        """Segundos desde o início desta captura. Vira `_t12.50.jpg` na fatia 2."""
        return self.captured_at - self.session_started_at

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.image.shape[:2]
        return w, h


@dataclass
class Rendered:
    """O que sai do worker: o JPEG anotado e o quadro cru que o gerou.

    A coleta da fatia 2 grava `frame.image` (sem sobreposição) usando
    `frame.elapsed` no nome — a sobreposição é só para o operador olhar.
    """

    jpeg: bytes
    frame: Frame
    detections: list[Detection] = field(default_factory=list)
    latency_ms: float = 0.0


class _Slot:
    """Espaço para exatamente um item. Publicar sobrescreve; ninguém enfileira."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._item: Any = None
        self._seq = 0
        self._taken = True
        self.dropped = 0

    def publish(self, item: Any) -> None:
        with self._cond:
            if not self._taken:
                self.dropped += 1  # ninguém consumiu o anterior
            self._item = item
            self._seq += 1
            self._taken = False
            self._cond.notify_all()

    def take(self, last_seq: int, timeout: float) -> tuple[Any, int] | None:
        """Bloqueia até haver item mais novo que `last_seq`. None no timeout."""
        with self._cond:
            if self._seq == last_seq:
                self._cond.wait(timeout)
            if self._seq == last_seq or self._item is None:
                return None
            self._taken = True
            return self._item, self._seq

    def peek(self) -> Any:
        with self._cond:
            return self._item

    def clear(self) -> None:
        with self._cond:
            self._item = None
            self._taken = True


# --- consumidores -----------------------------------------------------------


class Consumers:
    """Quem precisa do RTSP aberto.

    A fatia 1 registra apenas clientes MJPEG. A fatia 2 registra a coleta com
    `kind="collect"`: durante uma gravação pode não haver nenhum navegador
    aberto, e mesmo assim o leitor tem que continuar. Por isso a decisão de
    fechar o RTSP olha o total de consumidores, nunca a contagem de clientes
    HTTP.
    """

    KINDS = ("mjpeg", "collect")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._entries: dict[int, dict] = {}

    def add(self, kind: str, label: str | None = None) -> int:
        if kind not in self.KINDS:
            raise ValueError(f"consumidor desconhecido: {kind}")
        with self._lock:
            token = next(self._ids)
            self._entries[token] = {
                "kind": kind,
                "label": label or kind,
                "since": time.time(),
            }
            return token

    def discard(self, token: int) -> None:
        with self._lock:
            self._entries.pop(token, None)

    def total(self) -> int:
        with self._lock:
            return len(self._entries)

    def counts(self) -> dict:
        with self._lock:
            entries = list(self._entries.values())
        counts = {kind: 0 for kind in self.KINDS}
        for entry in entries:
            counts[entry["kind"]] += 1
        counts["total"] = len(entries)
        return counts


# --- serviço ----------------------------------------------------------------


class VideoService:
    def __init__(self) -> None:
        self.consumers = Consumers()
        self._raw = _Slot()
        self._out = _Slot()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

        self._capture_rate = _Rate()
        self._infer_rate = _Rate()
        self._latency_ms = 0.0
        self._frames = 0
        self._seq = itertools.count(1)

        self._connected = False
        self._source: str | None = None
        self._error: str | None = None
        self._reconnects = 0
        self._retry_at: float | None = None
        self._session_started_at: float | None = None
        self._resolution: tuple[int, int] | None = None
        self._res_change: dict | None = None
        self._placeholder_cache: tuple[str, bytes] | None = None

    # -- ciclo de vida -----------------------------------------------------

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for target, name in ((self._reader_loop, "video-reader"), (self._worker_loop, "video-worker")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=3)
        self._threads.clear()

    # -- leitor ------------------------------------------------------------

    def _rtsp_url(self) -> str:
        return pipeline.rtsp_url()

    def _path_ready(self) -> bool | None:
        """O monitor sabe se há path publicando? `None` quando ele não sabe.

        Com a API do MediaMTX fora do ar não dá para concluir que não há path —
        o servidor RTSP pode estar servindo normalmente. Nesse caso a resposta é
        `None` e o leitor tenta abrir, com backoff.
        """
        snapshot = monitor.snapshot()
        if not snapshot.get("api_ok"):
            return None
        return any(p.get("ready") for p in snapshot.get("paths") or [])

    def _reader_loop(self) -> None:
        cap = None
        backoff = RECONNECT_MIN_S
        idle_since: float | None = None
        waiting_for_path = False

        while not self._stop.is_set():
            if self.consumers.total() == 0:
                # Ninguém olhando e nenhuma coleta: não consome o RTSP.
                if cap is not None:
                    if idle_since is None:
                        idle_since = time.monotonic()
                    elif time.monotonic() - idle_since >= IDLE_CLOSE_S:
                        cap.release()
                        cap = None
                        self._on_disconnect(None)
                self._stop.wait(0.25)
                continue

            idle_since = None

            if cap is None:
                # Quando o monitor tem certeza de que não há path, abrir o RTSP
                # gastaria um processo de FFmpeg por tentativa para receber o
                # mesmo 404. Esperar aqui custa uma leitura de memória, e o
                # backoff fica reservado para falha de conexão de verdade — o
                # que também faz a captura começar em menos de um segundo
                # quando o drone finalmente publica.
                if self._path_ready() is False:
                    if not waiting_for_path:
                        waiting_for_path = True
                        self._on_disconnect(NO_PATH_MESSAGE)
                    backoff = RECONNECT_MIN_S
                    self._stop.wait(NO_PATH_POLL_S)
                    continue
                waiting_for_path = False

                url = self._rtsp_url()
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except cv2.error:
                    pass
                if not cap.isOpened():
                    cap.release()
                    cap = None
                    self._on_disconnect(f"não foi possível abrir {url}")
                    backoff = self._wait_backoff(backoff)
                    continue
                self._on_connect(url)
                # O backoff NÃO é zerado aqui. Um path que abre e nunca entrega
                # quadro — publicador que caiu sem o MediaMTX derrubar o path —
                # reiniciaria o backoff a cada ciclo, e o leitor ficaria abrindo
                # o RTSP uma vez por segundo para sempre. Só um quadro de
                # verdade confirma que a conexão serve para alguma coisa.

            ok, image = cap.read()
            if not ok or image is None:
                cap.release()
                cap = None
                self._on_disconnect("stream interrompido")
                backoff = self._wait_backoff(backoff)
                continue

            backoff = RECONNECT_MIN_S
            self._publish_raw(image)

        if cap is not None:
            cap.release()

    def _wait_backoff(self, backoff: float) -> float:
        with self._lock:
            self._retry_at = time.monotonic() + backoff
        self._stop.wait(backoff)
        with self._lock:
            self._retry_at = None
        return min(backoff * 2, RECONNECT_MAX_S)

    def _on_connect(self, url: str) -> None:
        with self._lock:
            self._connected = True
            self._source = url
            self._error = None
            self._session_started_at = time.monotonic()
            self._frames = 0
            # `_resolution` NÃO é zerada aqui de propósito: no FlightHub, trocar
            # a qualidade do canal derruba a sessão RTSP, e a resolução nova só
            # aparece na reconexão seguinte. Zerar aqui apagaria a comparação
            # justamente no caso que o aviso existe para pegar.
        self._capture_rate.reset()
        self._infer_rate.reset()

    def _on_disconnect(self, error: str | None) -> None:
        with self._lock:
            was_connected = self._connected
            self._connected = False
            self._error = error
            self._session_started_at = None
            self._latency_ms = 0.0
            if error and was_connected:
                self._reconnects += 1
        self._capture_rate.reset()
        self._infer_rate.reset()
        self._raw.clear()
        self._out.clear()

    def _publish_raw(self, image) -> None:
        now = time.monotonic()
        with self._lock:
            started = self._session_started_at or now
            self._frames += 1
            height, width = image.shape[:2]
            if self._resolution is None:
                self._resolution = (width, height)
            elif self._resolution != (width, height):
                # A causa mais comum de queda da captura: qualidade "Automático"
                # no FlightHub trocando o perfil do encoder no meio do voo.
                self._res_change = {
                    "from": f"{self._resolution[0]}×{self._resolution[1]}",
                    "to": f"{width}×{height}",
                    "at": time.time(),
                    "at_monotonic": now,
                }
                self._resolution = (width, height)

        self._capture_rate.tick()
        self._raw.publish(
            Frame(
                image=image,
                seq=next(self._seq),
                captured_at=now,
                captured_epoch=time.time(),
                session_started_at=started,
            )
        )

    # -- worker ------------------------------------------------------------

    def _worker_loop(self) -> None:
        last_seq = 0
        while not self._stop.is_set():
            if self.consumers.total() == 0:
                self._stop.wait(0.25)
                continue

            item = self._raw.take(last_seq, 0.5)
            if item is None:
                continue
            frame, last_seq = item

            _, detections = detector.detect(frame.image)

            annotated = frame.image.copy()
            detector.draw(annotated, detections)
            self._hud(annotated, frame, len(detections))

            ok, buffer = cv2.imencode(
                ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
            )
            if not ok:
                continue

            latency_ms = (time.monotonic() - frame.captured_at) * 1000
            with self._lock:
                self._latency_ms = latency_ms
            self._infer_rate.tick()
            self._out.publish(
                Rendered(
                    jpeg=buffer.tobytes(),
                    frame=frame,
                    detections=detections,
                    latency_ms=latency_ms,
                )
            )

    def _hud(self, image, frame: Frame, n_detections: int) -> None:
        width, height = frame.size
        mode = "modelo ativo" if detector.is_loaded else "sem modelo"
        left = f"{self._capture_rate.value():.1f} fps  {width}×{height}  #{frame.seq}"
        right = f"{mode}  {n_detections} det" if detector.is_loaded else mode

        cv2.rectangle(image, (0, 0), (width, 26), (0, 0, 0), -1)
        cv2.putText(image, left, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (230, 237, 243), 1, cv2.LINE_AA)
        (tw, _), _ = cv2.getTextSize(right, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        color = (80, 200, 120) if detector.is_loaded else (34, 153, 210)
        cv2.putText(image, right, (max(width - tw - 8, 8), 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

    # -- placeholder -------------------------------------------------------

    @staticmethod
    def _wrap(text: str, max_width: int, scale: float) -> list[str]:
        lines, current = [], ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            (width, _), _ = cv2.getTextSize(candidate, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
            if width > max_width and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines[:3]

    def _placeholder(self) -> bytes:
        """Quadro sintético quando não há sinal.

        Emitir isto em vez de encerrar o multipart mantém a conexão viva: quando
        o stream voltar, a imagem volta sozinha, sem o navegador precisar
        reconectar — e o operador lê o motivo em vez de ver ícone quebrado.
        """
        with self._lock:
            error = self._error
            retry_at = self._retry_at
        detail = error or "nenhum quadro recebido ainda"
        if retry_at:
            detail += f" — nova tentativa em {max(retry_at - time.monotonic(), 0):.0f} s"

        if self._placeholder_cache and self._placeholder_cache[0] == detail:
            return self._placeholder_cache[1]

        canvas = np.full((360, 640, 3), 18, dtype=np.uint8)
        cv2.putText(canvas, "Aguardando stream", (40, 150), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (230, 237, 243), 2, cv2.LINE_AA)
        for i, line in enumerate(self._wrap(detail, 560, 0.5)):
            cv2.putText(canvas, line, (40, 186 + i * 22), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (139, 148, 158), 1, cv2.LINE_AA)
        ok, buffer = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        data = buffer.tobytes() if ok else b""
        self._placeholder_cache = (detail, data)
        return data

    # -- saída -------------------------------------------------------------

    def latest(self) -> Rendered | None:
        """Último quadro renderizado. A fatia 2 lê daqui para gravar."""
        return self._out.peek()

    async def mjpeg(self):
        """Gerador multipart/x-mixed-replace. Um consumidor por cliente."""
        token = self.consumers.add("mjpeg")
        loop = asyncio.get_running_loop()
        last_seq = 0
        try:
            while not self._stop.is_set():
                item = await loop.run_in_executor(None, self._out.take, last_seq, 1.0)
                if item is None:
                    jpeg = self._placeholder()  # timeout de 1 s => ~1 fps parado
                else:
                    rendered, last_seq = item
                    jpeg = rendered.jpeg
                yield (
                    b"--" + BOUNDARY.encode() + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                    + jpeg + b"\r\n"
                )
        finally:
            self.consumers.discard(token)

    # -- estado ------------------------------------------------------------

    def stats(self) -> dict:
        with self._lock:
            connected = self._connected
            source = self._source
            error = self._error
            reconnects = self._reconnects
            retry_at = self._retry_at
            started = self._session_started_at
            resolution = self._resolution
            latency = self._latency_ms
            frames = self._frames
            res_change = dict(self._res_change) if self._res_change else None

        now = time.monotonic()
        if res_change and now - res_change.pop("at_monotonic") > RESOLUTION_WARNING_S:
            # Sem nova troca por 5 min, o problema passou: o aviso some sozinho.
            res_change = None

        rendered = self._out.peek()
        return {
            "connected": connected,
            "source": source,
            "error": error,
            "reconnects": reconnects,
            "retry_in_s": round(retry_at - now, 1) if retry_at else None,
            "consumers": self.consumers.counts(),
            "capture_fps": self._capture_rate.value(),
            "infer_fps": self._infer_rate.value(),
            "latency_ms": round(latency, 1),
            "dropped": self._raw.dropped,
            "frames": frames,
            "capture_uptime_s": round(now - started, 1) if started else None,
            "resolution": f"{resolution[0]}×{resolution[1]}" if resolution else None,
            "resolution_change": res_change,
            "detections": len(rendered.detections) if rendered else 0,
        }


video = VideoService()
