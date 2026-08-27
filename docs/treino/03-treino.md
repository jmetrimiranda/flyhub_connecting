# 3. Treino

O treino roda em `train/`, fora da aplicação. Produz dois arquivos que a plataforma lê.

## Preparar

```bash
cd ~/Desktop/git_repositories/flyhub_connecting
source .venv/bin/activate
python -m pip install -r train/requirements.txt
```

Confirme a GPU:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

## Baixar o dataset anotado

```python
from roboflow import Roboflow

rf      = Roboflow(api_key="SUA_CHAVE")
project = rf.workspace("robotdog-5oy4l").project("teste-v52z4")
dataset = project.version(1).download("yolov11")
print("Dataset em:", dataset.location)
```

Ou pela CLI do Roboflow, se preferir.

O export já vem com os rótulos em formato YOLO e um `data.yaml` pronto.

## Conferir a partição

O `train.py` compara as contagens do `data.yaml` baixado com o `split_manifest.json` local antes de treinar:

```
                    baixado      split temporal v0.3
train         686   (70.0%)           695    (70.9%)
valid         196   (20.0%)           140    (14.3%)
test           98   (10.0%)           145    (14.8%)

  ATENÇÃO
    - valid: o dataset baixado tem 20.0% e o split temporal tem 14.3%
```

Isso pega o caso em que o Roboflow redividiu ao gerar a versão — o que desfaria todo o cuidado do split temporal.

| Flag | Comportamento |
|---|---|
| padrão | avisa e continua |
| `--strict-split` | aborta se divergir |
| `--dry-run` | confere sem treinar |

O resultado vai para o `metrics.json` em `split_check_ok`, e a tela Modelo mostra que aquelas métricas podem estar otimistas.

!!! note "Aumento de dados não é rebalanceamento"
    O augmentation do Roboflow multiplica imagens **dentro** da partição, então a proporção se mantém. A checagem não confunde os dois.

## Treinar

```bash
python train/train.py \
  --data train/datasets/teste-1/data.yaml \
  --model yolo11s-seg.pt \
  --epochs 100 \
  --imgsz 1280 \
  --batch 8 \
  --name damage_v1
```

| Parâmetro | O que faz | Sugestão |
|---|---|---|
| `--data` | Caminho do `data.yaml` | do download |
| `--model` | Modelo base | `yolo11n` rápido, `yolo11s` equilibrado, `yolo11m` melhor |
| `--epochs` | Passagens pelo dataset | 100 para começar |
| `--imgsz` | Resolução de entrada | 1280 para alvos pequenos, 640 se couber |
| `--batch` | Imagens por passo | ver abaixo |
| `--name` | Nome da execução | identifique a rodada |

### Batch size e VRAM

Com 8 GB, e o desktop consumindo ~3 GB:

| `imgsz` | `batch` seguro |
|---|---|
| 640 | 16 |
| 1280 | 8 |
| 1280 (seg) | 4–8 |

Se der `CUDA out of memory`, reduza o batch pela metade. Fechar o navegador libera ~500 MB.

```bash
nvidia-smi   # veja a VRAM livre antes de começar
```

## O que o script produz

```
data/models/best.pt          ← copiado ao final
data/models/metrics.json     ← gerado ao final
train/runs/segment/damage_v1/
├── weights/best.pt
├── weights/last.pt
├── results.csv
├── confusion_matrix.png
├── PR_curve.png
└── F1_curve.png
```

O `metrics.json` contém mAP@50, mAP@50-95, precision, recall, valores por classe, data, nome do dataset e o `sha256` dos pesos.

## Segmentação ou detecção?

| | Caixa (detecção) | Máscara (segmentação) |
|---|---|---|
| Rotulagem | mais rápida | Smart Polygon deixa quase igual |
| Treino | mais leve | ~30% mais lento |
| Saída | posição e tamanho | **área** |

Se você precisa medir **área** do que foi detectado, use segmentação — o modelo termina em `-seg` e as métricas relevantes são as de máscara.

## Interpretar os resultados

O Ultralytics imprime uma tabela por época. O que observar:

- **`box_loss` e `seg_loss` caindo** — o modelo está aprendendo
- **`mAP50` subindo e depois estabilizando** — chegou ao teto do dataset
- **`mAP50` no valid caindo enquanto o treino melhora** — overfitting; pare antes ou colete mais dados

Detalhes em [4. Avaliação](04-avaliacao.md).

→ [4. Avaliação](04-avaliacao.md)
