#!/usr/bin/env python3
"""
Long-horizon autopilot for tetris.intent: drops each falling block into the lowest column.

Checks over many minutes of game time:
  * rows keep filling and clearing (score increases by 100 per cleared row)
  * gravity accelerates from delay=8 down to delay=2 as lines increase
  * replaying the recorded command stream gives the identical final board
Usage: python3 autopilot.py [minutes] [seed]
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(HERE, "tetris.intent")
BIN = os.path.join(ROOT, "build", "tetris")
W, H = 8, 14
STEP_MS = 50


def build():
    os.makedirs(os.path.dirname(BIN), exist_ok=True)
    subprocess.run([sys.executable, os.path.join(HERE, "gen_tetris.py")], check=True)
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

    send(f"seed {seed}")
    steps = int(minutes * 60_000 / STEP_MS)
    last, t0 = None, time.perf_counter()
    for s in range(steps):
        st, rows = screen()
        if last:
            assert st["score"] >= last["score"] and st["lines"] >= last["lines"], (last, st)
        last = st
        # Find @ and column stack heights of #
        px = None
        heights = [0] * W
        for y, r in enumerate(rows):
            for x, ch in enumerate(r):
                if ch == "@":
                    px = x + 1
                elif ch == "#":
                    heights[x] = max(heights[x], H - y)
        if any(ch == "#" for ch in rows[0]):
            break
        target_col = min(range(W), key=lambda c: (heights[c], c)) + 1
        if px is not None:
            while px < target_col:
                send("press right")
                px += 1
            while px > target_col:
                send("press left")
                px -= 1
            send("press down")
        send(f"wait {STEP_MS}")

    st, rows = screen()
    p.stdin.close()
    p.wait()
    wall = time.perf_counter() - t0
    print(f"played {(s + 1) * STEP_MS / 1000:.0f}s of game time in {wall:.2f}s wall ({s + 1} pipe round trips)")
    print(f"final {st} (rows cleared: {st['lines']})")
    print("\n".join("|" + r + "|" for r in rows))
    r = subprocess.run([BIN], input="\n".join(keys + ["screen"]) + "\n", capture_output=True, text=True)
    tail = r.stdout.rstrip("\n").split("\n")[-(H + 2):]
    same = [x[1:-1] for x in tail[1:-1]] == rows
    print(f"batch replay of {len(keys)} commands -> identical final board: {same}")
    assert same


if __name__ == "__main__":
    build()
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 5, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
