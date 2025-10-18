#!/usr/bin/env python3
"""一键启动 FastAPI 服务并在浏览器中打开面板。"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
UVICORN_APP = "app.main:app"
HOST = "127.0.0.1"
PORT = int(os.getenv("APP_PORT", "8000"))


def ensure_dependencies() -> None:
    if not REQUIREMENTS.exists():
        return

    print("正在安装/更新依赖...（如已安装会自动跳过）")
    try:
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(REQUIREMENTS),
            ]
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "依赖安装失败，请检查网络连接或手动运行 pip install -r requirements.txt"
        ) from exc


def run_server() -> subprocess.Popen:
    env = os.environ.copy()
    cmd = [sys.executable, "-m", "uvicorn", UVICORN_APP, "--host", HOST, "--port", str(PORT)]
    print("正在启动后端服务...")
    print("命令:", " ".join(cmd))
    return subprocess.Popen(cmd, cwd=PROJECT_ROOT, env=env)


def open_frontend() -> None:
    url = f"http://{HOST}:{PORT}/"
    print(f"打开浏览器访问 {url}，如未自动打开请手动在浏览器输入。")
    try:
        webbrowser.open(url, new=2)
    except webbrowser.Error:
        pass


def main() -> None:
    ensure_dependencies()
    server = run_server()
    time.sleep(2)
    open_frontend()
    print("按 Ctrl+C 可以退出程序。")
    try:
        server.wait()
    except KeyboardInterrupt:
        print("\n正在关闭服务...")
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            if server.poll() is None:
                server.send_signal(sig)
                time.sleep(1)
        if server.poll() is None:
            server.kill()
        print("已退出。")


if __name__ == "__main__":
    main()
