# Build 10: Breakout (`breakout.intent`)

## 1. What We Built
A multi-level **Breakout / Arkanoid** clone ([`breakout.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-10-breakout/breakout.intent)) with 3-wide multi-hit bricks, directional paddle steering, lookahead bounce physics, and endless level refills, paired with an automated long-horizon bot ([`autopilot.py`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-10-breakout/autopilot.py)).

### Mechanics Implemented in Pure English
- **Multi-cell composite entities without arrays**: Each brick is stored by its left edge `(x, y, toughness)` in the `Bricks` collection and rendered 3 cells wide via offset draw rules (`at its x and its y`, `at its x plus 1 and its y`, `at its x plus 2 and its y`), colored red (`"#"`) when `toughness > 1` and green (`"="`) when `toughness = 1`. Similarly, the 5-wide paddle is drawn from `the paddle minus 2` to `the paddle plus 2`.
- **Lookahead collision & bounce physics**: Each 70ms tick computes `(next x, next y)` first, reflects `(dx, dy)` off walls (`next x < 1`, `next x > 30`, `next y < 1`), checks for any brick spanning `[next x - 2, next x]` at `next y`, decrements brick toughness, removes broken bricks (`toughness < 1`), reflects `dy`, and steers `dx` based on whether the ball hits the left or right half of the paddle.
- **Progressive difficulty across endless levels**: When all bricks are cleared (`if no brick has a y over 0`), `the level increases by 1` and a new wall of bricks spawns whose top rows have `toughness` equal to `the level`.

---

## 2. What Failed First & What We Learned

### Finding 1: Ordering Sub-Steps Within a Single Timer Period
- Intent v0.6.0 executes `Every 70 milliseconds` rules strictly in source order within each tick (`plan.py` / `llvm.py`).
- Because there are no local temporary variables inside a timer block, lookahead collision resolution requires declared single values (`the next x`, `the next y`, `the broke`) that are recomputed after wall reflection so corner bounces don't tunnel into out-of-bounds bricks.
- Similarly, brick hit detection and brick removal must share a single-tick latch (`the broke becomes 1` -> `decrease toughness` -> `remove bricks whose toughness is under 1` -> `if the broke is 1, the dy becomes 0 minus the dy` -> `the broke becomes 0`). If `dy` were flipped before `decrease toughness`, `next y` would no longer match the brick!

### Finding 2: Edge Clipping in ASCII Observation (`autopilot.py`)
- When the 5-wide paddle moves near the left or right wall (`paddle = 29`), cells outside `[1..30]` are clipped by the board renderer, so the bottom row shows `"===="` (4 chars) instead of `"====="` (5 chars).
- Computing the paddle center as the average of all `"="` columns on the bottom row allowed the autopilot to track and steer the ball reliably for hours of simulated play without losing a single life.

---

## 3. Long-Horizon Stress Test (1 Hour of Simulated Play)
Running `python3 gemini-build/build-10-breakout/autopilot.py 60 1` (60 minutes of simulated gameplay):
- **Simulated Duration**: `3,600s` (1 full hour of game time, `51,428` pipe round-trips).
- **Wall-Clock Time**: **`2.06 seconds`** (`~25,000` interactive pipe frames per second!).
- **Progression**: Reached **Level 21** (where upper bricks require 21 hits each to break), **Score 16,966**, **1,226 brick-hit steps**, with **all 3 lives intact**.
- **Deterministic Replay**: Replaying all `76,255` recorded commands in batch mode produced the **100% identical final board** (`identical final board: True`).
