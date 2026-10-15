"""Token counting for the sizes turn_bundle() reports.

Exact with the optional `tokenizers` package and a tokenizer.json (set
AI_BEACH_TOKENIZER or pass a path); otherwise chars/4, labeled approximate.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Callable


@dataclass
class TokenCounter:
    method: str
    count: Callable[[str], int]

    def __call__(self, text: str) -> int:
        return self.count(text) if text else 0


def make_counter(tokenizer_json: str | None = None, name: str | None = None) -> TokenCounter:
    path = tokenizer_json or os.environ.get("AI_BEACH_TOKENIZER")
    if path:
        try:
            from tokenizers import Tokenizer
        except ImportError:
            path = None
        else:
            tok = Tokenizer.from_file(path)
            return TokenCounter(f"tokenizer:{name or os.path.basename(path)}",
                                lambda t: len(tok.encode(t, add_special_tokens=False).ids))
    return TokenCounter("approx chars/4", lambda t: math.ceil(len(t) / 4))
