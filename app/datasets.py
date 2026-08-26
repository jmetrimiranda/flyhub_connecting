"""Descoberta, versionamento, leitura e edição dos datasets em disco.

O versionamento é `vMAJOR.MINOR` com MINOR de 0 a 9 rolando para o próximo
MAJOR. A fonte da verdade é o disco, não um contador em memória ou no banco:
`data/datasets/` é varrido a cada consulta. Uma pasta criada à mão entra na
sequência; um processo reiniciado não repete uma versão.

Três arquivos descrevem uma versão, e cada um responde uma pergunta diferente:

| Arquivo | Pergunta | Quem escreve |
|---|---|---|
| `session.json` | como a gravação aconteceu | `app/collect.py` |
| `split_manifest.json` | o que o split **decidiu** | `app/split.py` |
| `edits.json` | o que mudou **depois** do split | este módulo |
| `roboflow.json` | o que foi enviado ao Roboflow | `app/roboflow_upload.py` |

O manifesto é **imutável entre splits**: nenhuma exclusão o reescreve. Ele
registra um evento, não o conteúdo atual das pastas — reescrevê-lo a cada
exclusão faria o dataset deixar de ser reproduzível, que é a única razão de ele
existir. As contagens exibidas na interface vêm sempre do disco, contadas na
hora, e a divergência entre as duas coisas é calculada e mostrada (`drift`), não
escondida.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = Path(os.environ.get("DATASETS_DIR") or ROOT / "data" / "datasets")

VERSION_RE = re.compile(r"^v(\d+)\.(\d)$")
MAX_MINOR = 9

SPLITS = ("train", "valid", "test")
RAW_DIR = "raw"

SESSION_NAME = "session.json"
MANIFEST_NAME = "split_manifest.json"
EDITS_NAME = "edits.json"
ROBOFLOW_NAME = "roboflow.json"

# Ponto no início para não aparecer em listagens nem confundir o split, que
# ignora nomes começados por ponto.
THUMBS_DIR = ".thumbs"
THUMB_WIDTH = 240
THUMB_QUALITY = 72

# Escrita de edits.json e roboflow.json: um lock por processo basta, os dois
# arquivos são pequenos e só mudam em ações do operador.
_write_lock = threading.Lock()

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


def dir_size(path: Path, skip: tuple[str, ...] = (THUMBS_DIR,)) -> int:
    """Bytes ocupados por uma árvore. Tolera arquivo removido durante a soma."""
    total = 0
    for root, dirs, files in os.walk(path, onerror=lambda _e: None):
        dirs[:] = [d for d in dirs if d not in skip]
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


# --- json --------------------------------------------------------------------


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, data: dict) -> None:
    """tmp + os.replace: uma queda no meio nunca deixa um JSON truncado."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# --- leitura de uma versão ---------------------------------------------------


class DatasetError(RuntimeError):
    pass


def require_version(version: str) -> Path:
    """Valida o nome e devolve o diretório. Nunca confie no que veio da URL.

    `parse_version` só aceita `^v\\d+\\.\\d$`, o que descarta `..`, barras e
    qualquer outra tentativa de sair de `data/datasets/`.
    """
    if parse_version(version) is None:
        raise DatasetError(f"versão inválida: {version!r}")
    base = version_dir(version)
    if not base.is_dir():
        raise DatasetError(f"dataset {version} não existe")
    return base


def require_split(split: str) -> str:
    if split not in SPLITS:
        raise DatasetError(f"partição inválida: {split!r}")
    return split


def split_dir(base: Path, split: str) -> Path:
    return base / split / "images"


def split_files(base: Path, split: str) -> list[str]:
    try:
        return sorted(
            e.name for e in os.scandir(split_dir(base, split))
            if e.is_file() and e.name.lower().endswith(".jpg")
        )
    except OSError:
        return []


def raw_files(base: Path) -> list[str]:
    try:
        return sorted(
            e.name for e in os.scandir(base / RAW_DIR)
            if e.is_file() and e.name.lower().endswith(".jpg")
        )
    except OSError:
        return []


def live_counts(base: Path) -> dict:
    """Contagem do que existe agora. Nunca lida do manifesto."""
    counts = {s: len(split_files(base, s)) for s in SPLITS}
    counts["raw"] = len(raw_files(base))
    counts["total"] = sum(counts[s] for s in SPLITS)
    return counts


def drift(manifest: dict | None, counts: dict) -> dict:
    """Divergência entre o que o split decidiu e o que existe em disco.

    Não é gravada em lugar nenhum: é calculada em toda leitura. O manifesto
    continua dizendo o que o split fez, e esta função diz o quanto isso deixou
    de valer.
    """
    if not manifest:
        return {
            "stale": counts["total"] > 0,
            "reason": "sem manifesto — o split ainda não rodou nesta versão",
            "by_split": {s: None for s in SPLITS},
            "total": None,
            "proportions": _proportions(counts),
            "manifest_proportions": None,
        }

    expected = manifest.get("counts") or {}
    by_split = {s: counts[s] - int(expected.get(s) or 0) for s in SPLITS}
    total = sum(by_split.values())
    kept = int(expected.get("kept") or 0)
    return {
        "stale": any(by_split.values()),
        "reason": (
            f"{-total} imagem(ns) excluída(s) depois do split"
            if total < 0 else
            (f"{total} imagem(ns) a mais que o manifesto" if total > 0 else None)
        ),
        "by_split": by_split,
        "total": total,
        "proportions": _proportions(counts),
        "manifest_proportions": {
            s: round(int(expected.get(s) or 0) / kept * 100, 1) if kept else None
            for s in SPLITS
        },
        "manifest_counts": {s: int(expected.get(s) or 0) for s in SPLITS},
    }


def _proportions(counts: dict) -> dict:
    total = counts["total"]
    return {s: round(counts[s] / total * 100, 1) if total else None for s in SPLITS}


# --- edits.json --------------------------------------------------------------


def read_edits(base: Path) -> dict:
    return read_json(base / EDITS_NAME) or {"events": []}


def append_edit(base: Path, event: dict) -> dict:
    """Registra um evento. Append-only: nada aqui é sobrescrito ou removido.

    É o que liga o manifesto antigo ao estado atual do disco — sem isto, a
    diferença entre 164 e 150 não tem explicação daqui a três meses.
    """
    entry = {"at": time.time(), "at_iso": _iso(time.time()), **event}
    with _write_lock:
        log = read_edits(base)
        log.setdefault("events", []).append(entry)
        write_json(base / EDITS_NAME, log)
    return entry


def _iso(epoch: float | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch)) if epoch else None


# --- roboflow.json (leitura; quem escreve é app/roboflow_upload.py) ----------


def read_upload_record(base: Path) -> dict | None:
    return read_json(base / ROBOFLOW_NAME)


def uploaded_map(record: dict | None) -> dict:
    """`{nome do arquivo: {"split": ..., "at": ...}}` do que já subiu.

    A chave é o nome do arquivo, não `split/arquivo`: um resplit pode mudar a
    partição de uma imagem, e re-enviá-la criaria duplicata no Roboflow.
    """
    if not record:
        return {}
    return dict(record.get("uploaded") or {})


def roboflow_divergence(base: Path, record: dict | None) -> dict:
    """O que o Roboflow tem e o disco não confirma mais.

    Nunca consulta a API do Roboflow. Lá é a fonte de verdade do que está lá;
    aqui só se torna visível que os dois lados deixaram de bater.
    """
    uploaded = uploaded_map(record)
    empty = {"any": False, "deleted_after_upload": 0, "discarded_after_upload": 0,
             "resplit_after_upload": 0, "deleted_files": [], "discarded_files": [],
             "moved_files": []}
    if not uploaded:
        return empty

    current = {}
    for split in SPLITS:
        for name in split_files(base, split):
            current[name] = split
    raw = set(raw_files(base))

    deleted, discarded, moved = [], [], []
    for name, info in uploaded.items():
        now = current.get(name)
        if now is None:
            # Fora das partições por dois motivos bem diferentes: o arquivo foi
            # excluído (some de raw/ também) ou um resplit o jogou na margem de
            # descarte (continua em raw/). Contar os dois juntos alarmaria o
            # operador por um resplit rotineiro.
            (discarded if name in raw else deleted).append(name)
        elif now != info.get("split"):
            moved.append({"file": name, "enviado_como": info.get("split"), "agora": now})

    return {
        "any": bool(deleted or discarded or moved),
        "deleted_after_upload": len(deleted),
        "discarded_after_upload": len(discarded),
        "resplit_after_upload": len(moved),
        "deleted_files": sorted(deleted)[:200],
        "discarded_files": sorted(discarded)[:200],
        "moved_files": moved[:200],
    }


def upload_summary(record: dict | None) -> dict:
    if not record:
        return {"state": "nunca enviado", "uploaded": 0, "total": 0, "project": None,
                "at": None, "at_iso": None, "resumable": False}
    totals = record.get("totals") or {}
    state = record.get("state") or "desconhecido"
    return {
        "state": state,
        "uploaded": int(totals.get("uploaded") or 0),
        "failed": int(totals.get("failed") or 0),
        "total": int(totals.get("selected") or 0),
        "project": record.get("project"),
        "workspace": record.get("workspace"),
        "batch_name": record.get("batch_name"),
        "tags": record.get("tags") or [],
        "at": record.get("finished_at") or record.get("started_at"),
        "at_iso": _iso(record.get("finished_at") or record.get("started_at")),
        "resumable": state in ("parcial", "cancelado", "erro"),
        "error": record.get("error"),
    }


# --- resumo e detalhe --------------------------------------------------------


def summary(version: str) -> dict:
    base = version_dir(version)
    session = read_json(base / SESSION_NAME)
    manifest = read_json(base / MANIFEST_NAME)
    record = read_upload_record(base)
    counts = live_counts(base)
    size = dir_size(base)

    created = (session or {}).get("started_at")
    if not created:
        try:
            created = base.stat().st_mtime
        except OSError:
            created = None

    return {
        "version": version,
        "created_at": created,
        "created_at_iso": _iso(created),
        "duration_s": (session or {}).get("duration_s"),
        "session_status": (session or {}).get("status") or "sem sessão",
        "interval_s": ((session or {}).get("params") or {}).get("interval_s"),
        "counts": counts,
        "bytes": size,
        "bytes_human": human_bytes(size),
        "has_manifest": manifest is not None,
        "strategy": (manifest or {}).get("strategy"),
        "margin_applied": (manifest or {}).get("margin_applied"),
        "drift": drift(manifest, counts),
        "roboflow": upload_summary(record),
        "divergence": roboflow_divergence(base, record),
    }


def list_datasets() -> list[dict]:
    """Da versão mais recente para a mais antiga."""
    return [summary(format_version(*v)) for v in reversed(existing_versions())]


def detail(version: str) -> dict:
    base = require_version(version)
    manifest = read_json(base / MANIFEST_NAME)
    record = read_upload_record(base)
    uploaded = uploaded_map(record)

    images = {}
    for split in SPLITS:
        images[split] = [
            {"file": name, "uploaded": name in uploaded}
            for name in split_files(base, split)
        ]

    return {
        **summary(version),
        "dir": str(base),
        "session": read_json(base / SESSION_NAME),
        "manifest": _manifest_summary(manifest),
        "edits": list(reversed(read_edits(base).get("events") or []))[:100],
        "images": images,
        "uploaded_files": sorted(uploaded),
    }


def _manifest_summary(manifest: dict | None) -> dict | None:
    """O manifesto sem o mapeamento arquivo a arquivo, que domina o payload."""
    if not manifest:
        return None
    return {k: v for k, v in manifest.items() if k not in ("files", "session")}


# --- imagens -----------------------------------------------------------------


def image_path(version: str, split: str, filename: str) -> Path:
    """Caminho de uma imagem, validado contra travessia de diretório."""
    base = require_version(version)
    require_split(split)
    if filename != Path(filename).name or filename.startswith("."):
        raise DatasetError(f"nome de arquivo inválido: {filename!r}")
    path = split_dir(base, split) / filename
    # Defesa final: o arquivo resolvido tem que estar mesmo dentro da partição.
    if not path.is_file() or path.resolve().parent != split_dir(base, split).resolve():
        raise DatasetError(f"{filename} não existe em {version}/{split}")
    return path


def thumb_path(version: str, split: str, filename: str) -> Path:
    """Miniatura, gerada sob demanda e cacheada em disco.

    Mandar o JPEG inteiro duzentas vezes para montar uma grade de miniaturas
    desperdiça banda e memória do navegador; gerar a miniatura a cada requisição
    desperdiça CPU. O cache resolve os dois, e é invalidado por mtime.
    """
    source = image_path(version, split, filename)
    cache = version_dir(version) / THUMBS_DIR / split / filename
    try:
        if cache.is_file() and cache.stat().st_mtime >= source.stat().st_mtime:
            return cache
    except OSError:
        pass

    image = cv2.imread(str(source))
    if image is None:
        raise DatasetError(f"não foi possível ler {filename}")
    height, width = image.shape[:2]
    if width > THUMB_WIDTH:
        scale = THUMB_WIDTH / width
        image = cv2.resize(image, (THUMB_WIDTH, max(int(height * scale), 1)),
                           interpolation=cv2.INTER_AREA)
    # imencode + write, não imwrite: o imwrite escolhe o codec pela extensão do
    # caminho, e o arquivo temporário termina em `.tmp`.
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), THUMB_QUALITY])
    if not ok:
        raise DatasetError(f"não foi possível gerar a miniatura de {filename}")
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(cache.name + ".tmp")
    tmp.write_bytes(buffer.tobytes())
    os.replace(tmp, cache)
    return cache


# --- exclusão ----------------------------------------------------------------


def preview_delete(version: str, split: str, filenames: list[str]) -> dict:
    """O que aconteceria. Alimenta o modal antes de qualquer coisa ser apagada."""
    base = require_version(version)
    require_split(split)
    present = set(split_files(base, split))
    # Só se apaga o que a listagem do diretório confirma: nomes vindos da URL ou
    # do corpo nunca viram caminho diretamente.
    targets = sorted(set(filenames) & present)
    uploaded = uploaded_map(read_upload_record(base))
    already = [name for name in targets if name in uploaded]
    counts = live_counts(base)
    after = dict(counts)
    after[split] -= len(targets)
    after["raw"] -= len(targets)
    after["total"] -= len(targets)
    return {
        "version": version,
        "split": split,
        "requested": len(filenames),
        "targets": targets,
        "count": len(targets),
        "missing": sorted(set(filenames) - present),
        "uploaded_count": len(already),
        "uploaded_files": already,
        "counts_before": counts,
        "counts_after": after,
        "proportions_after": _proportions(after),
    }


def delete_images(version: str, split: str, filenames: list[str]) -> dict:
    """Apaga da partição **e** de `raw/`.

    Apagar só da partição faria o "refazer o split a partir de raw/" —
    justamente o que se oferece porque as proporções mudaram — ressuscitar todas
    as imagens excluídas. Entre a irreversibilidade e um botão que desfaz o
    trabalho do operador, a irreversibilidade é o mal menor; por isso o modal
    diz, em palavras, que não dá para desfazer.
    """
    base = require_version(version)
    _refuse_if_uploading(version, "excluir imagens")
    plan = preview_delete(version, split, filenames)
    if not plan["targets"]:
        raise DatasetError("nenhuma das imagens indicadas existe nesta partição")

    removed, removed_raw, errors = [], [], []
    for name in plan["targets"]:
        try:
            (split_dir(base, split) / name).unlink()
            removed.append(name)
        except OSError as exc:
            errors.append({"file": name, "error": str(exc)})
            continue
        raw = base / RAW_DIR / name
        try:
            if raw.is_file():
                raw.unlink()
                removed_raw.append(name)
        except OSError as exc:
            errors.append({"file": name, "error": f"raw/: {exc}"})
        # a miniatura é derivada; sem isto sobraria cache de imagem inexistente
        thumb = base / THUMBS_DIR / split / name
        try:
            thumb.unlink()
        except OSError:
            pass

    event = append_edit(base, {
        "action": "delete_images",
        "split": split,
        "count": len(removed),
        "files": removed,
        "removed_from_raw": len(removed_raw),
        # Quais já estavam no Roboflow quando foram excluídas daqui. É o que
        # explica, depois, por que os dois lados divergem.
        "uploaded_before": plan["uploaded_files"],
        "errors": errors,
    })

    counts = live_counts(base)
    manifest = read_json(base / MANIFEST_NAME)
    return {
        "ok": True,
        "removed": len(removed),
        "removed_from_raw": len(removed_raw),
        "uploaded_before": len(plan["uploaded_files"]),
        "errors": errors,
        "counts": counts,
        "drift": drift(manifest, counts),
        "event": event,
    }


def _refuse_if_uploading(version: str, action: str) -> None:
    """Import local: `roboflow_upload` importa deste módulo, e no topo faria ciclo."""
    from .roboflow_upload import uploader

    status = uploader.status()
    if status["active"] and status["version"] == version:
        raise DatasetError(
            f"há um envio de {version} ao Roboflow em andamento — "
            f"cancele antes de {action}"
        )


def delete_dataset(version: str, confirm: str) -> dict:
    """Apaga a versão inteira. Exige digitar a versão, sem espaço para engano."""
    base = require_version(version)
    _refuse_if_uploading(version, "excluir o dataset")
    if (confirm or "").strip() != version:
        raise DatasetError(
            f"para excluir, digite exatamente {version} — recebido {confirm!r}"
        )
    counts = live_counts(base)
    size = dir_size(base)
    shutil.rmtree(base)
    return {"ok": True, "version": version, "removed_counts": counts,
            "removed_bytes": size, "removed_human": human_bytes(size)}


def resplit(version: str, margin: int | None = None, ratios: dict | None = None) -> dict:
    """Refaz o split a partir de `raw/`, no estado em que `raw/` está agora.

    É o mesmo `split.run()` da fatia 3, sem nenhuma variante: as partições são
    apagadas e reescritas, o manifesto é sobrescrito com a decisão nova, e a
    divergência volta a zero. Import local porque `split` importa deste módulo.
    """
    from . import split as split_mod

    base = require_version(version)
    # O resplit move arquivos entre partições; no meio de um envio, o uploader
    # passaria a procurar caminhos que deixaram de existir.
    _refuse_if_uploading(version, "refazer o split")
    before = live_counts(base)
    session = read_json(base / SESSION_NAME)
    if session:
        session = {k: v for k, v in session.items() if k != "frames"}

    manifest = split_mod.run(
        base,
        ratios=ratios,
        margin=split_mod.DEFAULT_MARGIN if margin is None else int(margin),
        session=session,
    )

    # As miniaturas apontam para caminhos por partição, e o resplit move os
    # arquivos de partição: o cache inteiro deixa de valer.
    shutil.rmtree(base / THUMBS_DIR, ignore_errors=True)

    counts = live_counts(base)
    append_edit(base, {
        "action": "resplit",
        "counts_before": before,
        "counts_after": counts,
        "margin_requested": manifest["margin_requested"],
        "margin_applied": manifest["margin_applied"],
        "warnings": manifest["warnings"],
    })
    return {
        "ok": True,
        "version": version,
        "counts": counts,
        "drift": drift(manifest, counts),
        "manifest": _manifest_summary(manifest),
    }
