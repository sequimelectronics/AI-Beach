# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Drive-In projector: one program's sound, turned into words, sent to the Drive-In's screen.

Windows 10 (2004) or later. On the keeper's own computer, beside the local speech-to-text helper (whisper_service.py):

    python -E -P projector.py claim --config <projector.json>     # once: the code from the Drive-In page
    python -E -P projector.py run --config <projector.json> [--title "What's on"]

What it captures (Pharos, 11-01), fail closed:
- ONE chosen program's sound and its child processes (Windows' per-process loopback), and nothing else. There is no
  code here for the whole computer's sound or for a microphone, so there is nothing to fall back to: if the chosen
  program can't be captured, the show doesn't start.
- The list shows only programs making sound right now, with their window titles; calls and chat programs are refused
  (DENY). A browser plays every tab through one process, so show from a browser used only for the Drive-In (its own
  profile), never the one with a call open in another tab.
- When the program closes, capture stops: pick again. The console says ON AIR while it captures; Ctrl+C stops it.
  After IDLE_STOP_S with no speech it stops by itself.

Where the words go: the local helper only (127.0.0.1), then the one Beach in the config, with the projector's own
narrow sign-in (it can open a show, send its words and end it, nothing else). The sign-in is kept encrypted for this
Windows user (DPAPI). The sound itself never leaves the computer and is never saved.
"""

from __future__ import annotations

import argparse
import ctypes
import http.client
import json
import os
import sys
import threading
import time
import urllib.parse
from ctypes import POINTER, byref, c_uint32, c_uint64, c_void_p, wintypes

sys.coinit_flags = 0      # COINIT_MULTITHREADED, before comtypes loads: the activation handler must be agile

RATE = 16000
CHUNK_MIN_S, CHUNK_MAX_S = 6.0, 14.0     # send speech in pieces cut at a pause, never longer than this
QUIET_RMS = 300                          # 16-bit amplitude under which a 0.3 s window counts as a pause
IDLE_STOP_S = 30 * 60
DENY = {"discord.exe", "teams.exe", "ms-teams.exe", "msteams.exe", "zoom.exe", "skype.exe", "slack.exe",
        "phoneexperiencehost.exe", "phonelink.exe", "claude.exe", "whatsapp.exe", "signal.exe", "telegram.exe",
        "python.exe", "pythonw.exe",     # calls and chat apps; Python, where a voice may run
        "msedgewebview2.exe",            # app windows built on WebView2 (a voice assistant's window may be one)
        # Parents of many other programs (Pharos, 11-01): capturing one captures its whole tree.
        "explorer.exe", "svchost.exe", "audiodg.exe", "sihost.exe", "runtimebroker.exe", "conhost.exe",
        "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe"}
TREE_CHECK_S = 10                        # during a show, the captured tree is re-checked this often


# ---------------------------------------------------------------------------------------------- the sign-in (DPAPI)

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    src, out = _Blob(len(data), ctypes.cast(buf, POINTER(ctypes.c_char))), _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(byref(src), None, None, None, None, 0x1, byref(out)):    # CRYPTPROTECT_UI_FORBIDDEN
        raise OSError("couldn't " + ("protect" if protect else "read") + " the projector's sign-in for this Windows user")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    base = urllib.parse.urlsplit(str(cfg.get("beach", "")))
    if base.scheme not in ("http", "https") or not base.hostname or base.path not in ("", "/"):
        sys.exit('config "beach" must be the Beach\'s address, e.g. http://192.168.1.20:8765')
    cfg["_beach"] = base
    cfg.setdefault("whisper_port", 8796)
    cfg.setdefault("token_file", os.path.join(os.path.dirname(os.path.abspath(path)), "projector.token"))
    # This computer's own programs that must never be captured (a household voice app's names, say): kept in the
    # local config, never in the shared code.
    cfg["_deny"] = DENY | {str(n).lower() for n in cfg.get("deny_also", []) if str(n).strip()}
    return cfg


def read_token(cfg: dict) -> str:
    try:
        return _dpapi(open(cfg["token_file"], "rb").read(), protect=False).decode()
    except FileNotFoundError:
        sys.exit("no projector sign-in yet: run `projector.py claim` with a code from the Drive-In page")


# ---------------------------------------------------------------------------------------------- talking to the Beach

def beach_call(cfg: dict, method: str, path: str, body: dict | None, token: str | None) -> tuple[int, dict]:
    u = cfg["_beach"]
    conn = (http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection)(u.hostname, u.port,
                                                                                                timeout=20)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    conn.request(method, path, body=json.dumps(body or {}), headers=headers)
    r = conn.getresponse()
    try:
        return r.status, json.loads(r.read() or b"{}")
    except ValueError:
        return r.status, {}


def transcribe(cfg: dict, pcm: bytes) -> list[str]:
    conn = http.client.HTTPConnection("127.0.0.1", int(cfg["whisper_port"]), timeout=60)
    conn.request("POST", "/transcribe", body=pcm, headers={"Content-Type": "application/octet-stream"})
    r = conn.getresponse()
    data = json.loads(r.read() or b"{}")
    if r.status != 200:
        raise RuntimeError(data.get("error") or f"speech-to-text answered {r.status}")
    return [s["text"] for s in data.get("segments", []) if s.get("text")]


# ---------------------------------------------------------------------------------------------- Windows audio (COM)

def _com():
    import comtypes
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class IMMDevice(IUnknown):
        _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
        _methods_ = [COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID), "iid"), (["in"], wintypes.DWORD, "ctx"),
                               (["in"], c_void_p, "params"), (["out"], POINTER(POINTER(IUnknown)), "out"))]

    class IMMDeviceCollection(IUnknown):
        _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
        _methods_ = [COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(wintypes.UINT), "n")),
                     COMMETHOD([], HRESULT, "Item", (["in"], wintypes.UINT, "i"), (["out"], POINTER(POINTER(IMMDevice)), "d"))]

    class IMMDeviceEnumerator(IUnknown):
        _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        _methods_ = [COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], wintypes.UINT, "flow"),
                               (["in"], wintypes.DWORD, "state"), (["out"], POINTER(POINTER(IMMDeviceCollection)), "c"))]

    class IAudioSessionControl2(IUnknown):
        _iid_ = GUID("{bfb7ff88-7239-4fc9-8fa2-07c950be9c6d}")
        _methods_ = [COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(wintypes.UINT), "s")),
                     COMMETHOD([], HRESULT, "GetDisplayName", (["out"], POINTER(wintypes.LPWSTR), "n")),
                     COMMETHOD([], HRESULT, "SetDisplayName"), COMMETHOD([], HRESULT, "GetIconPath"),
                     COMMETHOD([], HRESULT, "SetIconPath"), COMMETHOD([], HRESULT, "GetGroupingParam"),
                     COMMETHOD([], HRESULT, "SetGroupingParam"), COMMETHOD([], HRESULT, "RegisterAudioSessionNotification"),
                     COMMETHOD([], HRESULT, "UnregisterAudioSessionNotification"),
                     COMMETHOD([], HRESULT, "GetSessionIdentifier"), COMMETHOD([], HRESULT, "GetSessionInstanceIdentifier"),
                     COMMETHOD([], HRESULT, "GetProcessId", (["out"], POINTER(wintypes.DWORD), "pid"))]

    class IAudioSessionEnumerator(IUnknown):
        _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
        _methods_ = [COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(ctypes.c_int), "n")),
                     COMMETHOD([], HRESULT, "GetSession", (["in"], ctypes.c_int, "i"),
                               (["out"], POINTER(POINTER(IUnknown)), "s"))]

    class IAudioSessionManager2(IUnknown):
        _iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
        _methods_ = [COMMETHOD([], HRESULT, "GetAudioSessionControl"), COMMETHOD([], HRESULT, "GetSimpleAudioVolume"),
                     COMMETHOD([], HRESULT, "GetSessionEnumerator", (["out"], POINTER(POINTER(IAudioSessionEnumerator)), "e"))]

    class IAudioCaptureClient(IUnknown):
        _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
        _methods_ = [COMMETHOD([], HRESULT, "GetBuffer", (["out"], POINTER(c_void_p), "data"),
                               (["out"], POINTER(c_uint32), "frames"), (["out"], POINTER(wintypes.DWORD), "flags"),
                               (["out"], POINTER(c_uint64), "pos"), (["out"], POINTER(c_uint64), "qpc")),
                     COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "frames")),
                     COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "n"))]

    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD), ("nSamplesPerSec", wintypes.DWORD),
                    ("nAvgBytesPerSec", wintypes.DWORD), ("nBlockAlign", wintypes.WORD),
                    ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]

    class IAudioClient(IUnknown):
        _iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
        _methods_ = [COMMETHOD([], HRESULT, "Initialize", (["in"], wintypes.UINT, "mode"), (["in"], wintypes.DWORD, "flags"),
                               (["in"], ctypes.c_longlong, "buf"), (["in"], ctypes.c_longlong, "period"),
                               (["in"], POINTER(WAVEFORMATEX), "fmt"), (["in"], c_void_p, "session")),
                     COMMETHOD([], HRESULT, "GetBufferSize"), COMMETHOD([], HRESULT, "GetStreamLatency"),
                     COMMETHOD([], HRESULT, "GetCurrentPadding"), COMMETHOD([], HRESULT, "IsFormatSupported"),
                     COMMETHOD([], HRESULT, "GetMixFormat"), COMMETHOD([], HRESULT, "GetDevicePeriod"),
                     COMMETHOD([], HRESULT, "Start"), COMMETHOD([], HRESULT, "Stop"), COMMETHOD([], HRESULT, "Reset"),
                     COMMETHOD([], HRESULT, "SetEventHandle"),
                     COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "iid"),
                               (["out"], POINTER(POINTER(IUnknown)), "svc"))]

    class IActivateAudioInterfaceAsyncOperation(IUnknown):
        _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
        _methods_ = [COMMETHOD([], HRESULT, "GetActivateResult", (["out"], POINTER(HRESULT), "hr"),
                               (["out"], POINTER(POINTER(IUnknown)), "iface"))]

    class IActivateAudioInterfaceCompletionHandler(IUnknown):
        _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
        _methods_ = [COMMETHOD([], HRESULT, "ActivateCompleted",
                               (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "op"))]

    class IAgileObject(IUnknown):
        _iid_ = GUID("{94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90}")
        _methods_ = []

    return {k: v for k, v in locals().items() if not k.startswith("_")} | {"comtypes": comtypes, "GUID": GUID,
                                                                            "IUnknown": IUnknown}


def sounding_programs() -> list[dict]:
    """Programs playing sound right now (their audio session is active), with names and window titles."""
    import comtypes
    import psutil
    C = _com()
    comtypes.CoInitializeEx(0)
    enum = comtypes.CoCreateInstance(C["GUID"]("{BCDE0395-E52F-467C-8E3D-C4579291692E}"), C["IMMDeviceEnumerator"],
                                     comtypes.CLSCTX_ALL)
    devices = enum.EnumAudioEndpoints(0, 1)          # eRender, DEVICE_STATE_ACTIVE
    found: dict[int, dict] = {}
    for i in range(devices.GetCount()):
        mgr = devices.Item(i).Activate(byref(C["IAudioSessionManager2"]._iid_), comtypes.CLSCTX_ALL, None)
        sessions = mgr.QueryInterface(C["IAudioSessionManager2"]).GetSessionEnumerator()
        for j in range(sessions.GetCount()):
            ctl = sessions.GetSession(j).QueryInterface(C["IAudioSessionControl2"])
            if ctl.GetState() != 1:                     # AudioSessionStateActive
                continue
            pid = ctl.GetProcessId()
            if not pid or pid in found:
                continue
            try:
                proc = psutil.Process(pid)
                name = proc.name()
            except psutil.Error:
                continue
            found[pid] = {"pid": pid, "name": name, "created": proc.create_time(),
                          "titles": window_titles({pid, *_parents(proc)})}
    return sorted(found.values(), key=lambda p: p["name"].lower())


def _parents(proc) -> list[int]:
    out = []
    try:
        for p in proc.parents()[:3]:
            out.append(p.pid)
    except Exception:
        pass
    return out


def window_titles(pids: set[int]) -> list[str]:
    user32 = ctypes.windll.user32
    titles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, byref(pid))
            if pid.value in pids:
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    titles.append(buf.value)
        return True

    user32.EnumWindows(each, 0)
    return titles[:3]


class ProcessCapture:
    """Windows' per-process loopback: the sound ONE process (and its children) plays, as 16 kHz mono 16-bit samples.
    This is the only way this file captures anything."""

    def __init__(self, pid: int, name: str, created: float):
        import comtypes
        from comtypes import COMObject
        C = _com()
        self.C = C
        comtypes.CoInitializeEx(0)
        kernel32 = ctypes.windll.kernel32
        self.handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)   # SYNCHRONIZE | QUERY_LIMITED_INFO
        if not self.handle:
            raise RuntimeError("that program has already closed")
        # Still the program that was picked? Between the list and "yes" it could have closed and its number gone to
        # another program (Pharos, 11-01). Checked AFTER opening it, so the number can't change hands again.
        import psutil
        try:
            now = psutil.Process(pid)
            same = now.name() == name and abs(now.create_time() - created) < 0.01
        except psutil.Error:
            same = False
        if not same:
            kernel32.CloseHandle(self.handle)
            raise RuntimeError("that program closed and its place was taken by another; pick again")

        class Params(ctypes.Structure):   # AUDIOCLIENT_ACTIVATION_PARAMS: process loopback, include the target's tree
            _fields_ = [("type", ctypes.c_int), ("pid", wintypes.DWORD), ("mode", ctypes.c_int)]

        class Blob(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.ULONG), ("pBlobData", c_void_p)]

        class PropVariant(ctypes.Structure):
            _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.WORD), ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                        ("blob", Blob)]

        self.params = Params(1, pid, 0)    # AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK, INCLUDE_TARGET_PROCESS_TREE
        pv = PropVariant(65, 0, 0, 0, Blob(ctypes.sizeof(Params), ctypes.cast(byref(self.params), c_void_p)))
        done = threading.Event()

        class Handler(COMObject):
            _com_interfaces_ = [C["IActivateAudioInterfaceCompletionHandler"], C["IAgileObject"]]

            def ActivateCompleted(self, op):
                done.set()
                return 0

        handler = Handler()
        op = POINTER(C["IActivateAudioInterfaceAsyncOperation"])()
        activate = ctypes.windll.mmdevapi.ActivateAudioInterfaceAsync
        activate.argtypes = [wintypes.LPCWSTR, POINTER(C["GUID"]), c_void_p, c_void_p, c_void_p]
        hr = activate("VAD\\Process_Loopback", byref(C["IAudioClient"]._iid_), byref(pv),
                      handler.QueryInterface(C["IActivateAudioInterfaceCompletionHandler"]), byref(op))
        if hr != 0 or not done.wait(10):
            raise RuntimeError(f"Windows couldn't start capturing that program (0x{hr & 0xFFFFFFFF:08X})")
        result, iface = op.GetActivateResult()
        if result != 0 or not iface:
            raise RuntimeError(f"Windows refused to capture that program (0x{result & 0xFFFFFFFF:08X})")
        self.client = iface.QueryInterface(C["IAudioClient"])
        fmt = C["WAVEFORMATEX"](1, 1, RATE, RATE * 2, 2, 16, 0)     # PCM, mono, 16 kHz, 16-bit
        flags = 0x00020000 | 0x80000000 | 0x08000000                 # LOOPBACK | AUTOCONVERTPCM | SRC_DEFAULT_QUALITY
        self.client.Initialize(0, flags, 20_000_000, 0, byref(fmt), None)  # shared mode, a 2 s buffer
        svc = self.client.GetService(byref(C["IAudioCaptureClient"]._iid_))
        self.capture = svc.QueryInterface(C["IAudioCaptureClient"])
        self.client.Start()
        # Read on a thread of its own, every 20 ms: speech-to-text takes about a second per piece, and a reader that
        # waited for it would let the buffer overflow and drop words (found in testing, 11-01).
        self.pending = bytearray()
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.reader = threading.Thread(target=self._read_forever, name="drivein-capture", daemon=True)
        self.reader.start()

    def _read_forever(self) -> None:
        import comtypes
        comtypes.CoInitializeEx(0)
        while not self.stopping.is_set():
            data = self.read()
            if data:
                with self.lock:
                    self.pending += data
            time.sleep(0.02)

    def take(self) -> bytes:
        with self.lock:
            out, self.pending = bytes(self.pending), bytearray()
        return out

    def alive(self) -> bool:
        return ctypes.windll.kernel32.WaitForSingleObject(self.handle, 0) != 0     # WAIT_OBJECT_0 = it exited

    def read(self) -> bytes:
        out = bytearray()
        while self.capture.GetNextPacketSize():
            data, frames, flags, _, _ = self.capture.GetBuffer()
            n = frames * 2
            out += b"\0" * n if flags & 0x2 else ctypes.string_at(data, n)        # AUDCLNT_BUFFERFLAGS_SILENT
            self.capture.ReleaseBuffer(frames)
        return bytes(out)

    def close(self) -> None:
        self.stopping.set()
        self.reader.join(timeout=2)
        try:
            self.client.Stop()
        except Exception:
            pass
        ctypes.windll.kernel32.CloseHandle(self.handle)


# ---------------------------------------------------------------------------------------------- the show

def rms(pcm: bytes) -> float:
    import numpy as np
    a = np.frombuffer(pcm, dtype="<i2").astype("float32")
    return float(np.sqrt((a * a).mean())) if a.size else 0.0


def cut_point(buf: bytes) -> int | None:
    """Where to cut the sound to send: at a pause after CHUNK_MIN_S, or at CHUNK_MAX_S. None: keep listening."""
    n = len(buf) // 2
    if n < CHUNK_MIN_S * RATE:
        return None
    win = int(0.3 * RATE)
    for start in range(int(CHUNK_MIN_S * RATE), n - win, win // 2):
        if rms(buf[start * 2:(start + win) * 2]) < QUIET_RMS:
            return (start + win // 2) * 2
    return int(CHUNK_MAX_S * RATE) * 2 if n >= CHUNK_MAX_S * RATE else None


def denied_in_tree(pid: int, deny: set[str]) -> list[str]:
    """Programs that must never be captured, in this process or anywhere under it: capturing a process captures its
    whole tree (Pharos, 11-01: explorer, a terminal or a launcher parents a great deal). A vanished process: [] here;
    the capture notices it's gone on its own."""
    import psutil
    try:
        proc = psutil.Process(pid)
        tree = [proc, *proc.children(recursive=True)]
    except psutil.Error:
        return []
    out = []
    for p in tree:
        try:
            if p.name().lower() in deny:
                out.append(p.name())
        except psutil.Error:
            pass
    return out


def pick(programs: list[dict], deny: set[str] = DENY) -> dict | None:
    allowed, refused = [], []
    for p in programs:
        bad = [p["name"]] if p["name"].lower() in deny else denied_in_tree(p["pid"], deny)
        (refused if bad else allowed).append({**p, "why": bad})
    for p in refused:
        print(f"  (not offered: {p['name']}: it is, or runs, {', '.join(sorted(set(p['why'])))}, which is never captured)")
    if not allowed:
        print("Nothing is playing sound right now. Start the video or game, then run this again.")
        return None
    for i, p in enumerate(allowed, 1):
        print(f"  {i}. {p['name']} (process {p['pid']}): " + (" | ".join(p["titles"]) or "no window title"))
    choice = input("Which one is the show? (number, or Enter to cancel): ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(allowed):
        return None
    p = allowed[int(choice) - 1]
    if p["name"].lower() in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"):
        print("A browser plays EVERY tab through one process: this should be a browser window used only for the "
              "Drive-In (its own profile), with no call or other sound in another tab.")
        if input("Is it? (yes/no): ").strip().lower() != "yes":
            return None
    if input(f"Capture {p['name']}: {' | '.join(p['titles']) or 'no title'}? (yes/no): ").strip().lower() != "yes":
        return None
    return p


def run(cfg: dict, title: str | None) -> int:
    token = read_token(cfg)
    deny = cfg["_deny"]
    # Many programs (Blender, for one) only appear to Windows while they're actually playing sound: wait for the
    # show to start rather than giving up (the keeper, 11-01: Blender, paused, wasn't in the list).
    programs = [p for p in sounding_programs() if p["name"].lower() not in deny]
    if not programs:
        print("Nothing is making sound yet. Press Play on your show; waiting for it (Ctrl+C to stop)...")
        try:
            while not programs:
                time.sleep(2)
                programs = [p for p in sounding_programs() if p["name"].lower() not in deny]
        except KeyboardInterrupt:
            print("No show started.")
            return 1
    choice = pick(sounding_programs(), deny)
    if not choice:
        print("No show started.")
        return 1
    if denied_in_tree(choice["pid"], deny):   # it started something while you were choosing
        print("That program now runs something that is never captured. No show started.")
        return 1
    cap = ProcessCapture(choice["pid"], choice["name"], choice["created"])
    if title:
        st, r = beach_call(cfg, "POST", "/drivein/show", {"title": title}, token)
        if st not in (200, 409):
            cap.close()
            sys.exit(f"the Beach refused: {r.get('message') or st}")
    ctypes.windll.kernel32.SetConsoleTitleW("ON AIR - Drive-In projector")
    print(f"\n*** ON AIR: capturing {choice['name']} (process {choice['pid']}) and nothing else. Ctrl+C stops. ***\n")
    buf, last_speech, tree_at = b"", time.monotonic(), time.monotonic()
    try:
        while True:
            if not cap.alive():
                print("The program closed: capture stopped. Run again to pick a program.")
                break
            if time.monotonic() - tree_at >= TREE_CHECK_S:
                tree_at = time.monotonic()
                bad = denied_in_tree(choice["pid"], deny)
                if bad:
                    print(f"The show's program started {', '.join(sorted(set(bad)))}, which is never captured: "
                          "capture stopped.")
                    break
            buf += cap.take()
            cut = cut_point(buf)
            if cut:
                piece, buf = buf[:cut], buf[cut:]
                if rms(piece) >= QUIET_RMS / 3:
                    lines = transcribe(cfg, piece)
                    if lines:
                        last_speech = time.monotonic()
                        st, r = beach_call(cfg, "POST", "/drivein/lines", {"lines": lines}, token)
                        if st == 409:
                            print("Nothing is showing on the Beach: start the show on the Drive-In page (or --title).")
                        elif st != 200:
                            print(f"The Beach refused the lines: {r.get('message') or st}")
                        else:
                            for ln in lines:
                                print("  >", ln)
            if time.monotonic() - last_speech > IDLE_STOP_S:
                print(f"No speech for {IDLE_STOP_S // 60} minutes: capture stopped.")
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        cap.close()
        ctypes.windll.kernel32.SetConsoleTitleW("Drive-In projector")
    if input("End the show on the Beach too? (yes/no): ").strip().lower() == "yes":
        st, r = beach_call(cfg, "POST", "/drivein/show/end", None, token)
        print("The show has ended." if st == 200 else f"(the Beach said: {r.get('message') or st})")
    return 0


def claim(cfg: dict) -> int:
    # Shown as it's pasted (the keeper, 11-01: a hidden prompt made a mistyped or empty paste impossible to see). The
    # code is one-time and expires in an hour; the sign-in it becomes is what's protected.
    code = input("Projector code from the Drive-In page (paste it, then Enter): ").strip()
    if not code:
        sys.exit("Nothing was pasted. Copy the code from the Drive-In page (Projector sign-ins) and try again.")
    st, r = beach_call(cfg, "POST", "/drivein/claim", {"code": code}, None)
    if st != 200 or "token" not in r:
        why = r.get("message") or r.get("detail") or f"HTTP {st}"
        sys.exit(f"The Beach refused the code: {why}\n(Each code works once, for an hour; making a new one is fine.)")
    with open(cfg["token_file"], "wb") as f:
        f.write(_dpapi(r["token"].encode(), protect=True))
    print(f'Claimed: this projector is "{r.get("projector")}". Its sign-in is saved, encrypted for this Windows user.')
    return 0


def main() -> int:
    if os.name != "nt":
        sys.exit("the projector runs on Windows 10 (2004) or later")
    ap = argparse.ArgumentParser(description="The Drive-In projector: one program's speech, as words, to the Beach")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("claim", "run", "list"):
        s = sub.add_parser(name)
        s.add_argument("--config", required=True, help="projector.json: {\"beach\": \"http://<the Beach>\"}")
        if name == "run":
            s.add_argument("--title", help="open the show with this title (or start it on the Drive-In page)")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.cmd == "claim":
        return claim(cfg)
    if a.cmd == "list":
        for p in sounding_programs():
            flag = "  (never offered)" if p["name"].lower() in cfg["_deny"] or denied_in_tree(p["pid"], cfg["_deny"]) else ""
            print(f"{p['name']} (process {p['pid']}): {' | '.join(p['titles']) or 'no window title'}{flag}")
        return 0
    return run(cfg, a.title)


if __name__ == "__main__":
    sys.exit(main())
