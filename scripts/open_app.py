"""Finder entry point: reuse a running app, otherwise start the selected mode."""

import argparse
import json
import os
import subprocess
import sys

from scripts import start_realtime

ROOT = start_realtime.ROOT


def preferred_mode():
    if os.environ.get("DASHSCOPE_API_KEY", "").strip():
        return "realtime"
    path = ROOT / "data" / "realtime.json"
    if path.exists():
        try:
            if json.loads(path.read_text()).get("workspace_id"):
                return "realtime"
        except (OSError, ValueError):
            pass
    choice = input("启动模式：1 千问实时字幕 / 2 本地离线 [2]：").strip()
    if choice not in ("", "1", "2"):
        raise RuntimeError("请输入 1 或 2 后重新启动。")
    return "realtime" if choice == "1" else "local"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("auto", "local", "realtime"), default="auto")
    args = parser.parse_args(argv)
    os.chdir(ROOT)
    current = start_realtime.status()
    if current:
        if (current.get("application") != "local-lecsync"
                or current.get("project_root") != str(ROOT)):
            raise RuntimeError("8765 端口属于另一个服务，请先关闭它再打开听笺。")
        subprocess.run(["/usr/bin/open", start_realtime.ORIGIN], check=True)
        print("听笺已打开，原有服务和录音继续运行。")
        return
    mode = preferred_mode() if args.mode == "auto" else args.mode
    if mode == "realtime":
        start_realtime.main()
    else:
        subprocess.run(["/bin/zsh", str(ROOT / "启动听笺.command")], check=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"无法打开听笺：{exc}", file=sys.stderr)
        sys.exit(1)
