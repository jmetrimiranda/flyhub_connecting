#!/usr/bin/env bash
# Sobe o painel de controle. O pipeline em si é iniciado pelos botões da interface.
set -euo pipefail
cd "$(dirname "$0")"
# 8000 costuma estar ocupada pelo `mkdocs serve` deste repositório.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PANEL_PORT:-8080}" "$@"
