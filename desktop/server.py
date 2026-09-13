"""Packaged backend entry point and one-time, non-destructive library migration."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import threading
import time
import tempfile


def migrate(source: Path, destination: Path):
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='kite-migration-', dir=destination.parent))
    try:
        if (source / 'library.db').is_file():
            with sqlite3.connect(source / 'library.db') as src, sqlite3.connect(stage / 'library.db') as dst:
                src.backup(dst)
            if (source / 'runs').exists():
                shutil.copytree(source / 'runs', stage / 'runs')
            old, new = str(source / 'runs'), str(destination / 'runs')
            with sqlite3.connect(stage / 'library.db') as db:
                for table in ('videos', 'runs', 'checkpoints', 'transcripts', 'activities'):
                    columns = [row[1] for row in db.execute(f'PRAGMA table_info({table})') if row[2] == 'TEXT']
                    for column in columns:
                        db.execute(f'UPDATE {table} SET {column} = replace({column}, ?, ?) WHERE instr({column}, ?) > 0', (old, new, old))
                db.commit()
            for file in (stage / 'runs').rglob('*.json'):
                content = file.read_text()
                if old in content:
                    file.write_text(content.replace(old, new))
            # Recompute hashes for manifests whose embedded artifact paths changed.
            import hashlib
            with sqlite3.connect(stage / 'library.db') as db:
                for video_id, step, path in db.execute('SELECT video_id, step, artifact_path FROM checkpoints').fetchall():
                    copied = Path(path.replace(str(destination), str(stage), 1))
                    if copied.is_file():
                        db.execute('UPDATE checkpoints SET artifact_sha256 = ? WHERE video_id = ? AND step = ?', (hashlib.sha256(copied.read_bytes()).hexdigest(), video_id, step))
                db.commit()
        (stage / 'migration.json').write_text(json.dumps({'source': str(source), 'completed': True}))
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--migrate', nargs=2)
    args = parser.parse_args()
    if args.migrate:
        migrate(*(Path(p) for p in args.migrate))
        return
    import uvicorn
    from fastapi.responses import Response
    from fastapi.staticfiles import StaticFiles
    from backend.app.main import create_app
    token = os.environ['KITE_DESKTOP_TOKEN']
    app = create_app()

    @app.middleware('http')
    async def desktop_access(request, call_next):
        import secrets
        if not secrets.compare_digest(request.headers.get('x-kite-token', ''), token):
            return Response(status_code=403)
        return await call_next(request)

    app.mount('/', StaticFiles(directory=Path(__file__).parent / 'ui', html=True), name='desktop')
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level='info'))
    parent = os.getppid()
    def watch_parent():
        while not server.should_exit:
            if os.getppid() != parent:
                server.should_exit = True
            time.sleep(0.5)
    threading.Thread(target=watch_parent, daemon=True).start()
    print('KITE_READY=' + str(listener.getsockname()[1]), flush=True)
    server.run(sockets=[listener])


if __name__ == '__main__':
    main()
