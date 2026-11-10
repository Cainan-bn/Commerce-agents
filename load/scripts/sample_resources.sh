#!/usr/bin/env bash
# Amostra CPU e memória dos processos (ps) e dos containers (docker stats) a cada N segundos.
# Uso: sample_resources.sh <arquivo de pids "nome pid"> <dir de saída> <intervalo_s>
set -uo pipefail
PIDS=$1
OUT=$2
INTERVAL=${3:-5}
echo "ts,name,pid,cpu_percent,rss_kb" > "$OUT/resources.csv"
echo "ts,container,cpu_percent,mem_usage" > "$OUT/docker.csv"
while true; do
  ts=$(date +%s)
  while read -r name pid; do
    line=$(ps -o pcpu=,rss= -p "$pid" 2> /dev/null) || continue
    read -r cpu rss <<< "$line"
    echo "$ts,$name,$pid,$cpu,$rss" >> "$OUT/resources.csv"
  done < "$PIDS"
  docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' 2> /dev/null \
    | sed "s/^/$ts,/; s/%//" >> "$OUT/docker.csv"
  sleep "$INTERVAL"
done
