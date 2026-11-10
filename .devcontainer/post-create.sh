#!/usr/bin/env bash
# Prepara o ambiente do devcontainer: uv na mesma versão da imagem, dependências do projeto e
# do painel, e o .env local a partir do exemplo.
set -euo pipefail

pip install --user --quiet "uv==0.13.7"
export PATH="$HOME/.local/bin:$PATH"
uv sync --frozen
(cd panel && npm ci --no-audit --no-fund)
[ -f .env ] || cp .env.example .env

echo "Pronto. Para subir a demonstração, veja a seção do modo demonstração no README."
