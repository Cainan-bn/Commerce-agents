#!/usr/bin/env bash
#
# Diagnostico do ambiente local. Apenas reporta; nunca falha por ferramenta ausente.
#
set -uo pipefail

export PATH="${HOME}/.local/bin:${HOME}/.local/share/fnm:${PATH}"
eval "$(fnm env --shell bash 2>/dev/null)" 2>/dev/null || true

status=0
report_ok() { printf '[ok]    %s\n' "$*"; }
report_missing() { printf '[faltou] %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

check_version() {
  local cmd="$1"
  shift
  if have "${cmd}"; then
    report_ok "${cmd}: $("${cmd}" "$@" 2>/dev/null | head -n1)"
  else
    report_missing "${cmd} (instale com scripts/bootstrap_wsl2.sh)"
  fi
}

port_in_use() {
  local port="$1"
  if have ss; then
    ss -H -ltn "sport = :${port}" 2>/dev/null | grep -q .
    return
  fi
  if have lsof; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
    return
  fi
  (exec 3<>"/dev/tcp/127.0.0.1/${port}") >/dev/null 2>&1
}

printf '\n== Toolchain ==\n'
check_version git --version
check_version make --version
check_version gcc --version
check_version curl --version
check_version jq --version
check_version uv --version
check_version python3 --version
if have uv; then
  if py312="$(uv python find 3.12 2>/dev/null)"; then
    report_ok "Python 3.12 (uv): ${py312}"
  else
    report_missing "Python 3.12 via uv (rode scripts/bootstrap_wsl2.sh)"
  fi
fi
check_version node --version
check_version npm --version
check_version fnm --version
check_version gh --version
check_version k6 version
check_version pre-commit --version
check_version shellcheck --version

printf '\n== Docker ==\n'
if have docker; then
  if timeout 10 docker info >/dev/null 2>&1; then
    report_ok "docker funcional"
  else
    report_missing "docker presente mas daemon nao responde (ative a integracao WSL2 no Docker Desktop)"
  fi
  if timeout 10 docker compose version >/dev/null 2>&1; then
    report_ok "docker compose: $(docker compose version 2>/dev/null | head -n1)"
  else
    report_missing "docker compose (instale o plugin Compose; o bootstrap nao instala Docker)"
  fi
else
  report_missing "docker (instale Docker Engine/Desktop manualmente; o bootstrap nao instala Docker)"
fi

printf '\n== GitHub CLI ==\n'
if have gh; then
  if gh auth status >/dev/null 2>&1; then
    report_ok "gh autenticado"
  else
    report_missing "gh sem autenticacao (rode 'gh auth login')"
  fi
else
  report_missing "gh (instale com scripts/bootstrap_wsl2.sh)"
fi

printf '\n== Portas ==\n'
for port in 3000 5432 6379 8000 9092; do
  if port_in_use "${port}"; then
    printf '[ocupada] %s\n' "${port}"
  else
    printf '[livre]   %s\n' "${port}"
  fi
done

printf '\nDiagnostico concluido (somente leitura).\n'
exit "${status}"
