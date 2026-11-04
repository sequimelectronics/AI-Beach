# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Pictures of the show for the describer: grab, shrink, and tell whether the picture changed.

- grab_window(pid): the picked program's biggest visible window, through Windows' own PrintWindow (with
  PW_RENDERFULLCONTENT, which also reaches most video and game windows). Memory only: nothing is ever saved to disk.
- to_jpeg(img): the picture shrunk to at most MAX_SIDE pixels on its longest side (vision models look at roughly that
  much anyway; it keeps each request small), as JPEG bytes.
- Thumb / changed(): a 32 x 18 grayscale thumbnail of each picture; a new description only when the picture moved on
  by more than CHANGE (average brightness difference, 0-255), so a talking head gets one line, a magic act many.

Needs Pillow (already used by the Beach's gallery).
"""

from __future__ import annotations

import ctypes
import io
import os
from ctypes import wintypes

MAX_SIDE = 768
THUMB = (32, 18)
CHANGE = 12.0           # mean grayscale difference that counts as "the picture changed" (tuned on the bake-off frames)
PW_RENDERFULLCONTENT = 2


def to_jpeg(img, max_side: int = MAX_SIDE, quality: int = 85) -> bytes:
    img = img.convert("RGB")
    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality)
    return out.getvalue()


def thumb(img) -> bytes:
    return img.convert("L").resize(THUMB).tobytes()


def changed(prev: bytes | None, now: bytes, threshold: float = CHANGE) -> bool:
    if prev is None or len(prev) != len(now):
        return True
    return sum(abs(a - b) for a, b in zip(prev, now)) / len(now) > threshold


def looks_blank(img, floor: float = 6.0) -> bool:
    """A black or nearly uniform picture (a paused-at-black video, a minimized window): nothing to describe."""
    t = thumb(img)
    mean = sum(t) / len(t)
    return sum(abs(v - mean) for v in t) / len(t) < floor


# --------------------------------------------------------------------------------------------- Windows window grab

class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def _windows_of(pids: set[int]) -> list[tuple[int, int]]:
    """(area, hwnd) of each visible, not-minimized top-level window belonging to `pids`, biggest first."""
    user32 = ctypes.windll.user32
    found: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
            if area >= 160 * 120:
                found.append((area, hwnd))
        return True

    user32.EnumWindows(each, 0)
    return sorted(found, reverse=True)


def grab_window(pids: set[int]):
    """The biggest visible window of these processes as a PIL image, or None (minimized, closed, or not drawable)."""
    if os.name != "nt":
        return None
    from PIL import Image
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)        # true pixel sizes on scaled displays
    except (AttributeError, OSError):
        pass
    wins = _windows_of(pids)
    if not wins:
        return None
    hwnd = wins[0][1]
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w < 160 or h < 120:
        return None
    hdc = user32.GetDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        # PW_CLIENTONLY (1) | PW_RENDERFULLCONTENT (2): the inside of the window, including GPU-drawn video.
        if not user32.PrintWindow(hwnd, mem, 1 | PW_RENDERFULLCONTENT):
            return None
        bi = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0):
            return None
        return Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)
