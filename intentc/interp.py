"""Reference interpreter: the definition of what an Intent program means.

It runs Intent IR directly with the most obvious data structure (a Python list of dicts) and
knows nothing about the planner or the LLVM backend. Compiled programs are tested against it.

Numbers are 64-bit and wrap on overflow. Division truncates toward zero.
"""
import functools
import re

from .ir import usage

M = 1 << 64
NUM_RE = re.compile(r'[ \t\n\v\f\r]*[+-]?[0-9]+')


def wrap(x):
    x &= M - 1
    return x - M if x >> 63 else x


def tdiv(a, b):
    q = abs(a) // abs(b)
    return wrap(-q if (a < 0) != (b < 0) else q)


def parse_num(s):
    if not NUM_RE.fullmatch(s):
        return None
    return max(-(1 << 63), min((1 << 63) - 1, int(s)))


CMP = {'gt': lambda a, b: a > b, 'ge': lambda a, b: a >= b, 'lt': lambda a, b: a < b,
       'le': lambda a, b: a <= b, 'eq': lambda a, b: a == b, 'ne': lambda a, b: a != b,
       'has': lambda a, b: b in a, 'nhas': lambda a, b: b not in a,
       'starts': lambda a, b: a.startswith(b), 'nstarts': lambda a, b: not a.startswith(b),
       'ends': lambda a, b: a.endswith(b), 'nends': lambda a, b: not a.endswith(b)}


def ev(e, row, args, m=None):
    k = e[0]
    if k in ('num', 'str'):
        return e[1]
    if k == 'field':
        return row[e[1]]
    if k == 'param':
        return args[e[1]]
    if k == 'pfield':
        return m.parent_row(e[1], row[e[1]])[e[2]]
    a, b = ev(e[2], row, args, m), ev(e[3], row, args, m)
    if e[1] == 'mul':
        return wrap(a * b)
    if e[1] == 'add':
        return wrap(a + b)
    if e[1] == 'sub':
        return wrap(a - b)
    if e[1] == 'rem':
        return wrap(a - tdiv(a, b) * b)        # same sign as a, like C
    return tdiv(a, b)


def holds(c, row, args, m=None):
    if c is None:
        return True
    if c[0] == 'cmp':
        return CMP[c[1]](ev(c[2], row, args, m), ev(c[3], row, args, m))
    if c[0] == 'and':
        return holds(c[1], row, args, m) and holds(c[2], row, args, m)
    return holds(c[1], row, args, m) or holds(c[2], row, args, m)


class Machine:
    def __init__(self, prog):
        self.prog = prog
        self.data = {c: [] for c in prog.collections}
        self.tasks = {t.name: t for t in prog.tasks}

    def show(self, row, fields=None):
        def one(f):
            if '.' in f:
                ref, name = f.split('.')
                return self.parent_row(ref, row[ref])[name]
            return row[f]
        return ','.join(str(one(f)) for f in (fields or row))

    # ---- relationships: a record points at its owner by the owner's unique property
    def parent_row(self, ref, value):
        k = self.prog.key_of(ref).name
        return next(r for r in self.data[ref] if r[k] == value)

    def blocked(self, cname, gone):
        """The refusal, if any record about to be removed still owns records it must not lose."""
        for d, rf in self.prog.children_of(cname):
            if rf.on_removed == 'restrict':
                keys = [r[self.prog.key_of(cname).name] for r in gone]
                if any(r[rf.name] in keys for r in self.data[d.name]):
                    return f'{cname} still has {d.label.lower()}'
        return None

    def swept(self, cname):
        """After removals from `cname`: remove the records that belonged to what is gone."""
        for d, rf in self.prog.children_of(cname):
            if rf.on_removed == 'cascade':
                keys = [r[self.prog.key_of(cname).name] for r in self.data[cname]]
                rows = self.data[d.name]
                keep = [r for r in rows if r[rf.name] in keys]
                if len(keep) != len(rows):
                    self.data[d.name] = keep
                    self.swept(d.name)

    def run(self, line):
        """Execute one command line; return the lines it prints."""
        line = line[:-1] if line.endswith('\n') else line
        line = line[:-1] if line.endswith('\r') else line
        if not line:
            return []
        cmd, _, arg = line.partition(' ')
        t = self.tasks.get(cmd)
        if t is None and cmd == 'help':
            return usage(self.prog)
        if t is None:
            return [f'error: unknown command {cmd}']
        toks = arg.split(',') if arg else []
        args = {}
        for i, p in enumerate(t.params):
            if i >= len(toks):
                return [f'error: missing {p}']
            if t.ptypes[p] == 'int':
                v = parse_num(toks[i])
                if v is None:
                    return [f'error: {p} must be a number']
                args[p] = v
            else:
                args[p] = toks[i]
        return getattr(self, 'do_' + t.kind)(t, args)

    def do_calc(self, t, a):
        return [str(ev(t.expr, None, a))]

    def do_add(self, t, a):
        c = self.prog.collections[t.coll]
        rows = self.data[t.coll]
        for f in c.fields.values():
            if f.ref and not any(r[self.prog.key_of(f.ref).name] == a[f.name] for r in self.data[f.ref]):
                return [f'no such {f.ref}']
        for f in c.unique_fields():
            for i, r in enumerate(rows):
                if r[f.name] == a[f.name]:
                    if c.on_dup == 'replace':
                        rows[i] = dict(a)
                        return []
                    return [f'duplicate {f.name}']
        rows.append({f: a[f] for f in c.fields})
        return []

    def do_find(self, t, a):
        out = [self.show(r) for r in self.data[t.coll] if r[t.key] == a[t.key]]
        return out or ['none']

    def do_remove_key(self, t, a):
        return self.remove(t.coll, lambda r: r[t.key] == a[t.key]) or \
            ([] if self.removed else ['none'])

    def do_remove_where(self, t, a):
        return self.remove(t.coll, lambda r: holds(t.where, r, a, self)) or []

    def remove(self, cname, goes):
        rows = self.data[cname]
        gone = [r for r in rows if goes(r)]
        self.removed = len(gone)
        refusal = self.blocked(cname, gone) if gone else None
        if refusal:
            self.removed = -1
            return [refusal]
        self.data[cname] = [r for r in rows if not goes(r)]
        if gone:
            self.swept(cname)
        return None

    def do_update(self, t, a):
        for r in self.data[t.coll]:
            if holds(t.where, r, a, self):
                for f, e in t.assigns:
                    r[f] = ev(e, r, a, self)
        return []

    def do_list(self, t, a):
        rows = [(i, r) for i, r in enumerate(self.data[t.coll]) if holds(t.where, r, a, self)]
        if t.order:
            f, desc = t.order

            def key(v):
                return v.encode() if isinstance(v, str) else v

            def cmp(x, y):
                kx, ky = key(x[1][f]), key(y[1][f])
                if kx != ky:
                    return (-1 if kx < ky else 1) * (-1 if desc else 1)
                return -1 if x[0] < y[0] else 1
            rows.sort(key=functools.cmp_to_key(cmp))
        if t.limit is not None:
            rows = rows[:t.limit]
        return [self.show(r, t.fields) for _, r in rows]

    def do_agg(self, t, a):
        rows = [r for r in self.data[t.coll] if holds(t.where, r, a, self)]
        if t.fn == 'count':
            return [str(len(rows))]
        vals = [r[t.field] for r in rows]
        if t.fn == 'sum':
            return [str(wrap(sum(vals)))]
        if not vals:
            return ['none']
        if t.fn == 'max':
            return [str(max(vals))]
        if t.fn == 'min':
            return [str(min(vals))]
        return ['%.2f' % (float(wrap(sum(vals))) / float(len(vals)))]
