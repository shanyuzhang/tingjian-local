#!/bin/zsh
set -eu
cd -- "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  print '请先双击“初始化环境.command”。'
  read 'reply?按回车退出…'
  exit 1
fi
print '只下载语音识别模型（约 1.6GB）；不会下载或替换 Foresight 的 Gemma。'
.venv/bin/python scripts/download_models.py --only speech
read 'reply?准备完成。按回车关闭…'
