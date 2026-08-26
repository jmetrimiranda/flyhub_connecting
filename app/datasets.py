"""Descoberta, versionamento e uso de disco dos datasets.

O versionamento é `vMAJOR.MINOR` com MINOR de 0 a 9 rolando para o próximo
MAJOR. A fonte da verdade é o disco, não um contador em memória ou no banco:
`data/datasets/` é varrido a cada consulta. Uma pasta criada à mão entra na
sequência; um processo reiniciado não repete uma versão.

Este módulo não conhece coleta, vídeo nem split — só o layout em disco. A tela
de datasets da fatia 4 lê daqui.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = Path(os.environ.get("DATASETS_DIR") or ROOT / "data" / "datasets")

VERSION_RE = re.compile(r"^v(\d+)\.(\d)$")
MAX_MINOR = 9

SPLITS = ("train", "valid", "test")
RAW_DIR = "raw"

# Acima disto a coleta não começa e uma coleta em andamento é pausada.
DISK_LIMIT_PCT = float(os.environ.get("DISK_LIMIT_PCT", "90"))


# --- versões ----------------------------------------------------------------


def parse_version(name: str) -> tuple[int, int] | None:
    m = VERSION_RE.match(name)
    return (int(m.group(1)), int(m.group(2))) if m else None


def format_version(major: int, minor: int) -> str:
    return f"v{major}.{minor}"


def existing_versions() -> list[tuple[int, int]]:
    """Versões presentes em disco, ordenadas. Só diretórios com nome válido."""
    try:
        entries = list(DATASETS_DIR.iterdir())
    except OSError:
        return []
    out = []
    for entry in entries:
        if not entry.is_dir():
            continue
        parsed = parse_version(entry.name)
        if parsed:
            out.append(parsed)
    return sorted(out)


def _bump(major: int, minor: int) -> tuple[int, int]:
    return (major + 1, 0) if minor >= MAX_MINOR else (major, minor + 1)


def next_version() -> str:
    """A próxima versão livre. Primeira execução devolve `v0.0`.

    O laço final não é zelo excessivo: `existing_versions()` ignora nomes fora
    do padrão, e um diretório criado entre a varredura e a criação faria a
    coleta escrever dentro de um dataset alheio.
    """
    versions = existing_versions()
    if not versions:
        candidate = (0, 0)
    else:
        candidate = _bump(*versions[-1])
    while version_dir(format_version(*candidate)).exists():
        candidate = _bump(*candidate)
    return format_version(*candidate)


def version_dir(version: str) -> Path:
    return DATASETS_DIR / version


def create_version(version: str) -> Path:
    """Cria `<versão>/raw/`. Falha se a versão já existir."""
    base = version_dir(version)
    (base / RAW_DIR).mkdir(parents=True, exist_ok=False)
    return base


# --- disco ------------------------------------------------------------------


def _existing_ancestor(path: Path) -> Path:
    """`disk_usage` exige um caminho que exista; `data/datasets/` pode não existir."""
    current = path.resolve()
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def disk_usage() -> dict:
    try:
        usage = shutil.disk_usage(_existing_ancestor(DATASETS_DIR))
    except OSError as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "percent": None,
            "free_bytes": None,
            "total_bytes": None,
            "limit_pct": DISK_LIMIT_PCT,
            "over_limit": False,
        }
    percent = round(usage.used / usage.total * 100, 1) if usage.total else 0.0
    return {
        "ok": True,
        "error": None,
        "percent": percent,
        "free_bytes": usage.free,
        "free_human": human_bytes(usage.free),
        "total_bytes": usage.total,
        "limit_pct": DISK_LIMIT_PCT,
        "over_limit": percent >= DISK_LIMIT_PCT,
    }


def dir_size(path: Path) -> int:
    """Bytes ocupados por uma árvore. Tolera arquivo removido durante a soma."""
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def human_bytes(n: int | None) -> str:
    if n is None:
        return "—"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
