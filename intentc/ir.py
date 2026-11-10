"""Intent IR: the canonical meaning of a program. Everything downstream reads only this.

Expressions are tuples:
    ('num', n) | ('str', s) | ('field', name) | ('param', name) | ('bin', op, a, b)   op in mul add sub div rem
    ('pfield', ref, name)   a property of the record this one belongs to (ref is the linking property)
    ('value', name)         a single value the program keeps ("the score")
    ('if', cond, a, b)      a when cond holds, otherwise b
Conditions are tuples:
    ('cmp', op, a, b)   op in gt ge lt le eq ne
    ('and', a, b) | ('or', a, b)
"""
import json
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

    def unique_fields(self):
        return [f for f in self.fields.values() if f.unique]


@dataclass
class Task:
    name: str
    kind: str                   # add find remove_key remove_where update list agg calc
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
    glyph: str = None                               # draw: the one character shown there


STATE = '(values)'              # the hidden one-record collection that holds the program's single values


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


OPSYM = {'mul': '*', 'add': '+', 'sub': '-', 'div': '/', 'rem': 'mod'}
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
    if k == 'if':
        s = f'{fmt_expr(e[2], False)} if {fmt_cond(e[1])} else {fmt_expr(e[3], False)}'
        return s if top else f'({s})'
    s = f'{fmt_expr(e[2], False)} {OPSYM[e[1]]} {fmt_expr(e[3], False)}'
    return s if top else f'({s})'


def fmt_cond(c, top=True):
    if c[0] == 'cmp':
        return f'{fmt_expr(c[2])} {CMPSYM[c[1]]} {fmt_expr(c[3])}'
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


def walk_expr(e):
    """Every value inside e, including those inside the condition of an "if"."""
    yield e
    if e[0] == 'bin':
        yield from walk_expr(e[2])
        yield from walk_expr(e[3])
    elif e[0] == 'if':
        yield from walk_cond_exprs(e[1])
        yield from walk_expr(e[2])
        yield from walk_expr(e[3])


def task_exprs(t):
    """Every value a task computes or compares, at any depth."""
    tops = [e for _, e in t.assigns] + ([t.expr] if t.expr else []) + list(t.at or ())
    return [e for top in tops for e in walk_expr(top)] + list(walk_cond_exprs(t.where))


def task_conds(t):
    """Every comparison a task makes: its own condition and those inside "if" values."""
    yield from cond_cmps(t.where)
    for e in task_exprs(t):
        if e[0] == 'if':
            yield from cond_cmps(e[1])


def walk_cond_exprs(c):
    if c is None:
        return
    if c[0] == 'cmp':
        yield from walk_expr(c[2])
        yield from walk_expr(c[3])
    else:
        yield from walk_cond_exprs(c[1])
        yield from walk_cond_exprs(c[2])


def cond_cmps(c):
    if c is None:
        return
    if c[0] == 'cmp':
        yield c
    else:
        yield from cond_cmps(c[1])
        yield from cond_cmps(c[2])


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
LONGEST_STEP = 250              # while playing, time never jumps further than this at once
BAD_WAIT = f'error: wait takes a number of milliseconds, from 0 to {LONGEST_WAIT}'


MUTATING = ('add', 'remove_key', 'remove_where', 'update')
