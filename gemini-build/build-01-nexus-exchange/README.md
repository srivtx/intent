# Build 01: NEXUS — Multi-Collection Financial Exchange, Risk & Margin Engine

## 1. What We Tried to Build
A 5-collection financial exchange, margin risk engine, and compliance audit service compiled from a **single `.intent` file** directly to a native LLVM executable ([`nexus`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-01-nexus-exchange/nexus)):
- **`Traders`**: Hash-indexed by unique `handle` (`reject` duplicate policy).
- **`Assets`**: Hash-indexed by unique `ticker` (`replace` duplicate policy for live market feed upserts).
- **`Orders`**: Limit order book hash-indexed by unique `order_id` with `O(1)` swap-with-last cancellation.
- **`Positions`**: Leveraged margin positions hash-indexed by `pos_key` (`replace` policy) with **multi-step sequential in-place mark-to-market valuation** (`current_price` → `unrealized_pnl` → basis-points `margin_used` in one pass).
- **`Audits`**: Compliance log declared with `Keep audits in the order they were added` (`O(n)` gap-closing shift removal).

## 2. Files in This Build Folder
- [`attempt_failed.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-01-nexus-exchange/attempt_failed.intent) — Our first-instinct version that **fails to compile** with 8 distinct diagnostics.
- [`attempt_failed_output.txt`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-01-nexus-exchange/attempt_failed_output.txt) — Exact `./intent check` compiler diagnostics on the failed attempt.
- [`nexus.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-01-nexus-exchange/nexus.intent) — The working 5-collection exchange specification (48 compiled commands).
- [`plan_explanation.txt`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-01-nexus-exchange/plan_explanation.txt) — Full output of `./intent explain nexus.intent`.
- [`test_exchange.py`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-01-nexus-exchange/test_exchange.py) — End-to-end verification against the reference interpreter + 12,000-command benchmark (**~700,000+ ops/sec**).

---

## 3. Failure Analysis: "Where I Was Wrong" vs. "Where the Language/Compiler Was Wrong"

When [`attempt_failed.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-01-nexus-exchange/attempt_failed.intent) failed to compile, we separated every failure into **author mistakes** (our misunderstanding of the language's rules) vs. **compiler bugs / missing language capabilities**:

### A. Where I (the Programmer) Might Be Wrong
1. **Unscoped `Reject duplicates.` in a multi-collection file**
   - **What I wrote**: `Reject duplicates.` under `Assets` without naming `Assets`.
   - **Why I was wrong**: For the *first* collection at the top of a file, only one collection exists so far (`len(prog.collections) == 1`), so `Reject duplicates.` implicitly applies to it. Once a *second* collection is declared, `Reject duplicates.` is genuinely ambiguous across collections.
   - **Fix**: Explicitly scope the sentence: `If an asset already exists, reject it.`
2. **Mixing `and` and `or` without precedence**
   - **What I wrote**: `whose frozen is 0 and risk_score is under 100 or cash_cents is at least 1000000`
   - **Why I was wrong**: In English, `A and B or C` is genuinely ambiguous between `(A and B) or C` and `A and (B or C)`. The compiler is right to refuse to guess.
   - **Fix**: Split into taught noun definitions (`An active trader is a trader whose frozen is 0.`) or separate capabilities.
3. **Forgetting that property names are singularized**
   - **What I wrote**: Declared `cash_cents`, `volatility_bps`, `units`.
   - **Why I was wrong**: [`field_item()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L557) runs `singular()` on the last word of every property name (`cash_cents` → `cash_cent`, `units` → `unit`), which changes the parameter names in CLI usage (`<cash_cent>`, `<unit>`).

### B. Where the Compiler (`intentc`) Has Real Bugs (Even Within Its Own Scope)
1. **Bug: `"order by"` Lexicon Collision Swallows the `Orders` Collection Name**
   - **What happened**: Writing `inspect-order: find an order by order_id.` fails with `question: which collection is this about?` even though `order` is explicitly in the sentence!
   - **Why the compiler is wrong**: In [`normalize()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L421-L438), the 2-word SQL phrase `"order by"` (`SORTBY`, length 2 in [`lexicon.py`](file:///Users/zen/Desktop/project-10nov/intentc/lexicon.py#L90)) beats the 1-word collection match `"order"` (`COLL`, length 1) because `el >= pl` (`1 >= 2`) is false! So `"order by"` is tokenized as a sort keyword instead of `<collection: order> + <preposition: by>`.
   - **Workaround in `nexus.intent`**: Write `find an order using order_id` (`using` maps to `BY` without forming the 2-word phrase `"order by"`).
2. **Bug: Naming a Foreign-Key Field `trader` on `Orders` Globally Shadows the `Traders` Collection**
   - **What happened**: Declaring `Each order has a trader (text)...` makes every later sentence about the `Traders` collection (e.g., `register-trader: add a trader.`) fail!
   - **Why the compiler is wrong**: [`normalize()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L396-L438) checks `if key in self.prog.field_names()` *before* `elif singular(t.text) in self.prog.collections`. Once *any* collection has a field named `trader`, the word `trader` or `traders` is unconditionally classified as `FIELD` everywhere in the file and never as `COLL`.
   - **Workaround in `nexus.intent`**: Rename foreign-key fields to `buyer_or_seller` and `holder`.
3. **Bug: Taught Words Expand Inside Hyphenated Capability Names (`liquidate-underwater:`)**
   - **What happened**: When `"underwater" means unrealized_pnl under 0.` is taught, naming a capability `liquidate-underwater:` mutates the command name into `liquidate-unrealized_pnl-under-0` (or fails with a syntax error if the phrase is longer, as in `check-solvent:`)!
   - **Why the compiler is wrong**: [`expand_sentence()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L314) tries to skip macro expansion before `:`, but checks `if any(t.kind != 'word' for t in pre)`. Because the hyphen `-` has `t.kind == 'sym'`, it falls through and runs `self.expand(pre)` on the capability name itself!

### C. Where the Language Hits Fundamental Design Walls
1. **No Division by Runtime Variables (`entry_cents / leverage`)**: Blocked by [`check.py`](file:///Users/zen/Desktop/project-10nov/intentc/check.py#L148-L151) because Intent has no error/exception value or `Option` type when a parameter is `0`. We had to hardcode fixed-divisor capabilities (`calc-2-x-liq-price`, `calc-5-x-liq-price`, `calc-10-x-liq-price`) or use basis-point multiplication `(val * leverage_bps) / 10000`.
2. **No Cross-Collection Matching Inside `.intent`**: While `Orders`, `Traders`, `Assets`, and `Positions` all live in the same native binary, a capability on `Orders` cannot read `Assets.mark_price` or debit `Traders.cash_cent` directly; cross-collection coordination must be driven by the caller sending sequential stdin commands.

---

## 4. Where Our Analysis Might Be Wrong & Thoughts for a Reviewing Model (Aligned with Flexibility, Not Rigidity)

- **Why what worked actually worked**:
  - Multi-collection support in one `.intent` file worked seamlessly once each sentence explicitly named its collection, because [`Program.collections`](file:///Users/zen/Desktop/project-10nov/intentc/ir.py#L61) and [`Gen.module()`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L789-L794) were already designed to emit isolated global arrays and hash tables per collection.
  - Multi-step financial formulas (`mark-to-market`) worked in a single sentence because [`llvm.py:542-548`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L542-L548) lowers comma/`then`-separated assignments sequentially in-place on the record pointer.
- **Where our interpretation might be wrong (for a stronger reviewing model to evaluate)**:
  - We flagged `"order by"` swallowing the `order` collection in `find an order by order_id` as a bug in [`normalize()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L421-L438). A stronger model might observe that in `find an order by order_id`, the verb `find` at the start of the sentence already disambiguates that `order` is a noun (the collection) and `by` is the lookup preposition—so context-aware normalization (or checking whether `order` is preceded by an article `an`/`the` or verb `find`/`remove`) could preserve both `"order by"` (for sorting) and `"find an order by ..."` (for lookup) **without making the phrasing rigid**!
  - Similarly, for foreign-key field shadowing (`Each order has a trader` hiding the `Traders` collection), rather than forbidding field names that match collection names (which would make the language more rigid), a reviewing model could let [`normalize()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L427-L438) or [`scope()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L458-L475) distinguish collection position (`add a trader`, `for every trader`) from property position (`whose trader is ...`).
