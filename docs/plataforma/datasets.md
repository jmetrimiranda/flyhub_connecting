# Tela Datasets

Gerenciar as coletas: ver, limpar, reparticionar e enviar ao Roboflow.

## Lista

| Coluna | Origem |
|---|---|
| Versão | nome da pasta |
| Data | início da gravação |
| Duração | do `session.json` |
| Imagens | contagem no disco, na hora |
| Distribuição | barra train/valid/test |
| Disco | tamanho do diretório |
| Roboflow | nunca enviado / parcial / enviado |

Ordenada da mais recente para a mais antiga.

!!! note "As contagens vêm do disco, não do manifesto"
    Isso é deliberado. O manifesto registra **o que o split decidiu**; o disco mostra **o que existe agora**. Quando divergem, a tela mostra a divergência em vez de escondê-la.

## Detalhe e galeria

Abas para **train**, **valid** e **test**, cada uma com contagem e grade de miniaturas.

As miniaturas são redimensionadas no servidor (240×180, ~8 KB) e cacheadas — mandar o JPEG inteiro 200 vezes travaria a página.

Clique abre em tamanho real. Seleção múltipla permite exclusão em lote.

Cada miniatura já enviada ao Roboflow ganha um selo **enviada**.

## Excluir imagens

A exclusão remove o arquivo **da partição e de `raw/`**. É irreversível.

!!! warning "Por que apaga de raw/ também"
    Se a exclusão tirasse a imagem só de `train/images/`, o botão "Refazer o split" — oferecido justamente porque as proporções mudaram — ressuscitaria tudo.

    Você apagaria 14 quadros borrados, clicaria em refazer para corrigir a proporção, e os 14 voltariam.

    A exclusão cobre o caso real: "este quadro não presta". Quem quer outra distribuição não exclui imagem — refaz o split.

Se alguma das imagens já subiu ao Roboflow, o modal avisa:

```
3 destas já foram enviadas ao Roboflow. Excluir aqui não remove de lá —
faça isso pela interface do Roboflow se necessário.
```

Nada é consultado ou apagado via API. O Roboflow é a fonte de verdade para o que está lá.

## Manifesto desatualizado

Depois de excluir, aparece:

```
! Manifesto desatualizado
  train  82 → 68  (−14)     Proporção agora: 75,6 / 10,0 / 14,4%
  valid   9 →  9            o manifesto registra 78,8 / 8,7 / 12,5%
  test   13 → 13            [ Refazer o split a partir de raw/ ]
```

O manifesto **não é reescrito** a cada exclusão. Se fosse, deixaria de registrar o que o split fez e passaria a registrar o que sobrou — e aí não haveria como reproduzir nem auditar o experimento.

## Histórico

`edits.json`, append-only, liga o manifesto antigo ao estado atual:

```
1. Split refeito       26/08/2026, 12:32
   margem 5 · 56 / 3 / 8
2. Exclusão de imagens 26/08/2026, 12:32
   3 de train · 3 também de raw/ · 3 já estavam no Roboflow
3. Split refeito       26/08/2026, 12:32
   margem 5 · 58 / 4 / 8
```

Sem isso, a diferença entre 82 e 68 não tem explicação daqui a três meses.

## Refazer o split

Reparticiona a partir do `raw/` atual. As três pastas são apagadas e reescritas, e o manifesto é substituído.

Três contadores distinguem por que um quadro saiu de uma partição:

| Contador | Significa |
|---|---|
| `deleted_after_upload` | fora das partições **e** de `raw/` — foi excluída |
| `discarded_after_upload` | fora das partições mas **em** `raw/` — caiu na margem |
| `resplit_after_upload` | numa partição diferente daquela em que subiu |

Contá-los juntos reportaria um resplit rotineiro como exclusão em massa.

## Enviar ao Roboflow

| Campo | Observação |
|---|---|
| Workspace | do URL do projeto |
| Projeto | do URL do projeto |
| Batch | padrão: a versão |
| Tags | padrão: versão + `drone` |
| API key | do `.env` ou digitada; nunca exibida |

O URL do projeto tem os dois primeiros:

```
https://app.roboflow.com/robotdog-5oy4l/teste-v52z4/upload
                         └── workspace ─┘└─ projeto ─┘
```

!!! danger "A partição é preservada no upload"
    Cada imagem sobe com o parâmetro `split=`. Se subissem todas como `train` e o Roboflow dividisse, ele usaria split aleatório — e todo o cuidado do split temporal seria desfeito.

    Se o SDK recusar o parâmetro, o envio aborta no primeiro arquivo em vez de subir sem ele.

O envio roda em thread separada, mostra progresso e permite cancelar. Falha parcial é registrada: se 300 de 500 subiram, a lista mostra e permite retomar de onde parou.

A chave nunca é gravada em `roboflow.json`, nem aparece em log.

### Guarda durante o envio

Enquanto houver envio em andamento para uma versão, a exclusão de imagens, a exclusão do dataset e o resplit são recusados. Outra versão não é bloqueada.

## Excluir o dataset

Apaga `raw/`, as três partições, o manifesto e o histórico. Exige digitar a versão para confirmar.
