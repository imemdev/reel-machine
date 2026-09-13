from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .db import ConflictError, NotFoundError, RepositoryError, Repository, STAGES, STAGE_ORDER
from .metadata import inspect_video
from .pipeline import (
    MODEL_OPTIONS,
    PRIVATE_VIDEO_MESSAGE,
    PipelineError,
    model_catalog,
    model_selection,
)
from .runtime import Runtime, build_runtime
from .schemas import (
    BatchRequest,
    BatchStageActionRequest,
    PreviewRequest,
    TranscriptUpdateRequest,
    VideoActionRequest,
    VideoCreateRequest,
    VideoUpdateRequest,
)
from .transcripts import Segment, to_srt, to_text, to_timestamped_text, to_vtt, validate_segments
from .urls import URLValidationError, canonicalize_url


def _error(message: str, code: str, status_code: int, *, retryable: bool = False) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"message": message, "code": code, "retryable": retryable},
    )


def _segment_payload(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"start_ms": int(item["start_ms"]), "end_ms": int(item["end_ms"]), "text": str(item["text"])}
        for item in items
    ]


def serialize_video(video: dict[str, Any], *, runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    transcript = video.get("transcript")
    job = video.get("job")
    return {
        "id": video["id"],
        "platform": video["platform"],
        "canonical_id": video["canonical_id"],
        "canonical_url": video["canonical_url"],
        "source_url": video["source_url"],
        "source_page_url": video["source_page_url"],
        "title": video["display_title"] or video["captured_title"] or "Untitled video",
        "creator": video["display_creator"] or video["captured_creator"] or "Unknown creator",
        "thumbnail_url": video["display_thumbnail_url"] or video["captured_thumbnail_url"],
        "duration_ms": video["duration_ms"],
        "stage": video["stage"],
        "error_code": video["error_code"],
        "error_message": video["error_message"],
        "failed_step": video["failed_step"],
        "saved_at": video["saved_at"],
        "updated_at": video["updated_at"],
        "tags": video.get("tags", []),
        "manual_edits": bool(video["manual_edits"]),
        "version": video["version"],
        "transcript": (
            {
                "id": transcript["id"],
                "origin": transcript["origin"],
                "model_key": transcript["model_key"],
                "is_manual": bool(transcript["is_manual"]),
                "created_at": transcript["created_at"],
                "version": transcript["version"],
                "segments": _segment_payload(transcript["segments"]),
            }
            if transcript
            else None
        ),
        "job": (
            {
                "id": job["id"],
                "action": job["action"],
                "state": job["state"],
                "model_key": job["model_key"],
                "model_label": job["model_label"],
                "current_step": job["current_step"],
                "failed_step": job["failed_step"],
                "error_code": job["error_code"],
                "error_message": job["error_message"],
                "retryable": bool(job["retryable"]),
                "attempt_count": job["attempt_count"],
                "updated_at": job["updated_at"],
            }
            if job
            else None
        ),
        "runs": runs,
    }


def _clean_tags(tags: list[str]) -> list[str]:
    return sorted({item.strip()[:80] for item in tags if item.strip()})[:30]


def create_app(runtime: Runtime | None = None, *, start_worker: bool = True) -> FastAPI:
    current = runtime or build_runtime()
    repository = current.repository
    settings = current.settings

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if start_worker:
            current.worker.start()
        try:
            yield
        finally:
            if start_worker:
                current.worker.stop()

    app = FastAPI(title="Local Tunisian Video Library", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.api_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RepositoryError)
    async def repository_error_handler(_: Request, error: RepositoryError):
        status_code = 404 if isinstance(error, NotFoundError) else 409
        return PlainTextResponse(str(error), status_code=status_code)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "healthy",
            "persistence": "sqlite-filesystem",
            "bind_target": "127.0.0.1",
            "counts": repository.counts(),
            "models": model_catalog(settings),
        }

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "stages": list(STAGES),
            "models": model_catalog(settings),
            "suggested_tags": [
                "Marketing",
                "Education",
                "Storytelling",
                "Tutorials",
                "Inspiration",
                "Entertainment",
                "Product Reviews",
                "Behind the Scenes",
            ],
            "privacy": {
                "local_only": True,
                "storage": "SQLite + local files",
                "processing": "No transcript or media data is sent to a hosted service",
            },
        }

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        processing = repository.list_videos(stage="processing")
        return {
            "counts": repository.counts(),
            "recent_activity": repository.activities(12),
            "processing": [serialize_video(video) for video in processing],
        }

    @app.post("/api/videos/preview")
    def preview(payload: PreviewRequest) -> dict[str, Any]:
        try:
            return inspect_video(payload.url, settings)
        except URLValidationError as error:
            raise _error(str(error), error.code, 422) from error

    @app.post("/api/videos", status_code=201)
    def create_video(payload: VideoCreateRequest) -> dict[str, Any]:
        try:
            identity = canonicalize_url(payload.url, allow_fixture=settings.allow_fixture_sources)
        except URLValidationError as error:
            raise _error(str(error), error.code, 422) from error
        video, duplicate = repository.create_video(
            platform=identity.platform,
            canonical_id=identity.canonical_id,
            canonical_url=identity.canonical_url,
            source_url=identity.source_url,
            source_page_url=payload.source_page_url or identity.source_url,
            title=payload.title,
            creator=payload.creator,
            thumbnail_url=payload.thumbnail_url,
            duration_ms=payload.duration_ms,
            tags=_clean_tags(payload.tags),
        )
        return {"duplicate": duplicate, "video": serialize_video(video)}

    @app.get("/api/videos")
    def list_videos(
        stage: str | None = Query(default=None),
        search: str | None = Query(default=None, max_length=200),
        tags: str | None = Query(default=None, max_length=800),
    ) -> dict[str, Any]:
        tag_values = tags.split(",") if tags else None
        try:
            videos = repository.list_videos(stage=stage, search=search, tags=tag_values)
        except ConflictError as error:
            raise _error(str(error), "invalid_stage", 422) from error
        return {"items": [serialize_video(video) for video in videos], "count": len(videos)}

    @app.get("/api/videos/{video_id}")
    def get_video(video_id: str) -> dict[str, Any]:
        try:
            video = repository.hydrate_video(video_id)
            return serialize_video(video, runs=repository.list_runs(video_id))
        except NotFoundError as error:
            raise _error("Video not found", "not_found", 404) from error

    @app.patch("/api/videos/{video_id}")
    def update_video(video_id: str, payload: VideoUpdateRequest) -> dict[str, Any]:
        try:
            video = repository.update_video(
                video_id,
                title=payload.title,
                creator=payload.creator,
                thumbnail_url=payload.thumbnail_url,
                tags=_clean_tags(payload.tags) if payload.tags is not None else None,
            )
            return serialize_video(video)
        except NotFoundError as error:
            raise _error("Video not found", "not_found", 404) from error
        except ConflictError as error:
            raise _error(str(error), "edit_locked", 409) from error

    @app.delete("/api/videos/{video_id}", status_code=204)
    def delete_video(video_id: str) -> None:
        try:
            repository.delete_video(video_id)
        except NotFoundError as error:
            raise _error("Video not found", "not_found", 404) from error
        except ConflictError as error:
            raise _error(str(error), "complete_retention", 409) from error

    @app.post("/api/jobs", status_code=202)
    def create_jobs(payload: BatchRequest) -> dict[str, Any]:
        if not payload.owner_asserted_tunisian:
            raise _error(
                "Confirm that the selected videos are primarily Tunisian Arabic before processing.",
                "tunisian_confirmation_required",
                422,
            )
        try:
            selection = model_selection(settings, payload.model_key)
        except PipelineError as error:
            raise _error(error.message, error.code, 422) from error
        if len(payload.video_ids) > settings.max_batch_size:
            raise _error(f"Select no more than {settings.max_batch_size} videos at a time.", "batch_too_large", 422)
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for video_id in payload.video_ids:
            try:
                run = repository.create_run(
                    video_id,
                    action=payload.action,
                    model_key=selection.key,
                    model_label=selection.label,
                    model_source=selection.source,
                    owner_asserted=payload.owner_asserted_tunisian,
                )
                accepted.append(run)
            except (NotFoundError, ConflictError) as error:
                rejected.append({"video_id": video_id, "message": str(error)})
        current.worker.wake()
        return {"action": payload.action, "model_key": payload.model_key, "accepted": accepted, "rejected": rejected}

    @app.get("/api/jobs/{run_id}")
    def get_job(run_id: str) -> dict[str, Any]:
        try:
            return repository.get_run(run_id)
        except NotFoundError as error:
            raise _error("Processing run not found", "not_found", 404) from error

    @app.get("/api/jobs/{run_id}/logs", response_class=PlainTextResponse)
    def job_logs(run_id: str) -> PlainTextResponse:
        run = get_job(run_id)
        root = settings.artifact_root.resolve()
        directory = root / str(run["video_id"]) / str(run["id"])
        sections = [f"Run: {run['id']}\nModel: {run['model_label']}\nState: {run['state']}\n"
                    f"Failed step: {run.get('failed_step') or 'none'}\nError: {run.get('error_message') or 'none'}\n"
                    "Local debug report. May contain source URLs, local paths and tool output; review before sharing.\n"]
        paths = [directory / "pipeline.jsonl"]
        for step in STAGE_ORDER:
            paths.extend(sorted((directory / step).glob("*.log"))[:20])
        for path in paths:
            if not path.resolve().is_relative_to(root) or not path.is_file():
                continue
            with path.open("rb") as handle:
                size = path.stat().st_size
                handle.seek(max(0, size - 65536))
                content = handle.read(65536).decode("utf-8", errors="replace")
            sections.append(f"\n=== {path.relative_to(directory)} ===\n"
                            + ("[Showing last 64 KiB]\n" if size > 65536 else "") + content)
        if len(sections) == 1:
            sections.append("No log files yet. Queued runs have not started; older runs may not have step logs.\n")
        return PlainTextResponse("\n".join(sections), headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.post("/api/videos/{video_id}/action")
    def video_action(video_id: str, payload: VideoActionRequest) -> dict[str, Any]:
        try:
            video = repository.complete(video_id) if payload.action == "complete" else repository.transition(video_id, payload.action)
            return serialize_video(video)
        except NotFoundError as error:
            raise _error("Video not found", "not_found", 404) from error
        except ConflictError as error:
            raise _error(str(error), "invalid_transition", 409) from error

    @app.post("/api/videos/actions")
    def batch_video_action(payload: BatchStageActionRequest) -> dict[str, Any]:
        outcomes: list[dict[str, Any]] = []
        for video_id in payload.video_ids:
            try:
                video = repository.complete(video_id) if payload.action == "complete" else repository.transition(video_id, payload.action)
                outcomes.append({"video_id": video_id, "ok": True, "video": serialize_video(video)})
            except (NotFoundError, ConflictError) as error:
                outcomes.append({"video_id": video_id, "ok": False, "message": str(error)})
        return {"action": payload.action, "items": outcomes}

    @app.patch("/api/videos/{video_id}/transcript")
    def update_transcript(video_id: str, payload: TranscriptUpdateRequest) -> dict[str, Any]:
        segments = [Segment(item.start_ms, item.end_ms, item.text.strip()) for item in payload.segments]
        try:
            validate_segments(segments)
            video = repository.update_transcript(
                video_id,
                expected_revision_id=payload.expected_revision_id,
                segments=[{"start_ms": item.start_ms, "end_ms": item.end_ms, "text": item.text} for item in segments],
            )
            return serialize_video(video)
        except ValueError as error:
            raise _error(str(error), "invalid_transcript", 422) from error
        except NotFoundError as error:
            raise _error("Video not found", "not_found", 404) from error
        except ConflictError as error:
            raise _error(str(error), "transcript_conflict", 409) from error

    @app.get("/api/videos/{video_id}/export")
    def export_transcript(video_id: str, format: Literal["txt", "srt", "vtt", "timestamped"] = "txt") -> PlainTextResponse:
        try:
            video = repository.hydrate_video(video_id)
        except NotFoundError as error:
            raise _error("Video not found", "not_found", 404) from error
        transcript = video.get("transcript")
        if not transcript:
            raise _error("This video has no transcript yet.", "transcript_missing", 409)
        segments = [Segment(int(item["start_ms"]), int(item["end_ms"]), str(item["text"])) for item in transcript["segments"]]
        if format == "srt":
            content, extension = to_srt(segments), "srt"
        elif format == "vtt":
            content, extension = to_vtt(segments), "vtt"
        elif format == "timestamped":
            content, extension = to_timestamped_text(segments), "txt"
        else:
            content, extension = to_text(segments), "txt"
        filename = f"{video['canonical_id']}.{extension}"
        return PlainTextResponse(
            content,
            media_type="text/vtt" if format == "vtt" else "text/plain",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return app


app = create_app()
