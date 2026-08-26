# Treino

O ciclo fechado do projeto:

```
voa → coleta → split temporal → Roboflow → anota → TREINA → best.pt → inferência ao vivo
                                                    ^^^^^^^^^^^^^^^^
                                                    esta pasta
```

Nada aqui roda dentro da aplicação. O painel só **lê** o que este script
produz: `data/models/best.pt` e `data/models/metrics.json`.

---

## Instalação

Separada de propósito:

```bash
pip install -r train/requirements.txt
```

`ultralytics` arrasta torch e torchvision, ~2,5 GB. A aplicação não precisa de
nada disso — sem pesos ela roda em modo passthrough, e com pesos o `Detector`
importa `ultralytics` preguiçosamente, dentro da função de carga. Por isso o
`requirements.txt` principal não inclui nenhum dos dois: quem só opera o painel
não instala 2,5 GB à toa.

---

## 1. Baixar o dataset anotado do Roboflow

Depois de anotar as imagens no Roboflow, gere uma versão e baixe no formato
**YOLOv11** (ou YOLOv8 — o layout é o mesmo).

```python
from roboflow import Roboflow

rf = Roboflow(api_key="…")
project = rf.workspace("SEU_WORKSPACE").project("SEU_PROJETO")
project.version(1).download("yolov11", location="datasets/v1")
```

Ou pelo botão *Download Dataset* da interface, escolhendo *show download code*.

### Preserve a partição ao gerar a versão

**Este é o ponto em que todo o cuidado da coleta pode ser perdido em um clique.**

O painel particiona o dataset por **blocos contíguos de tempo**, com uma margem
de quadros descartados nas fronteiras, e sobe cada imagem ao Roboflow com o
parâmetro `split=` explícito. A razão está no `SPEC_ATUAL.md`, §7: quadros
consecutivos de vídeo são quase idênticos, e um split aleatório coloca o quadro
*N* em treino e o *N+1* em validação. O modelo memoriza em vez de generalizar, a
métrica de validação sobe para valores que não se sustentam em voo novo, e nada
no treino indica que aconteceu.

Ao **gerar uma versão**, o Roboflow oferece rebalancear a partição — o passo
*Train/Test Split*, que por padrão sugere algo como 70/20/10. Se você aceitar,
ele redistribui as imagens **aleatoriamente**, e o vazamento que o split
temporal evitou volta pela porta dos fundos:

- o `data.yaml` baixado vem com a partição **do Roboflow**, não a temporal;
- quadros vizinhos no tempo voltam a ficar em partições diferentes;
- o treino roda normalmente e reporta métricas melhores do que a realidade.

**O que fazer:** na tela *Generate* → *Train/Test Split*, escolha manter a
divisão existente (a opção que preserva o que veio no upload, geralmente
rotulada *Keep existing split* / *Use existing split*). Não use *Rebalance*.

Pré-processamento e aumento de dados (*Preprocessing* e *Augmentation*) podem
ser usados normalmente: eles multiplicam imagens **dentro** de cada partição,
não movem imagens entre partições. A contagem de train sobe, a proporção muda, e
isso é esperado — o que não pode acontecer é uma imagem mudar de partição.

### Como conferir que deu certo

Compare as contagens do dataset baixado com as do `split_manifest.json` local:

```bash
# o que o split temporal decidiu
python3 -c "import json;m=json.load(open('data/datasets/v0.3/split_manifest.json'));print(m['counts'])"
# o que veio do Roboflow
for s in train valid test; do echo -n "$s "; ls datasets/v1/$s/images | wc -l; done
```

As proporções têm que bater. Se train era 70% e voltou 70%, valid era 15% e
voltou 20%, a versão foi rebalanceada — volte ao Roboflow e gere outra.

O `train.py` **faz essa conferência sozinho** antes de treinar, comparando com o
manifesto da versão mais recente em `data/datasets/`. Ele imprime uma tabela
lado a lado e avisa em vermelho quando divergem:

```
--- partição do dataset ---
                    baixado      split temporal v0.3
train         686   (70.0%)           695    (70.9%)
valid         196   (20.0%)           140    (14.3%)
test           98   (10.0%)           145    (14.8%)

  ATENÇÃO
    - valid: o dataset baixado tem 20.0% das imagens e o split temporal de
      v0.3 tem 14.3% — a partição não é a mesma
```

Para conferir sem treinar nada:

```bash
python3 train/train.py --data datasets/v1/data.yaml --dry-run
```

Sai com código 0 se a partição bate, 1 se divergiu. Use `--strict-split` para
abortar o treino em vez de só avisar, `--manifest` para apontar outra versão e
`--skip-split-check` para não conferir.

---

## 2. Treinar

```bash
python3 train/train.py --data datasets/v1/data.yaml --epochs 100
```

| Argumento | Padrão | O que é |
|---|---|---|
| `--data` | *obrigatório* | caminho do `data.yaml` |
| `--model` | `yolo11n.pt` | pesos de partida; `yolo11s.pt`, `yolo11m.pt`… para modelos maiores |
| `--epochs` | `100` | épocas |
| `--imgsz` | `640` | lado da imagem no treino |
| `--batch` | `16` | tamanho do lote; baixe se faltar VRAM |
| `--name` | `m4td-<data>` | nome do run, vira o nome da pasta em `runs/detect/` |
| `--device` | automático | `cpu`, `0`, `cuda`… |

Sem GPU o treino roda, mas é lento a ponto de não valer para 100 épocas. Um
`--epochs 5 --imgsz 320` serve para verificar o encanamento de ponta a ponta
antes de mandar o treino real numa máquina com GPU.

---

## 3. Onde os arquivos vão parar

O Ultralytics grava tudo do run em `runs/detect/<name>/` — pesos, curvas,
matriz de confusão, `results.csv`, `args.yaml`. Essa pasta fica onde está: é o
registro completo do treino.

No fim, o script copia dois arquivos para onde a aplicação lê:

```
data/models/
├── best.pt         ← cópia de runs/detect/<name>/weights/best.pt
└── metrics.json    ← é isto que a tela de Modelo mostra
```

O `metrics.json` traz mAP@50, mAP@50-95, precision, recall, o mesmo por classe,
a data, o dataset de origem, os hiperparâmetros, o caminho do run e o **sha256
do `best.pt`**. O hash não é decorativo: é ele que permite à tela de Modelo
avisar quando o `metrics.json` é de um treino diferente do `best.pt` que está
carregado — o caso de alguém copiar pesos à mão por cima.

O resultado da conferência de partição também entra no `metrics.json`, em
`dataset.split_check_ok` e `dataset.split_warnings`. Meses depois dá para saber
se aquelas métricas vieram de um dataset com a partição preservada.

---

## 4. Como a aplicação detecta os pesos novos

**Sozinha, sem reiniciar.** O `Detector` (`app/inference.py`) confere o mtime de
`data/models/best.pt` no máximo uma vez por segundo. Assim que o arquivo muda —
apareceu, sumiu ou foi reescrito —, ele recarrega na próxima chamada.

Na prática, ao terminar o treino:

1. o badge sobre o vídeo, na Home, muda de `SEM MODELO — vídeo cru, sem
   detecções` (amarelo) para `MODELO ATIVO — best.pt · N classes` (verde);
2. as caixas passam a aparecer no vídeo ao vivo e no MJPEG;
3. a tela **Modelo** passa a mostrar as métricas e gera três exemplos do
   conjunto de teste com as predições desenhadas.

Se o arquivo for reescrito com o mesmo mtime — raro, mas acontece com alguns
sistemas de arquivos e ferramentas de cópia —, o botão **Recarregar pesos** no
painel da Home força a releitura.

Se a carga falhar (arquivo corrompido, torch ausente na máquina do painel), a
aplicação **não quebra**: cai em passthrough, o badge fica vermelho com
`MODELO NÃO CARREGOU — vídeo cru, sem detecções`, e a mensagem do erro aparece
no painel Modelo. O vídeo continua passando.

---

## 5. O ciclo de novo

Com o modelo em produção, a coleta seguinte já mostra as detecções sobre o vídeo
do voo — e os quadros em que o modelo erra são exatamente os que valem a pena
coletar para a próxima versão do dataset. A versão sobe para `v0.4`, `v0.5`, e o
`batch_name` no Roboflow marca de qual voo veio cada imagem.
