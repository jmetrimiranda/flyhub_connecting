"""Três exemplos do conjunto de teste com as predições desenhadas.

Por que não gerar na requisição
-------------------------------
Inferir em três imagens custa entre 50 e 300 ms cada — mas a **primeira**
chamada importa o torch e carrega os pesos, o que leva de 5 a 20 s. Uma rota que
inferisse na hora deixaria a requisição pendurada nesse tempo, e um F5 repetiria
tudo.

Então os exemplos são um artefato derivado com cache em disco, do mesmo jeito
que as miniaturas da galeria (§8):

    GET  /api/model/samples           nunca computa — devolve o cache e o estado
    POST /api/model/samples/generate  dispara uma thread e responde na hora

A chave do cache é `(mtime e tamanho dos pesos, versão do dataset, os três
nomes de arquivo)`. Retreinou e copiou um `best.pt` novo? O mtime muda, o cache
vence sozinho e os exemplos são regerados — o mesmo mecanismo que o `Detector`
usa para recarregar pesos.

Quais três
----------
Primeira, do meio e última de `test/images/`, na ordem temporal. Determinístico,
não sorteado: três aleatórias mudariam a cada geração e impediriam comparar
visualmente um modelo com o anterior, e três vizinhas seriam quase idênticas —
pelo mesmo motivo que o split é temporal.

A thread leva `os.nice`, como os workers de escrita da coleta: se alguém abrir
esta tela no meio de um voo, quem cede CPU é a tela, não o vídeo.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import cv2

from . import datasets
from .inference import detector

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data" / "models" / "samples"
INDEX_PATH = SAMPLES_DIR / "samples.json"

SAMPLE_COUNT = 3
JPEG_QUALITY = 85
MAX_WIDTH = 960           # o suficiente para olhar; não é o arquivo de treino
WORKER_NICE = 10

READY, GENERATING, MISSING, UNAVAILABLE = "pronto", "gerando", "ausente", "indisponível"


def _iso(epoch: float | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch)) if epoch else None


# --- escolha das imagens -----------------------------------------------------


def latest_test_dataset() -> tuple[str, list[str]] | None:
    """Versão mais recente que tenha imagens em `test/images/`."""
    for version in reversed(datasets.existing_versions()):
        name = datasets.format_version(*version)
        files = datasets.split_files(datasets.version_dir(name), "test")
        if files:
            return name, files
    return None


def pick(files: list[str], count: int = SAMPLE_COUNT) -> list[str]:
    """Primeira, do meio e última — espalhadas no tempo, sempre as mesmas."""
    if len(files) <= count:
        return list(files)
    if count == 1:
        return [files[0]]
    step = (len(files) - 1) / (count - 1)
    return [files[round(i * step)] for i in range(count)]


def _weights_stamp() -> tuple | None:
    path = Path(detector.weights_path)
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_mtime, stat.st_size)


def cache_key() -> dict | None:
    """`None` quando não dá para gerar: sem pesos ou sem dataset de teste."""
    stamp = _weights_stamp()
    if stamp is None:
        return None
    found = latest_test_dataset()
    if found is None:
        return None
    version, files = found
    return {
        "weights": stamp[0],
        "weights_mtime": stamp[1],
        "weights_size": stamp[2],
        "version": version,
        "files": pick(files),
    }


# --- serviço -----------------------------------------------------------------


class SampleService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._generating = False
        self._progress: dict = {}
        self._error: str | None = None
        self._thread: threading.Thread | None = None

    # -- leitura --

    @staticmethod
    def _read_index() -> dict | None:
        return datasets.read_json(INDEX_PATH)

    def status(self) -> dict:
        """Nunca computa nada. Só olha o cache e o estado do detector."""
        model = detector.status()
        with self._lock:
            generating = self._generating
            progress = dict(self._progress)
            error = self._error

        key = cache_key()
        if key is None:
            if not model["weights_exists"]:
                reason = (
                    f"nenhum modelo carregado — coloque os pesos em "
                    f"{model['weights_path']} para gerar exemplos"
                )
            else:
                reason = (
                    "nenhum dataset com partição de teste — colete um voo e "
                    "salve, ou refaça o split de uma versão existente"
                )
            return {
                "state": UNAVAILABLE, "reason": reason, "error": error,
                "samples": [], "version": None, "generated_at": None,
                "generated_at_iso": None, "generating": generating,
                "progress": progress or None, "model": model,
            }

        index = self._read_index()
        fresh = bool(index) and index.get("key") == key
        samples = index.get("samples", []) if fresh else []
        # Um arquivo do cache apagado à mão invalida o conjunto inteiro.
        if fresh and not all((SAMPLES_DIR / s["file"]).is_file() for s in samples):
            fresh, samples = False, []

        if generating:
            state, reason = GENERATING, "gerando os exemplos…"
        elif fresh:
            state, reason = READY, None
        else:
            state, reason = MISSING, (
                "os exemplos ainda não foram gerados para estes pesos"
                if index else "os exemplos ainda não foram gerados"
            )

        return {
            "state": state,
            "reason": reason,
            "error": error,
            "version": key["version"],
            "files": key["files"],
            "samples": samples,
            "generated_at": index.get("generated_at") if fresh else None,
            "generated_at_iso": _iso(index.get("generated_at")) if fresh else None,
            "generating": generating,
            "progress": progress or None,
            "model": model,
        }

    # -- geração --

    def generate(self) -> dict:
        with self._lock:
            if self._generating:
                return {"ok": False, "samples": self.status(),
                        "error": "já há uma geração em andamento"}
            key = cache_key()
            if key is None:
                status = self.status()
                return {"ok": False, "samples": status, "error": status["reason"]}

            self._generating = True
            self._error = None
            self._progress = {"done": 0, "total": len(key["files"]),
                              "current": None, "message": "carregando o modelo…"}
            self._thread = threading.Thread(target=self._run, args=(key,),
                                            name="model-samples", daemon=True)
            self._thread.start()
        return {"ok": True, "samples": self.status()}

    def _run(self, key: dict) -> None:
        try:
            # Mesma prioridade rebaixada dos workers de escrita da coleta: esta
            # tela nunca pode degradar o vídeo ao vivo.
            os.nice(WORKER_NICE)
        except OSError:
            pass

        error = None
        entries: list[dict] = []
        try:
            # poll() carrega os pesos se preciso — é a parte lenta, e é por isso
            # que ela está aqui e não no handler da requisição.
            detector.poll()
            if not detector.is_loaded:
                raise RuntimeError(
                    detector.status().get("error")
                    or "os pesos existem mas não puderam ser carregados"
                )

            base = datasets.version_dir(key["version"])
            SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
            for position, name in enumerate(key["files"]):
                with self._lock:
                    self._progress.update(current=name, done=position,
                                          message=f"inferindo em {name}")
                entries.append(self._one(base, position, name, key["version"]))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]

        if error is None:
            datasets.write_json(INDEX_PATH, {
                "key": key,
                "generated_at": time.time(),
                "version": key["version"],
                "model": {
                    "weights_name": Path(key["weights"]).name,
                    "classes": detector.classes,
                    "conf": detector.status().get("conf"),
                },
                "samples": entries,
            })

        with self._lock:
            self._generating = False
            self._error = error
            self._progress = {}

    def _one(self, base: Path, position: int, name: str, version: str) -> dict:
        source = datasets.split_dir(base, "test") / name
        image = cv2.imread(str(source))
        if image is None:
            raise RuntimeError(f"não foi possível ler {version}/test/images/{name}")

        _, detections = detector.detect(image)
        # `draw` é o mesmo do vídeo ao vivo: as caixas saem idênticas às que o
        # operador viu no voo, e não há um segundo código de desenho para
        # divergir.
        detector.draw(image, detections)

        height, width = image.shape[:2]
        if width > MAX_WIDTH:
            scale = MAX_WIDTH / width
            image = cv2.resize(image, (MAX_WIDTH, max(int(height * scale), 1)),
                               interpolation=cv2.INTER_AREA)

        ok, buffer = cv2.imencode(".jpg", image,
                                  [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if not ok:
            raise RuntimeError(f"não foi possível codificar o exemplo de {name}")
        target = SAMPLES_DIR / f"{position}.jpg"
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(buffer.tobytes())
        os.replace(tmp, target)

        counts: dict[str, int] = {}
        for det in detections:
            counts[det.name] = counts.get(det.name, 0) + 1
        return {
            "index": position,
            "file": target.name,
            "source": name,
            "version": version,
            "url": f"/api/model/samples/image/{position}",
            "size": [width, height],
            "count": len(detections),
            "by_class": counts,
            "detections": [d.as_dict() for d in detections],
        }

    def image_path(self, index: int) -> Path:
        if index not in range(SAMPLE_COUNT):
            raise datasets.DatasetError(f"exemplo inválido: {index}")
        path = SAMPLES_DIR / f"{index}.jpg"
        if not path.is_file():
            raise datasets.DatasetError(f"exemplo {index} não foi gerado")
        return path


samples = SampleService()
