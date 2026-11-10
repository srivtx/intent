# Build 09: Space Invaders (`invaders.intent`)

## 1. What We Built
A multi-wave **Space Invaders** game ([`invaders.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-09-invaders/invaders.intent)) compiled to native machine code by Intent v0.6.0, paired with an automated long-horizon bot ([`autopilot.py`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-09-invaders/autopilot.py)) that plays through multiple waves via Unix pipes (`wait <ms>`, `press <key>`, `screen`) and verifies 100% deterministic batch replay.

### Mechanics Implemented in Pure English
- **Marching alien formation (`Aliens` collection)**: 10 starting invaders across two rows (`kind 1` magenta `"W"`, `kind 2` cyan `"M"`) march horizontally (`Every 400 milliseconds, the x of each alien increases by the march.`).
- **Edge detection, direction reversal & descent**: When any alien reaches `x > 31` or `x < 2`, a latch (`the descend becomes 1`) reverses `the march` (`0 minus the march`) and drops every alien down one row (`increase the y of every alien by 1`).
- **Enemy bombs (`Bombs` collection)**: Random bombs spawn every 900ms (`a random number between 1 and 32`), plus targeted aimed bombs (`whose x is the ship`) starting in Wave 3.
- **Wave progression**: When all aliens are cleared (`if no alien has a y over 0`), `the wave increases by 1`, a new fleet spawns, and hit points scale with `10 times the wave`.

---

## 2. What Failed First & What We Learned (Notes for the Language Maintainer)

### Finding 1: No Cross-Collection Joins in Event Conditions (`other_cond`)
- **What we tried first**: Modeling both player shots (`Shots`) and aliens (`Aliens`) as collections so the player could fire rapid-fire volleys:
  ```intent
  Every 60 milliseconds, if any shot has an x equal to an alien's x and a y equal to an alien's y, ...
  ```
- **What happened**: Rejected by [`intentc/parser.py:785, 796-798`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L785) with:
  ```text
  error: a condition can look into one other collection in this version
  ```
  Even when an `update`/`remove` sentence is already scoped to `Aliens`, its `if any shot has ...` clause is parsed by `other_cond`, which forbids referencing fields of the outer collection (`Aliens`) inside the inner quantified condition.
- **Workaround**: Represent the active player projectile as scalar single values (`the shot x`, `the shot y`, where `shot y = 0` means no shot in flight). Because `Aliens` and `Bombs` are only ever compared against single values, both collision checks (`if any alien has an x equal to the shot x and a y equal to the shot y`) compile cleanly.
- **Hypothesis for Maintainer**: Allowing `other_cond` to bind outer collection fields (e.g., `remove the aliens where any shot has an x equal to its x and a y equal to its y`) would unlock many-to-many entity collisions (multi-bullet shooters, particle collisions).

### Finding 2: Word-Order Asymmetry on Conditional `remove` in Timer Events
- **What we tried first**:
  ```intent
  Every 150 milliseconds, if the hurt is 1, remove the bombs whose y is at least 14.
  ```
- **What happened**: Rejected with:
  ```text
  error: I don't see how "whose y is at least 14" fits in
  ```
  When a timer sentence starts with `if <single-value condition>, remove the <coll> whose ...`, the parser consumes the leading `if` as the `where` separator and fails when it encounters a second filter (`whose ...`).
- **Workaround**: Put the `if` condition **after** the `whose` clause:
  ```intent
  Every 150 milliseconds, remove the bombs whose y is at least 14 if the hurt is 1.
  ```

---

## 3. Long-Horizon Verification Results
Running [`autopilot.py`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-09-invaders/autopilot.py):
- **Interactive Pipe Mode**: `1,558` pipe round-trips (`78s` simulated game time) completed in **`0.39s` wall time** (`~4,000 ticks/sec`), clearing multiple alien waves and reaching **Wave 4, Score 460**.
- **Deterministic Batch Replay**: Replaying all `1,960` recorded commands (`seed`, `press`, `wait`) in one batch produced the **exact same final board and state** (`identical final board: True`).
