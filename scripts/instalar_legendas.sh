#!/usr/bin/env bash
# Instala o pycaps (legendas animadas) numa versão fixa e revisada, sem as partes que não usamos.
set -euo pipefail
PYCAPS_COMMIT=e2d36edfa08e3307d65b15bb20f17399dc2c9b40   # v0.3.0 (30/09/2026)
sudo apt-get install -y -qq fonts-noto-color-emoji > /dev/null 2>&1 || true
pip install -q "pycaps[faster-whisper] @ git+https://github.com/francozanardi/pycaps@${PYCAPS_COMMIT}" playwright
python -m playwright install --with-deps chromium > /dev/null
fc-cache -f > /dev/null 2>&1 || true
python -c "import pycaps, faster_whisper; print('pycaps pronto')"
