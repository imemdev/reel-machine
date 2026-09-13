"""Assemble this Mac's tested runtime into a relocatable application payload."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'desktop/payload'
DEST.mkdir(exist_ok=True)

def copytree(source, target):
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*editable*', '*.pth'))

python = next((ROOT / 'desktop/python-download').glob('cpython-*/bin/python3'))
copytree(python.parent.parent, DEST / 'python')
copytree(ROOT / '.venv/lib/python3.13/site-packages', DEST / 'python/lib/python3.13/site-packages')
copytree(ROOT / 'backend', DEST / 'backend')
copytree(ROOT / 'frontend/.next-desktop', DEST / 'ui')
shutil.copy2(ROOT / 'desktop/server.py', DEST / 'server.py')
tools = DEST / 'tools'
(tools / 'lib').mkdir(parents=True, exist_ok=True)
seen = {}

def bundle(source, target):
    source = Path(source).resolve()
    if str(source) in seen:
        return seen[str(source)]
    seen[str(source)] = target
    shutil.copy2(source, target)
    target.chmod(0o755)
    lines = subprocess.check_output(['otool', '-L', str(source)], text=True).splitlines()[1:]
    load_commands = subprocess.check_output(['otool', '-l', str(source)], text=True)
    rpaths = re.findall(r'cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (.*?) \(offset', load_commands)
    for line in lines:
        dependency = line.strip().split(' (')[0]
        resolved = dependency
        if dependency.startswith('@rpath/'):
            candidates = [Path(r.replace('@loader_path', str(source.parent))) / dependency[len('@rpath/'):] for r in rpaths]
            resolved = str(next((p for p in candidates if p.is_file()), Path('/opt/homebrew/opt/node/lib') / Path(dependency).name))
            if not Path(resolved).is_file():
                raise RuntimeError(f'Cannot resolve {dependency} from {source}')
        elif dependency.startswith('@loader_path/'):
            resolved = dependency.replace('@loader_path', str(source.parent))
        if resolved.startswith('/opt/homebrew/') and Path(resolved).resolve() != source:
            bundled = bundle(resolved, tools / 'lib' / Path(dependency).name)
            relative = '@loader_path/' + os.path.relpath(bundled, target.parent)
            subprocess.run(['install_name_tool', '-change', dependency, relative, str(target)], check=True, capture_output=True)
    if target.suffix == '.dylib':
        subprocess.run(['install_name_tool', '-id', '@loader_path/' + target.name, str(target)], check=True, capture_output=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(target)], check=True, capture_output=True)
    return target

for name in ('ffmpeg', 'ffprobe', 'node'):
    bundle(shutil.which(name), tools / name)
for name, module in [('yt-dlp', 'yt_dlp'), ('gallery-dl', 'gallery_dl')]:
    script = tools / name
    script.write_text('#!/bin/sh\nexec "$(dirname "$0")/../python/bin/python3" -m ' + module + ' "$@"\n')
    script.chmod(0o755)
script = tools / 'yta'
script.write_text('''#!/bin/sh
exec "$(dirname "$0")/yt-dlp" --ignore-config --no-playlist --js-runtimes node --extractor-args 'youtube:player_client=web_embedded' --retries 10 --fragment-retries 10 --extract-audio --audio-format mp3 --audio-quality 0 --embed-metadata --embed-thumbnail "$@"
''')
script.chmod(0o755)
(ROOT/'desktop/migration.json').write_text(json.dumps({'sourceData':str(ROOT/'data')}))
print('Payload assembled:', DEST, flush=True)
