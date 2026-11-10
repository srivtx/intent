# Build 06: IntentTSDB — Real-Time Time-Series, Sliding Window & Anomaly Detection Engine

## 1. What We Tried to Build
A Prometheus/Datadog-style **Observability & Time-Series Telemetry Engine** (`Samples`, `Hosts`, `Incidents`) supporting:
- High-throughput metric ingestion (`cpu_pct`, `mem_mb`, `latency_ms`, `error_count`),
- Composite health & anomaly scoring,
- Sliding time-window retention (`evict-old-samples`),
- Per-host / per-service rollups and top-K anomaly detection.

## 2. Files in This Build Folder
- [`attempt_failed.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-06-observability-timeseries-db/attempt_failed.intent) — Our attempt to use substring matching (`message contains "timeout"`), expression aggregates (`total of cpu_pct times mem_mb`), and `GROUP BY` (`average latency_ms for each host_name`).
- [`attempt_failed_output.txt`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-06-observability-timeseries-db/attempt_failed_output.txt) — Exact compiler diagnostics for those 3 failures.
- [`tsdb.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-06-observability-timeseries-db/tsdb.intent) — The working 3-collection observability engine using materialized score columns and parameterized rollups.
- [`plan_explanation.txt`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-06-observability-timeseries-db/plan_explanation.txt) — Output of `./intent explain tsdb.intent`.
- [`test_tsdb.py`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-06-observability-timeseries-db/test_tsdb.py) — Verifies the native binary against the reference interpreter and benchmarks 20,000 telemetry events (**~1,000,000+ ops/sec**).

---

## 3. Failure Analysis: "Where I Was Wrong" vs. "Where the Language/Compiler Was Wrong"

### A. Where the Compiler (`intentc`) Misleads the Programmer
1. **The `"contains"` Lexicon Trap (`lexicon.py:130` + `parser.py:881`)**
   - **What I wrote**: `show the samples whose message contains "timeout".`
   - **What happened**: Instead of saying `"contains (substring search) is not supported"`, the compiler printed:
     `error: compared with what? a value is missing` pointing at `message`!
   - **Why the compiler is wrong**: In [`lexicon.py:130`](file:///Users/zen/Desktop/project-10nov/intentc/lexicon.py#L130), `"contains"` is mapped to `('HAS', None)` (so you can write `Each sample contains a message`). Then [`parser.py:881`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L881) rewrites `HAS` inside a task to `WHERE` (`whose`), and [`parse_cond()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L671-L674) rewrites a second `WHERE` to `AND`! So `whose message contains "timeout"` is silently rewritten into `whose message AND "timeout"`, producing a baffling syntax error.

### B. Where I (the Programmer) Adapted Around Missing OLAP Features
1. **Materialized Columns Instead of Expression Aggregates (`SUM(cpu_pct * mem_mb)`)**
   - **Why `attempt_failed.intent` failed**: [`parser.py:1024-1033`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L1024-L1033) only allows a single `FIELD` token inside an aggregate (`agg`), not an arithmetic expression.
   - **How I fixed my code in `tsdb.intent`**: Declare `compute_load` and `anomaly_score` as fields on `Samples`, compute them in-place with `score-samples: for every sample, set compute_load to cpu_pct * mem_mb, then set anomaly_score to ...`, and then query `what is the total compute_load of samples?`.
2. **Parameterized Rollups Instead of `GROUP BY`**
   - **Why `attempt_failed.intent` failed**: Writing `what is the average latency_ms for each host_name` fails because `"for each"` is in [`lexicon.py:121`](file:///Users/zen/Desktop/project-10nov/intentc/lexicon.py#L121) as `QUANT` (stripped globally), leaving two fields (`latency_ms` and `host_name`) in a single aggregate (`average of which one? one property per summary`).
   - **How I fixed my code in `tsdb.intent`**: Use a parameterized `WHERE` filter:
     `host-avg-latency: what is the average latency_ms of samples whose host_name is a given host_name?`

---

## 4. Where Our Analysis Might Be Wrong & Thoughts for a Reviewing Model (Aligned with Flexibility, Not Rigidity)

- **Why what worked actually worked**:
  - Materializing `compute_load` and `anomaly_score` via `score-samples` and then running `top-anomalies` and `total-compute-load` worked at **~917,000 ops/sec** because [`llvm.py`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py) keeps all 10 fields of `Samples` in a contiguous 80-byte struct array (`%"sample"`), making sequential scans cache-friendly.
- **Where our analysis might be wrong (for a stronger reviewing model to evaluate)**:
  - We flagged `"contains"` (`lexicon.py:130`) being rewritten to `HAS` → `WHERE` → `AND` in `whose message contains "timeout"` as a lexicon trap. However, `"contains"` was put in `HAS` so declarations like `Each sample contains a host_name and a latency_ms.` read naturally! Simply removing `"contains"` from `HAS` would make collection declarations **more rigid** and break valid English declarations!
- **Flexible Hypotheses for a Reviewing Model**:
  1. **Context-sensitive `"contains"`**: In a declaration (`Each X contains ...`), `"contains"` means `HAS`. After `whose <text_field>` inside a condition (`whose message contains "timeout"`), `"contains"` (along with `"starts with"`, `"ends with"`, `"includes"`) is clearly a string comparison predicate (`strstr` in `libc`!)—or until string predicates are implemented, the compiler can emit a clear, helpful message (`text operations like "contains" are not supported yet`) rather than rewriting it into `AND`.
  2. **Natural `per` / `for each <field>` Grouping**: When `"for each"` or `"per"` is followed by a **property name** (`average latency_ms for each host_name` or `average latency_ms per host_name`) rather than a collection name (`for each sample`), the parser can recognize it as a `group_by` clause rather than stripping `"for each"` as a quantifier!
  3. **Aggregates over expressions (`total of cpu_pct times mem_mb`)**: Allowing `agg` in [`ir.py`](file:///Users/zen/Desktop/project-10nov/intentc/ir.py#L52) to hold an expression tuple `expr` instead of only a single field name `field` would let `llvm.py:594` call `self.expr(...)` directly inside the fused reduction loop with zero extra memory!
