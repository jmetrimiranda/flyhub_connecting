# Treinar o modelo

O treino acontece **fora da aplicação**, na pasta `train/`. A plataforma apenas lê o que o treino produz.

Essa separação é deliberada: trocar de modelo não deve exigir mexer em nada além de dois arquivos.

## O ciclo completo

```
 1. COLETAR      plataforma → data/datasets/vX.Y/
 2. ENVIAR       plataforma → Roboflow (partição preservada)
 3. ANOTAR       Roboflow, manual + assistido pelo modelo anterior
 4. BAIXAR       Roboflow → train/datasets/
 5. TREINAR      train/train.py → best.pt + metrics.json
 6. AVALIAR      métricas no valid
 7. AJUSTAR      threshold de confiança
 8. PUBLICAR     copiar para data/models/ → a plataforma detecta sozinha
 9. VOLTA AO 1
```

As páginas seguintes cobrem cada etapa.

## O que torna isso plug-and-play

A aplicação procura exatamente dois arquivos:

```
data/models/best.pt          pesos
data/models/metrics.json     métricas para a tela Modelo
```

Nada mais. Sem configuração, sem alteração de código, sem reiniciar o processo — a detecção é pelo **mtime** do arquivo.

Se `best.pt` não existir, o `Detector` entra em passthrough e o vídeo passa cru. A aplicação nunca quebra por falta de modelo.

## Git Flow

O código da aplicação e o ciclo de treino evoluem em ritmos diferentes. A estratégia separa os dois.

```
main ────────●────────────────●──────────────●────────►
             │                │              │
             │           merge│         merge│
develop ─────●───●────●───────●───●──────────●────────►
                 │            │   │          │
                 │      ┌─────┘   │    ┌─────┘
                 │      │         │    │
feature/xxx ─────●──────┘         │    │
                                  │    │
feature/new_training ─────────────●────┘
```

| Branch | Papel |
|---|---|
| `main` | O que está em produção. Sempre funcional |
| `develop` | Integração. Recebe features antes de subir para main |
| `feature/new_training` | Um ciclo de treino |
| `feature/xxx` | Mudanças na aplicação |

### Um ciclo de treino, na prática

```bash
git checkout develop
git pull
git checkout -b feature/new_training
```

Rode o treino. Ao final, commite **os artefatos leves**, não os pesos:

```bash
git add data/models/metrics.json train/configs/
git commit -m "treino v3: mAP50 0.87, recall 0.91"
```

!!! danger "Pesos não vão para o Git"
    O `.gitignore` tem `*.pt`. Um `best.pt` de 50 MB no histórico não sai mais de lá, e cada versão adiciona outros 50 MB permanentemente.

    Guarde os pesos fora do Git: um diretório versionado em disco, um bucket, ou o próprio Roboflow.

Valide na plataforma, e só então:

```bash
git checkout develop && git merge feature/new_training && git push
git checkout main && git merge develop && git push
git tag modelo-v3 && git push origin modelo-v3
```

A **tag** é o que amarra código, métricas e pesos. Meses depois, `git show modelo-v3` diz qual dataset, quais hiperparâmetros e quais números aquele modelo produziu.

### Estrutura de arquivos

```
train/
├── train.py                 script parametrizado
├── data.yaml.example        formato esperado
├── requirements.txt         ultralytics + torch (fora do principal)
├── README.md                referência rápida
├── configs/                 hiperparâmetros de cada treino (versionado)
├── datasets/                baixado do Roboflow (ignorado)
└── runs/                    saída do Ultralytics (ignorado)

data/models/
├── best.pt                  ignorado — pesos ativos
├── metrics.json             versionado — métricas
└── samples/                 ignorado — cache
```

Versione `configs/` e `metrics.json`. Ignore `datasets/`, `runs/` e `*.pt`.

## Dependências separadas

```bash
python -m pip install -r train/requirements.txt
```

Isso arrasta torch e torchvision, ~2,5 GB. O `requirements.txt` principal não os inclui de propósito: quem só opera o painel não precisa baixar isso.

## Regra de ouro

> **Nunca aceite os rótulos do modelo sem revisar.**
>
> Todo erro aprovado vira uma "verdade" que o próximo modelo aprende. A rotulagem assistida economiza tempo de desenho, não tempo de pensar.

→ [1. Dataset](01-dataset.md)
