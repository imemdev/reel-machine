from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


class URLValidationError(ValueError):
    def __init__(self, message: str, code: str = "invalid_url") -> None:
        super().__init__(message)
        self.code = code


SUPPORTED_PLATFORMS = ("instagram", "facebook", "tiktok")
TRACKING_QUERY_KEYS = {"igsh", "igshid", "si", "utm_source", "utm_medium", "utm_campaign"}


@dataclass(frozen=True)
class VideoIdentity:
    platform: str
    canonical_id: str
    canonical_url: str
    source_url: str


def _host(parsed) -> str:
    return (parsed.hostname or "").lower().rstrip(".")


def _clean_path(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _canonical_url(platform: str, canonical_id: str, parsed) -> str:
    if platform == "instagram":
        prefix = "reel"
    elif platform == "tiktok":
        prefix = "video"
    else:
        prefix = "watch"
    if platform == "facebook" and canonical_id.startswith("fbwatch-"):
        return f"https://fb.watch/{canonical_id.removeprefix('fbwatch-')}/"
    return f"https://{platform}.com/{prefix}/{canonical_id}/"


def canonicalize_url(value: str, *, allow_fixture: bool = False) -> VideoIdentity:
    source_url = value.strip()
    if not source_url:
        raise URLValidationError("Paste a public Facebook, Instagram, or TikTok video URL.")
    if source_url.startswith("fixture://"):
        if not allow_fixture:
            raise URLValidationError(
                "Fixture sources are disabled. Use a public social-video URL.",
                "fixture_disabled",
            )
        name = source_url.removeprefix("fixture://").strip().strip("/")
        if not re.fullmatch(r"[a-z0-9-]{3,80}", name):
            raise URLValidationError("This fixture name is not valid.")
        return VideoIdentity(
            platform="fixture",
            canonical_id=name,
            canonical_url=f"fixture://{name}",
            source_url=source_url,
        )

    parsed = urlparse(source_url)
    host = _host(parsed)
    if parsed.scheme not in {"http", "https"}:
        raise URLValidationError("Use a full http:// or https:// video URL.")

    if host == "instagram.com" or host.endswith(".instagram.com"):
        platform = "instagram"
        parts = _clean_path(parsed.path)
        if len(parts) >= 2 and parts[0] in {"reel", "reels", "p", "tv"}:
            canonical_id = parts[1]
        else:
            raise URLValidationError(
                "Use an individual Instagram Reel or video post URL.",
                "unsupported_url_surface",
            )
    elif host in {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"} or host.endswith(
        ".facebook.com"
    ):
        platform = "facebook"
        parts = _clean_path(parsed.path)
        query = parse_qs(parsed.query)
        if host == "fb.watch" and parts:
            canonical_id = f"fbwatch-{parts[0]}"
        elif query.get("v"):
            canonical_id = query["v"][0]
        elif len(parts) >= 2 and parts[0] in {"reel", "reels", "videos", "watch"}:
            canonical_id = parts[1]
        elif len(parts) >= 3 and parts[-2] in {"videos", "reels"}:
            canonical_id = parts[-1]
        else:
            raise URLValidationError(
                "Use an individual Facebook Reel, video, or watch URL.",
                "unsupported_url_surface",
            )
    elif host == "tiktok.com" or host.endswith(".tiktok.com"):
        platform = "tiktok"
        parts = _clean_path(parsed.path)
        if len(parts) >= 3 and parts[-2] == "video":
            canonical_id = parts[-1]
        elif len(parts) == 1 and parts[0]:
            canonical_id = f"short-{parts[0]}"
        else:
            raise URLValidationError(
                "Use an individual TikTok video URL.",
                "unsupported_url_surface",
            )
    else:
        raise URLValidationError(
            "This platform is not supported. Use Facebook, Instagram, or TikTok.",
            "unsupported_platform",
        )

    canonical_id = re.sub(r"[^A-Za-z0-9_.:-]", "", canonical_id)
    if not canonical_id or len(canonical_id) > 240:
        raise URLValidationError("The video URL does not contain a usable video identity.")
    query = parse_qs(parsed.query, keep_blank_values=True)
    clean_query = [(key, item) for key, values in query.items() if key not in TRACKING_QUERY_KEYS for item in values]
    canonical_source = urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", urlencode(clean_query), "")
    )
    return VideoIdentity(
        platform=platform,
        canonical_id=canonical_id,
        canonical_url=_canonical_url(platform, canonical_id, parsed),
        source_url=canonical_source,
    )


def stable_id_for_url(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:16]

