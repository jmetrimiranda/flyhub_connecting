# Painel de controle

Interface web que substitui os comandos de terminal das etapas 1 e 2, e mostra em tempo real se há voo disponível para capturar.

O problema que ele resolve: o túnel gratuito gera **uma porta nova a cada reinício**. Sem o painel, isso significa abrir o terminal, ler a saída do `start.sh`, selecionar o endereço e copiar à mão — várias vezes por dia.

## Subir

```bash
./run.sh
```

Sobe o uvicorn na porta **8080**. O padrão não é 8000 porque essa costuma estar ocupada pelo `mkdocs serve` deste mesmo repositório.

```bash
PANEL_PORT=9000 ./run.sh     # outra porta
```

No Codespaces, a porta é detectada automaticamente e aparece na aba **PORTS**.

!!! tip "Pode subir com o pipeline já rodando"
    O painel não guarda estado próprio — ele **mede o sistema** a cada consulta. Se você já tinha subido tudo pelo `start.sh`, ele detecta o container, o túnel e recupera o endereço RTMP sozinho. Não precisa parar nada nem clicar em iniciar.

## Fluxo de informação

Duas correntes independentes alimentam a tela:

```
                    ┌─────────────────────────────────────┐
                    │            NAVEGADOR                │
                    │                                     │
                    │   EventSource ──── POST ────┐       │
                    └────────▲────────────────────┼───────┘
                             │ data: {...}        │
                             │ a cada 2 s         │
                    ┌────────┴────────────────────▼───────┐
                    │           FastAPI (app/main.py)     │
                    │                                     │
                    │   GET /events        POST /start    │
                    │        │                  │         │
                    │        │ _state()         │ threadpool
                    │        ▼                  ▼         │
                    └────┬──────────────────┬─────────────┘
                         │                  │
              ┌──────────▼──────┐  ┌────────▼─────────┐
              │   monitor.py    │  │   pipeline.py    │
              │                 │  │                  │
              │ thread, poll 2s │  │ docker / bore    │
              │ cache do último │  │ medido na hora   │
              │ resultado       │  │                  │
              └────────┬────────┘  └────────┬─────────┘
                       │                    │
              GET /v3/paths/list      docker inspect
              (timeout 1,5 s)         pgrep bore
                       │              /tmp/bore.log
                       ▼                    ▼
                  ┌─────────┐         ┌──────────┐
                  │ MediaMTX│         │  Sistema │
                  └─────────┘         └──────────┘
```

**Corrente do `stream`** — uma thread faz polling da API do MediaMTX a cada 2 s e guarda o resultado em memória. O SSE apenas lê esse cache.

**Corrente do `pipeline`** — medida na hora, a cada emissão do SSE, com `docker inspect` e `pgrep`.

Consequência prática: o bloco `stream` pode ter até ~2 s de idade **além** do intervalo do SSE. Na pior das hipóteses, você vê um dado de 4 s atrás. Para operação de drone isso é irrelevante, mas ajuda a entender por que o semáforo às vezes demora um piscar a mudar.

## As duas cadências

| | Origem | Frequência | Frescor |
|---|---|---|---|
| `pipeline` | medido na hora | a cada emissão SSE | atual |
| `stream` | cache da thread | polling de 2 s | até 2 s de atraso |

O SSE emite o **primeiro frame imediatamente** na conexão — não há espera inicial. Intervalos medidos entre emissões: 2,03 s.

## Reconexão

O cliente usa `EventSource`, que reconecta sozinho (~3 s, padrão do navegador). O servidor não envia diretiva `retry:` nem `id:`, então não há replay de eventos perdidos — ao voltar, você recebe o estado atual.

Durante a queda, o indicador no canto direito passa a `SSE: reconectando…` em vermelho e **a última tela fica congelada**. Não há indicação de idade do dado além desse rótulo — se a tela parecer estática, confira esse indicador antes de suspeitar do pipeline.

## O que ainda não faz

As fatias 3 a 6 da especificação não estão implementadas:

- `/stream` — visualização MJPEG com a saída da rede neural
- Coleta de frames e sessões
- Split temporal e export
- Roboflow
- Formulário de configurações (path aleatório, transporte, resolução, FPS)

O `config/mediamtx.yml` é usado **como está** — o painel ainda não o gera dinamicamente.

E, por definição, o painel não toca no FlightHub: editar o canal e religar o toggle continuam manuais.

→ [Referência dos controles](controles.md) · [API e SSE](api.md)
