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

**Plain calculations** — nothing stored; numbers in, a number out
```
double: take a number n and return n times 2.
Sum: take a number a and a number b and return a plus b.
Area: take a width and a height and return width times height.
```

**Values that depend on a condition**
```
Bigger: take a and b and return a if a is over b, otherwise b.
Sign: take n and return 1 if n is over 0, otherwise -1 if n is under 0, otherwise 0.
Grade: set the grade to "pass" if the score is at least 50, otherwise "fail".
```
`otherwise`, `else` and `or else` mean the same. Half a decision (`return a if a is over b.`)
is a question: *and what if not?*

Dividing by something that might be zero is also a question, and the answer is a sentence:
```
Share: take a and b and return a divided by b if b is not 0, otherwise 0.
```

## Single values

Not everything is a collection. A program can keep single values:
```
The score is a number.                   starts at 0 (reported as a note)
The best starts at 0.
The lives start at 3.
The mood is text that starts at "calm".
The limit is 100.
```
They are shown and changed with the same sentences as properties, and any other sentence can
use them:
```
Hit: increase the score by a given amount.
Restart: set the score to 0, set the lives to 3.
Status: show the score, the best and the lives.
Rivals: show the names of players whose points are over the best.
```
Single values are remembered between runs exactly like records.

## Standing rules

A capability runs when someone calls it. A rule is never called: it is applied after every
change, and again until nothing moves, so rules may build on each other in any order.
```
When the score is over the best, the best becomes the score.
Whenever a player's points are at least 100, their rank becomes "gold".
As soon as a player's points are under 0, remove them.
The level is always 3 if the score is at least 50, otherwise 2 if the score is at least 10, otherwise 1.
```
A sentence is a rule when it starts with `when`, `whenever`, `as soon as`, `every time`, or
says `always`, and has no name. Give it a name (`Promote: when ...`) and it is an ordinary
capability again.

The compiler refuses a rule that could never come to rest (`When the lives are under 3,
increase the lives by 1.`) and a rule that waits for `a given` value. Two rules that undo each
other are caught when the program runs: `error: the rules keep changing each other`.

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

Decimals, dates and yes/no values; text in calculations; time ("every second"), a screen,
keys or a network; properties defined by a calculation; summaries per owner or per group
(`members with more than 3 visits`); capabilities made of several steps; mixing `and` with
`or`; commas inside text. See the [README](../README.md#what-this-version-cannot-do).
