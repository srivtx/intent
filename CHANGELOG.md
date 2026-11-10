# Changelog

Intent is experimental. Until 1.0, any version may change what a sentence means; `./intent check`
always shows the current reading.

## 0.7.0 — 2026-11-11

Records of different collections can meet, a sentence can count, and a program can be served
and shown in a window. A second model's review of 0.6.0 named four limits; all four were real,
and all four are gone.

### Added
- **Two collections in one condition.** `set the hit of the aliens to 1 if any shot has an x
  equal to the alien's x and a y equal to its y`, `... if any shot has the same x and y`,
  `the aliens that have the same x and y as a shot`, `the aliens whose x is the x of any shot`,
  `the bombs that do not have the same x as an alien`. Inside a condition about other records,
  `its x`, `the alien's x` and `the same x` are the record the sentence is about. If there is no
  such record the compiler asks whose it is.
- **Counting inside a sentence.** `the number of cells whose y is 3`, `the count of ...`,
  `the total of the x of the cells`, `the largest y of the cells where ...`, anywhere a number
  can stand: in a condition, in a new value, in a record that appears, in an ending
  (`The game is over when the number of aliens is 0.`). They nest, and `with the same y`
  compares with the record that asks, which gives per-group counts:
  `remove the cells if the number of cells with the same y is 10`.
- **Decided first.** When a change asks about other records of the collection it changes,
  every record is asked before any is changed or removed, in the reference and natively, so
  storage order cannot leak into the answer. A new value worked out from the property being
  changed in the other records is refused with the reason.
- **A server.** `./program serve 8080 [journal]` (`serve-public` for every address): plain
  connections with a command per line, `GET /<command>/<arguments>`, `POST /` with commands in
  the body, many callers at once through `poll`. Emitted as LLVM IR like the rest.
  `./intent serve file.intent` does the same from the reference interpreter.
- **A window.** `GET /` is a page generated from the program: the board painted in colour and
  played with the keyboard, or a console for a program of commands. `./intent window
  file.intent` opens it in a window of its own. A served game lives in real time and everyone
  who opens the page shares it.
- `picture`: the board plus the colour of every cell, for a page to paint.
- `examples/shooter.intent`.

### Fixed
- **Word order.** `if the hurt is 1, remove the bombs whose y is at least 14` and
  `increase the y of the cells whose y is under 1 by 1 if the clear is 1` were rejected while
  their rearrangements were read. A condition can now stand in front, behind, or both.
- **Names with a number in them.** `The fill1 starts at 0. The fill2 starts at 0.` was taken
  for a slip of the first name. A digit in a name is deliberate; `hurtt` for `hurt` is still
  caught.
- `remove the aliens if any shot ...` asked "remove which alien?".
- A program whose only ending counts records needs no single value to exist.

### Changed
- `./intent explain` says when a sentence passes over another collection for every record.
- A served or built program lists `picture` among its commands when it has a board.

## 0.6.0 — 2026-11-10

A snake game can now be written, and two things that scanned no longer do.

### Added
- **Colour.** `Draw each rock at its x and y as a red "#".` `Draw a green "@" at ...`
  `... as "#" in red.` Shown while playing in a terminal; `screen` stays plain text.
- **Chance.** `a random number between 1 and 30`, `from 1 to 30`. One number is kept and each
  draw moves it on by a fixed step, identically in the reference and natively. `seed <number>`
  sets it; a command that drew a number is journaled; playing in a terminal seeds from the
  clock and writes the seed to the journal. Refused in rules, drawings and endings.
- **Records that appear.** `Every second, add a rock whose x is ... and whose y is 1.`, also
  on a key, with a condition in front or behind.
- **Conditions about other records.** `if any rock has an x equal to the column and ...`,
  `if no shot has ...`, on something that happens by itself, on a rule, and on a record
  that appears. This is how a hit takes a life.
- **Several steps.** `..., and then ...` in a sentence that happens by itself.
- **Playing again.** `restart`. In a terminal a finished game stays on show: enter plays
  again, `q` stops.
- `examples/snake.intent`.

### Faster, with the same meaning
- **One record is found through the index.** When a condition fixes a unique property
  (`increase the points of the player with a given name`, `show the player with a given
  name`, counting, top-N), the hash index that already existed is probed instead of every
  record being looked at. 20,000 players and 40,000 awards: 79 s before, 0.65 s now, same output.
- **Rules look only where something changed**, when every rule in the program reads and
  changes a single record. After an add or a one-record change, the rules are applied to that
  record alone; after a removal, not at all. A record no command touched is still as the rules
  left it, so nothing is missed. Any rule that reads a single value, an owner or another
  collection puts the whole program back on the full pass. Rules that never come to rest are
  still reported on every command, as the reference does.
- `./intent explain` says which of these a capability gets, and why.

### Fixed
- `Menus`, `Skus`, `Gurus` are now several of a menu, a sku, a guru. `status`, `bonus`,
  `virus` and the like are still one thing.
- A game with no commands no longer gets the note "nothing to do with it yet".
- `as a "#"` (an article before the character) is read.

### Changed
- A game that can end needs one more terminal line, for the line that offers another game.
- `help` lists `seed` and `restart` where they apply.

## 0.5.1 — 2026-11-10

Hardening of 0.5.0. No new sentences.

### Fixed
- **Stray words are no longer ignored** in the new sentences. `The board is draw 30 wide and
  12 high`, `the left key key is pressed`, `Draw score "@" at ...` and `Start with a rock at
  x is is 4` all compiled before; each is now pointed at.
- **Two comparisons side by side are a question** (`whose y is over under 3`: *"over" or
  "under"?*). The second used to win silently, in every kind of sentence.
- A stray word between `where` and `each ... has` in a collection's description, or inside
  `The total starts at 15`, is now reported.
- `screen` crashed the reference interpreter when the program had a board but no single values.

### Changed
- Playing uses a screen of its own with line wrap off, and puts the terminal's settings back
  exactly as they were (not to defaults) on `q`, `Esc`, `Ctrl-C`, a hang-up or a request to
  stop. The last board stays visible afterwards.
- A terminal too small for the board is refused, with the size it needs.
- An arrow key whose bytes arrive apart is still an arrow key, not `Esc`.

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
