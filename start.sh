#!/usr/bin/env bash
# Sobe MediaMTX + túnel e imprime o endereço RTMP para colar no FlightHub.
set -euo pipefail

PATH_NAME="${STREAM_PATH:-live/m4td}"

echo "==> MediaMTX"
docker rm -f mtx >/dev/null 2>&1 || true
docker run -d --name mtx --restart unless-stopped \
  -v "$PWD/config/mediamtx.yml:/mediamtx.yml" \
  -p 1935:1935 -p 8554:8554 -p 8888:8888 -p 9997:9997 \
  bluenviron/mediamtx:latest >/dev/null

for i in $(seq 1 15); do
  curl -sf localhost:9997/v3/paths/list >/dev/null 2>&1 && break
  sleep 1
done
curl -sf localhost:9997/v3/paths/list >/dev/null || {
  echo "ERRO: API não respondeu. Veja: docker logs mtx"; exit 1; }
echo "    API respondendo"

echo "==> Túnel"
pkill -f "bore local" 2>/dev/null || true
nohup bore local 1935 --to bore.pub > /tmp/bore.log 2>&1 &

ADDR=""
for i in $(seq 1 20); do
  ADDR=$(grep -oP 'listening at \K\S+' /tmp/bore.log 2>/dev/null | tail -1 || true)
  [ -n "$ADDR" ] && break
  sleep 1
done
[ -n "$ADDR" ] || { echo "ERRO: túnel não subiu. Veja /tmp/bore.log"; exit 1; }

cat <<EOF

┌──────────────────────────────────────────────────────────┐
  Cole no FlightHub → Endereço do servidor:

      rtmp://${ADDR}/${PATH_NAME}

  Depois: desligue e religue o toggle do canal.
└──────────────────────────────────────────────────────────┘

  Consumo OpenCV : rtsp://localhost:8554/${PATH_NAME}
  Player HLS     : porta 8888, path /${PATH_NAME}
  Status         : curl -s localhost:9997/v3/paths/list | python3 -m json.tool
  Logs do túnel  : tail -f /tmp/bore.log

EOF
