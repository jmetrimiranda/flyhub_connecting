"""Split temporal por blocos contíguos, com margem de descarte.

Por que não aleatório
---------------------
Quadros consecutivos de vídeo são quase idênticos. Um split aleatório coloca o
quadro N em treino e o N+1 em validação: o modelo memoriza em vez de
generalizar, e a métrica de validação sobe para valores que não se sustentam em
voo novo. É vazamento de dados, e é silencioso — nada no treino indica que
aconteceu.

Aqui a partição é por blocos contíguos de tempo:

    [────────── train ──────────][── valid ──][── test ──]
    t=0                                               t=fim
                                ↑            ↑
                                margem de N quadros descartados de cada lado,
                                para que o último de treino e o primeiro de
                                validação não sejam vizinhos temporais.

O módulo é uma função pura sobre um diretório: recebe o caminho de uma versão,
lê `raw/`, escreve `train|valid|test/images/` e `split_manifest.json`. Não
conhece vídeo, coleta nem estado da aplicação — é o que permite reprocessar um
dataset antigo (o `resplit` da fatia 4) e testar sem drone.

Roda em uma única thread, sem paralelismo: acontece depois do Salvar, quando o
operador já não depende do vídeo em tempo real, e não vale disputar CPU com o
encode do MJPEG por alguns segundos de cópia.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from .datasets import RAW_DIR, SPLITS

# `000123_t45.50.jpg` — o índice zero-preenchido faz a ordem lexicográfica ser
# a ordem temporal, e o `t` é o que permite auditar as fronteiras sem reabrir
# nenhum banco.
FRAME_RE = re.compile(r"^(\d+)_t(-?\d+\.\d+)\.jpg$")

DEFAULT_RATIOS = {"train": 0.70, "valid": 0.15, "test": 0.15}
DEFAULT_MARGIN = 5

# Abaixo disto não há o que particionar: 3 quadros com margem 0 dariam um
# "valid" de 1 quadro que não mede nada. Vai tudo para train, com aviso.
MIN_FRAMES_FOR_SPLIT = 10

# Desvio em pontos percentuais a partir do qual a proporção real vira aviso.
PROPORTION_TOLERANCE_PP = 5.0

MANIFEST_NAME = "split_manifest.json"
STRATEGY = "temporal_contiguous"
STRATEGY_REASON = (
    "blocos contíguos de tempo com margem de descarte nas fronteiras; "
    "split aleatório vazaria quadros vizinhos entre treino e validação"
)


class SplitError(RuntimeError):
    pass


# --- leitura ----------------------------------------------------------------


def parse_frame_name(name: str) -> tuple[int, float] | None:
    m = FRAME_RE.match(name)
    return (int(m.group(1)), float(m.group(2))) if m else None


def list_raw(base: Path) -> tuple[list[dict], list[str]]:
    """Quadros de `raw/` em ordem temporal, mais os nomes que não casaram."""
    raw = base / RAW_DIR
    if not raw.is_dir():
        raise SplitError(f"{raw} não existe — nada para particionar")

    frames, ignored = [], []
    for entry in sorted(os.listdir(raw)):
        parsed = parse_frame_name(entry)
        if parsed is None:
            if not entry.startswith("."):
                ignored.append(entry)
            continue
        index, t = parsed
        frames.append({"file": entry, "index": index, "t": t})

    frames.sort(key=lambda f: (f["index"], f["t"]))
    return frames, ignored


# --- planejamento (puro) ----------------------------------------------------


def _cuts(n: int, ratios: dict) -> tuple[int, int]:
    # int(x + 0.5) em vez de round(): round() arredonda .5 para o par mais
    # próximo, e round(2.5) == 2 deslocaria o corte de um quadro sem motivo.
    c1 = int(n * ratios["train"] + 0.5)
    c2 = c1 + int(n * ratios["valid"] + 0.5)
    c1 = max(1, min(c1, n - 2))
    c2 = max(c1 + 1, min(c2, n - 1))
    return c1, c2


def _fits(n: int, c1: int, c2: int, margin: int) -> bool:
    """Toda partição precisa de pelo menos um quadro depois da margem."""
    return (c1 - margin) >= 1 and (c2 - margin) - (c1 + margin) >= 1 and (n - (c2 + margin)) >= 1


def plan(frames: list[dict], ratios: dict | None = None, margin: int = DEFAULT_MARGIN) -> dict:
    """Decide a partição. Sem I/O — é aqui que mora a regra, e é o que se testa.

    Devolve as três listas, os descartados com o motivo, a margem realmente
    aplicada e os avisos. Nunca levanta por dataset pequeno: encolhe a margem,
    e no limite manda tudo para train — sempre dizendo o que fez.
    """
    ratios = dict(ratios or DEFAULT_RATIOS)
    total = sum(ratios.values())
    if total <= 0:
        raise SplitError("proporções inválidas")
    if abs(total - 1.0) > 1e-6:
        ratios = {k: v / total for k, v in ratios.items()}

    n = len(frames)
    warnings: list[dict] = []
    parts: dict[str, list[dict]] = {s: [] for s in SPLITS}
    discarded: list[dict] = []

    if n == 0:
        raise SplitError("nenhum quadro em raw/ — nada para particionar")

    if n < MIN_FRAMES_FOR_SPLIT:
        parts["train"] = list(frames)
        warnings.append({
            "code": "dataset_curto",
            "level": "error",
            "message": (
                f"Apenas {n} quadro(s) coletado(s) — menos que o mínimo de "
                f"{MIN_FRAMES_FOR_SPLIT} para particionar. Tudo foi para train: "
                f"este dataset não tem valid nem test e não serve para medir o modelo."
            ),
        })
        return _result(parts, discarded, n, margin, 0, [], warnings, ratios)

    c1, c2 = _cuts(n, ratios)

    margin_applied = margin
    while margin_applied > 0 and not _fits(n, c1, c2, margin_applied):
        margin_applied -= 1
    if not _fits(n, c1, c2, margin_applied):
        parts["train"] = list(frames)
        warnings.append({
            "code": "sem_particao_possivel",
            "level": "error",
            "message": (
                f"{n} quadros não permitem três partições não vazias. Tudo foi "
                "para train: sem valid e sem test, não há como medir o modelo."
            ),
        })
        return _result(parts, discarded, n, margin, 0, [], warnings, ratios)

    if margin_applied != margin:
        warnings.append({
            "code": "margem_reduzida",
            "level": "warn",
            "message": (
                f"A margem de descarte caiu de {margin} para {margin_applied} quadro(s): "
                f"com {n} quadros, a margem pedida esvaziaria uma das partições. "
                + ("Com margem 0, o último quadro de treino e o primeiro de validação "
                   "são vizinhos temporais — colete mais tempo antes de treinar."
                   if margin_applied == 0 else
                   "A separação entre as partições ficou menor que a pedida.")
            ),
        })

    bounds = {
        "train": (0, c1 - margin_applied),
        "valid": (c1 + margin_applied, c2 - margin_applied),
        "test": (c2 + margin_applied, n),
    }
    for name, (lo, hi) in bounds.items():
        parts[name] = frames[lo:hi]

    for cut, (before, after) in ((c1, ("train", "valid")), (c2, ("valid", "test"))):
        for frame in frames[max(cut - margin_applied, 0):cut + margin_applied]:
            discarded.append({
                **frame,
                "reason": f"margem de fronteira {before}|{after}",
            })

    boundaries = []
    for cut, pair in ((c1, ("train", "valid")), (c2, ("valid", "test"))):
        before = frames[cut - margin_applied - 1] if cut - margin_applied - 1 >= 0 else None
        after = frames[cut + margin_applied] if cut + margin_applied < n else None
        boundaries.append({
            "between": list(pair),
            "cut_index": cut,
            "discarded_frames": min(margin_applied, cut) + min(margin_applied, n - cut),
            "last_before": before["file"] if before else None,
            "first_after": after["file"] if after else None,
            "t_before": before["t"] if before else None,
            "t_after": after["t"] if after else None,
            "gap_s": round(after["t"] - before["t"], 2) if before and after else None,
        })

    return _result(parts, discarded, n, margin, margin_applied, boundaries, warnings, ratios)


def _result(parts, discarded, n, margin_requested, margin_applied, boundaries, warnings, ratios) -> dict:
    kept = sum(len(v) for v in parts.values())
    for name in SPLITS:
        if not parts[name] and not any(w["level"] == "error" for w in warnings):
            warnings.append({
                "code": f"particao_vazia_{name}",
                "level": "error",
                "message": f"A partição {name} ficou vazia.",
            })
    if kept and not any(w["level"] == "error" for w in warnings):
        for name in SPLITS:
            actual = len(parts[name]) / kept * 100
            wanted = ratios[name] * 100
            if abs(actual - wanted) > PROPORTION_TOLERANCE_PP:
                warnings.append({
                    "code": f"proporcao_desviada_{name}",
                    "level": "warn",
                    "message": (
                        f"{name} ficou com {actual:.0f}% dos quadros mantidos, não os "
                        f"{wanted:.0f}% pedidos — a margem de descarte pesa mais quanto "
                        "menor o dataset."
                    ),
                })
    return {
        "parts": parts,
        "discarded": discarded,
        "total": n,
        "kept": kept,
        "margin_requested": margin_requested,
        "margin_applied": margin_applied,
        "boundaries": boundaries,
        "warnings": warnings,
        "ratios": ratios,
    }


# --- execução ---------------------------------------------------------------


def _reset_split_dirs(base: Path) -> None:
    """Zera train|valid|test. Sem isso, um resplit deixaria órfãos do anterior."""
    for name in SPLITS:
        target = base / name
        if target.exists():
            shutil.rmtree(target)
        (target / "images").mkdir(parents=True, exist_ok=True)


def write_manifest(base: Path, manifest: dict) -> Path:
    path = base / MANIFEST_NAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run(
    base: Path,
    ratios: dict | None = None,
    margin: int = DEFAULT_MARGIN,
    session: dict | None = None,
) -> dict:
    """Particiona `base/raw/` e grava o manifesto. Devolve o manifesto.

    Copia, não move: `raw/` é mantido para reprocessar — é o que torna possível
    refazer o split depois de excluir imagens, na fatia 4.
    """
    base = Path(base)
    frames, ignored = list_raw(base)
    decision = plan(frames, ratios, margin)

    _reset_split_dirs(base)

    copied = {s: [] for s in SPLITS}
    errors: list[dict] = []
    for name in SPLITS:
        target = base / name / "images"
        for frame in decision["parts"][name]:
            try:
                shutil.copy2(base / RAW_DIR / frame["file"], target / frame["file"])
            except OSError as exc:
                errors.append({"file": frame["file"], "split": name, "error": str(exc)})
                continue
            copied[name].append(frame)

    warnings = list(decision["warnings"])
    if ignored:
        warnings.append({
            "code": "arquivos_ignorados",
            "level": "warn",
            "message": (
                f"{len(ignored)} arquivo(s) em raw/ fora do padrão "
                "`NNNNNN_tSS.SS.jpg` foram ignorados: " + ", ".join(ignored[:5])
                + ("…" if len(ignored) > 5 else "")
            ),
        })
    if errors:
        warnings.append({
            "code": "falha_ao_copiar",
            "level": "error",
            "message": f"{len(errors)} quadro(s) não puderam ser copiados para as partições.",
        })

    times = [f["t"] for f in frames]
    manifest = {
        "version": base.name,
        "created_at": time.time(),
        "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "strategy": STRATEGY,
        "reason": STRATEGY_REASON,
        "source": RAW_DIR,
        "ratios": decision["ratios"],
        "margin_requested": decision["margin_requested"],
        "margin_applied": decision["margin_applied"],
        "total_raw": decision["total"],
        "counts": {
            **{name: len(copied[name]) for name in SPLITS},
            "discarded": len(decision["discarded"]),
            "kept": sum(len(copied[name]) for name in SPLITS),
        },
        "time_span": {
            "first_t": times[0] if times else None,
            "last_t": times[-1] if times else None,
            "duration_s": round(times[-1] - times[0], 2) if len(times) > 1 else 0.0,
        },
        "boundaries": decision["boundaries"],
        "warnings": warnings,
        "copy_errors": errors,
        "session": session,
        "files": {
            **{name: copied[name] for name in SPLITS},
            "discarded": decision["discarded"],
        },
    }
    write_manifest(base, manifest)
    return manifest


def read_manifest(base: Path) -> dict | None:
    try:
        return json.loads((Path(base) / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
