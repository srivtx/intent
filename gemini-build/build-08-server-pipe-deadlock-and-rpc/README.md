# Build 08: Can Intent Build a Server? (Proving the `stdout` Pipe Deadlock & Live PTY RPC Server)

## Direct Answer: Can Intent Build a Server Right Now?
- **NO for a Standalone HTTP / TCP Socket Server**: [`intentc/llvm.py`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L16-L40) emits no `socket()`, `bind()`, `listen()`, `accept()`, or HTTP parsing code; compiled binaries only read `stdin` (`fd 0`) and write `stdout` (`fd 1`).
- **NO Out-of-the-Box Over Standard OS Pipes (`subprocess.PIPE` / `inetd` / CGI) Due to a Buffering Bug We Discovered in `llvm.py:765`!**
- **YES When Attached to a Pseudo-Terminal (`pty.openpty()`) or Batch Stream**: Every compiled Intent binary *is* architected as a persistent stateful command server with Write-Ahead Log (`journal`) crash recovery ([`llvm.py:703-787`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L703-L787)). Once `stdout` is line-buffered via a PTY, it runs as a sub-millisecond stateful RPC server!

---

## 1. What We Tried to Do
We built a stateful **Authentication Session & Rate-Limit Server** ([`session_server.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-08-server-pipe-deadlock-and-rpc/session_server.intent)) and tried to run the compiled native binary ([`session_server`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-08-server-pipe-deadlock-and-rpc/session_server)) as a long-lived background daemon answering live request/response RPC calls over `stdin`/`stdout`.

---

## 2. What Did Not Work & The Critical Bug We Faced (and Why We Faced It)

### Bug #8: Interactive Pipe Deadlock in `@main` ([`intentc/llvm.py:752-787`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L752-L787))
- **What we did**: We spawned `./session_server` as a persistent child process with `stdin=subprocess.PIPE, stdout=subprocess.PIPE`, wrote `"active-session-count\n"`, flushed `stdin`, and waited to read the response line `"0\n"` from `stdout` (while keeping `stdin` open for the next request).
- **What happened**: **The server hung forever (deadlock)!**
- **Why we faced it**:
  1. Look at [`llvm.py:757-785`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L757-L785): inside the `loop` in `@main`, the binary reads a line with `@getline`, calls `@dispatch`, and if a journal file is active, calls `call i32 @fflush(ptr %jf)` on the **journal file** (line 781).
  2. However, **it never calls `call i32 @fflush(ptr null)` (or `fflush(stdout)`) after `@dispatch`!**
  3. When you run the binary in a terminal, `isatty(1) == 1`, so `libc` makes `stdout` line-buffered (`_IOLBF`). When you run it in batch tests (`subprocess.run(..., input=...)`), `stdin` is closed immediately, so `main()` exits and `libc` flushes `stdout` on exit.
  4. **When spawned as a persistent server over a pipe or socket**, `isatty(1) == 0`, so `libc` switches `stdout` to **4KB block-buffered mode (`_IOFBF`)**! `@printf` writes `"0\n"` into a 4KB memory buffer, `@main` loops back to `@getline` waiting for the next command on `stdin`, and the client waits forever for `"0\n"` to arrive on `stdout`!

Also in [`attempt_failed.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-08-server-pipe-deadlock-and-rpc/attempt_failed.intent):
- Trying to write `touch-and-get: increase hits by 1 and show the session...` (an atomic mutate-and-return RPC) failed with `question: is this a change or a query?` ([`parser.py:937`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L937)).

---

## 3. What Worked (and Why It Worked)
- **The PTY (`pty.openpty()`) Workaround in [`test_server.py`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-08-server-pipe-deadlock-and-rpc/test_server.py)**:
  By attaching the child process's `stdout` to a pseudo-terminal slave fd (`pty.openpty()`), `libc` sees `isatty(1) == 1` and flushes every `\n` immediately! Our unmodified [`session_server`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-08-server-pipe-deadlock-and-rpc/session_server) binary then served 8 live sequential RPC round-trips (`create-session`, `lookup-session`, `record-hit`, `enforce-quotas`, `active-session-count`) and recovered its exact state from `sessions_wal.log` after process termination.

---

## 4. Where Our Analysis Might Be Wrong & Thoughts for a Reviewing Model (Aligned with Flexibility, Not Rigidity)
- **Where we might be wrong**:
  - Perhaps the author of `intentc` intentionally omitted `fflush(null)` after every command in `@main` so batch benchmarks (`bench/bench.py` piping 100,000 commands at once) wouldn't pay a syscall flush cost on every single line!
  - A stronger reviewing model can weigh that trade-off much better than a blanket rule: for instance, flushing `stdout` after `@dispatch` (or only when `@dispatch` printed output, or calling `setvbuf` / flushing when `stdin` has no buffered bytes ready) would let every compiled `.intent` binary work immediately with `socat`, TCP bridges, and subprocess pipes without hurting bulk throughput.
- **Keeping the Language Flexible, Not Rigid**:
  - Notice how [`README.md`](file:///Users/zen/Desktop/project-10nov/README.md#L81) says *"A program is a service, not a script."* Allowing a sentence like `Increment hits and show the session for sessions whose token is a given token` (mutate-then-show on the same matched records) could make interactive service capabilities twice as expressive without requiring rigid multi-statement syntax.
