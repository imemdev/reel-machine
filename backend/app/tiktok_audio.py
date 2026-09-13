"""Process-local gallery-dl adapter: prefer the video's own audio, not music.

gallery-dl 1.32.12 sorts TikTok streams by resolution, including video-only
DASH. Keep its extraction, cookies and HTTP downloader but select audio-bearing
stream URLs. This private integration is pinned and covered by selector tests.
"""
from __future__ import annotations

from typing import Any


def audio_urls(video: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    tracks = video.get("bitrateAudioInfo") or []
    if isinstance(tracks, dict):
        tracks = [tracks]
    for track in sorted(tracks, key=lambda item: int(item.get("Bitrate") or 0), reverse=True):
        addresses = track.get("UrlList") or {}
        if isinstance(addresses, dict):
            urls.extend(addresses.get(key) for key in ("MainUrl", "BackupUrl", "FallbackUrl"))
        elif isinstance(addresses, list):
            urls.extend(addresses)
    variants = video.get("bitrateInfo") or []
    if isinstance(variants, dict):
        variants = [variants]
    for variant in variants:
        if str(variant.get("Format", "")).lower() == "mp4":
            urls.extend((variant.get("PlayAddr") or {}).get("UrlList") or [])
    urls.extend([video.get("playAddr"), video.get("downloadAddr")])
    return list(dict.fromkeys(url for url in urls if isinstance(url, str) and url.startswith("https://")))


def main() -> None:
    import gallery_dl
    from gallery_dl.extractor.tiktok import TiktokExtractor

    TiktokExtractor._extract_video_urls = lambda self, video: audio_urls(video)
    gallery_dl.main()


if __name__ == "__main__":
    main()
