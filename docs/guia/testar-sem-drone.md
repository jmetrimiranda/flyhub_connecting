# Testar sem drone

Um gerador de vídeo sintético publica direto no MediaMTX, exercitando **todo o pipeline** sem depender de voo. Mesmo caminho, mesmos protocolos, mesmo código de captura.

Isso desbloqueia o desenvolvimento: coleta de dataset, split, inferência e interface podem ser construídos e testados a qualquer hora, sem drone ligado e sem consumir cota de transmissão.

## Preparar

```bash
sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg
```

No Codespace leva cerca de um minuto — ele arrasta as bibliotecas de codec junto.

## Publicar

Com o pipeline já rodando (`./start.sh` ou botão **Iniciar pipeline**), num terminal separado:

```bash
ffmpeg -re -f lavfi -i testsrc=size=960x720:rate=30 \
       -f lavfi -i sine=frequency=1000 \
       -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p \
       -c:a aac -f flv rtmp://localhost:1935/live/m4td
```

Ele fica rodando e imprimindo `frame= ... fps= ...`. Deixe assim.

O painel deve ir para 🟢 em poucos segundos:

```
🟢 Recebendo — 960×720 · 0.35 Mbps
```

Aperte `q` no terminal do ffmpeg para encerrar.

## Por que esses parâmetros

| Flag | Motivo |
|---|---|
| `-re` | Publica em tempo real, não o mais rápido possível — simula a cadência de um drone |
| `testsrc` | Padrão colorido com contador de quadros, útil para medir latência a olho |
| `size=960x720` | Mesma resolução que o Matrice entrega em qualidade "Suave" |
| `sine` + `-c:a aac` | Reproduz a trilha de áudio que a DJI envia junto |
| `-preset ultrafast -tune zerolatency` | Encode leve, sem buffer — o Codespace não tem CPU sobrando |

A trilha de áudio parece supérflua, mas reproduz o cenário real: o stream da DJI vem com AAC 44.1 kHz que o OpenCV ignora. Se o seu código quebrar com áudio presente, é melhor descobrir aqui.

## Variações úteis

**Vídeo real em loop** — mais representativo que o padrão colorido:

```bash
ffmpeg -re -stream_loop -1 -i voo_gravado.mp4 -c copy \
  -f flv rtmp://localhost:1935/live/m4td
```

`-c copy` evita reencode, então gasta quase nada de CPU. Grave um trecho de voo real uma vez e reutilize sempre.

**Gravar um trecho do drone para reutilizar:**

```bash
ffmpeg -i rtsp://localhost:8554/live/m4td -t 120 -c copy voo_gravado.mp4
```

**Simular queda de conexão** — para testar a lógica de reconexão:

```bash
timeout 30 ffmpeg -re -f lavfi -i testsrc=size=960x720:rate=30 \
  -c:v libx264 -preset ultrafast -f flv rtmp://localhost:1935/live/m4td
```

Publica por 30 s e corta. O painel deve passar a 🟡 e depois 🔴, e o `capture.py` deve tentar reconectar.

**Simular mudança de resolução** — reproduz o problema da qualidade "Automático":

```bash
# primeiro em 960x720, depois mate e suba em 1280x720
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 \
  -c:v libx264 -preset ultrafast -f flv rtmp://localhost:1935/live/m4td
```

## Antes de voltar ao drone

!!! danger "Encerre o ffmpeg"
    Se o gerador continuar publicando quando o drone conectar, haverá **dois publishers no mesmo path** — eles se derrubam mutuamente e a conexão cai a cada poucos segundos.

    ```bash
    pkill ffmpeg
    ```

    Confirme nos logs que não há briga:

    ```bash
    docker logs --tail 20 mtx | grep "closing existing publisher"
    ```

## Usar um path separado

Para evitar o conflito de vez, publique o teste em outro path:

```bash
ffmpeg -re -f lavfi -i testsrc=size=960x720:rate=30 \
  -c:v libx264 -preset ultrafast -f flv rtmp://localhost:1935/live/teste
```

E consuma com:

```bash
STREAM_URL=rtsp://localhost:8554/live/teste python3 capture.py
```

Assim o teste e o drone coexistem — o MediaMTX aceita quantos paths você quiser, e o painel lista todos na tabela.
