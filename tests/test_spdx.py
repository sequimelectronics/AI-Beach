# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Every source file we wrote says its license (SPDX) and copyright at the top.

Ours: `SPDX-License-Identifier: AGPL-3.0-only` and the copyright line, in the file's own comment
style. Derived from Clawblox: `SPDX-License-Identifier: MIT`, above its kept MIT notice. The art
SVGs: `SPDX-License-Identifier: CC-BY-SA-4.0`. Vendored libraries keep their own files untouched.
See docs/LICENSES.md.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (".py", ".js", ".cjs", ".mjs", ".ts", ".lua", ".css", ".html", ".sh")
SKIP_DIRS = {".git", "__pycache__", "node_modules", "dist", ".clawblox", "_local"}
VENDOR = "worlds/beach/static/vendor/"
HEAD_LINES = 4   # the lines must be among the first few (after a shebang or <!doctype html>)

AGPL = "SPDX-License-Identifier: AGPL-3.0-only"
COPYRIGHT = "Copyright (C) 2026 Becky Northaven and the AI-Beach contributors"
MIT = "SPDX-License-Identifier: MIT"
ART = "SPDX-License-Identifier: CC-BY-SA-4.0"

# Derived from Clawblox (see worlds/beach/NOTICE.md, worlds/clawblox/NOTICE.md): they keep MIT.
MIT_FILES = {"worlds/beach/renderer/src/index.js", "worlds/clawblox/renderer/src/index.js"}
ART_FILES = {"beach/web/icon.svg", "beach/web/map-art.svg", "beach/web/map-art-portrait.svg"}


def repo_files() -> list[str]:
    """The repository's files (tracked, plus new ones not ignored), as forward-slash paths."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             check=True, timeout=60)
        return [p for p in out.stdout.decode("utf-8").splitlines() if (ROOT / p).is_file()]
    except (OSError, subprocess.SubprocessError):
        found = []
        for d, dirs, files in os.walk(ROOT):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            found += [Path(d, f).relative_to(ROOT).as_posix() for f in files]
        return found


def head(path: str) -> list[str]:
    with open(ROOT / path, encoding="utf-8") as f:
        return [f.readline() for _ in range(HEAD_LINES)]


def our_sources() -> list[str]:
    return sorted(p for p in repo_files() if p.endswith(SOURCE) and not p.startswith(VENDOR))


class SpdxHeaderTest(unittest.TestCase):
    def test_there_are_sources_to_check(self):
        self.assertGreater(len(our_sources()), 50)

    def test_every_source_file_has_its_spdx_line(self):
        missing = []
        for p in our_sources():
            top = "".join(head(p))
            if p in MIT_FILES:
                if MIT not in top:
                    missing.append(f"{p}: needs '{MIT}' (derived from Clawblox)")
            elif AGPL not in top or COPYRIGHT not in top:
                missing.append(f"{p}: needs '{AGPL}' and '{COPYRIGHT}'")
        self.assertEqual(missing, [], "add the two header lines (see CONTRIBUTING.md)")

    def test_mit_files_keep_their_notice(self):
        # Each names Clawblox's MIT copyright and points to its license text, kept next to it.
        for p in MIT_FILES:
            top = "".join(head(p))
            self.assertTrue(AGPL not in top and "Copyright (c) 2026 nacloos" in top and "LICENSE.clawblox" in top, p)
            license_text = (ROOT / p).parents[1] / "LICENSE.clawblox"
            self.assertIn("Permission is hereby granted, free of charge", license_text.read_text(encoding="utf-8"), p)

    def test_art_svgs_are_marked(self):
        for p in ART_FILES:
            self.assertIn(ART, "".join(head(p)), p)

    def test_vendored_files_are_left_alone(self):
        vendored = [p for p in repo_files() if p.startswith(VENDOR) and p.endswith(SOURCE)]
        for p in vendored:
            self.assertNotIn(AGPL, "".join(head(p)), p)

    def test_patches_keep_mit_attribution(self):
        patches = sorted((ROOT / "patches").glob("clawblox-*.patch"))
        self.assertEqual(len(patches), 12)
        for p in patches:
            top = "".join(p.read_text(encoding="utf-8").splitlines(keepends=True)[:8])
            self.assertIn("MIT", top, p.name)
            self.assertIn("Applies to: Clawblox", top, p.name)

    def test_no_npx_patch_removes_the_download(self):
        # Pharos, 10-21: the engine's `npx --yes esbuild` fallback ran an unpinned download at every world start.
        diff = (ROOT / "patches" / "clawblox-no-npx-esbuild.patch").read_text(encoding="utf-8")
        removed = [ln for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---")]
        added = [ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
        self.assertTrue(any('Command::new("npx")' in ln for ln in removed))
        self.assertFalse(any("Command::new(\"npx\")" in ln or "--yes" in ln and "args" in ln for ln in added))
        self.assertTrue(any("CLAWBLOX_ESBUILD" in ln for ln in added))

    def test_spectate_ws_cap_patch_caps_messages_and_frames(self):
        # Pharos, 10-24: before a viewer is reachable from outside, one connection mustn't be able to make the
        # world buffer a 64 MiB message.
        diff = (ROOT / "patches" / "clawblox-spectate-ws-cap.patch").read_text(encoding="utf-8")
        added = "\n".join(ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
        self.assertIn(".max_message_size(SPECTATE_WS_MAX_BYTES)", added)
        self.assertIn(".max_frame_size(SPECTATE_WS_MAX_BYTES)", added)
        self.assertIn("SPECTATE_WS_MAX_BYTES: usize = 64 * 1024", added)
        # Becky, 10-24: at most 20 watchers a world; 0 or unset still means 20, never unlimited.
        self.assertIn("DEFAULT_MAX_SPECTATORS: usize = 20", added)
        self.assertIn("CLAWBLOX_MAX_SPECTATORS", added)
        self.assertIn(".filter(|n| *n > 0)", added)
        self.assertIn("impl Drop for SpectatorSlot", added)


class ChatActivityPatchTest(unittest.TestCase):
    """The engine side of "chatting counts as being active": the patch makes local_chat record
    activity for the idle limit, and leaves the limit alone. The live proof is
    LiveChatIdleTest in test_clawblox_integration.py."""

    def test_chat_records_activity(self):
        text = (ROOT / "patches" / "clawblox-chat-activity.patch").read_text(encoding="utf-8")
        cli = text[text.index("diff --git a/src/bin/cli.rs"):text.index("diff --git a/src/game/manager/players.rs")]
        self.assertIn("async fn local_chat(", cli)
        self.assertIn("+    let _ = game::record_activity(&state.game_handle, state.game_id, agent_id);", cli)
        self.assertIn("+    instance.record_player_activity(agent_id);", text)
        self.assertNotIn("afk_timeout", "".join(ln for ln in text.splitlines(keepends=True) if ln.startswith(("+", "-"))))


if __name__ == "__main__":
    unittest.main()
