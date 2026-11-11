"""Intent IR: the canonical meaning of a program. Everything downstream reads only this.

Expressions are tuples:
    ('num', n) | ('str', s) | ('field', name) | ('param', name) | ('bin', op, a, b)   op in mul add sub div rem
    ('pfield', ref, name)   a property of the record this one belongs to (ref is the linking property)
    ('value', name)         a single value the program keeps ("the score")
    ('if', cond, a, b)      a when cond holds, otherwise b
    ('rand', lo, hi)        a whole number from lo to hi, drawn by chance (see CHANCE_*)
    ('dec', n)              a decimal number, kept as n hundredths: 12.50 is ('dec', 1250)
    ('cents', e)            put in by the checker: the whole number e as hundredths (e * 100)
                            the checker also turns * and / on decimals into the operators dmul
                            (a * b / 100) and rdiv (a / b), both rounded to the nearest hundredth
    ('agg', fn, coll, field, cond)   fn in count sum max min, over the records of coll that satisfy cond
                            (field is None for count; the largest or smallest of nothing is 0)
    ('outer', name)         inside a condition about other records: a property of the record the
                            sentence itself is about ("... any shot has an x equal to the alien's x")
Conditions are tuples:
    ('cmp', op, a, b)   op in gt ge lt le eq ne
    ('and', a, b) | ('or', a, b)
    ('any', coll, cond) | ('none', coll, cond)   cond holds for some / for no record of another collection
"""
import json
import math
from dataclasses import dataclass, field as _f


@dataclass
class Field:
    name: str
    type: str = None            # 'int' | 'text' | None (not yet known)
    unique: bool = False
    line: int = 0
    how: str = 'declared'       # declared | inferred | assumed
    unique_line: int = 0
    ref: str = None             # the collection this property points into ("each order belongs to a customer")
    on_removed: str = None      # what happens to these records when that one is removed: cascade | restrict
    on_removed_line: int = 0
    init: object = None         # a single value's starting value
    start_line: int = 0         # the line that gave a single value its starting value, 0 if none did
    dec: bool = False           # a number with two decimal places, kept in hundredths (type stays 'int')


@dataclass
class Collection:
    name: str                   # singular, lower-case: 'customer'
    label: str                  # as the programmer wrote it: 'Customers'
    line: int = 0
    fields: dict = _f(default_factory=dict)
    ordered: bool = False
    ordered_line: int = 0
    on_dup: str = None          # None | 'reject' | 'replace'
    on_dup_line: int = 0
    expect: int = None          # "Expect about 1,000,000 customers.": how many the planner should plan for
    expect_line: int = 0

    def unique_fields(self):
        return [f for f in self.fields.values() if f.unique]


@dataclass
class Task:
    name: str
    kind: str                   # add find remove_key remove_where update list agg calc make draw end seed
    coll: str = None
    line: int = 0
    text: str = ''
    named: bool = False
    assigns: list = _f(default_factory=list)     # update: [(field, expr)]
    where: tuple = None
    fields: list = None                             # list: projected properties, None = whole record
    order: tuple = None                             # list: (field, descending)
    limit: int = None                               # list: at most this many records
    fn: str = None                                  # agg
    field: str = None                               # agg
    key: str = None                                 # find / remove_key
    expr: tuple = None                              # calc
    params: list = _f(default_factory=list)      # names, in argument order
    ptypes: dict = _f(default_factory=dict)
    on: tuple = None                                # happens by itself: ('every', milliseconds) | ('key', name)
    at: tuple = None                                # draw: (x, y), counted from 1 at the top left
    glyph: object = None                            # draw: the one character shown there, or ('field' | 'value', name):
                                                    #   the first character of that text, if it is a plain one
    colour: object = None                           # draw: the name of its colour, None, or ('field' | 'value', name)
    dec: bool = False                               # calc: the result is a decimal number
    pdec: set = _f(default_factory=set)          # the parameters that are decimal numbers
    ranges: list = _f(default_factory=list)      # seed: [(property, lowest, highest)], a record for each combination
    spell: bool = False                             # draw: the whole text, one character a cell, rightward ("Write")


STATE = '(values)'              # the hidden one-record collection that holds the program's single values


@dataclass
class Figure:
    """A picture drawn by hand: rows of characters, and the colour some of them stand for."""
    name: str
    rows: list                  # strings, top row first
    legend: dict                # character -> colour name or "#rrggbb"; None: that character draws nothing
    line: int = 0

    def cells(self):
        """[(across, down, character drawn, colour or None)], counted from 0 at the top left."""
        out = []
        for j, row in enumerate(self.rows):
            for i, ch in enumerate(row):
                if ch in self.legend:
                    if self.legend[ch] is not None:
                        out.append((i, j, '#', self.legend[ch]))
                elif ch not in ' .':
                    out.append((i, j, ch, None))
        return out


@dataclass
class Program:
    collections: dict = _f(default_factory=dict)
    tasks: list = _f(default_factory=list)
    rules: list = _f(default_factory=list)       # standing rules: applied after every change until nothing moves
    events: list = _f(default_factory=list)      # what happens as time passes or a key is pressed
    draws: list = _f(default_factory=list)       # what is on the board, later ones on top
    ends: list = _f(default_factory=list)        # the game is over while any of these holds for any record
    seeds: list = _f(default_factory=list)       # records that are there from the start
    board: tuple = None                             # (width, height) in characters
    board_line: int = 0
    figures: dict = _f(default_factory=dict)     # name -> Figure
    background: str = None                          # the colour where nothing is drawn, in a picture
    above: list = _f(default_factory=list)       # single values shown over the board
    below: list = _f(default_factory=list)

    def work(self):
        """Everything that changes or reads data when it runs."""
        return self.tasks + self.rules + self.events

    def looks(self):
        """Sentences that are not run as commands: what is drawn, when the game is over, what is there at first."""
        return self.draws + self.ends + self.seeds

    def timers(self):
        return [t for t in self.events if t.on[0] == 'every']

    def keys(self):
        """The keys the program listens to, in the order first mentioned."""
        out = []
        for t in self.events:
            if t.on[0] == 'key' and t.on[1] not in out:
                out.append(t.on[1])
        return out

    def real(self):
        """The collections the programmer declared (not the hidden one that holds single values)."""
        return {n: c for n, c in self.collections.items() if n != STATE}

    def field_names(self):
        return {f for c in self.collections.values() for f in c.fields}

    def children_of(self, name):
        """[(collection, linking property)] for every collection whose records belong to `name`."""
        return [(c, f) for c in self.collections.values() for f in c.fields.values() if f.ref == name]

    def key_of(self, name):
        """The one unique property that identifies a record of `name`, or None."""
        u = self.collections[name].unique_fields()
        return u[0] if len(u) == 1 else None


@dataclass
class Diag:
    level: str                  # error | question | note
    msg: str
    line: int = 0
    start: int = 0
    end: int = 0
    label: str = ''
    hint: str = ''


OPSYM = {'mul': '*', 'add': '+', 'sub': '-', 'div': '/', 'rem': 'mod', 'dmul': '*', 'rdiv': '/'}


def fmt_dec(n):
    """Hundredths as they are written and printed: 1250 -> 12.50, -5 -> -0.05."""
    return f'{"-" if n < 0 else ""}{abs(n) // 100}.{abs(n) % 100:02d}'


def rdiv(a, b):
    """a / b rounded to the nearest whole number, halves away from zero (b is not 0)."""
    q = (abs(a) + abs(b) // 2) // abs(b)
    return -q if (a < 0) != (b < 0) else q
CMPSYM = {'gt': '>', 'ge': '>=', 'lt': '<', 'le': '<=', 'eq': '==', 'ne': '!=',
          'has': 'contains', 'nhas': 'does not contain', 'starts': 'starts with',
          'nstarts': 'does not start with', 'ends': 'ends with', 'nends': 'does not end with'}
TEXT_OPS = ('has', 'nhas', 'starts', 'nstarts', 'ends', 'nends')
NEGATE = {'gt': 'le', 'ge': 'lt', 'lt': 'ge', 'le': 'gt', 'eq': 'ne', 'ne': 'eq',
          'has': 'nhas', 'nhas': 'has', 'starts': 'nstarts', 'nstarts': 'starts', 'ends': 'nends', 'nends': 'ends'}


def binop(op, a, b):
    """Build a binary expression in canonical operand order (constant last for * and +)."""
    if op in ('mul', 'add') and a[0] == 'num' and b[0] != 'num':
        a, b = b, a
    return ('bin', op, a, b)


def negate(c):
    if c[0] == 'cmp':
        return ('cmp', NEGATE[c[1]], c[2], c[3])
    if c[0] in ('any', 'none'):
        return ('none' if c[0] == 'any' else 'any', c[1], c[2])
    if c[0] == 'and':
        return ('or', negate(c[1]), negate(c[2]))
    return ('and', negate(c[1]), negate(c[2]))


def fmt_expr(e, top=True):
    k = e[0]
    if k == 'num':
        return str(e[1])
    if k == 'str':
        return json.dumps(e[1])
    if k == 'field':
        return e[1]
    if k == 'param':
        return f'<{e[1]}>'
    if k == 'pfield':
        return f'{e[1]}.{e[2]}'
    if k == 'value':
        return e[1]
    if k == 'rand':
        return f'random({e[1]}..{e[2]})'
    if k == 'outer':
        return f'its {e[1]}'
    if k == 'dec':
        return fmt_dec(e[1])
    if k == 'cents':
        return fmt_expr(e[1], top)
    if k == 'fn':
        return f'{e[1][1:] if e[1] in ("dsqrt", "dround", "dtrunc") else e[1]}({fmt_expr(e[2])})'
    if k == 'agg':
        what = f'{e[2]}s' if e[1] == 'count' else f'{e[3]} of {e[2]}s'
        return f'{e[1]}({what}{" where " + fmt_cond(e[4]) if e[4] else ""})'
    if k == 'if':
        s = f'{fmt_expr(e[2], False)} if {fmt_cond(e[1])} else {fmt_expr(e[3], False)}'
        return s if top else f'({s})'
    s = f'{fmt_expr(e[2], False)} {OPSYM[e[1]]} {fmt_expr(e[3], False)}'
    return s if top else f'({s})'


def fmt_cond(c, top=True):
    if c[0] == 'cmp':
        return f'{fmt_expr(c[2])} {CMPSYM[c[1]]} {fmt_expr(c[3])}'
    if c[0] in ('any', 'none'):
        s = f'{"any" if c[0] == "any" else "no"} {c[1]} has {fmt_cond(c[2], False)}'
        return s if top else f'({s})'
    s = f'{fmt_cond(c[1], False)} {c[0]} {fmt_cond(c[2], False)}'
    return s if top else f'({s})'


def canon(t):
    """One line that states exactly what a task means. Equal meaning <=> equal string."""
    w = f' where {fmt_cond(t.where)}' if t.where else ''
    if t.coll == STATE:
        if t.kind == 'update':
            return 'set ' + ', '.join(f'{f} = {fmt_expr(e)}' for f, e in t.assigns) + w
        return 'show ' + ', '.join(t.fields or ['every value']) + w
    if t.kind == 'update':
        return f'update {t.coll}: ' + ', '.join(f'{f} = {fmt_expr(e)}' for f, e in t.assigns) + w
    if t.kind == 'add':
        return f'add {t.coll}'
    if t.kind == 'make':
        return f'new {t.coll}: ' + ', '.join(f'{f} = {fmt_expr(e)}' for f, e in t.assigns) + w
    if t.kind == 'find':
        return f'find {t.coll} by {t.key}'
    if t.kind == 'remove_key':
        return f'remove {t.coll} by {t.key}'
    if t.kind == 'remove_where':
        return f'remove {t.coll}{w}'
    if t.kind == 'list':
        what = ', '.join(t.fields) if t.fields else 'all'
        o = f' sorted by {t.order[0]} {"descending" if t.order[1] else "ascending"}' if t.order else ''
        lim = f', first {t.limit}' if t.limit is not None else ''
        return f'list {what} of {t.coll}{w}{o}{lim}'
    if t.kind == 'agg':
        return f'{t.fn}({t.field or ""}) of {t.coll}{w}'
    if t.kind == 'calc':
        return f'calc({", ".join(t.params)}) = {fmt_expr(t.expr)}'
    raise ValueError(t.kind)


# sin of 0, 1, ... 90 degrees in millionths. Written out so that every machine, and the compiled program,
# agree on every digit; between whole degrees the value is interpolated in a straight line.
SINE = [0, 17452, 34899, 52336, 69756, 87156, 104528, 121869, 139173, 156434, 173648, 190809, 207912, 224951, 241922, 258819, 275637, 292372, 309017, 325568, 342020, 358368, 374607, 390731, 406737, 422618, 438371, 453990, 469472, 484810, 500000, 515038, 529919, 544639, 559193, 573576, 587785, 601815, 615661, 629320, 642788, 656059, 669131, 681998, 694658, 707107, 719340, 731354, 743145, 754710, 766044, 777146, 788011, 798636, 809017, 819152, 829038, 838671, 848048, 857167, 866025, 874620, 882948, 891007, 898794, 906308, 913545, 920505, 927184, 933580, 939693, 945519, 951057, 956305, 961262, 965926, 970296, 974370, 978148, 981627, 984808, 987688, 990268, 992546, 994522, 996195, 997564, 998630, 999391, 999848, 1000000]


def sine(a):
    """The sine of a hundredths of a degree, in hundredths, rounded to the nearest (half away from zero)."""
    a %= 36000
    q, r = divmod(a, 9000)
    if q % 2:
        r = 9000 - r
    k, f = divmod(r, 100)
    s = SINE[k] * 100 + (SINE[min(k + 1, 90)] - SINE[k]) * f      # in hundred-millionths, never negative
    s = (s + 500000) // 1000000
    return -s if q >= 2 else s


def root(n):
    """The whole square root of n, rounded down (0 below 0, which a program is never allowed to reach)."""
    return math.isqrt(n) if n > 0 else 0


def droot(n):
    """The square root of a decimal kept in hundredths, in hundredths, rounded to the nearest."""
    if n <= 0:
        return 0
    m = n * 100
    s = math.isqrt(m)
    return s + 1 if m - s * s > s else s


FNNAME = {'sqrt': 'the square root of', 'dsqrt': 'the square root of', 'sin': 'the sine of', 'cos': 'the cosine of',
          'abs': 'the absolute value of', 'round': 'the nearest whole number to', 'dround': 'the nearest whole number to',
          'trunc': 'the whole part of', 'dtrunc': 'the whole part of'}


def inked(prog):
    """Is anything on the board drawn in a colour?"""
    return any(d.colour or (isinstance(d.glyph, tuple) and d.glyph[0] == 'figure' and
                            any(prog.figures[d.glyph[1]].legend.values())) for d in prog.draws)


def fmt_glyph(g):
    return f'"{g}"' if isinstance(g, str) else {'field': 'its ', 'value': 'the ', 'figure': 'a '}[g[0]] + g[1]


def draw_char(text):
    """What a text draws on the board: its first character, if that is a plain one (! to ~); else nothing."""
    b = text.encode()[:1]
    return chr(b[0]) if b and 33 <= b[0] <= 126 else None


def walk_expr(e):
    """Every value inside e, including those inside the condition of an "if"."""
    yield e
    if e[0] == 'cents':
        yield from walk_expr(e[1])
    elif e[0] == 'fn':
        yield from walk_expr(e[2])
    elif e[0] == 'bin':
        yield from walk_expr(e[2])
        yield from walk_expr(e[3])
    elif e[0] == 'if':
        yield from walk_cond_exprs(e[1])
        yield from walk_expr(e[2])
        yield from walk_expr(e[3])


def task_exprs(t):
    """Every value a task computes or compares, at any depth."""
    tops = [e for _, e in t.assigns] + ([t.expr] if t.expr else []) + list(t.at or ()) + \
        [x for x in (t.glyph, t.colour) if isinstance(x, tuple) and x[0] != 'figure']
    return [e for top in tops for e in walk_expr(top)] + list(walk_cond_exprs(t.where))


def task_conds(t):
    """Every comparison a task makes: its own condition and those inside "if" values."""
    yield from cond_cmps(t.where)
    for e in task_exprs(t):
        if e[0] == 'if':
            yield from cond_cmps(e[1])


def walk_cond_exprs(c):
    """Every value compared in c. What is said about another collection ("any rock ...") is not
    included: its properties are that collection's, so it is walked on its own (see cond_anys)."""
    if c is None or c[0] in ('any', 'none'):
        return
    if c[0] == 'cmp':
        yield from walk_expr(c[2])
        yield from walk_expr(c[3])
    else:
        yield from walk_cond_exprs(c[1])
        yield from walk_cond_exprs(c[2])


def cond_cmps(c):
    if c is None or c[0] in ('any', 'none'):
        return
    if c[0] == 'cmp':
        yield c
    else:
        yield from cond_cmps(c[1])
        yield from cond_cmps(c[2])


def cond_anys(c):
    """The parts of a condition that look into another collection."""
    if c is None or c[0] == 'cmp':
        return
    if c[0] in ('any', 'none'):
        yield c
    else:
        yield from cond_anys(c[1])
        yield from cond_anys(c[2])


def conjuncts(c):
    """The parts of a condition that all have to hold."""
    if c is None:
        return
    if c[0] == 'and':
        yield from conjuncts(c[1])
        yield from conjuncts(c[2])
    else:
        yield c


def lookups(t):
    """Every place a task looks into a collection from inside a sentence about something else:
    [(the collection the looking is done from, the node)], inner ones after the one they sit in.
    A node is ('any'|'none', coll, cond) or ('agg', fn, coll, field, cond)."""
    out = []

    def from_cond(c, frm):
        if c is None:
            return
        if c[0] == 'cmp':
            from_expr(c[2], frm)
            from_expr(c[3], frm)
        elif c[0] in ('any', 'none'):
            out.append((frm, c))
            from_cond(c[2], c[1])
        else:
            from_cond(c[1], frm)
            from_cond(c[2], frm)

    def from_expr(e, frm):
        if e[0] == 'bin':
            from_expr(e[2], frm)
            from_expr(e[3], frm)
        elif e[0] == 'if':
            from_cond(e[1], frm)
            from_expr(e[2], frm)
            from_expr(e[3], frm)
        elif e[0] == 'agg':
            out.append((frm, e))
            from_cond(e[4], e[2])
    for _, e in t.assigns:
        from_expr(e, t.coll)
    for e in ([t.expr] if t.expr else []) + list(t.at or ()):
        from_expr(e, t.coll)
    from_cond(t.where, t.coll)
    return out


def looks_into(t):
    """The collections a task reads from inside its conditions and values (see lookups)."""
    return {n[2] if n[0] == 'agg' else n[1] for _, n in lookups(t)}


def decides_first(t):
    """Does the condition of this change look at other records of the very collection it changes?
    Then which records change is decided before any of them does, so the order they are kept
    in can never matter."""
    if t.kind not in ('update', 'remove_where') or t.where is None:
        return False
    probe = Task('', 'list', t.coll, where=t.where)
    return t.coll in looks_into(probe)


def uses_chance(prog):
    return any(e[0] == 'rand' for t in prog.work() for e in task_exprs(t))


def usage(prog):
    """One line per capability: its command name and the arguments it expects."""
    return [t.name + (' ' + ','.join(f'<{p}>' for p in t.params) if t.params else '') for t in prog.tasks] + \
        [u for name, u in builtins(prog)]


def builtins(prog):
    """Commands the program answers without anyone having named them: time, keys, the board."""
    taken = {t.name for t in prog.tasks}
    out = []
    if prog.timers():
        out.append(('wait', 'wait <milliseconds>'))
    if prog.keys():
        out.append(('press', 'press <' + '|'.join(prog.keys()) + '>'))
    if prog.board:
        out.append(('screen', 'screen'))
        out.append(('picture', 'picture'))
    if uses_chance(prog):
        out.append(('seed', 'seed <number>'))
    if prog.ends:
        out.append(('restart', 'restart'))
    return [(n, u) for n, u in out if n not in taken]


def fmt_event(t):
    if t.on[0] == 'every':
        return f'every {t.on[1]} ms: {canon(t)}'
    return f'when {t.on[1]} is pressed: {canon(t)}'


KEYS = ['left', 'right', 'up', 'down', 'space', 'enter'] + list('abcdefghijklmnopqrstuvwxyz0123456789')
KEY_CODES = {'left': 256 + 68, 'right': 256 + 67, 'up': 256 + 65, 'down': 256 + 66, 'space': 32, 'enter': 10}
KEY_CODES.update({k: ord(k) for k in KEYS if len(k) == 1})      # an arrow is ESC [ A..D; the rest are themselves
LONGEST_WAIT = 3600000          # one hour, in milliseconds
OVER = 'the game is over'
OVER_HINT = 'the game is over: enter plays again, q stops'
BAD_SEED = 'error: seed takes a number'
ENTER_PLAY = '\x1b[?1049h\x1b[?7l\x1b[2J\x1b[?25l'     # a screen of its own, no line wrap, no cursor
LEAVE_PLAY = '\x1b[?7h\x1b[?25h\x1b[?1049l'
TOO_SMALL = 'this board needs a terminal at least %d wide and %d high; this one is %d wide and %d high'


def room(prog):
    """(columns, rows) the terminal needs to show the board with its frame and status lines."""
    w, h = prog.board
    return w + 2, h + 3 + bool(prog.above) + bool(prog.below) + bool(prog.ends)


LONGEST_STEP = 250              # while playing, time never jumps further than this at once
BAD_WAIT = f'error: wait takes a number of milliseconds, from 0 to {LONGEST_WAIT}'


MUTATING = ('add', 'remove_key', 'remove_where', 'update')

# Colours a drawing can have, and the number a terminal knows each by.
COLOURS = {'red': 31, 'green': 32, 'yellow': 33, 'blue': 34, 'magenta': 35, 'purple': 35, 'pink': 35,
           'cyan': 36, 'white': 37, 'grey': 90, 'gray': 90}

# Every other colour is kept as its red, green and blue, marked by RGB so it can never be mistaken
# for one of the terminal's own colours above: the 148 names of the web's colours, or "#rrggbb".
RGB = 1 << 24
NAMED = {
    'aliceblue': 0xf0f8ff, 'antiquewhite': 0xfaebd7, 'aqua': 0x00ffff, 'aquamarine': 0x7fffd4, 'azure': 0xf0ffff,
    'beige': 0xf5f5dc, 'bisque': 0xffe4c4, 'black': 0x000000, 'blanchedalmond': 0xffebcd, 'blue': 0x0000ff,
    'blueviolet': 0x8a2be2, 'brown': 0xa52a2a, 'burlywood': 0xdeb887, 'cadetblue': 0x5f9ea0, 'chartreuse': 0x7fff00,
    'chocolate': 0xd2691e, 'coral': 0xff7f50, 'cornflowerblue': 0x6495ed, 'cornsilk': 0xfff8dc, 'crimson': 0xdc143c,
    'cyan': 0x00ffff, 'darkblue': 0x00008b, 'darkcyan': 0x008b8b, 'darkgoldenrod': 0xb8860b, 'darkgray': 0xa9a9a9,
    'darkgreen': 0x006400, 'darkgrey': 0xa9a9a9, 'darkkhaki': 0xbdb76b, 'darkmagenta': 0x8b008b, 'darkolivegreen': 0x556b2f,
    'darkorange': 0xff8c00, 'darkorchid': 0x9932cc, 'darkred': 0x8b0000, 'darksalmon': 0xe9967a, 'darkseagreen': 0x8fbc8f,
    'darkslateblue': 0x483d8b, 'darkslategray': 0x2f4f4f, 'darkslategrey': 0x2f4f4f, 'darkturquoise': 0x00ced1, 'darkviolet': 0x9400d3,
    'deeppink': 0xff1493, 'deepskyblue': 0x00bfff, 'dimgray': 0x696969, 'dimgrey': 0x696969, 'dodgerblue': 0x1e90ff,
    'firebrick': 0xb22222, 'floralwhite': 0xfffaf0, 'forestgreen': 0x228b22, 'fuchsia': 0xff00ff, 'gainsboro': 0xdcdcdc,
    'ghostwhite': 0xf8f8ff, 'gold': 0xffd700, 'goldenrod': 0xdaa520, 'gray': 0x808080, 'green': 0x008000,
    'greenyellow': 0xadff2f, 'grey': 0x808080, 'honeydew': 0xf0fff0, 'hotpink': 0xff69b4, 'indianred': 0xcd5c5c,
    'indigo': 0x4b0082, 'ivory': 0xfffff0, 'khaki': 0xf0e68c, 'lavender': 0xe6e6fa, 'lavenderblush': 0xfff0f5,
    'lawngreen': 0x7cfc00, 'lemonchiffon': 0xfffacd, 'lightblue': 0xadd8e6, 'lightcoral': 0xf08080, 'lightcyan': 0xe0ffff,
    'lightgoldenrodyellow': 0xfafad2, 'lightgray': 0xd3d3d3, 'lightgreen': 0x90ee90, 'lightgrey': 0xd3d3d3, 'lightpink': 0xffb6c1,
    'lightsalmon': 0xffa07a, 'lightseagreen': 0x20b2aa, 'lightskyblue': 0x87cefa, 'lightslategray': 0x778899, 'lightslategrey': 0x778899,
    'lightsteelblue': 0xb0c4de, 'lightyellow': 0xffffe0, 'lime': 0x00ff00, 'limegreen': 0x32cd32, 'linen': 0xfaf0e6,
    'magenta': 0xff00ff, 'maroon': 0x800000, 'mediumaquamarine': 0x66cdaa, 'mediumblue': 0x0000cd, 'mediumorchid': 0xba55d3,
    'mediumpurple': 0x9370db, 'mediumseagreen': 0x3cb371, 'mediumslateblue': 0x7b68ee, 'mediumspringgreen': 0x00fa9a, 'mediumturquoise': 0x48d1cc,
    'mediumvioletred': 0xc71585, 'midnightblue': 0x191970, 'mintcream': 0xf5fffa, 'mistyrose': 0xffe4e1, 'moccasin': 0xffe4b5,
    'navajowhite': 0xffdead, 'navy': 0x000080, 'oldlace': 0xfdf5e6, 'olive': 0x808000, 'olivedrab': 0x6b8e23,
    'orange': 0xffa500, 'orangered': 0xff4500, 'orchid': 0xda70d6, 'palegoldenrod': 0xeee8aa, 'palegreen': 0x98fb98,
    'paleturquoise': 0xafeeee, 'palevioletred': 0xdb7093, 'papayawhip': 0xffefd5, 'peachpuff': 0xffdab9, 'peru': 0xcd853f,
    'pink': 0xffc0cb, 'plum': 0xdda0dd, 'powderblue': 0xb0e0e6, 'purple': 0x800080, 'rebeccapurple': 0x663399,
    'red': 0xff0000, 'rosybrown': 0xbc8f8f, 'royalblue': 0x4169e1, 'saddlebrown': 0x8b4513, 'salmon': 0xfa8072,
    'sandybrown': 0xf4a460, 'seagreen': 0x2e8b57, 'seashell': 0xfff5ee, 'sienna': 0xa0522d, 'silver': 0xc0c0c0,
    'skyblue': 0x87ceeb, 'slateblue': 0x6a5acd, 'slategray': 0x708090, 'slategrey': 0x708090, 'snow': 0xfffafa,
    'springgreen': 0x00ff7f, 'steelblue': 0x4682b4, 'tan': 0xd2b48c, 'teal': 0x008080, 'thistle': 0xd8bfd8,
    'tomato': 0xff6347, 'turquoise': 0x40e0d0, 'violet': 0xee82ee, 'wheat': 0xf5deb3, 'white': 0xffffff,
    'whitesmoke': 0xf5f5f5, 'yellow': 0xffff00, 'yellowgreen': 0x9acd32,
}
COLOUR_NAMES = sorted(set(NAMED) | set(COLOURS))      # what a text may name, in byte order (searched natively)


def colour_value(text):
    """The ink a text names: a terminal colour, RGB | the colour, or 0 for none. A name is one of the web's,
    read without spaces or capitals ("Light Blue" is "lightblue"); a colour can also be "#" and six
    hexadecimal digits."""
    if len(text) == 7 and text[0] == '#':
        return RGB | int(text[1:], 16) if all(c in '0123456789abcdefABCDEF' for c in text[1:]) else 0
    key = bytes(b + 32 if 65 <= b <= 90 else b for b in text.encode() if b != 32)
    if len(key) > 40:
        return 0
    key = key.decode('latin-1')
    if key in COLOURS:
        return COLOURS[key]
    return RGB | NAMED[key] if key in NAMED else 0


def ink_text(code):
    """How one cell's colour is written in a picture: a letter for a terminal colour, else #rrggbb."""
    return f'#{code & 0xffffff:06x}' if code >= RGB else INK_LETTER[code]


# "picture": the board for a page to paint. After the plain screen comes a line "~", then one
# letter per cell saying its colour, then one more line while the game is over.
INK_LETTER = {0: '.', 31: 'r', 32: 'g', 33: 'y', 34: 'b', 35: 'm', 36: 'c', 37: 'w', 90: 'k'}

# Chance. One 64-bit number is kept; every draw moves it on by the same fixed step, so a run
# that starts from the same number ("seed <number>") draws the same numbers again.
CHANCE_MUL = 6364136223846793005
CHANCE_ADD = 1442695040888963407
CHANCE_WIDEST = 1 << 31         # a draw picks one of at most this many numbers
