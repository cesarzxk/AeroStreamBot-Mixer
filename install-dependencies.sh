#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

if command -v apt-get >/dev/null 2>&1; then
    if [[ "$(id -u)" -eq 0 ]]; then
        APT=(apt-get)
    elif command -v sudo >/dev/null 2>&1; then
        APT=(sudo apt-get)
    else
        echo "Erro: sudo não encontrado para instalar dependências do sistema." >&2
        exit 1
    fi

    "${APT[@]}" update
    "${APT[@]}" install -y \
        python3 \
        python3-venv \
        python3-pyqt5 \
        pulseaudio-utils \
        pipewire \
        pipewire-pulse \
        ffmpeg
fi

if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo "Dependências instaladas com sucesso."