# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Thin, deterministic adapter between a small language model and a Clawblox world.

    from adapters.clawblox import ClawbloxAdapter, turn_bundle
    a = ClawbloxAdapter("http://127.0.0.1:8080", name="Sandy")
    bundle = turn_bundle(a)          # {"tools", "state", "recent"} with token sizes
    a.act("MoveTo", {"position": [15, 0, -1]})

See README.md in this folder for the hand-off contract.
"""

from .adapter import ACTION_DEFINITIONS, ACTIONS, ClawbloxAdapter, turn_bundle
from .tokens import TokenCounter, approx_counter, make_counter
from .world import MESA_RULES, Rules

__all__ = [
    "ACTIONS", "ACTION_DEFINITIONS", "ClawbloxAdapter", "MESA_RULES", "Rules",
    "TokenCounter", "approx_counter", "make_counter", "turn_bundle",
]
