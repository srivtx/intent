# `gemini-build`: Stress-Testing Intent Across 8 Ambitious Builds (Without Touching `intentc`)

This directory contains **8 self-contained experiment folders** pushing the unmodified Intent compiler ([`intentc/`](file:///Users/zen/Desktop/project-10nov/intentc)) to its limits. Each folder contains:
1. **`attempt_failed.intent` + `attempt_failed_output.txt`** — What we tried first that failed to compile, and why.
2. **The working `.intent` specification + compiled native LLVM binary + `.ll` IR + `plan_explanation.txt`**.
3. **An automated verification & stress test (`test_*.py`)** verifying native LLVM execution against [`Machine`](file:///Users/zen/Desktop/project-10nov/intentc/interp.py#L65-L168).
4. **`README.md` with explicit root-cause analysis, epistemic humility (*"where we might be wrong"*), and flexible (non-rigid) design hypotheses** for a stronger reviewing model.

## Run All 8 Suites
```bash
python3 gemini-build/run_all.py
```

---

## Can Intent Build Graphics or Servers Currently? (Direct YES / NO)

1. **Can we build Graphics / Visual programs currently?**
   - **Windowed / Interactive GPU Graphics (`OpenGL`, `Metal`, `SDL`, `HTML Canvas`)**: **NO** — [`llvm.py`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L16-L40) only links 24 standard `libc` text/memory functions (`getline`, `printf`, `malloc`, `qsort`, etc.) with no FFI, windowing syscalls, or floating-point types.
   - **Offline Software Rendering (Fractals, Raycasting, Netpbm `.ppm` Images & ASCII Framebuffers)**: **YES** — Proven in **[`build-07-graphics-mandelbrot-and-raytracer/`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-07-graphics-mandelbrot-and-raytracer/README.md)**, where pure `.intent` code compiled to native LLVM IR renders both a **48×21 Mandelbrot Set Fractal** ([`mandelbrot.ppm`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-07-graphics-mandelbrot-and-raytracer/mandelbrot.ppm)) and a **41×21 3D Lambertian-Shaded Sphere** ([`sphere.ppm`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-07-graphics-mandelbrot-and-raytracer/sphere.ppm)) using fixed-point integer math and 2nd-order Taylor polynomial normals!
2. **Can we build Servers currently?**
   - **Standalone HTTP / TCP Socket Server**: **NO** — `llvm.py` has no `socket()`, `bind()`, `listen()`, or `accept()`.
   - **Pipe-Driven Daemon (`subprocess.PIPE` / `inetd`)**: **NO out-of-the-box due to Bug #8** discovered in **[`build-08-server-pipe-deadlock-and-rpc/`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-08-server-pipe-deadlock-and-rpc/README.md)**: `@main` in [`llvm.py:765`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L765) never calls `fflush(stdout)` after `@dispatch`, so `libc` block-buffers `stdout` (4KB) when connected to a pipe, causing interactive request/response RPC to **deadlock**!
   - **PTY-Backed (`pty.openpty()`) Stateful RPC Microservice**: **YES** — Proven in **[`build-08-server-pipe-deadlock-and-rpc/test_server.py`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-08-server-pipe-deadlock-and-rpc/test_server.py)**, where attaching `stdout` to a pseudo-terminal forces line-buffering (`_IOLBF`) and turns the unmodified `.intent` binary into a live interactive session & rate-limiting RPC server with Write-Ahead Log (`sessions_wal.log`) crash recovery.

---

## Directory of All 8 Experiment Folders

| Folder | Experiment | What Worked | What Failed / Bugs Found |
|---|---|---|---|
| [`build-01-nexus-exchange/`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-01-nexus-exchange/README.md) | **5-Collection Financial Exchange, Margin Risk & Audit Engine** | 48 compiled commands across 5 collections running at **~759,000 ops/sec**; sequential in-place mark-to-market & basis-points margin math. | `"order by"` `SORTBY` lexicon collision hiding `Orders` collection; foreign-key field `trader` shadowing `Traders` collection; hyphenated label macro expansion bug. |
| [`build-02-collatz-and-physics-alu/`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-02-collatz-and-physics-alu/README.md) | **Branchless Collatz (`3n+1`) Automaton, 2D Physics & 64-Bit Fibonacci ALU** | Solved even/odd parity without `%` via `rem = val - (val / 2) * 2` and branchless update; verified `Collatz(27) -> 111 steps, peak 9,232` and `Fibonacci(91)`. | `%` is tokenized as `PCT` ("percent"), not modulo; no variable division (`target / guess`); no `while` loops or `O(n^2)` pairwise particle collisions. |
| [`build-03-relational-join-and-transactions/`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-03-relational-join-and-transactions/README.md) | **Two-Phase Wallet Ledger & Guarded Inventory Service** | Guarded `WHERE` clauses (`whose balance is at least a given amount`) prevent negative balances/stock within one collection. | Cross-collection joins forbidden; `update` prints 0 lines whether 1 row or 0 rows matched (silent guard failure); taught phrases with bare `is` fail without `whose`. |
| [`build-04-compiler-bug-hunt/`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-04-compiler-bug-hunt/README.md) | **7 Compiler & Runtime Bug Reproducers** | Deterministic reproducer suite comparing `intent check`, `intent run`, and `intent build`. | Proves `not between A and B` violates De Morgan's Law (`age < 18 and age <= 30`), missing 1st text arg coerced to `""`, and failed commands logged to WAL journal. |
| [`build-05-performance-cliff-stress-test/`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-05-performance-cliff-stress-test/README.md) | **Order-Preserving `reindex` Cliff, Tombstone Churn & 64-Bit Torture** | Unordered hash index achieves **1.68M ops/sec**; 100k tombstone churn achieves **2.86M ops/sec**; `INT64_MIN / -1` safely lowered to `0 - a`. | Adding `Keep items in the order they were added` makes workload **100x slower** because `remove_row` frees & rebuilds the entire hash table on every deletion. |
| [`build-06-observability-timeseries-db/`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-06-observability-timeseries-db/README.md) | **IntentTSDB — Real-Time Telemetry & Sliding Window DB** | Materialized `compute_load` and `anomaly_score` columns + sliding window retention (`keep samples whose ts_epoch >= cutoff`) at **~917k ops/sec**. | `"contains"` is mapped to `HAS` → `WHERE` → `AND`, turning `whose message contains "timeout"` into `whose message AND "timeout"`; no `GROUP BY` or `SUM(a * b)`. |
| [`build-07-graphics-mandelbrot-and-raytracer/`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-07-graphics-mandelbrot-and-raytracer/README.md) | **Visual Graphics: 2D Mandelbrot Fractal & 3D Sphere Raycaster** | Renders `mandelbrot.ppm` (`48x21`) and `sphere.ppm` (`41x21`) + ASCII previews in native LLVM IR via fixed-point math and Taylor polynomial normals. | No floats; LHS of `WHERE` comparison (`whose zx2 + zy2 is over 4000`) fails in `parse_term` even though RHS (`whose zx2 is over 4000 - zy2`) works. |
| [`build-08-server-pipe-deadlock-and-rpc/`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-08-server-pipe-deadlock-and-rpc/README.md) | **Stateful Session Server, Pipe Deadlock Proof & PTY RPC Fix** | Live interactive RPC server with sub-millisecond round-trips over `pty.openpty()` + full crash recovery via `sessions_wal.log`. | **Bug #8**: `@main` in `llvm.py:765` never flushes `stdout` after `@dispatch`, causing standard `subprocess.PIPE` interactive servers to deadlock! |
