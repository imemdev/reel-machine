from __future__ import annotations

import threading
import json
import os
import signal
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass

from .db import Repository, NotFoundError, STAGE_ORDER
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
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.active: tuple[str, subprocess.Popen] | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.serve, name="local-video-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        with self.lock:
            video_id = self.active[0] if self.active else None
            self._terminate_active()
            if video_id:
                video = self.runtime.repository.hydrate_video(video_id)
                if video["active_run_id"]:
                    self._discard_partial_step(video)
        if self.thread:
            self.thread.join(timeout=5)

    def wake(self) -> None:
        self.wake_event.set()

    def run_once(self) -> dict[str, object] | None:
        with self.lock:
            with self.runtime.repository.connection() as connection:
                row = connection.execute(
                    "SELECT runs.id FROM runs JOIN videos ON videos.id = runs.video_id WHERE runs.state IN ('queued', 'running') AND videos.paused = 0 ORDER BY runs.updated_at ASC LIMIT 1"
                ).fetchone()
            if row is None:
                return None
            return self.runtime.runner.run(str(row["id"]))

    def _terminate_active(self, video_id: str | None = None) -> None:
        if self.active is None or (video_id is not None and self.active[0] != video_id):
            return
        _, process = self.active
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        # Kill descendants too, including downloaders that outlive their parent.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        self.active = None

    def pause(self, video_id: str) -> dict[str, object]:
        with self.lock:
            self.runtime.repository.hydrate_video(video_id)
            self._terminate_active(video_id)
            result = self.runtime.repository.set_paused(video_id, True)
            self._discard_partial_step(result)
        self.wake()
        return result

    def _discard_partial_step(self, video: dict[str, object]) -> None:
        run = self.runtime.repository.get_run(str(video["active_run_id"]))
        step = run["current_step"]
        if step not in STAGE_ORDER:
            return
        checkpoint = self.runtime.repository.checkpoint(str(video["id"]), step)
        if checkpoint and checkpoint["run_id"] == run["id"]:
            return
        # An interrupted downloader may otherwise mistake a partial file for a
        # completed download. Completed checkpoints live outside this directory.
        directory = self.runtime.settings.artifact_root / str(video["id"]) / run["id"] / step
        if directory.is_dir():
            shutil.rmtree(directory)

    def resume(self, video_id: str) -> dict[str, object]:
        with self.lock:
            video = self.runtime.repository.hydrate_video(video_id)
            if not video.get("paused"):
                return video
            result = self.runtime.repository.set_paused(video_id, False)
        self.wake()
        return result

    def delete_video(self, video_id: str) -> None:
        with self.lock:
            self.runtime.repository.hydrate_video(video_id)
            self._terminate_active(video_id)
            video = self.runtime.repository.hydrate_video(video_id)
            if video["stage"] == "processing":
                self.runtime.repository.set_paused(video_id, True)
            self.runtime.repository.delete_video(video_id)
        self.wake()

    def _job_command(self, run_id: str) -> list[str]:
        return [sys.executable, "-m", "backend.app.worker", "--run-id", run_id]

    def run_isolated_once(self) -> bool:
        with self.lock:
            if self.stop_event.is_set() or self.active is not None:
                return False
            with self.runtime.repository.connection() as connection:
                row = connection.execute(
                    "SELECT runs.id, runs.video_id, runs.state FROM runs JOIN videos ON videos.id = runs.video_id "
                    "WHERE runs.state IN ('queued','running') AND videos.paused = 0 "
                    "ORDER BY runs.updated_at ASC LIMIT 1"
                ).fetchone()
            if row is None:
                return False
            if row["state"] == "running":
                self._discard_partial_step(self.runtime.repository.hydrate_video(row["video_id"]))
            env = os.environ.copy()
            env["KITE_RUN_SETTINGS"] = json.dumps(asdict(self.runtime.settings), default=str)
            env["KITE_SUPERVISOR_PID"] = str(os.getpid())
            log = self.runtime.artifacts.run_dir(row["video_id"], row["id"]) / "worker.log"
            with log.open("a") as output:
                process = subprocess.Popen(self._job_command(row["id"]), cwd=self.runtime.settings.project_root,
                                           env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            self.active = (row["video_id"], process)
        process.wait()
        with self.lock:
            if self.active is not None and self.active[1] is process:
                self._terminate_active()
                try:
                    run = self.runtime.repository.get_run(row["id"])
                    if run["state"] in {"queued", "running"}:
                        self.runtime.repository.mark_error(run_id=row["id"], step=run["current_step"] or "inspect",
                            code="worker_exited", message=f"Worker exited before finishing (exit code {process.returncode}). See worker.log.", retryable=True)
                except NotFoundError:
                    pass
        return True

    def serve(self) -> None:
        while not self.stop_event.is_set():
            result = self.run_isolated_once()
            if not result:
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
