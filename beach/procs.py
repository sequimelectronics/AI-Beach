"""Start a child program that ends when this process ends, however this process ends.

A plain child outlives its parent if the parent is killed abruptly (its window closed on Windows,
`kill -9` elsewhere): no `finally:` runs, so nothing stops the child. `python -m beach.world` uses
this so a world never keeps running and listening without its bridge.

- **Windows:** this process joins a Job Object created with "kill on close" before it starts the
  child, so the child (and anything the child starts) is in the job too. Windows closes this
  process's handle to the job when it ends, for any reason, and then ends everything in the job.
- **Elsewhere (POSIX):** the child runs in its own process group, and a small guard process
  (`python -m beach.procs <group>`) holds the read end of a pipe whose write end only this process
  has. When this process ends, for any reason, the pipe closes, and the guard ends the child's
  whole group (SIGTERM, then SIGKILL after a few seconds). On a normal stop this process tells the
  guard it's done first, so the guard just exits.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

WINDOWS = os.name == "nt"
ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------------------- Windows

JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9          # JOBOBJECTINFOCLASS
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
PROCESS_SET_QUOTA, PROCESS_TERMINATE = 0x0100, 0x0001


class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                                               "OtherOperationCount", "ReadTransferCount",
                                               "WriteTransferCount", "OtherTransferCount")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _kill_on_close_job():
    """A new Job Object whose processes all end when its last handle closes. Returns its handle."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
    info = _ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                       ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
    return job


def _assign(job, pid: int | None = None) -> bool:
    """Put a process (this one if pid is None) into the job."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    if pid is None:
        return bool(k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()))
    handle = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(k32.AssignProcessToJobObject(job, handle))
    finally:
        k32.CloseHandle(handle)


# ----------------------------------------------------------------------------------------- both

class TiedChild:
    """One child program, tied to this process's life (see the module docstring)."""

    def __init__(self, cmd: list[str], **popen):
        self.guard = None
        self._job = None
        # All three standard handles explicit: the child never inherits (and Windows never has to
        # duplicate) this process's own, which may be missing or invalid (no console, a test runner).
        for std in ("stdin", "stdout", "stderr"):
            popen.setdefault(std, subprocess.DEVNULL)
        if WINDOWS:
            self._job = _kill_on_close_job()
            # Joining the job ourselves first means the child is in it from its first instruction,
            # with everything it starts. If this process can't join (an old Windows that doesn't
            # nest jobs), the child is added right after it starts instead.
            joined = _assign(self._job)
            popen.setdefault("creationflags", subprocess.CREATE_NEW_PROCESS_GROUP)
            self.proc = subprocess.Popen(cmd, **popen)
            if not joined and not _assign(self._job, self.proc.pid):
                print("warning: couldn't tie the world to this window; close it with Ctrl+C",
                      file=sys.stderr)
        else:
            self.proc = subprocess.Popen(cmd, start_new_session=True, **popen)
            env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]))
            self.guard = subprocess.Popen([sys.executable, "-m", "beach.procs", str(self.proc.pid)],
                                          stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, env=env, cwd=str(ROOT),
                                          start_new_session=True)

    def poll(self):
        return self.proc.poll()

    @property
    def returncode(self):
        return self.proc.returncode

    @property
    def pid(self) -> int:
        return self.proc.pid

    def stop(self, grace: float = 10.0) -> None:
        """End the child and everything it started: politely first, then by force."""
        if self.proc.poll() is None:
            try:
                if WINDOWS:
                    self.proc.terminate()      # TerminateProcess: Windows has no polite kill for this
                else:
                    os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=grace)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    if WINDOWS:
                        self.proc.kill()
                    else:
                        os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        if self.guard is not None and self.guard.poll() is None:
            try:
                self.guard.stdin.write(b"done\n")     # stopped cleanly: the guard has nothing to do
                self.guard.stdin.close()
                self.guard.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.guard.kill()


def guard(pgid: int) -> int:
    """The POSIX guard: wait for the launcher to end, then end the world's process group."""
    for sig in (signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
        signal.signal(sig, signal.SIG_IGN)      # Ctrl+C or a closing terminal is the launcher's call
    said = sys.stdin.buffer.read()                # returns when the launcher ends or says "done"
    if said.startswith(b"done"):
        return 0
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return 0
    end = time.monotonic() + 5
    while time.monotonic() < end:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return 0
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(guard(int(sys.argv[1])))
