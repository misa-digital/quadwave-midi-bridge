import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

# Module under test
import quadwave_midi_bridge as qwb

# ───────────────────────── helper mini-mocks ──────────────────────────────
class StubMsg(SimpleNamespace):
    """Minimal stand-in for `mido.Message` (only .type & .data)."""

    def __init__(self, type_: str, data):
        super().__init__(type=type_, data=data)


class FakePort:
    def send(self, _):
        pass

    def close(self):
        pass


# ───────────────────────── utility builders ───────────────────────────────
FRET_TO_BIT = qwb.FRET_TO_BIT


def fret_mask(*frets) -> int:
    mask = 0
    for f in frets:
        mask |= 1 << FRET_TO_BIT[f]
    return mask


def encode_mask(mask: int) -> list[int]:
    return [mask >> 14 & 0x7F, mask >> 7 & 0x7F, mask & 0x7F]


def build_neck_sysex(string_masks):
    payload = []
    for m in string_masks:
        payload.extend(encode_mask(m))
    return StubMsg("sysex", qwb.MFG_ID + payload)


def build_touch_sysex(touches):
    """Build a complete 26-byte touch SysEx from an arbitrary touch list.

    The Quadwave firmware always sends 1 + 5*MAX_TOUCHES data bytes, so we pad
    with dummy touches to keep length constant. The first byte still carries the
    *actual* number of touches.
    """
    padded = touches + [{"x": 0, "y": 0, "pressed": False}] * (qwb.MAX_TOUCHES - len(touches))
    pl = [len(touches)]
    for t in padded:
        x, y, pressed = t["x"], t["y"], int(t["pressed"])
        pl.extend([x & 0x7F, x >> 7, y & 0x7F, y >> 7, pressed])
    return StubMsg("sysex", qwb.MFG_ID + pl)


# ──────────────────────────── test case ───────────────────────────────────
class QuadwaveBridgeLogicTest(unittest.TestCase):
    def setUp(self):
        self.p_in = patch("quadwave_midi_bridge.mido.open_input", return_value=FakePort()).start()
        self.p_out = patch("quadwave_midi_bridge.mido.open_output", return_value=FakePort()).start()
        with patch.object(qwb.QuadwaveBridge, "_auto_in", return_value="stub"), patch.object(
            qwb.QuadwaveBridge, "_open_out", return_value=("stub", FakePort())
        ):
            self.bridge = qwb.QuadwaveBridge(None, None)

    def tearDown(self):
        patch.stopall()

    # ----------------- neck tests -----------------
    def test_single_neck_press(self):
        press = build_neck_sysex([fret_mask(1), 0, 0, 0])
        release = build_neck_sysex([0, 0, 0, 0])
        with io.StringIO() as buf, redirect_stdout(buf):
            self.bridge._handle(press)
            self.bridge._handle(release)
            lines = [l.strip() for l in buf.getvalue().splitlines() if l.strip()]
        self.assertEqual(lines, ["String 1 fret 1 ON", "String 1 fret 1 OFF"])

    def test_multi_neck_press_release(self):
        press_masks = [fret_mask(1, 4), fret_mask(6), 0, 0]
        press = build_neck_sysex(press_masks)
        release = build_neck_sysex([0, 0, 0, 0])
        with io.StringIO() as buf, redirect_stdout(buf):
            self.bridge._handle(press)
            self.bridge._handle(release)
            out = {l.strip() for l in buf.getvalue().splitlines() if l.strip()}
        expected = {
            "String 1 fret 1 ON", "String 1 fret 4 ON", "String 2 fret 6 ON",
            "String 1 fret 1 OFF", "String 1 fret 4 OFF", "String 2 fret 6 OFF",
        }
        self.assertEqual(out, expected)

    # ---------------- touch tests ----------------
    def test_touch_press_drag_release(self):
        X0, Y0 = 1000, 2000
        X1, Y1 = 1010, 2020
        press = build_touch_sysex([{"x": X0, "y": Y0, "pressed": True}])
        drag = build_touch_sysex([{"x": X1, "y": Y1, "pressed": True}])
        release = build_touch_sysex([{"x": X1, "y": Y1, "pressed": False}])
        with io.StringIO() as buf, redirect_stdout(buf):
            self.bridge._handle(press)
            self.bridge._handle(drag)
            self.bridge._handle(release)
            lines = [l.strip() for l in buf.getvalue().splitlines() if l.strip()]
        self.assertEqual(lines, [
            f"Touch 0 pressed at x={X0} y={Y0}",
            f"Touch 0 dragged to x={X1} y={Y1}",
            f"Touch 0 released at x={X1} y={Y1}",
        ])

    def test_multi_touch(self):
        press = build_touch_sysex([
            {"x": 500, "y": 600, "pressed": True},
            {"x": 1500, "y": 1600, "pressed": True},
        ])
        drag = build_touch_sysex([
            {"x": 520, "y": 630, "pressed": True},
            {"x": 1520, "y": 1625, "pressed": True},
        ])
        release = build_touch_sysex([
            {"x": 520, "y": 630, "pressed": False},
            {"x": 1520, "y": 1625, "pressed": False},
        ])
        with io.StringIO() as buf, redirect_stdout(buf):
            self.bridge._handle(press)
            self.bridge._handle(drag)
            self.bridge._handle(release)
            out = {l.strip() for l in buf.getvalue().splitlines() if l.strip()}
        expected = {
            "Touch 0 pressed at x=500 y=600", "Touch 1 pressed at x=1500 y=1600",
            "Touch 0 dragged to x=520 y=630", "Touch 1 dragged to x=1520 y=1625",
            "Touch 0 released at x=520 y=630", "Touch 1 released at x=1520 y=1625",
        }
        self.assertEqual(out, expected)


if __name__ == "__main__":
    unittest.main()
