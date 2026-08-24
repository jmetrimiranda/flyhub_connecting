#!/usr/bin/env bash
# Reinstala tudo que o pipeline precisa. Roda sozinho a cada rebuild.
set -euo pipefail

echo "==> Dependências de sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg libgl1 libglib2.0-0 >/dev/null

echo "==> bore"
if ! command -v bore >/dev/null 2>&1; then
  URL=$(curl -s https://api.github.com/repos/ekzhang/bore/releases/latest \
    | grep browser_download_url | grep x86_64-unknown-linux-musl | cut -d '"' -f 4)
  curl -sL "$URL" | tar xz -C /tmp
  sudo mv /tmp/bore /usr/local/bin/
fi
bore --version

echo "==> Python"
python -m pip install --upgrade pip --quiet
[ -f requirements.txt ]      && python -m pip install -q -r requirements.txt
[ -f requirements-docs.txt ] && python -m pip install -q -r requirements-docs.txt

echo "==> Imagem do MediaMTX"
docker pull -q bluenviron/mediamtx:latest

chmod +x start.sh stop.sh 2>/dev/null || true

echo ""
echo "Pronto. Suba o pipeline com:  ./start.sh"
