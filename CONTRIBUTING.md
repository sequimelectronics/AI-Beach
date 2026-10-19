# Contributing to AI-Beach

Thank you for helping. A few things to know first.

## License of contributions

AI-Beach is licensed **AGPL-3.0-only** (see `LICENSE` and the License section of the README). By
contributing, you agree that your contribution is licensed AGPL-3.0-only too. Art you contribute (images,
SVG drawings, sketches) is licensed **CC BY-SA 4.0**, like the rest of the art (`docs/art/LICENSE`).

Every source file starts with these two lines, in its own comment style:

```text
SPDX-License-Identifier: AGPL-3.0-only
Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
```

`tests/test_spdx.py` fails if a source file is missing them. Files derived from Clawblox keep their MIT
notice instead (see `docs/LICENSES.md`); don't relicense them.

## The household rules

This repository grew up in a household, and its rules still hold:

- **No real people's or households' names or details** anywhere: in code, tests, docs, screenshots or
  commit history. Use the neutral test names (Sandy, Pebble, Coral, Drift, Shell, Kelp, Chatter, Tide)
  and they/them for anyone unnamed. History is permanent, so check before you commit.
  The only names are the credits the keeper approved: the copyright line in the headers, and Kellan N.'s
  art credit in `docs/art/README.md`.
- **The doohicky rule:** in anything an agent reads (game cards, error messages, the visitor kit, the
  helper's help), examples use obviously made-up names, like "ask Whomever for Whatsits", never a
  name that could be a real player. A small model copies an example as it stands, so an example has
  to be impossible to mistake for a real person or record. Keep the notation real ("ask Whomever 7s"),
  so the example still shows the exact form. The neutral test names above are for tests. (The keeper's
  household named it, and is happy to share it.)
- The keeper is the **Beach-keeper** ("keeper"), with **admin** rights; never other words for it.
- **Nothing from the internet at runtime**, apart from the local machine. No accounts, no telemetry.
- **Readable first**, American spelling (`tests/test_spelling.py` checks it), and the phone width works.
- Every subprocess gets explicit stdin, stdout and stderr (Windows matters).

## Before you send a change

```bash
python -m unittest discover -s tests
```
