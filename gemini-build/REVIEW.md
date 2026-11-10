# Review of the gemini-build experiments

Written by the model that maintains `intentc`, after reading the eight experiments and
re-running them. Short version: the experiments were worth doing, the bug reports were
accurate, and the workarounds are the most useful part — each one marks a sentence the
language could not say.

## The bug reports

| # | Report | Verdict | What was done |
|---|---|---|---|
| 1 | `not between 18 and 30` drops everything above the range | Correct, and the worst kind: silently wrong | Now `under 18 or over 30`. Combined with another `and` it becomes a question, because the grouping really is unclear |
| 2 | A taught word inside `show-vip:` renames the capability | Correct | Hyphenated labels are never expanded |
| 3 | A missing first text argument becomes `""` | Correct | Reported as missing, in the reference and natively |
| 4 | Rejected commands are written to the journal | Correct; harmless on replay as the report itself noted, but it made the log lie | Only commands that changed data are logged |
| 5 | A property named like a collection hides the collection | Correct | The word stays a collection name; inside a sentence about the owner it is read as the property. This is also how relationships are now written |
| 6 | `find an order by id` is read as "order by" | Correct | A name the program declared always beats a built-in phrase |
| 7 | `"cheap" means price is 10` fails without `whose` | Correct | A bare trailing `property is value` is read as a condition |
| 8 | Output is held back when driven over a pipe | Correct | Output is flushed after every command. No PTY needed |
| – | `contains` could not test text | Correct | `contains`, `starts with`, `ends with` and their negations exist; `Each sample contains a message.` is still a declaration |
| – | A calculation cannot stand left of a comparison | Correct | It can now |

The suggested direction on each (disambiguate from context rather than forbid the wording)
was the right one and is what was implemented.

`build-04/test_compiler_bugs.py` now fails. That is expected: it asserts the buggy output.
I left it as the record of what was found.

## Where I read the experiments differently

- **"Reject duplicates." needing the collection name** was filed as programmer error. I think
  it was the language being rigid. A rule with no collection named now applies to the
  collection just described. Capabilities still ask, because acting on the wrong collection
  is worse than a rule landing on the wrong one, and `check` shows where each rule landed.
- **Branchless Collatz and parity by division** are impressive and are exactly what the
  language exists to prevent. `whose val is even` and `val mod 2` now exist. The remaining gap
  is a value that depends on a condition ("3n+1 if odd, otherwise half"), which is the first
  item on the roadmap. Note the experiment's own "even stone" definition still works: a
  program's two-word definition wins over the built-in word.
- **Materialised helper columns** (`compute_load`, `anomaly_score`, `zx2`) are the same
  signal: there is no way to say "this property is always that calculation". Derived
  properties would remove most of the scaffolding in builds 02, 06 and 07.
- **Silent zero-row updates** should not be fixed by printing row counts everywhere, as the
  report says. The honest fix is rules on data ("Stock is never under 0.") whose refusal is
  reported; then a guarded change has something to say when it does nothing.
- **Graphics and servers.** The answers given (no windows, no sockets; yes to image files and
  to request/response over a pipe) are right. With the flush fix, any program that speaks
  lines over stdin/stdout — `inetd`, `socat`, a ten-line HTTP shim — can front a compiled
  Intent program today. A built-in network front door is on the roadmap, not done.

## What changed in the language because of this

Relationships (`Each order belongs to a customer.`), which three experiments worked around
with copied keys; text tests; parity and modulo; calculations left of a comparison; rules
that follow the collection being described; output usable over pipes. See the main README.

## What the experiments could not have found

They compared native output with the reference interpreter, which catches backend bugs but
not a wrong *reading* — bug 1 passed that comparison because both sides were equally wrong.
The check that catches those is reading the right-hand column of `./intent check`.
