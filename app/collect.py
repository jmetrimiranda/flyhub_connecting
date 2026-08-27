"""Coleta de quadros para dataset: máquina de estados, amostragem e escrita.

    ocioso ─start─► gravando ⇄ pausado ─save─► salvando ─► salvo ─dismiss─► ocioso

Prioridade do sistema
---------------------
Exibir o vídeo é a função principal da tela; a coleta é secundária e nunca pode
degradá-la. Três mecanismos garantem isso, e o quarto mede se garantiram:

1. **A amostradora nunca faz I/O.** Ela decide, atribui o índice e entrega o
   quadro para a fila. Encode e escrita ficam com os workers.
2. **Fila limitada** (`WRITE_QUEUE_MAX`). Cheia, o quadro é descartado na hora e
   contabilizado como `io_dropped`, visível na interface. Nunca bloqueia a
   amostragem, nunca cresce sem teto. Uma fila ilimitada trocaria o problema de
   latência por um de memória: cada item é um quadro decodificado inteiro.
3. **Workers com prioridade rebaixada** (`os.nice`), no máximo dois. Na disputa
   por CPU com o encode do MJPEG, quem cede é a coleta.
4. **Medição.** O FPS de captura e de inferência é amostrado antes do início e
   durante a gravação. Queda acima de `IMPACT_THRESHOLD_PCT` acende um aviso na
   tela em vez de ficar só no relatório.

O tempo dos nomes de arquivo
----------------------------
Vem de `frame.captured_at`, o instante de captura que já viaja no slot do
`video.py` — nenhum timestamp é gerado na hora de gravar. Não se usa
`frame.elapsed`: ele é relativo a `session_started_at`, que o leitor rezera a
cada reconexão do RTSP, e uma reconexão no meio do voo faria os nomes voltarem
para `t0.00`, quebrando o split temporal justamente no caso que a resolução em
"Automático" torna comum.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import deque
from pathlib import Path

import cv2

from . import datasets, pipeline, split
from .inference import detector
from .monitor import monitor
from .video import video

# --- parâmetros -------------------------------------------------------------

IDLE, RECORDING, PAUSED, SAVING, SAVED = "ocioso", "gravando", "pausado", "salvando", "salvo"

STATE_LABELS = {
    IDLE: "Ocioso",
    RECORDING: "Gravando",
    PAUSED: "Pausado",
    SAVING: "Salvando",
    SAVED: "Salvo",
}

INTERVAL_OPTIONS = (0.5, 1.0, 2.0, 5.0)
DEFAULT_INTERVAL = 2.0
DEFAULT_LIMIT = 500
DEFAULT_DEDUP = True

# Diferença média absoluta (0–255) abaixo da qual dois quadros são "o mesmo".
DEDUP_MAD = float(os.environ.get("DEDUP_MAD", "2.0"))
DEDUP_SIZE = 128  # compara em 128×128 cinza: barato e imune a troca de resolução

WRITE_QUEUE_MAX = int(os.environ.get("WRITE_QUEUE_MAX", "20"))
WRITE_WORKERS = 2          # teto fixo: mais threads disputariam CPU com o MJPEG
WRITER_NICE = int(os.environ.get("WRITER_NICE", "10"))
JPEG_QUALITY = int(os.environ.get("COLLECT_JPEG_QUALITY", "92"))

TICK_S = 0.1               # granularidade do laço da amostradora
METRICS_EVERY_S = 1.0
METRICS_WINDOW = 15        # amostras de FPS mantidas (≈15 s)
MIN_METRICS_SAMPLES = 5
IMPACT_THRESHOLD_PCT = 20.0
MIN_BASELINE_FPS = 1.0     # abaixo disto não havia vídeo: impacto não medível
DISK_CHECK_EVERY_S = 5.0
SESSION_FLUSH_EVERY_S = 2.0


class CollectError(RuntimeError):
    pass


def _iso(epoch: float | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch)) if epoch else None


# --- pré-condições ----------------------------------------------------------


def preflight(pipeline_snapshot: dict | None = None) -> dict:
    """Valida as pré-condições da coleta.

    Chamada pelo botão antes de abrir o modal e de novo dentro do `start` — a
    interface pode estar olhando um estado de dois segundos atrás, e o disco
    pode ter enchido nesse intervalo.

    O túnel **não** entra aqui. Gravar depende de o quadro chegar ao leitor
    RTSP local; por onde o drone alcançou o MediaMTX — túnel, IP público, rede
    local — não muda nada depois que o stream está de pé. Exigi-lo bloqueava a
    coleta numa máquina com IP público, onde o túnel nem é usado. O estado dele
    continua visível no cartão do cabeçalho.
    """
    snap = pipeline_snapshot if pipeline_snapshot is not None else pipeline.snapshot()
    stream = monitor.snapshot()
    disk = datasets.disk_usage()

    mtx_up = bool((snap.get("mediamtx") or {}).get("running"))
    api_ok = bool(stream.get("api_ok"))
    paths = [p for p in (stream.get("paths") or []) if p.get("ready")]
    level = stream.get("level")

    checks = [
        {
            "key": "availability",
            "label": "Disponibilidade",
            "ok": level == "green",
            "level": level or "red",
            "detail": stream.get("label") or "—",
            "fix": None if level == "green" else (
                "O drone está publicado mas sem enviar dados. Confira se o toggle do "
                "canal de encaminhamento está ligado no FlightHub."
                if level == "yellow" else
                "Nenhum stream chegando. Suba o pipeline e publique o endereço RTMP no FlightHub."
            ),
        },
        {
            "key": "mediamtx",
            "label": "MediaMTX",
            "ok": mtx_up and api_ok,
            "level": "green" if (mtx_up and api_ok) else ("yellow" if mtx_up else "red"),
            "detail": "no ar, API respondendo" if (mtx_up and api_ok)
                      else ("container no ar, API muda" if mtx_up else "parado"),
            "fix": None if (mtx_up and api_ok) else "Clique em Iniciar pipeline.",
        },
        {
            "key": "stream",
            "label": "Stream",
            "ok": bool(paths),
            "level": "green" if paths else "red",
            "detail": ", ".join(p["name"] for p in paths) if paths else "nenhum path ativo",
            "fix": None if paths else
                   "Confira o endereço no FlightHub e religue o toggle do canal.",
        },
        {
            "key": "disk",
            "label": "Disco",
            "ok": bool(disk.get("ok")) and not disk.get("over_limit"),
            "level": "green" if (disk.get("ok") and not disk.get("over_limit")) else "red",
            "detail": (f"{disk['percent']:.0f}% usado · {disk['free_human']} livres"
                       if disk.get("ok") else (disk.get("error") or "indisponível")),
            "fix": None if (disk.get("ok") and not disk.get("over_limit")) else
                   f"Acima de {disk.get('limit_pct')}% a coleta não inicia. Libere espaço em data/.",
        },
    ]

    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "failed": [c for c in checks if not c["ok"]],
        "next_version": datasets.next_version(),
        "disk": disk,
        "defaults": {
            "interval": DEFAULT_INTERVAL,
            "interval_options": list(INTERVAL_OPTIONS),
            "limit": DEFAULT_LIMIT,
            "dedup": DEFAULT_DEDUP,
            "dedup_mad": DEDUP_MAD,
            "margin": split.DEFAULT_MARGIN,
            "ratios": split.DEFAULT_RATIOS,
        },
    }


# --- sessão -----------------------------------------------------------------


class _Session:
    """Tudo que se sabe sobre uma gravação. Vive até o `dismiss`."""

    def __init__(self, version: str, base: Path, interval: float, limit: int | None, dedup: bool):
        self.version = version
        self.base = base
        self.raw = base / datasets.RAW_DIR
        self.interval = interval
        self.limit = limit
        self.dedup = dedup

        self.started_epoch = time.time()
        self.started_monotonic = time.monotonic()
        self.ended_epoch: float | None = None

        self.t0: float | None = None          # captured_at do primeiro quadro salvo
        self.next_index = 1
        self.records: list[dict] = []
        self.bytes = 0
        self.saved = 0
        self.dedup_skipped = 0
        self.stale_skipped = 0
        self.io_dropped = 0
        self.write_errors = 0
        self.last_file: str | None = None
        self.last_saved_epoch: float | None = None
        self.last_seq = 0
        self.last_gray = None

        self.paused_reason: str | None = None
        self.error: str | None = None
        self.result: dict | None = None       # manifesto do split

        self.baseline: dict | None = None
        self.samples: deque = deque(maxlen=METRICS_WINDOW)
        self.worst_impact = 0.0

    # -- métricas de impacto --

    def impact(self) -> dict:
        base = self.baseline
        if not base or not base.get("available"):
            return {
                "available": False,
                "reason": (base or {}).get("reason", "sem referência"),
                "degraded": False,
            }
        if len(self.samples) < MIN_METRICS_SAMPLES:
            return {"available": False, "reason": "medindo…", "degraded": False}

        current = {
            key: sum(s[key] for s in self.samples) / len(self.samples)
            for key in ("capture_fps", "infer_fps")
        }
        drops = {}
        for key in ("capture_fps", "infer_fps"):
            ref = base[key]
            drops[key] = round((ref - current[key]) / ref * 100, 1) if ref >= MIN_BASELINE_FPS else None
        worst = max((d for d in drops.values() if d is not None), default=0.0)
        self.worst_impact = max(self.worst_impact, worst)
        return {
            "available": True,
            "reason": None,
            "baseline": base,
            "current": {k: round(v, 1) for k, v in current.items()},
            "capture_drop_pct": drops["capture_fps"],
            "infer_drop_pct": drops["infer_fps"],
            "worst_drop_pct": round(worst, 1),
            "peak_drop_pct": round(self.worst_impact, 1),
            "threshold_pct": IMPACT_THRESHOLD_PCT,
            "degraded": worst > IMPACT_THRESHOLD_PCT,
            "samples": len(self.samples),
        }

    # -- session.json --

    def document(self, state: str) -> dict:
        return {
            "version": self.version,
            "status": state,
            "started_at": self.started_epoch,
            "started_at_iso": _iso(self.started_epoch),
            "ended_at": self.ended_epoch,
            "ended_at_iso": _iso(self.ended_epoch),
            "duration_s": round((self.ended_epoch or time.time()) - self.started_epoch, 2),
            "params": {
                "interval_s": self.interval,
                "limit": self.limit,
                "dedup": self.dedup,
                "dedup_mad": DEDUP_MAD if self.dedup else None,
                "jpeg_quality": JPEG_QUALITY,
            },
            "time_base": (
                "t = frame.captured_at - captured_at do primeiro quadro salvo "
                "(relógio monotônico do leitor, imune a reconexão do RTSP)"
            ),
            "counts": {
                "saved": self.saved,
                "dedup_skipped": self.dedup_skipped,
                "stale_skipped": self.stale_skipped,
                "io_dropped": self.io_dropped,
                "write_errors": self.write_errors,
            },
            "bytes": self.bytes,
            "paused_reason": self.paused_reason,
            "error": self.error,
            "impact": self.impact(),
            "stream": {
                "path": pipeline.effective_stream_path(),
                "rtsp_url": pipeline.rtsp_url(),
                "resolution": (video.stats() or {}).get("resolution"),
            },
            "model": {
                "loaded": detector.is_loaded,
                "weights": detector.weights_path.name if detector.is_loaded else None,
            },
            "frames": self.records,
        }

    def flush(self, state: str) -> None:
        """Grava `session.json` de forma atômica.

        tmp + os.replace: uma queda no meio da escrita deixa o arquivo anterior
        intacto, nunca um JSON truncado. E mesmo perdendo o último flush, o
        dataset continua íntegro — o nome de cada arquivo em `raw/` carrega o
        índice e o tempo, que é tudo que o split precisa.
        """
        path = self.base / "session.json"
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(self.document(state), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        except OSError as exc:
            self.error = f"falha ao gravar session.json: {exc}"[:200]


# --- serviço ----------------------------------------------------------------


class CollectService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = IDLE
        self._session: _Session | None = None
        self._token: int | None = None

        self._queue: queue.Queue = queue.Queue(maxsize=WRITE_QUEUE_MAX)
        self._writers: list[threading.Thread] = []
        self._sampler: threading.Thread | None = None
        self._finalizer: threading.Thread | None = None
        self._stop_sampler = threading.Event()

    # -- transições --------------------------------------------------------

    def _refuse(self, message: str) -> dict:
        # `error` depois do estado: invertido, o `error` do status apagaria esta
        # mensagem — mesma ordem de chaves do `pipeline.start`, pelo mesmo motivo.
        return {"ok": False, "collect": self.status(), "error": message}

    def start(self, interval: float, limit: int | None, dedup: bool,
              pipeline_snapshot: dict | None = None) -> dict:
        with self._lock:
            if self._state in (RECORDING, PAUSED, SAVING):
                return self._refuse(f"já existe uma coleta em andamento ({self._state})")

            check = preflight(pipeline_snapshot)
            if not check["ok"]:
                failed = ", ".join(c["label"] for c in check["failed"])
                return {
                    "ok": False,
                    "collect": self.status(),
                    "preflight": check,
                    "error": f"pré-condições não atendidas: {failed}",
                }

            interval = float(interval)
            if interval <= 0:
                return self._refuse("intervalo de amostragem inválido")
            limit = int(limit) if limit else None
            if limit is not None and limit <= 0:
                return self._refuse("limite de quadros inválido")

            version = check["next_version"]
            try:
                base = datasets.create_version(version)
            except OSError as exc:
                return self._refuse(f"não foi possível criar {version}: {exc}")

            session = _Session(version, base, interval, limit, bool(dedup))
            session.baseline = self._baseline()
            self._session = session
            self._state = RECORDING

            # Registra a coleta como consumidora do vídeo: durante a gravação
            # pode não haver nenhum navegador aberto, e o leitor tem que
            # continuar mesmo assim.
            self._token = video.consumers.add("collect", version)

            self._drain_queue()
            self._start_writers()
            self._stop_sampler.clear()
            self._sampler = threading.Thread(target=self._sample_loop, name="collect-sampler", daemon=True)
            self._sampler.start()

            session.flush(RECORDING)
            return {"ok": True, "collect": self.status()}

    def pause(self, reason: str | None = None) -> dict:
        with self._lock:
            if self._state != RECORDING:
                return self._refuse(f"não é possível pausar em {self._state}")
            self._state = PAUSED
            self._session.paused_reason = reason
            self._session.flush(PAUSED)
            return {"ok": True, "collect": self.status()}

    def resume(self) -> dict:
        with self._lock:
            if self._state != PAUSED:
                return self._refuse(f"não é possível continuar em {self._state}")
            disk = datasets.disk_usage()
            if disk.get("over_limit"):
                return self._refuse(
                    f"disco em {disk['percent']:.0f}% — libere espaço antes de continuar"
                )
            self._state = RECORDING
            self._session.paused_reason = None
            self._session.flush(RECORDING)
            return {"ok": True, "collect": self.status()}

    def save(self) -> dict:
        with self._lock:
            if self._state not in (RECORDING, PAUSED):
                return self._refuse(f"não é possível salvar em {self._state}")
            self._state = SAVING
            self._session.ended_epoch = time.time()
            self._finalizer = threading.Thread(
                target=self._finalize, name="collect-finalizer", daemon=True
            )
            self._finalizer.start()
            return {"ok": True, "collect": self.status()}

    def dismiss(self) -> dict:
        with self._lock:
            if self._state != SAVED:
                return self._refuse(f"não é possível dispensar em {self._state}")
            self._session = None
            self._state = IDLE
            return {"ok": True, "collect": self.status()}

    # -- amostragem --------------------------------------------------------

    def _baseline(self) -> dict:
        """FPS de referência, medido no instante anterior ao início da coleta.

        A janela do `_Rate` do leitor é de 3 s, então o valor lido aqui já é a
        média do vídeo *antes* da coleta existir.
        """
        stats = video.stats()
        capture = float(stats.get("capture_fps") or 0.0)
        infer = float(stats.get("infer_fps") or 0.0)
        if not stats.get("connected") or capture < MIN_BASELINE_FPS:
            return {
                "available": False,
                "reason": "não havia vídeo ativo quando a coleta começou",
                "capture_fps": capture,
                "infer_fps": infer,
            }
        return {"available": True, "reason": None, "capture_fps": capture, "infer_fps": infer,
                "at": time.time()}

    def _sample_loop(self) -> None:
        session = self._session
        assert session is not None
        now = time.monotonic()
        next_sample = now
        next_metrics = now
        next_disk = now + DISK_CHECK_EVERY_S
        next_flush = now + SESSION_FLUSH_EVERY_S

        while not self._stop_sampler.is_set():
            now = time.monotonic()

            if now >= next_metrics:
                stats = video.stats()
                if stats.get("connected"):
                    session.samples.append({
                        "capture_fps": float(stats.get("capture_fps") or 0.0),
                        "infer_fps": float(stats.get("infer_fps") or 0.0),
                    })
                next_metrics = now + METRICS_EVERY_S

            if now >= next_disk:
                if datasets.disk_usage().get("over_limit") and self._state == RECORDING:
                    self.pause(f"disco acima de {datasets.DISK_LIMIT_PCT:.0f}% — coleta interrompida")
                next_disk = now + DISK_CHECK_EVERY_S

            if self._state == RECORDING and now >= next_sample:
                self._sample_once(session)
                next_sample += session.interval
                if next_sample < now:  # atraso maior que um intervalo: ressincroniza
                    next_sample = now + session.interval

            if now >= next_flush:
                with self._lock:
                    if self._session is session:
                        session.flush(self._state)
                next_flush = now + SESSION_FLUSH_EVERY_S

            self._stop_sampler.wait(TICK_S)

    def _sample_once(self, session: _Session) -> None:
        rendered = video.latest()
        if rendered is None or rendered.frame.seq == session.last_seq:
            # Sem quadro novo: leitor ocioso, RTSP caído ou reconectando. A
            # sessão continua aberta e volta a gravar sozinha quando o vídeo
            # voltar — é o que mantém a coleta consistente numa queda do MediaMTX.
            session.stale_skipped += 1
            return

        frame = rendered.frame
        session.last_seq = frame.seq
        image = frame.image

        if session.dedup:
            gray = cv2.resize(
                cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
                (DEDUP_SIZE, DEDUP_SIZE),
                interpolation=cv2.INTER_AREA,
            )
            if session.last_gray is not None:
                mad = float(cv2.absdiff(gray, session.last_gray).mean())
                if mad < DEDUP_MAD:
                    session.dedup_skipped += 1
                    return
        else:
            gray = None

        if session.t0 is None:
            session.t0 = frame.captured_at
        t = frame.captured_at - session.t0

        index = session.next_index
        name = f"{index:06d}_t{t:.2f}.jpg"
        job = {
            "session": session,
            "path": session.raw / name,
            "image": image,
            "record": {
                "index": index,
                "file": name,
                "t": round(t, 2),
                "epoch": frame.captured_epoch,
                "seq": frame.seq,
            },
        }
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            # A escrita não acompanha a amostragem. Descartar aqui é a decisão
            # correta: bloquear seguraria a amostradora, e enfileirar faria a
            # memória crescer sem teto — cada item é um quadro decodificado.
            session.io_dropped += 1
            return

        session.next_index += 1
        if gray is not None:
            session.last_gray = gray

        # Conta pelo que foi aceito para escrita, não por `saved`: `saved` é
        # incrementado pelos workers e chegaria atrasado ao limite.
        if session.limit is not None and (session.next_index - 1) >= session.limit:
            # Auto-pausa, não auto-salva: salvar dispara o split, e essa decisão
            # é do operador. A sessão fica aberta e pode continuar se ele quiser.
            self.pause(f"limite de {session.limit} quadros atingido")

    # -- escrita -----------------------------------------------------------

    def _start_writers(self) -> None:
        self._writers = []
        for i in range(WRITE_WORKERS):
            thread = threading.Thread(target=self._writer_loop, name=f"collect-writer-{i}", daemon=True)
            thread.start()
            self._writers.append(thread)

    def _writer_loop(self) -> None:
        try:
            # No Linux, nice() vale para a thread que chama, não para o processo:
            # só os workers de escrita cedem CPU, o leitor e o encode do MJPEG não.
            os.nice(WRITER_NICE)
        except OSError:
            pass

        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                self._write(job)
            finally:
                self._queue.task_done()

    @staticmethod
    def _write(job: dict) -> None:
        session: _Session = job["session"]
        try:
            ok, buffer = cv2.imencode(
                ".jpg", job["image"], [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
            )
            if not ok:
                raise OSError("imencode falhou")
            data = buffer.tobytes()
            tmp = job["path"].with_suffix(".jpg.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, job["path"])
        except (OSError, cv2.error) as exc:
            session.write_errors += 1
            session.error = f"falha ao gravar quadro: {exc}"[:200]
            return

        record = {**job["record"], "bytes": len(data)}
        session.records.append(record)
        session.saved += 1
        session.bytes += len(data)
        session.last_file = record["file"]
        session.last_saved_epoch = record["epoch"]

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
            self._queue.task_done()

    def _stop_writers(self) -> None:
        for _ in self._writers:
            self._queue.put(None)
        for thread in self._writers:
            thread.join(timeout=10)
        self._writers = []

    # -- finalização e split ----------------------------------------------

    def _finalize(self) -> None:
        """Encerra a sessão e dispara o split. Único lugar que chama `split.run`."""
        session = self._session
        assert session is not None

        # 1. nenhum quadro novo entra
        self._stop_sampler.set()
        if self._sampler:
            self._sampler.join(timeout=10)
            self._sampler = None

        # 2. barreira: toda escrita pendente termina antes de listar raw/.
        #    Sem isto, um arquivo ainda na fila sairia calado do manifesto.
        self._queue.join()
        self._stop_writers()

        # 3. estado em disco antes de mexer em qualquer coisa
        session.flush(SAVING)

        # 4. o split — thread única, sem paralelismo
        manifest = None
        try:
            manifest = split.run(
                session.base,
                session=self._session_summary(session),
            )
        except split.SplitError as exc:
            session.error = f"split não pôde ser executado: {exc}"[:300]
        except OSError as exc:
            session.error = f"falha de I/O durante o split: {exc}"[:300]

        # 5. resultado gravado antes de anunciar
        session.result = manifest
        session.flush(SAVED)

        # 6. estado final; o vídeo deixa de ter a coleta como consumidora
        with self._lock:
            self._state = SAVED
            if self._token is not None:
                video.consumers.discard(self._token)
                self._token = None

    @staticmethod
    def _session_summary(session: _Session) -> dict:
        doc = session.document(SAVED)
        doc.pop("frames", None)  # o manifesto já traz o mapeamento arquivo a arquivo
        return doc

    # -- estado ------------------------------------------------------------

    def status(self) -> dict:
        with self._lock:
            state = self._state
            session = self._session

        base = {
            "state": state,
            "state_label": STATE_LABELS[state],
            "active": state in (RECORDING, PAUSED, SAVING),
            "queue": {"depth": self._queue.qsize(), "max": WRITE_QUEUE_MAX},
            "workers": WRITE_WORKERS,
            # O cliente valida a guarda antes de abrir o modal, e o disco é a
            # única das cinco pré-condições que não chega por outro bloco do SSE.
            "disk": datasets.disk_usage(),
            "limits": {
                "interval_options": list(INTERVAL_OPTIONS),
                "dedup_mad": DEDUP_MAD,
                "margin": split.DEFAULT_MARGIN,
                "disk_limit_pct": datasets.DISK_LIMIT_PCT,
                "impact_threshold_pct": IMPACT_THRESHOLD_PCT,
            },
        }
        if session is None:
            return {**base, "session": None}

        elapsed = (session.ended_epoch or time.time()) - session.started_epoch
        return {
            **base,
            "session": {
                "version": session.version,
                "dir": str(session.base),
                "started_at": session.started_epoch,
                "started_at_iso": _iso(session.started_epoch),
                "elapsed_s": round(elapsed, 1),
                "interval_s": session.interval,
                "limit": session.limit,
                "dedup": session.dedup,
                "saved": session.saved,
                "bytes": session.bytes,
                "bytes_human": datasets.human_bytes(session.bytes),
                "dedup_skipped": session.dedup_skipped,
                "stale_skipped": session.stale_skipped,
                "io_dropped": session.io_dropped,
                "write_errors": session.write_errors,
                "last_file": session.last_file,
                "paused_reason": session.paused_reason,
                "error": session.error,
                "impact": session.impact(),
                "result": self._result_summary(session),
            },
        }

    @staticmethod
    def _result_summary(session: _Session) -> dict | None:
        manifest = session.result
        if manifest is None:
            return None
        return {
            "version": manifest["version"],
            "strategy": manifest["strategy"],
            "counts": manifest["counts"],
            "total_raw": manifest["total_raw"],
            "ratios": manifest["ratios"],
            "margin_requested": manifest["margin_requested"],
            "margin_applied": manifest["margin_applied"],
            "time_span": manifest["time_span"],
            "boundaries": manifest["boundaries"],
            "warnings": manifest["warnings"],
            "manifest": str(Path(manifest["version"]) / split.MANIFEST_NAME),
        }

    def shutdown(self) -> None:
        """Encerra sem perder o que já está em disco."""
        self._stop_sampler.set()
        if self._sampler:
            self._sampler.join(timeout=5)
        if self._writers:
            self._queue.join()
            self._stop_writers()
        with self._lock:
            if self._session is not None and self._state in (RECORDING, PAUSED):
                self._session.flush(self._state)


collect = CollectService()
