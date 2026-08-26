# A plataforma

Três telas com dois propósitos: **ver a inferência ao vivo** sobre o vídeo do voo e **coletar imagens** para retreinar o modelo.

## O ciclo

```
    ┌─────────────────────────────────────────────────────┐
    │                                                     │
    ▼                                                     │
  VOA ──► COLETA ──► SPLIT ──► ROBOFLOW ──► ANOTA ──► TREINA
  drone    Home      temporal   Datasets    manual    train/
                     auto                                 │
                                                          ▼
                                                      best.pt
                                                          │
                                            ┌─────────────┘
                                            ▼
                                     INFERÊNCIA AO VIVO
                                     Home + tela Modelo
```

Cada volta melhora o modelo. A plataforma cobre tudo, menos a anotação — que é manual, no Roboflow.

## Tela Home

Operação em tempo real.

| Região | O que faz |
|---|---|
| Barra de estado | Disponibilidade, MediaMTX, Túnel, Stream |
| Vídeo | MJPEG com as detecções desenhadas, ou vídeo cru se não houver modelo |
| Conexão | Resolução, taxa, FPS de captura e inferência, latência, quadros perdidos, tempo de stream, modelo carregado |
| Pipeline | Iniciar / Parar, endereço RTMP com botão de copiar |
| Coleta | Criar dataset, e durante a gravação: Pausar / Continuar / Salvar |

O badge sobre o vídeo diz sempre qual dos dois modos está ativo — **modelo ativo** ou **sem modelo, vídeo cru**. Nunca some em silêncio.

### A coleta

O botão só habilita com os quatro indicadores verdes. Clicar com algum vermelho abre um modal listando exatamente o que falhou.

A confirmação mostra a versão que será criada (`v0.0`, `v0.1`… `v0.9`, `v1.0`) e deixa ajustar intervalo, limite e deduplicação.

Enquanto grava, as imagens vão para `raw/` com timestamp relativo no nome. **Pausar** congela sem fechar a sessão. **Salvar** encerra e dispara o split.

## Tela Datasets

| Elemento | O que faz |
|---|---|
| Lista | Versão, data, duração, imagens, distribuição, disco, status no Roboflow |
| Galeria | Abas train/valid/test, miniaturas, clique abre em tamanho real |
| Exclusão | Individual ou em lote, com confirmação. Apaga da partição **e** de `raw/` |
| Refazer split | Reparticiona a partir de `raw/` |
| Enviar ao Roboflow | Workspace, projeto, batch, tags, API key |
| Histórico | Cada exclusão e resplit, com data e contagem |

!!! warning "O manifesto não mente"
    `split_manifest.json` registra **o que o split decidiu**, não o que sobrou depois. Se você excluir imagens, as contagens exibidas (lidas do disco) divergem do manifesto — e a tela mostra essa divergência em vez de escondê-la.

    Para zerar, refaça o split.

## Tela Modelo

Somente leitura. Mostra mAP@50, mAP@50-95, precision e recall do modelo carregado, mais três exemplos do conjunto de teste com as predições desenhadas.

As três imagens são **primeira, meio e última** em ordem temporal — determinístico, para permitir comparar visualmente um modelo com o anterior.

Sem modelo, a tela explica onde colocar os pesos e sugere coletar. Sem métricas, explica que quem as gera é o `train/train.py`.

## Onde ficam os pesos

```
data/models/best.pt          ← o modelo
data/models/metrics.json     ← as métricas que a tela lê
data/models/samples/         ← cache dos três exemplos
```

O `train/train.py` grava os dois primeiros ao final do treino. A aplicação detecta o arquivo novo **pelo mtime** e recarrega sozinha, sem reiniciar o processo.

Para trocar de modelo à mão, basta copiar outro `best.pt` por cima.

!!! note "Métricas de outro treino"
    O `metrics.json` guarda o sha256 do `best.pt` que o gerou. Se você trocar os pesos sem trocar as métricas, a tela avisa que aquelas métricas são de outro treino.

## O que a plataforma não faz

- **Anotação** — é manual, no Roboflow
- **Treino** — roda em `train/`, fora da aplicação
- **Configuração do FlightHub** — editar canal e religar toggle continuam no portal da DJI
- **Autenticação** — qualquer um que alcance a porta controla o pipeline

→ [Como rodar](rodar.md) · [Hospedar na internet](hospedar.md)
