#!/usr/bin/env bash
# Publica um stream sintético no MediaMTX local, para desenvolver sem drone.
#
#   tools/fake_stream.sh                 # 960x720 @ 30 fps em live/m4td
#   tools/fake_stream.sh 1280x720 live/m4td
#
# Trocar a resolução com o painel aberto é o jeito de testar o aviso de
# mudança de resolução da seção "Conexão".
set -euo pipefail
SIZE="${1:-960x720}"
PATH_NAME="${2:-${STREAM_PATH:-live/m4td}}"
RATE="${RATE:-30}"

echo "publicando testsrc ${SIZE}@${RATE} em rtmp://localhost:1935/${PATH_NAME}"
exec ffmpeg -hide_banner -loglevel warning -re \
  -f lavfi -i "testsrc=size=${SIZE}:rate=${RATE}" \
  -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p -g "${RATE}" \
  -f flv "rtmp://localhost:1935/${PATH_NAME}"
