# Especificação: plataforma de coleta e inferência

> Briefing para o Claude Code. Abra o projeto e passe este arquivo como contexto.

## Contexto

Existe um pipeline funcionando que traz vídeo ao vivo de drones DJI para o OpenCV, e um painel web (fatias 1 e 2) que controla MediaMTX e túnel. Leia `SPEC_ATUAL.md` para o estado atual do código em `app/`.

Esta especificação transforma o painel em uma plataforma de **três telas** com dois propósitos:

1. **Ver a inferência do modelo em tempo real** sobre o vídeo do voo
2. **Coletar imagens rotuláveis** e enviá-las a um projeto Roboflow, onde serão anotadas e usarão para retreinar

O ciclo é: voa → coleta → sobe pro Roboflow → anota → treina → novos pesos → volta pra inferência.

## Stack

Mantenha o que já existe. Adições mínimas.

- **Backend:** FastAPI, Uvicorn
- **Frontend:** Jinja2 + JS puro. Sem build step, sem npm
- **Estado:** SQLite via `sqlite3` da stdlib
- **Visão:** OpenCV headless, Ultralytics (opcional em runtime)
- **Upload:** `roboflow` (SDK oficial)

---

## Princípio central: o modelo é opcional

**A aplicação precisa funcionar sem nenhum modelo treinado.** No começo do projeto não existem pesos — o objetivo da coleta é justamente criar o dataset para treinar o primeiro.

Implemente `app/inference.py` com um `Detector` que:

- Carrega pesos de `MODEL_WEIGHTS` (padrão: `data/models/best.pt`)
- **Se o arquivo não existir**, entra em modo passthrough: `detect(frame)` devolve o quadro intacto e uma lista vazia de detecções. Não lança exceção, não impede a aplicação de subir
- Expõe `is_loaded`, `weights_path` e `classes` para a interface mostrar o estado
- Recarrega sob demanda, sem reiniciar o processo, quando o arquivo mudar

A interface indica claramente qual dos dois modos está ativo. Nunca some silenciosamente — o operador precisa saber se está vendo detecções reais ou vídeo cru.

Toda importação de `ultralytics` deve ser preguiçosa (dentro da função), para que a aplicação suba em máquina sem torch instalado.

---

## Tela 1 — Home

Evolui a tela atual. Mantenha a barra de estado e os controles de pipeline como estão.

### 1.1 Visualização ao vivo

Substitua o placeholder pelo **vídeo real**: MJPEG em `/stream`, `multipart/x-mixed-replace`, servindo o quadro **após** a inferência.

Requisitos do leitor:

- Thread separada que sempre descarta quadros antigos. Se a inferência for mais lenta que o stream, a latência **não pode acumular** — o laço principal sempre pega o mais recente
- Reconexão automática com backoff exponencial, teto de 10 s
- Só consome RTSP quando há cliente conectado em `/stream` ou coleta ativa
- Sobreposição no quadro: FPS, resolução, contador de quadros e, quando houver detecções, as caixas com classe e confiança

### 1.2 Informações de conexão

Painel abaixo do vídeo com o que o operador precisa saber para confiar no que está vendo:

| Campo | Origem |
|---|---|
| Resolução do stream | `tracks2[].codecProps` |
| Taxa (Mbps) | derivada de `bytesReceived` |
| FPS de captura | medido no leitor |
| FPS de inferência | medido no detector |
| Latência estimada | tempo entre chegada do quadro e exibição |
| Quadros perdidos | descartados pelo leitor desde o início |
| Tempo de stream | desde que o path ficou pronto |
| Modelo | nome do arquivo de pesos ou `nenhum modelo carregado` |

Se a resolução mudar durante a transmissão, **avise na tela**. Isso acontece quando a qualidade do canal está em "Automático" no FlightHub e é a causa mais comum de queda da captura.

### 1.3 Criar dataset

O núcleo desta fatia.

**Botão "Criar dataset"** com estas regras:

**Guarda de pré-condição.** Só habilita quando os quatro indicadores estiverem verdes: disponibilidade, MediaMTX, túnel e stream. Se o operador clicar com algum vermelho ou amarelo, mostre um **modal de erro** listando exatamente qual condição falhou e o que fazer:

```
Não é possível iniciar a coleta

✕ Stream — nenhum path ativo
  Confira o endereço no FlightHub e religue o toggle do canal.

✓ MediaMTX
✓ Túnel
```

Não deixe o botão clicável e falhando depois; a validação acontece antes, no cliente, e é revalidada no servidor.

**Modal de confirmação.** Ao clicar com tudo verde, abre um diálogo mostrando:

- A versão que será criada (ex.: `v0.3`)
- Intervalo de amostragem, editável
- Limite de quadros, editável
- Deduplicação de quadros quase idênticos, on/off
- Botões **Confirmar** e **Cancelar**

**Versionamento.** As pastas seguem `vMAJOR.MINOR`, com MINOR de 0 a 9 rolando para o próximo MAJOR:

```
v0.0 → v0.1 → … → v0.9 → v1.0 → v1.1 → …
```

O sistema varre `data/datasets/`, encontra a maior versão existente e cria a próxima. Primeira execução cria `v0.0`.

**Estados da coleta.** Máquina de estados explícita:

```
   ocioso
     │ Confirmar
     ▼
  gravando ⇄ pausado
     │           │
     └─── Salvar ┘
     ▼
   salvo → volta a ocioso
```

Enquanto grava, os três botões aparecem:

| Botão | Efeito |
|---|---|
| **Pausar** | para de salvar quadros; o vídeo continua exibindo; a sessão permanece aberta |
| **Continuar** | volta a salvar na mesma sessão |
| **Salvar** | encerra a sessão, dispara o split e volta ao estado ocioso |

Mostre durante a gravação: quadros salvos, tempo decorrido, espaço em disco usado, e o estado atual (gravando/pausado) de forma inequívoca.

**Amostragem:**

| Parâmetro | Opções | Padrão |
|---|---|---|
| Intervalo | 0.5 / 1 / 2 / 5 s | 2 s |
| Limite | número ou ilimitado | 500 |
| Deduplicação | on/off | on |

A deduplicação compara a diferença média absoluta com o quadro anterior salvo. Quando o drone paira, salvar 30 quadros por segundo do mesmo enquadramento infla o dataset sem adicionar informação — e distorce a distribuição de treino.

**Estrutura em disco durante a gravação:**

```
data/datasets/v0.3/
├── raw/
│   ├── 000001_t0.00.jpg
│   ├── 000002_t2.00.jpg
│   └── …
└── session.json
```

O timestamp relativo no nome não é decorativo — é o que permite o split temporal sem reabrir o banco.

Grave o `session.json` incrementalmente, para que uma queda no meio deixe a sessão consistente.

### 1.4 O split ao salvar

**Esta é a decisão técnica mais importante do sistema. Não implemente split aleatório.**

Quadros consecutivos de vídeo são quase idênticos. Um split aleatório coloca o quadro *N* em treino e o *N+1* em validação — o modelo memoriza em vez de generalizar, e a métrica de validação sobe para valores que não se sustentam em voo novo. É vazamento de dados, e é silencioso: nada no treino indica que aconteceu.

Ao clicar em **Salvar**, particione por **blocos contíguos de tempo**:

```
[──────── train 70% ────────][─ valid 15% ─][─ test 15% ─]
t=0                                                   t=fim
```

Aplique uma **margem de descarte** de N quadros nas fronteiras (padrão 5), para que o último quadro de treino e o primeiro de validação não sejam vizinhos temporais.

Resultado:

```
data/datasets/v0.3/
├── train/images/
├── valid/images/
├── test/images/
├── raw/                    (mantido para reprocessar)
├── session.json
└── split_manifest.json
```

O manifesto registra estratégia, proporções, margem aplicada, contagem por partição e o mapeamento de cada arquivo. Sem isso não há como reproduzir nem auditar o experimento depois.

---

## Tela 2 — Datasets

### 2.1 Lista

Cada dataset com: versão, data, duração da gravação, total de imagens, distribuição train/valid/test, tamanho em disco, e se já foi enviado ao Roboflow.

Ordenada da versão mais recente para a mais antiga. Clicar abre o detalhe.

### 2.2 Detalhe e galeria

Abas ou seções para **train**, **valid** e **test**, cada uma com a contagem e uma galeria em grade de miniaturas.

- Clicar numa miniatura abre a imagem em tamanho real
- Cada imagem pode ser **excluída**, com confirmação
- Seleção múltipla com exclusão em lote

!!! Ao excluir imagens depois do split, as proporções mudam. Mostre as contagens atualizadas e ofereça **refazer o split** a partir de `raw/` — por isso a pasta original é mantida.

Ofereça também excluir o dataset inteiro, com confirmação que exige digitar a versão.

### 2.3 Upload para o Roboflow

Formulário pedindo:

| Campo | Observação |
|---|---|
| API key | do `.env` se existir; **nunca** exibida em texto claro |
| Workspace | |
| Projeto | |
| Batch name | padrão: a versão do dataset |
| Tags | padrão: versão + `drone` |

**Preserve a partição no upload.** O Roboflow aceita o parâmetro `split`. Se você enviar tudo como `train` e deixar o Roboflow dividir, ele usa split aleatório e desfaz todo o cuidado da seção 1.4.

```python
for split in ("train", "valid", "test"):
    for img in sorted((base / split / "images").glob("*.jpg")):
        project.upload(
            str(img),
            split=split,
            batch_name=batch_name,
            tag_names=tags,
        )
```

Use `batch_name` e `tag_names` com a versão do dataset. Meses depois, quando alguém perguntar de qual voo veio determinada imagem, essa é a única resposta possível.

Requisitos: rode em thread separada, nunca bloqueie o event loop. Mostre progresso e permita cancelar. Registre o resultado no banco para a lista mostrar o status. Trate falha parcial — se 300 de 500 subiram, registre isso e permita retomar.

---

## Tela 3 — Modelo

Somente leitura. Mostra o desempenho do modelo atualmente carregado.

### 3.1 Métricas

Lidas de um artefato produzido pelo treino, não calculadas aqui:

- **mAP@50** e **mAP@50-95**
- **Precision** e **Recall**
- Por classe, quando disponível
- Data do treino, dataset de origem, número de épocas

O treino do YOLO grava `results.csv` e `args.yaml` em `runs/detect/<nome>/`. Leia de lá, ou de um `data/models/metrics.json` que o script de treino gere.

### 3.2 Exemplos no conjunto de teste

**Três imagens** do conjunto de teste com as predições do modelo desenhadas. Gere sob demanda, rodando o detector nas imagens de `test/images/` do dataset mais recente.

Ao lado de cada uma, as detecções: classe, confiança, contagem.

### 3.3 Estado vazio

Quando não há modelo carregado — que é o estado inicial do projeto — a tela **não pode quebrar**. Mostre:

- Que nenhum modelo está carregado
- Onde colocar os pesos (`data/models/best.pt`)
- Um link para a tela de datasets, sugerindo coletar e treinar

O mesmo vale quando há modelo mas não há métricas, ou não há dataset de teste.

---

## Pasta de treino

Crie `train/` com:

**`train/train.py`** — script de treino YOLO parametrizado por CLI:

```python
"""
Treina um modelo YOLO a partir de um dataset baixado do Roboflow.

Uso:
    python train/train.py --data caminho/data.yaml --epochs 100
"""
```

Ele deve:

- Aceitar `--data`, `--model` (padrão `yolo11n.pt`), `--epochs`, `--imgsz`, `--batch`, `--name`
- Rodar o treino via Ultralytics
- Ao final, copiar `best.pt` para `data/models/best.pt`
- Gerar `data/models/metrics.json` com mAP@50, mAP@50-95, precision, recall, por classe, data e nome do dataset — é isso que a Tela 3 lê
- Imprimir onde os arquivos foram gravados

**`train/data.yaml.example`** — exemplo do formato esperado.

**`train/README.md`** — como baixar o dataset anotado do Roboflow, rodar o treino e onde os pesos vão parar.

**`train/requirements.txt`** — `ultralytics` e dependências. Separado do `requirements.txt` principal, porque arrasta torch (~2,5 GB) e a aplicação não precisa dele para rodar em modo passthrough.

---

## Rotas

```
GET  /                              Home
GET  /datasets                      Lista
GET  /datasets/{version}            Detalhe e galeria
GET  /model                         Métricas

GET  /events                        SSE (existente, estender)
GET  /stream                        MJPEG

POST /api/pipeline/start|stop       existente
GET  /api/pipeline/status           existente

GET  /api/collect/preflight         valida as pré-condições
POST /api/collect/start             {interval, limit, dedup}
POST /api/collect/pause
POST /api/collect/resume
POST /api/collect/save              encerra e dispara o split
GET  /api/collect/status

GET  /api/datasets
GET  /api/datasets/{version}
GET  /api/datasets/{version}/images/{split}
DELETE /api/datasets/{version}
DELETE /api/datasets/{version}/images   {split, filenames[]}
POST /api/datasets/{version}/resplit

POST /api/roboflow/upload           {version, api_key, workspace, project, ...}
GET  /api/roboflow/status

GET  /api/model                     estado, métricas
POST /api/model/reload
GET  /api/model/samples             3 exemplos do teste
```

Estenda o payload do SSE com um bloco `collect` (estado, contagem, tempo) e um bloco `model` (carregado, nome).

---

## Correções pendentes

Três problemas identificados no `SPEC_ATUAL.md`, corrija junto:

1. **§8, mensagem de colisão perdida** — `{"ok": False, "error": "...", **snapshot()}` faz o `error` do snapshot sobrescrever a mensagem. Inverta a ordem das chaves.

2. **§7, path errado na reconciliação** — quando houver path ativo no MediaMTX, use o nome real dele para montar o `rtmp_url`, em vez de assumir o `STREAM_PATH` padrão. Hoje o painel pode exibir um endereço com sufixo errado, e o sufixo é a única credencial do endpoint.

3. **`requirements.txt`** — troque `opencv-python` por `opencv-python-headless`. A variante com GUI exige `libGL`, ausente em servidor limpo.

---

## Design

Escuro, denso, operacional. Mantenha o tema atual e estenda.

Navegação entre as três telas no topo, sempre visível, indicando a atual.

Estados legíveis à distância — o operador olha de relance enquanto acompanha o voo. Cor **e** texto, nunca só cor.

Rótulos pelo que o operador controla, não pela implementação: "Coletar imagens do voo", não "Ativar frame dumper".

Modais para tudo que é destrutivo ou irreversível: iniciar coleta, excluir imagens, excluir dataset, enviar ao Roboflow.

---

## Requisitos não funcionais

- Coleta nunca bloqueia a exibição — threads separadas, escrita de arquivos em thread pool
- Se o disco passar de 90%, pare a coleta e avise na interface
- `.env` no `.gitignore`; nenhuma chave em código ou em log
- `data/` no `.gitignore`
- Sessão interrompida por queda deve ficar consistente
- A aplicação sobe sem torch, sem pesos e sem datasets — todos os estados vazios tratados

---

## Ordem de implementação

Entregue em fatias funcionais, validando cada uma:

1. **MJPEG + inferência abstraída** — vídeo na Home, detector em modo passthrough, painel de conexão
2. **Coleta** — guarda, modais, máquina de estados, gravação em `raw/`
3. **Split temporal** — ao salvar, com manifesto
4. **Tela de datasets** — lista, galeria, exclusão
5. **Roboflow** — upload preservando partição
6. **Pasta train/** — script e README
7. **Tela de modelo** — métricas e exemplos

A fatia 1 já muda a experiência sozinha. As fatias 2 e 3 são o coração do sistema.

---

## Testes

Todo o desenvolvimento pode ser feito **sem drone**, com um stream sintético:

```bash
ffmpeg -re -f lavfi -i testsrc=size=960x720:rate=30 \
  -c:v libx264 -preset ultrafast -f flv rtmp://localhost:1935/live/m4td
```

Verifique especificamente:

- O split temporal não coloca quadros adjacentes em partições diferentes
- A guarda impede iniciar coleta com stream vermelho
- Pausar realmente para de gravar, e continuar retoma na mesma sessão
- A aplicação sobe e navega nas três telas **sem nenhum modelo, dataset ou torch instalado**
- Uma queda do MediaMTX durante a coleta deixa a sessão consistente

Atualize o `SPEC_ATUAL.md` ao terminar, no mesmo nível de detalhe do atual.
