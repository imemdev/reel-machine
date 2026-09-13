> Update, September 13, 2026: the workspace now uses only FarukSTT. The full
> Whisper Large-v3 weights were removed from this Mac at the owner's request.
> References to Whisper testing below are historical setup records.

# Local setup record — September 13, 2026

## Run

From this checkout, run `./scripts/run-local`, then open http://127.0.0.1:3001.
The launcher reads `.env`, activates the project's executable paths, and starts
FastAPI on 127.0.0.1:8001 and the built Next.js app on 127.0.0.1:3001.
Ctrl-C stops both processes. It refuses to start if either port is occupied.
Run `npm --prefix frontend run build` after changing frontend code.

The production server is the verified normal launch path. During setup,
`next dev` reported ready but did not answer initial HTTP requests. No package
upgrade was needed to run the production build.

## Installed with owner approval

- Existing Python 3.13.15, Homebrew, and FFmpeg 9.0.1 were reused.
- Homebrew installed Node 26.8.2, uv 0.12.13, and whisper.cpp 1.9.4,
  with their required formula dependencies.
- `frontend/node_modules` was installed from the existing package lock.
- `.venv` contains the project's `test`, `faruk`, and `downloads` extras.
  Recognition uses PyTorch 2.14.0, Transformers 5.17.0, Accelerate 1.15.0,
  and safetensors 0.8.0. PyTorch detects Apple MPS on this 32 GiB Mac.
- Downloads use yt-dlp 2026.08.19 and gallery-dl 1.32.12.
- No additional browser testing package was installed.

Ask the owner before any further installation. The launcher does not install
anything, TikTok uses the installed Python environment instead of `uvx`, and
the provided `.env` sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

## Model storage

- Whisper: `/Users/suser/Library/Caches/whisper.cpp/ggml-large-v3.bin`
  from [ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp).
  Full, unquantized weights; SHA-256:
  `64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2`.
- FarukSTT: `/Users/suser/Library/Caches/kite/FarukSTT`
  from [medyas/FarukSTT](https://huggingface.co/medyas/FarukSTT), revision
  `a0898fa42804fc1ad86bbee147479d3e8a5f2270`.
  Only the single safetensors weight file and inference configuration/tokenizer
  files were selected. Duplicate shards, training checkpoints, optimizer state,
  and training logs were excluded. The downloaded weight SHA-256 is
  `4d4733162daf275cfda5c2672c6c988830d8902f02b0e50234d0968e327e7d23`.

The two weights total approximately 9.27 GB. Models and environments are local
and excluded from Git. Readiness checks validate file presence, not accuracy.

## Configuration repairs

The old `/Users/a/...` paths have been removed from `.env.example`.
The local `.env` points to the installed models. Optional prompt and ledger
paths are blank because their original files were not included in the checkout.

`scripts/yta` replaces the missing personal shell function for this project.
It uses the project's yt-dlp with Node, retries, audio extraction, embedded
metadata, and thumbnails. It does not modify global shell configuration.

The real library uses `data/library.db` and `data/runs`; fixture mode is off.
Verification fixtures used temporary databases, leaving the library empty.

## Verification

- 22 backend tests pass; two upstream deprecation warnings remain.
- Python compilation, dependency consistency, frontend typecheck, and production
  build pass.
- Browser: dashboard, library, settings, and add-video form render; no console
  warnings or errors were observed in the production session.
- Both explicit model choices pass the fixture API → worker → SQLite →
  TXT/SRT/VTT export flow.
- The repository's public TikTok sample downloads with its audio; FFmpeg converts
  it to 10.495 seconds of mono 16 kHz WAV.
- Full Whisper weights pass SHA-256 verification and real inference through the
  project's adapter on the official whisper.cpp 11-second JFK sample, producing
  timestamped segments and exports.
- FarukSTT weights pass SHA-256 verification and real inference through the
  project's adapter on Apple MPS, producing two timestamped segments from the
  same 11-second JFK sample. No extra inference packages were needed.

The English sample verifies inference mechanics, not Tunisian dialect accuracy.
The app forces Arabic for Whisper, so this sample's output is rendered in Arabic.
Representative Tunisian Arabic/French/English clips still need accuracy review.
Instagram/Facebook access and all TikTok posts are not guaranteed by the sample
download. No accounts, cookies, or hosted transcription were configured.

## Processing controls follow-up

Pause/resume and stop-and-delete are available in video details. Jobs now execute
in isolated process groups so downloads and in-process PyTorch inference can both
be stopped before deleting files. A non-destructive SQLite migration adds a paused
flag. Active cancellation, forced child-process termination, isolated deletion,
queued cancellation, paused restart behavior, completed-record deletion, and
checkpoint reuse are covered by tests. Pause/Resume were also verified in the
browser on the live FarukSTT job; its existing download/audio checkpoints survived,
and it was resumed afterward. User videos were not deleted during verification.
