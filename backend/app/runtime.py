from __future__ import annotations

import threading
from dataclasses import dataclass

from .db import Repository
from .pipeline import PipelineRunner
from .settings import Settings, load_settings
from .storage import ArtifactStore


@dataclass
class Runtime:
    settings: Settings
    repository: Repository
    artifacts: ArtifactStore
    runner: PipelineRunner
    worker: "LocalWorker"


class LocalWorker:
    """One durable local worker that resumes rows left in Processing on restart."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.serve, name="local-video-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.thread:
            self.thread.join(timeout=3)

    def wake(self) -> None:
        self.wake_event.set()

    def run_once(self) -> dict[str, object] | None:
        with self.lock:
            with self.runtime.repository.connection() as connection:
                row = connection.execute(
                    "SELECT id FROM runs WHERE state IN ('queued', 'running') ORDER BY updated_at ASC LIMIT 1"
                ).fetchone()
            if row is None:
                return None
            return self.runtime.runner.run(str(row["id"]))

    def serve(self) -> None:
        while not self.stop_event.is_set():
            result = self.run_once()
            if result is None:
                self.wake_event.wait(timeout=self.runtime.settings.worker_poll_seconds)
                self.wake_event.clear()


def build_runtime(settings: Settings | None = None, *, failure_plan: dict[str, int] | None = None) -> Runtime:
    current = settings or load_settings()
    repository = Repository(current.database_path, current.artifact_root)
    artifacts = ArtifactStore(current.artifact_root)
    runtime = Runtime(
        settings=current,
        repository=repository,
        artifacts=artifacts,
        runner=None,  # type: ignore[arg-type]
        worker=None,  # type: ignore[arg-type]
    )
    runtime.runner = PipelineRunner(
        repository=repository,
        artifacts=artifacts,
        settings=current,
        failure_plan=failure_plan,
    )
    runtime.worker = LocalWorker(runtime)
    return runtime

