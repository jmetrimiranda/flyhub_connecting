# Tela Home

Operação em tempo real: ver o vídeo, acompanhar a conexão e coletar imagens.

## Barra de estado

Quatro cartões não clicáveis. A cor nunca aparece sozinha — sempre com texto.

| Cartão | Valores | Regra da cor |
|---|---|---|
| **Disponibilidade** | rótulo do semáforo | ver abaixo |
| **MediaMTX** | `Parado` · `No ar` · `Container no ar, API muda` | 🔴 parado · 🟢 no ar e respondendo · 🟡 no ar mas API muda |
| **Túnel** | `não usado (IP direto)` · endereço · `Parado` | ⬜ cinza com `PUBLIC_HOST` · 🟢 túnel ativo · 🔴 esperado e falhou |
| **Stream** | nomes dos paths | igual ao semáforo |

À direita: o indicador do SSE. Se ficar em `reconectando…`, a tela está congelada — o dado que você vê é o último recebido.

### O semáforo

Avaliado a cada 2 s. A primeira regra que casar decide:

| # | Condição | Cor | Rótulo |
|---|---|---|---|
| 1 | API não responde | 🔴 | `MediaMTX não responde` |
| 2 | nenhum path pronto | 🔴 | `Sem stream` |
| 3 | path pronto, parado há <10 s, taxa >0 | 🟢 | `Recebendo — 960×720 · 0.38 Mbps` |
| 4 | há path pronto mas nenhum satisfaz 3 | 🟡 | `Conectado, sem dados há 14s` |

A taxa é derivada localmente da variação de `bytesReceived`, com média exponencial. Três consequências:

- **O primeiro ciclo sempre dá 0,00 Mbps** — não há amostra anterior. Por isso pode piscar amarelo por ~2 s antes de ficar verde
- **Não cai a zero instantaneamente** quando o fluxo para: decai pela metade a cada ciclo
- **`Parado há`** conta desde o último ciclo com bytes novos, não desde o início do path

## Vídeo

MJPEG com as detecções desenhadas. No canto, um badge indica sempre qual modo está ativo:

- **MODELO ATIVO — best.pt · N classes** (verde)
- **SEM MODELO — vídeo cru, sem detecções** (âmbar)

Nunca some em silêncio. Se você vê vídeo sem caixas, o badge diz se é porque não há modelo ou porque o modelo não detectou nada.

## Painel de conexão

| Campo | O que significa |
|---|---|
| Resolução do stream | Do `codecProps` do MediaMTX |
| Taxa | Derivada de `bytesReceived` |
| FPS de captura | Quadros lidos do RTSP por segundo |
| FPS de inferência | Quadros processados por segundo |
| Latência estimada | Entre chegada do quadro e exibição |
| Quadros perdidos | Descartados pelo slot desde o início |
| Tempo de stream | Desde que o path ficou pronto |
| Modelo | Nome dos pesos ou "nenhum modelo carregado" |

Se a resolução mudar durante a transmissão, aparece um banner de aviso. Isso acontece com qualidade "Automático" no FlightHub e é a causa mais comum de queda da captura.

**FPS de captura muito maior que FPS de inferência** é normal com modelo carregado — significa que o slot está descartando quadros para manter a latência constante. É o comportamento desejado.

## Controles do pipeline

| Botão | Ação | Desabilitado quando |
|---|---|---|
| **Iniciar pipeline** | sobe MediaMTX (e túnel, se aplicável) | operação em andamento |
| **Parar pipeline** | derruba os dois | operação em andamento |
| **Copiar** | copia o endereço RTMP | sem endereço disponível |

!!! warning "Parar não pede confirmação"
    Não há diálogo, e o botão não fica bloqueado com stream ativo. Um clique acidental durante um voo derruba a captura.

### Relatório de passos

| Marcador | Status |
|---|---|
| `✓` | ok |
| `✕` | erro |
| `…` | em execução |
| `·` | pendente ou pulado |

!!! danger "O relatório é histórico, não estado atual"
    `steps` descreve o **último** start ou stop e não é invalidado depois. Os passos podem estar todos verdes enquanto o MediaMTX está morto.

    Quem informa o agora é o cartão MediaMTX e o semáforo.

## Coleta de imagens

O botão **Coletar imagens do voo** só habilita com as pré-condições atendidas: MediaMTX no ar, stream pronto e disco com espaço.

O túnel **não** é pré-condição — a coleta grava do stream local, independente de como ele chegou.

Clicar sem as condições abre um modal listando exatamente o que falta.

### Confirmação

O diálogo mostra a versão que será criada e permite ajustar:

| Parâmetro | Opções | Padrão |
|---|---|---|
| Intervalo | 0.5 / 1 / 2 / 5 s | 2 s |
| Limite | número ou ilimitado | 500 |
| Dedup | on/off | on |

### Versionamento

```
v0.0 → v0.1 → … → v0.9 → v1.0 → v1.1 → …
```

O sistema varre `data/datasets/`, encontra a maior versão e cria a próxima.

### Durante a gravação

| Botão | Efeito |
|---|---|
| **Pausar** | para de salvar; o vídeo continua; a sessão permanece aberta |
| **Continuar** | volta a salvar na mesma sessão, com o índice de onde parou |
| **Salvar** | encerra, dispara o split, volta ao estado ocioso |

A tela mostra quadros salvos, tempo decorrido, espaço usado e o estado atual.

**Auto-pausa** acontece em dois casos: limite de quadros atingido e disco acima de 90%. Nunca auto-salva — salvar dispara o split, e essa decisão é do operador.

### Ao salvar

O split roda em thread separada. Durante isso o estado é `salvando` e a tela reflete o progresso.

O resumo mostra as contagens e os avisos. Preste atenção neles:

```
✕ Apenas 8 quadro(s) coletado(s) — menos que o mínimo de 10 para
  particionar. Tudo foi para train: este dataset não tem valid nem
  test e não serve para medir o modelo.
```

## Modelo

O card mostra onde a aplicação procura os pesos e o estado atual. O botão **Recarregar pesos** força a releitura.

Normalmente não é necessário: a aplicação detecta arquivo novo pelo mtime e recarrega sozinha, sem reiniciar o processo.
