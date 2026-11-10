# Build 02: Branchless Collatz (`3n+1`) Automaton, 2D Particle Physics & 64-Bit Register ALU

## 1. What We Tried to Build
We wanted to see if Intent—which on the surface looks like a simple CRUD/query language—can execute **stateful mathematical automata, branching algorithms, and physical simulations**:
1. **Collatz (`3n + 1`) Hailstone Parity Engine**: Requires testing whether `val` is even or odd (`val % 2`), branching (`val / 2` vs `3 * val + 1`), counting stopping times, and tracking `max(peak, val)` across trajectories (such as seed `27`, which takes **111 steps** and climbs to **9,232** before converging to `1`).
2. **2D Rigid-Body / Elastic Particle Simulator**: Integrates velocity and position under gravity (`g = 10`) and 1% drag, computes Kinetic Energy (`ke = m * (vx^2 + vy^2) / 2`), Potential Energy (`pe = m * g * py`), and total Hamiltonian energy, and reflects particles off the floor (`py < 0` with 80% restitution) and walls (`px < -1000`, `px > 1000`).
3. **64-Bit Fibonacci Register Machine**: Computes exact 64-bit Fibonacci numbers up to `F(91) = 4,660,046,610,375,530,309` in-place.

## 2. Files in This Build Folder
- [`attempt_failed.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-02-collatz-and-physics-alu/attempt_failed.intent) — Our first attempt using `%`, `modulo`, variable division (`10000 / val`), and `while`, which fails to compile.
- [`attempt_failed_output.txt`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-02-collatz-and-physics-alu/attempt_failed_output.txt) — Exact compiler diagnostics for the failed attempt.
- [`physics_alu.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-02-collatz-and-physics-alu/physics_alu.intent) — The working specification using integer-truncation parity and branchless sequential register updates.
- [`plan_explanation.txt`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-02-collatz-and-physics-alu/plan_explanation.txt) — Output of `./intent explain physics_alu.intent`.
- [`test_physics_alu.py`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-02-collatz-and-physics-alu/test_physics_alu.py) — Compiles `physics_alu` to native code and verifies `Collatz(27) -> 111 steps, peak 9232`, `Fibonacci(91) -> 4660046610375530309`, and 100 physics ticks against the reference interpreter.

---

## 3. Failure Analysis: "Where I Was Wrong" vs. "Where the Language/Compiler Was Wrong"

### A. Where I (the Programmer) Was Wrong (And How Algebraic Rewriting Solved It!)
1. **Assuming `%` Means Modulo**
   - **What I wrote**: `show the stones whose val % 2 is 0.`
   - **Why I was wrong**: In [`lexicon.py`](file:///Users/zen/Desktop/project-10nov/intentc/lexicon.py#L156), `%` is mapped to `('PCT', None)` (percentage change, as in `increase salary by 10%`), not C/Python modulo!
   - **How I fixed my code in `physics_alu.intent`**: Because Intent's whole-number division `/` truncates toward zero (`7 / 2 == 3`), **`(val / 2) * 2` equals `val` if and only if `val` is even**, and `rem = val - (val / 2) * 2` evaluates to `0` (even) or `1` (odd)!
     - Even filter: `An even stone is a stone whose val is (val / 2) * 2 and val is over 1.`
     - Odd filter: `An odd stone is a stone whose val is not (val / 2) * 2 and val is over 1.`
2. **Assuming We Need `if / else` to Branch Between Even and Odd Updates**
   - **Why I was wrong**: Because multiple assignments in a single `update` sentence (`set A to ..., then set B to ...`) execute **sequentially in-place on the record** in both [`llvm.py`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L542-L548) and [`interp.py`](file:///Users/zen/Desktop/project-10nov/intentc/interp.py#L133-L134), a field on the record (`rem` or `scratch`) acts as a mutable CPU register!
   - **How I fixed my code**: We wrote a single branchless sentence that steps both even and odd numbers simultaneously in one pass:
     ```text
     step-collatz: for every active stone, set rem to val - (val / 2) * 2, then set val to (1 - rem) * (val / 2) + rem * (val * 3 + 1), then increase steps by 1.
     ```

### B. Where the Language / Compiler (`intentc`) Is Missing Core Capabilities
1. **No Unbounded Iteration (`while` / `until` / Recursion)**
   - Every capability in Intent executes **one bounded linear scan (`O(n)`)** over a collection. You cannot express *"repeat `step-collatz` until `active-stone-count` is 0"* inside the `.intent` file; an external driver must send `step-collatz` 111 times on `stdin`.
2. **No Division or Modulo by Runtime Variables (`target / guess`)**
   - Algorithms like Newton-Raphson (`guess = (guess + target / guess) / 2`) or Euclidean GCD (`a, b = b, a % b`) are impossible to express because [`check.py`](file:///Users/zen/Desktop/project-10nov/intentc/check.py#L148-L151) rejects any division where the divisor is not a non-zero integer literal (`e[3][0] != 'num'`).
3. **No Pairwise Record Interactions (`N`-Body Gravity / Particle-Particle Collisions)**
   - `Particles` can bounce off fixed walls (`py < 0`, `px < -1000`) because each particle is updated independently (`O(n)`). However, computing gravitational attraction or collisions *between* Particle `i` and Particle `j` requires a self-join (`O(n^2)` nested loop over `Particles`), which Intent's single-row-at-a-time `rows()` loop generator in [`llvm.py`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L139-L153) cannot represent.

---

## 4. Where Our Analysis Might Be Wrong & Thoughts for a Reviewing Model (Aligned with Flexibility, Not Rigidity)

- **Why what worked actually worked**:
  - Even without `if/else` or `%`, Intent's expression grammar in [`parse_expr()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L608-L656) supports arbitrary parenthesized arithmetic on 64-bit integers, and [`parse_term()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L731) allows full expressions on the right-hand side of comparisons (`whose val is (val / 2) * 2`). Combined with sequential field updates, any bounded-degree polynomial or branchless arithmetic step compiles straight to native LLVM registers.
- **Where our approach might be wrong (for a stronger reviewing model to evaluate)**:
  - Writing `set rem to val - (val / 2) * 2, then set val to (1 - rem) * (val / 2) + rem * (val * 3 + 1)` is a clever mathematical trick, **but it violates the spirit of Intent**, which is that you should write *what you mean in plain English* (`If val is even, halve val; otherwise set val to val * 3 + 1`), not obscure C-style branchless bit-hacks!
- **Flexible Hypotheses for a Reviewing Model**:
  - Instead of forcing users to write algebraic tricks for parity or remainders, natural phrases like `"remainder of X divided by Y"`, `"modulo"`, `"even"` (`divisible by 2`), and `"odd"` could map directly to LLVM `srem i64` in [`lexicon.py`](file:///Users/zen/Desktop/project-10nov/intentc/lexicon.py) and [`llvm.py`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py).
  - For runtime division/modulo by a variable (`target / guess`), rather than rigidly banning all variable divisors in [`check.py:148`](file:///Users/zen/Desktop/project-10nov/intentc/check.py#L148), a stronger model could explore asking the programmer a compiler `question` (just like duplicate policies!): *"What should happen if `guess` is 0? (e.g. 'If guess is 0, reject it.' or guard with `whose guess is not 0`)"*—preserving safety and determinism while keeping the language flexible!
