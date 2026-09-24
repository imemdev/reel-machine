import subprocess
import sys
import time
from pathlib import Path

from backend.app import procs
from backend.app.pipeline import yta_command


def test_windows_download_command_uses_portable_wrapper(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("KITE_DESKTOP_TOKEN", raising=False)
    monkeypatch.setattr(procs, "IS_WINDOWS", True)
    command = yta_command(yta_function="./scripts/yta", source_url="https://www.instagram.com/reel/example/",
                          output=tmp_path / "source.%(ext)s")
    assert command[0] == sys.executable
    assert Path(command[1]).name == "yta.py" and Path(command[1]).is_file()
    assert command[2:] == ["https://www.instagram.com/reel/example/", "--output", str(tmp_path / "source.%(ext)s")]


def test_windows_group_kwargs_and_taskkill(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(procs, "IS_WINDOWS", True)
    monkeypatch.setattr(procs.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(procs.subprocess, "run", lambda command, **kwargs: calls.append(command))
    assert procs.new_group_kwargs() == {"creationflags": 0x200}
    procs.terminate_tree(4321)
    procs.kill_tree(4321)
    assert calls == [["taskkill", "/PID", "4321", "/T", "/F"]] * 2


def test_posix_process_tree_is_stopped() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], **procs.new_group_kwargs())
    assert procs.process_alive(child.pid)
    procs.terminate_tree(child.pid)
    child.wait(timeout=5)
    time.sleep(0.1)
    assert not procs.process_alive(child.pid)
