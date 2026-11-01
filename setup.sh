#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"
if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' '请先安装 Docker Engine 和 Docker Compose 插件，参见 README。'
  exit 1
fi
docker compose version >/dev/null
docker compose config --quiet
if [[ ! -f "$project_dir/data/config.json" && ! -t 0 ]]; then
  printf '%s\n' '首次配置需要交互终端，请在 SSH 终端直接运行 bash setup.sh。'
  exit 1
fi
docker compose build speaker
if [[ ! -f "$project_dir/data/config.json" ]]; then
  docker compose run --rm --no-deps -i --entrypoint python speaker \
    configure.py
fi
docker compose up -d --no-build speaker
docker compose ps
printf '%s\n' '启动命令已完成。日志：docker compose logs -f --tail=80 speaker'
