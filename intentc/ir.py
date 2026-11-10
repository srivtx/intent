"""Intent IR: the canonical meaning of a program. Everything downstream reads only this.

Expressions are tuples:
    ('num', n) | ('str', s) | ('field', name) | ('param', name) | ('bin', op, a, b)   op in mul add sub div rem
    ('pfield', ref, name)   a property of the record this one belongs to (ref is the linking property)
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


@dataclass
class Program:
    collections: dict = _f(default_factory=dict)
    tasks: list = _f(default_factory=list)

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
    yield e
    if e[0] == 'bin':
        yield from walk_expr(e[2])
        yield from walk_expr(e[3])


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
    return [t.name + (' ' + ','.join(f'<{p}>' for p in t.params) if t.params else '') for t in prog.tasks]


MUTATING = ('add', 'remove_key', 'remove_where', 'update')
