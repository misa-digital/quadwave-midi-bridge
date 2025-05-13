#!/usr/bin/env python3
"""
Quadwave MIDI Bridge
====================
"""
from __future__ import annotations

import argparse
import platform
import signal
import sys
import time
from typing import Dict, List, Tuple

import mido

MFG_ID = [0x00, 0x22, 0x0A]
NUM_STRINGS, MAX_TOUCHES = 4, 5   # Quadwave sends max 5 touches
WIN = platform.system() == "Windows"

# ───────────────── neck bit ↔ fret maps ────────────────────
VALID_BITS = range(16)  # bit-0 → fret-1 … bit-15 → fret-16
BIT_TO_FRET = {b: b + 1 for b in VALID_BITS}
FRET_TO_BIT = {f: f - 1 for f in range(1, 17)}

# ───────────────── helper ─────────────────────────────────

def _dump_ports() -> str:
    ins = "\n  - ".join(mido.get_input_names()) or "<none>"
    outs = "\n  - ".join(mido.get_output_names()) or "<none>"
    return f"\nINPUTS:\n  - {ins}\n\nOUTPUTS:\n  - {outs}\n"

# ───────────────── state classes ──────────────────────────
class NeckState:
    def __init__(self):
        self.prev = [0] * NUM_STRINGS
        self.curr = [0] * NUM_STRINGS

    def update(self, payload: List[int]):
        self.prev = self.curr[:]
        self.curr = []
        for i in range(0, 12, 3):
            b0, b1, b2 = payload[i], payload[i + 1], payload[i + 2]
            self.curr.append((b0 << 14) | (b1 << 7) | b2)

    def events(self) -> List[Tuple[int, int, bool]]:
        ev = []
        for sidx, (p, c) in enumerate(zip(self.prev, self.curr)):
            diff = p ^ c
            for bit in VALID_BITS:
                if diff & (1 << bit):
                    ev.append((sidx, BIT_TO_FRET[bit], bool(c & (1 << bit))))
        return ev


class TouchState:
    def __init__(self):
        self.prev: List[Dict[str, int | bool]] = []
        self.curr: List[Dict[str, int | bool]] = []

    def update(self, payload: List[int]):
        self.prev = self.curr
        nt = MAX_TOUCHES
        touches = []
        idx = 1
        for _ in range(nt):
            if idx + 6 > len(payload):
                break
            x_lo, x_hi, y_lo, y_hi, z, pressed = payload[idx : idx + 6]
            touches.append({
                "x": (x_hi << 7) | x_lo,
                "y": (y_hi << 7) | y_lo,
                "z": z,
                "pressed": bool(pressed),
            })
            idx += 6
        self.curr = touches

    def events(self):
        """Yield (tid, x, y, kind) where kind∈{pressed,released,drag}."""
        ev = []
        maxn = max(len(self.prev), len(self.curr))
        for tid in range(maxn):
            prev = self.prev[tid] if tid < len(self.prev) else {"x":0,"y":0,"z":0,"pressed":False}
            curr = self.curr[tid] if tid < len(self.curr) else {"x":0,"y":0,"z":0,"pressed":False}
            if not prev["pressed"] and curr["pressed"]:
                ev.append((tid, curr["x"], curr["y"], curr["z"], "pressed"))
            elif prev["pressed"] and not curr["pressed"]:
                ev.append((tid, curr["x"], curr["y"], curr["z"], "released"))
            elif prev["pressed"] and curr["pressed"] and ((prev["x"]!=curr["x"]) or (prev["y"]!=curr["y"])):
                ev.append((tid, curr["x"], curr["y"], curr["z"], "drag"))
        return ev

# ───────────────── bridge ─────────────────────────────────
class QuadwaveBridge:
    def __init__(self, in_port: str | None, out_port: str | None):
        self.in_name = in_port or self._auto_in()
        self.out_name, self.outport = self._open_out(out_port)
        self.inport = mido.open_input(self.in_name, callback=self._handle)
        self.neck, self.touch = NeckState(), TouchState()
        print(f"[Bridge] 🚀 '{self.in_name}' → '{self.out_name}'. Ctrl-C to quit.")

    # -------- port helpers --------
    @staticmethod
    def _auto_in():
        for n in mido.get_input_names():
            if any(k in n.lower() for k in ("Misa Quadwave")):
                return n
        raise RuntimeError("Quadwave input not found" + _dump_ports())

    def _open_out(self, requested):
        outs = mido.get_output_names()
        def _try(name):
            try:
                return name, mido.open_output(name)
            except (OSError, IOError):
                return None
        if requested:
            exact = _try(requested)
            if exact: return exact
            cand = next((n for n in outs if requested.lower() in n.lower()), None)
            if cand: return _try(cand)
            raise RuntimeError("No such out port" + _dump_ports())
        if not WIN:
            return "Quadwave Bridge", mido.open_output("Quadwave Bridge", virtual=True)
        loop = next((n for n in outs if "loop" in n.lower()), None)
        if loop: return loop, mido.open_output(loop)
        raise RuntimeError("Need loopMIDI port" + _dump_ports())

    # -------- run loop --------
    def run(self):
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("[Bridge] 👋 Bye")
        finally:
            self.inport.close(); self.outport.close()

    # -------- handler --------
    # Start hacking here!
    def _handle(self, msg):
        if msg.type != "sysex": # Pass-through any MIDI from the Quadwave
            self.outport.send(msg); return
        data = list(msg.data)
        if data[:3] != MFG_ID:
            self.outport.send(msg); return
        msg_id = data[3]
        payload = data[4:]
        if msg_id == 0x01: # Handle Neck event
            self.neck.update(payload)
            for s, fret, on in self.neck.events():
                print(f"String {s+1} fret {fret} {'ON' if on else 'OFF'}")
        elif msg_id == 0x02: # Handle Touchpad event
            self.touch.update(payload)
            for tid, x, y, z, kind in self.touch.events():
                if kind == "pressed":
                    print(f"Touch {tid} pressed at x={x} y={y} z={z}")
                elif kind == "released":
                    print(f"Touch {tid} released at x={x} y={y} z={z}")
                elif kind == "drag":
                    print(f"Touch {tid} dragged to x={x} y={y} z={z}")
        elif msg_id == 0x03: # Handle Configuration Change event (5 presses on touchpad)
            colors = ['blue', 'green', 'purple']
            config_id = payload[0]
            print(f"Config set to {colors[config_id]}")
            print(f"Firmware version: {payload[1]}.{payload[2]}.{payload[3]}")

# ───────────────── CLI ─────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(description="Quadwave SysEx → debug prints + MIDI passthrough")
    p.add_argument("--in-port"); p.add_argument("--out-port"); p.add_argument("--list-ports", action="store_true")
    args = p.parse_args(argv)
    if args.list_ports:
        print(_dump_ports()); sys.exit(0)
    bridge = QuadwaveBridge(args.in_port, args.out_port)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    bridge.run()

if __name__ == "__main__":
    main()
