#!/usr/bin/env bash
# Baixa os modelos de fala (Whisper + detector de voz) do GitHub, se ainda não existirem.
set -euo pipefail
M="${1:-small}"
D="$(cd "$(dirname "$0")/.." && pwd)/models"
mkdir -p "$D"
BASE=https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models
[ -f "$D/silero_vad.onnx" ] || curl -sSL -o "$D/silero_vad.onnx" "$BASE/silero_vad.onnx"
if [ ! -f "$D/sherpa-onnx-whisper-$M/$M-encoder.int8.onnx" ]; then
  curl -sSL "$BASE/sherpa-onnx-whisper-$M.tar.bz2" | tar xj -C "$D"
  rm -f "$D/sherpa-onnx-whisper-$M/$M-encoder.onnx" "$D/sherpa-onnx-whisper-$M/$M-decoder.onnx"
  rm -rf "$D/sherpa-onnx-whisper-$M/test_wavs"
fi
echo "modelos ok: $(ls "$D")"
