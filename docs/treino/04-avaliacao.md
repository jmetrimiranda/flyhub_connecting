# 4. Avaliação

Depois do treino, os números dizem se dá para confiar no modelo. Esta página explica cada métrica com palavras simples.

## Obter os números

```python
from ultralytics import YOLO

model   = YOLO("train/runs/segment/damage_v1/weights/best.pt")
metrics = model.val(
    data="train/datasets/teste-1/data.yaml",
    split="test",          # use "val" durante o desenvolvimento
    imgsz=1280,
)
print("Box  mAP50:", metrics.box.map50)
print("Mask mAP50:", metrics.seg.map50)
```

O Ultralytics salva os gráficos (matriz de confusão, curva PR, curva F1) em `runs/segment/val*/`.

!!! danger "valid vs test"
    Tome **toda** decisão no `valid`: comparar modelos, ajustar threshold, escolher hiperparâmetros.

    Toque no `test` **uma vez só**, no final. Se você ajustar olhando o test, o número dele deixa de ser honesto — vira mais um conjunto de treino disfarçado.

## IoU — Intersection over Union

Mede quanto a região prevista se sobrepõe à região real:

```
IoU = área da interseção / área da união
```

Vai de 0 (nenhuma sobreposição) a 1 (perfeita). Uma previsão normalmente conta como correta com **IoU ≥ 0,5**.

## TP, FP, FN

| Termo | O que é | Custo |
|---|---|---|
| **TP** — verdadeiro positivo | Marcou um alvo e ele existia (IoU ≥ 0,5) | — |
| **FP** — falso positivo | Marcou onde não havia nada | A equipe inspeciona um ponto sadio à toa |
| **FN** — falso negativo | Havia um alvo real e o modelo não viu | **O defeito continua crescendo sem ninguém saber** |
| **TN** — verdadeiro negativo | Não marcou e não havia nada | Não é contado — há infinitas regiões vazias numa imagem |

## Precision

```
Precision = TP / (TP + FP)
```

De tudo que o modelo marcou, quanto era real?

Precisão baixa = muitos alarmes falsos = **a equipe para de confiar no sistema**. E um sistema em que ninguém confia é pior que sistema nenhum, porque consome atenção sem entregar valor.

## Recall

```
Recall = TP / (TP + FN)
```

De tudo que existia, quanto o modelo encontrou?

Recall baixo = alvo passando despercebido. Em inspeção de ativos, **é a métrica que você menos quer sacrificar**.

## F1-score

```
F1 = 2 × (Precision × Recall) / (Precision + Recall)
```

Um número único que equilibra os dois. Só fica alto quando ambos estão bons. Usado em [5. Threshold](05-threshold.md) para escolher o corte de confiança.

## Confiança

Toda previsão vem com uma confiança entre 0 e 1. O **threshold** que você escolhe decide quais previsões são mantidas:

- Threshold baixo → mais detecções (recall ↑, precision ↓)
- Threshold alto → menos detecções (precision ↑, recall ↓)

## mAP50 e mAP50-95

**AP** é a área sob a curva precision-recall — a qualidade do modelo resumida em todos os thresholds ao mesmo tempo. Por isso é o número padrão para comparar versões.

**mAP** é a média entre as classes.

| Métrica | Pergunta que responde |
|---|---|
| **mAP50** | Achou o alvo? (IoU ≥ 0,5) |
| **mAP50-95** | Quão preciso é o contorno? (média de IoU 0,5 a 0,95) |

O mAP50-95 é sempre menor e mais rigoroso.

### Box vs Mask — (B) vs (M)

Um modelo de segmentação reporta cada métrica duas vezes: para a caixa `mAP50(B)` e para a máscara `mAP50(M)`.

Se a área vem da máscara, **as métricas de máscara são as que importam**.

## Matriz de confusão

Cruza o que o modelo previu (linhas) com o que é verdade (colunas). O Ultralytics adiciona uma classe `background`, e é nela que moram os erros de detecção.

| | true: alvo | true: background |
|---|---|---|
| **pred: alvo** | 84 (TP) | 9 (FP — alarmes falsos) |
| **pred: background** | 12 (FN — perdidos) | — |

Lendo: 84 acertos, 9 alarmes em cima de nada, 12 alvos reais perdidos. **A última célula é a que merece atenção.**

A partir dela:

```
recall    = 84 / (84 + 12) = 0,875
precision = 84 / (84 +  9) = 0,903
```

Com mais classes, células fora da diagonal indicam confusão entre elas.

## Em qual métrica confiar

Para inspeção de ativos, perder um alvo real (FN) custa muito mais que um alarme falso (FP).

| Prioridade | Métrica | Por quê |
|---|---|---|
| 1 | **Recall** | Não deixar passar despercebido |
| 2 | **Precision** | Manter os alarmes baixos o suficiente para o time confiar |
| 3 | **mAP50(M)** | Número geral para comparar versões |

**Alvo prático:** recall ≥ 0,90 com precision ≥ 0,80 no `valid`. O threshold que leva até lá é exatamente o que a [página 5](05-threshold.md) encontra.

→ [5. Threshold](05-threshold.md)
