# Reiniciar o pipeline

Depois que o repositório tem os scripts `start.sh` e `stop.sh`, as etapas 1 e 2 do passo a passo viram **um comando**.

```bash
./stop.sh && ./start.sh
```

Saída:

```
==> MediaMTX
    API respondendo
==> Túnel
┌──────────────────────────────────────────────────────────┐
  Cole no FlightHub → Endereço do servidor:

      rtmp://bore.pub:38828/live/m4td

  Depois: desligue e religue o toggle do canal.
└──────────────────────────────────────────────────────────┘
```

O comando é **idempotente**: pode ser executado quantas vezes for necessário. O `stop.sh` remove o container antes, então nunca aparece o erro `container name "/mtx" is already in use`.

## Onde retomar

O script cobre as etapas 1 e 2. **A etapa 3 é sempre manual** — o túnel gratuito gera uma porta nova a cada reinício, e o FlightHub precisa saber dela.

```
┌─ 1. MediaMTX ─┐
│               │ ← ./start.sh faz estas duas
└─ 2. Túnel ────┘
   3. FlightHub   ← SEMPRE manual: colar endereço + religar toggle
   4. Captura     ← reiniciar o script Python
```

## Tabela de decisão

| Sintoma | Comando | Retomar em |
|---|---|---|
| Codespace hibernou | `./stop.sh && ./start.sh` | Etapa 3 |
| Porta do bore mudou | `./stop.sh && ./start.sh` | Etapa 3 |
| Container travado | `./stop.sh && ./start.sh` | Etapa 3 |
| Rebuild do Codespace | `./start.sh` (setup é automático) | Etapa 3 |
| Container caiu, túnel vivo | `docker restart mtx` | Etapa 3 (só religar toggle) |
| `capture.py` travou | reiniciar só o script | Etapa 4 |
| Stream cai a cada 30 s | nenhum — é canal duplicado | Etapa 3 (apagar a cópia) |

!!! warning "Não reinicie por precaução"
    Cada reinício derruba a conexão da DJI e gera porta nova, criando trabalho onde não havia. Antes de reiniciar, verifique se realmente há problema:

    ```bash
    curl -s localhost:9997/v3/paths/list | python3 -m json.tool
    ```

    | Resposta | Significado |
    |---|---|
    | `"ready": true` e `bytesReceived` crescendo | Tudo certo — não reinicie |
    | `items: []` | Servidor de pé, ninguém publicando |
    | Erro de conexão | Container caído — aí sim reinicie |

    `items: []` logo após o `start.sh` é o esperado, não é falha.

## Etapa 3 em detalhe

Com o endereço novo em mãos, no portal do FlightHub:

1. Minha organização → engrenagem → FlightHub Sync → Detalhes
2. Card **Encaminhamento de transmissão ao vivo**
3. Ícone de **lápis** no canal (nunca o de copiar — [ele cria um canal novo](03-flighthub.md))
4. Cole o endereço em **Endereço do servidor**
5. Confirme
6. Desligue o toggle **Status do canal**, espere 5 s, ligue novamente

O passo 6 força a DJI a reconectar no endereço novo. Sem ele, ela continua tentando o antigo.

## Verificar que voltou

```bash
# há stream?
curl -s localhost:9997/v3/paths/list | python3 -m json.tool

# a DJI conectou?
tail -5 /tmp/bore.log

# o que o servidor viu?
docker logs --tail 20 mtx
```

Em `docker logs`, procure:

```
INF [RTMP] [conn ...] is publishing to path 'live/m4td'
```

## Parar sem reiniciar

```bash
./stop.sh
```

Encerra container e túnel. Os dados em `/workspaces` permanecem — só o pipeline para.

## Rebuild do Codespace

O `.devcontainer/setup.sh` reinstala `bore`, dependências Python e a imagem do MediaMTX automaticamente. Depois do rebuild:

```bash
./start.sh
```

!!! danger "Rebuild derruba o que está rodando"
    Para travamento, tente primeiro *Reload Window* (`Ctrl+Shift+P`), depois parar e reabrir o Codespace. Rebuild só como último recurso — ele recria o container e apaga tudo fora de `/workspaces`.

## Rotina de um voo

```bash
# 1. subir
./stop.sh && ./start.sh

# 2. colar o endereço no FlightHub e religar o toggle

# 3. confirmar
curl -s localhost:9997/v3/paths/list | python3 -m json.tool

# 4. capturar
python3 capture.py

# 5. ao terminar
./stop.sh
```
