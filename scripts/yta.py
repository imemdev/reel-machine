"""Portable Instagram/Facebook audio downloader (same options as scripts/yta).

Used automatically on Windows, where the zsh wrapper cannot run.
Usage: python scripts/yta.py URL [extra yt-dlp options]
"""
from __future__ import annotations

import subprocess
import sys

OPTIONS = [
    "--ignore-config", "--no-playlist",
    "--js-runtimes", "node",
    "--extractor-args", "youtube:player_client=web_embedded",
    "--retries", "10", "--fragment-retries", "10",
    "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0",
    "--embed-metadata", "--embed-thumbnail",
]


def main() -> int:
    return subprocess.call([sys.executable, "-m", "yt_dlp", *OPTIONS, *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
