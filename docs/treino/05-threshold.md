# 5. Threshold

O modelo treinado não é o fim. Em produção, um número decide tudo que você vê: o **threshold de confiança**. Toda previsão abaixo dele é descartada.

- Threshold baixo → o modelo marca tudo → recall ↑ mas muitos alarmes falsos
- Threshold alto → só detecções "certas" sobrevivem → precision ↑ mas alvos reais passam

O melhor valor está no meio, e é diferente para cada modelo e cada dataset. Então medimos, em vez de chutar.

!!! danger "Ajuste no valid, confirme no test"
    Escolha o threshold no `valid`. Confirme uma única vez no `test`.

    Se escolher olhando o test, a métrica dele deixa de ser honesta.

## Como funciona a avaliação

Para cada threshold candidato:

1. Mantém só as previsões com confiança ≥ threshold
2. Casa cada previsão com um rótulo real da mesma classe com IoU ≥ 0,5 — cada rótulo só pode ser casado uma vez
3. Conta TP (casadas), FP (previsão sem par), FN (rótulo sem par)
4. Calcula precision, recall e F1

Para ser rápido, o modelo roda **uma vez por imagem** com confiança bem baixa; os thresholds são testados depois sobre as previsões salvas.

## O script

Salve como `train/tune_threshold.py`:

```python
"""
Encontra o melhor threshold de confiança no split VALID.

Prevê uma vez com conf muito baixa, depois avalia vários thresholds
casando previsões com o ground truth por IoU >= 0.5.
"""
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from ultralytics import YOLO

WEIGHTS    = "train/runs/segment/damage_v1/weights/best.pt"
DATA_DIR   = Path("train/datasets/teste-1")
SPLIT      = "valid"            # ajuste aqui; confirme depois em "test"
IMGSZ      = 1280
IOU_MATCH  = 0.5
THRESHOLDS = np.round(np.arange(0.05, 0.96, 0.05), 2)
IMG_EXTS   = {".jpg", ".jpeg", ".png"}


def load_ground_truth(label_file: Path, img_w: int, img_h: int):
    """YOLO txt (caixa ou polígono) -> [(classe, [x1,y1,x2,y2])] em pixels."""
    boxes = []
    if not label_file.exists():          # imagem sem alvo
        return boxes
    for line in label_file.read_text().splitlines():
        parts = line.split()
        cls   = int(parts[0])
        vals  = [float(v) for v in parts[1:]]
        if len(vals) == 4:               # detecção: xc yc w h
            xc, yc, w, h = vals
            box = [(xc - w / 2) * img_w, (yc - h / 2) * img_h,
                   (xc + w / 2) * img_w, (yc + h / 2) * img_h]
        else:                            # segmentação: x1 y1 x2 y2 ...
            xs, ys = vals[0::2], vals[1::2]
            box = [min(xs) * img_w, min(ys) * img_h,
                   max(xs) * img_w, max(ys) * img_h]
        boxes.append((cls, box))
    return boxes


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter  = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-9)


def evaluate(all_preds, all_gts, thr):
    TP = FP = FN = 0
    for preds, gts in zip(all_preds, all_gts):
        keep    = sorted((p for p in preds if p[1] >= thr), key=lambda p: -p[1])
        matched = set()
        for cls, conf, box in keep:
            best_iou, best_j = 0.0, -1
            for j, (gcls, gbox) in enumerate(gts):
                if j in matched or gcls != cls:
                    continue
                v = iou(box, gbox)
                if v > best_iou:
                    best_iou, best_j = v, j
            if best_iou >= IOU_MATCH:
                TP += 1
                matched.add(best_j)
            else:
                FP += 1
        FN += len(gts) - len(matched)
    return TP, FP, FN


def main():
    model  = YOLO(WEIGHTS)
    images = sorted(p for p in (DATA_DIR / SPLIT / "images").iterdir()
                    if p.suffix.lower() in IMG_EXTS)
    print(f"Avaliando {len(images)} imagens de '{SPLIT}'...")

    all_preds, all_gts = [], []
    for img_path in images:
        res  = model(img_path, conf=0.01, imgsz=IMGSZ, verbose=False)[0]
        h, w = res.orig_shape
        all_preds.append([(int(b.cls), float(b.conf), b.xyxy[0].tolist())
                          for b in res.boxes])
        all_gts.append(load_ground_truth(
            DATA_DIR / SPLIT / "labels" / (img_path.stem + ".txt"), w, h))

    rows = []
    print(f"\n{'thr':>5} {'TP':>5} {'FP':>5} {'FN':>5} "
          f"{'prec':>6} {'rec':>6} {'F1':>6}")
    for thr in THRESHOLDS:
        TP, FP, FN = evaluate(all_preds, all_gts, thr)
        prec = TP / (TP + FP + 1e-9)
        rec  = TP / (TP + FN + 1e-9)
        f1   = 2 * prec * rec / (prec + rec + 1e-9)
        rows.append([thr, prec, rec, f1])
        print(f"{thr:>5} {TP:>5} {FP:>5} {FN:>5} "
              f"{prec:>6.3f} {rec:>6.3f} {f1:>6.3f}")

    rows = np.array(rows)
    best = rows[rows[:, 3].argmax()]
    print(f"\nMelhor threshold: conf = {best[0]:.2f} "
          f"(precision {best[1]:.3f}, recall {best[2]:.3f}, F1 {best[3]:.3f})")

    plt.figure(figsize=(8, 5))
    plt.plot(rows[:, 0], rows[:, 1], marker="o", label="precision")
    plt.plot(rows[:, 0], rows[:, 2], marker="o", label="recall")
    plt.plot(rows[:, 0], rows[:, 3], marker="o", label="F1")
    plt.axvline(best[0], ls="--", c="gray", label=f"melhor = {best[0]:.2f}")
    plt.xlabel("threshold de confiança")
    plt.ylabel("score")
    plt.grid(True, alpha=0.4)
    plt.legend()
    plt.tight_layout()
    plt.savefig("train/threshold_sweep.png", dpi=150)
    print("Gráfico em train/threshold_sweep.png")


if __name__ == "__main__":
    main()
```

## Como ler o resultado

A tabela mostra o trade-off acontecendo ao vivo: conforme o threshold cresce, FP cai (precision ↑) e FN sobe (recall ↓).

O valor escolhido é o pico da curva F1 — o melhor equilíbrio.

**Confira cruzado:** o Ultralytics já salva um `F1_curve.png` quando você roda `model.val()`. O pico dele deve ficar perto do mesmo threshold. Este script existe para você ver os TP/FP/FN crus por trás da curva.

## Regra alternativa: recall primeiro

Perder um alvo real custa mais que um alarme falso. Em vez de "melhor F1", escolha o **maior recall que mantém a precision aceitável**:

```python
ok   = rows[rows[:, 1] >= 0.80]     # thresholds com precision >= 0.80
best = ok[ok[:, 2].argmax()]        # entre eles, o maior recall
```

Isso costuma dar um threshold um pouco mais baixo que o de F1 máximo — mais alarmes, menos alvos perdidos.

## Confirmar e usar

**1. Confirme no test**, uma vez só:

```python
SPLIT      = "test"
THRESHOLDS = [0.40]     # o valor escolhido
```

Os números devem ficar próximos aos do valid. Se estiverem muito piores, algo vazou ou o voo de teste é muito diferente — investigue antes de publicar.

**2. Use em produção.** Defina o threshold na aplicação:

```bash
echo "MODEL_CONF=0.40" >> .env
```

Ou passe direto ao detector, se preferir editar o código.

!!! warning "Reajuste a cada retreino"
    Todo treino novo — rótulos novos, modelo maior, mais épocas — muda a distribuição de confiança.

    Rode este sweep de novo depois de cada `best.pt` novo. O threshold do modelo anterior não vale para o novo.

→ [6. Publicar os pesos](06-publicar.md)
