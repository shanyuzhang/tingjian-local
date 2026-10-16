#!/bin/zsh
set -eu
cd -- "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  print '请先双击“初始化环境.command”。'
  read 'reply?按回车退出…'
  exit 1
fi
if /usr/bin/curl -fsS http://127.0.0.1:8765/api/status >/dev/null 2>&1; then
  /usr/bin/open http://127.0.0.1:8765
  exit 0
fi
print '听笺正在本机启动。关闭此终端或按 Control-C 可以停止服务。'
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  .venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8765 --log-level warning &
server_pid=$!
trap 'kill -TERM "$server_pid" 2>/dev/null || true' EXIT INT TERM
for attempt in {1..40}; do
  if /usr/bin/curl -fsS http://127.0.0.1:8765/api/status >/dev/null 2>&1; then
    /usr/bin/open http://127.0.0.1:8765
    break
  fi
  sleep 0.25
done
wait "$server_pid"
