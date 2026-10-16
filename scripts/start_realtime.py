"""Prompt for an environment-only API key and start this project's local server."""

import getpass
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:8765"
OPENER = build_opener(ProxyHandler({}))


def status():
    try:
        with OPENER.open(ORIGIN + "/api/status", timeout=2) as response:
            return json.load(response)
    except URLError:
        return None


def stop_previous():
    previous = status()
    if not previous:
        return
    if previous.get("application") != "local-lecsync" or previous.get("project_root") != str(ROOT):
        raise RuntimeError("8765 端口已有其他服务，请先关闭它再启动。")
    if previous.get("pending_jobs") or previous.get("active_realtime"):
        raise RuntimeError("听笺还有任务或实时录音，请完成后再重新启动。")
    listeners = subprocess.run(
        ["/usr/sbin/lsof", "-t", "-iTCP:8765", "-sTCP:LISTEN"],
        capture_output=True, text=True, check=False,
    ).stdout.split()
    pid = previous.get("pid")
    if not isinstance(pid, int) or listeners != [str(pid)]:
        raise RuntimeError("无法确认旧服务进程，请先在原终端停止听笺。")
    command = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "command="],
        capture_output=True, text=True, check=True,
    ).stdout
    if "uvicorn app.server:app" not in command:
        raise RuntimeError("旧服务进程与预期不同，请先在原终端停止听笺。")
    os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        if status() is None:
            return
        time.sleep(0.25)
    raise RuntimeError("旧服务尚未退出，请稍后再试。")


def main():
    os.chdir(ROOT)
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        key = getpass.getpass("粘贴千问 API Key（输入隐藏，不写入文件）：").strip()
    if not key:
        raise RuntimeError("未提供 Key，未启动 API 模式。")
    os.environ["DASHSCOPE_API_KEY"] = key
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    stop_previous()
    server = subprocess.Popen([
        sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
        "--port", "8765", "--log-level", "warning",
    ])
    try:
        for _ in range(40):
            if server.poll() is not None:
                raise RuntimeError("本地服务未能启动，请查看终端错误。")
            if status():
                subprocess.run(["/usr/bin/open", ORIGIN], check=False)
                print("已启动。请在页面配置业务空间和地域，选择千问实时字幕后录音。")
                break
            time.sleep(0.25)
        server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"无法启动：{exc}", file=sys.stderr)
        sys.exit(1)
