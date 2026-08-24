# 1. Servidor de mídia

O MediaMTX recebe a publicação RTMP da DJI e a republica em RTSP para o OpenCV.

**Onde:** no servidor (Codespace, VM ou máquina local).

## Modo rápido

```bash
docker run -d --name mtx --restart unless-stopped \
  -e MTX_API=yes \
  -e MTX_AUTHINTERNALUSERS_0_USER=any \
  -e MTX_AUTHINTERNALUSERS_0_IPS= \
  -e MTX_AUTHINTERNALUSERS_0_PERMISSIONS_0_ACTION=publish \
  -e MTX_AUTHINTERNALUSERS_1_USER=any \
  -e MTX_AUTHINTERNALUSERS_1_IPS= \
  -e MTX_AUTHINTERNALUSERS_1_PERMISSIONS_0_ACTION=read \
  -e MTX_AUTHINTERNALUSERS_1_PERMISSIONS_1_ACTION=api \
  -p 1935:1935 -p 8554:8554 -p 8888:8888 -p 9997:9997 \
  bluenviron/mediamtx:latest
```

Verifique:

```bash
sleep 3
curl -s localhost:9997/v3/paths/list
```

Resposta esperada: `{"itemCount":0,"pageCount":0,"items":[]}`

Lista vazia é o correto neste momento — o servidor está de pé e ninguém publicou ainda.

## Modo recomendado: arquivo de configuração

Mais legível e versionável. Crie `mediamtx.yml`:

```yaml
logLevel: info

# Ingestão — é aqui que a DJI publica
rtmp: yes
rtmpAddress: :1935

# Consumo pelo OpenCV
rtsp: yes
rtspAddress: :8554
rtspTransports: [tcp]

# Visualização em navegador
hls: yes
hlsAddress: :8888
hlsVariant: lowLatency
hlsPartDuration: 200ms
hlsSegmentDuration: 1s

# API de status
api: yes
apiAddress: :9997

# Protocolos não usados — desligados para poupar CPU
webrtc: no
srt: no

authInternalUsers:
  - user: any
    ips: []
    permissions:
      - action: publish
      - action: read
      - action: playback
      - action: api
      - action: metrics

paths:
  all_others:
```

Suba com o volume montado:

```bash
docker rm -f mtx 2>/dev/null
docker run -d --name mtx --restart unless-stopped \
  -v $PWD/mediamtx.yml:/mediamtx.yml \
  -p 1935:1935 -p 8554:8554 -p 8888:8888 -p 9997:9997 \
  bluenviron/mediamtx:latest
```

## Erros comuns nesta etapa

**`{"status":"error","error":"authentication error"}`**
Versões recentes exigem permissão explícita até para leitura interna. Use o bloco `authInternalUsers` acima.

**Resposta vazia no `curl`**
A API vem desabilitada por padrão. Faltou `api: yes` ou `MTX_API=yes`.

**`docker: command not found`**
Sem Docker no ambiente. Baixe o binário direto:

```bash
URL=$(curl -s https://api.github.com/repos/bluenviron/mediamtx/releases/latest \
  | grep browser_download_url | grep linux_amd64 | cut -d '"' -f 4)
curl -sL "$URL" | tar xz
./mediamtx
```

## Verificação final

```bash
docker logs mtx
```

Deve mostrar listeners ativos em 1935 (RTMP), 8554 (RTSP), 8888 (HLS) e 9997 (API).

→ [Próximo: abrir o túnel](02-tunel.md)
