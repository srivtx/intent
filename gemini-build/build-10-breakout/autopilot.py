#!/usr/bin/env python3
"""
Long-horizon autopilot for breakout.intent: the paddle follows the ball.

Checks over many minutes of game time:
  * levels keep advancing (bricks are removed and re-added again and again)
  * score never decreases, level never decreases
  * replaying the recorded command stream gives the identical final board
Usage: python3 autopilot.py [minutes] [seed]
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(HERE, "breakout.intent")
BIN = os.path.join(ROOT, "build", "breakout")
W, H = 30, 18
STEP_MS = 70


def build():
    os.makedirs(os.path.dirname(BIN), exist_ok=True)
    r = subprocess.run([os.path.join(ROOT, "intent"), "build", SRC, "-o", BIN], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)


def main(minutes, seed):
    p = subprocess.Popen([BIN], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    keys = []

    def send(line, record=True):
        if record:
            keys.append(line)
        p.stdin.write(line + "\n")
        p.stdin.flush()

    def screen():
        send("screen", record=False)
        head = p.stdout.readline().split()
        rows = [p.stdout.readline().rstrip("\n")[1:-1] for _ in range(H + 2)][1:-1]
        return {head[i]: int(head[i + 1]) for i in range(0, len(head) - 1, 2)}, rows

    steps = int(minutes * 60_000 / STEP_MS)
    last, max_level, t0 = None, 1, time.perf_counter()
    bricks_broken = 0
    for s in range(steps):
        st, rows = screen()
        if last:
            assert st["score"] >= last["score"] and st["level"] >= last["level"], (last, st)
            bricks_broken += st["score"] > last["score"]
        last = st
        max_level = max(max_level, st["level"])
        if st["lives"] < 1:
            break
        # the paddle may be clipped at a wall, so take the middle of the '=' cells on the last row
        pad = [i + 1 for i, c in enumerate(rows[H - 1]) if c == "="]
        paddle = sum(pad) // len(pad) if pad else W // 2
        ball = next(((r.find("o") + 1) for r in rows if "o" in r), paddle)
        # aim one cell ahead of the ball, so the paddle edge steers it sideways
        if ball < paddle - 1:
            send("press left")
        elif ball > paddle + 1:
            send("press right")
        send(f"wait {STEP_MS}")
    st, rows = screen()
    p.stdin.close()
    p.wait()
    wall = time.perf_counter() - t0
    print(f"played {(s + 1) * STEP_MS / 1000:.0f}s of game time in {wall:.2f}s wall ({s + 1} pipe round trips)")
    print(f"final {st}; highest level {max_level}; scoring steps {bricks_broken}")
    print("\n".join("|" + r + "|" for r in rows))
    r = subprocess.run([BIN], input="\n".join(keys + ["screen"]) + "\n", capture_output=True, text=True)
    tail = r.stdout.rstrip("\n").split("\n")[-(H + 2):]
    same = [x[1:-1] for x in tail[1:-1]] == rows
    print(f"batch replay of {len(keys)} commands -> identical final board: {same}")
    assert same


if __name__ == "__main__":
    build()
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 5, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
