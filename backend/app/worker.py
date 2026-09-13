from __future__ import annotations

import argparse
import json

from .runtime import build_runtime


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local video-library worker")
    parser.add_argument("--once", action="store_true", help="process one queued item")
    args = parser.parse_args()
    runtime = build_runtime()
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

