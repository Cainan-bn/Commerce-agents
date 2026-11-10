FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# A fonte apt do Yarn da imagem base está com a chave GPG desatualizada e quebra o apt-get das
# features (Docker-in-Docker); o projeto não usa Yarn.
RUN rm -f /etc/apt/sources.list.d/yarn.list
