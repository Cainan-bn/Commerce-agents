#!/usr/bin/env bash
#
# Bootstrap idempotente do ambiente de desenvolvimento no WSL2.
# Pode ser executado quantas vezes forem necessarias.
#
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
readonly SCRIPT_NAME
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly PROJECT_ROOT

export PATH="${HOME}/.local/bin:${PATH}"

log() { printf '[bootstrap] %s\n' "$*"; }
warn() { printf '[bootstrap] AVISO: %s\n' "$*" >&2; }
die() { printf '[bootstrap] ERRO: %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

require_wsl2() {
  if ! grep -qi microsoft /proc/version 2>/dev/null; then
    die "este script exige WSL2 (/proc/version sem 'microsoft'). Abortando."
  fi
  log "WSL2 detectado"
}

require_not_mnt() {
  case "${PROJECT_ROOT}" in
    /mnt/*)
      die "o projeto esta sob /mnt/ (filesystem do Windows). Copie para ~/ e rode novamente."
      ;;
  esac
  log "projeto em filesystem Linux: ${PROJECT_ROOT}"
}

apt_install() {
  if ! have sudo; then
    die "sudo nao disponivel para instalar: $*"
  fi
  log "instalando via apt: $*"
  sudo apt-get update -qq
  sudo apt-get install -y "$@"
}

ensure_apt_tool() {
  local cmd="$1"
  local pkg="${2:-$1}"
  if have "${cmd}"; then
    log "ok: ${cmd} ($(command -v "${cmd}"))"
    return 0
  fi
  apt_install "${pkg}"
  have "${cmd}" || die "falha ao instalar ${pkg} (comando '${cmd}' continua ausente)"
}

ensure_build_essential() {
  if have gcc && have make; then
    log "ok: build-essential (gcc, make)"
    return 0
  fi
  apt_install build-essential
  if ! have gcc || ! have make; then
    die "falha ao instalar build-essential"
  fi
}

ensure_uv() {
  if have uv; then
    log "ok: uv ($(uv --version))"
    return 0
  fi
  log "instalando uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  have uv || die "uv nao encontrado apos instalacao"
  log "ok: uv ($(uv --version))"
}

ensure_python312() {
  log "garantindo Python 3.12 via uv"
  uv python install 3.12
  local py
  py="$(uv python find 3.12)"
  log "ok: Python 3.12 (${py})"
}

ensure_fnm() {
  if ! have fnm; then
    if have unzip; then
      log "instalando fnm (instalador oficial)"
      curl -fsSL https://fnm.vercel.app/install | bash
    else
      log "instalando fnm (download direto; unzip ausente)"
      install_fnm_direct
    fi
  fi
  export PATH="${HOME}/.local/share/fnm:${HOME}/.local/bin:${PATH}"
  have fnm || die "fnm nao encontrado apos instalacao"
  eval "$(fnm env --shell bash)"
  log "ok: fnm ($(fnm --version))"
}

install_fnm_direct() {
  local arch version asset tmp
  case "$(uname -m)" in
    x86_64) asset="fnm-linux.zip" ;;
    aarch64 | arm64) asset="fnm-arm64.zip" ;;
    *) die "arquitetura nao suportada para fnm: $(uname -m)" ;;
  esac

  version="$(curl -fsSL https://api.github.com/repos/Schniz/fnm/releases/latest \
    | jq -r '.tag_name')"
  [ -n "${version}" ] && [ "${version}" != "null" ] || die "nao foi possivel obter a versao do fnm"

  tmp="$(mktemp -d)"
  curl -fsSL "https://github.com/Schniz/fnm/releases/download/${version}/${asset}" \
    -o "${tmp}/fnm.zip"
  python3 -m zipfile -e "${tmp}/fnm.zip" "${tmp}/unpacked"
  mkdir -p "${HOME}/.local/bin"
  install -m 0755 "${tmp}/unpacked/fnm" "${HOME}/.local/bin/fnm"
  rm -rf "${tmp}"

  if [ -f "${HOME}/.bashrc" ] && ! grep -q 'fnm env' "${HOME}/.bashrc"; then
    {
      printf '\n# fnm (adicionado por bootstrap_wsl2.sh)\n'
      printf "export PATH=\"\${HOME}/.local/bin:\${PATH}\"\n"
      printf "if command -v fnm >/dev/null 2>&1; then eval \"\$(fnm env --use-on-cd --shell bash)\"; fi\n"
    } >>"${HOME}/.bashrc"
  fi
}

ensure_node_lts() {
  log "garantindo Node.js LTS via fnm"
  fnm install --lts
  fnm default lts-latest
  eval "$(fnm env --shell bash)"
  have node || die "node nao encontrado apos instalacao via fnm"
  log "ok: node ($(node --version))"
}

ensure_k6() {
  if have k6; then
    log "ok: k6 ($(k6 version))"
    return 0
  fi

  local arch version tarball tmp
  case "$(uname -m)" in
    x86_64) arch="amd64" ;;
    aarch64 | arm64) arch="arm64" ;;
    *) die "arquitetura nao suportada para k6: $(uname -m)" ;;
  esac

  log "instalando k6 (linux-${arch})"
  version="$(curl -fsSL https://api.github.com/repos/grafana/k6/releases/latest \
    | jq -r '.tag_name')"
  [ -n "${version}" ] && [ "${version}" != "null" ] || die "nao foi possivel obter a versao do k6"

  tarball="k6-${version}-linux-${arch}.tar.gz"
  tmp="$(mktemp -d)"
  curl -fsSL "https://github.com/grafana/k6/releases/download/${version}/${tarball}" \
    -o "${tmp}/${tarball}"
  tar -xzf "${tmp}/${tarball}" -C "${tmp}"
  mkdir -p "${HOME}/.local/bin"
  install -m 0755 "${tmp}/k6-${version}-linux-${arch}/k6" "${HOME}/.local/bin/k6"
  rm -rf "${tmp}"
  have k6 || die "k6 nao encontrado apos instalacao"
  log "ok: k6 ($(k6 version))"
}

ensure_uv_tool() {
  local tool="$1"
  local bin="${2:-$1}"
  if have "${bin}"; then
    log "ok: ${bin} ($(command -v "${bin}"))"
    return 0
  fi
  log "instalando ${tool} via uv tool"
  uv tool install "${tool}"
  have "${bin}" || die "${bin} nao encontrado apos instalacao"
  log "ok: ${bin} ($(command -v "${bin}"))"
}

check_docker() {
  if ! have docker; then
    warn "docker nao encontrado. Instale o Docker Engine/Desktop manualmente (fora do escopo deste script)."
    return 0
  fi

  if timeout 15 docker info >/dev/null 2>&1; then
    log "ok: docker funcional ($(docker --version 2>/dev/null || echo versao desconhecida))"
  else
    warn "docker encontrado, mas o daemon nao responde. Ative a integracao WSL2 no Docker Desktop."
  fi

  if timeout 15 docker compose version >/dev/null 2>&1; then
    log "ok: docker compose ($(docker compose version 2>/dev/null | head -n1))"
  else
    warn "docker compose indisponivel. Instale o plugin Compose manualmente (fora do escopo deste script)."
  fi
}

check_gh_auth() {
  if ! have gh; then
    warn "gh nao encontrado; autenticacao nao verificada."
    return 0
  fi
  if gh auth status >/dev/null 2>&1; then
    log "ok: gh autenticado"
  else
    warn "gh nao autenticado. Rode 'gh auth login' quando precisar de operacoes no GitHub."
  fi
}

ensure_env_file() {
  cd "${PROJECT_ROOT}"
  if [ -f .env ]; then
    log "ok: .env existente preservado (nunca sobrescrito)"
    return 0
  fi
  if [ -f .env.example ]; then
    cp .env.example .env
    log "ok: .env criado a partir de .env.example"
  else
    warn ".env.example ausente; .env nao criado"
  fi
}

main() {
  log "iniciando ${SCRIPT_NAME}"
  require_wsl2
  require_not_mnt

  ensure_apt_tool git
  ensure_apt_tool make
  ensure_build_essential
  ensure_apt_tool curl
  ensure_apt_tool jq

  ensure_uv
  ensure_python312
  ensure_fnm
  ensure_node_lts
  ensure_apt_tool gh

  ensure_k6
  ensure_uv_tool pre-commit
  ensure_uv_tool shellcheck-py shellcheck

  check_docker
  check_gh_auth
  ensure_env_file

  log "concluido com sucesso"
}

main "$@"
