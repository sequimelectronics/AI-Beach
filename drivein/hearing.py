# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Drive-In's listener (optional): what the show SOUNDS like, beyond its words.

Two kinds of line, both from the same pieces of sound the speech helper turns into words:
  "(new voice)" in front of a piece's first line when the person speaking isn't the one from the piece before (the
      keeper's reviewers, 11-04: "the film's narration and the two hosts arrive as plain lines");
  "(sound) laughter", "(sound) applause", ... when a sound STARTS (a long song gets one line, not one every piece).

Who does the listening (projector.json, "hearing"):
  "llm"     an audio-capable model on a llama-server (LFM3-Omni-2B in our tests): voice changes, and sounds too when there
            is no "events" model. "vision" = the same server the pictures use (one model for everything).
  "events"  a small sound-event model (CED, 87 MB, on the processor) run by hearing_ced.py in its own Python, for
            laughter, applause, cheering, music, singing and crying. In our tests it was the best at applause and music.

Privacy (Pharos, 11-04): only the show's own sound (the same capture the words come from: never the microphone),
kept in memory (the current piece, and the last 4 seconds of the one before), dropped when the show ends, never saved
or sent anywhere but the models on this computer. No voiceprints are made: the model just hears the moment where one
piece meets the next, and nothing about a voice is kept or compared across shows. The lines name nobody.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import struct
import subprocess

RATE = 16000
SOUNDS = ("laughter", "applause", "cheering", "music", "singing", "crying")
TIMEOUT_S = 20

# Plain words, nothing to recite (the keeper's Rule of Doohicky): the six sounds are the categories asked about, not
# examples, and no example answer is given.
#
# Voice changes (11-05, tested on pairs of pieces with a known answer: one person talking vs two different shows):
# handing the model the two pieces as two clips and asking "same person?" was a coin flip (3 of 6 different pairs);
# joining the end of the last piece and the start of this one into ONE clip and asking "does the speaker change during
# it?" got 9 of 12 (5 of 6 changes). Useful, not reliable: off unless "voices": true.
ASK_CHANGE = ("Listen to this clip of sound from a show. Answer in exactly one line:\n"
              "CHANGE: yes or no, does the person speaking change during the clip")
ASK_SOUNDS = ("You hear a clip of sound from a show. Answer in exactly one line:\n"
              "SOUNDS: which of these you hear: laughter, applause, cheering, music, singing, crying (or none)")
JOIN_S = 4                  # seconds from each side of the boundary between two pieces


def wav(pcm: bytes, rate: int = RATE) -> bytes:
    """16-bit mono PCM as a WAV file (what the model's server takes)."""
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(pcm)) + pcm)


def parse_change(answer: str) -> bool | None:
    """The speaker changed? From "CHANGE: yes", or a bare "Yes" (the model often drops the label). None if unclear."""
    m = re.search(r"CHANGE:\s*(yes|no)\b", answer, re.I) or re.match(r"\W*(yes|no)\b", answer, re.I)
    return None if not m else m.group(1).lower() == "yes"


def parse_sounds(answer: str) -> set[str]:
    m = re.search(r"SOUNDS:\s*(.*)", answer, re.I)
    said = (m.group(1) if m else answer).lower()
    return {s for s in SOUNDS if re.search(r"\b" + s + r"\b", said)}


class AudioModel:
    """An audio-capable model behind an OpenAI-style /v1/chat/completions on this computer (llama-server)."""

    def __init__(self, port: int, api_key: str, timeout: float = TIMEOUT_S):
        self.port, self.api_key, self.timeout = int(port), api_key, timeout

    def ask(self, clips: list[bytes], question: str) -> str:
        parts = [{"type": "input_audio", "input_audio": {"data": base64.b64encode(wav(c)).decode(), "format": "wav"}}
                 for c in clips]
        body = {"messages": [{"role": "user", "content": parts + [{"type": "text", "text": question}]}],
                "max_tokens": 40, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        conn.request("POST", "/v1/chat/completions", body=json.dumps(body),
                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key})
        r = conn.getresponse()
        raw = r.read()
        if r.status != 200:
            raise RuntimeError(f"the listening model answered {r.status}")
        return json.loads(raw)["choices"][0]["message"].get("content") or ""


class EventModel:
    """hearing_ced.py in its own Python (the sound-event model needs onnxruntime, which the projector doesn't): started
    once per show by full paths, no shell; a piece in (4-byte length + PCM), one JSON line out."""

    def __init__(self, python: str, model: str, labels: str):
        here = os.path.dirname(os.path.abspath(__file__))
        for label, path in (("python", python), ("model", model), ("labels", labels)):
            if not os.path.isabs(path) or not os.path.isfile(path):
                raise RuntimeError(f'hearing "events" {label} must be the full path of a file that exists ({path!r})')
        flags = 0x08000000 if os.name == "nt" else 0                       # CREATE_NO_WINDOW
        self.proc = subprocess.Popen([python, "-I", os.path.join(here, "hearing_ced.py"), model, labels],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     creationflags=flags)
        if json.loads(self.proc.stdout.readline() or b"{}").get("ready") is not True:
            self.close()
            raise RuntimeError("the sound-event model didn't start")

    MAX_PIECE = 60 * RATE * 2          # the helper takes at most a minute of sound per piece

    def scores(self, pcm: bytes) -> dict:
        if self.proc.poll() is not None:
            raise RuntimeError("the sound-event helper has stopped; sounds are off for the rest of this show")
        pcm = pcm[: self.MAX_PIECE]
        self.proc.stdin.write(struct.pack("<I", len(pcm)) + pcm)
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline() or b"{}")

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(5)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()


# Cutoffs for the event model, from the sound-off against the keeper's ear (11-04): laughter scores low even when it's
# there (its near neighbors "snicker" and "chuckle" count too), music and applause score high.
CUTOFF = {"laughter": 0.10, "applause": 0.30, "cheering": 0.30, "music": 0.50, "singing": 0.30, "crying": 0.30}


class Listener:
    def __init__(self, model: AudioModel | None = None, events: EventModel | None = None, voices: bool = False,
                 say=print):
        self.model, self.events, self.voices, self.say = model, events, voices and model is not None, say
        self.last_speech: bytes | None = None     # the end of the piece before (memory only, this show only)
        self.last_sounds: set[str] = set()
        self.failures = 0

    def _trouble(self, e: Exception) -> None:
        self.failures += 1
        if self.failures in (1, 5):
            self.say(f"(listening: {e})")

    def new_voice(self, piece: bytes) -> bool:
        """For a piece with speech in it: did the person speaking change since the last one? (The projector waits for
        this, short, on the graphics card, so the mark lands on the right line.) Off unless "voices": true."""
        if not self.voices:
            return False
        edge = JOIN_S * RATE * 2
        changed = False
        try:
            if self.last_speech is not None:
                changed = parse_change(self.model.ask([self.last_speech + piece[:edge]], ASK_CHANGE)) is True
            self.failures = 0
        except (OSError, RuntimeError, ValueError, KeyError, IndexError) as e:
            self._trouble(e)
        self.last_speech = piece[-edge:]
        return changed

    def sounds(self, piece: bytes) -> list[str]:
        """A "(sound) ..." line for sounds that just STARTED in this piece (a long song: one line). Runs beside the
        words, never holding them up."""
        try:
            if self.events is not None:
                s = self.events.scores(piece)
                heard = {k for k, cut in CUTOFF.items() if s.get(k, 0) >= cut}
            elif self.model is not None:
                heard = parse_sounds(self.model.ask([piece], ASK_SOUNDS))
            else:
                return []
            self.failures = 0
        except (OSError, RuntimeError, ValueError, KeyError, IndexError) as e:
            self._trouble(e)
            return []
        started = [s for s in SOUNDS if s in heard and s not in self.last_sounds]
        self.last_sounds = heard
        if not started:
            return []
        return ["(sound) " + (started[0] if len(started) == 1 else ", ".join(started[:-1]) + " and " + started[-1])]

    def close(self) -> None:
        self.last_speech = None
        if self.events is not None:
            self.events.close()


def make_listener(hearing: dict, vision_describer=None, say=print) -> Listener:
    """The listener projector.json asks for. "llm": "vision" uses the picture model's own server (one model)."""
    if not isinstance(hearing, dict):
        raise RuntimeError('"hearing" in projector.json is a section like {"llm": "vision", "events": {...}}')
    model = None
    llm = hearing.get("llm")
    if llm == "vision":
        if vision_describer is None or not hasattr(vision_describer, "u"):
            raise RuntimeError('"llm": "vision" needs pictures on with a llama-server or openai describer')
        model = AudioModel(vision_describer.u.port, vision_describer.api_key)
    elif llm:
        raise RuntimeError('hearing "llm" is "vision" (the picture model listens too) or left out')
    events = None
    ev = hearing.get("events")
    if ev:
        events = EventModel(ev.get("python", ""), ev.get("model", ""), ev.get("labels", ""))
    if model is None and events is None:
        raise RuntimeError('"hearing" needs "llm": "vision", an "events" model, or both')
    return Listener(model, events, voices=bool(hearing.get("voices", False)), say=say)
