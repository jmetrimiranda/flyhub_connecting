# Tela Modelo

Somente leitura. Mostra o desempenho do modelo carregado.

## Métricas

Lidas de `data/models/metrics.json`, **nunca calculadas aqui**. Quem as gera é o `train/train.py`.

| Métrica | O que mede |
|---|---|
| mAP@50 | Encontrou o objeto? (IoU ≥ 0,5) |
| mAP@50-95 | Quão preciso é o contorno? (média de IoU 0,5 a 0,95) |
| Precision | Do que marcou, quanto era real |
| Recall | Do que existia, quanto encontrou |

Mais por classe, quando disponível, e a data do treino, dataset de origem e número de épocas.

Interpretação detalhada em [avaliação](../treino/04-avaliacao.md).

## Exemplos do conjunto de teste

Três imagens do `test/` da versão mais recente, com as predições desenhadas.

A escolha é **primeira, meio e última em ordem temporal** — determinística, não aleatória. Três sorteadas mudariam a cada geração e tornariam impossível comparar visualmente um modelo com o anterior. Três vizinhas seriam quase idênticas, pelo mesmo motivo que o split é temporal.

### Como são geradas

Artefato derivado com cache em disco:

```
data/models/samples/
├── samples.json          chave do cache + detecções
└── 0.jpg  1.jpg  2.jpg   já com as caixas
```

A chave é `(mtime dos pesos, versão do dataset, nomes dos três arquivos)`. Trocou o `best.pt`? O mtime muda, o cache vence sozinho e os exemplos são regerados.

A geração roda em thread com prioridade rebaixada. Se alguém abrir esta tela no meio de um voo, quem cede CPU é a tela, não o vídeo.

A rota de leitura nunca computa — devolve o cache e o estado (`pronto`, `gerando`, `ausente`). A tela carrega instantaneamente e consulta o status a cada segundo enquanto gera.

## Estados vazios

Quatro situações, nenhuma quebra a tela:

| Situação | O que a tela mostra |
|---|---|
| Sem pesos | Onde largar o `best.pt`, link para Datasets |
| Pesos sem `metrics.json` | Explica que quem as gera é o `train/train.py`; os exemplos funcionam |
| Sem dataset com `test/` | Explica que precisa de uma versão particionada |
| `metrics.json` de outro treino | Métricas marcadas como **históricas** |

O último caso é a mesma disciplina do manifesto: o `metrics.json` descreve **um treino**, não o arquivo carregado agora.

Ele guarda o `sha256` do `best.pt` que o gerou. Se alguém copiar pesos à mão sem trocar as métricas, a tela avisa em vez de mentir.

## Onde ficam os pesos

```
data/models/best.pt          ← o modelo
data/models/metrics.json     ← as métricas
data/models/samples/         ← cache dos exemplos
```

A aplicação detecta arquivo novo **pelo mtime** e recarrega sozinha, sem reiniciar o processo.

Trocar de modelo é copiar outro `best.pt` por cima. Ver [publicar os pesos](../treino/06-publicar.md).
