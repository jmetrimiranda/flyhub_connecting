#!/usr/bin/env bash
docker rm -f mtx 2>/dev/null && echo "MediaMTX parado"
pkill -f "bore local" 2>/dev/null && echo "Túnel parado"
echo "Pipeline encerrado."
