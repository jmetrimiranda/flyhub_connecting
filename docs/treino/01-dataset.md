# 1. Dataset

A plataforma já faz a extração de quadros, a deduplicação e o split temporal. Esta página explica **por que** cada decisão foi tomada — e como fazer o mesmo a partir de vídeos já gravados.

## Por que split temporal

Um vídeo é uma sequência de fotos tiradas muito próximas no tempo. Dois quadros separados por 1 segundo são praticamente a mesma foto.

Se você embaralhar todos os quadros e dividir aleatoriamente, cópias quase idênticas caem em `train` **e** em `test`. O modelo "já viu a resposta" durante o treino, e suas métricas ficam ótimas — mas mentem. Isso se chama **vazamento de dados**.

A correção é dividir por tempo, não por sorteio:

```
linha do tempo do voo:
[========== train (70%) ==========][ valid (15%) ][ test (15%) ]
```

O modelo treina no começo do voo e é testado em imagens que nunca viu — que é exatamente o que acontece quando um voo novo chega.

### A margem de descarte

Não basta cortar. Os quadros exatamente na fronteira são os mais parecidos entre si:

```
… 96 97 98 [99 100 101 102 103] 104 105 …
   train        descartados       valid
```

A plataforma descarta 5 quadros para cada lado por padrão. Eles continuam em `raw/` e aparecem nomeados no manifesto, com o motivo.

!!! warning "Margem pesa mais em dataset pequeno"
    Com 87 quadros, `valid` ficou com 4% em vez dos 15% pedidos — a margem consumiu proporção demais.

    O manifesto registra `margin_requested` diferente de `margin_applied` quando isso acontece, e a tela avisa. Colete mais tempo.

### O caso que o split temporal não resolve sozinho

Se o drone filma a área A no início do voo e volta à área A no fim, o mesmo ativo aparece em `train` e em `test`. A deduplicação remove só vistas muito similares, não "mesmo ativo de outro ângulo".

Duas saídas:

- **Melhor**: com vários voos, coloque um voo inteiro em `test` em vez de usar o split por voo
- **Mínimo**: abra `test/images/` e confira a olho que não repete vistas de `train`

## Por que remover quase-duplicatas

Mesmo dentro de uma partição, manter 30 cópias da mesma vista desperdiça disco, tempo de rotulagem e tempo de treino — e distorce a distribuição que o modelo aprende.

A plataforma compara a diferença média absoluta entre quadros consecutivos. Quando o drone paira, ela descarta as repetições.

!!! tip "Desligue a dedup com o padrão de teste"
    O padrão colorido do `fake_stream.sh` quase não muda entre quadros, então a dedup descartaria quase tudo. Com vídeo real de voo, mantenha ligada.

## A partir de vídeos já gravados

Se você tem vídeos de voos anteriores que não passaram pela plataforma, este script faz o mesmo trabalho — com uma vantagem: usa **pHash** para deduplicação global, comparando cada quadro novo contra todos os já mantidos, de todos os vídeos.

```bash
python -m pip install opencv-python-headless imagehash pillow
```

| Ajuste | Significado | Valor inicial |
|---|---|---|
| `TARGET_FPS` | Quadros por segundo mantidos | 1.0 |
| `HASH_DISTANCE` | Similaridade para contar como duplicata | 5 |
| `SPLITS` | Frações temporais | 0.70 / 0.15 / 0.15 |

```python
"""
Extrai quadros de vídeos, remove quase-duplicatas e cria split temporal.
"""
from pathlib import Path
import csv

import cv2
import imagehash
from PIL import Image

VIDEOS_DIR    = Path("data/videos")
OUTPUT_DIR    = Path("train/datasets/from_videos")
TARGET_FPS    = 1.0
HASH_DISTANCE = 5
SPLITS        = {"train": 0.70, "valid": 0.15, "test": 0.15}
VIDEO_EXTS    = {".mp4", ".mov", ".avi", ".mkv"}


def get_split(position: float) -> str:
    """position = tempo do quadro / duração do vídeo (0.0 a 1.0)."""
    if position < SPLITS["train"]:
        return "train"
    if position < SPLITS["train"] + SPLITS["valid"]:
        return "valid"
    return "test"


def extract_video(video_path: Path, kept_hashes: list, writer) -> dict:
    cap      = cv2.VideoCapture(str(video_path))
    fps      = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total    = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total / fps

    step  = max(1, round(fps / TARGET_FPS))
    stats = {"kept": 0, "duplicates": 0}
    idx   = -1

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if idx % step != 0:
            continue

        # duplicata global — compara contra tudo que já foi mantido
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        h = imagehash.phash(img)
        if any(h - other <= HASH_DISTANCE for other in kept_hashes):
            stats["duplicates"] += 1
            continue
        kept_hashes.append(h)

        split   = get_split((idx / fps) / duration)
        out_dir = OUTPUT_DIR / split
        out_dir.mkdir(parents=True, exist_ok=True)
        name    = f"{video_path.stem}_f{idx:06d}.jpg"
        cv2.imwrite(str(out_dir / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])

        writer.writerow([video_path.name, name, f"{idx / fps:.2f}", split])
        stats["kept"] += 1

    cap.release()
    return stats


def main():
    videos = sorted(p for p in VIDEOS_DIR.iterdir()
                    if p.suffix.lower() in VIDEO_EXTS)
    if not videos:
        print(f"Nenhum vídeo em {VIDEOS_DIR.resolve()}")
        return

    kept_hashes = []          # compartilhado -> dedup global
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_DIR / "manifest.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["video", "frame", "time_seconds", "split"])
        for video in videos:
            stats = extract_video(video, kept_hashes, writer)
            print(f"{video.name}: {stats['kept']} mantidos, "
                  f"{stats['duplicates']} duplicatas removidas")


if __name__ == "__main__":
    main()
```

O `manifest.csv` registra de onde veio cada quadro. Guarde — é sua rastreabilidade.

!!! note "Uma checagem resolve dois problemas"
    A lista `kept_hashes` é compartilhada entre todos os vídeos e todas as partições. Assim, um quadro em `valid` nunca pode ser quase-cópia de um em `train`: a segunda cópia simplesmente não é salva.

## Enviar ao Roboflow

A plataforma faz isso pela tela de Datasets. Para o script acima, o equivalente:

```python
from pathlib import Path
from roboflow import Roboflow

rf      = Roboflow(api_key="SUA_CHAVE")
project = rf.workspace("robotdog-5oy4l").project("teste-v52z4")

for split in ["train", "valid", "test"]:
    images = sorted((Path("train/datasets/from_videos") / split).glob("*.jpg"))
    print(f"Enviando {len(images)} imagens para '{split}'...")
    for img in images:
        project.upload(
            image_path=str(img),
            split=split,               # preserva o split temporal
            batch_name=f"videos_{split}",
            num_retry_uploads=3,
        )
```

## Configuração do Roboflow que importa

Ao gerar a versão (**Generate → New Version**):

| Ajuste | O que fazer |
|---|---|
| Preprocessing | **Remova tudo.** Só Auto-Orient pode ficar |
| Augmentations | **Nenhuma** |
| Train/Test split | **Não rebalanceie nem redivida** |

!!! danger "O Roboflow redivide se você deixar"
    Se você gerar a versão com split diferente do que subiu, o `data.yaml` vem com a partição do Roboflow — aleatória — e todo o cuidado do split temporal é desfeito.

    O `train.py` confere isso automaticamente e avisa. Ver [3. Treino](03-treino.md).

Redimensionamento e aumento de dados são feitos pelo código de treino. Fazer duas vezes prejudica o modelo.

→ [2. Rotulagem assistida](02-rotulagem.md)
