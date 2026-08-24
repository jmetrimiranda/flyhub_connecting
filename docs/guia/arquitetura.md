# Arquitetura

## O caminho do quadro

Um quadro de vídeo sai do sensor da câmera e percorre seis saltos até chegar ao `frame` do Python:

```
┌─────────────┐
│ Matrice 4TD │  câmera Carga-zoom, H.264
└──────┬──────┘
       │ enlace de rádio / 4G
┌──────▼──────────┐
│  FlightHub 2    │  nuvem DJI, transcodifica e encaminha
└──────┬──────────┘
       │ RTMP push  ← a DJI inicia esta conexão
┌──────▼──────────┐
│  Túnel público  │  bore.pub / playit / IP público direto
└──────┬──────────┘
       │ TCP 1935
┌──────▼──────────┐
│    MediaMTX     │  recebe RTMP, republica em RTSP/HLS/WebRTC
└──────┬──────────┘
       │ RTSP 8554
┌──────▼──────────┐
│  OpenCV / PyAV  │  decodifica em ndarray BGR
└──────┬──────────┘
       │
┌──────▼──────────┐
│  Rede neural    │
└─────────────────┘
```

## Por que cada peça existe

**FlightHub Sync — Encaminhamento de transmissão ao vivo.** É a saída oficial da DJI para terceiros. Você registra um endereço RTMP e a nuvem passa a publicar ali sempre que o dispositivo estiver online e o canal habilitado.

**Túnel.** Existe apenas porque a DJI precisa alcançar seu servidor. Em produção com IP público, some.

**MediaMTX.** Faz a ponte de protocolo. O FlightHub só publica RTMP ou RTSP; o OpenCV consome bem RTSP. O MediaMTX aceita a publicação e republica em vários protocolos ao mesmo tempo, permitindo que o script Python, um dashboard HLS e uma gravação consumam o mesmo stream sem multiplicar a carga na nuvem da DJI.

**OpenCV.** Decodifica H.264 em array NumPy.

## Modos de operação

=== "Desenvolvimento"

    Codespace + bore.pub. Zero custo, zero fricção com TI, endereço muda a cada reinício.

    ```
    Codespace ──bore──> bore.pub:PORTA <──RTMP── DJI
    ```

=== "Produção"

    VM em nuvem com IP fixo, mesma VNet do Databricks.

    ```
    VM Azure (IP público) <──RTMP── DJI
         │
         └──RTSP privado──> inferência ──> Delta / ADLS
    ```

A troca entre os dois é uma string: o endereço no campo "Endereço do servidor" do canal.

## O que consome cota

Segundo a documentação da DJI, o encaminhamento via FlightHub Sync conta como consumo de minutos de transmissão — igual a assistir pela interface. Em planos Enterprise com minutos ilimitados isso é irrelevante; em planos por minuto, desligue o canal quando não estiver usando.

!!! danger "Um publisher por path"
    Dois canais apontando para o mesmo path RTMP se derrubam mutuamente. O MediaMTX registra `closing existing publisher` e a conexão cai a cada poucos segundos. Se você duplicou um canal para editar, **apague a cópia**.
