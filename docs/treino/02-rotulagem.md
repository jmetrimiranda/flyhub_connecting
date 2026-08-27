# 2. Rotulagem assistida

Rotular milhares de quadros à mão é lento. O truque é um laço em que o modelo faz o trabalho pesado e você só revisa.

```
  Rotula um lote          Treina um
  pequeno à mão   ────►   modelo auxiliar
        ▲                       │
        │                       ▼
  Você só revisa   ◄────  Auxiliar pré-rotula
  e corrige               no Roboflow
```

A cada rodada o auxiliar melhora e você corrige menos. Para quando as sugestões estiverem certas na maioria das vezes (~90%).

## Antes de desenhar qualquer coisa: defina as classes

Olhe suas imagens e escreva regras claras. Exemplo de estrutura, adapte ao seu caso:

| Classe | Como aparece nas imagens | Rotular? |
|---|---|---|
| `alvo_principal` | O que você quer detectar, descrito sem ambiguidade | Sim |
| `classe_secundaria` | Algo relacionado mas distinto | Só se o time precisar. Comece sem, na dúvida |
| Elementos normais | Partes esperadas da cena, não são o alvo | Não |

!!! tip "Menos classes = primeiro modelo melhor"
    Comece com uma classe. É fácil adicionar outra depois; é doloroso corrigir 500 imagens rotuladas com regras confusas.

    Seja consistente: o modelo aprende exatamente o que você desenha.

## Quantas imagens rotular à mão?

Não há número mágico, mas estas faixas funcionam bem na prática:

| Imagens à mão | O que você obtém |
|---|---|
| ~100–150 | Auxiliar fraco. Acha o óbvio. Usável, mas você corrige muito |
| **~200–300** | Auxiliar sólido. Já torna a rotulagem assistida bem mais rápida que a manual |
| 800–1500+ | Suficiente para o modelo de produção, depois de algumas rodadas |

**Variedade importa mais que quantidade.** Suas 200–300 imagens precisam cobrir: sol e sombra, vistas próximas e distantes, todos os ativos, todos os tamanhos de alvo, e **algumas imagens sem nenhum alvo** — negativos ensinam o modelo a ignorar.

Conte instâncias também: uma imagem pode conter vários alvos. Mire em ~300 instâncias no primeiro lote.

## Rotular rápido com Smart Polygon

O Roboflow tem uma ferramenta de segmentação assistida que roda SAM por baixo:

1. Projeto → **Annotate** → escolha uma imagem
2. Selecione **Smart Polygon**
3. Clique uma vez dentro do alvo. O polígono é desenhado sozinho. Clique em pontos extras para adicionar ou remover áreas
4. Atribua a classe e salve

Você obtém rótulos com qualidade de segmentação quase na velocidade de caixa delimitadora.

## Treinar o auxiliar

Baixe as imagens rotuladas do Roboflow — versão **sem preprocessing e sem augmentation**:

```python
from roboflow import Roboflow

rf      = Roboflow(api_key="SUA_CHAVE")
project = rf.workspace("robotdog-5oy4l").project("teste-v52z4")
dataset = project.version(1).download("yolov11")
print("Dataset em:", dataset.location)
```

Treino rápido:

```bash
python train/train.py \
  --data train/datasets/teste-1/data.yaml \
  --model yolo11s-seg.pt \
  --epochs 100 \
  --imgsz 1280 \
  --batch 8 \
  --name helper_v1
```

O `yolo11s-seg` é um bom equilíbrio velocidade/qualidade para auxiliar. Com 8 GB de VRAM e `imgsz 1280`, `batch 8` costuma caber — se der out of memory, caia para 4.

## Colocar o auxiliar dentro do Roboflow

O Roboflow permite subir seus próprios pesos e usá-los para pré-rotular. É literalmente "a rede neural rotula para mim".

```python
from roboflow import Roboflow

rf      = Roboflow(api_key="SUA_CHAVE")
project = rf.workspace("robotdog-5oy4l").project("teste-v52z4")

project.version(1).deploy(
    model_type="yolov11-seg",              # ou "yolov11" para detecção
    model_path="train/runs/segment/helper_v1",
)
```

!!! warning "Compatibilidade de versão"
    O Roboflow valida a versão do Ultralytics usada no treino. A documentação deles já exigiu `ultralytics<=8.3.40` para pesos YOLOv11.

    Se o upload reclamar, ou você instala a versão indicada e retreina o auxiliar, ou consulta as regras atuais na documentação do Roboflow sobre upload de pesos customizados.

Agora use na anotação:

1. Espere alguns minutos o Roboflow processar (aparece um check verde na versão)
2. **Annotate** → abra uma imagem sem rótulo
3. Clique no ícone **Label Assist** (varinha) → selecione seu modelo → confiança inicial ~0,4
4. O modelo desenha os polígonos

Seu trabalho muda de **desenhar** para **revisar**: corrigir formas erradas, apagar alarmes falsos, adicionar o que faltou, aprovar.

## O laço, na prática

1. Rotule ~200–300 imagens com Smart Polygon → treine `helper_v1` → publique
2. Com Label Assist, revise mais ~300–500 imagens (bem mais rápido agora)
3. Retreine (`helper_v2`) com todos os rótulos → republique → repita
4. Pare quando o assistente acertar ~90% das vezes e você tiver ~800–1500+ instâncias rotuladas

Esse dataset treina o modelo de produção.

## Regra de ouro

!!! danger "Nunca aceite os rótulos do modelo sem olhar"
    Todo erro que você aprova vira uma "verdade" que o próximo modelo aprende — e o erro se propaga, amplificado, por todas as rodadas seguintes.

    A rotulagem assistida economiza tempo de desenho, não tempo de pensar.

→ [3. Treino](03-treino.md)
