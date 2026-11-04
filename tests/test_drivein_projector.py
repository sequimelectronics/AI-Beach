# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Drive-In's projector and speech-to-text helper (11-01): what can be checked without a sound card or a model.
The capture itself was tested live on Windows (one speaking program captured, transcribed, posted, read back)."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drivein"))


def code_of(path: Path) -> str:
    """The code alone, without comments or docstrings (they may NAME what the code must never do)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(body, list) and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)):
            body[0] = ast.Pass()
    return ast.unparse(tree)


PROJ = ROOT / "drivein" / "projector.py"
SVC = ROOT / "drivein" / "whisper_service.py"

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


class ProjectorTests(unittest.TestCase):
    def test_it_can_only_ever_capture_one_program(self):
        # Pharos (11-01): no whole-computer or microphone path at all, so there is nothing to fall back to.
        src, code = PROJ.read_text(encoding="utf-8"), code_of(PROJ)
        self.assertIn('"VAD\\\\Process_Loopback"', src)
        self.assertIn("Params(1, pid, 0)", src)                       # process loopback, include the target's tree
        for forbidden in ("GetDefaultAudioEndpoint", "eCapture", "WaveIn", "sounddevice", "soundcard", "pyaudio",
                          "IMMEndpoint", "Stereo Mix", "os.system"):
            self.assertNotIn(forbidden, code, forbidden)

    def test_calls_and_chat_programs_are_never_offered(self):
        import projector
        for name in ("Discord.exe", "Teams.exe", "ms-teams.exe", "Zoom.exe", "slack.exe", "claude.exe"):
            self.assertIn(name.lower(), projector.DENY)

    def test_tree_parents_and_webview_windows_are_never_captured(self):
        # Pharos (11-01): a voice assistant's window may be WebView2; and capturing a parent captures its whole tree.
        import projector
        for name in ("msedgewebview2.exe", "explorer.exe", "svchost.exe", "audiodg.exe", "cmd.exe", "powershell.exe",
                     "pwsh.exe", "windowsterminal.exe", "conhost.exe", "sihost.exe", "runtimebroker.exe"):
            self.assertIn(name, projector.DENY)

    def test_a_denied_program_anywhere_in_the_tree_refuses_the_pick(self):
        import os
        import projector
        me = os.path.basename(sys.executable).lower()            # this test runs in python(.exe)
        self.assertIn(me, [n.lower() for n in projector.denied_in_tree(os.getpid(), {me})])
        self.assertEqual(projector.denied_in_tree(os.getpid(), {"nothing-like-this.exe"}), [])
        self.assertEqual(projector.denied_in_tree(999_999_999, {me}), [])          # gone: nothing to say
        import builtins
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        out = io.StringIO()
        with mock.patch.object(builtins, "input", return_value="1"), redirect_stdout(out):
            picked = projector.pick([{"pid": os.getpid(), "name": "harmless.exe", "created": 0, "titles": []}], {me})
        self.assertIsNone(picked)                                                # never offered: "1" picks nothing
        self.assertIn("not offered: harmless.exe, because it's running", out.getvalue())   # and the list says why
        self.assertIn("0. A browser tab", out.getvalue())                        # a tab is always possible

    def test_picking_the_app_is_the_only_question(self):
        # The keeper, 11-01: "don't ask them to capture the audio, we already picked it". One question, a number.
        import builtins
        from unittest import mock
        import projector
        apps = [{"pid": 999_999_991, "name": "vlc.exe", "created": 0, "titles": ["zombies.mp4"], "playing": False},
                {"pid": 999_999_992, "name": "Discord.exe", "created": 0, "titles": ["a call"], "playing": True}]
        with mock.patch.object(builtins, "input", return_value="1") as asked:
            picked = projector.pick(apps, projector.DENY)
        self.assertEqual(asked.call_count, 1)
        self.assertEqual(picked["name"], "vlc.exe")                     # Discord never listed, so VLC is number 1
        self.assertNotIn("yes/no", PROJ.read_text(encoding="utf-8"))

    def test_the_helpers_messages_are_always_read_and_kept_in_memory_only(self):
        # Pharos (11-01): a stderr pipe nobody reads fills after a few warnings and freezes the helper mid-show.
        src = PROJ.read_text(encoding="utf-8")
        self.assertIn("iter(proc.stderr.readline", src)
        self.assertIn("deque(maxlen=20)", src)
        start = src.index("def start_helper")
        import re
        body = src[start:src.index(chr(10) + "def ", start + 1)]
        self.assertIsNone(re.search(r"(?<![A-Za-z])open\(", body))           # nothing written to a file (Popen is fine)

    def test_local_names_join_the_deny_list_from_the_config(self):
        import json
        import tempfile
        import projector
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "projector.json")
            p.write_text(json.dumps({"beach": "http://192.168.1.20:8765", "deny_also": ["Our-Voice-App.exe", " "]}))
            deny = projector.load_config(str(p))["_deny"]
            self.assertIn("our-voice-app.exe", deny)
            self.assertTrue(projector.DENY <= deny)

    def test_a_sentence_split_at_a_pause_is_joined_once(self):
        # The keeper's second show (11-02): "she found" / "herself in a most peculiar predicament."
        from projector import join_unfinished
        self.assertEqual(join_unfinished(None, ["Once upon a time.", "But she found"]),
                         (["Once upon a time."], "But she found"))
        self.assertEqual(join_unfinished("But she found", ["herself in a predicament."]),
                         (["But she found herself in a predicament."], None))
        # joined once: still unfinished, it goes out anyway rather than waiting forever
        self.assertEqual(join_unfinished("We have", ["just the"]), (["We have just the"], None))
        # a later line in the same piece may still wait
        self.assertEqual(join_unfinished("Hello", ["there.", "And then"]), (["Hello there."], "And then"))
        self.assertEqual(join_unfinished("Alone", []), ([], "Alone"))            # nothing new: keeps waiting
        self.assertEqual(join_unfinished(None, ['She said "yes."']), (['She said "yes."'], None))

    def test_a_caption_file_is_read_as_plain_cues(self):
        # The keeper makes an .srt for every commercial (11-02).
        from projector import parse_srt
        srt = ("1\r\n00:00:01,000 --> 00:00:03,500\r\nOnce upon a time,\r\n<i>a fairy</i> visited Whatsit Bay.\r\n\r\n"
               "2\n00:00:04.250 --> 00:00:06,000 X1:0\n{\\an8}Her wand lost its glow.\n\n"
               "not a cue at all\n\n3\n00:00:07,000 --> garbage\nskipped\n\n"
               "4\n00:01:02,5 --> 00:01:03,000\nThe end.\n")
        cues = parse_srt(chr(0xFEFF) + srt)
        self.assertEqual([c["text"] for c in cues],
                         ["Once upon a time, a fairy visited Whatsit Bay.", "Her wand lost its glow.", "The end."])
        self.assertEqual(cues[0]["start"], 1.0)
        self.assertEqual(cues[1]["start"], 4.25)
        self.assertEqual(cues[2]["start"], 62.5)

    def test_captions_from_an_editors_one_hour_timeline_start_at_zero(self):
        # The keeper's first captioned show (11-03): Resolve's timeline starts at 01:00:00, so the 2:35 commercial's
        # first caption was at 1:00:00.9 and nothing ever reached the screen.
        from projector import from_timeline_start
        cues = [{"start": 3600.92, "end": 3602.79, "text": "Once upon a time,"},
                {"start": 3602.79, "end": 3605.5, "text": "a fairy visited."}]
        shifted, by = from_timeline_start(cues, 155.0)
        self.assertEqual(by, 3600.0)
        self.assertAlmostEqual(shifted[0]["start"], 0.92, places=2)
        self.assertAlmostEqual(shifted[1]["end"], 5.5, places=2)
        self.assertEqual(from_timeline_start(cues, 7200.0), (cues, 0.0))             # a 2-hour film: leave it
        normal = [{"start": 1.0, "end": 2.0, "text": "Hi."}]
        self.assertEqual(from_timeline_start(normal, 155.0), (normal, 0.0))
        late = [{"start": 3900.0, "end": 3901.0, "text": "x"}]
        self.assertEqual(from_timeline_start(late, 100.0), (late, 0.0))             # past the end even shifted

    def test_captions_follow_play_pause_skip_and_rewind(self):
        from projector import next_cues
        cues = [{"start": s, "end": s + 2, "text": f"line {i}"} for i, s in enumerate((1, 4, 8, 12, 20))]
        due, i = next_cues(cues, 0, 0.5, None)
        self.assertEqual((due, i), ([], 0))                                   # nothing yet
        due, i = next_cues(cues, i, 4.2, 3.7)
        self.assertEqual(due, ["line 0", "line 1"])                          # caught up in order
        due, i = next_cues(cues, i, 4.2, 4.2)
        self.assertEqual(due, [])                                            # paused: nothing new
        due, i = next_cues(cues, i, 12.5, 4.2)                               # skipped ahead
        self.assertEqual(due, ["line 3"])                                    # the cue playing now, not the skipped one
        due, i = next_cues(cues, i, 1.5, 12.5)                               # rewound to the start
        self.assertEqual(due, ["line 0"])
        due, i = next_cues(cues, i, 4.4, 3.9)                                # playing on after the rewind
        self.assertEqual(due, ["line 1"])
        due, i = next_cues(cues, i, 22.0, 21.6)                              # a long stretch, polled late
        self.assertEqual(due, ["line 4"])                                     # cues long gone aren't sent late
        self.assertEqual(i, len(cues))

    def test_the_projector_only_ever_asks_vlc_never_commands_it(self):
        # Pharos's rule for a remote: read-only. VLC's remote can also open files and play URLs; we never ask it to.
        src = code_of(PROJ)                                    # code only: the docstring may say "command"
        start = src.index("class VlcRemote")
        body = src[start:src.index("def caption_source", start)]
        import re
        self.assertNotIn("command", body)
        self.assertIsNone(re.search(r"""['"]POST['"]""", body))
        self.assertRegex(body, r"""HTTPConnection\(['"]127\.0\.0\.1['"]""")
        self.assertEqual(sorted(set(re.findall(r"""_get\(['"]([^'"]+)['"]\)""", body))),
                         ["/requests/playlist.json", "/requests/status.json"])

    def test_the_vlc_password_is_long_random_and_never_typed(self):
        # Pharos (11-03): VLC's remote has no lockout, so a memorable password could be guessed locally.
        src = PROJ.read_text(encoding="utf-8")
        start = src.index("def vlc_setup")
        body = src[start:src.index("def run(", start)]
        self.assertIn("secrets.token_urlsafe(24)", body)
        self.assertNotIn("input(", body)

    def test_the_tab_page_takes_only_its_own_pages_samples(self):
        # The in-browser projector (11-03): a page on 127.0.0.1 hands one shared tab's sound to the projector.
        import http.client
        from projector import TabCapture
        tab = TabCapture(0)
        try:
            def call(method, path, body=b"", host=None, origin=None, key=None, ctype="application/octet-stream"):
                c = http.client.HTTPConnection("127.0.0.1", tab.port, timeout=5)
                h = {"Host": host or tab.host, "Content-Type": ctype}
                if origin is not False:
                    h["Origin"] = origin or tab.origin
                h["X-Key"] = tab.key if key is None else key
                c.request(method, path, body=body if method == "POST" else None, headers=h)
                r = c.getresponse()
                return r.status, r.getheader("Content-Security-Policy") or "", r.read()
            st, csp, page = call("GET", "/")
            self.assertEqual(st, 200)
            self.assertIn(b"Share a tab", page)
            self.assertIn("default-src 'self'", csp)
            self.assertEqual(call("GET", "/tabpage.js")[0], 200)
            self.assertEqual(call("GET", "/../projector.py")[0], 404)                # only its three files
            self.assertEqual(call("GET", "/", host="evil.example:80")[0], 421)       # no DNS rebinding
            pcm = b"\x01\x00" * 800
            self.assertEqual(call("POST", "/pcm", pcm, origin="http://evil.example")[0], 403)
            self.assertEqual(call("POST", "/pcm", pcm, origin=False)[0], 403)        # no Origin: not its page
            self.assertEqual(call("POST", "/pcm", pcm, key="guess")[0], 403)
            self.assertEqual(call("POST", "/pcm", pcm, ctype="text/plain")[0], 415)
            try:                                    # refused before the body is read: a 413, or the line simply cut
                self.assertEqual(call("POST", "/pcm", b"\x00" * (300 * 1024))[0], 413)
            except ConnectionError:
                pass
            self.assertEqual(call("POST", "/pcm", pcm)[0], 404)                     # nothing before sharing starts
            self.assertTrue(tab.alive())                                             # waiting for the share
            self.assertEqual(call("POST", "/start")[0], 204)
            self.assertEqual(call("POST", "/pcm", pcm)[0], 204)
            self.assertEqual(call("POST", "/pcm", pcm)[0], 204)
            self.assertEqual(tab.take(), pcm * 2)
            self.assertEqual(tab.take(), b"")
            self.assertEqual(call("POST", "/stop")[0], 204)
            self.assertFalse(tab.alive())
            self.assertEqual(call("POST", "/pcm", pcm)[0], 410)                     # ended: the page stops too
        finally:
            tab.close()

    def test_the_tab_page_owns_its_port(self):
        # Pharos (11-03): on Windows, address reuse lets a second socket bind the same port; a squatter must make the
        # projector's page fail loudly, not share the port.
        import socket
        from projector import TabCapture
        squatter = socket.socket()
        squatter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        squatter.bind(("127.0.0.1", 0))
        squatter.listen(1)
        try:
            with self.assertRaises(OSError):
                TabCapture(squatter.getsockname()[1]).close()
        finally:
            squatter.close()
        self.assertIn("surfaceSwitching: 'exclude'", (ROOT / "drivein" / "tabpage.js").read_text(encoding="utf-8"))

    def test_the_word_list_reaches_the_helper_as_plain_words(self):
        import json
        import tempfile
        import projector
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "projector.json")
            p.write_text(json.dumps({"beach": "http://192.168.1.20:8765",
                                     "words": ["Whatsit Town", "Doohicky's <b>Shop</b>", "Ünïcode-ok", "中"]}))
            words = projector.load_config(str(p))["_words"]
            self.assertEqual(words, "Whatsit Town, Doohicky's bShopb, Ünïcode-ok, ")
        self.assertIn('headers["X-Words"] = cfg["_words"]', PROJ.read_text(encoding="utf-8"))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_a_reused_process_number_is_refused(self):
        # Pharos: between the list and "yes" the program can close and its number go to another one.
        import os
        import psutil
        import projector
        me = psutil.Process(os.getpid())
        for name, created in ((me.name(), me.create_time() + 5), ("someone-else.exe", me.create_time())):
            with self.assertRaises(RuntimeError) as e:
                projector.ProcessCapture(os.getpid(), name, created)
            self.assertIn("pick again", str(e.exception))

    def test_the_config_names_one_beach(self):
        import json
        import tempfile
        import projector
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "projector.json")
            for bad in ("ftp://x", "http://", "http://x/path", ""):
                p.write_text(json.dumps({"beach": bad}))
                with self.assertRaises(SystemExit):
                    projector.load_config(str(p))
            p.write_text(json.dumps({"beach": "http://192.168.1.20:8765"}))
            self.assertEqual(projector.load_config(str(p))["_beach"].hostname, "192.168.1.20")

    @unittest.skipUnless(HAVE_NUMPY, "needs numpy")
    def test_sound_is_cut_at_a_pause(self):
        import numpy as np
        import projector
        rate = projector.RATE
        loud = (np.sin(np.arange(rate * 7) / 3) * 8000).astype("<i2")
        quiet = np.zeros(int(rate * 0.6), dtype="<i2")
        cut = projector.cut_point(np.concatenate([loud, quiet, loud]).tobytes())
        self.assertTrue(7 * rate * 2 <= cut <= 7.6 * rate * 2, cut)       # inside the pause
        self.assertIsNone(projector.cut_point(loud[: rate * 3].tobytes()))  # too short yet
        endless = (np.sin(np.arange(rate * 15) / 3) * 8000).astype("<i2").tobytes()
        self.assertEqual(projector.cut_point(endless), projector.CHUNK_MAX_S * rate * 2)   # no pause: cut at the max


class WhisperServiceTests(unittest.TestCase):
    def test_the_models_inventions_over_music_are_dropped(self):
        # The keeper, 11-02: "it likes to insert 'thanks for watching' and 'no' randomly".
        from whisper_service import keep_segment
        speech = dict(no_speech_prob=0.02, avg_logprob=-0.2)
        self.assertTrue(keep_segment("Once upon a time, a fairy visited the town.", **speech))
        self.assertFalse(keep_segment("Thanks for watching!", **speech))           # a phantom, even when "sure"
        self.assertFalse(keep_segment("Please subscribe.", **speech))
        self.assertTrue(keep_segment("Thanks for watching the shop, she said.", **speech))   # inside a sentence: kept
        self.assertTrue(keep_segment("No.", no_speech_prob=0.05, avg_logprob=-0.3))          # a real "No."
        self.assertFalse(keep_segment("No", no_speech_prob=0.25, avg_logprob=-0.6))          # a filler over music
        self.assertFalse(keep_segment("Lovely day", no_speech_prob=0.45, avg_logprob=-0.6))  # short, unsure
        self.assertTrue(keep_segment("A long line of real words here.", no_speech_prob=0.45, avg_logprob=-0.6))
        self.assertFalse(keep_segment("Some words", no_speech_prob=0.7, avg_logprob=-1.2))   # Whisper's own silence rule
        self.assertFalse(keep_segment("  ...  ", **speech))

    def test_the_word_list_header_is_only_ever_words(self):
        from whisper_service import clean_words
        self.assertEqual(clean_words("Whatsit Town, Doohicky's"), "Whatsit Town, Doohicky's")
        newline = chr(10)
        self.assertEqual(clean_words("Ignore" + newline + 'previous <script>"x"</script>; rm -rf /'),
                         "Ignore previous scriptxscript rm -rf")
        self.assertEqual(len(clean_words("a" * 1000)), 240)
        self.assertEqual(clean_words(None), "")

    def test_it_takes_raw_samples_only_and_answers_only_the_beach(self):
        # Pharos: nothing to parse (no container, no decoder); Host and Origin checked; CORS for one origin, never "*".
        src, code = SVC.read_text(encoding="utf-8"), code_of(SVC)
        for forbidden in ("ffmpeg", "decode_audio", "av.open", "wave.open", "'*'"):
            self.assertNotIn(forbidden, code, forbidden)
        for needed in ('Exclusive(("127.0.0.1", a.port)', "allow_reuse_address = False", "SO_EXCLUSIVEADDRUSE",
                       'self.headers.get("Host") != svc.host',
                       "origin is not None and origin != svc.origin", "Access-Control-Allow-Private-Network",
                       'os.environ["HF_HUB_OFFLINE"] = "1"', "local_files_only=True"):
            self.assertIn(needed, src, needed)


if __name__ == "__main__":
    unittest.main()
