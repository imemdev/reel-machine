<div align="center">

<img src="docs/assets/readme-banner.svg" alt="Reel Machine — Your reels. Ready to read." width="100%" />

# Reel Machine

**Your local workspace for Tunisian Arabic video transcripts.**

Save YouTube videos and reels. Turn speech into editable drafts. Keep your next script close.

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
[![Next.js](https://img.shields.io/badge/Next.js-16-111827?style=flat-square&logo=nextdotjs&logoColor=white)](frontend/package.json)
[![Storage](https://img.shields.io/badge/Storage-SQLite-00758F?style=flat-square&logo=sqlite&logoColor=white)](backend/app/db.py)
[![Platforms](https://img.shields.io/badge/Runs%20on-macOS%20%7C%20Windows-527A60?style=flat-square)](#-install-and-launch)

[Screenshots](#-a-quick-look) · [Install on macOS](#-macos) · [Install on Windows](#-windows) · [First transcript](#-your-first-transcript) · [Your files](#-where-are-my-files) · [Troubleshooting](#-troubleshooting)

<br />

<img src="docs/assets/screenshots/library.png" alt="Reel Machine library with a selected video, its details and processing pipeline" width="100%" />

</div>

## 👋 What is it?

Reel Machine is a personal video library and transcript editor built for **Tunisian Arabic (Derja)**, including the French and English words people mix in.

Paste a public **YouTube**, **Instagram**, **Facebook**, or **TikTok** link. Reel Machine downloads the video, prepares its audio, runs speech recognition **on your own computer** with the [FarukSTT](https://huggingface.co/medyas/FarukSTT) model, and gives you a clean draft to review, edit, and export. Every video and its audio are saved in a tidy folder you can open anytime. A Notes space keeps your own ideas and scripts next to your research.

> The app window is branded **Kite**. Nothing is uploaded to a cloud service: your library, media, and transcripts stay on your machine.

## 📸 A quick look

<table>
  <tr>
    <td width="50%"><img src="docs/assets/screenshots/dashboard.png" alt="Dashboard with queue counters and recent activity" /></td>
    <td width="50%"><img src="docs/assets/screenshots/resultat-dark.png" alt="Résultat gallery of finished transcripts in the dark theme" /></td>
  </tr>
  <tr>
    <td align="center"><b>Dashboard</b> — queue at a glance</td>
    <td align="center"><b>Résultat</b> — every finished transcript, ready to copy</td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/assets/screenshots/notes.png" alt="Notes page with script ideas in Arabic and English" /></td>
    <td width="50%">

**Also inside**

- ▶️ YouTube (videos & Shorts), Instagram, Facebook, TikTok
- 🎞️ Watch the video and play its audio right in the app
- ✍️ Transcript editor with timestamps and revision history
- 📤 Export to **TXT**, **SRT**, and **VTT**
- ⏯️ Pause, resume, and retry jobs without losing progress
- 🔎 Filter by creator, tag, platform, duration, and date
- 🎨 Four themes: Light, Warm Paper, Slate, Dark

</td>
  </tr>
  <tr>
    <td align="center"><b>Notes</b> — your own scripts and ideas</td>
    <td></td>
  </tr>
</table>

<sub>Screenshots use sample data with fictional creators.</sub>

## 🧰 What you need

| Tool | Why | macOS | Windows |
| :--- | :--- | :--- | :--- |
| **Git** | Download the code | `brew install git` | `winget install Git.Git` |
| **uv** | Installs Python 3.12 and the Python packages | `brew install uv` | `winget install astral-sh.uv` |
| **Node.js 20+** | Builds and serves the interface | `brew install node` | `winget install OpenJS.NodeJS.LTS` |
| **FFmpeg** | Converts audio for recognition | `brew install ffmpeg` | `winget install Gyan.FFmpeg` |
| **Disk space** | App + FarukSTT model | about **10 GB** free | about **10 GB** free |

On macOS, install [Homebrew](https://brew.sh) first if you don't have it. On Windows, `winget` is built into Windows 10 and 11. **Close and reopen your terminal after installing** so the new commands are found.

## 🚀 Install and launch

### 🍎 macOS

Open **Terminal** and run these blocks one at a time.

**1. Download the project**

```sh
cd ~/Documents
git clone https://github.com/imemdev/reel-machine.git
cd reel-machine
```

**2. Install everything**

```sh
uv venv --python 3.12 .venv
uv pip install -e '.[test,faruk,downloads]'
npm --prefix frontend ci
cp .env.example .env
```

**3. Download the FarukSTT model** (one time, several GB)

```sh
.venv/bin/hf download medyas/FarukSTT --local-dir ~/models/FarukSTT
```

Then open `.env` in any text editor (for example `open -e .env`) and set:

```dotenv
FARUKSTT_MODEL=${HOME}/models/FarukSTT
```

**4. Build and launch**

```sh
npm --prefix frontend run build
./scripts/run-local
```

Open **http://127.0.0.1:3001** in your browser. 🎉 Press **Ctrl + C** in Terminal to stop.

**Next time**, you only need:

```sh
cd ~/Documents/reel-machine
./scripts/run-local
```

### 🪟 Windows

Open **PowerShell** (Start menu → type *PowerShell*) and run these blocks one at a time.

**1. Download the project**

```powershell
cd $HOME\Documents
git clone https://github.com/imemdev/reel-machine.git
cd reel-machine
```

**2. Install everything**

```powershell
uv venv --python 3.12 .venv
uv pip install -e ".[test,faruk,downloads]"
npm --prefix frontend ci
Copy-Item .env.example .env
```

**3. Download the FarukSTT model** (one time, several GB)

```powershell
.venv\Scripts\hf.exe download medyas/FarukSTT --local-dir $HOME\models\FarukSTT
```

Then open `.env` with `notepad .env` and set the model path with **forward slashes** (replace `YOUR_NAME` with your Windows user name):

```dotenv
FARUKSTT_MODEL=C:/Users/YOUR_NAME/models/FarukSTT
```

**4. Build and launch**

```powershell
npm --prefix frontend run build
.\scripts\run-local.cmd
```

Open **http://127.0.0.1:3001** in your browser. 🎉 Press **Ctrl + C** in PowerShell to stop.

**Next time**, open the `reel-machine` folder and double-click `scripts\run-local.cmd`, or run:

```powershell
cd $HOME\Documents\reel-machine
.\scripts\run-local.cmd
```

> [!NOTE]
> Windows support is new. Everything is set up to work natively in PowerShell, but if you hit a problem, please [open an issue](https://github.com/imemdev/reel-machine/issues) with the error text.

### 🔄 Updating to a new version

```sh
git pull
uv pip install -e '.[test,faruk,downloads]'     # Windows: ".[test,faruk,downloads]"
npm --prefix frontend ci
npm --prefix frontend run build
```

Your `.env`, library, and model files are kept.

## 🎬 Your first transcript

1. Open **Library** and click **New video**.
2. Paste a public YouTube, Instagram, Facebook, or TikTok link, check the preview, add tags, and save.
3. The video joins the queue automatically. Open it to watch each step: download → prepare audio → transcribe.
4. Under **Media files**, play the video or its audio, or click **Show in folder**.
5. Review the draft, fix any words, then **copy** the text or export **TXT / SRT / VTT**.
6. Find everything finished in **Résultat**, and write your own scripts in **Notes**.

Transcription speed depends on your computer. The first run loads the model and takes longer; the app learns and shows time estimates after a few videos.

## 📂 Where are my files?

Every video you process is saved, with its audio, in a clean, human-friendly folder: **`Documents/Reel Machine`** in your home folder by default.

```text
Reel Machine/
├── Videos/
│   ├── YouTube/    2026-09-24 كسكسي بالعلوش على طريقة جدتي [Kx7r2mQpL0a].mp4
│   ├── Instagram/  2026-09-24 غروب الشمس في سيدي بوسعيد [C9demoSidi].mp4
│   └── TikTok/ …
└── Audio/
    ├── YouTube/    2026-09-24 كسكسي بالعلوش على طريقة جدتي [Kx7r2mQpL0a].wav
    ├── Instagram/  2026-09-24 غروب الشمس في سيدي بوسعيد [C9demoSidi].wav
    └── TikTok/ …
```

- **Videos** are MP4 (H.264/AAC preferred, up to 1080p), so they open in QuickTime, Photos, or the Windows Media Player.
- **Audio** is the exact 16 kHz mono WAV the recognizer listened to, with the **same name** as its video.
- Open them from **Settings → Media folder** (*Open videos folder* / *Open audio folder*), or from any video's **Media files** section (*Open*, *Show in folder*).
- **Done → Complete** keeps these files. **Delete video** removes them.
- Want a different place? Set `MEDIA_ROOT` in `.env` (for example an external drive).

<img src="docs/assets/screenshots/media-folder.png" alt="Settings panel showing the Videos and Audio folders with open buttons" width="100%" />

## ⚙️ How it works

```mermaid
flowchart LR
    A[Public video URL] --> B["Download video<br/>MP4"]
    B --> C["FFmpeg<br/>Mono 16 kHz audio"]
    B --> M[("Media folder<br/>Videos + Audio")]
    C --> M
    C --> D["FarukSTT<br/>Transcript draft"]
    D --> E[Review and edit]
    E --> F[TXT · SRT · VTT]
    G[(SQLite + local files)] --- B
    G --- D
    G --- E
```

**Next.js + React** power the interface on port `3001`. **FastAPI** runs the API on port `8001` (interactive docs at [/docs](http://127.0.0.1:8001/docs)). Both only listen on your own computer. A local worker processes **one video at a time**, in order, and saves checkpoints so finished steps are never repeated. YouTube, Instagram, and Facebook download with yt-dlp; TikTok uses a pinned gallery-dl adapter.

FarukSTT produces a **draft** for human review. The app does not verify that a clip is actually Tunisian Arabic.

## 🎛️ Controls

| Action | What happens |
| :--- | :--- |
| **Pause** | Stops the job but keeps finished steps. Stays paused after restarts. |
| **Resume** | Continues from the last finished step. |
| **Retry** | Tries a failed job again, reusing anything still valid. |
| **Done → Complete** | Cleans up internal working copies, keeps the transcript read-only. Your media folder files stay. |
| **Delete** | Removes the video and all its files, including its media folder copies. The model is kept. |

## 🔧 Configuration

Settings live in `.env` (copied from [.env.example](.env.example)).

| Setting | Default | Purpose |
| :--- | :--- | :--- |
| `FARUKSTT_MODEL` | `${HOME}/Library/Caches/kite/FarukSTT` | Folder with the downloaded model. **Set this.** |
| `MEDIA_ROOT` | `~/Documents/Reel Machine` | Where organized videos and audio are saved. |
| `DATABASE_PATH` | `data/library.db` | Your library database. |
| `ARTIFACT_ROOT` | `data/runs` | Internal working files, checkpoints, and logs. |
| `FFMPEG` | `ffmpeg` | FFmpeg command or full path. |
| `GALLERY_DL` | `gallery-dl` | TikTok metadata command. |
| `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` | `1` | Keep model loading fully offline. |
| `ALLOW_FIXTURE_SOURCES` | `false` | Enables fake `fixture://` sources for testing. |

Paths can be absolute or relative to the project folder.

## 🩺 Troubleshooting

<details>
<summary><b>The model shows “Setup” in Settings</b></summary>

`FARUKSTT_MODEL` must point to the complete model folder (with `config.json`, `preprocessor_config.json`, `tokenizer_config.json`, and the `.safetensors` weights). Check the path in `.env`, then restart the app. On Windows, use forward slashes.
</details>

<details>
<summary><b>“Port 8001/3001 is already in use”</b></summary>

Reel Machine is probably already running in another terminal window. Stop it with Ctrl + C there, or restart your computer.
</details>

<details>
<summary><b>“Missing frontend build”</b></summary>

Run `npm --prefix frontend run build`, then launch again. Rebuild after every update.
</details>

<details>
<summary><b>The video doesn't play inside the app</b></summary>

Use **Open** to play it in your system player, or **Show in folder**. Some browsers can't play every codec; the file itself is fine.
</details>

<details>
<summary><b>Videos I processed before this update aren't in the media folder</b></summary>

When the app starts, it copies the audio (and video, when one was downloaded) of older items into the media folder automatically. Older items were downloaded as audio only; use **Reprocess** on one to download its video (the existing transcript is reused).
</details>

<details>
<summary><b>Windows: “running scripts is disabled on this system”</b></summary>

Use `.\scripts\run-local.cmd` instead of the `.ps1` file, or run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
</details>

<details>
<summary><b>`uv`, `node`, or `ffmpeg` is “not recognized” / “command not found”</b></summary>

Close and reopen the terminal after installing them. On Windows, sign out and back in if it still isn't found.
</details>

<details>
<summary><b>A video can't be downloaded (YouTube, Instagram, …)</b></summary>

Make sure the post is public. Platforms change often, so update the downloader and retry:
`uv pip install -U "yt-dlp[default]"`. YouTube also needs Node.js installed (it's in the requirements above). Age-restricted or members-only YouTube videos can't be downloaded. Open the video → **Processing history → View debug logs** for details. Logs can contain URLs and local paths, so review them before sharing.
</details>

## 🧑‍💻 Development

```sh
.venv/bin/python -m pytest -q               # Windows: .venv\Scripts\python.exe -m pytest -q
.venv/bin/python -m compileall -q backend
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Tests use temporary databases and fake sources, so they need no network or model.

```text
reel-machine/
├── backend/app/         FastAPI, SQLite, worker, and media pipeline
├── backend/tests/       API and workflow tests
├── frontend/            Next.js interface and transcript editor
├── desktop/             Optional Electron packaging (macOS, Apple Silicon)
├── scripts/             Launchers for macOS and Windows, download wrappers
└── docs/                Setup guide, architecture notes, images
```

More detail: [Local setup guide](docs/LOCAL-SETUP.md) · [macOS desktop app](desktop/README.md) · [Technical design](docs/TECHNICAL-DESIGN.md) (historical).

## 🤝 Good to know

This is a personal, local-only app: no accounts, no hosted transcription. Only process content you have permission to use, and review transcript drafts before reusing them.

---

<div align="center">

**From saved clips to words you can work with.** ✨

If Reel Machine helps you, consider giving it a ⭐

</div>
