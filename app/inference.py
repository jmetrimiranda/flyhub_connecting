"""Detector de objetos com dois modos: com pesos e sem pesos.

Sem pesos — que é o estado inicial do projeto, antes de existir qualquer dataset
— `detect()` devolve o quadro intacto e nenhuma detecção. Não levanta exceção e
não impede a aplicação de subir. É o modo *passthrough*, e a interface precisa
dizer que está nele: ver vídeo cru achando que são detecções reais é pior que
não ver nada.

`ultralytics` é importado dentro da função de carga, nunca no topo do módulo,
para que a aplicação suba numa máquina sem torch instalado.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEIGHTS = ROOT / "data" / "models" / "best.pt"

CONF_THRESHOLD = float(os.environ.get("MODEL_CONF", "0.25"))
# Um stat() por segundo é barato; um por quadro, a 30 fps, não é.
MTIME_CHECK_EVERY_S = 1.0

BOX_COLOR = (80, 200, 120)   # BGR
LABEL_TEXT = (14, 20, 16)


@dataclass(frozen=True)
class Detection:
    name: str
    conf: float
    box: tuple[int, int, int, int]  # x1, y1, x2, y2 em pixels

    def as_dict(self) -> dict:
        return {"name": self.name, "conf": round(self.conf, 3), "box": list(self.box)}


class Detector:
    """Carrega pesos sob demanda e recarrega quando o arquivo muda.

    Estados possíveis, todos visíveis em `status()`:

    | is_loaded | error | significado                                  |
    |-----------|-------|----------------------------------------------|
    | True      | None  | inferindo de verdade                         |
    | False     | None  | passthrough — não há arquivo de pesos ainda  |
    | False     | str   | passthrough — havia pesos, mas falhou        |
    """

    def __init__(self, weights: str | Path | None = None, conf: float = CONF_THRESHOLD) -> None:
        raw = weights or os.environ.get("MODEL_WEIGHTS") or DEFAULT_WEIGHTS
        self.weights_path = Path(raw)
        self._conf = conf
        self._lock = threading.Lock()
        self._model = None
        self._names: dict[int, str] = {}
        self._error: str | None = None
        self._loaded_at: float | None = None
        # -1.0 é impossível como mtime real, então a primeira checagem carrega.
        self._mtime: float | None = -1.0
        self._checked_at = 0.0

    # -- estado ------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def classes(self) -> list[str]:
        return [self._names[k] for k in sorted(self._names)]

    def status(self) -> dict:
        return {
            "loaded": self.is_loaded,
            "weights_path": str(self.weights_path),
            "weights_name": self.weights_path.name,
            "weights_exists": self.weights_path.is_file(),
            "classes": self.classes,
            "conf": self._conf,
            "error": self._error,
            "loaded_at": self._loaded_at,
            "mode": "inferência" if self.is_loaded else "passthrough",
        }

    # -- carga -------------------------------------------------------------

    def _weights_mtime(self) -> float | None:
        try:
            return self.weights_path.stat().st_mtime
        except OSError:
            return None

    def _maybe_reload(self) -> None:
        """Recarrega se o arquivo apareceu, sumiu ou mudou. Nunca a cada quadro."""
        now = time.monotonic()
        if now - self._checked_at < MTIME_CHECK_EVERY_S:
            return
        self._checked_at = now
        mtime = self._weights_mtime()
        if mtime != self._mtime:
            self._load(mtime)

    def _load(self, mtime: float | None, force: bool = False) -> None:
        with self._lock:
            if not force and mtime == self._mtime:
                return  # outra thread carregou enquanto esta esperava o lock
            self._mtime = mtime
            self._loaded_at = None

            if mtime is None:
                # Ausência de pesos não é erro: é o ponto de partida do projeto.
                self._model, self._names, self._error = None, {}, None
                return

            try:
                from ultralytics import YOLO  # import preguiçoso: arrasta torch
            except Exception as exc:
                self._model, self._names = None, {}
                self._error = f"ultralytics indisponível ({type(exc).__name__}: {exc})"[:200]
                return

            try:
                model = YOLO(str(self.weights_path))
                names = getattr(model, "names", {}) or {}
                self._names = {int(k): str(v) for k, v in dict(names).items()}
                self._model = model
                self._error = None
                self._loaded_at = time.time()
            except Exception as exc:
                self._model, self._names = None, {}
                self._error = f"falha ao carregar pesos ({type(exc).__name__}: {exc})"[:200]

    def reload(self) -> dict:
        """Força nova tentativa agora, sem esperar o mtime mudar."""
        self._checked_at = time.monotonic()
        self._load(self._weights_mtime(), force=True)
        return self.status()

    def poll(self) -> dict:
        """Checa o arquivo e devolve o estado.

        Existe porque o hot-reload por mtime acontece dentro de `detect()`, e
        com o leitor ocioso ninguém chama `detect()` — a tela ficaria mostrando
        um estado velho enquanto o operador copia o `best.pt` para a pasta.
        Pode carregar o modelo, que é lento: chame fora do event loop.
        """
        self._maybe_reload()
        return self.status()

    # -- inferência --------------------------------------------------------

    def detect(self, frame):
        """Devolve (quadro, detecções). Em passthrough, o quadro sai intacto."""
        self._maybe_reload()
        model = self._model
        if model is None:
            return frame, []

        try:
            results = model.predict(frame, conf=self._conf, verbose=False)
        except Exception as exc:
            # Uma falha em runtime derruba para passthrough e fica registrada;
            # o vídeo continua, e o operador vê o estado mudar na tela.
            with self._lock:
                self._model = None
                self._error = f"inferência falhou ({type(exc).__name__}: {exc})"[:200]
            return frame, []

        return frame, self._parse(results)

    def _parse(self, results) -> list[Detection]:
        out: list[Detection] = []
        for result in results or []:
            for box in getattr(result, "boxes", None) or []:
                try:
                    x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                except (IndexError, TypeError, ValueError):
                    continue
                out.append(
                    Detection(self._names.get(cls_id, str(cls_id)), conf, (x1, y1, x2, y2))
                )
        return out

    @staticmethod
    def draw(frame, detections: list[Detection]):
        """Desenha as caixas no quadro recebido (modifica no lugar)."""
        for det in detections:
            x1, y1, x2, y2 = det.box
            cv2.rectangle(frame, (x1, y1), (x2, y2), BOX_COLOR, 2)
            label = f"{det.name} {det.conf:.2f}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            top = max(y1 - th - 6, 0)
            cv2.rectangle(frame, (x1, top), (x1 + tw + 8, top + th + 6), BOX_COLOR, -1)
            cv2.putText(
                frame, label, (x1 + 4, top + th + 1),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, LABEL_TEXT, 1, cv2.LINE_AA,
            )
        return frame


detector = Detector()
