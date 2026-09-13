"""Run the local app; stop both services on Ctrl-C or a service failure."""
from pathlib import Path
import os
import signal
import socket
import subprocess
import sys
import time

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
os.environ["PATH"] = os.pathsep.join(
    [str(ROOT / ".venv/bin"), str(ROOT / "scripts"), "/opt/homebrew/bin", os.environ.get("PATH", "")]
)
os.environ.setdefault("NEXT_PUBLIC_API_URL", "http://127.0.0.1:8001")


def main() -> int:
    if not (ROOT / "frontend/.next/BUILD_ID").is_file():
        print("Missing frontend build. Run: npm --prefix frontend run build", file=sys.stderr)
        return 1
    for port in (8001, 3001):
        with socket.socket() as probe:
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
            cwd=ROOT, start_new_session=True,
        ))
        children.append(subprocess.Popen(
            ["node", "node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", "3001"],
            cwd=ROOT / "frontend", start_new_session=True,
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
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
