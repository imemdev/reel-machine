from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    candidate = Path(raw).expanduser()
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


@dataclass(frozen=True)
class Settings:
    project_root: Path
    database_path: Path
    artifact_root: Path
    allow_fixture_sources: bool
    api_origins: tuple[str, ...]
    ytdlp: str
    yta_function: str
    gallery_dl: str
    ffmpeg: str
    whisper_cli: str
    whisper_large_v3_model: Path | None
    farukstt_model: str
    prompt_file: Path | None
    ledger_file: Path | None
    worker_poll_seconds: float
    max_batch_size: int
    process_timeout_seconds: int
    worker_concurrency: int = 1
    # Organized copies of downloaded videos and prepared audio (None disables).
    media_root: Path | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.worker_concurrency <= 3:
            raise ValueError("WORKER_CONCURRENCY must be between 1 and 3")


def load_settings() -> Settings:
    origin_values = tuple(
        value.strip()
        for value in os.environ.get(
            "API_ORIGINS",
            "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:3001,http://localhost:3001",
        ).split(",")
        if value.strip()
    )
    prompt_value = os.environ.get("PIPELINE_PROMPT_FILE", "").strip()
    ledger_value = os.environ.get("PIPELINE_LEDGER_FILE", "").strip()
    return Settings(
        project_root=PROJECT_ROOT,
        database_path=_path("DATABASE_PATH", PROJECT_ROOT / "data" / "library.db"),
        artifact_root=_path("ARTIFACT_ROOT", PROJECT_ROOT / "data" / "runs"),
        allow_fixture_sources=_bool("ALLOW_FIXTURE_SOURCES", False),
        api_origins=origin_values,
        ytdlp=os.environ.get("YTDLP", "yt-dlp").strip() or "yt-dlp",
        yta_function=os.environ.get("YTA_FUNCTION", "yta").strip() or "yta",
        gallery_dl=os.environ.get("GALLERY_DL", "gallery-dl").strip() or "gallery-dl",
        ffmpeg=os.environ.get("FFMPEG", "ffmpeg").strip() or "ffmpeg",
        whisper_cli=os.environ.get("WHISPER_CLI", "whisper-cli").strip()
        or "whisper-cli",
        whisper_large_v3_model=Path(
            os.environ.get(
                "WHISPER_LARGE_V3_MODEL",
                "~/Library/Caches/whisper.cpp/ggml-large-v3.bin",
            )
        ).expanduser(),
        farukstt_model=os.environ.get("FARUKSTT_MODEL", "medyas/FarukSTT").strip()
        or "medyas/FarukSTT",
        prompt_file=Path(prompt_value).expanduser() if prompt_value else None,
        ledger_file=Path(ledger_value).expanduser() if ledger_value else None,
        worker_concurrency=1,
        worker_poll_seconds=float(os.environ.get("WORKER_POLL_SECONDS", "0.5")),
        max_batch_size=int(os.environ.get("MAX_BATCH_SIZE", "12")),
        process_timeout_seconds=int(os.environ.get("PROCESS_TIMEOUT_SECONDS", "3600")),
        media_root=_path("MEDIA_ROOT", Path.home() / "Documents" / "Reel Machine"),
    )
