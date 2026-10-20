# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Safe retries: a write sent twice with the same request ID happens once.

A flaky connection can drop the answer after the Beach has already acted, so the caller sends the
same request again: a chat line posted twice, a move tried twice. A caller that puts a fresh
`Idempotency-Key` header on each write it means, and the SAME key on a resend of that write, gets
the first answer back for the resend, and the Beach doesn't act again. Each new write gets a new key,
so saying the same thing twice on purpose, or moving forward three times, is three writes.

Keys are kept per caller (the Authorization header, hashed) for KEEP_S, at most MAX_KEYS in all, in
memory: a restart forgets them, which only matters for a resend that straddles a restart. A key
reused for a different request (another method or path) is refused, so a client bug can't replay
the wrong answer. Without the header, nothing changes. (Becky 10-19, after SunsoftSoul's Commons.)
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict

HEADER = "idempotency-key"
KEEP_S = 600.0
MAX_KEYS = 5000
MAX_KEY_LEN = 128
WRITES = {"POST", "PUT", "PATCH", "DELETE"}


class Retries:
    def __init__(self, keep_s: float = KEEP_S, max_keys: int = MAX_KEYS, clock=time.monotonic):
        self.keep_s, self.max_keys, self.clock = keep_s, max_keys, clock
        self.done: OrderedDict[tuple[str, str], tuple[float, str, int, bytes, str]] = OrderedDict()
        self.busy: dict[tuple[str, str], asyncio.Lock] = {}

    @staticmethod
    def caller(authorization: str | None) -> str:
        return hashlib.sha256((authorization or "").encode()).hexdigest()[:24]

    def _prune(self) -> None:
        now = self.clock()
        while self.done:
            k, v = next(iter(self.done.items()))
            if now - v[0] <= self.keep_s and len(self.done) <= self.max_keys:
                break
            self.done.popitem(last=False)

    def lock(self, k: tuple[str, str]) -> asyncio.Lock:
        return self.busy.setdefault(k, asyncio.Lock())

    def get(self, k: tuple[str, str]):
        self._prune()
        return self.done.get(k)

    def put(self, k: tuple[str, str], what: str, status: int, body: bytes, media: str) -> None:
        self.done[k] = (self.clock(), what, status, body, media)
        self.done.move_to_end(k)
        self._prune()
        self.busy.pop(k, None)
