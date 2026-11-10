# Changelog

Intent is experimental. Until 1.0, any version may change what a sentence means; `./intent check`
always shows the current reading.

## 0.5.0 — 2026-11-10

### Added
- **Time.** `Every 150 milliseconds, the y of each rock increases by 1.` `Every second, ...`
  `4 times a second, ...` Things due together happen in the order written, then the rules settle.
- **Keys.** `When the left key is pressed, ...` `When the player presses space, ...`
  Arrows, space, enter, letters and digits.
- **A board.** `The board is 30 wide and 12 high.` `Draw each rock at its x and y as "#".`
  `Show the score above the board.`
- **An ending.** `The game is over when the lives are under 1.` or `... when any rock has ...`
- **Starting records.** `Start with a rock at x 4, y 1.`
- **Playing.** A compiled program with a board, run in a terminal, is played with the real
  clock and keyboard (`q`, `Esc`, `Ctrl-C` stop). `./intent run` plays it in the reference.
  Over a pipe the same program takes `wait <milliseconds>`, `press <key>` and `screen`, so a
  game is scripted, remembered and replayed exactly.
- The thing may come before the verb: `the score increases by 1`, `the speed doubles`,
  `goes up by`, `goes down by`.
- `examples/dodge.intent`.

### Fixed
- Short names that differ by one letter (`px` and `py`, `x` and `y`) are no longer taken for
  a slip of each other when declared as single values.

## 0.4.0 — 2026-11-10

### Added
- **Single values.** `The score is a number.` `The best starts at 0.` `The limit is 100.`
  Shown, changed and remembered like properties; usable in any condition or calculation.
- **Values that depend on a condition.** `... a if a is over b, otherwise b`, chained as often
  as needed, in calculations and in changes (`Set the grade to "pass" if ..., otherwise "fail".`).
- **Standing rules.** `When the score is over the best, the best becomes the score.`
  `Whenever a player's points are under 0, remove them.` `The level is always ... if ...,
  otherwise ...` Applied after every change until nothing moves; compiled natively.
- Calculations accept one-letter names (`take a number a and a number b`) and
  `take two numbers a and b`.
- `increase the points of the player with a given name by a given amount` (the amount may
  follow the condition).
- `examples/calculator.intent`, `examples/arcade.intent`.

### Changed
- Dividing by a value that might be zero is now a **question** (*what should happen when it is
  zero?*), answered with `if ... is not 0, otherwise ...`, instead of an error. Dividing by an
  input is therefore possible.
- An unnamed sentence starting with `when` that changes or removes something is now a standing
  rule, not a command. Name it (`Retire: when ...`) to keep it a command.

## 0.3.0 — 2026-11-10

### Added
- **Relationships.** `Each order belongs to a customer.` (or `Each order has a number and a
  customer.`). Sentences can reach the owner: `orders of a given customer`,
  `orders whose customer's city is "rome"`, `the customer's name of orders`, and two links
  deep: `lines whose order's customer is ...`.
- **Removal rules.** If owners can be removed, the compiler asks what happens to what they
  own: `When a customer is removed, remove its orders.` or
  `A customer with orders cannot be removed.`
- **One-sentence declarations.** `Customers is a collection where each customer has ...`,
  `Customers have a name, an age and an email.`
- **Several-valued properties.** `phones`, `several tags`, `a list of tags`. A bare plural is
  an assumption and is reported; count words (`points`, `units`) stay one number.
- **Text tests.** `contains`, `starts with`, `ends with`, and their negations.
- **Arithmetic.** `mod`, `is even`, `is odd`; a calculation may stand left of a comparison.
- Rules such as `Reject duplicates.` apply to the collection just described.
- A program's own two-word definition (`An even stone is ...`) wins over a built-in word.
- `examples/store.intent`; a review of the stress experiments in `gemini-build/REVIEW.md`.

### Fixed
Found by the `gemini-build` stress experiments:
- `not between 18 and 30` silently dropped everything above the range.
- A taught word inside a hyphenated capability name renamed the command.
- A property named like a collection hid the collection.
- `find an order by id` was read as "order by".
- `show the orders cheap` (a taught condition without "whose") failed.
- A command given no arguments treated the missing one as empty text.
- Rejected and malformed commands were written to the journal.
- Output was held back when the program was driven over a pipe.

### Changed
- With more than one collection, generated command names carry the collection
  (`order-add`, `customer-count`).
- Output is flushed after every command. Query-heavy batch runs make more system calls.

## 0.2.0 — 2026-11-10

### Added
- **Spelling tolerance.** A misspelled word is accepted when exactly one known word that
  close makes the whole sentence readable; each correction is reported; two possible
  corrections with different meanings is a question.
- **Definitions.** `"older than" means age over.`, `An adult is a customer whose age is at
  least 18.`, adjectives (`An open task is ...`), definitions built on definitions.
- **Rankings and limits.** `the top 3 players by score`, `the customer with the lowest age`,
  `the first 5 ...` (a question unless an order is declared).
- **Ranges and percentages.** `between 18 and 30`, `increase every salary by 10 percent`.
- `Remove all customers.` when said outright.
- More word orders: `Customers whose age is under 18: remove them.`,
  `By email, find a customer.`, `The age of every customer, double it.`
- Every compiled program has `help`.
- **Remembering between runs.** Given a file name, a program logs each change and replays the
  log on start.
- Examples: leaderboard, to-do list, shop stock.

## 0.1.0 — 2026-11-10

First version.
- Sentences to Intent IR to LLVM IR to a native program, with no intermediate language and no
  AI in the compiler.
- Collections, typed properties (text and whole numbers), uniqueness, duplicate policy,
  insertion order.
- Capabilities: add, find and remove by a property, remove and keep by condition, bulk
  changes, listing with projection, sorting, count / sum / average / largest / smallest,
  simple calculations.
- The never-drop rule: every word is a known concept, known filler, or a declared name.
- Questions instead of guesses, pointing at the words.
- Representation chosen from declared capabilities: growable array, hash index on a unique
  property only when needed, swap or shift removal, fused passes; `explain` cites the lines.
- Reference interpreter and differential tests against native code.
