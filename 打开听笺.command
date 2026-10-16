#!/bin/zsh
set -eu
cd -- "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  print '请先双击“初始化环境.command”，或按照 README.md 完成环境准备。'
  read 'reply?按回车退出…'
  exit 1
fi
if ! .venv/bin/python -m scripts.open_app; then
  read 'reply?启动失败，按回车退出…'
  exit 1
fi
