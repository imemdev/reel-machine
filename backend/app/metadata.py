from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

from .media import ytdlp_prefix
from .pipeline import PRIVATE_VIDEO_MESSAGE, PipelineError, gallery_dl_command
from .settings import Settings
from .urls import URLValidationError, VideoIdentity, canonicalize_url


def _private_error(output: str) -> bool:
    return bool(re.search(r"(?:private video|this video is private|followers[- ]only)", output, re.I))


def _parse_json(output: str) -> dict[str, Any] | None:
    try:
        value = json.loads(output)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        for line in reversed(output.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None


def _parse_gallery_json(output: str) -> dict[str, Any] | None:
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, list) and len(item) >= 2 and isinstance(item[1], dict):
                return item[1]
    return value if isinstance(value, dict) else None


def _inspect_tiktok_with_gallery_dl(identity: VideoIdentity, settings: Settings) -> dict[str, Any] | None:
    try:
        command = gallery_dl_command(
            gallery_dl=settings.gallery_dl,
            source_url=identity.source_url,
            directory=settings.artifact_root,
            dump_json=True,
        )
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=25,
        )
    except (PipelineError, OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return _parse_gallery_json(completed.stdout)


def inspect_video(url: str, settings: Settings) -> dict[str, Any]:
    identity = canonicalize_url(url, allow_fixture=settings.allow_fixture_sources)
    base: dict[str, Any] = {
        "url": identity.source_url,
        "canonical_url": identity.canonical_url,
        "canonical_id": identity.canonical_id,
        "platform": identity.platform,
        "status": "unknown",
        "title": None,
        "creator": None,
        "thumbnail_url": None,
        "source_page_url": identity.source_url,
        "duration_ms": None,
        "metadata_source": None,
        "message": "We couldn't load metadata yet. You can still save the link and retry processing later.",
    }
    if identity.platform == "fixture":
        base.update(
            {
                "status": "ready",
                "title": "Tunisian transcript test fixture",
                "creator": "Local test source",
                "metadata_source": "test fixture",
                "message": "Test-only source. It does not prove platform retrieval or transcription accuracy.",
            }
        )
        return base

    if identity.platform == "tiktok":
        payload = _inspect_tiktok_with_gallery_dl(identity, settings)
        if payload:
            author = payload.get("author") if isinstance(payload.get("author"), dict) else {}
            video = payload.get("video") if isinstance(payload.get("video"), dict) else {}
            duration = video.get("duration")
            title = payload.get("desc") or f"TikTok video {identity.canonical_id}"
            creator = author.get("nickname") or author.get("uniqueId") or payload.get("textLanguage")
            thumbnail = video.get("originCover") or video.get("cover") or video.get("dynamicCover")
            if payload.get("privateItem") or author.get("privateAccount"):
                base.update({"status": "private", "message": PRIVATE_VIDEO_MESSAGE})
            else:
                base.update(
                    {
                        "status": "ready",
                        "title": title,
                        "creator": creator,
                        "thumbnail_url": thumbnail,
                        "source_page_url": identity.source_url,
                        "duration_ms": int(float(duration) * 1000) if isinstance(duration, (int, float, str)) and str(duration).replace(".", "", 1).isdigit() else None,
                        "metadata_source": "gallery-dl TikTok extractor",
                        "message": "Metadata detected through the local TikTok fallback. Verify the source before saving.",
                    }
                )
            return base

    try:
        prefix = ytdlp_prefix(settings.ytdlp)
    except PipelineError:
        base["message"] = "yt-dlp is not available for metadata inspection. The link can still be saved."
        return base
    command = [
        *prefix,
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
    ]
    if shutil.which("node"):
        command.extend(["--js-runtimes", "node"])
    command.append(identity.source_url)
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=25,
        )
    except subprocess.TimeoutExpired:
        base["message"] = "Metadata lookup timed out. You can still save the link and retry processing later."
        return base
    output = f"{completed.stdout}\n{completed.stderr}"
    if _private_error(output):
        base.update({"status": "private", "message": PRIVATE_VIDEO_MESSAGE})
        return base
    payload = _parse_json(completed.stdout)
    if completed.returncode != 0 or payload is None:
        return base
    duration = payload.get("duration")
    base.update(
        {
            "status": "ready",
            "title": payload.get("title") or payload.get("fulltitle"),
            "creator": payload.get("uploader") or payload.get("channel") or payload.get("creator"),
            "thumbnail_url": payload.get("thumbnail"),
            "source_page_url": payload.get("webpage_url") or identity.source_url,
            "duration_ms": int(float(duration) * 1000) if isinstance(duration, (int, float)) else None,
            "metadata_source": "yt-dlp",
            "message": "Metadata detected. Verify the source before saving.",
        }
    )
    return base
