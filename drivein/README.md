# The Drive-In projector

The Drive-In (a room on the Beach's map) shows a show's words on its screen. These two programs make the words, on
the keeper's own Windows computer, the one playing the show:

- `whisper_service.py`: local speech-to-text (127.0.0.1 only). Sound in, words out. It takes raw 16 kHz mono 16-bit
  samples and nothing else, answers only the Beach's own page, and holds no sign-in.
- `projector.py`: captures ONE program's sound (a game, a player, a browser used only for the Drive-In), sends it to
  the helper, and sends the words to the Drive-In with its own narrow sign-in. It has no code for the whole
  computer's sound or for a microphone.

Words only for now: the speech in a show (and an audio-description track's narration, where a video has one).
Ordinary videos, games, your own videos and cameras; never a stream protected against copying.

## You need

- Windows 10 (2004) or later, Python 3, and `faster-whisper`, `numpy`, `comtypes`, `psutil` installed.
- A faster-whisper model in a local folder (a CTranslate2 conversion, e.g. Systran's `faster-whisper-large-v3` or
  `faster-whisper-small.en`, pinned by commit and checked by hash). Nothing is downloaded at run time.
- An NVIDIA graphics card helps (`--device cuda`, with `nvidia-cublas-cu12` and `nvidia-cudnn-cu12`); the CPU works
  for the small model.

## Once

1. `projector.json` beside the programs:
   `{"beach": "http://<the Beach's address>", "model": "<the faster-whisper model folder>"}`
   (and `"deny_also": [...]` for any program of yours that must never be captured; and `"words": [...]` for names
   the speech helper should spell right, like your town, a shop or a character: `["Whatsit Bay", "Doohicky"]`).
2. On the Beach, as the keeper: the Drive-In, **Projector sign-ins**, **Make a projector code**.
3. `python -E -P projector.py claim --config projector.json`, and paste the code at the prompt.
   The sign-in is saved encrypted for your Windows user.
4. A desktop shortcut to `python -E -P projector.py run --config projector.json` makes each show a double-click.

## Describing the picture (optional)

With a vision model, the projector also says what's on screen, as lines starting `(seen)`, and watchers can ask for a
fresh look with `/look`. We recommend LFM3-Omni-2B through llama.cpp (one small model that also hears, for the
Drive-In's coming listening part); MiniCPM-V 4.7 1B is a fine pair of eyes that also runs without a graphics card. Any
other model can be swapped in: a server you already run (Ollama, LM Studio, ...) or a program of your own. When a show
starts, two optional questions (a genre, and show notes about what's on stage) help the model name what it sees.
Setup, swapping recipes and tips: **[VISION.md](VISION.md)**.

## Captions from a file (optional, VLC)

If you have captions for a video (an `.srt` file, from your editor or your own channel), they beat speech-to-text:
names come out right and nothing gets invented. Put the `.srt` beside the video with the same name (`Show.mp4` and
`Show.srt`), play it in VLC, and the projector sends its captions as VLC reaches them, following pause, skip and
rewind. No sound is captured. Once, to set it up:

1. `python -E -P projector.py vlc --config projector.json`. It makes a long random password (VLC's remote has no
   lockout, so a memorable one could be guessed), saves it encrypted for your Windows user, and shows it once.
2. In VLC: **Tools > Preferences**, **Show settings: All**, **Interface > Main interfaces > Lua**: paste it as the
   **Password**. Save. Leave **Web** unticked under Main interfaces: the remote should run only for shows.
3. A shortcut that starts VLC with its remote on, on this computer only, for Drive-In shows (your everyday VLC stays
   as it was):
   `"C:\Program Files\VideoLAN\VLC\vlc.exe" --extraintf http --http-host 127.0.0.1 --http-port 8798`
   (another port? set `"vlc_port"` in `projector.json` too).

**Never open VLC's web page in a browser.** A browser that remembers the login would let any website send VLC
commands through it. Only the projector talks to VLC's remote, and it only ever asks which file is playing and
where: it never sends VLC a command. With no `.srt` beside the video, or VLC opened the ordinary way, it listens to
the sound as usual.

## Showing from a browser (YouTube and other sites)

**Share one tab (option 0, the easy way).** Start the projector and pick **0. A browser tab**. Your browser opens the
projector's own page, which runs on this computer only (`http://127.0.0.1:8795`). Click **Share a tab**, choose the
tab with your show, and keep **Also share tab audio** on. Only that one tab's sound is used: other tabs, calls and
extensions don't matter, so your everyday browser is fine. Stop sharing (the browser's bar) to end the show. The
page holds no sign-in; it only hands the tab's sound to the projector beside it. (Chrome and Edge share tab sound;
Firefox doesn't.)

Or pick the whole browser program from the list, as with any app. Then:

- **A browser window just for the Drive-In.** A browser plays every tab's sound through one program, so a call,
  music or another video in any tab would be heard too.
- **If your browser isn't in the list:** the projector never captures a program that's running a command prompt or
  a shell, and some browser extensions start one as a helper (for example, an AI assistant extension that can control
  the browser). The list says so; share a tab (option 0) instead.

Either way (tried with YouTube, 11-03):

- **Words only, by ear.** The projector turns the sound into words on this computer; it never fetches a site's own
  captions. Spoken words come through well (a word list in `projector.json` gets names right), but sound effects
  don't: for those, a captions file with VLC (above) is the deluxe version.
- **Long stretches with no pause** can split a word between two pieces now and then ("magic" heard as "ma-" and
  "...gic"). A small overlap between pieces is on the way.

## Each show

1. Open your video or game, and pause it.
2. Start the projector (the shortcut). It starts the speech helper by itself.
3. Type the show's title, then the number of your app. It opens the show on the Beach and starts listening.
4. Press Play, and go talk. Close the projector's window (or Ctrl+C) to end the show.

Picking the app is the choice to capture its sound: there's no second question. Calls, chat programs and anything
running one are never listed. A browser plays every tab through one process, so show from a browser window used only
for the Drive-In, never the one with a call open in another tab.

(`-E -P` keeps Python from reading settings from the environment or modules from the current folder, while still
using libraries installed for your user.)
