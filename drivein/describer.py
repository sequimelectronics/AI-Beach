# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Drive-In's picture describer: one picture in, one plain line out. This file is THE SWAP POINT.

The projector hands this module a picture of the show (JPEG bytes) and gets back a short line like "A man hangs upside
down from a burning rope." That line goes on the Drive-In screen as "(seen) ...". Which model does the looking is up to
the keeper, in projector.json under "vision". Three ways, all ending in the same `describe()`:

  "llama-server"  (the default)  The projector starts llama.cpp's llama-server itself with a vision model + its mmproj
                                 (the bake-off winner, MiniCPM-V 4.7 1B), on this computer only, and stops it after.
  "openai"                       Any OpenAI-compatible chat server that takes images: llama-server you run yourself,
                                 Ollama, LM Studio, vLLM, KoboldCpp, ... Give its address and model name.
  "command"                      Your own program: it gets the JPEG on stdin and prints one line on stdout.

Whatever runs, two things always happen here, so a swapped-in model gets them too:
  - the default prompts carry the keeper's no-names rule ("Don't use anyone's name, even if you recognize them"). In the
    bake-off, small models asked "who is this?" named the wrong famous person with full confidence; with this wording
    none of them used a name;
  - scrub() takes out anything that still looks like a person's name, as a safety net (a model like Florence-2 can't be
    given instructions at all).

See drivein/VISION.md for setup, swapping recipes and tips.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import secrets
import subprocess
import time
import urllib.parse

MAX_LINE = 300                  # characters of one description on the screen
DEFAULT_TIMEOUT_S = 60

# The keeper's rule (11-03): "Don't use anyone's name", not "don't guess": a model that thinks it KNOWS isn't guessing.
NO_NAMES = ("Don't use anyone's name, even if you recognize them; say 'a man', 'a woman', 'a child' or 'the performer'. "
            "Say only what you can see.")
DEFAULT_PROMPTS = {
    "short": "Describe what is happening on screen in ONE short sentence of at most 15 words. " + NO_NAMES,
    "long": "Describe what is happening on screen in two or three plain sentences, at most 50 words: who is there "
            "and what they are doing. " + NO_NAMES,
    # Two pictures (the one last described, and now). Tested 11-03 on 36 frames of a magic act ("version E"): it
    # narrated the action ("swings upward, gripping a rope"; "now it's a massive fireball") where one picture at a time
    # couldn't. NO EXAMPLE PEOPLE in this prompt on purpose: with "the woman in the red dress" as an example, the model
    # described a woman in red eight times in a show that had none (the keeper's rule of placeholders, proven).
    # The keeper (11-03, after the floating table): "talk rarely about lighting and more about the actions of the
    # people or things on the screen", and "if something seems impossible go ahead and describe it, this could be
    # sci-fi or fantasy". Phrased POSITIVELY on purpose: naming lighting ("mention lighting only if...") made every
    # line mention lighting (36 of 36), and a list of impossible things made it recite "nothing appears or
    # disappears". Whatever words the prompt holds, a small model repeats.
    "change": "You see two pictures from a video, a few seconds apart: the FIRST is earlier, the SECOND is now. In one "
              "or two short sentences (at most 25 words): first say what is happening in the SECOND picture, then "
              "what changed since the first. Focus on what people and things are doing. Describe anything unusual "
              "exactly as it looks, even if it seems impossible. If there is more than one person, tell them apart by "
              "what they are wearing or how they look. Never name anyone you recognize; use a name only if the "
              "show's words below just said it. Say only what you can see.",
}


class DescriberError(Exception):
    pass


# --------------------------------------------------------------------------------------------- cleaning the answer

_THOUGHTS = [re.compile(r"<think>.*?</think>", re.S | re.I),            # Qwen/DeepSeek-style reasoning
             re.compile(r"<\|channel>thought.*?<channel\|>", re.S)]       # Gemma 4's thinking channel
_LEADS = re.compile(r"^(?:(?:the|this) (?:(?:second|first) )?(?:image|picture|frame|scene|screen|still) "
                    r"(?:shows|depicts|displays|features)"
                    r"|in (?:the|this) (?:(?:second|first) )?(?:image|picture|frame|scene),?)\s+", re.I)


def tidy(text: str) -> str:
    """One plain line: reasoning and markup dropped, whitespace folded, "The image shows" trimmed, length capped."""
    for pat in _THOUGHTS:
        text = pat.sub(" ", text)
    if "<channel|>" in text:                     # a thinking model's answer comes after its last channel marker
        text = text.rsplit("<channel|>", 1)[-1]
    text = re.sub(r"[*_`#>]+", "", text)
    text = " ".join(text.split()).strip(" \"'")
    m = _LEADS.match(text)
    if m:
        rest = text[m.end():]
        text = rest[:1].upper() + rest[1:]
    if len(text) > MAX_LINE:
        cut = text[:MAX_LINE]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = cut[: end + 1] if end > 40 else cut.rstrip() + "…"
    return text


# Words that start with a capital for reasons other than being a name.
_NOT_NAMES = {
    "a", "an", "the", "this", "that", "these", "those", "one", "two", "three", "four", "five", "several", "some", "many",
    "he", "she", "they", "it", "his", "her", "their", "its", "i", "we", "you", "there", "here", "in", "on", "at", "near",
    "behind", "beside", "above", "below", "under", "over", "with", "while", "as", "and", "but", "or", "no", "nothing",
    "someone", "something", "people", "person", "man", "woman", "child", "performer", "audience", "stage", "both",
    "each", "another", "other", "others", "all", "most", "close", "inside", "outside", "from", "to", "of", "by", "for",
    "after", "before", "during", "then", "now", "suddenly", "meanwhile", "only", "just", "black", "white", "red",
    "blue", "green", "yellow", "dark", "bright", "large", "small", "big", "old", "young", "left", "right",
    "mr", "mrs", "ms", "dr", "danger", "warning", "exit", "stop", "open", "closed", "high", "voltage", "tv", "dvd",
}
# Two or more capitalized words in a row ("Michael Jackson"), or a lowercase run Florence-style models produce isn't
# catchable without a name list; this is a net for the common shape, not a guarantee (VISION.md says so).
_CAP_RUN = re.compile(r"\b([A-Z][a-z'’]+(?:[ -][A-Z][a-z'’]+)+)\b")


def scrub(text: str, allowed: set[str] | frozenset = frozenset()) -> str:
    """Replace what looks like a person's name with "someone". `allowed` = words the show itself supplies (the keeper's
    word list, on-screen text), kept as they are. Sentence-initial ordinary words and signs in capitals are left alone."""
    allowed_low = {a.lower() for a in allowed}

    def swap(m: re.Match) -> str:
        words = re.split(r"[ -]", m.group(1))
        if m.group(1).lower() in allowed_low or all(w.lower() in allowed_low for w in words):
            return m.group(1)
        if all(w.lower().strip("'’") in _NOT_NAMES for w in words):
            return m.group(1)
        if words[0].lower() in _NOT_NAMES:       # "The Magician" / "A Woman": a capitalized lead word, not a name
            return m.group(1)
        return "someone"

    return _CAP_RUN.sub(swap, text)


def names_in(lines) -> set[str]:
    """Name-shaped runs in the show's own words ("Tonight, Firstname Lastname will..."): names the SHOW supplies, which
    scrub() then lets through (the keeper, 11-03: the title card said a name the narration had said aloud, and the net
    turned it into "someone"). Names a model guesses from a face are still caught."""
    found: set[str] = set()
    for line in lines:
        for m in _CAP_RUN.finditer(str(line)):
            words = re.split(r"[ -]", m.group(1))
            if words[0].lower() in _NOT_NAMES:          # "The Magic" -> keep looking inside the run
                words = words[1:]
            if len(words) >= 2 and not all(w.lower() in _NOT_NAMES for w in words):   # a name = 2+ capitalized words
                found.add(" ".join(words))
    return found


CONTEXT_MAX = 800     # characters of "what happened just before" handed to the model with each picture


def with_context(prompt: str, context: str) -> str:
    """The prompt plus the story so far (the keeper, 11-03: "the poor thing would have to have a running narrative to make
    sense of this": each picture alone never showed that the act was two people walking into a giant fan)."""
    context = (context or "").strip()[-CONTEXT_MAX:]
    if not context:
        return prompt
    return (prompt + "\n\nWhat happened just before, for context only (describe what you see in THIS picture; "
            "don't repeat these lines):\n" + context)


# --------------------------------------------------------------------------------------------- the three ways

def _host_is_local(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


class OpenAIDescriber:
    """Any OpenAI-compatible /v1/chat/completions server that accepts image_url content parts."""

    def __init__(self, url: str, model: str = "", api_key: str = "", timeout: float = DEFAULT_TIMEOUT_S,
                 remote_ok: bool = False, prompts: dict | None = None, extra: dict | None = None):
        u = urllib.parse.urlsplit(url.rstrip("/"))
        if u.scheme not in ("http", "https") or not u.hostname:
            raise DescriberError(f"vision url must look like http://127.0.0.1:8805/v1 (got {url!r})")
        if not _host_is_local(u.hostname) and not remote_ok:
            raise DescriberError("the vision server isn't on this computer, so the show's pictures would leave it. "
                                 'If that is really what you want, set "remote_ok": true under "vision" '
                                 "(see VISION.md first).")
        self.u = u
        self.base = u.path if u.path.endswith("/v1") else (u.path + "/v1" if u.path else "/v1")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.prompts = {**DEFAULT_PROMPTS, **(prompts or {})}
        self.extra = extra or {}

    def describe(self, jpeg: bytes, detail: str = "short", context: str = "", previous: bytes | None = None) -> str:
        """`previous` (the picture last described) makes it a two-picture "what changed" look (detail "change")."""
        pictures = ([previous] if previous else []) + [jpeg]
        if not previous and detail == "change":
            detail = "short"
        parts = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(p).decode()}}
                 for p in pictures]
        body = {
            "messages": [{"role": "user", "content": parts + [
                {"type": "text", "text": with_context(self.prompts[detail], context)}]}],
            "max_tokens": 150, "temperature": 0.2,
            # Many servers pass this to the model's chat template: "answer, don't reason first" for thinking models.
            "chat_template_kwargs": {"enable_thinking": False},
            **self.extra,
        }
        if self.model:
            body["model"] = self.model
        conn = (http.client.HTTPSConnection if self.u.scheme == "https" else http.client.HTTPConnection)(
            self.u.hostname, self.u.port, timeout=self.timeout)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        try:
            conn.request("POST", self.base + "/chat/completions", body=json.dumps(body), headers=headers)
            r = conn.getresponse()
            raw = r.read()
        except OSError as e:
            raise DescriberError(f"the vision server didn't answer ({e})") from e
        if r.status != 200:
            raise DescriberError(f"the vision server answered {r.status}: {raw[:200]!r}")
        try:
            msg = json.loads(raw)["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as e:
            raise DescriberError("the vision server's answer wasn't a chat completion") from e
        return tidy(msg.get("content") or "")

    def close(self) -> None:
        pass


class LlamaServerDescriber(OpenAIDescriber):
    """Starts llama.cpp's llama-server for the show and stops it after (the default way).

    Kept to the rules Pharos set for the bake-off: launched by full path (never from PATH), 127.0.0.1 only, its own
    port, a fresh random --api-key every start (llama-server otherwise answers any web page), --no-webui."""

    def __init__(self, server: str, model: str, mmproj: str, port: int = 8805, gpu_layers: int = 99,
                 ctx: int = 4096, timeout: float = DEFAULT_TIMEOUT_S, prompts: dict | None = None,
                 extra_args: list | None = None, log_path: str | None = None):
        for label, path in (("server", server), ("model", model), ("mmproj", mmproj)):
            if not os.path.isabs(path) or not os.path.isfile(path):
                raise DescriberError(f'vision "{label}" must be the full path of a file that exists (got {path!r})')
        key = secrets.token_urlsafe(24)
        args = [server, "-m", model, "--mmproj", mmproj, "--host", "127.0.0.1", "--port", str(int(port)),
                "--api-key", key, "--no-webui", "-c", str(int(ctx)), "-ngl", str(int(gpu_layers)), "--jinja"]
        args += [str(a) for a in (extra_args or [])]
        self._log = open(log_path, "ab") if log_path else subprocess.DEVNULL
        flags = 0x08000000 if os.name == "nt" else 0                       # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(args, stdout=self._log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=flags)
        super().__init__(f"http://127.0.0.1:{int(port)}/v1", api_key=key, timeout=timeout, prompts=prompts)
        self._wait_ready()

    def _wait_ready(self, limit_s: float = 180) -> None:
        end = time.monotonic() + limit_s
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                raise DescriberError(f"llama-server stopped while loading (exit {self.proc.returncode}); "
                                     "check the paths, or run it by hand to see why")
            try:
                c = http.client.HTTPConnection("127.0.0.1", self.u.port, timeout=2)
                c.request("GET", "/health")
                if c.getresponse().status == 200:
                    return
            except OSError:
                pass
            time.sleep(0.5)
        self.close()
        raise DescriberError("llama-server didn't get ready in time")

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._log is not subprocess.DEVNULL:
            self._log.close()


class CommandDescriber:
    """Your own program: JPEG on stdin, the detail ("short" or "long") as its last argument, one line on stdout.
    The story so far (recent lines, plain text) is in the environment variable DRIVEIN_CONTEXT, to use or ignore.
    No shell is used; the program is a list of arguments, and it gets the timeout to answer."""

    def __init__(self, argv: list, timeout: float = DEFAULT_TIMEOUT_S):
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
            raise DescriberError('vision "command" is a list, e.g. ["C:/path/python.exe", "C:/path/describe.py"]')
        if not os.path.isabs(argv[0]) or not os.path.isfile(argv[0]):
            raise DescriberError(f'vision "command" must start with the full path of a program (got {argv[0]!r})')
        self.argv = argv
        self.timeout = timeout

    def describe(self, jpeg: bytes, detail: str = "short", context: str = "", previous: bytes | None = None) -> str:
        # One picture only through this way (stdin carries one JPEG); a "change" look becomes a "short" one here.
        if detail == "change":
            detail = "short"
        flags = 0x08000000 if os.name == "nt" else 0
        env = {**os.environ, "DRIVEIN_CONTEXT": (context or "")[-CONTEXT_MAX:]}
        try:
            r = subprocess.run(self.argv + [detail], input=jpeg, capture_output=True, timeout=self.timeout,
                               creationflags=flags, env=env)
        except subprocess.TimeoutExpired as e:
            raise DescriberError(f"your describe command took longer than {self.timeout} s") from e
        except OSError as e:
            raise DescriberError(f"your describe command couldn't start ({e})") from e
        if r.returncode != 0:
            raise DescriberError(f"your describe command exited {r.returncode}: "
                                 f"{r.stderr.decode('utf-8', 'replace')[:200]}")
        return tidy(r.stdout.decode("utf-8", "replace"))

    def close(self) -> None:
        pass


def make_describer(vision: dict, log_dir: str | None = None):
    """Build the describer projector.json asks for. Raises DescriberError with a plain message when it can't."""
    if not isinstance(vision, dict):
        raise DescriberError('"vision" in projector.json is a section like {"kind": "llama-server", ...}')
    kind = vision.get("kind", "llama-server")
    timeout = float(vision.get("timeout_s", DEFAULT_TIMEOUT_S))
    prompts = vision.get("prompts")
    if prompts is not None and not (isinstance(prompts, dict) and set(prompts) <= {"short", "long", "change"}
                                    and all(isinstance(v, str) and v.strip() for v in prompts.values())):
        raise DescriberError('vision "prompts" is {"short": "...", "long": "...", "change": "..."} (any of them)')
    if kind == "llama-server":
        return LlamaServerDescriber(
            vision.get("server", ""), vision.get("model", ""), vision.get("mmproj", ""),
            port=int(vision.get("port", 8805)), gpu_layers=int(vision.get("gpu_layers", 99)),
            ctx=int(vision.get("ctx", 4096)), timeout=timeout, prompts=prompts,
            extra_args=vision.get("extra_args"),
            log_path=os.path.join(log_dir, "vision-server.log") if log_dir else None)
    if kind == "openai":
        key = ""
        if vision.get("api_key_file"):
            with open(vision["api_key_file"], encoding="utf-8") as f:
                key = f.read().strip()
        return OpenAIDescriber(vision.get("url", ""), model=str(vision.get("model", "")), api_key=key,
                               timeout=timeout, remote_ok=bool(vision.get("remote_ok", False)), prompts=prompts,
                               extra=vision.get("extra_body"))
    if kind == "command":
        return CommandDescriber(vision.get("command"), timeout=timeout)
    raise DescriberError(f'vision "kind" is "llama-server", "openai" or "command" (got {kind!r})')
