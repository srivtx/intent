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
37 tests pass.

This shows the backend agrees with the reference. It does not show the reference agrees
with what you meant; that is what `check` is for — read the right-hand column.

## What this version cannot do

- One collection per sentence; no relationships between collections.
- Whole numbers (64-bit, wrapping) and text only. No decimals, dates, or missing values.
- Text may not contain commas (the command format is comma-separated).
- Conditions are a flat list of `and` or of `or`; no grouping.
- No constraints other than uniqueness; a unique property cannot be changed in bulk.
- Division only by a fixed non-zero number.
- The vocabulary is fixed. `older than 30` is an unknown word, because nothing tells the
  compiler that "older" is about age.
- Non-unique lookups scan. Sorted output sorts on every call.
- The planner decides from declared capabilities, not from measured workload.

## How this differs from the conversation it came from

The source discussion is `intent_language_research_conversation.txt`. Where this build
departs from it:

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

## Next steps, in the order I would do them

1. **Definitions as the extension mechanism.** `An adult is a customer whose age is at
   least 18.` and `"older than" means age over.` This grows the vocabulary from inside the
   program and is the cheapest large gain in fluidity.
2. **Constraints that follow the data.** `Age is never negative.` checked on every add and
   update, then the conversation's change experiment: tighten a constraint and report
   exactly which capabilities are affected.
3. **Relationships.** `Each order belongs to a customer.` This is where representation
   choice gets much richer (joins, foreign indexes).
4. **Better structures.** An ordered index for range and sorted queries, tombstones so
   ordered removal stops being O(n), and counters so the choice can follow real workload.
5. **AI as a writer.** A model turns loose speech into Intent text; `check` shows the
   reading for confirmation before anything is compiled.

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
tests/                  phrasings, questions, planner, native-vs-reference
bench/bench.py          the table above
examples/               customers.intent, questions.intent
```
