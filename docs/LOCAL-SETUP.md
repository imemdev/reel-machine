# Local setup and operations

Reel Machine runs its interface, API, SQLite library, media pipeline, and speech
recognition on your computer. The application currently displays the name **Kite**.
This guide covers the supplied macOS source launcher. The optional Apple Silicon
desktop bundle has a separate [packaging guide](../desktop/README.md).

## Prerequisites and installation

Set up Python 3.12+, uv, Node.js/npm compatible with the pinned frontend dependencies,
FFmpeg (including ffprobe), and zsh. Install missing tools explicitly during setup.
The launcher and processing jobs do not install packages or model weights.

From the repository root:

```sh
uv venv .venv
uv pip install -e '.[test,faruk,downloads]'
npm --prefix frontend ci
cp .env.example .env
```

Copy the example only when creating a new configuration; retain an existing
`.env` when updating. The `faruk` extra supplies the recognition runtime, and
`downloads` supplies yt-dlp and the pinned gallery-dl adapter.

## Configure FarukSTT

Obtain the inference files for **medyas/FarukSTT** as a separate setup step.
Set `FARUKSTT_MODEL` in `.env` to the complete local directory:

```dotenv
FARUKSTT_MODEL=/absolute/path/to/FarukSTT
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

Keep the model's configuration, processor, and tokenizer files alongside its
weights. The readiness check expects `config.json`, `preprocessor_config.json`,
and `tokenizer_config.json`, plus `model.safetensors` or the complete set of
indexed weight shards. Presence checks do not establish transcription accuracy.
Model files are excluded from Git. FarukSTT is the only current processing model.

## Build and launch

```sh
npm --prefix frontend run build
./scripts/run-local
```

Open **[http://127.0.0.1:3001](http://127.0.0.1:3001)**. The API listens on
`127.0.0.1:8001`, with interactive documentation at
[http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).
The launcher reads `.env`, uses the project's executable paths, and binds both
services to loopback. It refuses to start when either port is occupied.
Ctrl-C stops both services.

The launcher serves the production frontend. After frontend changes, build again
and restart. Changes to this checkout do not update an installed desktop bundle;
rebuild that bundle separately.

## Configuration and storage

[.env.example](../.env.example) documents the settings. Defaults use
`data/library.db` for SQLite and `data/runs` for media and processing artifacts.
Paths may be absolute or relative to the project. Optional `PIPELINE_PROMPT_FILE`
and `PIPELINE_LEDGER_FILE` values can remain blank when no context files are available.

Use one supervisor per database. The standard runtime processes one video at a
time, regardless of an old `WORKER_CONCURRENCY` environment value.
`MAX_BATCH_SIZE=12` limits one manual processing request, not the waiting queue.

The desktop application uses a separate library under
`~/Library/Application Support/Kite/library`. Initial migration copies configured
source data; the source and desktop libraries are not synchronized. See the
desktop guide before replacing a packaged application.

## Downloads and recognition

Instagram and Facebook use `YTA_FUNCTION`, which defaults to the bundled
[`scripts/yta`](../scripts/yta) wrapper. It invokes the project's yt-dlp with
Node.js, retries, audio extraction, metadata, and thumbnails. It does not require
a personal shell function or alter your shell configuration.

TikTok downloads use the installed, version-pinned gallery-dl adapter. It prefers
the video's audio stream and then muxed MP4 alternatives, avoiding the separate
music-library track. `GALLERY_DL` controls metadata previews. Neither path installs
dependencies during processing.

FFmpeg checks for usable audio and prepares mono 16 kHz WAV for FarukSTT.
An explicit retry after `audio_stream_missing` invalidates the unusable download
checkpoint and fetches again, while retaining earlier run artifacts and logs.
Public-platform availability varies by post. Review transcript drafts before reuse;
successful inference does not guarantee dialect accuracy.

## Queue and controls

Saving a new video also queues its FarukSTT job. The worker processes videos in
FIFO order. A failed job moves to Error so the next runnable video can start;
retry requires an explicit action. Duplicate imports do not create a second job.

- **Pause** stops the job and its downloader/model processes while preserving
  successful checkpoints. Paused work remains paused across restarts.
- **Resume** continues the same run, reuses completed steps, and restarts the
  interrupted step. Partial files for that interrupted step are discarded.
- **Done → Complete** removes source media and keeps transcript revisions and
  generated text artifacts. The record becomes read-only.
- **Delete** stops processing and permanently removes the video's records,
  media, transcripts, exports, checkpoints, and logs. Model weights are retained.

Estimates learn from recent successful real runs using the same model source.
They exclude download/preparation time and paused time. Fixture, failed, and
reused transcription steps do not create speed samples. Missing duration or timing
history can leave estimates unavailable.

## Processing logs and troubleshooting

Open **Processing history → View debug logs** for the video. New runs retain an
ordered `pipeline.jsonl`, a `step.log` for each attempted step, and separate tool
logs containing external command output and exit status. Steps that were never
reached have no logs. Retries retain earlier run files.

`GET /api/jobs/{run_id}/logs` returns up to the last 64 KiB of each log file.
Full logs remain under the artifact root until the video is deleted. Logs may
include source URLs, local paths, and tool output; review them before sharing.
A hard crash may prevent a final event from being recorded.

If Settings shows **Setup**, check the optional recognition dependencies and the
configured model directory. If launch reports an occupied port, stop the service
you intend to replace before starting another supervisor. If interface changes
are missing, rebuild and restart the frontend or desktop bundle as appropriate.

## Verification

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q backend
npm --prefix frontend run typecheck
npm --prefix frontend run build
node --check desktop/main.cjs
```

Backend fixtures use temporary databases and artifact directories. They verify
API behavior, persistence, checkpoint reuse, editing/export, notes, estimates,
and processing controls without live downloads or model inference.

For a manual synthetic-source smoke test, set `ALLOW_FIXTURE_SOURCES=true` and
configure separate database and artifact paths. Keep fixture mode disabled for
normal use. Fixture success does not verify platform access or transcription
accuracy; evaluate those separately with representative content you may process.
