"""Run the local app; stop both services on Ctrl-C or a service failure.

Works on macOS, Linux, and Windows. Start it with ./scripts/run-local
(macOS/Linux) or .\\scripts\\run-local.ps1 (Windows PowerShell).
"""
from pathlib import Path
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from backend.app import procs  # noqa: E402

VENV_BIN = ROOT / ".venv" / ("Scripts" if procs.IS_WINDOWS else "bin")

load_dotenv(ROOT / ".env")
os.environ["PATH"] = os.pathsep.join(
    [str(VENV_BIN), str(ROOT / "scripts"), "/opt/homebrew/bin", os.environ.get("PATH", "")]
)
os.environ.setdefault("NEXT_PUBLIC_API_URL", "http://127.0.0.1:8001")
# Transcripts are Arabic text; never fall back to a legacy Windows code page.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def main() -> int:
    if not (ROOT / "frontend/.next/BUILD_ID").is_file():
        print("Missing frontend build. Run: npm --prefix frontend run build", file=sys.stderr)
        return 1
    node = shutil.which("node")
    if node is None:
        print("Node.js was not found on PATH. Install Node.js, then try again.", file=sys.stderr)
        return 1
    for port in (8001, 3001):
        with socket.socket() as probe:
            if not procs.IS_WINDOWS:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                print(f"Port {port} is already in use. Stop the existing service first.", file=sys.stderr)
                return 1
    children: list[subprocess.Popen] = []

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        children.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8001"],
            cwd=ROOT, **procs.new_group_kwargs(),
        ))
        children.append(subprocess.Popen(
            [node, "node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", "3001"],
            cwd=ROOT / "frontend", **procs.new_group_kwargs(),
        ))
        print("Kite: http://127.0.0.1:3001 — Ctrl-C stops both services.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        return next((child.returncode or 1 for child in children if child.poll() is not None), 1)
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                try:
                    procs.terminate_tree(child.pid)
                except ProcessLookupError:
                    pass
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                procs.kill_tree(child.pid)
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
