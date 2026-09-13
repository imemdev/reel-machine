# Kite — local Tunisian video library

Kite is a local-only browser app for saving public Instagram, Facebook, and TikTok videos, processing them into timestamped Tunisian Arabic transcript drafts, editing those drafts, and exporting TXT/SRT/VTT files.

The app is intentionally local: FastAPI, SQLite, the media artifacts, and the worker stay on the Mac. It does not provide accounts, social-platform login, hosted transcription, or public deployment.

## This Mac — September 13, 2026

The project now has a local Python environment, frontend dependencies, a bundled downloader wrapper, and a single launcher. Setup and verification details are recorded in [docs/LOCAL-SETUP.md](docs/LOCAL-SETUP.md).

After setup, start the app from the project folder:

```sh
./scripts/run-local
```

Open [http://127.0.0.1:3001](http://127.0.0.1:3001). The launcher serves the production frontend and the backend on loopback only; Ctrl-C stops both. After frontend changes, rebuild with `npm --prefix frontend run build` before restarting. The development server hung on initial page requests during this Mac's setup; the production build and server work.

**Installation policy:** ask the owner before installing additional tools, packages, or models. The launcher never installs dependencies. TikTok uses the already-installed project environment, and `.env` disables automatic model downloads. Media downloads still require network access.

The old Mac's optional prompt and edit-ledger files were not included in Git. Their settings are blank here; supply the original files to restore that context. No files were deleted to make space.

### Debugging processing

TikTok downloads use a local audio-stream selector with `gallery-dl==1.32.12` from the project's Python environment. This keeps gallery-dl's HTTP/session handling, but prefers the video's `bitrateAudioInfo` stream, then muxed MP4 alternatives—not the separate music-library track. FFmpeg checks for usable audio before caching a download. A retry after `audio_stream_missing` invalidates the download checkpoint and fetches again, retaining old run artifacts/logs. `GALLERY_DL` still controls metadata previews; the downloads extra pins the adapter dependency because it uses an internal extractor method. This path was verified against the previously failing 223.9-second TikTok clip; not all TikTok posts are guaranteed accessible.

Open a video's Processing history and select **View debug logs**. Each new run keeps an ordered `pipeline.jsonl` and a `step.log` for each attempted step, including timestamps, selected model, success/reuse/failure and exception tracebacks. External commands retain their stdout/stderr and exit code in separate tool logs. Steps not reached do not have logs. Retries keep earlier run files; older runs show whatever tool logs already exist, without invented historical events. The report endpoint is `/api/jobs/{run_id}/logs` and shows up to the last 64 KiB per file; full files remain under the configured artifact root. Logs remain until the video is deleted. They can contain source URLs, paths and tool output: review before sharing. Logging cannot guarantee a final event after a hard crash or disk failure.

## Run it locally

Requirements: Python 3.12+, `uv`, Node.js/npm, FFmpeg, and the local FarukSTT runtime. Reuse existing tools. Install missing requirements **only after owner approval**.

For a new checkout, after approval:

```sh
uv venv .venv
uv pip install -e '.[test,faruk,downloads]'
npm --prefix frontend ci
cp .env.example .env
npm --prefix frontend run build
```

Install the model files separately, set their local paths in `.env`, and run `./scripts/run-local`. See [the setup record](docs/LOCAL-SETUP.md) for this Mac's paths. The default database is `data/library.db` and artifacts live under `data/runs`.

For a safe local fixture smoke test, set `ALLOW_FIXTURE_SOURCES=true` and use a separate database/artifact directory. Fixture output verifies the UI, persistence, checkpoints, editing, export, and lifecycle behavior; it does not prove live platform retrieval or model accuracy.

## Download paths

Instagram and Facebook downloads use the configured `YTA_FUNCTION` through a login shell. `.env.example` selects the bundled `scripts/yta` wrapper, which invokes the project's yt-dlp with `youtube:player_client=web_embedded`, Node.js, retries, audio extraction, embedded metadata, and thumbnails. No personal shell function is needed; an existing wrapper can still be configured explicitly.

TikTok uses the version-pinned local `gallery-dl` audio selector described above because the tested public TikTok sample failed through `yta` at the webpage request. Install the `downloads` extra during approved setup. Metadata previews use `GALLERY_DL` (default `gallery-dl`, falling back to the installed Python module); media downloads use the pinned adapter. Neither path installs packages during processing. FFmpeg creates the same mono 16 kHz WAV used by FarukSTT. No hosted downloader is involved.

Use only content you are permitted to retrieve and process, and respect each platform’s terms and copyright rules.

## Recognition

FarukSTT is the only model for this Tunisian Arabic workspace. Process, Retry, and Reprocess queue it directly; no model dialog or language confirmation is required. API jobs default to `model_key="farukstt"` and Tunisian Arabic when omitted. Whisper jobs are rejected. Existing transcripts retain their original provenance.

Set `FARUKSTT_MODEL` in `.env` to the local model directory. The Settings screen checks configuration and weights. Install the `faruk` extra when setting up a new machine. No model downloads occur during processing.

## Résultat

The Résultat sidebar page displays videos in Processed, Done, or Complete with a published transcript (these stages are reached only after the full pipeline succeeds). Responsive cards start compact with a portrait thumbnail and transcript preview, alongside platform, duration, title, creator, and tags. Expand card animates open to show the full transcript without internal scrolling; Compact card folds it back. Covers are saved locally on import (and fetched on first display for older videos), with a placeholder if unavailable. Saved covers are removed with their video. Copy copies transcript text only. Creator, tag, platform, duration, saved-date range, and text search filters combine. Dates use the browser's local timezone. Deletion asks for confirmation and removes the video, transcript revisions, media, exports, runs, checkpoints, activity, and unshared tags.

## Checks

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q backend
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

A single local supervisor runs each job in its own process group, with configurable parallelism. Successful steps are checkpointed; retry/reprocess uses valid artifacts where possible, and `Done → Complete` removes source media while retaining transcript revisions and generated text artifacts.

## Pause, resume, and delete

Select a video in the library to find its processing controls:

- **Pause** stops the active job and its downloader/model processes. Completed
  checkpoints and source media are retained. Paused jobs stay paused across restarts.
- **Resume** uses the same model and run, reuses completed checkpoints, and restarts
  the interrupted step. Partial download/transcription files for that step are discarded.
- **Stop & delete** stops processing before deleting the video record, cached audio
  and video, transcripts, exports, logs, checkpoints, and processing history. Queued,
  paused, and completed records can also be deleted. Other videos and installed model
  weights are unaffected. Deletion is permanent and does not start another run for
  the deleted video.

The APIs are `POST /api/videos/{id}/pause`, `POST /api/videos/{id}/resume`, and
`DELETE /api/videos/{id}`. The normal launcher hosts the single supervisor; avoid
running a second independent worker against the same database.

## Mac application

The Electron desktop build is installed as `/Applications/Kite.app`. It starts its bundled backend automatically and uses a migrated library at `~/Library/Application Support/Kite/library`. The project data remains a separate backup. See [desktop packaging and usage](desktop/README.md) for lifecycle behavior, model location, logs, and rebuild instructions.

## Automatic processing queue and estimates

Adding a video saves it and queues FarukSTT automatically in one SQLite transaction.
The app runs **one video at a time** to reduce CPU/GPU and memory pressure. Additional
videos wait in FIFO order. Failed videos move to Error and leave the runnable queue;
the next waiting video starts automatically. Failed jobs require an explicit Retry
and never retry endlessly. Duplicate imports do not create another job.

Pause/resume and delete are available on each library row, in the selection bar, and
in video details. Pause retains completed checkpoints; restart preserves waiting and
paused jobs. Delete confirms before stopping and removing the selected video.

Transcription estimates learn from up to 20 recent successful real runs with the same
model source: total transcription seconds divided by total audio duration. Durations
are measured from prepared audio. Timing starts anew when an interrupted transcription
restarts, excluding paused time. Failed, fixture, and reused transcription steps do not
create new speed samples. Timing history is stored locally and removed with its video.
Old runs without recorded timing are not guessed or treated as zero-duration samples.

The running transcription shows approximate minutes remaining and finish time, updated
by normal UI polling. Waiting videos show their queue position, expected transcription
length, and transcription time ahead when known. Download/preparation time is excluded;
unknown preparation or an overdue upstream run suppresses the queue wait prediction.
No timing history shows “Learning processing speed”; missing duration shows a duration
placeholder; overruns show “Taking longer than estimated.” Estimates are not promises.

`MAX_BATCH_SIZE=12` limits each manual processing request, not the waiting queue length.
The desktop and standard launcher always load a concurrency of 1; an old
`WORKER_CONCURRENCY` environment value does not raise it. `/api/config` reports the
actual limit. Use one supervisor per database.

Rebuild the packaged Kite.app after source changes; an installed bundle does not
read code or `.env` updates from the project checkout.
