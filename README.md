# Kite — local Tunisian video library

Kite is a local-only browser app for saving public Instagram, Facebook, and TikTok videos, processing them into timestamped Tunisian Arabic transcript drafts, editing those drafts, and exporting TXT/SRT/VTT files.

The app is intentionally local: FastAPI, SQLite, the media artifacts, and the worker stay on the Mac. It does not provide accounts, social-platform login, hosted transcription, or public deployment.

## Latest handoff — September 13, 2026

**Blocked: real transcription model setup.** The app and download pipeline are implemented, but real ASR inference and accuracy have not been verified on this Mac.

- FarukSTT: the optional Transformers/PyTorch runtime is not installed. Model weights require approximately 6.17 GB, plus dependencies and working space.
- Whisper Large-v3 (Full): `whisper-cli` is installed, but the unquantized `ggml-large-v3.bin` is missing (approximately 3.10 GB). Existing quantized model files are not substitutes for this explicit Full choice.
- At the last disk check, only 6.4 GiB was free. Installation was paused before downloading either model. Free additional space or select an external model-storage folder, then install/configure both models and restart the backend. No files were deleted to make room.
- Preserve the user's explicit model choice for each run. After setup, retry the failed transcription step; model accuracy still needs evaluation on representative Tunisian Arabic/French/English clips.

**Verified:** 13 backend tests pass (two dependency deprecation warnings); frontend typecheck passed after the debug-log UI changes. The previously failing TikTok clip downloaded as its own AAC audio stream and converted successfully to a 223.9-second mono 16 kHz WAV. The backend was restarted with the TikTok selector/retry fix. This is audio acquisition evidence, not a successful real-model transcription.

**Latest fixes:** ordered per-step/run logs, debug-log links, actionable missing-audio errors, audio-bearing TikTok stream selection, audio validation before checkpointing, and download-checkpoint invalidation when retrying a missing-audio failure. Old artifacts and logs remain available locally.

**Local session:** frontend on port 3001; backend on port 8001 with `DATABASE_PATH=data/browser-smoke.db`, `ARTIFACT_ROOT=data/browser-runs`, and `ALLOW_FIXTURE_SOURCES=true`. These are local test settings, not deployment configuration. The default setup below uses a separate library database. Local databases, downloaded media, logs, model weights, environments and dependencies are not included in Git.

**Remaining limitations:** the `yta` shell wrapper is an external local prerequisite, not bundled here; platform access is not guaranteed; language eligibility currently uses owner confirmation, not a validated dialect detector; real model inference/accuracy and end-to-end acceptance remain unproven. No Chrome extension or hosted deployment is included. Bulk tag/delete UI and transcript revision-history browsing are not yet implemented.

### Debugging processing

TikTok downloads use a local audio-stream selector with `uvx --from gallery-dl==1.32.12` (requires `uvx`). This keeps gallery-dl's HTTP/session handling, but prefers the video's `bitrateAudioInfo` stream, then muxed MP4 alternatives—not the separate music-library track. FFmpeg checks for usable audio before caching a download. A retry after `audio_stream_missing` invalidates the download checkpoint and fetches again, retaining old run artifacts/logs. `GALLERY_DL` still controls metadata previews; the download adapter is version-pinned because it uses an internal extractor method. This path was verified against the previously failing 223.9-second TikTok clip; not all TikTok posts are guaranteed accessible.

Open a video's Processing history and select **View debug logs**. Each new run keeps an ordered `pipeline.jsonl` and a `step.log` for each attempted step, including timestamps, selected model, success/reuse/failure and exception tracebacks. External commands retain their stdout/stderr and exit code in separate tool logs. Steps not reached do not have logs. Retries keep earlier run files; older runs show whatever tool logs already exist, without invented historical events. The report endpoint is `/api/jobs/{run_id}/logs` and shows up to the last 64 KiB per file; full files remain under the configured artifact root. Logs remain until the video is deleted. They can contain source URLs, paths and tool output: review before sharing. Logging cannot guarantee a final event after a hard crash or disk failure.

## Run it locally

Requirements: Python 3.12+, `uv`, Node.js, FFmpeg, and the local `yta` function from the existing `youtube-downloader` setup.

```sh
uv venv .venv
uv pip install -e '.[test]'
cp .env.example .env
```

In one terminal, load the environment and start the backend:

```sh
set -a
source .env
set +a
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

In a second terminal:

```sh
npm --prefix frontend install
NEXT_PUBLIC_API_URL=http://127.0.0.1:8001 npm --prefix frontend run dev -- --hostname 127.0.0.1 --port 3001
```

Open [http://127.0.0.1:3001](http://127.0.0.1:3001).

For a safe local fixture smoke test, set `ALLOW_FIXTURE_SOURCES=true` and use a separate database/artifact directory. Fixture output verifies the UI, persistence, checkpoints, editing, export, and lifecycle behavior; it does not prove live platform retrieval or model accuracy.

## Download paths

Instagram and Facebook downloads invoke the owner’s login-shell function exactly as `zsh -lic 'yta "$@"'`. This preserves the existing wrapper’s `youtube:player_client=web_embedded`, Node.js runtime, retries, metadata, thumbnail, and audio options.

TikTok uses the version-pinned local `gallery-dl` audio selector described above because the tested public TikTok sample failed through `yta` at the webpage request. Install `uv` so `uvx` is available. Metadata previews use `GALLERY_DL` (default `gallery-dl`, falling back to `uvx gallery-dl`); media downloads use the pinned adapter. FFmpeg creates the same mono 16 kHz WAV used by both recognizers. No hosted downloader is involved.

Use only content you are permitted to retrieve and process, and respect each platform’s terms and copyright rules.

## Recognition choices

The processing dialog always requires an explicit model selection and owner confirmation that the video is primarily Tunisian Arabic. The two choices are:

- `FarukSTT` — loaded through the optional local Transformers dependencies.
- `Whisper Large-v3 (Full)` — uses the full local `ggml-large-v3.bin` file through `whisper-cli`; there is no turbo or quantized fallback under this label.

Install the FarukSTT dependencies only when needed:

```sh
uv pip install -e '.[faruk]'
```

Set `FARUKSTT_MODEL` and `WHISPER_LARGE_V3_MODEL` in `.env` to local model directories/files that you own. The Settings screen reports whether each path is ready. A fixture can still exercise either choice without loading a model.

## Checks

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q backend
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

The worker is a durable single local thread. Successful steps are checkpointed; retry/reprocess uses valid artifacts where possible, and `Done → Complete` removes source media while retaining transcript revisions and generated text artifacts.
