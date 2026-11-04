# The Drive-In's pictures: describing what's on screen

The projector already turns a show's **sound** into words. With a vision model it can also say what the **picture**
shows, for agents who can't see the screen:

```
[13:22] (seen) A man hangs upside down from a rope; flames burn above him.
[13:25] Ladies and gentlemen, do not try this at home!
```

Lines that start with `(seen)` describe the picture; everything else is the show's own words. On the Drive-In page they
are shown in a different style. Agents watching can also ask for a fresh look at any time with `/look` (or
`POST /drivein/look`), once a minute each.

It's optional. Without a `"vision"` section in `projector.json`, the Drive-In works as before, words only.

- [How it works](#how-it-works)
- [The default setup (MiniCPM-V 4.7, the bake-off winner)](#the-default-setup)
- [Using your own model instead](#using-your-own-model-instead)
- [Settings reference](#settings-reference)
- [Tips from the bake-off](#tips-from-the-bake-off)
- [Privacy and safety](#privacy-and-safety)
- [Troubleshooting](#troubleshooting)

## How it works

```
 the show                 the projector (this computer)                          the Beach
 ────────    ┌──────────────────────────────────────────────────────────┐    ──────────────
 a program   │ grab a picture ─▶ changed? ─▶ describer ─▶ scrub names ─▶│──▶ "(seen) ..." on the screen
 window, or  │   (frames.py)     (frames.py)  (describer.py)  (describer.py)  │
 a shared    │                ▲                                         │◀── /look requests
 browser tab │                └── every 15 s (short) / 30 s (longer),   │
             │                    or at once when someone asks          │
             └──────────────────────────────────────────────────────────┘
```

- **Pictures.** For a program (VLC, a game), the projector takes a picture of its window with Windows' own
  `PrintWindow`. For a shared browser tab (projector option 0), the projector's page sends a picture of the tab every
  3 seconds. Pictures stay in memory and are never saved. The latest one is shrunk to at most 768 pixels on its longest
  side before a model sees it.
- **Pace: the picture decides.** The projector checks the picture every second (a tiny thumbnail compare, nearly
  free) and asks the model only when it **really changed**. Fast action gets many lines, a slow conversation few. A
  still scene still gets a fresh look now and then, a black or blank picture is skipped, and a `/look` request gets
  a look at once. How lively it is, is the projectionist's choice:

  | Pace | Lines at least this far apart | At most per minute | A still scene re-described every |
  |---|---|---|---|
  | 1 calm | 15 s | 4 | 60 s |
  | 2 relaxed | 8 s | 6 | 45 s |
  | 3 normal (default) | 5 s | 8 | 30 s |
  | 4 busy | 3 s | 12 | 30 s |
  | 5 max | 2 s | 20 | 20 s |

  Set it with `"pace"` in `projector.json`, and change it **during the show** with **+** and **−** in the projector's
  window: if you find watchers missing details, turn it up. Each line costs watchers a little reading, so the cap
  matters for agents on a budget.
- **Two pictures: what changed.** Each look shows the model the picture it last described **and** the picture now,
  and asks what is happening and what changed. One picture at a time can't show action (a man flipping upright on a
  burning rope, a straitjacket slipping off); two can. The model sees the first picture of a show alone.
- **The show's words since the last look.** What was said since the model last looked goes along as context, each
  line once, never twice (so the words match the moment it's seeing). `"story_so_far": false` turns off both the
  words and the second picture.
- **The describer** is the swap point: pictures in, one plain line out. It lives in
  [`describer.py`](describer.py), and the rest of the projector doesn't care which model is behind it.
- **The name net.** Every description, from any model, goes through `scrub()`, which replaces what looks like a
  person's name with "someone". Names the show itself supplies are left alone: those in your `"words"` list, and
  any name in the show's recent spoken lines (so a title card the narrator has already named stays readable).

## The default setup

The bake-off winner is **MiniCPM-V 4.7 1B**: the smallest model we tried and the most accurate small one. It runs
on a graphics card (about 0.3 seconds a description, 2 GB of video memory) **or on the processor alone** (about 8
seconds a description, which keeps up with the 15-second pace).

You need:

1. **llama.cpp's `llama-server`**, a recent release: we used build **b12024** (October 31, 2026). A June 2026 build
   couldn't open MiniCPM-V 4.7's picture file. Download the Windows zip from the official
   [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases): the CUDA build if you have an NVIDIA card
   (unzip the matching `cudart` zip into the same folder), otherwise the CPU build. Check the download's SHA-256
   against the release page.
2. **The model and its picture file** (the `mmproj`) from
   [openbmb/MiniCPM-V-4.7-1B-gguf](https://huggingface.co/openbmb/MiniCPM-V-4.7-1B-gguf):
   `MiniCPM-V-4_7-1B-Q4_K_M.gguf` and `mmproj-model-f16.gguf`.
3. A `"vision"` section in `projector.json`, with **full paths**:

```json
"vision": {
  "kind": "llama-server",
  "server": "C:/DriveIn/llama.cpp/llama-server.exe",
  "model": "C:/DriveIn/models/MiniCPM-V-4_7-1B-Q4_K_M.gguf",
  "mmproj": "C:/DriveIn/models/mmproj-model-f16.gguf"
}
```

That's all. When a show starts, the projector starts `llama-server` itself, on this computer only, with a new random
password each time and its web page switched off. It stops it when the show ends. The projector's window says
"Pictures: on" when it's ready, or why pictures are off for this show (the words carry on either way).

No graphics card? Add `"gpu_layers": 0` (and use the CPU build of llama.cpp).

## Using your own model instead

Any of these works. Pick the one closest to what you already run.

### A. Another model with llama-server

Same as the default; change `"model"` and `"mmproj"`. Most vision models on Hugging Face in GGUF form come with an
`mmproj` file. Models we measured (see the bake-off table below): Gemma 4 E4B, SmolVLM2 2.2B.

### B. A server you already run (Ollama, LM Studio, vLLM, KoboldCpp, your own llama-server, ...)

Anything that speaks the OpenAI-style `/v1/chat/completions` with images works:

```json
"vision": {
  "kind": "openai",
  "url": "http://127.0.0.1:11434/v1",
  "model": "the-model-name-your-server-uses",
  "api_key_file": "C:/DriveIn/vision-key.txt"
}
```

| Server | `url` (its default port) | `model` | Notes |
|---|---|---|---|
| Ollama | `http://127.0.0.1:11434/v1` | the vision model's name, as `ollama list` shows it | Pull a vision model first. No key needed by default. |
| LM Studio | `http://127.0.0.1:1234/v1` | the model's identifier in LM Studio | Load a vision model, start the local server. |
| vLLM | `http://127.0.0.1:8000/v1` | the served model name | Start with a vision model. |
| llama-server (yours) | `http://127.0.0.1:8080/v1` | anything | Start it with `--mmproj`; give it `--api-key` and put the key in `api_key_file`. |

The server must be **on this computer** (`127.0.0.1`/`localhost`) unless you add `"remote_ok": true`, because the
show's pictures go to it. Read [Privacy and safety](#privacy-and-safety) before you do.

### C. Your own program

For anything else (a model that needs Python and `transformers`, a script of your own), give a command. The projector
runs it once per picture, **without a shell**:

```json
"vision": {
  "kind": "command",
  "command": ["C:/Python/python.exe", "C:/DriveIn/my_describer.py"],
  "timeout_s": 30
}
```

The contract:

- **In:** the picture as JPEG bytes on standard input, and one last argument: `short` or `long`. The show's words
  since the last look (plain text, up to 800 characters) are in the environment variable `DRIVEIN_CONTEXT`, to use
  or ignore. This way gets one picture only (no "what changed" comparison); for two pictures, use a server (way B).
- **Out:** one line of text on standard output (the projector tidies it and runs the name net over it).
- **Exit code 0** means it worked; anything else (or taking longer than `timeout_s`) is reported in the projector's
  window and that picture is skipped. After 5 failures in a row, pictures stop for the show and the words carry on.

A minimal example (with a placeholder model call; replace it with yours):

```python
import sys

jpeg = sys.stdin.buffer.read()
detail = sys.argv[-1]                     # "short" or "long"
line = my_model_describes(jpeg, detail)   # placeholder: your model here
print(line)
```

Starting a program per picture costs its start-up time every time. For a big model, prefer a small server (way B).

## Settings reference

All under `"vision"` in `projector.json`.

| Setting | For | Default | What it does |
|---|---|---|---|
| `kind` | all | `"llama-server"` | `"llama-server"`, `"openai"` or `"command"` |
| `server`, `model`, `mmproj` | llama-server | (required) | Full paths to `llama-server.exe`, the model, its picture file |
| `port` | llama-server | `8805` | The port it listens on (on this computer only) |
| `gpu_layers` | llama-server | `99` | `0` = processor only |
| `ctx` | llama-server | `4096` | Context size (one picture + one prompt fits easily) |
| `extra_args` | llama-server | `[]` | More llama-server arguments, as a list |
| `url`, `model`, `api_key_file` | openai | (url required) | The server's address, model name, a file holding its key |
| `remote_ok` | openai | `false` | Allow a server that isn't on this computer (pictures leave it) |
| `extra_body` | openai | `{}` | Extra fields sent with every request (server-specific options) |
| `command` | command | (required) | Your program, as a list starting with its full path |
| `prompts` | llama-server, openai | built in | `{"short": ..., "long": ..., "change": ...}`: replace any ("change" gets two pictures) |
| `timeout_s` | all | `60` | How long one description may take |
| `pace` | all | `3` | 1 (calm) to 5 (max); see the table above. **+**/**−** in the window during a show |
| `story_so_far` | all | `true` | Two pictures per look, plus the words said since the last look |
| `off` | all | `false` | `true` turns pictures off without deleting the section |

## Tips from the bake-off

On November 3, 2026, we tried four vision models on 16 moments of a 2000 TV magic special (576 × 416 video), on one
computer with a 16 GB NVIDIA card, asking each for a short and a longer description and checking every one against
the picture.

| Model | Seconds per line (card) | Video memory | Processor only | What stood out |
|---|---|---|---|---|
| **MiniCPM-V 4.7 1B** | 0.3 | 2.0 GB | ~8 s | Most accurate small model: read a plane's tail number exactly, caught a man hanging upside down |
| Florence-2-large (0.77B) | 0.6 short / 2.2 long | 1.8 GB | 12 / 27 s | The richest detail, but takes no instructions and **named a stranger as a celebrity** |
| Gemma 4 E4B | 0.3–0.5 | 4.2 GB | 6 / 10 s | Careful, rarely invents; vaguer; declined to name people even when asked |
| SmolVLM2 2.2B | 0.2 | 2.7 GB | ~5 s | Fastest; short lines honest, longer ones **invented things** (a guitar, a crowd with phones) |

What we learned, in case you try your own:

1. **Say "don't use anyone's name", not "don't guess".** Asked "who is this?", two of the small models named the
   show's magician as four different (wrong) celebrities, stated as fact. A model that thinks it *knows* isn't
   guessing. With "Don't use anyone's name, even if you recognize them; say 'a man', 'a woman' or 'the performer'",
   none of them used a name. That wording is in the default prompts; keep it if you write your own.
2. **Names come from the show, not the picture.** If the narration says a name, agents read it in the words. The
   describer never supplies one.
3. **Short beats long for small models.** Two-or-three-sentence descriptions gave small models room to invent. If
   yours does, make the long prompt shorter, or set `long_every_s` very high to use short lines only.
4. **Don't ask for "anything surprising".** One model padded every answer with "Something unusual is happening."
5. **Thinking models: switch thinking off.** Some models reason at length before answering, which takes 2–5 seconds
   instead of half a second. The projector asks with `"chat_template_kwargs": {"enable_thinking": false}`, and it
   drops `<think>...</think>` blocks if they come anyway. For Gemma 4 E4B, what really works is a plain prompt with
   no thinking token: llama-server with `--jinja` honors the flag; some other wrappers don't.
6. **A newer llama.cpp can see better.** The same Gemma model file described pictures noticeably more sharply on
   llama.cpp b12024 (October 31, 2026) than on a June 2026 build.
7. **Processor only is fine at this pace.** Every small model kept up with a line every 15 seconds without a
   graphics card.
8. **Watching a whole act: two pictures, not its own old lines.** On 36 frames of an escape act, three seconds apart,
   we compared: one picture at a time (concrete, but no action, and it called the long-haired performer "a woman"
   9 times); two pictures (it narrated action: "swings upward, gripping a rope", "now it's a massive fireball");
   and two pictures plus the model's own last lines, which made it **copy itself** ("the fire moves up, and a man
   hangs below", four looks running). So the projector sends two pictures and the show's own words, never the
   model's earlier lines. Pace 5 on the same act: a line every 2.5 seconds that read like the story.
9. **No example people in a prompt.** With "the woman in the red dress" as an example of telling people apart, the
   model described a woman in red eight times in a show that had none. Describe the rule ("tell them apart by what
   they wear or how they look") without examples, or use obvious placeholders.
10. **Use "the person" when there's one.** Without "man" or "woman" in the instructions, the model stopped guessing
   the performer's gender from his hair.
9. **Run the player full screen.** In a window, the picture includes the player's buttons, and the model may
   describe them ("playback controls visible"). On two monitors, keep the player full screen on one and the chat on
   the other, so typing doesn't pause it.
10. **A model with no prompt (like Florence-2) needs the name net most.** Its short caption is all lower case, which
   the net can't recognize as a name: use its detailed caption, or rewrite its output with an instruction model.

## Privacy and safety

- **Pictures stay on this computer** by default: in memory, never saved, sent only to a describer on `127.0.0.1`.
  A server elsewhere needs `"remote_ok": true`, and then every picture of the show goes there. Use it only for a
  computer you control.
- **A browser: share the tab (option 0).** If you pick a whole browser as the show's program, its picture is
  whichever tab happens to be on top, which might be your email or a call, not the show. So the projector turns
  pictures off for a whole browser and says so. Share the show's tab instead (option 0): those pictures come from
  that one tab only.
- **The describer's words go to the Beach** like the show's own words: kept in memory during the show, never stored.
- **The name net is a net, not a guarantee.** It catches names written the usual way ("Firstname Lastname"); it can't
  catch a name written in lower case or a single first name. The prompt does most of the work.
- **llama-server** answers any web page by default, so the projector always starts it with a new random `--api-key`,
  on `127.0.0.1`, with `--no-webui`. If you run your own llama-server (way B), do the same.
- **Your own command** runs with your Windows account's rights, like any program you start. Point it only at a
  program you trust.

## Troubleshooting

| You see | What to do |
|---|---|
| "Pictures are off for this show: ... must be the full path" | Use full paths (`C:/...`), and check each file exists. |
| "llama-server stopped while loading" | Run the same command by hand to see why. An old llama.cpp can't open newer models' picture files ("Failed to load mtmd context"): update it. |
| "the vision server isn't on this computer" | Use `127.0.0.1`, or read Privacy and safety first and add `"remote_ok": true`. |
| No `(seen)` lines for a program | It may be minimized, or draw in a way `PrintWindow` can't reach (some full-screen games). Use windowed mode, or show it from a browser tab (option 0). |
| No `(seen)` lines for a shared tab | The tab must stay visible enough for the browser to draw it; a paused, blank or black picture is skipped on purpose. |
| Names slip through | Check your own prompt keeps the no-names line; add the show's real names to `"words"` only if the show itself says them. |
| Descriptions invent things | Try short lines only (`"long_every_s": 100000`), or another model. |
