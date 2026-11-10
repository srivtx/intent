# Intent language guide

> Experimental. Everything here compiles today; [examples/tour.intent](../examples/tour.intent)
> is this guide as one program. When in doubt, run `./intent check yourfile.intent` and read
> the right-hand column: it shows exactly how each sentence was understood.

A program is a list of sentences. Some **describe information**, some **teach words**, and the
rest are **capabilities**: things the compiled program can be asked to do, any number of times.
Sentences end with `.` or `?`. Lines starting with `#` are comments. Capitals, filler words
("please", "basically", "I want to") and most word orders do not matter.

## Describing information

```
Members have a name, an email, an age (number), points and several badges (text).
```

Any of these also works: `Members is a collection.` followed by `Each member has ...`, or
`Members is a collection where each member has ...`.

| You write | Meaning |
|---|---|
| `a name`, `an email` | one value; text or number is worked out from the name and from how it is used |
| `an age (number)`, `a code (text)` | one value of that type |
| `points`, `units`, `cents` | one number (plural count words) |
| `badges`, `several badges`, `a list of badges` | several values per member |
| `a member` (when Members is a collection) | this record belongs to a member |

If nothing decides whether a property is text or a number, the compiler asks.

### Rules

```
Emails are unique.                      No two members share the same email.
Reject duplicates.                      If a member already exists, replace it.
Keep members in the order they were added.
Each visit belongs to a member.
When a member is removed, remove its visits.      A member with visits cannot be removed.
```

A rule that names no collection applies to the one just described. The compiler asks for a
rule whenever the program makes it matter: what a clash does once something is unique and can
be added, and what happens to visits once members can be removed.

## Teaching it words

```
"older than" means age over.
An adult is a member whose age is at least 18.
A regular is an adult whose points is over 100.
An open task is a task whose done is 0.
"oldest" means with the largest age.
```

A taught word is replaced by its meaning before the sentence is read. A word can have only
one meaning; a two-word definition such as "even stone" may reuse a built-in word.

## Capabilities

Each becomes a command of the compiled program. Put `name:` in front to choose the command
name; otherwise one is derived (`find-by-email`). `a given X` becomes an argument.

**Add, find, remove**
```
join: add a member.
Find a member by email.
leave: remove a member by email.
Remove the members whose points is under a given floor.
Keep only the visits whose cost is at least 1.
Remove all members.
award: add a badge to a given member.
```

**Show**
```
Show the members.
Show the names and ages of the adults.
Show the members sorted by age, largest first.
Show the top 3 members by points.
Show the name of the oldest member.
Show the first 5 members.                (needs a declared order, or "sorted by")
```

**Conditions** — join with `and` or with `or` (not both in one sentence)
```
whose age is over 30          at least / at most / under / exactly / not
whose age is between 18 and 30           whose age is not between 18 and 30
whose points is even                     whose age times 2 is over points
whose name starts with "A"               contains / ends with / does not contain
whose email is a given email
```

**Summaries**
```
How many members are there?
What is the average age of the regulars?
What is the largest cost?                total / smallest / count
```

**Change**
```
For every member, increase the points by 10.
Double the points of members whose age is under 18.
Increase the cost by 10 percent for visits whose cost is over a given limit.
Set the points to 0.                     halve / triple / multiply by / decrease by / mod
```

**Across collections** — from a record to what it belongs to
```
Show the visits of a given member.
What is the sum of the cost of visits for a given member?
Show the ticket and the member's name of visits sorted by ticket.
Show the visits whose member's age is under 18.
```

**Plain calculations**
```
double: take a number n and return n times 2.
```

## What happens when it does not understand

- **An unknown word stops compilation** and is pointed at. Nothing is skipped.
- **A misspelling** is accepted only if exactly one known word that close makes the whole
  sentence readable. Each correction is reported.
- **A sentence with two readings is a question**, with both readings named:
  `Show the customers by age.` (sorted by age, or looked up by a given age?)
- **An assumption is a note**: `assuming "name" is text, from its name`.

## Using the compiled program

```bash
./intent build examples/tour.intent -o build/tour
```

```bash
./build/tour members.log
```

One command per line: the command name, a space, then comma-separated arguments
(`join Ana,ana@x.io,31,0`). `help` lists every command. The optional file name makes the
program remember: changes are logged there and replayed on the next start.

Answers: records print as comma-separated values; `none` when nothing matches a lookup;
`duplicate email`, `no such member`, `member still has visits` when a rule refuses;
`error: ...` when the command itself is malformed.

## Not yet

Decimals, dates and yes/no values; values that depend on a condition ("... if ..., otherwise
..."); properties defined by a calculation; summaries per owner or per group
(`members with more than 3 visits`); capabilities made of several steps; mixing `and` with
`or`; commas inside text. See the [README](../README.md#what-this-version-cannot-do).
