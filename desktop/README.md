# Kite for macOS (Apple Silicon)

Kite.app bundles Electron, a static frontend, Python 3.13, the installed Python dependencies, FFmpeg/FFprobe, Node, and the downloader wrappers. It runs without the project checkout, a terminal, Next.js, or a system Python/Homebrew installation. FarukSTT weights remain at `~/Library/Caches/kite/FarukSTT` and must be retained.

## Using the app

Open `/Applications/Kite.app`. The first launch copies the existing local library into `~/Library/Application Support/Kite/library`. Subsequent launches use that copy; the source project data is retained as a backup and is not synchronized. The migration source is captured in `migration.json` when the app is built. If it no longer exists, the app starts with an empty library.

- Close window: keep the backend running. Reopen using the Dock or Kite menu-bar item.
- Cmd+Q / Quit Kite: stop the backend and current worker safely. Completed pipeline checkpoints and saved data remain; unpaused unfinished jobs resume when the app reopens.
- Open data folder: available in the Kite application and menu-bar menus.
- Logs: `~/Library/Application Support/Kite/logs/backend.log`.
- Updating/replacing the app preserves the Application Support folder.
- This is a locally ad-hoc signed build for this Mac, not an Apple-notarized public installer.

The backend binds a random loopback port and requires a per-launch secret header attached by Electron. Browser windows use sandboxing and context isolation without Node integration. External video links open in the system browser. No cloud hosting is involved.

## Rebuild on this Mac

From the repository root:

```sh
npm --prefix desktop ci
node desktop/node_modules/electron/install.js
UV_PYTHON_INSTALL_DIR="$PWD/desktop/python-download" uv python install 3.13 --no-bin
KITE_DESKTOP_BUILD=1 NEXT_PUBLIC_API_URL='' npm --prefix frontend run build
python3 desktop/build_payload.py
swift desktop/make-icon.swift desktop/Kite.iconset
iconutil -c icns desktop/Kite.iconset -o desktop/icon.icns
npm --prefix desktop run package
codesign --force --deep --sign - desktop/dist/mac-arm64/Kite.app
```

`build_payload.py` copies the project's tested `.venv` packages into the standalone Python runtime and relocates the native dependencies of media tools. Rebuild after changing backend/frontend code. Quit Kite before replacing the installed app using `ditto desktop/dist/mac-arm64/Kite.app /Applications/Kite.app`.

The assembled bundle is about 1.3 GB, excluding FarukSTT weights. This packaging targets the current Apple Silicon Mac; distribution to other machines requires clean-machine testing, model setup, license review, and developer signing/notarization.
