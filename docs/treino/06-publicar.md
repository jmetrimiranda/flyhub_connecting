# 6. Publicar os pesos

A parte plug-and-play: colocar o modelo novo em produção sem mexer em código, sem reiniciar processo, sem configurar nada.

## O que a aplicação procura

```
data/models/best.pt          pesos
data/models/metrics.json     métricas para a tela Modelo
```

Só isso. A detecção é pelo **mtime** do arquivo — a aplicação percebe que mudou e recarrega sozinha.

## Publicar

O `train.py` já copia ao final. Se você treinou por fora:

```bash
cp train/runs/segment/damage_v1/weights/best.pt data/models/best.pt
cp train/runs/segment/damage_v1/metrics.json data/models/metrics.json
```

Confira na tela Home: o badge sobre o vídeo deve mudar de "SEM MODELO" para o nome do arquivo e o número de classes.

Se demorar, clique em **Recarregar pesos** no card Modelo.

## Verificar

Na tela **Modelo**:

- [ ] As métricas aparecem e batem com o treino
- [ ] Os três exemplos do test mostram detecções coerentes
- [ ] Não há aviso de "métricas de outro treino"

O último item é importante. O `metrics.json` guarda o `sha256` dos pesos que o geraram — se você trocar o `best.pt` sem trocar as métricas, a tela avisa em vez de mentir sobre o desempenho.

Na tela **Home**, com stream ativo:

- [ ] As caixas aparecem sobre o vídeo
- [ ] **FPS de inferência** compatível com a GPU
- [ ] Sem erro no log do `run.sh`

## Rollback

Guarde a versão anterior antes de trocar:

```bash
mkdir -p data/models/history
cp data/models/best.pt data/models/history/best_v2.pt
cp data/models/metrics.json data/models/history/metrics_v2.json
```

Voltar é copiar de volta:

```bash
cp data/models/history/best_v2.pt data/models/best.pt
cp data/models/history/metrics_v2.json data/models/metrics.json
```

A aplicação detecta e recarrega. Sem downtime.

## Git Flow do ciclo

```bash
# antes de treinar
git checkout develop && git pull
git checkout -b feature/new_training

# depois de treinar e validar
git add data/models/metrics.json train/configs/
git commit -m "treino v3: mAP50 0.87, recall 0.91, threshold 0.40"

git checkout develop && git merge feature/new_training && git push
git checkout main && git merge develop && git push

git tag modelo-v3
git push origin modelo-v3
```

!!! danger "Pesos não vão para o Git"
    O `.gitignore` tem `*.pt`. Um arquivo de 50 MB no histórico não sai mais de lá — e cada versão adiciona outros 50 MB permanentemente, para sempre, em todo clone.

    Versione o `metrics.json` e os hiperparâmetros. Guarde os pesos em disco, num bucket, ou no próprio Roboflow.

A **tag** é o que amarra tudo. Meses depois, `git show modelo-v3` responde: qual dataset, quais hiperparâmetros, quais métricas.

## O que registrar em cada ciclo

Mantenha um `train/configs/modelo-v3.yaml`:

```yaml
dataset:
  roboflow_project: teste-v52z4
  version: 3
  images: {train: 695, valid: 140, test: 145}
  source_collections: [v0.3, v0.4, v0.5]

training:
  base_model: yolo11s-seg.pt
  epochs: 100
  imgsz: 1280
  batch: 8

results:
  map50_mask: 0.87
  map50_95_mask: 0.61
  precision: 0.83
  recall: 0.91
  best_threshold: 0.40

notes: |
  Terceira rodada. Adicionadas imagens de voo noturno.
  Recall subiu de 0.84 para 0.91 sem perder precision.
```

Sem isso, daqui a seis meses ninguém sabe por que o modelo v3 é melhor que o v2 — nem como reproduzi-lo.

## Checklist de publicação

- [ ] Threshold reajustado para este modelo
- [ ] Métricas confirmadas no test, uma vez só
- [ ] Versão anterior salva em `history/`
- [ ] `best.pt` e `metrics.json` copiados
- [ ] Badge na Home mostra o modelo novo
- [ ] Tela Modelo sem aviso de divergência
- [ ] Config registrado em `train/configs/`
- [ ] Commit e tag

Volte ao [ciclo](index.md) para a próxima rodada.
