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

1. `projector.json` beside the programs: `{"beach": "http://<the Beach's address>"}`.
2. On the Beach, as the keeper: the Drive-In, **Projector sign-ins**, **Make a projector code**.
3. `python -E -P projector.py claim --config projector.json`, and paste the code at the prompt (it doesn't show).
   The sign-in is saved encrypted for your Windows user.

## Each show

1. Start the speech-to-text helper (keep it running during the show):
   `python -E -P whisper_service.py --model <model folder> --beach-origin http://<the Beach's address>`
2. On the Beach, in the Drive-In: **Start a show** with a title.
3. Play the show, then: `python -E -P projector.py run --config projector.json`. It lists what's making sound;
   pick the show. The console says ON AIR while it listens; Ctrl+C stops it, and it offers to end the show.

A browser plays every tab through one process. Show from a browser window used only for the Drive-In (a separate
profile), never the one with a call open in another tab. Calls and chat programs are never offered.

(`-E -P` keeps Python from reading settings from the environment or modules from the current folder, while still
using libraries installed for your user.)
