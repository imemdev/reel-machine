# Social video library and Tunisian transcription

Created: 2026-09-13
Status: First-release scope clarified; remaining product questions are listed below.

## Product boundary — confirmed

This is a personal, web-only application for the owner.

- The interface is a local web app opened in a browser on the owner's Mac.
- There is no Chrome extension in this scope.
- There are no accounts, sign-up, login, Google sign-in, email/password authentication, or multi-user libraries.
- The app runs locally on the Mac with a Python backend, SQLite database, and local media/transcript files.
- No public deployment or cloud storage is in scope. Without authentication, the app must not be exposed beyond the owner's local machine unless access control is added later.
- Videos are added by pasting public Facebook, Instagram, or TikTok URLs.

## Product vision

A local web app lets the owner save public social-video URLs, turn selected videos into timestamped Tunisian Arabic transcripts, edit and export those transcripts, and track the work through a small personal library.

Core journey: paste a public video URL → save it in the local library → select saved videos → process them → read or edit the transcript → mark the item **Done** → move it to **Complete** when finished, which deletes the source media while permanently retaining the transcript data.

## Confirmed persistence and processing behavior

- Saved records, metadata, transcript text, timestamps, generated text data, tags, and processing state persist locally across closing and reopening the app.
- Transcript text and timestamp edits are debounce-saved to SQLite as the owner edits. The editor shows a small **Saved** indicator.
- Processing pauses when the app is closed. It resumes when the app is opened again from the persisted state and checkpoint.
- A later retry should reuse valid local artifacts already produced by earlier steps rather than repeat successful work unnecessarily.
- No processing or transcript data is sent to a hosted service in this first release.

## Requirements described by the owner

### Add and identify videos

- The owner pastes a video URL into the web app.
- Support public videos on Facebook, Instagram (including Reels), and TikTok on the web.
- After a URL is pasted, show the detected video's thumbnail, creator, platform, and source URL when available, so the owner can verify the item before saving.
- Save the individual video URL and available thumbnail, source platform, and creator/source-page information.
- Image fallback order: video thumbnail → originating page/profile logo or image → platform logo (Facebook, Instagram, or TikTok).
- The exact behavior for unavailable, expired, or fallback images remains open.

### Public video support

- Support public videos only. Private and followers-only videos are unsupported.
- When a video is identified as private, clearly inform the user: **This video is private. We can only access public videos.**
- Do not attempt to retrieve private videos using a user's social-platform login.
- If privacy is discovered during processing, move the item to Error with the private-video explanation.
- Distinguish confirmed privacy from an unknown access failure. For an unknown cause, show: **We couldn't access this video.**
- Do not label every inaccessible link as private.

### Duplicate saves

- Keep one record per canonical video in the local library.
- On a duplicate save, show **Already saved** with **Open in library**.
- Preserve the existing record's tags, transcript, workflow stage, and original save date.
- Different URL forms pointing to the same platform video should resolve to the same record; platform-specific identification requires implementation verification.

### Manage on the website

- Display saved videos with their thumbnail/fallback, original video link, and source page/creator information.
- Allow the owner to add, read, update, and delete local records, subject to the Complete-stage retention rule below.
- Allow selection of multiple records for batch actions.
- The video link cannot be modified after saving.
- Other user-facing fields, including thumbnails and transcripts, may be editable subject to processing locks and the Complete-stage retention rule.
- Make reading, editing, copying, and exporting transcripts convenient.

### Process selected videos

- Newly saved videos wait for the user to select them and click **Process**.
- A local Python worker processes selected links using the supplied transcription workflow as its starting point.
- Processing state is written to SQLite. If the app closes, work pauses; reopening the app makes the persisted work available to resume.
- Each successful item moves to **Processed**, with its timestamped transcript attached.
- Each failed item moves to **Error**; successful items in the same batch still move to Processed.
- Processed records retain their thumbnail, source page/creator, and original video link alongside the transcript.
- Transcript language target: Tunisian Arabic, with video timestamps.

### Language eligibility and transcript experience

- The application supports Tunisian Arabic videos only.
- Render Tunisian Arabic in Arabic script, preserving French/English words in their original language, with timestamps per segment. Mark unclear speech instead of guessing.
- Videos in English or French must move to Error with an unsupported-language explanation, rather than produce a transcript or a translation.
- User-facing message: **This application currently supports Tunisian Arabic videos only. To request another language, email medimemhamdi18@gmail.com.** The address is a feature-request contact; no email is sent automatically.
- Mixed-language videos qualify when the main spoken language is Tunisian Arabic. Videos mainly in French or English move to Error with the unsupported-language message.
- Reject clearly non-Tunisian speech with the unsupported-language message. For uncertain detection, show **We couldn’t confidently identify Tunisian Arabic** and allow **Retry**.
- No dialect-detection capability has been verified; the existing script's configured recognition language does not establish a Tunisian-only eligibility check.
- The owner can edit transcript text and timestamps, use **Copy text** or **Copy with timestamps**, and download **TXT, SRT, and VTT**.

### Reprocessing

- Offer **Reprocess**, warning the owner if the existing transcript contains manual edits.
- Keep the existing transcript until the new result succeeds. A failed attempt must not erase it.
- While reprocessing runs, the previous transcript remains readable and copyable, but transcript editing is temporarily disabled.
- Failed reprocessing moves the record to **Error**, showing the failure reason and **Retry**. The previous transcript remains available to read, copy, and edit.
- Reprocessing after **Complete** is not yet defined; the source media will have been deleted at that point.

### Finish using a transcript

- The owner can move a processed item to **Done** after finishing their work with its transcript.
- **Done** items remain accessible and keep their source media.
- The owner can move a **Done** item to **Complete** when the item is fully finished.
- Moving an item from **Done** to **Complete** triggers the deletion and retention rule below.
- **Complete** items are read-only for retained transcript and generated-text artifacts.
- The existing ability to move a **Done** item back to **Processed**, individually or in bulk, remains confirmed. Whether **Complete** can ever be reversed is still open because its source media has been deleted.

## Confirmed workflow stages and content tags

Each video has one workflow stage. Content tags are separate labels for filtering and search; they do not move a video between stages.

| Stage | Meaning |
| --- | --- |
| Inbox | Saved and not yet submitted for processing |
| Processing | Queued or currently being transcribed; work pauses when the app closes and resumes when it reopens |
| Processed | Transcription succeeded; available for use and editing |
| Error | Processing failed; shows a reason and a Retry action |
| Done | The owner has finished using the transcript; source media is still retained |
| Complete | Source audio and video have been deleted; transcript and generated text data are retained permanently |

Normal progression: **Inbox → Processing → Processed → Done → Complete**.  
Error recovery: **Error → Processing** through **Retry**.  
Reprocessing: **Processed → Processing** through **Reprocess**.  
The owner may move **Done → Processed** individually or in bulk when more work is needed.

### Workflow Rule: Status Transition to “Complete”

Stage progression: **[Current Stage] → Done → Complete**.

When an item moves from **Done** to **Complete**:

1. **Deletion:** Delete the source audio and video files associated with the item.
2. **Retention:** Permanently retain all transcripts, timestamps, and generated text data. Never modify or delete transcript files during this stage.

Before **Complete**, retain the source audio and video for processing and reprocessing. Do not delete source media as part of any other status transition. Manual media deletion is outside the first-release workflow.

### Content tags

- The owner can select default tags or create custom tags in **Inbox** to organize videos by topic or content type.
- Multiple tags can describe a video, such as Marketing and Storytelling.
- Tags are library organization labels, not social-platform hashtags or workflow stages.
- Tags stay attached through all stages, including **Complete**, and remain usable as filters in each stage. A video tagged Education + Storytelling keeps both labels from Inbox through Complete.
- Tagging is optional when saving; the owner can save quickly and organize later.
- The owner can select multiple videos in any stage and add or remove tags in bulk.
- Filtering defaults to **Any selected tag**; a video matches if it has at least one selected tag. An **All selected tags** option has not been approved.

Proposed starter set (exact defaults not yet approved): Marketing, Education, Storytelling, Tutorials, Inspiration, Entertainment, Product Reviews, Behind the Scenes.

Research basis: Adobe's [video content types guide](https://www.adobe.com/sg/creativecloud/video/discover/video-content-types.html) discusses explainers, educational videos, reviews, and comedy; its [video storytelling lesson](https://www.adobe.com/learn/express/web/video-storytelling) covers storytelling in short social videos; its [content creation guide](https://www.adobe.com/express/learn/blog/content-creation) discusses educational and inspirational content; an [Adobe creator partnership announcement](https://news.adobe.com/news/downloads/pdfs/2025/1/unrivaled-partners-with-adobe-express-to-transform-fan-engagement-through-creativity.pdf) describes behind-the-scenes stories. This starter set combines those examples with the owner's requested labels; it is a product recommendation, not a ranking of popular tags.

## Existing transcription script: verified source behavior

Reference: [transcribe_reel.py](/Users/a/Documents/reels/transcription_pipeline/transcribe_reel.py)

Supporting documentation: [pipeline README](/Users/a/Documents/reels/transcription_pipeline/README.md)

Source inspection shows that the script:

1. Accepts an Instagram video URL or a local audio/video file. Its URL validator currently rejects Facebook and TikTok URLs.
2. Downloads audio through the local `yta` zsh function.
3. Uses FFmpeg to prepare 16 kHz mono audio.
4. Runs local `whisper-cli` recognition with a model file and a configurable language/prompt.
5. Preserves raw recognition output and optionally applies a correction ledger to produce candidate editorial text.
6. Produces timestamped SRT, plain text, and WebVTT outputs, with raw JSON, logs, hashes, and an applied-edit ledger.

The documented target includes Tunisian Arabic and mixed French/English spellings. Automatic spelling substitutions do not establish transcription accuracy; the script describes its outputs as drafts requiring listening review.

This is a local single-input pipeline, not an existing web application or batch service. Facebook/TikTok downloading, local batch orchestration, checkpointed resume, and the web interface require additional work and verification. No processing run or platform integration was tested during this idea capture.

## Open product questions

These items are not approved defaults:

1. Exact default tag labels and tag rename/delete behavior.
2. Exact Facebook, Instagram, and TikTok URL surfaces and metadata behavior.
3. Local processing limits: maximum video duration, concurrent jobs, and expected library size.
4. Failure details, cancellation, and recovery if the Mac or local backend stops unexpectedly.
5. Whether **Complete** is permanently terminal and whether a Complete item can be restored by reacquiring source media.
6. Whether deleting a library record is allowed after **Complete**; any such action must not delete the permanently retained transcript files.
7. Search, additional sort orders, and the scope of “select all.”
8. Playback behavior inside the transcript view.
9. Exact source-image fallback behavior when thumbnails are unavailable or expired.

## Current scope of work

Build a personal, local, web-only video library and Tunisian transcription tool. The first release includes:

- a browser-based web interface;
- a local Python backend;
- SQLite for durable records, state, and transcript edits;
- local source media and transcript/generated-text files;
- pasted public Facebook, Instagram, and TikTok URLs;
- the workflow stages through **Complete**;
- Tunisian Arabic transcription with mixed French/English preservation, editing, and TXT/SRT/VTT export.

Out of scope for this release: Chrome extension development, user accounts, authentication, multi-user access, cloud storage, public hosting, social-platform login, and a production-scale hosted worker system.

## Local implementation direction

Technology choices for the browser UI are not selected. The confirmed local architecture is:

| Layer | Confirmed direction | Purpose |
| --- | --- | --- |
| Web UI | Local browser application; frontend framework open | Paste URLs, library, filters, stage actions, transcript editor, autosave indicator, and exports |
| Backend | Python running locally on the Mac | URL handling, processing orchestration, persistence, and local file management |
| Database | SQLite | Library records, workflow state, tags, checkpoints, transcript edits, and processing attempts |
| Files | Local filesystem | Source video/audio, derived audio, transcript artifacts, generated text, logs, hashes, and edit ledgers |
| Transcription | Existing Python pipeline, `whisper.cpp`, and FFmpeg | Produce timestamped Tunisian Arabic transcript drafts and exports |

Keep the web UI and Python processing boundary clear so components remain maintainable and replaceable. Persist job checkpoints and transcript edits locally. Validate URL handling, duplicate detection, public/private errors, partial batch success, close/reopen resume, autosave recovery, exports, reprocessing locks, and the **Done → Complete** media deletion/retention rule before treating the first release as finished.

The local app should be bound to the owner's machine only. Do not expose it to a network or deploy it publicly without adding authentication or another explicit access-control mechanism.

## Related documents

The linked [PRD.md](/Users/a/Documents/PRD.md) and [PRD-decisions.md](/Users/a/Documents/PRD-decisions.md) may contain the earlier Chrome-extension, account, and hosted-stack direction. Reconcile those documents with this clarified local web-only scope before using them as implementation contracts.

Durable processing checkpoints remain required: if audio download succeeds and a later step fails, **Retry** resumes from the first unfinished step using valid saved artifacts. Do not claim implementation, accuracy, platform support, or local acceptance until those are actually verified.
