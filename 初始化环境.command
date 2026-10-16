#!/bin/zsh
set -eu
cd -- "$(dirname "$0")"
uv_bin="$(command -v uv || true)"
if [[ -z "$uv_bin" && -x /opt/homebrew/bin/uv ]]; then
  uv_bin=/opt/homebrew/bin/uv
fi
if [[ -z "$uv_bin" ]]; then
  print '需要先安装 uv。请查看 README.md 中的环境说明。'
  read 'reply?按回车退出…'
  exit 1
fi
UV_CACHE_DIR="$PWD/.cache/uv" "$uv_bin" sync --locked --python 3.11
print '环境已就绪。现在可以双击“启动听笺.command”。'
read 'reply?按回车关闭…'
