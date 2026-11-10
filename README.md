<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="intent." width="260">
  </picture>
</p>

<p align="center">
  <img alt="status: experimental" src="https://img.shields.io/badge/status-experimental-f59e0b">
  <img alt="version 0.5.0" src="https://img.shields.io/badge/version-0.5.0-6366f1">
  <a href="https://github.com/srivtx/intent/actions/workflows/tests.yml"><img alt="tests" src="https://github.com/srivtx/intent/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-3776ab">
  <img alt="backend: LLVM IR" src="https://img.shields.io/badge/backend-LLVM%20IR-262d3a">
  <img alt="dependencies: none" src="https://img.shields.io/badge/dependencies-none-22c55e">
  <img alt="AI in the compiler: none" src="https://img.shields.io/badge/AI%20in%20the%20compiler-none-ef4444">
</p>

> **Experimental.** Intent is a research prototype, a day or two old. The language changes
> between versions, there are things it cannot say yet ([limits](#what-this-version-cannot-do)),
> and it has only been run on macOS. Use it to explore the idea, not to hold data you care about.

**[Language guide](docs/language.md)** · **[Changelog](CHANGELOG.md)** · **[Examples](examples/)** · **[Stress experiments](gemini-build/README.md)**

# Intent

You describe **what information exists and what should be possible with it**, in ordinary
sentences. The compiler works out the data structures, loops and algorithms, and emits
**LLVM IR directly** — no Rust, C or JavaScript in between — which becomes a native program.

No AI is involved. The compiler is deterministic: the same text always means the same thing.

```
Customers is a collection.
Each customer has a name, an age and an email.
Emails are unique.
Reject duplicates.

Add a customer.
Find a customer by email.
Remove a customer by email.
For every customer, double their age.
adults: the names of customers whose age is at least 18.
What is the average age?
Show the customers sorted by age, largest first.
```

Nothing above says array, hash map, loop, index or sort algorithm.

## Try it

Needs Python 3.10+ and `clang`. No packages to install.

```bash
./intent check examples/customers.intent
```

```bash
./intent explain examples/customers.intent
```

```bash
./intent build examples/customers.intent -o build/customers
```

```bash
printf 'add Alice,20,alice@x.com\nadd Bob,25,bob@x.com\ndouble-age\nfind-by-email bob@x.com\naverage-age\n' | ./build/customers
```

```bash
./intent check examples/questions.intent
```

```bash
python3 -m pytest tests -q
```

| command | what it shows |
|---|---|
| `check` | how every sentence was read, and every question the compiler has |
| `explain` | the representation it chose and which lines of your program caused each choice |
| `ir` | the generated LLVM IR (each function is labelled with the sentence it came from) |
| `build` | native executable; it reads one command per line on stdin |
| `run` | the same program in the reference interpreter |

## The three rules that make this work

**1. It never drops a word it does not know.** Every word is either a concept in the
[lexicon](intentc/lexicon.py), filler in the lexicon, or a name your program declared.
Anything else stops compilation and is pointed at. So `So basically, I want to double the
age of all the customers please` compiles, and `Show the largest positive age` does not:

```
error: I don't know the word "positive"
9 | Show the largest positive age.
  |                  ^^^^^^^^ not a concept I know, and not a name this program declared
```

**2. It asks instead of guessing, and points at the words.** Things it asks about today:
a pronoun with no clear referent (`double it`), sorting without a property, removing without
saying which, `by age` (sorted by, or looked up by?), a comparison with no property
(`customers over 25`), mixed `and`/`or`, a property whose type nothing decides, and what
happens when a unique value is added twice.

**3. A program is a service, not a script.** You declare capabilities; the compiled program
accepts them as commands, any number of times in any order. That is what gives the compiler
a real decision to make about representation: it minimises the per-call cost of the
capabilities you declared and builds nothing you did not ask for.

## How flexible is it?

**Different words, different order.** These all compile to `remove customer where age < 18`:

- Remove the customers whose age is under 18.
- Customers whose age is under 18: remove them.
- If the age is under 18, delete the customer.
- Wipe out every customer with an age below 18.

**Spelling slips.** `Shwo teh customres sroted by aeg.` compiles, and says what it did:

```
note: read "Shwo" as "show"
note: read "customres" as "customers"   (and three more)
```

A misspelled word is accepted only when exactly one known word that close makes the *whole
sentence* readable. If two corrections would give different meanings (`coxt` when the
program has both `cost` and `coat`), it asks. A word that is not close to anything
(`positive`) is still an error. Names in declarations are never "corrected".

**Teach it your own words.** The vocabulary is not fixed; a program extends it:

```
"older than" means age over.
An adult is a customer whose age is at least 18.
A senior is an adult older than 64.
An open task is a task whose done is 0.
"oldest" means with the largest age.

Show the names of seniors.          ->  list name of customer where age >= 18 and age > 64
Show the 3 oldest adults.           ->  ... where age >= 18 sorted by age descending, first 3
```

A taught word is substituted before the sentence is read, so it behaves exactly like its
meaning, typos in it are caught the same way, and a word can never be given a second meaning.

**Rankings, ranges, percentages.** `Show the top 3 players by score.`,
`the customer with the lowest age`, `whose age is between 18 and 30`,
`Increase every salary by 10 percent.`, `Remove all customers.`

What flexibility does *not* mean: it will not act on a sentence it only half understood.
`Show the first 5 customers.` on a collection with no declared order is a question
("first in what order?"), not a guess.

## Describing things in one breath

All of these declare the same collection; none needs a separate "is a collection" line:

```
Customers is a collection where each customer has a name, an age and an email.
Customers is a collection with a name, an age and an email.
Customers have a name, an age and an email.
Each customer has a name, an age and an email.
```

**One value or several** is read from how you say it:

| you write | it means |
|---|---|
| `a phone` | one value |
| `phones`, `several phones`, `a list of phones`, `one or more phones` | several per customer |
| `phones (text)` | one value (a type says it is a single thing) |
| `points`, `units`, `cents`, `likes` ... | one number: these plurals are counts |

A bare plural is an assumption, so it is reported: *reading "phones" as several values per
contact, because it is plural*. Several values are stored as records that belong to their
owner and go when it goes, so everything else works on them unchanged:

```
Add a phone to a given contact.
Show the phones of a given contact.
How many phones does a given contact have?
Show the phones whose contact's city is a given city.
```

`Each customer has orders.`, when Orders is already a collection, links the two instead.

## Collections that belong to each other

```
Each order belongs to a customer.            (or: Each order has a number and a customer.)
Each line belongs to an order.
When a customer is removed, remove its orders.

Show the orders of a given customer.
Show the number and the customer's name of orders.
Decrease the total by 10 percent for orders whose customer's city is a given city.
Show the lines whose order's customer is a given customer.
```

An order stores its customer's unique property (so customers need exactly one; otherwise the
compiler asks how a customer is identified). Adding an order for a customer that does not
exist answers `no such customer`. If the program can remove customers, the compiler **asks
what happens to their orders** and accepts either rule:
`When a customer is removed, remove its orders.` or `A customer with orders cannot be removed.`

The planner indexes the owner's key because of the link, and `explain` says so.
Not yet: asking about owners through what they own (`customers with more than 3 orders`) —
that is refused with an explanation, not misread.

## Values, decisions and rules

Three things every language needs, said the same way as everything else.

```
The score is a number.
The best starts at 0.

Hit: increase the score by a given amount.
Bigger: take a and b and return a if a is over b, otherwise b.
Share: take a and b and return a divided by b if b is not 0, otherwise 0.

When the score is over the best, the best becomes the score.
The level is always 3 if the score is at least 50, otherwise 1.
```

- **Single values** (`the score`) sit beside collections and are remembered the same way.
- **A value can depend on a condition.** Half a decision is a question (*and what if not?*).
  Division by something that might be zero is a question too; the answer is the `otherwise`.
- **Standing rules** are never called. After every change they are applied until nothing
  moves, natively. A rule that could never come to rest is refused at compile time.

## A game you can play

A program can run by itself: time passes, keys are pressed, and a board is drawn.

```
The board is 30 wide and 12 high.
The column starts at 15.
Rocks is a collection where each rock has an x and a y.
Start with a rock at x 4, y 1.

Every 150 milliseconds, the y of each rock increases by 1.
Whenever the y of a rock is over 12, its y becomes 1.
When the left key is pressed, the column decreases by 1 if the column is over 1.
The game is over when any rock has an x equal to the column and a y equal to 12.

Draw each rock at its x and y as "#".
Draw "@" at the column and 12.
```

```bash
./intent build examples/dodge.intent -o build/dodge
```

```bash
./build/dodge
```

Run in a terminal, it is played with the arrow keys (`q` stops). Over a pipe, the same program
takes `wait 450`, `press left` and `screen` as commands. Time and keys are events handed to the
program, never read behind its back, so a game is replayed exactly and the native code is
tested against the reference like everything else.

## Small programs written in it

| file | what it is |
|---|---|
| [examples/leaderboard.intent](examples/leaderboard.intent) | game leaderboard: join, award points, podium, champions |
| [examples/todo.intent](examples/todo.intent) | to-do list: open / finished / urgent tasks, what to do next |
| [examples/shop.intent](examples/shop.intent) | shop stock: sell, restock, sale, what is running low |
| [examples/store.intent](examples/store.intent) | customers, their orders and order lines, with cascading removal |
| [examples/calculator.intent](examples/calculator.intent) | a calculator: nothing stored, values that depend on conditions |
| [examples/arcade.intent](examples/arcade.intent) | the scorekeeping of a game: single values, players, standing rules |
| [examples/dodge.intent](examples/dodge.intent) | a game played in the terminal: time, arrow keys, a board, an ending |
| [examples/tour.intent](examples/tour.intent) | every kind of sentence in the [language guide](docs/language.md) |

```bash
./intent build examples/leaderboard.intent -o build/leaderboard
```

```bash
./build/leaderboard scores.log
```

Then type `help`, `join ana,900,3`, `award 150,ana`, `podium`. Every compiled program has
`help`. **Give it a file name and it remembers between runs**: each command that can change
data is appended to that file and replayed (silently) on the next start. Because the language
is deterministic, replaying the commands rebuilds exactly the same data.

## Many phrasings, one meaning

All of these compile to the identical IR `update customer: age = age * 2` (tested):

- Transform the age of each customer by multiplying it by 2.
- For every customer, double their age.
- Take the customer collection and make everyone's age twice as large.
- Customers: increase each person's age to two times its current value.
- Each customer's age should be multiplied by 2
- age = age * 2

## The compiler chooses the representation

| you wrote | it builds |
|---|---|
| add, list, update, summaries only | one growable array |
| `Emails are unique` + `Add` | + hash index on email (every add must check for a clash) |
| `Find / Remove a customer by email` | the same index answers these in O(1) |
| unique property, but nothing adds or looks up by it | no index |
| remove by key, order not mentioned | swap the last row into the hole, O(1) |
| + `Keep customers in the order they were added.` | close the gap instead, O(n) |
| filter + projection, or filter + summary | one fused pass, nothing copied |

Same program, same commands (n adds, n finds, n/2 removes), seconds on this machine
(`python3 bench/bench.py`):

| records | planner's choice | index forbidden | + "keep insertion order" |
|---:|---:|---:|---:|
| 5,000 | 0.009 | 0.111 | 0.198 |
| 10,000 | 0.021 | 0.439 | 0.667 |
| 20,000 | 0.035 | 1.669 | 3.032 |
| 40,000 | 0.046 | 6.823 | 13.188 |

The third column is one extra sentence of intent changing the generated data structure
code, without touching anything else in the program. It is slow on purpose-built churn
because v0.1 rebuilds the index after an order-preserving removal; see next steps.

## Is the generated code right?

`intentc/interp.py` is a deliberately naive interpreter over the IR (a Python list of
dicts). It is the definition of meaning. The tests build native programs and feed both
the same random command streams — unordered and ordered collections, text and numeric keys,
reject and replace, with and without indexes, including malformed input and 64-bit overflow
— and require identical output (as a multiset where order is not part of the meaning).
155 tests pass, including the example apps, three-collection relationship programs and a
game, run against the reference on random commands; the game is also played through a real
terminal.

This shows the backend agrees with the reference. It does not show the reference agrees
with what you meant; that is what `check` is for — read the right-hand column.

## What this version cannot do

- Relationships go one way: from a record to its owner. No summaries per owner, no grouping.
- Whole numbers (64-bit, wrapping) and text only. No decimals, dates, or missing values.
- Text may not contain commas (the command format is comma-separated).
- Conditions are a flat list of `and` or of `or`; no grouping.
- No constraints other than uniqueness; a unique property cannot be changed in bulk.
- **Games are simple ones.** There is time, keys and a board of characters in the terminal, but
  no chance (`a random number`), nothing can appear while the game runs (`every second, add a
  rock`), a hit cannot change a single value (`lose a life`), and a period is fixed when compiled.
  No colours, no window, no sound. Played only on macOS so far.
- **No network.** No server yet.
- Calculations work on whole numbers only (no text, no decimals), and cannot read a collection.
- Rules are re-applied in full after every change: each rule costs one pass over its collection.
- No summaries of a calculation (`total of price times stock`), no grouping
  (`average salary per city`), no loops written by the programmer.
- A change applies to the records a condition selects; there is no "do this, then that"
  within one capability, and capabilities cannot call each other.
- Remembering is a growing command log, never compacted. Nothing else touches files or the network.
- Rankings with ties are broken by storage order unless insertion order is declared.
- Non-unique lookups scan. Sorted and top-N output sorts everything on every call.
- The planner decides from declared capabilities, not from measured workload.

## How this differs from the conversation it came from

Intent started from a long spoken research conversation about an "intent-driven" language.
Where this build departs from that discussion:

- The conversation leaned toward an AI front end for fluid phrasing. This shows a lexicon
  plus the never-drop rule gets real fluidity deterministically. AI becomes an optional
  writer of Intent text, checked by the same compiler.
- "Should the compiler ask or assume?" is answered with four tiers, each reported
  differently: declared, inferred from use (`age` is multiplied, so it is a number), assumed
  from a naming convention (`email` is text; printed as a note), and asked.
- "Is it doable / has it been done?" Automatic data-structure selection is old: SETL in the
  1970s–80s, and later synthesis work such as RelC and Cozy and adaptive collections such
  as Chameleon; Inform 7 and Attempto are deterministic natural-language-like languages
  (names from memory — verify before citing). The part I did not find a match for is the
  combination: fluid sentences, refusal to guess, representation chosen from declared
  capabilities with source-line reasons, straight to LLVM. That is a combination claim,
  not a claim that any single piece is new.

## Stress-tested by a second model

[gemini-build/](gemini-build/README.md) holds eight experiments another model wrote *against*
the language without touching the compiler: an exchange, a Collatz machine, a ledger, a
time-series store, a fractal renderer, a pipe server. It found eight real bugs; all are fixed
and pinned by tests (`TestStressFindings`, `TestService`). My reading of what those
experiments say about the language is in [gemini-build/REVIEW.md](gemini-build/REVIEW.md).
Its `build-04` test now fails on purpose: it asserts the old buggy behaviour.

## Where it can go next

Done so far: definitions, spelling tolerance, rankings, remembering, text tests, relationships,
single values, values that depend on a condition, standing rules, time, keys and a board.
The stress experiments show the same thing from eight directions: people fall back to
arithmetic tricks when the language cannot *say* something. So, in order:

1. **What a snake game still needs.** Chance (`a random number between 1 and 30`), rules that
   add and remove records (`every tick, add a segment at the head`), conditions over another
   collection (`when any segment is at the head`), several steps in one sentence.
2. **Faces.** The program stays the same and one sentence says how it meets the world:
   `Serve this on the web.` turns every capability into an endpoint; a window instead of
   terminal characters is another face.
3. **Summaries per owner and per group.** `customers with more than 3 orders`,
   `the total of the lines of each order`, `the average salary for each city`.
4. **Rules on data.** `Stock is never under 0.` checked on every add and change, with the
   refusal reported, so a guarded change no longer fails silently.
5. **Capabilities made of steps.** `To check out: decrease the stock, then add an order.` and
   `repeat until nothing changes`.
6. **More kinds of value.** Decimals and money, dates, yes/no, "may be missing"; properties
   defined by a calculation (`A line's cost is its price times its quantity.`).
7. **Better structures.** An index on linking properties, an ordered index for ranges and
   top-N, tombstones so ordered removal stops being O(n).
8. **Rules that only look where something changed**, instead of a full pass each time.
9. **A model that turns loose speech into Intent text**, with `check` showing the reading
   before anything is compiled.

## Layout

```
intent                  launcher
intentc/lexicon.py      the knowledge system: phrases -> concepts, filler, conventions
intentc/source.py       text -> sentences of tokens with positions
intentc/parser.py       sentences -> Intent IR, or a pointed question
intentc/ir.py           Intent IR and its canonical one-line form
intentc/check.py        type inference and open decisions
intentc/plan.py         representation discovery, with reasons
intentc/interp.py       reference interpreter (the meaning)
intentc/llvm.py         Intent IR + plan -> LLVM IR
intentc/play.py         playing in a terminal with the reference interpreter
tests/                  phrasings, questions, planner, spelling, definitions, apps, native-vs-reference
bench/bench.py          the table above
examples/               customers, questions, leaderboard, todo, shop, store, calculator, arcade, dodge
```
