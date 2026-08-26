#!/usr/bin/env bash
# Publica um vídeo no MediaMTX local, para testar sem drone.
#
#   ./tools/fake_stream.sh                      padrão colorido de teste
#   ./tools/fake_stream.sh voo.mp4              seu vídeo, em loop
#   ./tools/fake_stream.sh voo.mp4 --copy       sem reencode (mais leve)
#   STREAM_PATH=live/teste ./tools/fake_stream.sh voo.mp4
set -euo pipefail

VIDEO="${1:-}"
MODE="${2:-}"
PATH_NAME="${STREAM_PATH:-live/m4td}"
URL="rtmp://localhost:1935/${PATH_NAME}"

command -v ffmpeg >/dev/null || {
  echo "ffmpeg não encontrado. Instale com:"
  echo "  sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg"
  exit 1
}

if [ -z "$VIDEO" ]; then
  echo "padrão de teste 960x720@30 → $URL"
  echo "(Ctrl+C para parar)"
  exec ffmpeg -hide_banner -loglevel warning -re \
    -f lavfi -i testsrc=size=960x720:rate=30 \
    -f lavfi -i sine=frequency=1000 \
    -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p \
    -c:a aac -f flv "$URL"
fi

[ -f "$VIDEO" ] || { echo "arquivo não encontrado: $VIDEO"; exit 1; }

RES=$(ffprobe -v error -select_streams v:0 \
      -show_entries stream=width,height -of csv=s=x:p=0 "$VIDEO" 2>/dev/null || echo "?")
echo "publicando $VIDEO ($RES) em loop → $URL"
echo "(Ctrl+C para parar)"

if [ "$MODE" = "--copy" ]; then
  # Sem reencode: quase zero CPU, mas exige que o vídeo já seja H.264.
  exec ffmpeg -hide_banner -loglevel warning -re -stream_loop -1 \
    -i "$VIDEO" -c copy -f flv "$URL"
fi

# Reencode: funciona com qualquer formato de entrada.
exec ffmpeg -hide_banner -loglevel warning -re -stream_loop -1 \
  -i "$VIDEO" \
  -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p \
  -c:a aac -f flv "$URL"
