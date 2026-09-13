from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, video_id: str, run_id: str) -> Path:
        path = self.root / video_id / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def step_dir(self, video_id: str, run_id: str, step: str) -> Path:
        path = self.run_dir(video_id, run_id) / step
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def write_json(path: Path, payload: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return path

    @staticmethod
    def copy(source: Path, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        return destination

    @staticmethod
    def valid(path: Path | None, expected_sha256: str | None = None) -> bool:
        if path is None or not path.is_file() or path.stat().st_size == 0:
            return False
        return expected_sha256 is None or sha256(path) == expected_sha256

