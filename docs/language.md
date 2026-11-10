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

## Time, keys and a board

Three more kinds of sentence make a program that runs by itself and can be played.

**Time.** Something that happens again and again, without anyone calling it:
```
Every 150 milliseconds, the y of each rock increases by 1.
Every second, the score goes up by 1.
The score increases by 2 every second.
4 times a second, remove the rocks whose y is over 12.
```
Things due at the same moment happen in the order written; then the standing rules settle.

**Keys.** `left`, `right`, `up`, `down`, `space`, `enter`, and any letter or digit:
```
When the left key is pressed, the column decreases by 1 if the column is over 1.
When the player presses space, the score doubles.
```

**The board**, and what is on it. Places count from 1 at the top left; whatever is off the
board is not drawn; later sentences draw over earlier ones.
```
The board is 30 wide and 12 high.
Draw each rock at its x and y as "#".
Draw "@" at the column and the row.
Show the score above the board.
```

**What is there at the start, and when it ends:**
```
Start with a rock at x 4, y 1.
The game is over when any rock has an x equal to the column and a y equal to the row.
The game ends when the lives are under 1.
```
While the game is over, time and keys do nothing.

**Colour.** A drawing can have one: red, green, yellow, blue, magenta (or purple, pink), cyan,
white, grey.
```
Draw each rock at its x and y as a red "#".
Draw a green "@" at the column and the row.
Draw "*" in yellow at the food x and the food y.
```
Colour is shown while playing in a terminal. The `screen` command stays plain text.

**Chance.** Both ends can come up:
```
When space is pressed, the column becomes a random number between 1 and 30.
Every second, the wind increases by a random number from -1 to 1.
```
The program keeps one number and each draw moves it on by a fixed step, so the same start gives
the same draws. `seed 7` sets the start. Chance cannot be used in a standing rule, in what is
drawn, or in when the game ends: those are looked at again and again. Draw the number at one
moment and keep it in a single value.

**Records that appear.** In a sentence that happens by itself, `add` makes a record; every
property needs a value, from numbers, text, single values and chance:
```
Every second, add a rock whose x is a random number between 1 and 30 and whose y is 1.
When space is pressed, add a shot with x the column and y 11.
Every second, if the score is over 10, add a rock whose x is the column and whose y is 1.
```
If a unique property would clash, the new record is passed over (or replaces the old one, if
the program says `Replace duplicates.`). Removing already works the same way:
`Every second, remove the rocks whose y is over 12.`

**A condition about other records.** A sentence about one thing can depend on another:
```
Every 100 milliseconds, if any rock has an x equal to the column and a y equal to the row, the lives decrease by 1.
When space is pressed, if no shot has a y over 10, add a shot with x the column and y 11.
Whenever any rock has a y over 12, the alarm becomes "low".
```
`any` and `no` are the two forms. A sentence that goes on to speak about those same records
(`if any rock's y is over 12, its y becomes 1`) is about each of them, as before.

Inside such a condition the record the sentence is about can be spoken of too, so records of
two collections can meet:
```
Every 60 milliseconds, set the hit of the aliens to 1 if any shot has an x equal to the alien's x and a y equal to its y.
Every 60 milliseconds, remove the aliens if any shot has the same x and y.
Every 60 milliseconds, remove the shots that have the same x and y as an alien.
Every second, remove the aliens whose x is the x of any shot.
Every second, remove the bombs that do not have the same x as an alien.
```
After a comparison, `its x` and `the alien's x` are the x of the record the sentence is about;
`the same x` is short for "an x equal to its x". If the sentence is not about any one record
(`set the lives to 0 if any rock has an x equal to its y`) the compiler asks whose it is.

**Counting inside a sentence.** Wherever a number can stand, so can a count, a total, or the
largest or smallest of a property, over all records of a collection or those a condition picks:
```
When space is pressed, add a shot whose x is the column and whose y is 13 if the number of shots is under 3.
Every second, increase the score by the number of aliens whose hit is 1.
Every second, set the weight to the total of the size of the rocks whose y is over 5.
Every second, set the top to the smallest y of the cells.
The game is over when the number of aliens is 0.
Every second, remove the cells if the number of cells with the same y is 10.
Every second, set the gap to the largest y of the cells where the number of cells with the same y is 10.
```
`the number of`, `the count of`; `the total of`, `the sum of`; `the largest`, `the highest`,
`the smallest`, `the lowest`. The largest or smallest of no records is 0. A count that is
asked for (`How many cells have a y of 3?`) is still a command, and `the cell with the largest y`
is still a ranking.

When a change asks about the other records of the collection it changes, as in the last two
lines, every record is asked first and only then do any change, so the answer never depends on
the order the records are kept in. A new value may not be worked out from the very property
that is being changed in the other records (the compiler says so); put it in a single value first.

**Word order.** A condition can stand in front, behind, or both:
```
Every second, if the hurt is 1, remove the bombs whose y is at least 14.
Every second, remove the bombs whose y is at least 14 if the hurt is 1.
Every second, increase the y of the cells whose y is under 1 by 1 if the clear is 1.
```

**Several steps.** `and then` puts steps in order within one moment:
```
When space is pressed, add a shot with x the column and y 11, and then the score decreases by 1.
```
It is the same as writing two sentences with the same beginning. A condition in front of
several steps is a question (does it go with all of them?), so give each step its own.

**Playing again.** `restart` puts everything back as it was at the start (chance keeps going,
so the next game is a new one). In a terminal, a game that is over stays on show: enter plays
again, `q` stops.

Run the compiled program in a terminal and it is played: the real clock and the real keyboard
drive it, and `q`, `Esc` or `Ctrl-C` stops. Over a pipe it takes commands instead, and time,
keys and the board are three more commands, so a game can be scripted and tested exactly:
```
wait 450          let 450 milliseconds pass
press left        as if the left key was pressed
screen            print the board
picture           the board, then "~", then one letter per cell for its colour (for a page to paint)
seed 7            where chance starts (only if the program uses chance)
restart           back to the start (only if the game can end)
```
With a journal file, a game played by hand is written down as these same commands, including
the seed the clock gave it, so it can be replayed exactly.
None of the words used here is reserved: `the high score` and `each ticket has a key` are
still ordinary names.

While playing, the program uses a screen of its own and gives the terminal back exactly as it
was, however it stops; the last board stays visible. A terminal too small for the board is
refused with the size it needs.

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

## On the network, and in a window

```bash
./build/tour serve 8080 members.log
```

The program now takes its commands from the network instead of stdin: the same commands, the
same answers, the same journal. Callers are answered one command at a time, in the order the
commands arrive.

| How it is asked | What happens |
| --- | --- |
| a plain connection, one command per line | each answer comes back on that connection |
| `GET /join/Ana,ana@x.io,31,0` | that one command runs (`%40` and the like are decoded; the first `/` after the name parts it from its arguments) |
| `POST /` with commands in the body | every line runs; the answers are the body of the reply |
| `GET /` | a page: a console, or the board in colour |

`serve` listens on this machine only; `serve-public 8080` on every address. There is room for
64 callers at once and 8 KB per request. `./intent serve file.intent --port 8080` serves from
the reference interpreter in exactly the same way (without a journal), and
`./intent window file.intent` serves on a free port and opens the page in a window of its own.

A program with a board lives in real time while it is served, as it does in a terminal: the
clock becomes `wait` commands (written to the journal, with the seed, so the game can be
replayed). The page asks for `picture` about 25 times a second, paints each cell in its colour
(a `#` as a filled block), and sends `press <key>` for the keys the program listens to; when
the game is over, Enter sends `restart`. Everyone who opens the page sees the same game.

## Not yet

Decimals, dates and yes/no values; text in calculations; a random number between two values
that are not written as numbers; a game that speeds up; sound and pictures; calling other servers;
a record of the same collection "other than this one";
properties defined by a calculation; summaries per owner or per group
(`members with more than 3 visits`); named capabilities made of several steps; mixing `and` with
`or`; commas inside text. See the [README](../README.md#what-this-version-cannot-do).
