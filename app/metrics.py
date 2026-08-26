"""Leitura do `data/models/metrics.json`. Nada é calculado aqui.

As métricas são um artefato do treino, produzido por `train/train.py` a partir
do validador do Ultralytics. A aplicação só lê e exibe. Calcular mAP no painel
exigiria torch, o dataset de validação em disco e minutos de CPU — e daria um
número que não é o do treino, o que é pior que não dar número nenhum.

O `metrics.json` descreve **um treino**, não o arquivo de pesos que está
carregado agora. Os dois podem divergir: basta alguém copiar um `best.pt` à mão
por cima. Por isso o documento carrega o sha256 dos pesos que o produziram, e
esta leitura compara com o sha256 do arquivo carregado — a mesma disciplina do
`split_manifest.json` em relação às pastas do dataset (§8).
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from .inference import detector

ROOT = Path(__file__).resolve().parent.parent
METRICS_PATH = ROOT / "data" / "models" / "metrics.json"

# (caminho, mtime, tamanho) -> sha256. Hashear 6 MB a cada requisição de tela
# seria desperdício; o arquivo só muda quando o treino copia um novo.
_sha_cache: dict[tuple, str] = {}
_sha_lock = threading.Lock()


def file_sha256(path: Path) -> str | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime, stat.st_size)
    with _sha_lock:
        cached = _sha_cache.get(key)
    if cached:
        return cached
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    value = digest.hexdigest()
    with _sha_lock:
        _sha_cache.clear()  # só interessa o arquivo atual
        _sha_cache[key] = value
    return value


def read() -> dict:
    """Estado das métricas para a tela de Modelo.

    Nunca levanta. Os três estados vazios — sem arquivo, arquivo ilegível e
    arquivo de outro treino — são dados, não exceções.
    """
    status = detector.status()
    weights_path = Path(status["weights_path"])

    if not METRICS_PATH.is_file():
        return {
            "present": False,
            "path": str(METRICS_PATH),
            "error": None,
            "reason": "nenhum arquivo de métricas",
            "match": "sem_metricas",
            "document": None,
            "model": status,
        }

    try:
        document = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "present": False,
            "path": str(METRICS_PATH),
            "error": f"{type(exc).__name__}: {exc}"[:200],
            "reason": "arquivo de métricas ilegível",
            "match": "erro",
            "document": None,
            "model": status,
        }

    recorded = ((document.get("weights") or {}).get("sha256")) or None
    current = file_sha256(weights_path) if weights_path.is_file() else None

    if not weights_path.is_file():
        match, reason = "sem_pesos", (
            "as métricas são de um treino anterior; não há arquivo de pesos "
            "carregado para conferir"
        )
    elif not recorded:
        match, reason = "desconhecido", (
            "o arquivo de métricas não registra o sha256 dos pesos — não dá "
            "para confirmar que descreve o best.pt carregado"
        )
    elif recorded == current:
        match, reason = "confere", None
    else:
        match, reason = "divergente", (
            "estas métricas são de outro treino: o sha256 registrado não é o do "
            "best.pt carregado. Alguém copiou pesos por cima, ou o treino não "
            "terminou de atualizar o metrics.json."
        )

    return {
        "present": True,
        "path": str(METRICS_PATH),
        "error": None,
        "reason": reason,
        "match": match,
        "recorded_sha256": recorded,
        "current_sha256": current,
        "document": document,
        "model": status,
    }
