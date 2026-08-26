#!/usr/bin/env python3
"""
Treina um modelo YOLO a partir de um dataset baixado do Roboflow.

Uso:
    python train/train.py --data caminho/data.yaml --epochs 100

Ao final, copia `best.pt` para `data/models/best.pt` e grava
`data/models/metrics.json`, que é o arquivo que a tela de Modelo lê. A
aplicação detecta os pesos novos sozinha, pelo mtime, sem reiniciar.

Antes de treinar, confere a partição do dataset baixado contra o
`split_manifest.json` da coleta e avisa se elas divergirem — o Roboflow
reparticiona ao gerar uma versão, e um dataset rebalanceado por lá desfaz o
split temporal sem dizer nada. Ver train/README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "data" / "models"
DATASETS_DIR = ROOT / "data" / "datasets"
WEIGHTS_TARGET = MODELS_DIR / "best.pt"
METRICS_TARGET = MODELS_DIR / "metrics.json"

SPLIT_KEYS = (("train", "train"), ("val", "valid"), ("test", "test"))
# Desvio em pontos percentuais a partir do qual a partição baixada é suspeita.
PROPORTION_TOLERANCE_PP = 5.0

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


# --- utilidades sem dependência externa --------------------------------------


def sha256(path: Path) -> str | None:
    """Identidade do arquivo de pesos.

    O mtime muda a cada cópia; o hash não. É ele que permite à tela de Modelo
    dizer que o `metrics.json` é de um treino diferente do `best.pt` carregado.
    """
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def read_yaml(path: Path) -> dict:
    """Lê o `data.yaml`.

    Usa PyYAML quando disponível (vem com o ultralytics) e cai num parser
    mínimo quando não — o suficiente para `path`, `train`, `val`, `test`, `nc` e
    uma lista `names`. Assim a checagem de partição funciona antes mesmo de o
    ambiente de treino estar montado.
    """
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        pass

    data: dict = {}
    current_list: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if current_list and line.lstrip().startswith("- "):
            data[current_list].append(line.lstrip()[2:].strip().strip("'\""))
            continue
        current_list = None
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not value:
            data[key] = []
            current_list = key
        elif value.startswith("[") and value.endswith("]"):
            data[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
        else:
            data[key] = value.strip("'\"")
    return data


def count_images(directory: Path) -> int:
    try:
        return sum(1 for e in directory.iterdir()
                   if e.is_file() and e.suffix.lower() in IMAGE_SUFFIXES)
    except OSError:
        return 0


def resolve_split_dir(data_yaml: Path, config: dict, key: str) -> Path | None:
    """Resolve `train:`/`val:`/`test:` do data.yaml para uma pasta de imagens."""
    value = config.get(key)
    if not value or not isinstance(value, str):
        return None
    base = Path(str(config.get("path") or data_yaml.parent))
    if not base.is_absolute():
        base = (data_yaml.parent / base).resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve()
    # O Roboflow escreve `train/images`; alguns exports apontam para a pasta pai.
    if candidate.is_dir() and (candidate / "images").is_dir():
        candidate = candidate / "images"
    return candidate if candidate.is_dir() else None


def latest_manifest() -> tuple[str, dict] | None:
    """O `split_manifest.json` da versão mais recente em `data/datasets/`."""
    import re

    versions = []
    try:
        for entry in DATASETS_DIR.iterdir():
            m = re.match(r"^v(\d+)\.(\d)$", entry.name)
            if m and entry.is_dir() and (entry / "split_manifest.json").is_file():
                versions.append(((int(m.group(1)), int(m.group(2))), entry))
    except OSError:
        return None
    if not versions:
        return None
    _, newest = max(versions)
    try:
        return newest.name, json.loads((newest / "split_manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- checagem da partição ----------------------------------------------------


def check_split(data_yaml: Path, config: dict, manifest_path: Path | None) -> dict:
    """Compara a partição do dataset baixado com a do split temporal local.

    O Roboflow reparticiona ao gerar uma versão. Se a versão foi gerada com
    rebalanceamento, o `data.yaml` vem com a partição *dele* — aleatória — e o
    vazamento que o split temporal evitou volta pela porta dos fundos, sem nada
    no treino indicar que aconteceu.
    """
    downloaded = {}
    for yaml_key, split in SPLIT_KEYS:
        directory = resolve_split_dir(data_yaml, config, yaml_key)
        downloaded[split] = count_images(directory) if directory else 0

    total = sum(downloaded.values())
    result = {
        "downloaded": downloaded,
        "downloaded_total": total,
        "downloaded_proportions": {
            s: round(n / total * 100, 1) if total else None for s, n in downloaded.items()
        },
        "manifest": None,
        "manifest_version": None,
        "warnings": [],
        "ok": True,
    }

    if not downloaded["test"]:
        result["warnings"].append(
            "o data.yaml não aponta para nenhuma imagem de test — não haverá "
            "conjunto de teste, e a tela de Modelo não terá exemplos para mostrar"
        )

    if manifest_path is not None:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            version = manifest.get("version") or manifest_path.parent.name
        except (OSError, ValueError) as exc:
            result["warnings"].append(f"não foi possível ler {manifest_path}: {exc}")
            return _finish_check(result)
    else:
        found = latest_manifest()
        if found is None:
            result["warnings"].append(
                "nenhum split_manifest.json em data/datasets/ para comparar — "
                "a partição do dataset baixado não pôde ser conferida"
            )
            return _finish_check(result)
        version, manifest = found

    counts = manifest.get("counts") or {}
    local = {s: int(counts.get(s) or 0) for _, s in SPLIT_KEYS}
    local_total = sum(local.values())
    result["manifest_version"] = version
    result["manifest"] = {
        "counts": local,
        "total": local_total,
        "proportions": {
            s: round(n / local_total * 100, 1) if local_total else None for s, n in local.items()
        },
        "strategy": manifest.get("strategy"),
        "margin_applied": manifest.get("margin_applied"),
    }

    for split in local:
        want = result["manifest"]["proportions"][split]
        got = result["downloaded_proportions"][split]
        if want is None or got is None:
            continue
        if abs(got - want) > PROPORTION_TOLERANCE_PP:
            result["warnings"].append(
                f"{split}: o dataset baixado tem {got}% das imagens e o split "
                f"temporal de {version} tem {want}% — a partição não é a mesma"
            )

    if total and local_total and total != local_total:
        result["warnings"].append(
            f"o dataset baixado tem {total} imagens e {version} tem {local_total} — "
            "contagens diferentes podem ser só aumento de dados do Roboflow, "
            "mas confira se a partição foi preservada"
        )

    return _finish_check(result)


def _finish_check(result: dict) -> dict:
    result["ok"] = not result["warnings"]
    return result


def print_split_check(check: dict) -> None:
    print("\n--- partição do dataset ---")
    header = f"{'':8} {'baixado':>18}"
    if check["manifest"]:
        header += f" {'split temporal ' + (check['manifest_version'] or ''):>24}"
    print(header)
    for _, split in SPLIT_KEYS:
        got = check["downloaded"][split]
        gp = check["downloaded_proportions"][split]
        line = f"{split:8} {got:>8} {'(' + str(gp) + '%)' if gp is not None else '':>9}"
        if check["manifest"]:
            want = check["manifest"]["counts"][split]
            wp = check["manifest"]["proportions"][split]
            line += f" {want:>13} {'(' + str(wp) + '%)' if wp is not None else '':>10}"
        print(line)

    if check["ok"]:
        print("\n  OK — a partição do dataset baixado bate com o split temporal.")
        return

    print("\n  ATENÇÃO")
    for warning in check["warnings"]:
        print(f"    - {warning}")
    print(
        "\n  O Roboflow reparticiona ao gerar uma versão. Se a versão foi gerada\n"
        "  com rebalanceamento, quadros vizinhos no tempo voltaram a cair em\n"
        "  partições diferentes: o modelo memoriza, a métrica de validação sobe\n"
        "  e não se sustenta em voo novo. Veja train/README.md, seção\n"
        "  'Preserve a partição ao gerar a versão'."
    )


# --- métricas ----------------------------------------------------------------


def _float(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else round(out, 5)  # descarta NaN


def _sequence(value) -> list:
    if value is None:
        return []
    try:
        return list(value)
    except TypeError:
        return []


def extract_metrics(results, names: dict | None = None) -> dict:
    """Extrai as métricas do objeto de validação do Ultralytics.

    Tolerante de propósito: a forma de `results.box` mudou entre versões, e um
    atributo ausente vira `null` no JSON em vez de derrubar o treino inteiro
    depois de horas de GPU.
    """
    box = getattr(results, "box", None)
    overall = {
        "map50": _float(getattr(box, "map50", None)),
        "map50_95": _float(getattr(box, "map", None)),
        "precision": _float(getattr(box, "mp", None)),
        "recall": _float(getattr(box, "mr", None)),
        "fitness": _float(getattr(results, "fitness", None)),
    }

    names = dict(names or getattr(results, "names", {}) or {})
    indices = [int(i) for i in _sequence(getattr(box, "ap_class_index", None))]
    ap50 = _sequence(getattr(box, "ap50", None))
    maps = _sequence(getattr(box, "maps", None))
    precision = _sequence(getattr(box, "p", None))
    recall = _sequence(getattr(box, "r", None))

    per_class = []
    for position, class_id in enumerate(indices):
        per_class.append({
            "class_id": class_id,
            "name": str(names.get(class_id, class_id)),
            "map50": _float(ap50[position]) if position < len(ap50) else None,
            # `maps` é indexado por id de classe, não pela posição na lista
            "map50_95": _float(maps[class_id]) if class_id < len(maps) else None,
            "precision": _float(precision[position]) if position < len(precision) else None,
            "recall": _float(recall[position]) if position < len(recall) else None,
        })

    return {"overall": overall, "per_class": per_class,
            "classes": [str(names[k]) for k in sorted(names)] if names else []}


def build_metrics_document(args, results, run_dir: Path, weights: Path,
                           check: dict, names: dict | None) -> dict:
    extracted = extract_metrics(results, names)
    return {
        "generated_at": time.time(),
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": "train/train.py",
        "weights": {
            "path": str(WEIGHTS_TARGET.relative_to(ROOT)),
            "sha256": sha256(weights),
            "size_bytes": weights.stat().st_size if weights.is_file() else None,
            "from_run": str(weights),
        },
        "training": {
            "base_model": args.model,
            "epochs": args.epochs,
            "imgsz": args.imgsz,
            "batch": args.batch,
            "name": run_dir.name,
            "run_dir": str(run_dir),
            "device": args.device,
        },
        "dataset": {
            "data_yaml": str(Path(args.data).resolve()),
            "name": Path(args.data).resolve().parent.name,
            "counts": check["downloaded"],
            "proportions": check["downloaded_proportions"],
            "split_manifest_version": check.get("manifest_version"),
            "split_check_ok": check["ok"],
            "split_warnings": check["warnings"],
        },
        "metrics": extracted["overall"],
        "per_class": extracted["per_class"],
        "classes": extracted["classes"],
    }


# --- execução ----------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Treina um modelo YOLO a partir de um dataset do Roboflow.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--data", required=True, help="caminho do data.yaml")
    parser.add_argument("--model", default="yolo11n.pt", help="pesos de partida")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--name", default=None, help="nome do run (padrão: m4td-<data>)")
    parser.add_argument("--device", default=None, help="cuda, 0, cpu… (padrão: automático)")
    parser.add_argument("--manifest", default=None,
                        help="split_manifest.json para conferir a partição "
                             "(padrão: o da versão mais recente em data/datasets/)")
    parser.add_argument("--skip-split-check", action="store_true",
                        help="não confere a partição do dataset baixado")
    parser.add_argument("--strict-split", action="store_true",
                        help="aborta se a partição divergir, em vez de só avisar")
    parser.add_argument("--dry-run", action="store_true",
                        help="só confere a partição e sai, sem treinar")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    data_yaml = Path(args.data).expanduser().resolve()
    if not data_yaml.is_file():
        print(f"erro: data.yaml não encontrado: {data_yaml}", file=sys.stderr)
        return 2

    config = read_yaml(data_yaml)
    check = {"downloaded": {s: 0 for _, s in SPLIT_KEYS}, "downloaded_proportions": {},
             "manifest": None, "manifest_version": None, "warnings": [], "ok": True}
    if not args.skip_split_check:
        manifest_path = Path(args.manifest).expanduser().resolve() if args.manifest else None
        check = check_split(data_yaml, config, manifest_path)
        print_split_check(check)
        if not check["ok"] and args.strict_split:
            print("\nabortado por --strict-split", file=sys.stderr)
            return 3

    if args.dry_run:
        print("\n--dry-run: nada foi treinado.")
        return 0 if check["ok"] else 1

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        print(
            f"\nerro: ultralytics não está instalado ({exc}).\n"
            f"      pip install -r train/requirements.txt",
            file=sys.stderr,
        )
        return 2

    name = args.name or f"m4td-{time.strftime('%Y%m%d-%H%M%S')}"
    print(f"\n--- treino ---\n  modelo   {args.model}\n  dados    {data_yaml}\n"
          f"  épocas   {args.epochs}\n  imgsz    {args.imgsz}\n  batch    {args.batch}\n"
          f"  run      {name}\n")

    model = YOLO(args.model)
    model.train(data=str(data_yaml), epochs=args.epochs, imgsz=args.imgsz,
                batch=args.batch, name=name, device=args.device)

    run_dir = Path(getattr(model.trainer, "save_dir", Path("runs/detect") / name)).resolve()
    best = run_dir / "weights" / "best.pt"
    if not best.is_file():
        print(f"erro: {best} não foi produzido pelo treino", file=sys.stderr)
        return 4

    print("\n--- validação ---")
    results = model.val(data=str(data_yaml), imgsz=args.imgsz, device=args.device)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, WEIGHTS_TARGET)

    document = build_metrics_document(
        args, results, run_dir, WEIGHTS_TARGET, check,
        getattr(model, "names", None),
    )
    tmp = METRICS_TARGET.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(METRICS_TARGET)

    overall = document["metrics"]
    print(
        "\n--- pronto ---\n"
        f"  pesos     {WEIGHTS_TARGET}\n"
        f"  métricas  {METRICS_TARGET}\n"
        f"  run       {run_dir}\n\n"
        f"  mAP@50     {overall['map50']}\n"
        f"  mAP@50-95  {overall['map50_95']}\n"
        f"  precision  {overall['precision']}\n"
        f"  recall     {overall['recall']}\n\n"
        "  A aplicação detecta os pesos novos sozinha, pelo mtime — não é\n"
        "  preciso reiniciar. A tela de Modelo passa a ler estas métricas."
    )
    if not check["ok"]:
        print("\n  Lembrete: a partição do dataset baixado divergiu do split "
              "temporal.\n  As métricas acima podem estar otimistas. Veja o "
              "aviso no início do log.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
