#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

bundle_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
deploy_dir="/opt/xiaogpt"
image="yihong0618/xiaogpt@sha256:2513ebea5a74b4c1e2fc5374ebbd8d05601dded39b23c3c3d7387bd7cbaf26c8"
compose=(docker compose -p xiaogpt-speaker -f "$deploy_dir/compose.yaml")
exec 9>"$deploy_dir/.smart-install.lock"
flock -n 9 || { printf '%s\n' '已有安装任务正在运行。'; exit 1; }
"${compose[@]}" config --quiet
docker image inspect "$image" >/dev/null

run_image() {
  docker run --rm --pull=never \
    --mount "type=bind,src=$deploy_dir/config,dst=/config" \
    --mount "type=bind,src=$bundle_dir,dst=/bundle,readonly" \
    --env HOME=/config --entrypoint pdm "$image" run python "$@"
}

if [[ "${1:-}" == "--rollback" ]]; then
  run_image /bundle/deploy.py rollback
  "${compose[@]}" restart speaker
  printf '%s\n' '已恢复并重启音箱服务。'
  exit 0
fi
if [[ -n "${1:-}" ]]; then
  printf '%s\n' '用法：bash install.sh [--rollback]'
  exit 1
fi

stage="$(mktemp -d "$deploy_dir/config/.smart-stage.XXXXXXXX")"
stage_name="${stage##*/}"
for file in smart_deepseek.py smart_voice.json voice_prompt.txt deploy.py direct_answer_patch.py; do
  install -m 600 "$bundle_dir/$file" "$stage/$file"
done
# Retain the user's edited prompt/settings on a repeated installation.
for file in smart_voice.json voice_prompt.txt; do
  if [[ -f "$deploy_dir/config/smart_voice/$file" ]]; then
    install -m 600 "$deploy_dir/config/smart_voice/$file" "$stage/$file"
  fi
done

printf '%s\n' '先测试官方搜索和模型回答，成功后才修改正在使用的配置。'
run_image "/config/$stage_name/smart_deepseek.py" smoke --config /config/config.json
run_image "/config/$stage_name/deploy.py" install --stage "/config/$stage_name"
"${compose[@]}" restart speaker
docker inspect xiaogpt-speaker-speaker-1 \
  --format 'Status={{.State.Status}} Restarts={{.RestartCount}}'
printf '%s\n' '安装命令已完成。请用音箱测试联网提问和连续追问。'
printf '%s\n' '回退命令：bash install.sh --rollback'
