from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import wave
import traceback
from datetime import datetime, timezone
from time import monotonic
from dataclasses import dataclass
from hashlib import sha256 as digest_sha256
from pathlib import Path
from typing import Any

from .db import STAGE_ORDER, Repository
from .settings import Settings
from .storage import ArtifactStore, sha256
from .transcripts import Segment, parse_segments_json, parse_whisper_json, segments_to_json, to_srt, to_text, to_vtt


UNSUPPORTED_LANGUAGE_MESSAGE = (
    "This application currently supports Tunisian Arabic videos only. "
    "To request another language, email medimemhamdi18@gmail.com."
)
UNCERTAIN_LANGUAGE_MESSAGE = "We couldn’t confidently identify Tunisian Arabic."
PRIVATE_VIDEO_MESSAGE = "This video is private. We can only access public videos."
UNKNOWN_ACCESS_MESSAGE = "We couldn't access this video."


MODEL_OPTIONS: dict[str, dict[str, str]] = {
    "farukstt": {
        "label": "FarukSTT",
        "description": "Tunisian Derja fine-tune for Arabic + French + English code-switching.",
        "source": "medyas/FarukSTT",
    },

}


class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ModelSelection:
    key: str
    label: str
    source: str


def model_selection(settings: Settings, key: str) -> ModelSelection:
    if key != "farukstt":
        raise PipelineError("unknown_model", "Only FarukSTT is supported for this Tunisian Arabic workspace.")
    return ModelSelection(key, MODEL_OPTIONS[key]["label"], settings.farukstt_model)


def _local_faruk_ready(source: str) -> bool:
    directory = Path(source).expanduser()
    if not all((directory / name).is_file() for name in ("config.json", "preprocessor_config.json", "tokenizer_config.json")):
        return False
    if (directory / "model.safetensors").is_file():
        return True
    try:
        index = json.loads((directory / "model.safetensors.index.json").read_text())
        shards = set(index["weight_map"].values())
        return bool(shards) and all((directory / shard).is_file() for shard in shards)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def model_catalog(settings: Settings) -> list[dict[str, Any]]:
    faruk_dependencies = (
        importlib.util.find_spec("transformers") is not None
        and importlib.util.find_spec("torch") is not None
    )
    faruk_ready = faruk_dependencies and _local_faruk_ready(settings.farukstt_model)
    return [
        {
            "key": "farukstt",
            **MODEL_OPTIONS["farukstt"],
            "source": settings.farukstt_model,
            "available": faruk_ready,
            "availability_note": (
                "Local Transformers runtime and model files found."
                if faruk_ready
                else "Install the FarukSTT runtime and set FARUKSTT_MODEL to a complete local model directory."
            ),
        },

    ]


def _command_path(command: str) -> str:
    path = command if os.path.isabs(command) else None
    if path and Path(path).is_file():
        return path
    from shutil import which

    resolved = which(command)
    if not resolved:
        raise PipelineError("tool_missing", f"Required local command is not available: {command}")
    return resolved


def _run_logged(command: list[str], log_path: Path, *, timeout: int) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"$ {shlex.join(command)}\n\n")
        log.flush()
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            log.write(f"\nTimed out after {timeout} seconds.\n")
            raise PipelineError("tool_timeout", f"Local processing timed out: {command[0]}", retryable=True) from error
        log.write(f"\nExit code: {completed.returncode}\n")
    if completed.returncode != 0:
        content = log_path.read_text(encoding="utf-8", errors="replace")
        if Path(command[0]).name == "ffmpeg" and "matches no streams" in content and "0:a:0" in content:
            raise PipelineError(
                "audio_stream_missing",
                "The downloaded file has no audio track. Transcription cannot start. "
                "The downloader may have selected a video-only version; downloading an audio-bearing version is required. "
                "Retrying this same file will not help. See debug logs for FFmpeg details.",
            )
        classified = _extract_error_code(log_path)
        if classified:
            raise PipelineError(*classified)
        raise PipelineError(
            "tool_failed",
            f"{Path(command[0]).name} stopped with exit code {completed.returncode}. "
            f"Open debug logs and check {log_path.name} for the tool's explanation.",
            retryable=True,
        )


def _fingerprint(*values: str | None) -> str:
    payload = "|".join(value or "" for value in values)
    return digest_sha256(payload.encode("utf-8")).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PipelineError("artifact_invalid", f"Could not read checkpoint artifact {path.name}.") from error
    if not isinstance(value, dict):
        raise PipelineError("artifact_invalid", f"Checkpoint artifact {path.name} is not an object.")
    return value


def _fixture_segments(name: str) -> list[Segment]:
    if name in {"english-demo", "french-demo", "uncertain-demo", "private-demo", "unknown-demo"}:
        return []
    return [
        Segment(0, 4_760, "هذه عقلة تونسية تجريبية، نخلط فيها كلمة programme و flashcards."),
        Segment(4_760, 10_200, "إذا كانت كلمة غير واضحة، نخليها معلّمة وما نخمنوش فيها."),
        Segment(10_200, 15_800, "هذا transcript تجريبي باش نختبرو الحفظ والتعديل والتصدير."),
    ]


def _write_silent_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16_000)
        handle.writeframes(b"\x00\x00" * 1_600)


def _extract_error_code(log_path: Path) -> tuple[str, str] | None:
    if not log_path.is_file():
        return None
    content = log_path.read_text(encoding="utf-8", errors="replace")
    private = re.search(r"(?:private video|this video is private|followers[- ]only)", content, re.I)
    if private:
        return "private_video", PRIVATE_VIDEO_MESSAGE
    return None


def yta_command(*, yta_function: str, source_url: str, output: Path) -> list[str]:
    """Build the login-shell invocation that preserves the owner's working yta path."""
    if os.environ.get("KITE_DESKTOP_TOKEN"):
        return [_command_path(yta_function), source_url, "--output", str(output)]
    return [
        "zsh",
        "-lic",
        f'{yta_function} "$@"',
        "local-video-library",
        source_url,
        "--output",
        str(output),
    ]


def gallery_dl_command(*, gallery_dl: str, source_url: str, directory: Path, dump_json: bool = False) -> list[str]:
    """Build a local gallery-dl command for TikTok's current public-page path."""
    parts = shlex.split(gallery_dl)
    if not parts:
        raise PipelineError("tool_missing", "GALLERY_DL is empty; configure gallery-dl or uvx gallery-dl.")
    try:
        executable = _command_path(parts[0])
        prefix = [executable, *parts[1:]]
    except PipelineError:
        if parts == ["gallery-dl"] and importlib.util.find_spec("gallery_dl") is not None:
            prefix = [sys.executable, "-m", "gallery_dl"]
        else:
            raise
    command = [*prefix, "--config-ignore", "--no-colors"]
    if dump_json:
        command.extend(["--dump-json", source_url])
    else:
        command.extend(["--directory", str(directory), "--no-mtime", "--no-part", source_url])
    return command


def tiktok_audio_command(*, source_url: str, directory: Path) -> list[str]:
    if importlib.util.find_spec("gallery_dl") is None:
        raise PipelineError("tool_missing", "Install the approved downloads extra before processing TikTok videos.")
    return [
        sys.executable,
        str(Path(__file__).with_name("tiktok_audio.py")),
        "--config-ignore", "--no-colors", "--directory", str(directory),
        "--no-mtime", "--no-part", source_url,
    ]


class PipelineRunner:
    def __init__(
        self,
        *,
        repository: Repository,
        artifacts: ArtifactStore,
        settings: Settings,
        failure_plan: dict[str, int] | None = None,
    ) -> None:
        self.repository = repository
        self.artifacts = artifacts
        self.settings = settings
        self.failure_plan = failure_plan or {}

    def _event(self, video: dict[str, Any], run: dict[str, Any], step: str, status: str, **details: Any) -> None:
        event = {"timestamp": datetime.now(timezone.utc).isoformat(), "run_id": run["id"],
                 "model_key": run["model_key"], "step": step, "status": status, **details}
        line = json.dumps(event, ensure_ascii=False) + "\n"
        for path in (self.artifacts.run_dir(video["id"], run["id"]) / "pipeline.jsonl",
                     self.artifacts.step_dir(video["id"], run["id"], step) / "step.log"):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)

    def _execute_step(self, video: dict[str, Any], run: dict[str, Any], step: str, action: Any) -> dict[str, Any]:
        self.repository.set_run_step(run["id"], step)
        self._event(video, run, step, "started")
        started = monotonic()
        self._maybe_fail(step)
        checkpoint = self._reuse(video, run, step)
        result = checkpoint or action()
        self._event(video, run, step, "reused" if checkpoint else "succeeded",
                    duration_seconds=round(monotonic() - started, 3), artifact_path=result["artifact_path"])
        if step == "transcribe" and not checkpoint and video["platform"] != "fixture":
            duration = self.repository.hydrate_video(video["id"])["duration_ms"]
            if duration and duration > 0:
                self.repository.record_transcription_time(run["id"], monotonic() - started, duration)
        return result

    def _maybe_fail(self, step: str) -> None:
        remaining = self.failure_plan.get(step, 0)
        if remaining > 0:
            self.failure_plan[step] = remaining - 1
            raise PipelineError("injected_failure", f"Injected test failure at {step}.", retryable=True)

    def _reuse(self, video: dict[str, Any], run: dict[str, Any], step: str) -> dict[str, Any] | None:
        checkpoint = self.repository.checkpoint(video["id"], step)
        if not checkpoint:
            return None
        if step in {"transcribe", "format"}:
            metadata = json.loads(checkpoint["metadata_json"])
            if metadata.get("model_key") != run["model_key"]:
                return None
        path = Path(checkpoint["artifact_path"])
        if not self.artifacts.valid(path, checkpoint["artifact_sha256"]):
            return None
        return checkpoint

    def _save(
        self,
        *,
        video: dict[str, Any],
        run: dict[str, Any],
        step: str,
        artifact: Path,
        metadata: dict[str, Any],
        input_fingerprint: str,
    ) -> dict[str, Any]:
        self.repository.save_checkpoint(
            video_id=video["id"],
            run_id=run["id"],
            step=step,
            artifact_path=artifact,
            artifact_sha256=sha256(artifact),
            input_fingerprint=input_fingerprint,
            metadata=metadata,
        )
        return {"artifact_path": str(artifact), "metadata": metadata}

    def _inspect(self, video: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        path = self.artifacts.step_dir(video["id"], run["id"], "inspect") / "metadata.json"
        payload = {
            "source_url": video["source_url"],
            "canonical_url": video["canonical_url"],
            "platform": video["platform"],
            "canonical_id": video["canonical_id"],
            "title": video["display_title"],
            "creator": video["display_creator"],
            "thumbnail_url": video["display_thumbnail_url"],
            "captured_at": video["updated_at"],
        }
        self.artifacts.write_json(path, payload)
        return self._save(video=video, run=run, step="inspect", artifact=path, metadata=payload, input_fingerprint=_fingerprint(video["source_url"]))

    def _download(self, video: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        step_dir = self.artifacts.step_dir(video["id"], run["id"], "download")
        if video["platform"] == "fixture":
            source = step_dir / "source-fixture.txt"
            source.write_text("TEST-ONLY FIXTURE SOURCE\n", encoding="utf-8")
            metadata = {"path": str(source), "kind": "test_fixture", "embedded_metadata": False}
            self.repository.set_media_paths(video["id"], media_path=source, audio_path=None)
            return self._save(video=video, run=run, step="download", artifact=source, metadata=metadata, input_fingerprint=_fingerprint(video["source_url"]))

        output = step_dir / "source.%(ext)s"
        if video["platform"] == "tiktok":
            command = tiktok_audio_command(
                source_url=video["source_url"],
                directory=step_dir,
            )
        else:
            command = yta_command(
                yta_function=self.settings.yta_function,
                source_url=video["source_url"],
                output=output,
            )
        log_path = step_dir / "download.log"
        _run_logged(command, log_path, timeout=self.settings.process_timeout_seconds)
        candidates = [
            item
            for item in step_dir.iterdir()
            if item.is_file() and item.suffix.lower() in {".mp3", ".m4a", ".wav", ".webm", ".mp4", ".mkv", ".mov", ".opus"}
        ]
        if not candidates:
            classified = _extract_error_code(log_path)
            if classified:
                raise PipelineError(classified[0], classified[1])
            raise PipelineError("access_unknown", UNKNOWN_ACCESS_MESSAGE, retryable=True)
        source = max(candidates, key=lambda item: item.stat().st_size)
        if video["platform"] == "tiktok":
            # Reject video-only/HTML downloads before recording a reusable checkpoint.
            _run_logged([
                _command_path(self.settings.ffmpeg), "-nostdin", "-hide_banner",
                "-loglevel", "error", "-i", str(source), "-map", "0:a:0",
                "-t", "0.1", "-f", "null", "-",
            ], step_dir / "validate_audio.log", timeout=self.settings.process_timeout_seconds)
        metadata = {
            "path": str(source),
            "kind": "tiktok_audio_bearing_media" if video["platform"] == "tiktok" else "yta_audio",
            "downloader": "gallery-dl 1.32.12 + local audio selector" if video["platform"] == "tiktok" else self.settings.yta_function,
            "embedded_metadata": video["platform"] != "tiktok",
            "embedded_thumbnail": video["platform"] != "tiktok",
            "extractor_args": "youtube:player_client=web_embedded" if video["platform"] != "tiktok" else None,
        }
        self.repository.set_media_paths(video["id"], media_path=source, audio_path=None)
        return self._save(video=video, run=run, step="download", artifact=source, metadata=metadata, input_fingerprint=_fingerprint(video["source_url"]))

    def _prepare_audio(self, video: dict[str, Any], run: dict[str, Any], download: dict[str, Any]) -> dict[str, Any]:
        destination = self.artifacts.step_dir(video["id"], run["id"], "prepare_audio") / "audio-16k-mono.wav"
        if video["platform"] == "fixture":
            _write_silent_wav(destination)
        else:
            command = [
                _command_path(self.settings.ffmpeg),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                download["artifact_path"],
                "-map",
                "0:a:0",
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ]
            _run_logged(command, destination.parent / "ffmpeg.log", timeout=self.settings.process_timeout_seconds)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise PipelineError("audio_prepare_failed", "FFmpeg produced no usable audio.", retryable=True)
        if video["platform"] != "fixture":
            with wave.open(str(destination), "rb") as audio_file:
                self.repository.set_audio_duration(video["id"], round(audio_file.getnframes() / audio_file.getframerate() * 1000))
        self.repository.set_media_paths(video["id"], media_path=Path(download["artifact_path"]), audio_path=destination)
        metadata = {"path": str(destination), "sample_rate": 16_000, "channels": 1}
        return self._save(video=video, run=run, step="prepare_audio", artifact=destination, metadata=metadata, input_fingerprint=_fingerprint(download["artifact_path"]))

    def _check_language(self, video: dict[str, Any], run: dict[str, Any], audio: dict[str, Any]) -> dict[str, Any]:
        fixture = video["canonical_id"]
        if fixture == "private-demo":
            raise PipelineError("private_video", PRIVATE_VIDEO_MESSAGE)
        if fixture in {"english-demo", "french-demo"}:
            raise PipelineError("unsupported_language", UNSUPPORTED_LANGUAGE_MESSAGE)
        if fixture == "uncertain-demo":
            raise PipelineError("uncertain_language", UNCERTAIN_LANGUAGE_MESSAGE, retryable=False)
        if fixture == "unknown-demo":
            raise PipelineError("access_unknown", UNKNOWN_ACCESS_MESSAGE, retryable=True)
        if not bool(run["owner_asserted"]):
            raise PipelineError(
                "tunisian_confirmation_required",
                "Confirm that this video is primarily Tunisian Arabic before processing.",
            )
        path = self.artifacts.step_dir(video["id"], run["id"], "check_language") / "eligibility.json"
        payload = {
            "outcome": "owner_assertion",
            "language": "ar",
            "validated": False,
            "owner_asserted": True,
            "note": "No dialect classifier is bundled; this is not Tunisian-language proof.",
            "audio_path": audio["artifact_path"],
        }
        self.artifacts.write_json(path, payload)
        return self._save(video=video, run=run, step="check_language", artifact=path, metadata=payload, input_fingerprint=_fingerprint(audio["artifact_path"], str(run["owner_asserted"])))

    def _transcribe_farukstt(self, audio_path: Path, raw_path: Path) -> list[Segment]:
        if importlib.util.find_spec("transformers") is None or importlib.util.find_spec("torch") is None:
            raise PipelineError(
                "farukstt_not_installed",
                "FarukSTT needs the optional local Transformers runtime. Install the `faruk` extra and retry.",
            )
        try:
            from transformers import pipeline as transformers_pipeline
            import torch

            device = "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else -1
            recognizer = transformers_pipeline(
                "automatic-speech-recognition",
                model=self.settings.farukstt_model,
                device=device,
            )
            result = recognizer(
                str(audio_path),
                return_timestamps=True,
                chunk_length_s=30,
                stride_length_s=(5, 2),
            )
        except PipelineError:
            raise
        except Exception as error:
            raise PipelineError("farukstt_failed", f"FarukSTT could not run locally: {error}", retryable=True) from error
        raw_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        chunks = result.get("chunks", []) if isinstance(result, dict) else []
        segments: list[Segment] = []
        for chunk in chunks:
            if not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str):
                continue
            timestamps = chunk.get("timestamp")
            if not isinstance(timestamps, (list, tuple)) or len(timestamps) != 2 or timestamps[0] is None or timestamps[1] is None:
                continue
            start = max(0, int(float(timestamps[0]) * 1000))
            end = max(start + 1, int(float(timestamps[1]) * 1000))
            if chunk["text"].strip():
                segments.append(Segment(start, end, chunk["text"].strip()))
        if not segments:
            raise PipelineError("farukstt_no_timestamps", "FarukSTT returned no usable timestamped segments.")
        return segments

    def _transcribe(self, video: dict[str, Any], run: dict[str, Any], audio: dict[str, Any]) -> dict[str, Any]:
        step_dir = self.artifacts.step_dir(video["id"], run["id"], "transcribe")
        raw_path = step_dir / "transcript.raw.json"
        if video["platform"] == "fixture":
            segments = _fixture_segments(video["canonical_id"])
            if not segments:
                raise PipelineError("no_speech", "No supported speech was found in this test fixture.")
            raw_path.write_text(json.dumps({"segments": segments_to_json(segments), "test_only": True}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        elif run["model_key"] == "farukstt":
            segments = self._transcribe_farukstt(Path(audio["artifact_path"]), raw_path)
        else:
            raise PipelineError("unsupported_model", "Reprocess this video with FarukSTT.")
        normalized = step_dir / "segments.json"
        self.artifacts.write_json(normalized, {"segments": segments_to_json(segments), "model_key": run["model_key"]})
        manifest = step_dir / "manifest.json"
        self.artifacts.write_json(
            manifest,
            {
                "raw_json": str(raw_path),
                "segments_json": str(normalized),
                "model_key": run["model_key"],
                "raw_sha256": sha256(raw_path),
            },
        )
        return self._save(video=video, run=run, step="transcribe", artifact=manifest, metadata={"manifest": str(manifest), "raw_json": str(raw_path), "segments_json": str(normalized), "model_key": run["model_key"]}, input_fingerprint=_fingerprint(audio["artifact_path"], run["model_key"], run["model_source"]))

    def _format(self, video: dict[str, Any], run: dict[str, Any], transcription: dict[str, Any]) -> dict[str, Any]:
        metadata = json.loads(self.repository.checkpoint(video["id"], "transcribe")["metadata_json"])
        segments = parse_segments_json(Path(metadata["segments_json"]))
        step_dir = self.artifacts.step_dir(video["id"], run["id"], "format")
        txt_path = step_dir / "transcript.txt"
        srt_path = step_dir / "transcript.srt"
        vtt_path = step_dir / "transcript.vtt"
        txt_path.write_text(to_text(segments), encoding="utf-8")
        srt_path.write_text(to_srt(segments), encoding="utf-8")
        vtt_path.write_text(to_vtt(segments), encoding="utf-8")
        normalized = step_dir / "segments.json"
        self.artifacts.write_json(normalized, {"segments": segments_to_json(segments), "model_key": run["model_key"]})
        manifest = step_dir / "manifest.json"
        manifest_payload = {
            "txt": str(txt_path),
            "srt": str(srt_path),
            "vtt": str(vtt_path),
            "segments_json": str(normalized),
            "model_key": run["model_key"],
        }
        self.artifacts.write_json(manifest, manifest_payload)
        return self._save(video=video, run=run, step="format", artifact=manifest, metadata=manifest_payload, input_fingerprint=_fingerprint(transcription["artifact_path"], run["model_key"]))

    def run(self, run_id: str) -> dict[str, Any]:
        run = self.repository.claim_run(run_id)
        if run["state"] not in {"running"}:
            return run
        video = self.repository.hydrate_video(str(run["video_id"]))
        try:
            self._execute_step(video, run, "inspect", lambda: self._inspect(video, run))
            download = self._execute_step(video, run, "download", lambda: self._download(video, run))
            audio = self._execute_step(video, run, "prepare_audio", lambda: self._prepare_audio(video, run, download))
            self._execute_step(video, run, "check_language", lambda: self._check_language(video, run, audio))
            transcription = self._execute_step(video, run, "transcribe", lambda: self._transcribe(video, run, audio))
            self._execute_step(video, run, "format", lambda: self._format(video, run, transcription))

            self.repository.set_run_step(run_id, "publish")
            self._event(video, run, "publish", "started")
            format_metadata = json.loads(self.repository.checkpoint(video["id"], "format")["metadata_json"])
            segments = parse_segments_json(Path(format_metadata["segments_json"]))
            self.repository.publish_transcript(
                run_id=run_id,
                segments=segments_to_json(segments),
                origin="fixture draft" if video["platform"] == "fixture" else "machine draft",
                model_key=run["model_key"],
                raw_artifact_path=Path(json.loads(self.repository.checkpoint(video["id"], "transcribe")["metadata_json"])["raw_json"]),
                txt_path=Path(format_metadata["txt"]),
                srt_path=Path(format_metadata["srt"]),
                vtt_path=Path(format_metadata["vtt"]),
            )
            self._event(video, run, "publish", "succeeded")
            return self.repository.get_run(run_id)
        except PipelineError as error:
            failed_step = self.repository.get_run(run_id).get("current_step") or "unknown"
            self._event(video, run, str(failed_step), "failed", code=error.code, message=error.message,
                        retryable=error.retryable, traceback=traceback.format_exc())
            self.repository.mark_error(run_id=run_id, step=str(failed_step), code=error.code, message=error.message, retryable=error.retryable)
            return self.repository.get_run(run_id)
        except Exception as error:
            failed_step = self.repository.get_run(run_id).get("current_step") or "unknown"
            self._event(video, run, str(failed_step), "failed", code="worker_error", traceback=traceback.format_exc())
            self.repository.mark_error(run_id=run_id, step=str(failed_step), code="worker_error", message=f"Processing failed unexpectedly: {error}", retryable=True)
            return self.repository.get_run(run_id)
