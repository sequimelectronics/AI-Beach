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
- [Choose your setup (one model, or two)](#choose-your-setup)
- [Genre and show notes (optional)](#genre-and-show-notes)
- [Listening: sounds, and voice changes (optional)](#listening)
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
 browser tab │                └── when the picture really changes,      │
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
- **Short lines about actions, not outfits.** Each line says what someone or something *does* ("the man holds a
  white chicken while the woman looks at it"), in at most 15 words, calling people the man, the woman, he, she or they,
  and mentioning clothes only when two people would otherwise get mixed up. Measured on a 30-second clip: 23 words a
  line before, 13 after, with the outfits gone from almost every line.
- **No repeats.** A line that says nearly the same as one of the last three on the screen isn't posted (a still
  stretch used to give six "the man holds the chicken" lines in a row). A watcher's `/look` always gets a line.
- **The show's words since the last look.** What was said since the model last looked goes along as context, each
  line once, never twice (so the words match the moment it's seeing). `"story_so_far": false` turns off both the
  words and the second picture.
- **The describer** is the swap point: pictures in, one plain line out. It lives in
  [`describer.py`](describer.py), and the rest of the projector doesn't care which model is behind it.
- **The name net.** Every description, from any model, goes through `scrub()`, which replaces what looks like a
  person's name with "someone". Names the show itself supplies are left alone: those in your `"words"` list, and
  any name the show has said aloud so far this show (so a title card the narrator named minutes ago stays readable).
  A name that only appears on screen (a caption under an expert, a label on a map) is still replaced for now.

## Choose your setup

Two ways, both on this computer only. Start with the first unless you have a reason not to.

### 1. One model that sees (recommended): LFM3-Omni-2B

One small model for the whole Drive-In. It **sees** (the `(seen)` lines), and it can also **hear** (see
[Listening](#listening)): one model for both, and video memory is precious on a home computer, so it's the default.

- About **1.6 GB** to download; **about 2.7 GB of video memory** in use; **0.2 to 0.3 seconds** a line on our
  16 GB NVIDIA card. Processor-only speed: not measured yet.
- It sees more than the other small models (it named props, followed a card trick, read a playing card's suit on old
  VHS) and writes a little more. On the very hardest frames (a man upside down in a loose straitjacket) it can see
  things that aren't there.
- License: the **LFM Open License 1.0** (free, including commercial use, for organizations under 10 million dollars
  of yearly revenue). Read it before you use it in a product.

You need:

1. **llama.cpp's `llama-server`**, build **b12024** (October 31, 2026) or newer: LFM3 support arrived on October 27,
   2026. Download the Windows zip from the official [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases):
   the CUDA build if you have an NVIDIA card (unzip the matching `cudart` zip into the same folder), otherwise the CPU
   build. Check the download's SHA-256 against the release page. The zip also holds `ggml-rpc-server.exe`, for sharing
   work across computers. The Drive-In never uses it and it has a published security advisory, so don't start it; you
   can delete it.
2. **The model and its picture file** (the `mmproj`) from
   [LiquidAI/LFM3-Omni-2B-GGUF](https://huggingface.co/LiquidAI/LFM3-Omni-2B-GGUF):
   `LFM3-Omni-2B-Q4_K_M.gguf` and `mmproj-LFM3-Omni-2B-Q8_0.gguf`.
3. A `"vision"` section in `projector.json`, with **full paths**:

```json
"vision": {
  "kind": "llama-server",
  "server": "C:/DriveIn/llama.cpp/llama-server.exe",
  "model": "C:/DriveIn/models/LFM3-Omni-2B-Q4_K_M.gguf",
  "mmproj": "C:/DriveIn/models/mmproj-LFM3-Omni-2B-Q8_0.gguf"
}
```

That's all. When a show starts, the projector starts `llama-server` itself, on this computer only, with a new random
password each time and its web page switched off. It stops it when the show ends. The projector's window says
"Pictures: on" when it's ready, or why pictures are off for this show (the words carry on either way).

### 2. A separate pair of eyes: MiniCPM-V 4.7 1B

The winner of our first bake-off, and still a very good pair of eyes: plainer, shorter lines, and fewer vivid
mistakes on hard frames. It **runs on the processor alone** too (about 8 seconds a line: fine at pace 1 or 2). It
only sees; for listening, use the small sound-event model (no video memory at all, see [Listening](#listening)).

- Files from [openbmb/MiniCPM-V-4.7-1B-gguf](https://huggingface.co/openbmb/MiniCPM-V-4.7-1B-gguf):
  `MiniCPM-V-4_7-1B-Q4_K_M.gguf` and `mmproj-model-f16.gguf`. llama.cpp b12024 or newer (a June 2026 build couldn't
  open its picture file).
- About **2 GB of video memory**, **0.3 seconds** a line on a graphics card.
- The same `"vision"` section, with those two file names.

No graphics card, either way? Add `"gpu_layers": 0` (and use the CPU build of llama.cpp).

## Genre and show notes

Two optional questions when a show starts (Enter skips them), so the model knows what it's looking at:

- **Genre:** a word or two, like documentary, cooking or magic. Without it, small models read every stage as a rock
  concert (a saw became "an electric guitar", the props "speakers").
- **Show notes:** at most 25 words about **what is on stage, not what happens**. Change them between acts: press
  **N** in the projector's window, type the new notes, Enter (an empty Enter clears them, Esc keeps the old ones).
  You can also set `"genre"` and `"notes"` under `"vision"` in `projector.json` as the starting answers.

Why "not what happens": we tested a magic act both ways. Notes that told the ending ("they walk into the fan, vanish
and reappear in the audience") made the model announce the ending from the very first frame, over and over, even on
the title card, and adding "keep the suspense" didn't stop it. Notes about the setup only ("A giant rotating fan forms
one wall of a lit box; two dancers.") got the fan named in most lines and spoiled nothing. Write them like a stage
direction, not a plot summary.

## Listening

Optional, and separate from the words (which come from the speech helper either way). The listener hears the same
pieces of the show's sound the words come from and adds two kinds of line:

```
[10:20] (sound) laughter
[11:18] (sound) applause and music
[11:18] Elvis has left the building.
```

- **`(sound) ...`** when a sound **starts**: laughter, applause, cheering, music, singing or crying. A long song gets
  one line, not one every few seconds. It runs beside the words and never holds them up.
- **`(new voice)`** in front of a line when the person speaking changes. **Off by default**: see below.

Two ways to listen, and you can use both:

| | What it is | Good at | Cost |
|---|---|---|---|
| **The sound-event model** (CED-Base) | A small model made for this, 87 MB, run on the processor in its own Python | Applause and music (all of ours), laughter with a low cutoff | ~0.7 s per piece on the processor, no video memory |
| **The picture model listening too** (`"llm": "vision"`) | LFM3-Omni-2B, the same server the pictures use | Sounds when there's no event model; voice changes | ~0.2 s per question on the graphics card |

What we measured (a magic special and a documentary, checked against a person listening to every clip): the event
model got applause and music every time and most laughter (a single quiet chuckle slipped past); every model found
laughter the hardest. For **voice changes**, the picture model heard 9 of 12 known changes and non-changes in clean
speech, but with a laughing audience between the lines it marked a "new voice" on almost every piece of one man
talking. So `"voices"` is off unless you turn it on, and it's best tried on shows without an audience.

**Setting it up.** The event model needs `onnxruntime` and `numpy`, which the projector itself doesn't, so it gets a
Python of its own:

1. Make a separate Python environment just for it, and install exactly these, hash-checked:
   `python -m venv C:/DriveIn/sound-venv`, then
   `C:/DriveIn/sound-venv/Scripts/python.exe -m pip install --require-hashes -r requirements.txt` with a
   requirements file that pins `onnxruntime`, `numpy` and their dependencies to exact versions and hashes.
2. Download the model from [mispeech/ced-base](https://huggingface.co/mispeech/ced-base): `model.onnx` and
   `config.json` (the labels).
3. A `"hearing"` section in `projector.json`, with full paths:

```json
"hearing": {
  "llm": "vision",
  "voices": false,
  "events": {
    "python": "C:/DriveIn/sound-venv/Scripts/python.exe",
    "model": "C:/DriveIn/models/ced-base/model.onnx",
    "labels": "C:/DriveIn/models/ced-base/config.json"
  }
}
```

Leave out `"events"` to listen with the picture model alone (one model for everything), or leave out `"llm"` to use
the event model alone (no pictures needed). The window says "Listening: on" when it's ready, or why it's off.

**Privacy.** The listener hears only the show's own sound, the same capture the words come from: never the
microphone. Pieces stay in memory (the current one, and the last 4 seconds of the one before, for voice changes) and
are dropped when the show ends: nothing is saved, and nothing leaves this computer. No voiceprints are made: the model
just hears the moment where one piece meets the next, and nothing about a voice is kept or compared across shows. The
lines name nobody. The event model runs on the processor only, loaded from its exact path, and a model that points at
another file for its weights is refused.

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
| `genre`, `notes` | all | (none) | Starting answers to the two show-start questions (notes: 25 words, what's on stage) |

Listening, under `"hearing"` (see [Listening](#listening)):

| Setting | Default | What it does |
|---|---|---|
| `llm` | (none) | `"vision"`: the picture model's server listens too (sounds when there's no event model; voice changes) |
| `voices` | `false` | `true` marks `(new voice)` when the speaker changes (needs `llm`; see the measurements first) |
| `events` | (none) | `{"python": ..., "model": ..., "labels": ...}`: the sound-event model, its own Python, full paths |
| `off` | `false` | `true` turns listening off without deleting the section |
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
   guessing. Told plainly never to name anyone they recognize, none of them used a name. That rule is in the default
   prompts; keep it if you write your own.
2. **Names come from the show, not the picture.** If the narration says a name, agents read it in the words. The
   describer never supplies one.
3. **Short beats long for small models.** Two-or-three-sentence descriptions gave small models room to invent. If
   yours does, ask for fewer words in your own prompts, or lower the pace.
4. **Don't ask for "anything surprising".** One model padded every answer with "Something unusual is happening."
5. **Thinking models: switch thinking off.** Some models reason at length before answering, which takes 2–5 seconds
   instead of half a second. The projector asks with `"chat_template_kwargs": {"enable_thinking": false}`, and it
   drops `<think>...</think>` blocks if they come anyway. For Gemma 4 E4B, what really works is a plain prompt with
   no thinking token: llama-server with `--jinja` honors the flag; some other wrappers don't.
6. **A newer llama.cpp can see better.** The same Gemma model file described pictures noticeably more sharply on
   llama.cpp b12024 (October 31, 2026) than on a June 2026 build.
7. **Processor only is fine at a calm pace.** Every small model kept up with a line every 15 seconds (pace 1)
   without a graphics card; paces 4 and 5 look every 2 to 3 seconds and want one.
8. **Watching a whole act: two pictures, not its own old lines.** On 36 frames of an escape act, three seconds apart,
   we compared: one picture at a time (concrete, but no action, and it called the long-haired performer "a woman"
   9 times); two pictures (it narrated action: "swings upward, gripping a rope", "now it's a massive fireball");
   and two pictures plus the model's own last lines, which made it **copy itself** ("the fire moves up, and a man
   hangs below", four looks running). So the projector sends two pictures and the show's own words, never the
   model's earlier lines. Pace 5 on the same act: a line every 2.5 seconds that read like the story.
9. **No example people in a prompt.** With "the woman in the red dress" as an example of telling people apart, the
   model described a woman in red eight times in a show that had none. Describe the rule ("tell them apart by what
   they wear or how they look") without examples, or use obvious placeholders.
10. **Short tags and pronouns, not "the same person".** Asked to say "the same person" for someone it had already
   described, one model used it for everyone, so two dancers blurred into one. Telling it to call people the man,
   the woman, he, she or they (and to mention clothes only when needed) kept them apart and cut the words.
11. **Say what you want, not what you don't.** Asked to "mention lighting only if nothing else is happening", a small
   model mentioned lighting in every single line; given a list of impossible things to watch for, it recited
   "nothing appears or disappears" over and over. Whatever words your prompt holds, it repeats. "Focus on what people
   and things are doing" and "describe anything unusual exactly as it looks, even if it seems impossible" worked
   better (and the second suits sci-fi and fantasy shows too).
12. **Run the player full screen.** In a window, the picture includes the player's buttons, and the model may
   describe them ("playback controls visible"). On two monitors, keep the player full screen on one and the chat on
   the other, so typing doesn't pause it.
13. **A model with no prompt (like Florence-2) needs the name net most.** Its short caption is all lower case, which
   the net can't recognize as a name: use its detailed caption, or rewrite its output with an instruction model.
14. **No quoted phrases, no lists of examples.** Whatever a prompt holds, a small model repeats: a quoted phrase came
   back on screen in quotation marks, a list of action words ("lifts, holds up, ...") put "lifts" in every line (even
   "the man lifts the glowing fire"), and an old example list of people ("a man, a woman, a child") was followed by
   "a child is present" in a scene with no child. Describe the rule; leave the examples out.
15. **Say "fantasy" and you get fantasy.** Telling a model "this may be a sci-fi or fantasy story" turned an ordinary
   stage into "a glowing, fiery entity" for one model. "Describe it exactly as it looks, even if it seems impossible"
   keeps the door open without the invitation.
16. **Old footage gets modern details.** A 1995 audience got "glowing phone screens" (lighters and camera flashes,
   really). Models fill gaps with what's normal in their own training; a genre or show note helps.
17. **Steady lighting helps more than simple action.** Silhouettes, glare and colored smoke take away the clothes
   and faces a model uses to tell people apart; a brightly and evenly lit stage with three people went far better than
   a hazy one with two.
18. **A model's advice about itself is a hint, not a recipe.** Asked what instructions would help it, one model wrote
   its own prompt; its lines got longer. It also explained that a man hanging upside down meant "the image is
   rotated", which told us exactly why it misread him.

### What to expect (start with something easy)

A small model describes what's **there**, not what's **impossible**. We tested on a magic special, the hardest kind
of show there is: in one act, six volunteers and the magician circled a floating table while he talked at full speed,
and the model tracked who was who, saw the tablecloth change hands, and never once noticed the table was floating,
even on a shot from underneath. Magic is built to fool eyes; it fooled this one too.

**For magic, the model reports and you gasp.** The model's job is to hand over faithful evidence: "she is in the left
tower" now, "she is in the right tower" a few seconds later. Connecting the two ("wait, she's in both!") is for the
people and agents watching, who are good at it. A model small enough to run at home that does the gasping itself may
not exist yet.

So try your setup first on something gentle: a cooking or crafts show, a nature documentary, a slow drama, your
own home videos, a walk-through game. People in plain sight, doing visible things, one scene at a time. Save the
magic specials for later, and enjoy it when it catches something anyway.

A field-archaeology documentary was the best show we tried: the model followed the digger, the trench filling with
stones, a ruler drawn across an aerial photo, and a computer-drawn temple rising over the real field, while the
narration carried the history. Two things we measured on it:

- **Pictures can drown out the talk.** At pace 5, picture lines were about two thirds of all the text on the screen,
  even in a show that's mostly conversation (a picture line runs about three times as long as a spoken one). For
  talky shows, **pace 3** is plenty.
- **What a show costs a watcher.** 21 minutes at pace 5 then 4 came to about 17,700 tokens of screen text (counted
  with a Gemma tokenizer), about 830 a minute. Without pictures it would be roughly half.

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
| The same line keeps coming | Near-repeats of the last three lines are dropped already; lower the pace for a slow show. |
| Names slip through | Check your own prompt keeps the no-names line; add the show's real names to `"words"` only if the show itself says them. |
| Descriptions invent things | Add a genre and show notes, lower the pace, or try the other setup's model. |
