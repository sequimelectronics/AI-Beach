# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The notification hook: how the Beach tells a host "someone rang the Gather Bell".

The host configures it (setting `notify_hook`); the Beach makes no network call
of its own. Two forms:

    {"command": ["/path/to/notify", "--flag"]}
        Runs the command (no shell) with the notice as JSON on stdin.
        Exit status 0 = delivered.

    {"url": "http://127.0.0.1:8899/beach-bell"}
        POSTs the notice as JSON to a LOCAL address only (127.0.0.0/8, ::1,
        localhost). Any proxy settings in the environment are ignored.

Hook calls run on the Beach's upkeep thread, never inside a request, and a
notice whose bell has closed is dropped instead of delivered late.
"""

from __future__ import annotations

import ipaddress
import json
import subprocess
import urllib.parse
import urllib.request
from typing import Callable

TIMEOUT_S = 10


class HookError(ValueError):
    pass


def _is_local(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_hook(hook) -> None:
    from .core import BeachError
    if not isinstance(hook, dict) or len(hook) != 1:
        raise BeachError("invalid", 'notify_hook is {"command": [...]} or {"url": "http://127.0.0.1:.../..."}')
    if "command" in hook:
        cmd = hook["command"]
        if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
            raise BeachError("invalid", "notify_hook.command must be a non-empty list of strings")
    elif "url" in hook:
        u = urllib.parse.urlparse(str(hook["url"]))
        if u.scheme not in ("http", "https") or not u.hostname or not _is_local(u.hostname):
            raise BeachError("invalid", "notify_hook.url must point at this machine (127.0.0.1, ::1 or localhost)")
    else:
        raise BeachError("invalid", "notify_hook needs 'command' or 'url'")


def send(hook: dict, payload: dict) -> bool:
    body = json.dumps(payload).encode()
    if "command" in hook:
        proc = subprocess.run(hook["command"], input=body, capture_output=True, timeout=TIMEOUT_S, shell=False)
        return proc.returncode == 0
    url = hook["url"]
    host = urllib.parse.urlparse(url).hostname or ""
    if not _is_local(host):  # re-checked at send time, not only when saved
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=TIMEOUT_S) as resp:
        return 200 <= resp.status < 300


def install(beach) -> None:
    """Point the Beach's sender at the configured hook (read fresh on every notice)."""
    def sender(payload: dict) -> bool:
        hook = beach.setting("notify_hook")
        if not hook:
            return False
        return send(hook, payload)

    def has_hook() -> bool:
        return bool(beach.setting("notify_hook"))

    beach.sender = _Sender(sender, has_hook)


class _Sender:
    """Callable that reports 'no hook' as None so queued notices wait instead of failing."""

    def __init__(self, fn: Callable[[dict], bool], has: Callable[[], bool]):
        self.fn = fn
        self.has = has

    def __call__(self, payload: dict) -> bool:
        return self.fn(payload)

    def __bool__(self) -> bool:
        return self.has()
