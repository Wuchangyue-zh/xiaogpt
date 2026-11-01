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
docker compose build speaker
if [[ ! -f "$project_dir/data/config.json" ]]; then
  docker compose run --rm --no-deps -it --entrypoint pdm speaker \
    run python configure.py
fi
docker compose up -d --no-build speaker
docker compose ps
printf '%s\n' '启动命令已完成。日志：docker compose logs -f --tail=80 speaker'
