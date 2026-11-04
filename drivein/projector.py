# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Drive-In projector: one program's sound, turned into words, sent to the Drive-In's screen.

Windows 10 (2004) or later, on the keeper's own computer. The keeper's routine (11-01): open the show and pause it,
start this, type the title, pick the app, press Play, go and talk. It starts the local speech-to-text helper
(whisper_service.py) by itself, opens the show on the Beach, and ends it when its window closes.

    python -E -P projector.py claim --config <projector.json>     # once: the code from the Drive-In page
    python -E -P projector.py run --config <projector.json>

What it captures (Pharos, 11-01), fail closed:
- ONE chosen program's sound and its child processes (Windows' per-process loopback), and nothing else. There is no
  code here for the whole computer's sound or for a microphone, so there is nothing to fall back to: if the chosen
  program can't be captured, the show doesn't start. Capture can start while the show is paused, so the first words
  are heard.
- The list shows open apps (those playing marked); calls, chat programs and anything running one are never listed
  (DENY, the whole tree). Picking the app is the choice to capture it: there's no second question. A browser plays
  every tab through one process, so show from a browser window used only for the Drive-In.
- When the program closes, capture stops. The console says ON AIR while it captures; closing it or Ctrl+C ends the
  show. After IDLE_STOP_S with no speech it stops by itself.

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
    # Names to spell right (a town, a shop, a character), sent with each piece as words to expect (the keeper, 11-02:
    # "Sequim" came out "Squim"). Plain words only; the helper cleans them again.
    words = cfg.get("words", [])
    words = words if isinstance(words, list) else [words]
    cfg["_words"] = ", ".join("".join(c for c in str(w) if (c.isalnum() or c in " -'") and ord(c) < 256).strip()
                              for w in words if str(w).strip())[:240]
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
    headers = {"Content-Type": "application/octet-stream"}
    if cfg.get("_words"):
        headers["X-Words"] = cfg["_words"]
    conn.request("POST", "/transcribe", body=pcm, headers=headers)
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


BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe"}


# ------------------------------------------------------------------------------------------- a shared browser tab
# The keeper, 11-03: picking a whole browser captures every tab, and a browser running an extension's command-prompt
# helper is refused, so YouTube meant a second browser. Instead, the projector serves a small page on THIS computer
# (127.0.0.1, which browsers treat as secure, so tab sharing works without HTTPS); the browser's own picker shares ONE
# tab, and the page posts that tab's sound here as raw 16 kHz mono samples. The page holds no Beach sign-in.
TAB_PORT = 8795
TAB_WAIT_S = 600             # time to share a tab after the page opens
TAB_QUIET_S = 20             # no sound from the page this long after sharing = it's gone
TAB_MAX_POST = 256 * 1024    # bytes per post (the page sends about half a second at a time)
TAB_MAX_BUFFER = 60 * RATE * 2
TAB_FILES = {"/": ("tabpage.html", "text/html; charset=utf-8"),
             "/tabpage.js": ("tabpage.js", "text/javascript; charset=utf-8"),
             "/tabpage-worklet.js": ("tabpage-worklet.js", "text/javascript; charset=utf-8")}


class TabCapture:
    """Sound from one shared browser tab, through the local page. Same shape as ProcessCapture (take/alive/close).
    Answers only requests addressed to exactly 127.0.0.1:<port> (no DNS rebinding), posts only from its own page
    (Origin) carrying this show's random key, raw samples only, capped."""

    def __init__(self, port: int = TAB_PORT):
        import secrets
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.key = secrets.token_urlsafe(18)
        self.lock = threading.Lock()
        self.buf = bytearray()
        self.started = self.ended = False
        self.opened = self.last = time.monotonic()
        here = os.path.dirname(os.path.abspath(__file__))
        tab = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):        # nothing about the show in a log
                pass

            def _send(self, status: int, body: bytes = b"", ctype: str = "text/plain; charset=utf-8") -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; connect-src 'self'; "
                                 "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.headers.get("Host") != tab.host:
                    return self._send(421, b"wrong host")
                f = TAB_FILES.get(self.path)
                if not f:
                    return self._send(404, b"not here")
                with open(os.path.join(here, f[0]), "rb") as fh:
                    self._send(200, fh.read(), f[1])

            def do_POST(self):
                import hmac
                if self.headers.get("Host") != tab.host:
                    return self._send(421, b"wrong host")
                if self.headers.get("Origin") != tab.origin:
                    return self._send(403, b"only the projector's own page")
                if not hmac.compare_digest(self.headers.get("X-Key", ""), tab.key):
                    return self._send(403, b"wrong key")
                if self.headers.get("Content-Type") != "application/octet-stream":
                    return self._send(415, b"raw samples only")
                try:
                    size = int(self.headers.get("Content-Length", "-1"))
                except ValueError:
                    size = -1
                if size < 0 or size > TAB_MAX_POST or size % 2:
                    return self._send(413, b"too big")
                body = self.rfile.read(size)
                with tab.lock:
                    if tab.ended:
                        return self._send(410, b"the show has ended")
                    if self.path == "/start":
                        tab.started = True
                    elif self.path == "/stop":
                        tab.ended = True
                    elif self.path == "/pcm" and tab.started:
                        tab.buf += body
                        del tab.buf[:max(0, len(tab.buf) - TAB_MAX_BUFFER)]
                    else:
                        return self._send(404, b"not here")
                    tab.last = time.monotonic()
                self._send(204)

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.server.server_address[1]          # port 0 (tests): the one the system gave
        self.host = f"127.0.0.1:{self.port}"
        self.origin = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, name="drivein-tab-page", daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#k={self.key}"

    def take(self) -> bytes:
        with self.lock:
            out = bytes(self.buf)
            self.buf.clear()
        return out

    def alive(self) -> bool:
        now = time.monotonic()
        with self.lock:
            if self.ended:
                return False
            return now - self.opened < TAB_WAIT_S if not self.started else now - self.last < TAB_QUIET_S

    def close(self) -> None:
        with self.lock:
            self.ended = True
        self.server.shutdown()
        self.server.server_close()
HELPER = None    # the speech helper this projector started (None: one was already running)


def open_programs() -> list[dict]:
    """Programs with a visible, titled window: the show can be picked while it's paused, before it makes any sound
    (capture starts on a silent program and hears it from the first word). Those playing right now are marked."""
    import psutil
    user32 = ctypes.windll.user32
    found: dict[int, dict] = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, byref(pid))
            if pid.value and pid.value not in found:
                try:
                    proc = psutil.Process(pid.value)
                    found[pid.value] = {"pid": pid.value, "name": proc.name(), "created": proc.create_time()}
                except psutil.Error:
                    pass
        return True

    user32.EnumWindows(each, 0)
    # The projector's own capture (and its helper) show up as sound sessions; they mustn't make the window that
    # started it (Explorer, a terminal) look like it's playing (the keeper's list, 11-02).
    me = {os.getpid(), *_children(os.getpid())}
    playing = {p["pid"] for p in sounding_programs()} - me
    out = []
    for pid, p in found.items():
        p["titles"] = window_titles({pid})
        p["playing"] = pid in playing or any(c in playing for c in _children(pid))
        out.append(p)
    return sorted(out, key=lambda p: (not p["playing"], p["name"].lower()))


def _children(pid: int) -> list[int]:
    import psutil
    try:
        return [c.pid for c in psutil.Process(pid).children(recursive=True)]
    except psutil.Error:
        return []


def pick(programs: list[dict], deny: set[str] = DENY) -> dict | None:
    """One question: which app is the show. Picking it IS choosing to capture its sound (the keeper, 11-01: a second
    "capture it?" cost her a whole playthrough). Calls, chat programs and anything running them are never listed."""
    allowed, hidden = [], []
    for p in programs:
        if p["name"].lower() in deny:
            continue                                    # calls, chat, shells: never shown, nothing to explain
        bad = denied_in_tree(p["pid"], deny)
        (hidden if bad else allowed).append((p, sorted(set(bad))))
    print("  0. A browser tab: share just one tab from any browser (extensions and all)")
    for i, (p, _) in enumerate(allowed, 1):
        mark = "  (playing now)" if p.get("playing") else ""
        print(f"  {i}. {p['name']}: " + (" | ".join(p["titles"]) or "no window title") + mark)
    # Say why an app isn't offered (the keeper, 11-03: Chrome just wasn't there; an extension's helper ran cmd.exe).
    for p, bad in hidden:
        why = "a command prompt or shell (often an extension's helper)" if {"cmd.exe", "powershell.exe", "pwsh.exe",
                                                                           "conhost.exe"} & set(bad) else ", ".join(bad)
        print(f"     (not offered: {p['name']}, because it's running {why}; for a browser, use 0)")
    choice = input("Which is the show? (its number): ").strip()
    if choice == "0":
        return {"tab": True, "name": "a shared browser tab", "pid": None, "titles": []}
    if not choice.isdigit() or not 1 <= int(choice) <= len(allowed):
        print("Nothing picked.")
        return None
    p = allowed[int(choice) - 1][0]
    if p["name"].lower() in BROWSERS:
        print("(A browser plays every tab through one program: keep calls and other sound out of its other tabs.)")
    return p


def helper_up(cfg: dict) -> bool:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", int(cfg["whisper_port"]), timeout=2)
        conn.request("GET", "/health")
        return conn.getresponse().status == 200
    except OSError:
        return False


def start_helper(cfg: dict):
    """Start the local speech-to-text helper if it isn't running, and wait until it answers. Returns the process we
    started (to stop at the end), or None if one was already running."""
    if helper_up(cfg):
        return None
    model = cfg.get("model")
    if not model or not os.path.isdir(model):
        sys.exit('set "model" in the config to a faster-whisper model folder (e.g. E:\\\\DriveIn\\\\models\\\\...)')
    import subprocess
    u = cfg["_beach"]
    origin = f"{u.scheme}://{u.netloc}"
    service = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper_service.py")
    proc = subprocess.Popen([sys.executable, "-E", "-P", service, "--model", model, "--beach-origin", origin,
                             "--port", str(cfg["whisper_port"])],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                            creationflags=0x08000000)       # CREATE_NO_WINDOW: no extra window to juggle
    # Its messages are read all the time, into memory only (the last 20 lines; nothing is written anywhere): a pipe
    # nobody reads fills after a few warnings, and the helper would freeze mid-show (Pharos, 11-01).
    from collections import deque
    proc.last_words = deque(maxlen=20)

    def drain():
        for raw in iter(proc.stderr.readline, b""):
            proc.last_words.append(raw.decode(errors="replace").rstrip())

    threading.Thread(target=drain, name="drivein-helper-messages", daemon=True).start()
    print("Starting the speech helper (the first time takes a moment)...", end="", flush=True)
    for _ in range(180):
        if proc.poll() is not None:
            time.sleep(0.2)                                  # let the reader catch the last lines
            sys.exit("\nThe speech helper didn't start:\n" + "\n".join(list(proc.last_words)[-3:]))
        if helper_up(cfg):
            print(" ready.")
            global HELPER
            HELPER = proc
            return proc
        time.sleep(1)
    proc.terminate()
    sys.exit("\nThe speech helper took too long to start.")


# ------------------------------------------------------------------------------------------- caption files (.srt)
# The keeper makes an .srt for every commercial (11-02): real captions beat speech-to-text (names right, nothing
# invented). When the show plays in VLC and an .srt sits beside the file, its captions go to the screen as VLC
# reaches them, following pause, skip and rewind; no sound is captured at all. VLC's own web remote says which file
# is playing and where: it listens on this computer only, behind a password kept encrypted (DPAPI) like the
# projector's sign-in. Without it, or without an .srt, the projector listens as before.

VLC_PORT = 8798                          # 8080 (VLC's usual) is often taken
SRT_MAX_BYTES = 2_000_000
CAPTION_POLL_S = 0.5
JUMP_S = 3.0                             # VLC's time moving by more than this between polls = a skip or rewind


def _srt_time(s: str) -> float:
    h, m, rest = s.strip().replace(".", ",").split(":")
    sec, ms = (rest.split(",") + ["0"])[:2]
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms.ljust(3, "0")[:3]) / 1000


def parse_srt(text: str) -> list[dict]:
    """An .srt's cues as [{"start", "end", "text"}], in time order. Formatting tags ({\\an8}, <i>) are dropped and a
    cue's lines become one line. Anything that doesn't look like a cue is skipped, never guessed at."""
    import re
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", text.replace(chr(0xFEFF), "")):
        lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
        at = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if at is None:
            continue
        try:
            a, b = lines[at].split("-->")[:2]
            start, end = _srt_time(a), _srt_time(b.split()[0])
        except (ValueError, IndexError):
            continue
        words = " ".join(re.sub(r"<[^>]{0,40}>|\{[^}]{0,40}\}", "", ln) for ln in lines[at + 1:])
        words = " ".join(words.split())
        if words:
            cues.append({"start": start, "end": max(end, start), "text": words})
    return sorted(cues, key=lambda c: c["start"])


def srt_beside(video: str) -> str | None:
    """The caption file beside a video: same name with .srt (or .en.srt / .eng.srt)."""
    base, _ = os.path.splitext(video)
    for cand in (base + ".srt", base + ".en.srt", base + ".eng.srt"):
        if os.path.isfile(cand):
            return cand
    return None


def read_srt(path: str) -> list[dict]:
    if os.path.getsize(path) > SRT_MAX_BYTES:
        raise ValueError("that caption file is too big to be captions")
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return parse_srt(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    return []


def vlc_secret_file(cfg: dict) -> str:
    return os.path.join(os.path.dirname(cfg["token_file"]), "vlc.secret")


class VlcRemote:
    """VLC's web remote on this computer (127.0.0.1 only): which file is playing, where, and whether it plays.
    Read-only use: the projector only ever asks for status and the playlist, never sends VLC a command."""

    def __init__(self, password: str, port: int = VLC_PORT):
        import base64
        self.port = port
        self.auth = "Basic " + base64.b64encode(f":{password}".encode()).decode()

    def _get(self, path: str) -> dict:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.request("GET", path, headers={"Authorization": self.auth})
        r = conn.getresponse()
        body = r.read()
        if r.status != 200:
            raise OSError(f"VLC's remote answered {r.status}")
        return json.loads(body)

    def status(self) -> dict:
        s = self._get("/requests/status.json")
        length, pos = float(s.get("length") or 0), float(s.get("position") or 0)
        at = pos * length if length > 0 else float(s.get("time") or 0)
        return {"state": s.get("state"), "time": at, "length": length}

    def current_file(self) -> str | None:
        def walk(node):
            if isinstance(node, dict):
                if node.get("current") and node.get("uri"):
                    return node["uri"]
                for child in node.get("children", []) or []:
                    found = walk(child)
                    if found:
                        return found
            return None
        uri = walk(self._get("/requests/playlist.json"))
        if not uri or not uri.startswith("file:///"):
            return None                         # captions only for a file on this computer
        return urllib.parse.unquote(uri[len("file:///"):]).replace("/", os.sep)


def caption_source(cfg: dict) -> tuple["VlcRemote", list[dict], str] | None:
    """VLC's remote, the playing file's captions and the .srt's name, or None (then the projector listens)."""
    secret = vlc_secret_file(cfg)
    if not os.path.isfile(secret):
        return None
    try:
        vlc = VlcRemote(_dpapi(open(secret, "rb").read(), protect=False).decode(), int(cfg.get("vlc_port", VLC_PORT)))
        video = vlc.current_file()
    except (OSError, ValueError) as e:
        print(f"(VLC's remote didn't answer: {e}. Listening instead.)")
        return None
    srt = srt_beside(video) if video else None
    if not srt:
        return None
    try:
        cues = read_srt(srt)
        length = vlc.status()["length"]
    except (OSError, ValueError) as e:
        print(f"(Couldn't read {os.path.basename(srt)}: {e}. Listening instead.)")
        return None
    cues, shift = from_timeline_start(cues, length)
    if shift:
        print(f"(The captions start at the editor's {int(shift // 3600)}:00:00 timeline mark; following them from 0:00.)")
    return (vlc, cues, os.path.basename(srt)) if cues else None


def from_timeline_start(cues: list[dict], length: float) -> tuple[list[dict], float]:
    """Editors' timelines often start at 01:00:00 (DaVinci Resolve's default), so an exported .srt's first caption
    sits an hour in while the video itself starts at 0:00 (the keeper's first captioned show, 11-03: nothing ever
    reached the screen). When the first caption is an hour or more past the video's end, shift back by those whole
    hours. Returns (cues, seconds shifted)."""
    if not cues or cues[0]["start"] < 3600:
        return cues, 0.0
    hours = int(cues[0]["start"] // 3600)
    if length > 0 and cues[0]["start"] - hours * 3600 > length:
        return cues, 0.0                      # still past the end after shifting: not a timeline offset, leave it
    if length > 0 and cues[0]["start"] <= length:
        return cues, 0.0                      # a long video really does reach its first caption an hour in
    shift = hours * 3600.0
    return [{**c, "start": c["start"] - shift, "end": c["end"] - shift} for c in cues], shift


def next_cues(cues: list[dict], index: int, now: float, last: float | None) -> tuple[list[str], int]:
    """The captions due at VLC time `now`, given the next unsent cue `index` and the time seen last poll. A skip or
    rewind (the time jumping) moves to the cue playing at the new time without replaying the ones skipped over."""
    if last is not None and (now < last - 1.0 or now > last + JUMP_S):
        index = next((i for i, c in enumerate(cues) if c["end"] > now), len(cues))
    due = []
    while index < len(cues) and cues[index]["start"] <= now:
        if cues[index]["end"] > now - JUMP_S:       # a cue long gone (a jump landed past it) isn't sent late
            due.append(cues[index]["text"])
        index += 1
    return due, index


def _captions_on_air(cfg: dict, token: str, choice: dict, vlc: "VlcRemote", cues: list[dict], name: str) -> int:
    import psutil
    _end_on_close(cfg, token)
    ctypes.windll.kernel32.SetConsoleTitleW("ON AIR - Drive-In projector (captions)")
    print(f"\n*** ON AIR: captions from {name} ({len(cues)} lines), following VLC. Press Play whenever you're ready. ***")
    print("    No sound is captured. Close this window (or Ctrl+C) to end the show.\n")
    index, last, misses = 0, None, 0
    try:
        while True:
            if not psutil.pid_exists(choice["pid"]):
                print("VLC closed: the show ends.")
                break
            try:
                st = vlc.status()
                misses = 0
            except (OSError, ValueError):
                misses += 1
                if misses * CAPTION_POLL_S > 15:
                    print("VLC's remote stopped answering: the show ends.")
                    break
                time.sleep(CAPTION_POLL_S)
                continue
            due, index = next_cues(cues, index, st["time"], last)
            last = st["time"]
            if due:
                code, r = beach_call(cfg, "POST", "/drivein/lines", {"lines": due}, token)
                if code == 409:
                    print("The show was ended on the Beach: stopping.")
                    return 0
                if code != 200:
                    print(f"The Beach refused the lines: {r.get('message') or code}")
                else:
                    for ln in due:
                        print("  >", ln)
            if index >= len(cues) and st["state"] != "playing":
                print("The captions are done: the show ends.")
                break
            time.sleep(CAPTION_POLL_S)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        ctypes.windll.kernel32.SetConsoleTitleW("Drive-In projector")
    code, r = beach_call(cfg, "POST", "/drivein/show/end", None, token)
    print("The show has ended. Thanks for projecting!" if code in (200, 409) else
          f"(the Beach said: {r.get('message') or code})")
    return 0


def vlc_setup(cfg: dict) -> int:
    """Make VLC's web-remote password for the captions: long and random (Pharos, 11-03: VLC's remote has no lockout,
    so a memorable password can be guessed by any program on this computer), saved encrypted for this Windows user,
    and shown once to paste into VLC."""
    import secrets
    pw = secrets.token_urlsafe(24)
    with open(vlc_secret_file(cfg), "wb") as f:
        f.write(_dpapi(pw.encode(), protect=True))
    print("A new password for VLC's web remote is saved (encrypted) for the projector. Paste it into VLC once:")
    print("  VLC: Tools > Preferences > Show settings: All > Interface > Main interfaces > Lua > Password")
    print(f"\n    {pw}\n")
    print("Then save and close VLC. Don't open VLC's web page in a browser: only the projector should talk to it.")
    return 0


def run(cfg: dict, title: str | None) -> int:
    """The keeper's routine (11-01): open the show paused, start this, type the title, pick the app, press Play.
    The helper starts by itself; the show opens on the Beach by itself; closing this window ends it."""
    token = read_token(cfg)
    deny = cfg["_deny"]
    helper = start_helper(cfg)
    try:
        title = title or input("Title of the show: ").strip()
        if not title:
            print("No title, no show.")
            return 1
        choice = pick(open_programs(), deny)
        if not choice:
            return 1
        if choice.get("tab"):
            try:
                cap = TabCapture(int(cfg.get("tab_port", TAB_PORT)))
            except OSError as e:
                print(f"Couldn't open the tab page ({e}). Is another projector running?")
                return 1
            os.startfile(cap.url)              # the default browser opens the projector's own page
            print("\nYour browser opened the projector's page. Click 'Share a tab' there and pick your show's tab.")
            st, r = beach_call(cfg, "POST", "/drivein/show", {"title": title}, token)
            if st not in (200, 409):
                cap.close()
                print(f"The Beach refused: {r.get('message') or r.get('detail') or st}")
                return 1
            try:
                return _on_air(cfg, token, deny, choice, cap)
            finally:
                cap.close()
        if denied_in_tree(choice["pid"], deny):   # it started something while you were choosing
            print("That app now runs something that is never captured. No show started.")
            return 1
        captions = caption_source(cfg) if choice["name"].lower() == "vlc.exe" else None
        if captions:
            st, r = beach_call(cfg, "POST", "/drivein/show", {"title": title}, token)
            if st not in (200, 409):
                print(f"The Beach refused: {r.get('message') or r.get('detail') or st}")
                return 1
            return _captions_on_air(cfg, token, choice, *captions)
        cap = ProcessCapture(choice["pid"], choice["name"], choice["created"])
        st, r = beach_call(cfg, "POST", "/drivein/show", {"title": title}, token)
        if st == 409:
            print("(A show was already open on the Beach: its screen gets these words.)")
        elif st != 200:
            cap.close()
            print(f"The Beach refused: {r.get('message') or r.get('detail') or st}")
            return 1
        return _on_air(cfg, token, deny, choice, cap)
    finally:
        if helper is not None:
            helper.terminate()


def _end_on_close(cfg: dict, token: str) -> None:
    """Closing the projector's window ends the show on the Beach (Windows gives a few seconds to do it)."""
    handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    def on_event(event):
        if event in (2, 5, 6):          # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT
            try:
                beach_call(cfg, "POST", "/drivein/show/end", None, token)
            except OSError:
                pass
        return False

    _end_on_close.keep = handler_type(on_event)    # keep a reference, or Windows calls freed memory
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_end_on_close.keep, True)


SENTENCE_END = (".", "!", "?", "…", '"', "'", ")", "”", "’")
HOLD_S = 8          # an unfinished line waits at most this long for the rest of its sentence


def join_unfinished(held: str | None, lines: list[str]) -> tuple[list[str], str | None]:
    """Speech is cut at pauses, so a sentence can arrive in two pieces ("she found" / "herself in a ..."; the keeper,
    11-02). A last line without an ending is held back and joined to the start of the next piece, once: a line that
    was already joined goes out as it is. Returns (lines to send now, the line now held, if any)."""
    lines = list(lines)
    joined = False
    if held:
        if lines:
            lines[0] = f"{held} {lines[0]}"
            joined = len(lines) == 1            # only the first line was joined; a later one may still wait
        else:
            lines = [held]
    if lines and not joined and not lines[-1].rstrip().endswith(SENTENCE_END):
        return lines[:-1], lines[-1]
    return lines, None


def _on_air(cfg: dict, token: str, deny: set[str], choice: dict, cap: "ProcessCapture") -> int:
    _end_on_close(cfg, token)
    ctypes.windll.kernel32.SetConsoleTitleW("ON AIR - Drive-In projector")
    print(f"\n*** ON AIR: listening to {choice['name']} only. Press Play whenever you're ready. ***")
    print("    Close this window (or Ctrl+C) to end the show.\n")
    if choice.get("tab"):
        print("    (Waiting for you to share the tab in the browser page.)")
    buf, last_speech, tree_at = b"", time.monotonic(), time.monotonic()
    held, held_at, beach_ended = None, 0.0, False

    def send(lines: list[str]) -> bool:
        """Put lines on the screen; False when the show has been ended on the Beach."""
        if not lines:
            return True
        st, r = beach_call(cfg, "POST", "/drivein/lines", {"lines": lines}, token)
        if st == 409:
            print("The show was ended on the Beach: stopping.")
            return False
        if st != 200:
            print(f"The Beach refused the lines: {r.get('message') or st}")
        else:
            for ln in lines:
                print("  >", ln)
        return True

    try:
        while True:
            if not cap.alive():
                print("Tab sharing stopped: the show ends." if choice.get("tab") else
                      "The program closed: capture stopped. Run again to pick a program.")
                break
            if not choice.get("tab") and time.monotonic() - tree_at >= TREE_CHECK_S:
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
                    try:
                        lines = transcribe(cfg, piece)
                    except (OSError, RuntimeError) as e:
                        print(f"The speech helper stopped answering ({e}): capture stopped.")
                        if HELPER is not None and HELPER.poll() is not None:
                            print("Its last words:\n  " + "\n  ".join(list(HELPER.last_words)[-5:]))
                        break
                    if lines:
                        last_speech = time.monotonic()
                        out, held = join_unfinished(held, lines)
                        held_at = time.monotonic()
                        if not send(out):
                            held, beach_ended = None, True
                            break
            if held and time.monotonic() - held_at > HOLD_S:    # the sentence never went on: show what there is
                out, held = [held], None
                if not send(out):
                    beach_ended = True
                    break
            if time.monotonic() - last_speech > IDLE_STOP_S:
                print(f"No speech for {IDLE_STOP_S // 60} minutes: capture stopped.")
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        cap.close()
        ctypes.windll.kernel32.SetConsoleTitleW("Drive-In projector")
    # The last words still held (up to a piece's length) go out before the show ends; found in rehearsal (11-01): a
    # show stopped mid-piece lost its final line.
    buf += cap.take()
    last: list[str] = []
    if buf and not beach_ended and rms(buf) >= QUIET_RMS / 3:
        try:
            last = transcribe(cfg, buf[: 29 * RATE * 2])
        except (OSError, RuntimeError):
            pass
    if held or last:                       # nothing waits any more: a held line and the last words go out together
        out, rest = join_unfinished(held, last)
        send(out + ([rest] if rest else []))
    st, r = beach_call(cfg, "POST", "/drivein/show/end", None, token)
    print("The show has ended. Thanks for projecting!" if st in (200, 409) else
          f"(the Beach said: {r.get('message') or st})")
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
    for name in ("claim", "run", "list", "vlc"):
        s = sub.add_parser(name)
        s.add_argument("--config", required=True, help="projector.json: {\"beach\": \"http://<the Beach>\"}")
        if name == "run":
            s.add_argument("--title", help="open the show with this title (or start it on the Drive-In page)")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.cmd == "claim":
        return claim(cfg)
    if a.cmd == "vlc":
        return vlc_setup(cfg)
    if a.cmd == "list":
        for p in sounding_programs():
            flag = "  (never offered)" if p["name"].lower() in cfg["_deny"] or denied_in_tree(p["pid"], cfg["_deny"]) else ""
            print(f"{p['name']} (process {p['pid']}): {' | '.join(p['titles']) or 'no window title'}{flag}")
        return 0
    return run(cfg, a.title)


if __name__ == "__main__":
    sys.exit(main())
