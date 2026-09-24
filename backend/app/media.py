"""Video download commands and the user-facing media folder.

Processing works inside ARTIFACT_ROOT (checkpoints, logs, partial files). Once a
video has been downloaded and its audio prepared, a clean copy of each is placed
in MEDIA_ROOT so people can browse them in Finder / File Explorer:

    <MEDIA_ROOT>/Videos/<Platform>/<YYYY-MM-DD> <title> [<id>].mp4
    <MEDIA_ROOT>/Audio/<Platform>/<YYYY-MM-DD> <title> [<id>].wav

Both files share the same name, so a video and its audio are easy to pair.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

from . import procs

VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".opus", ".ogg", ".aac"}
PLATFORM_FOLDERS = {"youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok", "facebook": "Facebook"}
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def folder_for(platform: str) -> str:
    return PLATFORM_FOLDERS.get(platform, platform.title() or "Other")


def safe_name(value: str, *, limit: int = 70) -> str:
    """A readable, cross-platform file-name fragment (keeps Arabic and emoji)."""
    text = unicodedata.normalize("NFC", value or "")
    text = _UNSAFE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text.strip(" .") or "video"


def media_basename(video: dict[str, Any]) -> str:
    date = str(video.get("saved_at") or "")[:10] or "undated"
    title = video.get("display_title") or video.get("captured_title") or video.get("canonical_id") or "video"
    identity = safe_name(str(video.get("canonical_id") or video.get("id")), limit=40)
    return f"{date} {safe_name(str(title))} [{identity}]"


def media_dirs(root: Path) -> dict[str, Path]:
    return {"root": root, "videos": root / "Videos", "audio": root / "Audio"}


def _place(source: Path, destination: Path) -> Path:
    """Put ``source`` at ``destination`` without duplicating bytes when possible."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size == source.stat().st_size:
        return destination
    temporary = destination.with_name(destination.name + ".partial")
    if temporary.exists():
        temporary.unlink()
    try:
        os.link(source, temporary)  # same disk: instant, no extra space
    except OSError:
        shutil.copy2(source, temporary)
    os.replace(temporary, destination)
    return destination


def export_media(root: Path, video: dict[str, Any], *, video_file: Path | None, audio_file: Path | None) -> dict[str, Path | None]:
    """Copy/link the downloaded video and prepared audio into the media folder."""
    base = media_basename(video)
    platform = folder_for(str(video.get("platform") or ""))
    dirs = media_dirs(root)
    exported: dict[str, Path | None] = {"video": None, "audio": None}
    if video_file and video_file.is_file() and video_file.suffix.lower() in VIDEO_SUFFIXES:
        exported["video"] = _place(video_file, dirs["videos"] / platform / f"{base}{video_file.suffix.lower()}")
    if audio_file and audio_file.is_file():
        exported["audio"] = _place(audio_file, dirs["audio"] / platform / f"{base}{audio_file.suffix.lower()}")
    return exported


def has_video_stream(path: Path, ffmpeg: str) -> bool | None:
    """Return whether ``path`` contains a video stream (None if unknown)."""
    probe = shutil.which(str(Path(ffmpeg).with_name("ffprobe"))) if os.path.isabs(ffmpeg) else None
    probe = probe or shutil.which("ffprobe")
    if not probe:
        return None
    try:
        completed = subprocess.run(
            [probe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return "video" in completed.stdout


def ytdlp_prefix(configured: str) -> list[str]:
    """Run yt-dlp from this Python environment when available (works everywhere)."""
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    found = shutil.which(configured)
    if found:
        return [found]
    from .pipeline import PipelineError

    raise PipelineError("tool_missing", "yt-dlp is not installed. Install the `downloads` extra, then retry.")


def video_download_command(*, ytdlp: str, ffmpeg: str | None, source_url: str, output: Path) -> list[str]:
    """Download the full video (not just audio) as a widely playable MP4."""
    command = [
        *ytdlp_prefix(ytdlp),
        "--ignore-config", "--no-playlist", "--no-progress", "--newline",
        # Best video up to 1080p + best audio; H.264/AAC first so QuickTime and
        # Windows Media Player can open the file.
        "-f", "bv*+ba/b",
        "-S", "vcodec:h264,res:1080,acodec:aac",
        "--merge-output-format", "mp4",
        "--retries", "10", "--fragment-retries", "10",
        "--embed-metadata",
        "-o", str(output),
    ]
    if ffmpeg:
        command.extend(["--ffmpeg-location", ffmpeg])
    if shutil.which("node"):
        command.extend(["--js-runtimes", "node"])
    command.append(source_url)
    return command


def open_path(path: Path, *, reveal: bool = False) -> None:
    """Open a file/folder with the system app, or reveal it in Finder/Explorer."""
    target = path.resolve()
    if not target.exists():
        raise FileNotFoundError(str(target))
    if procs.IS_WINDOWS:
        if reveal:
            subprocess.Popen(["explorer", f"/select,{target}"])
        else:
            os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)] if reveal else ["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target.parent if reveal else target)])
