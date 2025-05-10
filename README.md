# Quadwave MIDI Bridge

Turn the **Misa Quadwave's** custom SysEx snapshots into human‑readable
console output or any control‑logic you want. The script *doesn't generate
MIDI itself* (pass‑through only) – it's a hack‑ready scaffold for you to
generate any MIDI you like.

---

## What It Prints

| Input         | Console output                                                          |
| ------------- | ----------------------------------------------------------------------- |
| Neck packet   | `String N fret F ON` **or** `OFF` for every state change                |
| Touch panel   | `pressed` / `released` and **`dragged`** (when X/Y moves while pressed) |
| Anything else | Sent straight through to the chosen MIDI OUT                            |

Example stream:

```
String 1 fret 1 ON
Touch 0 pressed  at x=4560 y=2120
Touch 0 dragged  to x=4900 y=2440
String 1 fret 1 OFF
Touch 0 released at x=4900 y=2440
```

---

## Quick Start

```bash
pip install mido python-rtmidi   # deps

# macOS / Linux – creates a virtual port "Quadwave Bridge"
python quadwave_midi_bridge.py

# Windows – point it at a loopMIDI cable you created
Install loopMIDI (free) and create a loopback port called "misa-loopback".
python quadwave_midi_bridge.py --out-port "misa-loopback"
```

Make sure the Misa Quadwave is in 'Raw Mode'. This mode will send the Sysex messages
expected by the Quadwave Bridge.

In Ableton or any DAW's settings, select the new MIDI output.

---

## Packet Format (firmware ≥ v2.4.0)

### Neck

* **3 bytes per string** → 12‑byte payload.
* After de‑7‑bit‑ifying you get a **16‑bit mask** – **bit‑0 = fret‑1 … bit‑15 =
  fret‑16**.  No gaps, no padding.

### Touch panel

* Always `1 + 5×MAX_TOUCHES = 26` data bytes.
* Byte 0 = number of active touches.  Each touch =
  `x_lo, x_hi, y_lo, y_hi, pressed_bool` (14‑bit coords).

---

## Hacking

Start from the QuadwaveBridge's _handle method.

---

## Dev & Tests

```bash
# run unit tests (hardware‑free)
python -m unittest -v test_quadwave_bridge.py
```

The tests mock all MIDI I/O.

---

## Files

```
quadwave_midi_bridge.py   # runtime bridge (print + pass‑through)
README.md                 # this file
test_quadwave_bridge.py   # offline test‑suite
```

Fork, PR, or issue at will – happy shredding! 🎸
