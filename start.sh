#!/usr/bin/env bash
# Sobe MediaMTX (e o túnel, se for preciso) e imprime o endereço RTMP para
# colar no FlightHub.
#
# O túnel só existe para dar um endereço alcançável a uma máquina sem IP
# público. Defina PUBLIC_HOST=<ip-ou-host> quando a máquina já for alcançável:
# o bore é pulado e o endereço é montado direto. Sem PUBLIC_HOST o túnel é
# tentado, mas falhar nele não interrompe o script — o MediaMTX no ar já basta
# para receber stream e gravar imagens.
set -euo pipefail

PATH_NAME="${STREAM_PATH:-live/m4td}"
PUBLIC_HOST="${PUBLIC_HOST:-}"
RTMP_PORT="${RTMP_PORT:-1935}"
BORE_TO="${BORE_TO:-bore.pub}"

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

ADDR=""
if [ -n "$PUBLIC_HOST" ]; then
  echo "==> Túnel: pulado (PUBLIC_HOST=$PUBLIC_HOST)"
  # Aceita host com ou sem porta; sem, assume a do MediaMTX.
  case "$PUBLIC_HOST" in
    *:*) ADDR="$PUBLIC_HOST" ;;
    *)   ADDR="${PUBLIC_HOST}:${RTMP_PORT}" ;;
  esac
else
  echo "==> Túnel"
  pkill -f "bore local" 2>/dev/null || true
  nohup bore local 1935 --to "$BORE_TO" > /tmp/bore.log 2>&1 &
  BORE_PID=$!

  for i in $(seq 1 20); do
    ADDR=$(grep -oP 'listening at \K\S+' /tmp/bore.log 2>/dev/null | tail -1 || true)
    [ -n "$ADDR" ] && break
    # Com o bore.pub fora do ar o processo morre no primeiro segundo; esperar
    # os 20 s de timeout depois disso só atrasa o aviso.
    kill -0 "$BORE_PID" 2>/dev/null || break
    sleep 1
  done
fi

if [ -z "$ADDR" ]; then
  LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  cat <<EOF

  AVISO: o túnel não subiu (veja /tmp/bore.log). Ele é opcional.

  O MediaMTX está no ar e a coleta de imagens funciona normalmente. Falta só
  um endereço público para o drone publicar. Opções:

    - Se esta máquina tem IP público, rode com PUBLIC_HOST:
          PUBLIC_HOST=\$(curl -s ifconfig.me) ./start.sh
    - Se o drone está na mesma rede, use o IP local desta máquina:
          rtmp://${LAN_IP}:${RTMP_PORT}/${PATH_NAME}
    - Se depende mesmo do bore, confira se bore.pub está no ar:
          nc -vz bore.pub 7835

  Consumo OpenCV : rtsp://localhost:8554/${PATH_NAME}
  Status         : curl -s localhost:9997/v3/paths/list | python3 -m json.tool

EOF
  exit 0
fi

cat <<EOF

┌──────────────────────────────────────────────────────────┐
  Cole no FlightHub → Endereço do servidor:

      rtmp://${ADDR}/${PATH_NAME}

  Depois: desligue e religue o toggle do canal.
└──────────────────────────────────────────────────────────┘

EOF

if [ -n "$PUBLIC_HOST" ]; then
  cat <<EOF
  Endereço fixo (PUBLIC_HOST) — não muda entre reinícios.
  Confira que a porta ${RTMP_PORT}/tcp está liberada no firewall.

EOF
fi

cat <<EOF
  Consumo OpenCV : rtsp://localhost:8554/${PATH_NAME}
  Player HLS     : porta 8888, path /${PATH_NAME}
  Status         : curl -s localhost:9997/v3/paths/list | python3 -m json.tool
EOF

[ -n "$PUBLIC_HOST" ] || echo "  Logs do túnel  : tail -f /tmp/bore.log"
echo
