#!/bin/zsh
set -eu
cd -- "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  print '请先双击“初始化环境.command”。'
  read 'reply?按回车退出…'
  exit 1
fi
print '千问实时模式会发送录音至阿里云并产生 API 费用。'
print '只需输入 Key，地域和业务空间可在网页中配置。关闭终端或按 Control-C 停止服务。'
if ! .venv/bin/python scripts/start_realtime.py; then
  read 'reply?按回车退出…'
  exit 1
fi
