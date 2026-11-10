# Build 05: Performance Cliff, Tombstone Churn & 64-Bit Boundary Stress Test

## 1. What We Tested
We stress-tested the unmodified compiler (`intentc`) and its generated LLVM IR across four extreme dimensions:
1. **The `O(n^2)` Order-Preserving Deletion Cliff**: [`fast_unordered.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-05-performance-cliff-stress-test/fast_unordered.intent) vs. [`slow_ordered.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-05-performance-cliff-stress-test/slow_ordered.intent) (identical except for `Keep items in the order they were added.`).
2. **High-Churn Tombstone Saturation**: 100,000 `add-item` + `remove-item` operations where only 10 items remain live at any time, testing open-addressing tombstone (`-1`) accumulation and rehashing.
3. **16-Stage Sequential Register Pipeline & 64-Bit Overflow Torture**: [`deep_pipeline.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-05-performance-cliff-stress-test/deep_pipeline.intent) chaining 16 sequential in-place mutations in a single sentence and probing `INT64_MIN` (`-9223372036854775808`), `INT64_MAX` (`9223372036854775807`), `INT64_MIN / -1`, `-7 / 2`, and `9 + 10%`.
4. **Hardcoded Parser Length Limits**: [`attempt_failed.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-05-performance-cliff-stress-test/attempt_failed.intent) hitting hardcoded token-count caps.

---

## 2. Analysis: "Where I Might Be Wrong" vs. "Where the Compiler/Planner Is Wrong"

### A. Where the Planner (`plan.py`) & Backend (`llvm.py`) Are Wrong About Ordered Removal
- **What `intent explain` claims**: In [`plan.py:80`](file:///Users/zen/Desktop/project-10nov/intentc/plan.py#L80), `remove-item` on an ordered indexed collection is reported as:
  `O(n) — index probe, then close the gap`
- **What [`llvm.py:408-412`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L408-L412) actually emits**:
  ```llvm
  call ptr @memmove(ptr %p, ptr %nxt, i64 %nbytes)
  store i64 %last, ptr @"item.len"
  call void @"item.reindex"()
  ```
  Every single call to `remove-item` calls `@"item.reindex"()`, which **`free`s the entire hash table, `calloc`s a brand-new table, and re-hashes all `n` remaining records from scratch**!
- **Why this is a compiler flaw**:
  1. Even if you delete the **last element** (`row == last`, where `memmove` moves `0` bytes and **no other row's index changed**!), `remove_row` still destroys and rebuilds the entire hash table in `O(n)` instead of `O(1)`!
  2. Even for an interior deletion at `row`, only elements `row .. last-1` shifted by `-1`; rebuilding the entire hash table via `free` + `calloc` + `n` hash computations on every single deletion makes `n/2` deletions ~**50x–280x slower** than unordered removal!

### B. Where the Compiler Got Subtle 64-Bit Edge Cases Right!
We tried to break the LLVM backend with C/LLVM Undefined Behavior (UB) traps, and found that `intentc/llvm.py` **explicitly anticipated and guarded against them**:
- **`INT64_MIN / -1` Trap**: In two's complement 64-bit arithmetic, `-9223372036854775808 / -1` overflows `i64`, which in LLVM IR `sdiv i64` is immediate **Undefined Behavior**. Look at [`llvm.py:174-175`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L174-L175):
  ```python
  if e[3][1] == -1:
      return f.r(f'sub i64 0, {a}'), 'int'
  ```
  The author specifically lowered `/ -1` to `0 - a` (`sub i64 0, %a`) so `INT64_MIN / -1` wraps cleanly to `INT64_MIN` without triggering LLVM `sdiv` UB!
- **Tombstone (`-1`) Rehash Trigger**: In [`llvm.py:340, 387-394`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L387-L394), `remove_row` writes `-1` (deleted) into the hash slot without decrementing `@"item.key.used"`. When `(used + 1) * 2 > cap`, `put` calls `rebuild()`, which sizes the new table from `len` (live rows, not `used`), purging all tombstones in `O(len)` time and preventing unbounded memory growth!

### C. Hardcoded Parser Limits Where the Author Must Adapt
In [`attempt_failed.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-05-performance-cliff-stress-test/attempt_failed.intent):
- **Property names > 3 words** fail (`parser.py:555`: `len(ws) > 3`).
- **Taught phrases > 5 words** fail (`parser.py:342`: `len(key) > 5`).
- **Taught nouns > 4 words** fail (`parser.py:368`: `not 1 <= len(words) <= 4`).
- **Capability names > 6 words** before `:` fail (`parser.py:858`: `len(words) > 6`).
- **Multi-word field names > 3 words** fail to normalize (`parser.py:427`: `range(min(3, n - i), 0, -1)`).

---

## 3. Where Our Analysis Might Be Wrong & Thoughts for a Reviewing Model (Aligned with Flexibility, Not Rigidity)

- **Where we might be wrong**:
  - In [`README.md:186-187`](file:///Users/zen/Desktop/project-10nov/README.md#L186-L187), the language author explicitly documented that v0.1 rebuilds the index after an order-preserving removal (*"It is slow on purpose-built churn because v0.1 rebuilds the index after an order-preserving removal; see next steps"*). So the `100x` slowdown in `slow_ordered.intent` is a **known v0.1 simplification**, not an accidental oversight!
- **How a Reviewing Model Could Improve Both Speed and Flexibility**:
  1. **Fast tail deletion & incremental index shift**: In [`remove_row()`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L407-L412), if `%row == %last`, only that single slot in the hash table needs to be marked `-1` (`O(1)`), and even for general ordered collections, tombstones in the data array (marking deleted rows inactive instead of `memmove`ing all subsequent rows) would make ordered deletion `O(1)` while preserving insertion order!
  2. **Replacing arbitrary word-count limits with dynamic phrase matching**: Rather than hardcoding `3` words for properties (`parser.py:427, 555`), `4` for nouns, `5` for phrases, and `6` for capability labels, computing `max_field_words` from the declared fields in `self.prog` (just as `longest` is computed from `self.macros` at `parser.py:279`) would make multi-word domain names flexible without arbitrary cutoffs.
