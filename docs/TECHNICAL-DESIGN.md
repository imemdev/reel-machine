# Local video library — technical design

Status: implementation design for the clarified `idea.md` scope.

## Scope and reconciliation

The local `idea.md` is the active contract. The older `/Users/a/Documents/PRD.md`
and `/Users/a/Documents/PRD-decisions.md` describe a different hosted product
with accounts, a Chrome extension, Supabase/Postgres, and Celery. Those parts are
not carried into this build. The separate project at
`/Users/a/Documents/tunisian-video-library-poc` was inspected read-only as a
reference; it is not modified by this project.

The delivered slice is a personal, localhost-only web application with:

- a Next.js/React browser UI;
- a FastAPI Python API and one durable local worker thread;
- SQLite as the source of truth;
- local run artifacts for source media, normalized audio, raw recognition,
  formatted transcript, logs, and checkpoint metadata;
- explicit `fixture://` test sources, disabled by default in production, so the
  recovery flow can be exercised without inventing a real platform result.

## Stack decisions

| Concern | Decision | Reason |
| --- | --- | --- |
| Browser | Next.js App Router, React, TypeScript | Clear client boundary for a single local workspace and straightforward build output |
| Motion | `motion` with `motion/react` plus CSS transitions | Purposeful list/modal/theme/status motion and reduced-motion support without a large animation framework |
| Icons | `@phosphor-icons/react` | One consistent accessible icon family |
| Styling | Native CSS variables and component CSS | Four themes, offline runtime, no utility build dependency, easy token audit |
| API | FastAPI + Pydantic | Typed request validation, OpenAPI, small local process |
| Persistence | Python `sqlite3` | No database service; transactions and JSON fields are enough for this local scope |
| Worker | A single background thread polling SQLite | Durable restart/resume without pretending a hosted queue exists |
| Downloader | The owner’s login-shell `yta` function for Instagram/Facebook, plus a TikTok-only local `gallery-dl` fallback | Preserves `youtube:player_client=web_embedded`, Node.js runtime, retries, embedded metadata, and embedded thumbnails on the working `yta` path; gallery-dl handles the tested TikTok public-page path |
| Audio | FFmpeg to mono 16 kHz PCM WAV | Matches the supplied pipeline’s verified preprocessing contract |
| ASR | Owner-selected `FarukSTT` or `Whisper Large-v3 (Full)` | FarukSTT is the Tunisian-Derja fine-tune requested for testing; full Whisper is the general multilingual baseline. Each run records the selected model and artifact/provider identity |

## Boundaries

```text
Next.js client
  └─ HTTP JSON + file download
      └─ FastAPI routes
          ├─ Repository: SQLite transactions and guarded stage changes
          ├─ URL metadata adapter: fixture or yt-dlp inspect
          ├─ Local worker: claims processing rows and runs checkpoints
          │   ├─ inspect
          │   ├─ download
          │   ├─ prepare_audio
          │   ├─ check_language
          │   ├─ transcribe
          │   ├─ format
          │   └─ publish
          └─ Artifact store: content-addressed-ish files under data/runs/
```

The API is the only place that changes workflow state. The worker never trusts a
filename alone: a checkpoint is reusable only when its recorded artifact exists,
has the expected SHA-256, and has compatible input metadata. A failed reprocess
writes a candidate revision but does not move the current transcript pointer.

For Instagram and Facebook acquisition, the worker invokes `zsh -lic 'yta "$@"'`
with a run-local output template. This intentionally keeps the user’s
`download-youtube` wrapper and its `youtube:player_client=web_embedded` extractor
setting in the execution path; a bare `yt-dlp URL` invocation is not equivalent
for this machine. A public TikTok smoke test showed the current `yta` path
failing at TikTok’s webpage request, while local `gallery-dl` 1.32.12 downloaded
the same public post successfully; TikTok therefore uses gallery-dl to fetch the
video and the existing FFmpeg step to extract mono 16 kHz audio. This fallback
does not use a hosted downloader service.

## Processing and language boundary

Before a process/retry/reprocess action, the UI requires the owner to select one
of exactly two model options: `FarukSTT` or `Whisper Large-v3 (Full)`. Real URL
processing uses the selected local adapter and records raw recognition output
separately from any candidate editorial formatting. It does not claim that either
model alone proves Tunisian dialect eligibility. Until a dialect-aware classifier
and reviewer-labeled holdout are supplied, real-link processing requires the
owner’s explicit “primarily Tunisian Arabic” confirmation and records
`validated: false` in the language checkpoint. Fixture branches cover
unsupported, uncertain, private, and unknown-access error states for recovery/UI
testing only.

The UI labels generated transcripts as drafts and preserves `[كلمة غير واضحة]`
markers where the recognition provider emits them. No translation is performed.

## Data and lifecycle rules

- `videos.source_url` and its canonical identity are immutable after save.
- Tags, display metadata, stage, checkpoints, attempts, and transcript revisions
  persist in SQLite.
- Text/timestamp edits use an expected revision number; the UI debounce-saves
  them and shows `Saved` after the API accepts the revision.
- `Done -> Complete` is a guarded transaction followed by deletion of only source
  audio/video paths. Transcript artifacts and their SQLite references remain.
- `Complete` records are read-only and cannot be reprocessed because source media
  is intentionally gone.
- The backend binds to `127.0.0.1`; no authentication or external exposure is
  introduced in this first release.

## Acceptance slice

Automated tests cover URL canonicalization, duplicate identity, guarded stage
transitions, checkpoint reuse, partial batch outcomes, transcript revision
conflicts, export rendering, and Complete-stage media deletion/retention. A
browser smoke check covers add/preview, stage actions, transcript editing, theme
switching, and responsive layout.

Still unproven by local source tests: live retrieval on every public Facebook,
Instagram, and TikTok surface; true private-vs-unknown access classification;
Tunisian dialect accuracy/eligibility; long-running resource limits; and user
acceptance on real clips. These require owner-supplied permitted fixtures and
audio review.
