"""Small persistent cover images, stored alongside each video's artifacts."""
from __future__ import annotations

import hashlib
import ipaddress
import socket
import ssl

import certifi
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .db import NotFoundError, Repository

MAX_BYTES = 5 * 1024 * 1024


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid thumbnail URL")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Thumbnail must use a public address")


class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def image_type(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("Unsupported thumbnail image")


def download_thumbnail(url: str) -> bytes:
    validate_url(url)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
    with build_opener(PublicRedirects(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))).open(request, timeout=8) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Thumbnail is too large")
    image_type(data)
    return data


def saved_thumbnail(repository: Repository, video_id: str) -> tuple[bytes, str]:
    video = repository.hydrate_video(video_id)
    url = video.get("display_thumbnail_url") or video.get("captured_thumbnail_url")
    if not url or not repository.artifact_root:
        raise ValueError("No thumbnail available")
    target = repository.artifact_root / video_id / ("thumbnail-" + hashlib.sha256(url.encode()).hexdigest()[:20])
    # Keep deletion and cache writes mutually exclusive via the database transaction.
    with repository.connection() as connection:
        repository.begin(connection)
        repository._video_row(connection, video_id)
        if target.is_file():
            data = target.read_bytes()
            return data, image_type(data)
    data = download_thumbnail(url)
    with repository.connection() as connection:
        repository.begin(connection)
        repository._video_row(connection, video_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        connection.commit()
    return data, image_type(data)


def cache_thumbnail(repository: Repository, video_id: str) -> None:
    # A missing/expired cover must never prevent saving or processing the video.
    try:
        saved_thumbnail(repository, video_id)
    except (OSError, ValueError, NotFoundError):
        pass
