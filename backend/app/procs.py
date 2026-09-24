"""Cross-platform helpers for starting and stopping process trees.

macOS and Linux use POSIX process groups. Windows has no process groups in the
same sense, so child trees are started in a new process group and stopped with
``taskkill /T``, which walks the whole descendant tree.
"""
from __future__ import annotations

import os
import signal
import subprocess
from typing import Any

IS_WINDOWS = os.name == "nt"


def new_group_kwargs() -> dict[str, Any]:
    """Popen keyword arguments that isolate a child and its descendants."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _taskkill(pid: int, *, force: bool) -> None:
    command = ["taskkill", "/PID", str(pid), "/T"]
    if force:
        command.append("/F")
    subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=False)


def terminate_tree(pid: int) -> None:
    """Ask a process tree to stop (SIGTERM on POSIX)."""
    if IS_WINDOWS:
        # Console children rarely honour a polite taskkill; force keeps pause prompt.
        _taskkill(pid, force=True)
    else:
        os.killpg(pid, signal.SIGTERM)


def kill_tree(pid: int) -> None:
    """Forcefully stop a process tree (SIGKILL on POSIX)."""
    if IS_WINDOWS:
        _taskkill(pid, force=True)
    else:
        os.killpg(pid, signal.SIGKILL)


def kill_own_tree() -> None:
    """Forcefully stop the current process and everything it started."""
    if IS_WINDOWS:
        _taskkill(os.getpid(), force=True)
        os._exit(1)
    os.killpg(os.getpgrp(), signal.SIGKILL)


def process_alive(pid: int) -> bool:
    """Return whether ``pid`` still refers to a running process."""
    if pid <= 0:
        return False
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        synchronize = 0x00100000
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x00000102  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
