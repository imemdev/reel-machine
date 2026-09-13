from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class Segment:
    start_ms: int
    end_ms: int
    text: str


def _parse_timestamp(value: str) -> int:
    normalized = value.replace(".", ",")
    hours, minutes, rest = normalized.split(":", 2)
    seconds, millis = rest.split(",", 1)
    return int(hours) * 3_600_000 + int(minutes) * 60_000 + int(seconds) * 1_000 + int(millis[:3].ljust(3, "0"))


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return _parse_timestamp(value)
        except (ValueError, IndexError):
            return None
    return None


def _raw_segments(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    if isinstance(payload.get("segments"), list):
        yield from (item for item in payload["segments"] if isinstance(item, dict))
        return
    if isinstance(payload.get("transcription"), list):
        yield from (item for item in payload["transcription"] if isinstance(item, dict))


def parse_whisper_json(path: Path) -> list[Segment]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    parsed: list[Segment] = []
    for item in _raw_segments(payload):
        timestamps = item.get("timestamps") if isinstance(item.get("timestamps"), dict) else {}
        offsets = item.get("offsets") if isinstance(item.get("offsets"), dict) else {}
        start = _as_int(offsets.get("from")) or _as_int(item.get("start_ms")) or _as_int(item.get("start")) or _as_int(timestamps.get("from"))
        end = _as_int(offsets.get("to")) or _as_int(item.get("end_ms")) or _as_int(item.get("end")) or _as_int(timestamps.get("to"))
        text = item.get("text")
        if start is None or end is None or not isinstance(text, str):
            continue
        text = text.strip()
        if not text:
            continue
        parsed.append(Segment(max(0, start), max(start + 1, end), text))
    if not parsed:
        raise ValueError("Whisper returned no timed speech segments.")
    return parsed


def parse_segments_json(path: Path) -> list[Segment]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("segments") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("Transcript JSON must contain a segments list.")
    result: list[Segment] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        start = _as_int(item.get("start_ms"))
        end = _as_int(item.get("end_ms"))
        if start is None or end is None or not item["text"].strip():
            continue
        result.append(Segment(max(0, start), max(start + 1, end), item["text"].strip()))
    if not result:
        raise ValueError("Transcript JSON contains no usable segments.")
    return result


def timestamp(ms: int, *, decimal: str = ",") -> str:
    ms = max(0, int(ms))
    hours, remainder = divmod(ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{decimal}{millis:03d}"


def to_srt(segments: Iterable[Segment]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(f"{index}\n{timestamp(segment.start_ms)} --> {timestamp(segment.end_ms)}\n{segment.text}")
    return "\n\n".join(blocks).rstrip() + "\n\n"


def to_vtt(segments: Iterable[Segment]) -> str:
    blocks = []
    for segment in segments:
        blocks.append(f"{timestamp(segment.start_ms, decimal='.')} --> {timestamp(segment.end_ms, decimal='.')}\n{segment.text}")
    return "WEBVTT\n\n" + "\n\n".join(blocks).rstrip() + "\n\n"


def to_text(segments: Iterable[Segment]) -> str:
    return "\n".join(segment.text for segment in segments).rstrip() + "\n"


def to_timestamped_text(segments: Iterable[Segment]) -> str:
    return "\n".join(f"[{timestamp(segment.start_ms)[:-4]}] {segment.text}" for segment in segments) + "\n"


def validate_segments(segments: list[Segment]) -> None:
    if not segments:
        raise ValueError("A transcript needs at least one segment.")
    previous = -1
    for segment in segments:
        if segment.start_ms < 0 or segment.end_ms <= segment.start_ms:
            raise ValueError("Each segment must have a non-negative start before its end.")
        if segment.start_ms < previous:
            raise ValueError("Transcript segments must be ordered by start time.")
        if not segment.text.strip():
            raise ValueError("Transcript segments cannot be empty.")
        previous = segment.start_ms


def segments_to_json(segments: Iterable[Segment]) -> list[dict[str, Any]]:
    return [{"start_ms": item.start_ms, "end_ms": item.end_ms, "text": item.text} for item in segments]
