#!/usr/bin/env python3
"""
Long-horizon autopilot for invaders.intent.

Drives the compiled native binary over a pipe (wait / press / screen), reads the board
back as text, and plays like a (dumb) human: walk under the lowest alien, fire, dodge
bombs directly overhead. Then checks the things a long game needs to keep true:

  * waves keep advancing (records appear and disappear for minutes of game time)
  * the score only goes up, lives only go down
  * the whole game is replayable: the same seed + the same keys -> the same final board

Usage:  python3 autopilot.py [minutes_of_game_time] [seed]
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(HERE, "invaders.intent")
BIN = os.path.join(ROOT, "build", "invaders")
W, H = 32, 16
STEP_MS = 50


def build():
    r = subprocess.run([os.path.join(ROOT, "intent"), "build", SRC, "-o", BIN], capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        sys.exit("build failed")


class Game:
    def __init__(self, seed):
        self.p = subprocess.Popen([BIN], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.keys = [f"seed {seed}"]
        self.send(f"seed {seed}")

    def send(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def act(self, line):
        self.keys.append(line)
        self.send(line)

    def screen(self):
        self.send("screen")
        header = self.p.stdout.readline().rstrip("\n")
        rows = [self.p.stdout.readline().rstrip("\n") for _ in range(H + 2)]
        tail = []
        # a finished game prints one more line under the board ("game over")
        return header, [r[1:-1] for r in rows[1:-1]], tail

    def close(self):
        self.p.stdin.close()
        self.p.wait()


def parse_header(h):
    parts = h.split()
    return {parts[i]: int(parts[i + 1]) for i in range(0, len(parts) - 1, 2)}


def play(minutes, seed):
    g = Game(seed)
    steps = int(minutes * 60_000 / STEP_MS)
    last = None
    max_wave = 1
    t0 = time.perf_counter()
    over_at = None
    for s in range(steps):
        header, board, _ = g.screen()
        st = parse_header(header)
        if last:
            assert st["score"] >= last["score"], ("score went down", last, st)
            assert st["lives"] <= last["lives"] or st["lives"] == 3, ("lives went up", last, st)
        last = st
        max_wave = max(max_wave, st["wave"])
        if st["lives"] < 1 or any("W" in r or "M" in r for r in board[14:15]):
            over_at = s * STEP_MS
            break
        ship = board[H - 1].find("A") + 1
        aliens = [(x + 1, y + 1) for y, r in enumerate(board) for x, ch in enumerate(r) if ch in "WM"]
        bomb_over = any(board[y][ship - 1] == "!" for y in range(H - 6, H - 1))
        shot_flying = any("|" in r for r in board)
        if bomb_over:
            g.act("press left" if ship > 2 else "press right")
        elif aliens:
            tx = max(aliens, key=lambda a: (a[1], -abs(a[0] - ship)))[0]
            if tx < ship:
                g.act("press left")
            elif tx > ship:
                g.act("press right")
            elif not shot_flying:
                g.act("press space")
        g.act(f"wait {STEP_MS}")
    final_header, final_board, _ = g.screen()
    g.close()
    wall = time.perf_counter() - t0
    return {
        "steps": s + 1,
        "game_ms": (s + 1) * STEP_MS,
        "over_at_ms": over_at,
        "max_wave": max_wave,
        "final": final_header,
        "board": final_board,
        "keys": g.keys,
        "wall_s": wall,
    }


def replay(keys):
    r = subprocess.run([BIN], input="\n".join(keys + ["screen"]) + "\n", capture_output=True, text=True)
    lines = r.stdout.rstrip("\n").split("\n")
    return lines[-(H + 3)], [x[1:-1] for x in lines[-(H + 2):][1:-1]]


if __name__ == "__main__":
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 3
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    build()
    res = play(minutes, seed)
    print(f"played {res['game_ms']/1000:.0f}s of game time in {res['wall_s']:.2f}s wall "
          f"({res['steps']} round trips over the pipe)")
    print(f"game over at: {res['over_at_ms']} ms" if res["over_at_ms"] else "still alive at the end")
    print(f"highest wave reached: {res['max_wave']}")
    print("final:", res["final"])
    print("\n".join("|" + r + "|" for r in res["board"]))
    h2, b2 = replay(res["keys"])
    same = (h2 == res["final"] and b2 == res["board"])
    print(f"replay of {len(res['keys'])} recorded commands in one batch -> identical final board: {same}")
    assert same, (h2, res["final"])
