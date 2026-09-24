from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

from . import procs
from .runtime import build_runtime
from .settings import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local video-library worker")
    parser.add_argument("--once", action="store_true", help="process one queued item")
    parser.add_argument("--run-id", help="internal isolated job execution")
    args = parser.parse_args()
    settings = None
    if args.run_id and os.environ.get("KITE_RUN_SETTINGS"):
        values = json.loads(os.environ["KITE_RUN_SETTINGS"])
        for key in ("project_root", "database_path", "artifact_root", "whisper_large_v3_model", "prompt_file", "ledger_file", "media_root"):
            if values.get(key) is not None:
                values[key] = Path(values[key])
        values["api_origins"] = tuple(values["api_origins"])
        settings = Settings(**values)
    runtime = build_runtime(settings)
    if args.run_id:
        parent = int(os.environ.get("KITE_SUPERVISOR_PID", "0"))
        if parent:
            def watch_parent() -> None:
                while True:
                    if procs.IS_WINDOWS:
                        # Windows never reparents, and venv launchers sit between
                        # supervisor and job, so check that the supervisor lives.
                        orphaned = not procs.process_alive(parent)
                    else:
                        orphaned = os.getppid() != parent
                    if orphaned:
                        procs.kill_own_tree()
                    time.sleep(0.2)
            threading.Thread(target=watch_parent, daemon=True).start()
        runtime.runner.run(args.run_id)
        return 0
    if args.once:
        result = runtime.worker.run_once()
        print(json.dumps(result or {"state": "idle"}, ensure_ascii=False))
        return 0
    try:
        runtime.worker.serve()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
