from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


STAGES = ("inbox", "processing", "processed", "error", "done", "complete")
STAGE_ORDER = ("inspect", "download", "prepare_audio", "check_language", "transcribe", "format", "publish")


class RepositoryError(RuntimeError):
    """Base repository error."""


class NotFoundError(RepositoryError):
    pass


class ConflictError(RepositoryError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class Repository:
    def __init__(self, database_path: Path, artifact_root: Path | None = None) -> None:
        self.database_path = database_path
        self.artifact_root = artifact_root
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=20, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 20000")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def begin(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    script TEXT NOT NULL DEFAULT '',
                    done INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    canonical_id TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_page_url TEXT,
                    captured_title TEXT,
                    captured_creator TEXT,
                    captured_thumbnail_url TEXT,
                    display_title TEXT,
                    display_creator TEXT,
                    display_thumbnail_url TEXT,
                    duration_ms INTEGER,
                    stage TEXT NOT NULL DEFAULT 'inbox' CHECK (stage IN ('inbox','processing','processed','error','done','complete')),
                    error_code TEXT,
                    error_message TEXT,
                    failed_step TEXT,
                    active_run_id TEXT,
                    current_transcript_id TEXT,
                    source_media_path TEXT,
                    source_audio_path TEXT,
                    saved_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    manual_edits INTEGER NOT NULL DEFAULT 0,
                    version INTEGER NOT NULL DEFAULT 1,
                    deleted_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS videos_identity_unique
                    ON videos(platform, canonical_id) WHERE deleted_at IS NULL;
                CREATE INDEX IF NOT EXISTS videos_stage_idx ON videos(stage, saved_at DESC);

                CREATE TABLE IF NOT EXISTS tags (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS video_tags (
                    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY(video_id, tag_id)
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    action TEXT NOT NULL CHECK (action IN ('process','retry','reprocess')),
                    model_key TEXT NOT NULL,
                    model_label TEXT NOT NULL,
                    model_source TEXT NOT NULL,
                    owner_asserted INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','succeeded','failed')),
                    current_step TEXT,
                    failed_step TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    retryable INTEGER NOT NULL DEFAULT 1,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS runs_video_idx ON runs(video_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS checkpoints (
                    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    step TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    artifact_path TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY(video_id, step)
                );

                CREATE TABLE IF NOT EXISTS transcripts (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    previous_id TEXT REFERENCES transcripts(id),
                    origin TEXT NOT NULL,
                    model_key TEXT NOT NULL,
                    is_manual INTEGER NOT NULL DEFAULT 0,
                    segments_json TEXT NOT NULL,
                    raw_artifact_path TEXT,
                    txt_path TEXT,
                    srt_path TEXT,
                    vtt_path TEXT,
                    created_at TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS transcripts_video_idx ON transcripts(video_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS activities (
                    id TEXT PRIMARY KEY,
                    video_id TEXT REFERENCES videos(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS activities_created_idx ON activities(created_at DESC);
                """
            )
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS step_clocks (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
                    started_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transcription_timings (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
                    seconds REAL NOT NULL, duration_ms INTEGER NOT NULL
                );
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(videos)")}
            if "paused" not in columns:
                connection.execute("ALTER TABLE videos ADD COLUMN paused INTEGER NOT NULL DEFAULT 0")
            connection.commit()

    def _activity(
        self,
        connection: sqlite3.Connection,
        *,
        video_id: str | None,
        kind: str,
        message: str,
    ) -> None:
        connection.execute(
            "INSERT INTO activities(id, video_id, kind, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (new_id("activity"), video_id, kind, message, now()),
        )

    def _video_row(self, connection: sqlite3.Connection, video_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM videos WHERE id = ? AND deleted_at IS NULL", (video_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("Video not found")
        return row

    def _tags_for(self, connection: sqlite3.Connection, video_id: str) -> list[str]:
        rows = connection.execute(
            """
            SELECT tags.name FROM tags
            JOIN video_tags ON video_tags.tag_id = tags.id
            WHERE video_tags.video_id = ? ORDER BY lower(tags.name)
            """,
            (video_id,),
        ).fetchall()
        return [str(row["name"]) for row in rows]

    def _transcript_row(self, connection: sqlite3.Connection, video_id: str) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT transcripts.* FROM transcripts
            JOIN videos ON videos.current_transcript_id = transcripts.id
            WHERE transcripts.video_id = ? AND videos.id = ?
            """,
            (video_id, video_id),
        ).fetchone()

    def _run_row(self, connection: sqlite3.Connection, run_id: str | None) -> sqlite3.Row | None:
        if not run_id:
            return None
        return connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()

    @staticmethod
    def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def hydrate_video(self, video_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = self._video_row(connection, video_id)
            payload = dict(row)
            payload["tags"] = self._tags_for(connection, video_id)
            transcript = self._transcript_row(connection, video_id)
            if transcript:
                transcript_payload = dict(transcript)
                transcript_payload["segments"] = json.loads(transcript["segments_json"])
                payload["transcript"] = transcript_payload
            else:
                payload["transcript"] = None
            run = self._run_row(connection, row["active_run_id"])
            payload["job"] = dict(run) if run else None
            from .estimates import queue_estimates
            payload["estimate"] = queue_estimates(connection).get(video_id) if row["stage"] == "processing" else None
        return payload

    def list_videos(
        self,
        *,
        stage: str | None = None,
        search: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["deleted_at IS NULL"]
        parameters: list[Any] = []
        if stage and stage != "all":
            if stage not in STAGES:
                raise ConflictError("Unknown workflow stage")
            clauses.append("stage = ?")
            parameters.append(stage)
        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT id FROM videos WHERE {' AND '.join(clauses)} ORDER BY saved_at DESC, id DESC",
                parameters,
            ).fetchall()
        videos = [self.hydrate_video(str(row["id"])) for row in rows]
        needle = search.strip().lower() if search else ""
        wanted_tags = {item.strip().lower() for item in tags or [] if item.strip()}
        if needle:
            videos = [
                video
                for video in videos
                if needle in " ".join(
                    str(video.get(key) or "")
                    for key in ("display_title", "display_creator", "source_url", "platform")
                ).lower()
                or any(needle in tag.lower() for tag in video["tags"])
            ]
        if wanted_tags:
            videos = [video for video in videos if wanted_tags.intersection(tag.lower() for tag in video["tags"])]
        return videos

    def counts(self) -> dict[str, int]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT stage, COUNT(*) AS count FROM videos WHERE deleted_at IS NULL GROUP BY stage"
            ).fetchall()
        counts = {stage: 0 for stage in STAGES}
        counts.update({str(row["stage"]): int(row["count"]) for row in rows})
        counts["total"] = sum(counts.values())
        return counts

    def activities(self, limit: int = 12) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT activities.*, videos.display_title, videos.platform
                FROM activities LEFT JOIN videos ON videos.id = activities.video_id
                ORDER BY activities.created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_video(
        self,
        *,
        platform: str,
        canonical_id: str,
        canonical_url: str,
        source_url: str,
        source_page_url: str | None,
        title: str | None,
        creator: str | None,
        thumbnail_url: str | None,
        duration_ms: int | None = None,
        tags: list[str] | None = None,
        processing_model: tuple[str, str, str] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        video_id = new_id("video")
        created = now()
        normalized_tags = sorted({item.strip() for item in tags or [] if item.strip()})
        with self.connection() as connection:
            self.begin(connection)
            duplicate = connection.execute(
                "SELECT id FROM videos WHERE platform = ? AND canonical_id = ? AND deleted_at IS NULL",
                (platform, canonical_id),
            ).fetchone()
            if duplicate:
                connection.rollback()
                return self.hydrate_video(str(duplicate["id"])), True
            connection.execute(
                """
                INSERT INTO videos(
                    id, platform, canonical_id, canonical_url, source_url, source_page_url,
                    captured_title, captured_creator, captured_thumbnail_url,
                    display_title, display_creator, display_thumbnail_url, duration_ms,
                    stage, saved_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'inbox', ?, ?)
                """,
                (
                    video_id,
                    platform,
                    canonical_id,
                    canonical_url,
                    source_url,
                    source_page_url,
                    title,
                    creator,
                    thumbnail_url,
                    title,
                    creator,
                    thumbnail_url,
                    duration_ms,
                    created,
                    created,
                ),
            )
            self._replace_tags(connection, video_id, normalized_tags)
            self._activity(connection, video_id=video_id, kind="saved", message="Saved video" if processing_model else "Saved to Inbox")
            if processing_model:
                key, label, source = processing_model
                self._create_run(connection, video_id, action="process", model_key=key,
                                 model_label=label, model_source=source, owner_asserted=True)
            connection.commit()
        return self.hydrate_video(video_id), False

    def _replace_tags(self, connection: sqlite3.Connection, video_id: str, names: list[str]) -> None:
        connection.execute("DELETE FROM video_tags WHERE video_id = ?", (video_id,))
        for name in names:
            tag = connection.execute("SELECT id FROM tags WHERE lower(name) = lower(?)", (name,)).fetchone()
            tag_id = str(tag["id"]) if tag else new_id("tag")
            if not tag:
                connection.execute(
                    "INSERT INTO tags(id, name, created_at) VALUES (?, ?, ?)", (tag_id, name, now())
                )
            connection.execute(
                "INSERT OR IGNORE INTO video_tags(video_id, tag_id) VALUES (?, ?)", (video_id, tag_id)
            )

    def update_video(
        self,
        video_id: str,
        *,
        title: str | None = None,
        creator: str | None = None,
        thumbnail_url: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        fields = {"display_title": title, "display_creator": creator, "display_thumbnail_url": thumbnail_url}
        fields = {key: value for key, value in fields.items() if value is not None}
        with self.connection() as connection:
            self.begin(connection)
            row = self._video_row(connection, video_id)
            if row["stage"] == "processing":
                raise ConflictError("Video metadata is locked while processing")
            if fields:
                assignments = ", ".join(f"{key} = ?" for key in fields)
                connection.execute(
                    f"UPDATE videos SET {assignments}, updated_at = ?, version = version + 1 WHERE id = ?",
                    [*fields.values(), now(), video_id],
                )
            if tags is not None:
                self._replace_tags(connection, video_id, sorted({item.strip() for item in tags if item.strip()}))
            self._activity(connection, video_id=video_id, kind="edited", message="Updated library details")
            connection.commit()
        return self.hydrate_video(video_id)

    def set_media_paths(self, video_id: str, *, media_path: Path, audio_path: Path | None) -> None:
        with self.connection() as connection:
            self.begin(connection)
            self._video_row(connection, video_id)
            connection.execute(
                "UPDATE videos SET source_media_path = ?, source_audio_path = ?, updated_at = ? WHERE id = ?",
                (str(media_path), str(audio_path) if audio_path else None, now(), video_id),
            )
            connection.commit()

    def create_run(
        self,
        video_id: str,
        *,
        action: str,
        model_key: str,
        model_label: str,
        model_source: str,
        owner_asserted: bool,
    ) -> dict[str, Any]:
        with self.connection() as connection:
            self.begin(connection)
            run = self._create_run(connection, video_id, action=action, model_key=model_key,
                                   model_label=model_label, model_source=model_source, owner_asserted=owner_asserted)
            connection.commit()
        return run

    def _create_run(
        self, connection: sqlite3.Connection, video_id: str, *, action: str,
        model_key: str, model_label: str, model_source: str, owner_asserted: bool,
    ) -> dict[str, Any]:
        """Queue within the caller's transaction, including atomic save-and-queue."""
        if action not in {"process", "retry", "reprocess"}:
            raise ConflictError("Unsupported processing action")
        run_id = new_id("run")
        video = self._video_row(connection, video_id)
        allowed = {
            "process": {"inbox"},
            "retry": {"error"},
            "reprocess": {"processed"},
        }[action]
        if video["stage"] not in allowed:
            raise ConflictError(f"Cannot {action} a video in {video['stage']} stage")
        if action == "retry" and video["active_run_id"]:
            previous = connection.execute(
                "SELECT failed_step, error_code FROM runs WHERE id = ?", (video["active_run_id"],)
            ).fetchone()
            failed_step = previous["failed_step"] if previous else None
            if previous and previous["error_code"] == "audio_stream_missing":
                failed_step = "download"
            if failed_step in STAGE_ORDER:
                start = STAGE_ORDER.index(failed_step)
                connection.execute(
                    f"DELETE FROM checkpoints WHERE video_id = ? AND step IN ({','.join('?' for _ in STAGE_ORDER[start:])})",
                    [video_id, *STAGE_ORDER[start:]],
                )
        if action == "reprocess":
            start = STAGE_ORDER.index("transcribe")
            connection.execute(
                f"DELETE FROM checkpoints WHERE video_id = ? AND step IN ({','.join('?' for _ in STAGE_ORDER[start:])})",
                [video_id, *STAGE_ORDER[start:]],
            )
        connection.execute(
            """
            INSERT INTO runs(
                id, video_id, action, model_key, model_label, model_source,
                owner_asserted, state, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)
            """,
            (run_id, video_id, action, model_key, model_label, model_source, int(owner_asserted), now()),
        )
        connection.execute(
            """
            UPDATE videos SET stage = 'processing', active_run_id = ?,
                error_code = NULL, error_message = NULL, failed_step = NULL,
                updated_at = ?, version = version + 1 WHERE id = ?
            """,
            (run_id, now(), video_id),
        )
        message = {"process": "Queued for processing", "retry": "Retry queued", "reprocess": "Reprocess queued"}[action]
        self._activity(connection, video_id=video_id, kind="processing", message=f"{message} with {model_label}")
        return {"id": run_id, "video_id": video_id, "action": action, "model_key": model_key, "state": "queued"}

    def claim_run(self, run_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            self.begin(connection)
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise NotFoundError("Processing run not found")
            if row["state"] not in {"queued", "running"}:
                connection.rollback()
                return dict(row)
            connection.execute(
                "UPDATE runs SET state = 'running', attempt_count = attempt_count + 1, started_at = COALESCE(started_at, ?), updated_at = ? WHERE id = ?",
                (now(), now(), run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise NotFoundError("Processing run not found")
        return dict(row)

    def list_runs(self, video_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            self._video_row(connection, video_id)
            rows = connection.execute(
                "SELECT * FROM runs WHERE video_id = ? ORDER BY updated_at DESC", (video_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def set_run_step(self, run_id: str, step: str) -> None:
        with self.connection() as connection:
            connection.execute("UPDATE runs SET current_step = ?, updated_at = ? WHERE id = ?", (step, now(), run_id))
            connection.execute("INSERT OR REPLACE INTO step_clocks VALUES (?, ?)", (run_id, datetime.now(timezone.utc).isoformat()))
            connection.commit()

    def record_transcription_time(self, run_id: str, seconds: float, duration_ms: int) -> None:
        with self.connection() as connection:
            connection.execute("INSERT OR REPLACE INTO transcription_timings VALUES (?, ?, ?)", (run_id, seconds, duration_ms))
            connection.commit()

    def set_audio_duration(self, video_id: str, duration_ms: int) -> None:
        with self.connection() as connection:
            connection.execute("UPDATE videos SET duration_ms=? WHERE id=?", (duration_ms, video_id))
            connection.commit()

    def checkpoint(self, video_id: str, step: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM checkpoints WHERE video_id = ? AND step = ?", (video_id, step)
            ).fetchone()
        return dict(row) if row else None

    def save_checkpoint(
        self,
        *,
        video_id: str,
        run_id: str,
        step: str,
        artifact_path: Path,
        artifact_sha256: str,
        input_fingerprint: str,
        metadata: dict[str, Any],
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO checkpoints(video_id, step, run_id, artifact_path, artifact_sha256, input_fingerprint, metadata_json, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id, step) DO UPDATE SET
                    run_id = excluded.run_id,
                    artifact_path = excluded.artifact_path,
                    artifact_sha256 = excluded.artifact_sha256,
                    input_fingerprint = excluded.input_fingerprint,
                    metadata_json = excluded.metadata_json,
                    completed_at = excluded.completed_at
                """,
                (video_id, step, run_id, str(artifact_path), artifact_sha256, input_fingerprint, json.dumps(metadata, ensure_ascii=False), now()),
            )
            connection.commit()

    def mark_error(
        self,
        *,
        run_id: str,
        step: str,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        with self.connection() as connection:
            self.begin(connection)
            run = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise NotFoundError("Processing run not found")
            connection.execute(
                "UPDATE runs SET state = 'failed', current_step = ?, failed_step = ?, error_code = ?, error_message = ?, retryable = ?, finished_at = ?, updated_at = ? WHERE id = ?",
                (step, step, code, message, int(retryable), now(), now(), run_id),
            )
            connection.execute(
                "UPDATE videos SET stage = 'error', failed_step = ?, error_code = ?, error_message = ?, updated_at = ?, version = version + 1 WHERE id = ? AND active_run_id = ?",
                (step, code, message, now(), run["video_id"], run_id),
            )
            self._activity(connection, video_id=str(run["video_id"]), kind="error", message=message)
            connection.commit()

    def publish_transcript(
        self,
        *,
        run_id: str,
        segments: list[dict[str, Any]],
        origin: str,
        model_key: str,
        raw_artifact_path: Path | None,
        txt_path: Path,
        srt_path: Path,
        vtt_path: Path,
    ) -> dict[str, Any]:
        transcript_id = new_id("transcript")
        with self.connection() as connection:
            self.begin(connection)
            run = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise NotFoundError("Processing run not found")
            video = self._video_row(connection, str(run["video_id"]))
            if video["active_run_id"] != run_id:
                raise ConflictError("This processing run is no longer active")
            previous_id = video["current_transcript_id"]
            connection.execute(
                """
                INSERT INTO transcripts(
                    id, video_id, previous_id, origin, model_key, is_manual,
                    segments_json, raw_artifact_path, txt_path, srt_path, vtt_path, created_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transcript_id,
                    video["id"],
                    previous_id,
                    origin,
                    model_key,
                    json.dumps(segments, ensure_ascii=False),
                    str(raw_artifact_path) if raw_artifact_path else None,
                    str(txt_path),
                    str(srt_path),
                    str(vtt_path),
                    now(),
                ),
            )
            connection.execute(
                """
                UPDATE videos SET stage = 'processed', current_transcript_id = ?, active_run_id = NULL,
                    error_code = NULL, error_message = NULL, failed_step = NULL,
                    updated_at = ?, version = version + 1 WHERE id = ?
                """,
                (transcript_id, now(), video["id"]),
            )
            connection.execute(
                "UPDATE runs SET state = 'succeeded', current_step = 'publish', finished_at = ?, updated_at = ? WHERE id = ?",
                (now(), now(), run_id),
            )
            self._activity(connection, video_id=str(video["id"]), kind="processed", message=f"Transcript ready with {run['model_label']}")
            connection.commit()
        return self.hydrate_video(str(video["id"]))

    def update_transcript(
        self,
        video_id: str,
        *,
        expected_revision_id: str,
        segments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        revision_id = new_id("transcript")
        with self.connection() as connection:
            self.begin(connection)
            video = self._video_row(connection, video_id)
            if video["stage"] == "processing":
                raise ConflictError("Transcript editing is locked while processing")
            if video["stage"] == "complete":
                raise ConflictError("Complete transcripts are read-only")
            if not video["current_transcript_id"]:
                raise ConflictError("No transcript is available to edit")
            if video["current_transcript_id"] != expected_revision_id:
                connection.rollback()
                raise ConflictError("Transcript changed elsewhere; refresh before saving")
            current = connection.execute(
                "SELECT * FROM transcripts WHERE id = ?", (expected_revision_id,)
            ).fetchone()
            if current is None:
                raise ConflictError("Transcript revision no longer exists")
            connection.execute(
                """
                INSERT INTO transcripts(
                    id, video_id, previous_id, origin, model_key, is_manual,
                    segments_json, raw_artifact_path, txt_path, srt_path, vtt_path, created_at, version
                ) VALUES (?, ?, ?, 'manual_edit', ?, 1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    video_id,
                    expected_revision_id,
                    current["model_key"],
                    json.dumps(segments, ensure_ascii=False),
                    current["raw_artifact_path"],
                    current["txt_path"],
                    current["srt_path"],
                    current["vtt_path"],
                    now(),
                    int(current["version"]) + 1,
                ),
            )
            connection.execute(
                "UPDATE videos SET current_transcript_id = ?, manual_edits = 1, updated_at = ?, version = version + 1 WHERE id = ?",
                (revision_id, now(), video_id),
            )
            self._activity(connection, video_id=video_id, kind="edited", message="Saved transcript edits")
            connection.commit()
        return self.hydrate_video(video_id)

    def transition(self, video_id: str, action: str) -> dict[str, Any]:
        with self.connection() as connection:
            self.begin(connection)
            video = self._video_row(connection, video_id)
            transitions = {"done": ("processed", "done"), "move_to_processed": ("done", "processed")}
            if action not in transitions or video["stage"] != transitions[action][0]:
                raise ConflictError(f"Cannot {action} a video in {video['stage']} stage")
            target = transitions[action][1]
            connection.execute(
                "UPDATE videos SET stage = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                (target, now(), video_id),
            )
            self._activity(connection, video_id=video_id, kind="stage", message=f"Moved to {target.title()}")
            connection.commit()
        return self.hydrate_video(video_id)

    def complete(self, video_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            self.begin(connection)
            video = self._video_row(connection, video_id)
            if video["stage"] != "done":
                raise ConflictError("Only Done videos can move to Complete")
            paths = {Path(path) for path in (video["source_media_path"], video["source_audio_path"]) if path}
            for path in paths:
                if self.artifact_root and path.is_relative_to(self.artifact_root) and path.exists():
                    path.unlink()
            connection.execute(
                """
                UPDATE videos SET stage = 'complete', source_media_path = NULL, source_audio_path = NULL,
                    updated_at = ?, version = version + 1 WHERE id = ?
                """,
                (now(), video_id),
            )
            self._activity(connection, video_id=video_id, kind="complete", message="Completed; source media deleted, transcript retained")
            connection.commit()
        return self.hydrate_video(video_id)

    def set_paused(self, video_id: str, paused: bool) -> dict[str, Any]:
        with self.connection() as connection:
            self.begin(connection)
            video = self._video_row(connection, video_id)
            if video["stage"] != "processing":
                raise ConflictError("Only processing videos can be paused or resumed")
            connection.execute("UPDATE videos SET paused = ?, updated_at = ?, version = version + 1 WHERE id = ?", (int(paused), now(), video_id))
            connection.execute("UPDATE runs SET state = 'queued', updated_at = ? WHERE id = ?", (now(), video["active_run_id"]))
            self._activity(connection, video_id=video_id, kind="paused" if paused else "processing", message="Processing paused" if paused else "Processing resumed")
            connection.commit()
        return self.hydrate_video(video_id)

    def delete_video(self, video_id: str) -> None:
        with self.connection() as connection:
            self.begin(connection)
            video = self._video_row(connection, video_id)
            if video["stage"] == "processing" and not video["paused"]:
                raise ConflictError("Stop processing before deleting video data")
            # Remove files before committing the row deletion so filesystem failures
            # leave a record that can be retried. The worker has already been stopped.
            if self.artifact_root:
                target = self.artifact_root / video_id
                if target.is_symlink():
                    target.unlink()
                elif target.is_dir() and target.parent == self.artifact_root:
                    shutil.rmtree(target)
            tag_ids = [row[0] for row in connection.execute("SELECT tag_id FROM video_tags WHERE video_id = ?", (video_id,))]
            connection.execute("DELETE FROM videos WHERE id = ?", (video_id,))
            for tag_id in tag_ids:
                connection.execute("DELETE FROM tags WHERE id = ? AND NOT EXISTS (SELECT 1 FROM video_tags WHERE tag_id = tags.id)", (tag_id,))
            connection.commit()

    def list_notes(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM notes ORDER BY created_at DESC, rowid DESC").fetchall()
        return [dict(row) | {"done": bool(row["done"])} for row in rows]

    def create_note(self, title: str, description: str, script: str) -> dict[str, Any]:
        note = dict(id=new_id("note"), title=title, description=description, script=script,
                    done=False, created_at=now(), updated_at=now())
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO notes (id, title, description, script, done, created_at, updated_at) VALUES (:id, :title, :description, :script, :done, :created_at, :updated_at)", note,
            )
            connection.commit()
        return note

    def update_note(self, note_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self.connection() as connection:
            self.begin(connection)
            row = connection.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            if row is None:
                raise NotFoundError("Note not found")
            note = dict(row)
            note.update({key: value for key, value in changes.items() if key in {"title", "description", "script", "done"}})
            note["updated_at"] = now()
            connection.execute(
                "UPDATE notes SET title=:title, description=:description, script=:script, done=:done, updated_at=:updated_at WHERE id=:id", note,
            )
            connection.commit()
        return note | {"done": bool(note["done"])}

    def delete_note(self, note_id: str) -> None:
        with self.connection() as connection:
            result = connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            if not result.rowcount:
                raise NotFoundError("Note not found")
            connection.commit()
