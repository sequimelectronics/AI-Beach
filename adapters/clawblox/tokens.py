# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Token counting for the sizes reported by turn_bundle().

With the optional `tokenizers` package and a tokenizer.json file, counts are
exact for that tokenizer. Without them, counts fall back to chars/4, which is
approximate and, for number-heavy text, an underestimate.
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


def approx_counter() -> TokenCounter:
    return TokenCounter("approx chars/4", lambda t: math.ceil(len(t) / 4))


def make_counter(tokenizer_json: str | None = None, name: str | None = None) -> TokenCounter:
    """Exact counter from a tokenizer.json path (or $CLAWBLOX_TOKENIZER), else approx."""
    path = tokenizer_json or os.environ.get("CLAWBLOX_TOKENIZER")
    if path:
        try:
            from tokenizers import Tokenizer  # optional dependency
        except ImportError:
            return approx_counter()
        tok = Tokenizer.from_file(path)
        name = name or os.path.basename(path)
        return TokenCounter(f"tokenizer:{name}",
                            lambda t: len(tok.encode(t, add_special_tokens=False).ids))
    return approx_counter()
