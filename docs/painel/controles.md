# Referência dos controles

Cada elemento da tela, o que dispara e quando fica indisponível.

## Barra de estado

Quatro cartões fixos no topo. **Nenhum é clicável** — são indicadores. A cor nunca aparece sozinha; sempre acompanha texto, para ser legível à distância e por quem não distingue cores.

| Cartão | Valores possíveis | Regra da cor |
|---|---|---|
| **Disponibilidade** | o rótulo do semáforo (ver abaixo) | igual ao semáforo |
| **MediaMTX** | `Parado` · `No ar` · `Container no ar, API muda` | 🔴 container parado · 🟢 container no ar **e** API respondendo · 🟡 container no ar e API muda |
| **Túnel** | `Parado` · `bore.pub:49934` · `Subindo…` | 🔴 sem processo · 🟢 processo com endereço · 🟡 processo sem endereço ainda |
| **Stream** | nomes dos paths ou `Nenhum path ativo` | igual ao semáforo |

À direita, fora dos cartões: `SSE: conectando` → `SSE: conectado` → `SSE: reconectando…`.

Antes do primeiro frame, as bolinhas ficam cinza e os valores em `—`.

O estado `Container no ar, API muda` merece atenção: significa que o Docker diz que o container existe, mas a porta 9997 não responde. Normalmente indica que o MediaMTX subiu e morreu, ou que o `mediamtx.yml` tem erro. Confira com `docker logs mtx`.

## Elementos clicáveis

São quatro.

### Iniciar pipeline

Dispara `POST /api/pipeline/start` com corpo vazio — a interface **sempre usa o path padrão do servidor**, não envia `stream_path`.

Desabilita quando há um POST em voo ou quando `pipeline.busy` é verdadeiro. Ao chegar a resposta, a tela redesenha com o relatório de passos preenchido.

### Parar pipeline

Dispara `POST /api/pipeline/stop`. Mesmas regras de desabilitação.

!!! warning "Sem confirmação e sem proteção"
    Não há diálogo de confirmação, e o botão não fica bloqueado quando há stream ativo. Um clique acidental durante um voo derruba a captura e gera porta nova — obrigando a reeditar o canal no FlightHub.

### Copiar

Copia `rtmp_url` para a área de transferência.

| Estado | Quando |
|---|---|
| `Copiar` | normal |
| `Copiado` | por 1800 ms após sucesso, com fundo verde |
| `Falhou` | erro na cópia — **não se recupera sozinho** |
| desabilitado | sempre que `rtmp_url` for nulo, ou seja, sem túnel vivo |

Se ficar em `Falhou`, só volta ao normal quando o endereço mudar. A alternativa é clicar no campo do endereço, que tem `user-select: all` — um clique seleciona tudo, `Ctrl+C` copia.

O motivo do `Falhou` é quase sempre contexto inseguro: a Clipboard API exige HTTPS, e um Codespace acessado por HTTP simples cai num fallback com API obsoleta.

### Abrir FlightHub 2

Link em nova aba, junto do texto que explica que resolução e bitrate saem do encoder da aeronave e **não têm controle no painel**.

## Campo do endereço RTMP

Não é um input — é um bloco de código selecionável inteiro com um clique.

| Estado | Aparência |
|---|---|
| Sem túnel | `pipeline parado`, cinza |
| Com túnel | URL completo, verde com borda esverdeada |

Abaixo, aviso permanente em amarelo lembrando que o endereço muda a cada reinício e exige reeditar o canal **e** religar o toggle.

## Relatório de passos

| Marcador | Status | Aparência |
|---|---|---|
| `✓` | `ok` | verde |
| `✕` | `error` | vermelho |
| `…` | `running` | amarelo |
| `·` | `pending` / `skipped` | linha a 45% de opacidade |

!!! danger "O relatório é histórico, não estado atual"
    `steps` descreve o **último** start ou stop e não é invalidado depois. Os quatro passos podem estar verdes enquanto o MediaMTX está morto.

    Quem informa o estado agora é o **cartão MediaMTX** e o **semáforo** — não a lista de passos.

Abaixo da lista, uma caixa vermelha aparece quando há erro de pipeline ou de stream (o do pipeline tem precedência).

## Tabela de paths

Fica oculta quando não há path ativo. Colunas: `Path`, `Pronto`, `Resolução`, `Taxa`, `Codecs`, `Parado há`.

Um path com `Pronto: não` aparece aqui, mas conta como "Sem stream" no semáforo.

## O semáforo

Avaliado a cada ciclo de polling (2 s). A **primeira regra que casar decide**:

| # | Condição | Cor | Rótulo |
|---|---|---|---|
| 1 | API não responde | 🔴 | `MediaMTX não responde` |
| 2 | nenhum path com `ready: true` | 🔴 | `Sem stream` |
| 3 | path pronto, parado há menos de 10 s, com taxa acima de zero | 🟢 | `Recebendo — 960×720 · 0.34 Mbps` |
| 4 | há path pronto mas nenhum satisfaz a regra 3 | 🟡 | `Conectado, sem dados há 14s` |

Quando várias opções existem, a regra 3 escolhe o path de **maior taxa** e a regra 4 o de **maior tempo parado**.

### Como a taxa é medida

Não vem do MediaMTX — é derivada local da variação de `bytesReceived`, com média exponencial de fator 0,5, em **megabits decimais** por segundo.

Três consequências que confundem quem não sabe:

- **O primeiro ciclo de um path sempre dá 0,00 Mbps** — não há amostra anterior para derivar. Por isso o painel pode piscar `Conectado, sem dados há 0s` por ~2 s antes de ficar verde.
- **A taxa não cai a zero instantaneamente** quando o fluxo para: decai pela metade a cada ciclo, levando ~4–6 s para convergir.
- **`Parado há`** conta desde o último ciclo em que chegaram bytes novos, não desde o início do path.

### Por que o limiar de 10 s

Ele não serve para atrasar a passagem ao amarelo — essa acontece assim que a taxa arredonda para zero. Serve no sentido oposto: impede que uma oscilação momentânea da taxa derrube o verde enquanto ainda chegam bytes.

## Os passos do start

| # | Passo | O que faz | Timeout |
|---|---|---|---|
| 1 | `MediaMTX` | valida o config, remove o container antigo, sobe o novo | 180 s |
| 2 | `API` | tenta a API a cada 1 s até responder | 15 s |
| 3 | `Túnel` | encerra bore antigo, zera o log, sobe o novo | — |
| 4 | `Endereço` | lê o log procurando o endereço | 20 s |

Um start bem-sucedido leva cerca de **1,6 s** com a imagem já em cache.

**Quando um passo falha:** a sequência para. O passo vira `✕`, os seguintes viram `skipped`, e a resposta HTTP é **200 com `ok: false`** — não um código de erro.

!!! warning "Não há rollback"
    Se o passo 4 falhar, o container do passo 1 continua no ar e o bore do passo 3 continua vivo. A recuperação é clicar em parar e iniciar de novo.

A validação do arquivo de config acontece **antes** de remover o container — então esse erro específico não derruba um pipeline que já estava funcionando.

### Passos do stop

Ordem inversa: `Túnel` e depois `MediaMTX`. O detalhe é `encerrado` ou `já estava parado`. Parar duas vezes é seguro.

## Variáveis de ambiente

Lidas **na importação do módulo** — mudar exige reiniciar o painel. O `.env` do repositório **não** é carregado.

| Variável | Padrão | Efeito |
|---|---|---|
| `STREAM_PATH` | `live/m4td` | path usado nos URLs |
| `MEDIAMTX_API` | `http://localhost:9997` | base da API |
| `BORE_TO` | `bore.pub` | destino do túnel |
| `PANEL_PORT` | `8080` | porta do uvicorn |

Fixos no código: nome do container (`mtx`), imagem, portas publicadas, caminho do config, log do túnel, intervalos de 2 s e limiar de 10 s.
