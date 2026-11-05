# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The sound-event helper for the Drive-In's listener: run by hearing.py in its own Python (with onnxruntime), never by
hand. Reads pieces of the show's sound from stdin (4-byte little-endian length, then 16 kHz mono 16-bit PCM) and
writes one JSON line per piece: the highest score each watched sound reached in any 3-second window.

Pharos (11-04): the processor only, no custom operators, the model loaded by its exact path, and no model whose
weights point at another file (ONNX "external data") is accepted. Pieces stay in memory; nothing is saved.
"""

import json
import struct
import sys

import numpy as np
import onnxruntime as ort

# The watched sounds and the event model's labels that count for each ("snicker" and "chuckle" rank high when people
# laugh softly, even when "laughter" itself scores low).
WATCH = {
    "laughter": ("Laughter", "Snicker", "Chuckle, chortle", "Giggle", "Belly laugh", "Baby laughter"),
    "applause": ("Applause", "Clapping"),
    "cheering": ("Cheering",),                          # not "Crowd": an arena's hum would always "cheer"
    "music": ("Music",),
    "singing": ("Singing", "Choir"),
    "crying": ("Crying, sobbing", "Whimper", "Wail, moan"),
}
WIN, HOP = 3 * 16000, 16000 + 8000          # 3-second windows, 1.5 seconds apart


def main() -> int:
    model_path, labels_path = sys.argv[1], sys.argv[2]
    with open(model_path, "rb") as f:
        if b"location" in f.read():                      # an external-data model names its weight file this way
            print(json.dumps({"ready": False, "why": "the model refers to another file"}), flush=True)
            return 1
    opts = ort.SessionOptions()
    sess = ort.InferenceSession(model_path, sess_options=opts, providers=["CPUExecutionProvider"])
    with open(labels_path, encoding="utf-8") as f:
        id2label = json.load(f)["id2label"]
    index = {v: int(k) for k, v in id2label.items()}
    cols = {name: [index[l] for l in labels if l in index] for name, labels in WATCH.items()}
    print(json.dumps({"ready": True}), flush=True)
    stdin, stdout = sys.stdin.buffer, sys.stdout
    while True:
        head = stdin.read(4)
        if len(head) < 4:
            return 0
        n = struct.unpack("<I", head)[0]
        if n > 60 * 16000 * 2:                            # at most a minute of sound per piece
            return 1
        x = np.frombuffer(stdin.read(n), dtype="<i2").astype(np.float32) / 32768.0
        frames = [x[i:i + WIN] for i in range(0, max(1, len(x) - WIN + 1), HOP)] or [x]
        batch = np.stack([np.pad(f, (0, WIN - len(f))) for f in frames]).astype(np.float32)
        p = sess.run(None, {"waveform": batch})[0].max(axis=0)
        stdout.write(json.dumps({k: round(float(max(p[c] for c in cs)), 3) if cs else 0.0
                                 for k, cs in cols.items()}) + "\n")
        stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
