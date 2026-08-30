# hexapod-vision

[![CI](https://github.com/DexstarLau/hexapod-vision/actions/workflows/ci.yml/badge.svg)](https://github.com/DexstarLau/hexapod-vision/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.14-blue)
![Tests](https://img.shields.io/badge/tests-19%20passing-brightgreen)

Monocular range estimation from a printed fiducial, for a six-legged robot.
The printable targets, the collection protocol, the manifest, and the checks
that catch a recording mistake in week two rather than in November.

Companion to [`hexapod-kinematics`](https://github.com/DexstarLau/hexapod-kinematics),
which holds the robot's constant table and kinematics. Neither repository
depends on the other.

---

## Status — 30 August 2026

| | |
|---|---|
| Printable marker set | done — `print/` |
| Calibration board | done — `print/` |
| Collection protocol | done — `docs/` |
| Manifest template and checker | done — `data/`, `tools/` |
| Camera calibration | **not started** — needs the printed board |
| Collection, 40 sessions x 50 frames | **not started** — September to November |
| Range estimator and error analysis | **not written** |

**19 tests passing, 0 skipped.** Standard library only, so CI needs no
`pip install` and cannot be broken by a wheel that does not exist yet for a
Python version in the matrix.

---

## The three things no later processing can recover

| | |
|---|---|
| **True distance** | The image does not contain it. An unlabelled frame is a picture, not a data point |
| **Session identity** | Which frames share a camera setup, a room and a lighting condition. Lose it and the set cannot be split into train and test without leaking |
| **Deliberately hard frames** | A frame that was hard on purpose and one that failed by accident look identical afterwards |

Crops, resizes, re-detection and derived features can all be redone from the
file. These three cannot. `tools/check_manifest.py` treats a missing one as an
**error**; everything else is a warning.

---

## The print set

| File | Job |
|---|---|
| `print/aruco_4x4_100mm.pdf` | 4 range markers, `DICT_4X4_50`, IDs 0–3, 100 mm nominal |
| `print/charuco_a4_landscape.pdf` | ChArUco calibration board, `DICT_5X5_100`, 7×5 squares at 32 mm |

**Different dictionaries on purpose.** A ChArUco board built from `4X4_50`
would carry IDs 0–16, and a frame containing both targets would report the
same ID twice with no way to say which target it came from.

**Print at 100 %. No fit-to-page, matte paper, flat.** Then measure the black
square with calipers and write it down. Every range estimate divides by the
*measured* width, not by 100 — a sheet that came out at 99.6 mm gives a clean
0.4 % bias on every frame in the set, which survives every sanity check
because it moves nothing relative to anything else. The checker warns when a
manifest records exactly 100.0.

Both PDFs are generated, committed, and checksummed. Generation is
byte-reproducible (`reportlab invariant=1`), so regenerating unchanged input
gives an identical file and the checksum means something.

```bash
python -m pytest tests/ -q

# regenerating the print set needs requirements-print.txt, CI does not
python -m tools.make_print_set --out print/

# after a session
python -m tools.check_manifest --manifest data/manifest.csv --frames data/frames
```

---

## Frames are not in this repository

`data/manifest.csv` is tracked. The 2000 JPEGs are not, and
`.gitignore` enforces it.

**Git has no delete.** A committed image stays in every clone forever, even
after a later commit removes it. Several gigabytes of frames would make this
repository permanently slow to clone, for data that is not the deliverable.

The manifest **is** the record: 2000 rows of text, diffable, reviewable, and
the thing that makes the images meaningful. A representative sample lives in
`docs/samples/`. The full set is held outside git with its own backup.

---

## Line endings are pinned

`.gitattributes` normalises text to LF and marks `*.pdf` and `*.png` binary.
Not a style preference — **Git decides a file is binary by looking for a NUL
byte in its first 8000, and neither PDF here has one.** Both were classified as
text and rewritten on a Windows checkout, which corrupts them. Anyone cloning
on Windows would have got a broken calibration target with no indication of it.
Found by the Windows half of the CI matrix; invisible on the machine that made
the files. `tests/test_manifest.py` fails if `.gitattributes` is removed.

---

## Third-party material

The kit manufacturer's manuals, schematic and example source are referenced,
never redistributed, and never copied into source. Nothing here is theirs.
The ArUco and ChArUco markers are generated from OpenCV's public dictionaries.

---

## Licence

MIT. See `LICENSE`.
