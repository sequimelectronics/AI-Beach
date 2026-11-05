# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Drive-In's listener (drivein/hearing.py, hearing_ced.py): sound lines, voice changes, and its privacy shape."""

from __future__ import annotations

import importlib.util
import io
import json
import struct
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drivein"))

import hearing  # noqa: E402
from test_drivein_projector import code_of  # noqa: E402

SECOND = hearing.RATE * 2           # bytes of 16-bit mono sound per second


class FakeModel:
    def __init__(self, answers):
        self.answers, self.asked = list(answers), []

    def ask(self, clips, question):
        self.asked.append(([len(c) for c in clips], question))
        return self.answers.pop(0)


class FakeEvents:
    def __init__(self, scores):
        self.list = list(scores)

    def scores(self, pcm):
        return self.list.pop(0)

    def close(self):
        pass


class ListenerTests(unittest.TestCase):
    def test_wav_is_a_real_wav(self):
        pcm = b"\x01\x00" * hearing.RATE
        w = wave.open(io.BytesIO(hearing.wav(pcm)))
        self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()),
                         (1, 2, hearing.RATE, hearing.RATE))

    def test_reading_the_answers(self):
        self.assertIs(hearing.parse_change("CHANGE: yes"), True)
        self.assertIs(hearing.parse_change("Yes"), True)          # the model often drops the label
        self.assertIs(hearing.parse_change("no."), False)
        self.assertIsNone(hearing.parse_change("Hard to say."))
        self.assertEqual(hearing.parse_sounds("SOUNDS: laughter and applause"), {"laughter", "applause"})
        self.assertEqual(hearing.parse_sounds("SOUNDS: none"), set())
        self.assertEqual(hearing.parse_sounds("Music, then singing."), {"music", "singing"})

    def test_a_sound_gets_one_line_when_it_starts(self):
        loud = {"music": 0.7, "laughter": 0.0, "applause": 0.0}
        ev = FakeEvents([loud, loud, {**loud, "laughter": 0.4}, {"applause": 0.6, "cheering": 0.5}, {}])
        L = hearing.Listener(events=ev, say=lambda m: None)
        piece = b"\x00\x00" * hearing.RATE
        self.assertEqual(L.sounds(piece), ["(sound) music"])
        self.assertEqual(L.sounds(piece), [])                                  # the song goes on: nothing new
        self.assertEqual(L.sounds(piece), ["(sound) laughter"])                # laughter over the music
        self.assertEqual(L.sounds(piece), ["(sound) applause and cheering"])
        self.assertEqual(L.sounds(piece), [])

    def test_laughter_counts_at_a_low_score(self):
        # The keeper's ear (11-04): laughter was there but scored low; its near neighbors rank high.
        L = hearing.Listener(events=FakeEvents([{"laughter": 0.15}]), say=lambda m: None)
        self.assertEqual(L.sounds(b"\x00\x00"), ["(sound) laughter"])

    def test_voices_are_off_unless_asked_for(self):
        m = FakeModel(["SOUNDS: none"])
        L = hearing.Listener(model=m, say=lambda m: None)
        self.assertFalse(L.new_voice(b"\x00\x00" * hearing.RATE * 10))
        self.assertEqual(m.asked, [])                                           # not even asked
        self.assertIsNone(L.last_speech)                                        # and no sound kept

    def test_a_voice_change_is_heard_where_two_pieces_meet(self):
        m = FakeModel(["CHANGE: no", "Yes"])
        L = hearing.Listener(model=m, voices=True, say=lambda m: None)
        piece = b"\x00\x00" * hearing.RATE * 10                                # 10 seconds
        self.assertFalse(L.new_voice(piece))                                    # the first piece: nothing to compare
        self.assertEqual(m.asked, [])
        self.assertEqual(len(L.last_speech), hearing.JOIN_S * SECOND)            # only the last 4 seconds are kept
        self.assertFalse(L.new_voice(piece))
        self.assertTrue(L.new_voice(piece))
        self.assertEqual(m.asked[-1][0], [2 * hearing.JOIN_S * SECOND])          # ONE clip: 4 s before + 4 s after
        L.close()
        self.assertIsNone(L.last_speech)                                        # dropped when the show ends

    def test_one_model_hears_sounds_too_and_trouble_is_quiet(self):
        m = FakeModel(["SOUNDS: applause"])
        said = []
        L = hearing.Listener(model=m, say=said.append)
        self.assertEqual(L.sounds(b"\x00\x00"), ["(sound) applause"])

        class Broken:
            def ask(self, clips, question):
                raise OSError("no server")
        L = hearing.Listener(model=Broken(), voices=True, say=said.append)
        L.last_speech = b"\x00\x00"
        for _ in range(6):
            self.assertFalse(L.new_voice(b"\x00\x00"))
            self.assertEqual(L.sounds(b"\x00\x00"), [])
        self.assertEqual(len(said), 2)                                          # said once, and again at 5

    def test_settings_that_cannot_work_say_why(self):
        with self.assertRaises(RuntimeError):
            hearing.make_listener({"llm": "vision"}, None)                      # no picture server to share
        with self.assertRaises(RuntimeError):
            hearing.make_listener({}, None)                                     # nothing to listen with
        with self.assertRaises(RuntimeError):
            hearing.make_listener({"events": {"python": "python", "model": "m.onnx", "labels": "c.json"}}, None)

        class Pics:
            api_key = "k"

            class u:
                port = 8805
        L = hearing.make_listener({"llm": "vision", "voices": True}, Pics())
        self.assertEqual((L.model.port, L.model.api_key, L.voices), (8805, "k", True))


class PrivacyShapeTests(unittest.TestCase):
    def test_the_listener_never_saves_or_records(self):
        # Pharos (11-04): the show's own sound only, in memory, never saved. Neither file opens a sound device or
        # writes a file (the helper only READS its model and labels).
        for name in ("hearing.py", "hearing_ced.py"):
            code = code_of(ROOT / "drivein" / name)
            for bad in ("sounddevice", "pyaudio", "soundcard", "wasapi", "microphone", '"w"', "'w'", '"wb"', "'wb'",
                        '"a"', "'a'", "shell=True", "os.system"):
                self.assertNotIn(bad, code, (name, bad))
        ced = code_of(ROOT / "drivein" / "hearing_ced.py")
        # (code_of reads the code back through ast.unparse, which writes single quotes)
        self.assertIn("providers=['CPUExecutionProvider']", ced)               # processor only, no custom operators
        self.assertNotIn("register_custom_ops", ced)
        self.assertIn("b'location'", ced)                                       # external-data models refused


@unittest.skipUnless(importlib.util.find_spec("onnxruntime") and importlib.util.find_spec("numpy"),
                     "needs onnxruntime (the sound helper's own Python has it)")
class HelperTests(unittest.TestCase):
    def test_a_model_pointing_at_another_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            model = Path(d) / "model.onnx"
            model.write_bytes(b"\x08\x07 ... location ... weights.data")
            labels = Path(d) / "config.json"
            labels.write_text(json.dumps({"id2label": {"0": "Music"}}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                hearing.EventModel(sys.executable, str(model), str(labels))


class WorkerTests(unittest.TestCase):
    def test_the_sound_worker_keeps_up_and_stops(self):
        import projector

        class Ears:
            def __init__(self):
                self.seen = []

            def sounds(self, piece):
                self.seen.append(piece)
                time.sleep(0.05)
                return [f"(sound) {piece.decode()}"]

        ears, sent = Ears(), []
        q = projector.start_sound_worker(ears, sent.extend, maxsize=2)
        for i in range(10):                                                     # faster than it can hear
            q.put(str(i).encode())
        q.put(None)
        for _ in range(100):
            time.sleep(0.02)
            if sent and sent[-1] == "(sound) 9":
                break
        self.assertEqual(sent[-1], "(sound) 9")                                # the newest always gets heard
        self.assertLess(len(sent), 10)                                          # the oldest were let go


if __name__ == "__main__":
    unittest.main()
