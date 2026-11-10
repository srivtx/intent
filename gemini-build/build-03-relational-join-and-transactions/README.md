# Build 03: Two-Phase E-Commerce Ledger & Inventory Checkout (The Relational & Transaction Wall)

## 1. What We Tried to Build
A classic transactional business system—an **E-Commerce Inventory & Double-Entry Wallet Ledger** (`Wallets`, `Products`, `Transfers`)—where a checkout must:
1. Verify `wallet.balance >= cost` and `product.stock >= qty`,
2. Deduct `cost` from the buyer's wallet and `qty` from the product's stock,
3. Record a committed `Transfer` receipt atomically (or roll back if either check fails).

## 2. Files in This Build Folder
- [`attempt_failed.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-03-relational-join-and-transactions/attempt_failed.intent) — Our attempt to write a cross-collection join, a `never under 0` check constraint, an update-and-return receipt, and bulk key renumbering.
- [`attempt_failed_output.txt`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-03-relational-join-and-transactions/attempt_failed_output.txt) — Compiler diagnostics showing why each of those 4 constructs is rejected.
- [`ledger_service.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-03-relational-join-and-transactions/ledger_service.intent) — The working 3-collection Two-Phase Reservation Ledger (`hold-funds`, `allocate-stock`, `capture-funds` / `release-funds`, `commit-transfer` / `abort-transfer`).
- [`plan_explanation.txt`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-03-relational-join-and-transactions/plan_explanation.txt) — Output of `./intent explain ledger_service.intent`.
- [`test_ledger.py`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-03-relational-join-and-transactions/test_ledger.py) — Compiles and tests the native binary, demonstrating both guarded updates and the silent 0-row update hazard.

---

## 3. Failure Analysis: "Where I Was Wrong" vs. "Where the Language/Compiler Was Wrong"

### A. Where I (the Programmer) Was Wrong (And How Guarded Predicates Helped)
1. **Trying to Write a Global Schema Constraint (`stock is never under 0`)**
   - **Why I was wrong**: Intent v0.1 only supports `unique` and `insertion order` as collection-level schema declarations. Writing `Products whose stock is never under 0.` is parsed as a query/task with an unknown word `"never"`.
   - **How I fixed my code**: Move the invariant into the `where` clause of the mutating capability!
     ```text
     hold-funds: for every wallet whose wallet_id is a given wallet_id and balance is at least a given amount, decrease balance by a given amount, then increase reserved by a given amount.
     ```
     Notice how `whose wallet_id is a given wallet_id and balance is at least a given amount` uses the same parameter `<amount>` in *both* the `where` guard and the `decrease`/`increase` body! If `balance < amount`, the `where` clause evaluates to `false` and the balance is never driven negative.
2. **Defining a Taught Phrase with `"is"` (`"pending" means state is 0.`) Instead of a Taught Noun (`A pending transfer is a transfer whose state is 0.`)**
   - **What happened**: Writing `"pending" means state is 0.` and then `show the transfers pending.` failed with `error: I don't see how "is" fits in`!
   - **Am I wrong or is the compiler wrong? Both!**
     - In [`parser.py`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L941-L949), when a sentence has no `WHERE` keyword (`whose`/`where`/`with`), the parser only splits a trailing condition if it sees a `CMP` token (`over`, `under`, `at least`, `equal to`)—not `IS` (`is`). So `"whale" means cash_cents at least 100000000` works without `whose`, whereas `"pending" means state is 0` fails unless you write `A pending transfer is a transfer whose state is 0.` or `"pending" means whose state is 0.`.

### B. Where the Language / Compiler (`intentc`) Blocks Real-World Transactional Software
1. **Silent No-Op on Guarded `update` (No Row-Count Return Value)**
   - In [`llvm.py`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L538-L549) and [`interp.py`](file:///Users/zen/Desktop/project-10nov/intentc/interp.py#L130-L135), an `update` command **always prints nothing (`[]`)**, whether it updated 1,000 rows or 0 rows!
   - Consequence: When `allocate-stock 1,GPU_H100` fails its guard (`stock >= 1` is false because `stock == 0`), the compiled binary prints **nothing**. The caller has to issue a separate `find-product GPU_H100` query after every `update` to find out whether the guard passed or failed!
2. **One Collection Per Sentence (`parser.py:468`)**
   - [`scope()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L466-L468) explicitly raises `one sentence can only be about one collection in this version` whenever `len(names) > 1`. You cannot join `Transfers` with `Wallets`, nor can `allocate-stock` look up `Products.unit_price` and debit `Wallets.balance` in one step.
3. **No Multi-Step Capabilities or Sub-Capability Calls**
   - You cannot write `To checkout: hold-funds, allocate-stock, capture-funds, commit-transfer.` Every capability maps to a single `Task` node in [`ir.py`](file:///Users/zen/Desktop/project-10nov/intentc/ir.py#L39-L56) operating on a single collection.

---

## 4. Where Our Analysis Might Be Wrong & Thoughts for a Reviewing Model (Aligned with Flexibility, Not Rigidity)

- **Why what worked actually worked**:
  - Parameter sharing in [`emit()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L1220-L1250) deduplicates parameter names (`seen`) across `t.assigns` and `t.where`. That is why writing `whose balance is at least a given amount, decrease balance by a given amount` bound both occurrences of `a given amount` to the **single** command parameter `<amount>`, giving us an atomic compare-and-sub guard on a single collection!
- **Where our analysis might be wrong (for a stronger reviewing model to evaluate)**:
  - We criticized `update` for printing nothing when 0 rows match (`allocate-stock` silently doing nothing when out of stock). However, in bulk updates (`for every customer, double their age`), silent execution matches existing tests (`tests/test_intent.py`). Changing `update` to print row counts everywhere would break the existing reference specification in [`interp.py:135`](file:///Users/zen/Desktop/project-10nov/intentc/interp.py#L135).
- **Flexible Hypotheses for a Reviewing Model**:
  - Rather than rigidly changing all `update` outputs, how could Intent express invariants and relationships naturally in English?
    1. **Collection-level invariants**: Sentences like `Balance is never under 0.` or `Stock is at least 0.` could attach a constraint to `Collection` that is automatically checked before `add` and `update` (printing `rejected: stock would be under 0` on violation, just like `duplicate sku`!).
    2. **Natural relationships**: Allowing `Each transfer belongs to a wallet.` would let the planner automatically maintain a foreign-key index and let sentences naturally span related records (`Decrease the wallet's balance by the transfer's amount`).
