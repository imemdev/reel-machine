from __future__ import annotations

import threading
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass

from .db import Repository, NotFoundError, STAGE_ORDER
from . import procs
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
    """Bounded local process supervisor that resumes interrupted runs on restart."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.active: dict[str, tuple[str, subprocess.Popen]] = {}

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
            video_ids = list(self.active)
            self._terminate_active()
            for video_id in video_ids:
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
                    "SELECT runs.id FROM runs JOIN videos ON videos.id = runs.video_id WHERE runs.state IN ('queued', 'running') AND videos.paused = 0 ORDER BY runs.rowid ASC LIMIT 1"
                ).fetchone()
            if row is None:
                return None
            return self.runtime.runner.run(str(row["id"]))

    def _terminate_active(self, video_id: str | None = None) -> None:
        targets = list(self.active) if video_id is None else [video_id]
        for target in targets:
            entry = self.active.get(target)
            if entry is None:
                continue
            _, process = entry
            try:
                procs.terminate_tree(process.pid)
            except ProcessLookupError:
                pass
            except PermissionError as error:
                # macOS can report EPERM while an exiting group is not yet reapable.
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    raise error
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            # Kill descendants too, including downloaders that outlive their parent.
            try:
                procs.kill_tree(process.pid)
            except ProcessLookupError:
                pass
            except PermissionError as error:
                # macOS can report EPERM while an exiting group is not yet reapable.
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    raise error
            process.wait(timeout=5)
            del self.active[target]

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

    def run_isolated_once(self, *, wait: bool = True) -> bool:
        with self.lock:
            if self.stop_event.is_set() or len(self.active) >= self.runtime.settings.worker_concurrency:
                return False
            with self.runtime.repository.connection() as connection:
                excluded = list(self.active)
                exclusion = " AND runs.video_id NOT IN (" + ",".join("?" for _ in excluded) + ")" if excluded else ""
                row = connection.execute(
                    "SELECT runs.id, runs.video_id, runs.state FROM runs JOIN videos ON videos.id = runs.video_id "
                    "WHERE runs.state IN ('queued','running') AND videos.paused = 0 "
                    + exclusion + " ORDER BY runs.rowid ASC LIMIT 1", excluded
                ).fetchone()
            if row is None:
                return False
            env = os.environ.copy()
            env["KITE_RUN_SETTINGS"] = json.dumps(asdict(self.runtime.settings), default=str)
            env["KITE_SUPERVISOR_PID"] = str(os.getpid())
            try:
                if row["state"] == "running":
                    self._discard_partial_step(self.runtime.repository.hydrate_video(row["video_id"]))
                log = self.runtime.artifacts.run_dir(row["video_id"], row["id"]) / "worker.log"
                with log.open("a", encoding="utf-8") as output:
                    process = subprocess.Popen(self._job_command(row["id"]), cwd=self.runtime.settings.project_root,
                                               env=env, stdout=output, stderr=subprocess.STDOUT, **procs.new_group_kwargs())
            except OSError as error:
                self.runtime.repository.mark_error(run_id=row["id"], step="inspect",
                    code="worker_start_failed", message=f"Could not start worker: {error}", retryable=True)
                return True
            self.active[row["video_id"]] = (row["id"], process)
        if wait:
            process.wait()
            self._reap_finished()
        return True

    def _reap_finished(self) -> None:
        with self.lock:
            for video_id, (run_id, process) in list(self.active.items()):
                if process.poll() is None:
                    continue
                self._terminate_active(video_id)
                try:
                    run = self.runtime.repository.get_run(run_id)
                    if run["state"] in {"queued", "running"}:
                        self.runtime.repository.mark_error(run_id=run_id, step=run["current_step"] or "inspect",
                            code="worker_exited", message=f"Worker exited before finishing (exit code {process.returncode}). See worker.log.", retryable=True)
                except NotFoundError:
                    pass

    def _recover_interrupted(self) -> None:
        with self.lock:
            with self.runtime.repository.connection() as connection:
                rows = connection.execute("SELECT runs.id, runs.video_id FROM runs JOIN videos ON videos.active_run_id=runs.id WHERE runs.state='running'").fetchall()
            for row in rows:
                if row["video_id"] in self.active:
                    continue
                try:
                    self._discard_partial_step(self.runtime.repository.hydrate_video(row["video_id"]))
                except OSError as error:
                    self.runtime.repository.mark_error(run_id=row["id"], step="inspect", code="recovery_failed", message=f"Could not recover interrupted files: {error}", retryable=True)
                    continue
                with self.runtime.repository.connection() as connection:
                    connection.execute("UPDATE runs SET state='queued', current_step=NULL WHERE id=?", (row["id"],))
                    connection.execute("DELETE FROM step_clocks WHERE run_id=?", (row["id"],))
                    connection.commit()

    def serve(self) -> None:
        self._recover_interrupted()
        while not self.stop_event.is_set():
            self._reap_finished()
            while self.run_isolated_once(wait=False):
                pass
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
