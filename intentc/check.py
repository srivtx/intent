"""Semantic checks on Intent IR: infer types, and find every decision the program left open.

Four tiers, in this order, and each is reported differently:
  declared  - the programmer said it
  inferred  - follows from how the property is used (age is multiplied -> number)
  assumed   - a naming convention (email -> text); reported as a note, overridable
  asked     - nothing decides it; compilation stops with a question
"""
from .ir import (FNNAME, NEGATE, STATE, TEXT_OPS, Diag, cond_cmps, fmt_dec, lookups, task_conds, task_exprs, walk_cond_exprs,
                 walk_expr)
from .lexicon import CONVENTION

def nonzero(c, yes):
    """The values that cannot be zero when condition c is true (yes) or false (not yes)."""
    if c is None or c[0] in ('any', 'none'):
        return []
    if c[0] == 'cmp':
        op = c[1] if yes else NEGATE.get(c[1])
        x, y = c[2], c[3]
        if y[0] == 'num':
            n = y[1]
            if (op == 'ne' and n == 0) or (op == 'gt' and n >= 0) or (op == 'ge' and n >= 1) or \
                    (op == 'lt' and n <= 0) or (op == 'le' and n <= -1):
                return [x]
        if x == ('num', 0) and op in ('ne', 'gt', 'lt'):
            return [y]
        return []
    if (c[0] == 'and') == yes:      # every part is known to hold
        return nonzero(c[1], yes) + nonzero(c[2], yes)
    return []


def notneg(c, yes):
    """The values that cannot be below zero when condition c is true (yes) or false (not yes)."""
    if c is None or c[0] in ('any', 'none'):
        return []
    if c[0] == 'cmp':
        op = c[1] if yes else NEGATE.get(c[1])
        x, y = c[2], c[3]
        if y[0] in ('num', 'dec') and ((op in ('ge', 'eq') and y[1] >= 0) or (op == 'gt' and y[1] >= -1)):
            return [x]
        if x[0] in ('num', 'dec') and ((op in ('le', 'eq') and x[1] >= 0) or (op == 'lt' and x[1] >= -1)):
            return [y]
        return []
    if (c[0] == 'and') == yes:
        return notneg(c[1], yes) + notneg(c[2], yes)
    return []


def nonneg(e, known):
    """Can e be shown never to be below zero? Squares, sums and products of such, and what a condition says."""
    k = e[0]
    if e in known:
        return True
    if k in ('num', 'dec'):
        return e[1] >= 0
    if k == 'fn':
        return e[1] in ('sqrt', 'dsqrt', 'abs') or (e[1] in ('round', 'trunc') and nonneg(e[2], known))
    if k == 'agg':
        return e[1] == 'count'
    if k == 'if':
        return nonneg(e[2], known) and nonneg(e[3], known)
    if k == 'bin':
        if e[1] == 'mul' and e[2] == e[3]:
            return True
        return e[1] in ('add', 'mul', 'div', 'rem') and nonneg(e[2], known) and nonneg(e[3], known)
    return False


TYPE_NAME = {'int': 'a number', 'text': 'text'}


class Checker:
    def __init__(self, prog, src):
        self.prog, self.src = prog, src
        self.diags = []
        self.seen = set()
        self.div_noted = False      # the note on whole-number division is given once
        self.outer = None           # while a condition about other records is checked: where it is asked from

    def d(self, level, line, msg, label='', hint=''):
        key = (level, line, msg)
        if key in self.seen:
            return
        self.seen.add(key)
        text = self.src.line_text(line)
        start = len(text) - len(text.lstrip())
        self.diags.append(Diag(level, msg, line, start, max(len(text.rstrip()), start + 1), label, hint))

    # ------------------------------------------------------------------ types
    def ty(self, e, coll, t):
        k = e[0]
        if k in ('num', 'bin', 'rand', 'agg', 'dec', 'cents', 'fn'):
            return 'int'
        if k == 'outer':
            return self.outer.fields[e[1]].type
        if k == 'str':
            return 'text'
        if k == 'field':
            return coll.fields[e[1]].type
        if k == 'pfield':
            return self.prog.collections[coll.fields[e[1]].ref].fields[e[2]].type
        if k == 'value':
            return self.prog.collections[STATE].fields[e[1]].type
        if k == 'if':
            return self.ty(e[2], coll, t) or self.ty(e[3], coll, t)
        return t.ptypes.get(e[1])

    def name_of(self, e):
        if e[0] == 'pfield':
            return f'"{e[1]}\'s {e[2]}"'
        if e[0] == 'value':
            return f'"{e[1]}"'
        if e[0] == 'if':
            return 'an either-or value'
        if e[0] == 'rand':
            return 'a random number'
        if e[0] == 'dec':
            return fmt_dec(e[1])
        if e[0] == 'cents':
            return self.name_of(e[1])
        if e[0] == 'agg':
            return 'a count' if e[1] == 'count' else f'the {e[1]} of "{e[3]}"'
        if e[0] == 'outer':
            return f'"{e[1]}"'
        return {'field': f'"{e[1]}"', 'param': f'the given {e[1]}', 'num': str(e[1]),
                'str': f'"{e[1]}"', 'bin': 'a calculation', 'fn': 'a calculation', 'rand': 'a random number'
                }.get(e[0], 'this') if e[0] != 'num' else str(e[1])

    def need(self, e, typ, coll, t):
        k = e[0]
        if k == 'if':               # both outcomes have to be the same kind of value
            return any([self.need(e[2], typ, coll, t), self.need(e[3], typ, coll, t)])
        cur = self.ty(e, coll, t)
        if cur is None:
            if k == 'pfield':
                f = self.prog.collections[coll.fields[e[1]].ref].fields[e[2]]
                f.type, f.how = typ, 'inferred'
            elif k == 'field':
                f = coll.fields[e[1]]
                f.type, f.how = typ, 'inferred'
            elif k == 'outer':
                f = self.outer.fields[e[1]]
                f.type, f.how = typ, 'inferred'
            else:
                t.ptypes[e[1]] = typ
            return True
        if cur != typ:
            self.d('error', t.line, 'this mixes text and numbers',
                   f'{self.name_of(e)} is {TYPE_NAME[cur]}, but is used as {TYPE_NAME[typ]} here')
        return False

    def equal(self, a, b, coll, t):
        ta, tb = self.ty(a, coll, t), self.ty(b, coll, t)
        if ta and not tb:
            return self.need(b, ta, coll, t)
        if tb and not ta:
            return self.need(a, tb, coll, t)
        if ta and tb and ta != tb:
            self.d('error', t.line, 'this mixes text and numbers',
                   f'{self.name_of(a)} is {TYPE_NAME[ta]}, but {self.name_of(b)} is {TYPE_NAME[tb]}')
        return False

    def constrain(self, t):
        ch = False
        coll = self.prog.collections.get(t.coll)
        if t.kind == 'calc':
            for p in t.params:
                t.ptypes[p] = 'int'
            ch |= self.need(t.expr, 'int', coll, t)
        for e in task_exprs(t):
            if e[0] == 'bin':
                ch |= self.need(e[2], 'int', coll, t)
                ch |= self.need(e[3], 'int', coll, t)
            elif e[0] == 'if':
                ch |= self.equal(e[2], e[3], coll, t)
        for f, e in t.assigns:
            ch |= self.equal(('field', f), e, coll, t)
        ch |= self.compared(task_conds(t), coll, t)
        for frm, node in lookups(t):        # "if any rock ...", "the number of rocks whose ...": the rock's properties
            other = self.prog.collections[node[2] if node[0] == 'agg' else node[1]]
            self.outer = self.prog.collections.get(frm)
            for e in walk_cond_exprs(node[-1]):
                if e[0] == 'bin':
                    ch |= self.need(e[2], 'int', other, t)
                    ch |= self.need(e[3], 'int', other, t)
            ch |= self.compared(cond_cmps(node[-1]), other, t)
            if node[0] == 'agg' and node[3]:
                ch |= self.need(('field', node[3]), 'int', other, t)
            self.outer = None
        for e in t.at or ():            # a place on the board is two numbers
            ch |= self.need(e, 'int', coll, t)
        if t.kind == 'agg' and t.field:
            ch |= self.need(('field', t.field), 'int', coll, t)
        return ch

    def compared(self, cmps, coll, t):
        ch = False
        for c in cmps:
            if c[1] in ('eq', 'ne'):
                ch |= self.equal(c[2], c[3], coll, t)
            elif c[1] in TEXT_OPS:
                ch |= self.need(c[2], 'text', coll, t)
                ch |= self.need(c[3], 'text', coll, t)
            else:
                if 'text' in (self.ty(c[2], coll, t), self.ty(c[3], coll, t)):
                    self.d('error', t.line, 'text can only be compared with "is" / "is not" in this version')
                else:
                    ch |= self.need(c[2], 'int', coll, t)
                    ch |= self.need(c[3], 'int', coll, t)
        return ch

    def link(self):
        """A linking property has the type of the unique property it points at."""
        ch = False
        for c in self.prog.collections.values():
            for f in c.fields.values():
                k = self.prog.key_of(f.ref) if f.ref else None
                if k is not None and k.type != f.type and None in (k.type, f.type):
                    k.type = f.type = k.type or f.type
                    ch = True
        return ch

    def settle(self):
        for _ in range(12):
            if not any([self.constrain(t) for t in self.prog.work() + self.prog.looks()] + [self.link()]):
                break

    def infer(self):
        self.settle()
        assumed = False
        for c in self.prog.collections.values():
            for f in c.fields.values():
                if f.type is None and f.name in CONVENTION:
                    f.type, f.how = CONVENTION[f.name], 'assumed'
                    assumed = True
                    self.d('note', f.line, f'assuming "{f.name}" is {TYPE_NAME[f.type]}, from its name',
                           hint=f'write "{f.name} ({"number" if f.type == "text" else "text"})" if that is wrong')
        if assumed:
            self.settle()
        for c in self.prog.collections.values():
            for f in c.fields.values():
                if f.ref and self.prog.key_of(f.ref) is None:
                    p = self.prog.collections[f.ref]
                    f.type = f.type or 'text'
                    self.d('question', f.line, f'how is a {p.name} identified?',
                           f'each {c.name} has to say which {p.name} it belongs to',
                           f'declare exactly one unique property of {p.label}, e.g. "Names are unique."')
                elif f.type is None:
                    self.d('question', f.line, f'is "{f.name}" text or a number?',
                           'nothing in the program decides this',
                           f'write "{f.name} (text)" or "{f.name} (number)"')
        for t in self.prog.work():
            coll = self.prog.collections.get(t.coll)
            if t.kind == 'add':
                t.ptypes = {f.name: f.type for f in coll.fields.values()}
            elif t.kind in ('find', 'remove_key'):
                t.ptypes = {t.key: coll.fields[t.key].type}
            for p in t.params:
                t.ptypes.setdefault(p, 'int')

    # ------------------------------------------------------------------ open decisions
    def validate(self):
        P = self.prog
        for c in P.collections.values():
            if not c.fields and c.name != STATE:
                self.d('question', c.line, f'what does each {c.name} have?', 'no properties declared',
                       f'e.g. "Each {c.name} has a name and an age."')
            if c.on_dup == 'replace' and len(c.unique_fields()) > 1:
                self.d('error', c.on_dup_line, 'replacing duplicates with more than one unique property is not supported yet')
        self.unused_values()
        if not P.tasks and not P.events and not P.draws and P.collections:
            line = max(c.line for c in P.collections.values())
            self.d('note', line, 'this program describes information but nothing to do with it yet')
        for c in P.collections.values():
            for f in c.fields.values():
                if not f.ref:
                    continue
                p = P.collections[f.ref]
                removers = [t for t in P.work() if t.coll == p.name and t.kind in ('remove_key', 'remove_where')]
                if removers and f.on_removed is None:
                    self.d('question', removers[0].line,
                           f'what happens to the {c.label.lower()} of a removed {p.name}?',
                           f'line {f.line} says each {c.name} belongs to a {p.name}',
                           f'add a sentence: "When a {p.name} is removed, remove its {c.label.lower()}." or '
                           f'"A {p.name} with {c.label.lower()} cannot be removed."')
                if f.on_removed == 'cascade':
                    for d, g in P.children_of(c.name):
                        if g.on_removed == 'restrict':
                            self.d('question', g.on_removed_line,
                                   f'removing a {p.name} removes its {c.label.lower()}, but a {c.name} with '
                                   f'{d.label.lower()} cannot be removed: which wins?',
                                   'two rules meet here', 'make both rules remove, or both refuse')
        live = P.events or P.draws or P.ends or P.above or P.below
        if P.draws and not P.board:
            self.d('question', P.draws[0].line, 'how big is the board this is drawn on?', 'no sentence gives its size',
                   'e.g. "The board is 30 wide and 15 high."')
        elif live and not P.board:
            first = min(t.line for t in P.events + P.ends) if P.events or P.ends else 1
            self.d('note', first, 'nothing is drawn, so this program cannot be played; time only passes when it is '
                   'told to wait', hint='add a board, e.g. "The board is 30 wide and 15 high.", and say what to draw')
        elif P.board and not P.draws:
            self.d('note', P.board_line, 'nothing is drawn on the board yet',
                   hint='e.g. Draw each rock at its x and y as "#".')
        for i, t in enumerate(P.seeds):
            coll = P.collections[t.coll]
            for u in coll.unique_fields():
                twin = next((o for o in P.seeds[:i] if o.coll == t.coll and
                             dict(o.assigns)[u.name] == dict(t.assigns)[u.name]), None)
                if twin:
                    self.d('error', t.line, f'two {coll.label.lower()} would start with the same {u.name}',
                           f'line {twin.line} already starts with this one; line {u.unique_line} makes {u.name} unique')
        for t in P.events:
            coll = P.collections[t.coll]
            if t.kind == 'remove_where' and any(rf.on_removed == 'restrict' for _, rf in P.children_of(coll.name)):
                self.d('error', t.line, f'removing {coll.label.lower()} that other records belong to cannot happen '
                       f'by itself yet')
        for t in P.rules + P.looks() + [x for x in P.work() if x.kind == 'remove_where']:
            if any(e[0] == 'rand' for e in task_exprs(t)):
                what = ('a rule looks again and again, so it would draw a new number each time'
                        if t in P.rules else 'this is looked at many times, and would be different each time')
                self.d('error', t.line, 'chance cannot be used here', what,
                       'draw the number in a sentence that happens at one moment, and keep it in a single value')
        for t in P.rules:
            coll = P.collections[t.coll]
            for f, e in t.assigns:
                if any(x == ('field', f) for x in walk_expr(e)):
                    self.d('error', t.line, f'this rule would change "{f}" again every time it looks',
                           f'the new {f} is worked out from the old {f}, so the rule never comes to rest',
                           f'give the value outright, e.g. "... the {f} becomes 100"; or make it a capability '
                           f'by naming it: "Bump: ..."')
            if t.kind == 'remove_where' and any(rf.on_removed == 'restrict' for _, rf in P.children_of(coll.name)):
                self.d('error', t.line, f'a rule cannot remove {coll.label.lower()} that other records belong to yet')
        for t in P.work() + P.looks():
            coll = P.collections.get(t.coll)
            for e in task_exprs(t):
                if e[0] == 'fn' and self.ty(e[2], coll, t) == 'text':
                    self.d('error', t.line, f'{FNNAME[e[1]]} {self.name_of(e[2])} is not a number: that is text')
            for top in [e for _, e in t.assigns] + ([t.expr] if t.expr else []) + list(t.at or ()) + \
                    [x for c in cond_cmps(t.where) for x in c[2:4]]:
                self.roots(top, notneg(t.where, True), t)
            safe = nonzero(t.where, True)
            for _, e in t.assigns:
                self.divisions(e, safe, t)
            for e in t.at or ():
                self.divisions(e, safe, t)
            if t.expr:
                self.divisions(t.expr, [], t)
            for c in list(cond_cmps(t.where)) + [c for _, node in lookups(t) for c in cond_cmps(node[-1])]:
                self.divisions(c[2], [], t)
                self.divisions(c[3], [], t)
            if t.kind == 'update':
                changed = {f for f, _ in t.assigns}
                probe = type(t)('', 'update', t.coll, assigns=t.assigns)
                for frm, node in lookups(probe):    # a new value worked out from the other records of the same kind
                    read = {e[1] for e in walk_cond_exprs(node[-1]) if e[0] == 'field'} | \
                        ({node[3]} if node[0] == 'agg' and node[3] else set())
                    if (node[2] if node[0] == 'agg' else node[1]) == t.coll and read & changed:
                        f = sorted(read & changed)[0]
                        self.d('error', t.line, f'this works out the new "{f}" from the "{f}" of the other {coll.label.lower()} '
                               f'while changing them', 'the answer would depend on which one is changed first',
                               'work it out into a single value first, in a sentence of its own')
                for f, _ in t.assigns:
                    if coll.fields[f].ref:
                        self.d('error', t.line, f'moving a {coll.name} to another {f} is not supported yet')
                    if coll.fields[f].unique:
                        self.d('error', t.line, f'changing "{f}" in bulk is not supported yet because it is unique',
                               f'line {coll.fields[f].unique_line} says so; a bulk change could create duplicates')
            if t.kind in ('add', 'make'):
                u = coll.unique_fields()
                if u and coll.on_dup is None:
                    self.d('question', t.line,
                           f'what should happen when a {coll.name} with an existing {u[0].name} is added?',
                           f'line {u[0].unique_line} makes {u[0].name} unique, but nothing says what a clash does',
                           'add a sentence: "Reject duplicates." or "Replace duplicates."')
            if t.kind in ('find', 'remove_key') and not coll.fields[t.key].unique:
                self.d('note', t.line,
                       f'"{t.key}" is not declared unique, so this can match several {coll.label} and has to look at all of them',
                       hint=f'say "{t.key} is unique" if it is; then I can index it')

    def unused_values(self):
        """A single value nothing reads or changes is most likely a slip in its name ("The hurtt starts at 5.")."""
        P = self.prog
        S = P.collections.get(STATE)
        if S is None:
            return
        used = set(P.above) | set(P.below)
        for t in P.work() + P.looks():
            used |= {e[1] for e in task_exprs(t) if e[0] == 'value'}
            if t.coll == STATE:
                used |= {f for f, _ in t.assigns} | set(t.fields if t.fields is not None else S.fields)
                used |= {e[1] for e in task_exprs(t) if e[0] == 'field'}
            used |= {x[1] for x in (t.glyph, t.colour) if isinstance(x, tuple) and x[0] == 'value'}
        for f in S.fields.values():
            if f.name not in used:
                self.d('note', f.line, f'"{f.name.replace("_", " ")}" is never used',
                       hint='if it is a slip for another name, correct it; a value is declared once')

    def roots(self, e, known, t):
        """A square root must be of something that cannot be below zero where it happens."""
        if e[0] == 'fn':
            if e[1] == 'sqrt' and not nonneg(e[2], known):
                name = self.name_of(e[2]).strip('"')
                said = e[2][1].replace('_', ' ') if e[2][0] in ('param', 'field', 'value') else 'it'
                self.d('question', t.line, f'what should happen when {name} is below 0?',
                       'a number below zero has no square root, and I will not invent one',
                       f'say it, e.g. "the square root of {said} if {said} is at least 0, otherwise 0"')
            self.roots(e[2], known, t)
        elif e[0] == 'bin':
            self.roots(e[2], known, t)
            self.roots(e[3], known, t)
        elif e[0] == 'if':
            self.roots(e[2], known + notneg(e[1], True), t)
            self.roots(e[3], known + notneg(e[1], False), t)

    def divisions(self, e, safe, t):
        """Every division must be by something that cannot be zero where it happens."""
        if e[0] == 'bin':
            d = e[3]
            if e[1] in ('div', 'rem'):
                if d in (('num', 0), ('dec', 0)):
                    self.d('error', t.line, 'this divides by zero')
                elif d[0] not in ('num', 'dec') and d not in safe:
                    name = self.name_of(d).strip('"')
                    self.d('question', t.line, f'what should happen when {name} is zero?',
                           'dividing by zero has no answer, and I will not invent one',
                           f'say it, e.g. "... divided by {name} if {name} is not 0, otherwise 0"')
                elif e[1] == 'div' and not self.isdec(e, self.prog.collections.get(t.coll), t) and not self.div_noted:
                    self.div_noted = True       # said once: it holds for every whole-number division
                    self.d('note', t.line, 'whole-number division drops the remainder (7 / 2 is 3)',
                           hint='this holds for every division of whole numbers in the program')
            self.divisions(e[2], safe, t)
            self.divisions(d, safe, t)
        elif e[0] == 'if':
            for c in cond_cmps(e[1]):
                self.divisions(c[2], safe, t)
                self.divisions(c[3], safe, t)
            self.divisions(e[2], safe + nonzero(e[1], True), t)
            self.divisions(e[3], safe + nonzero(e[1], False), t)

    # ------------------------------------------------------------------ decimal numbers
    # A decimal number is kept exactly, as a whole number of hundredths. Which numbers are decimal
    # follows from how they are declared and used; then every place where a decimal meets a whole
    # number is made explicit, so that running the program is plain whole-number arithmetic.
    def isdec(self, e, coll, t):
        k, cs = e[0], self.prog.collections
        if k in ('dec', 'cents'):
            return True
        if k == 'field':
            return coll is not None and e[1] in coll.fields and coll.fields[e[1]].dec
        if k == 'pfield':
            return cs[coll.fields[e[1]].ref].fields[e[2]].dec
        if k == 'value':
            return cs[STATE].fields[e[1]].dec
        if k == 'outer':
            return self.outer is not None and self.outer.fields[e[1]].dec
        if k == 'param':
            return e[1] in t.pdec
        if k == 'agg':
            return e[1] != 'count' and cs[e[2]].fields[e[3]].dec
        if k in ('if', 'bin'):
            return self.isdec(e[2], coll, t) or self.isdec(e[3], coll, t)
        if k == 'fn':           # a sine is a decimal number; a root or a size is whatever it is of; a rounding, whole
            return e[1] in ('sin', 'cos', 'dsqrt') or (e[1] in ('sqrt', 'abs') and self.isdec(e[2], coll, t))
        return False

    def make_dec(self, e, coll, t):
        """A bare name that meets a decimal number is one itself, unless it was declared whole."""
        if e[0] == 'param' and e[1] not in t.pdec and t.ptypes.get(e[1], 'int') == 'int':
            t.pdec.add(e[1])
            return True
        f = None
        if e[0] == 'field' and coll is not None:
            f = coll.fields[e[1]]
        elif e[0] == 'value':
            f = self.prog.collections[STATE].fields[e[1]]
        elif e[0] == 'outer' and self.outer is not None:
            f = self.outer.fields[e[1]]
        if f is not None and not f.dec and f.type == 'int' and not f.unique and not f.ref and \
                (f.how != 'declared' or e[0] == 'value' or (coll is not None and coll.name == STATE)):
            f.dec = True
            if isinstance(f.init, int):
                f.init *= 100
            return True
        return False

    def spread(self, t):
        ch = False
        coll = self.prog.collections.get(t.coll)
        if t.kind == 'add':
            new = {f.name for f in coll.fields.values() if f.dec} - t.pdec
            t.pdec |= new
            ch |= bool(new)
        if t.kind in ('find', 'remove_key') and coll.fields[t.key].dec and t.key not in t.pdec:
            t.pdec.add(t.key)
            ch = True

        def meet(a, b, c):
            if self.isdec(a, c, t) != self.isdec(b, c, t):
                return self.make_dec(b if self.isdec(a, c, t) else a, c, t)
            return False

        def exprs(e, c):
            nonlocal ch
            if e[0] == 'bin':
                exprs(e[2], c)
                exprs(e[3], c)
                if e[1] in ('add', 'sub'):
                    ch |= meet(e[2], e[3], c)
            elif e[0] == 'if':
                conds(e[1], c)
                exprs(e[2], c)
                exprs(e[3], c)
            elif e[0] == 'fn':
                exprs(e[2], c)
            elif e[0] == 'agg' and e[4] is not None:
                was, self.outer = self.outer, c
                conds(e[4], self.prog.collections[e[2]])
                self.outer = was

        def conds(cnd, c):
            nonlocal ch
            if cnd is None:
                return
            if cnd[0] == 'cmp':
                exprs(cnd[2], c)
                exprs(cnd[3], c)
                if cnd[1] not in TEXT_OPS and 'text' not in (self.ty(cnd[2], c, t), self.ty(cnd[3], c, t)):
                    ch |= meet(cnd[2], cnd[3], c)
            elif cnd[0] in ('any', 'none'):
                was, self.outer = self.outer, c
                conds(cnd[2], self.prog.collections[cnd[1]])
                self.outer = was
            else:
                conds(cnd[1], c)
                conds(cnd[2], c)
        for f, e in t.assigns:
            exprs(e, coll)
            if coll.fields[f].type == 'int':
                ch |= meet(('field', f), e, coll)
        for e in ([t.expr] if t.expr else []) + list(t.at or ()):
            exprs(e, coll)
        conds(t.where, coll)
        return ch

    def lower(self, t):
        coll = self.prog.collections.get(t.coll)
        cs = self.prog.collections

        def cents(e):
            return ('cents', e)

        def low(e, c):
            k = e[0]
            if k == 'agg':
                was, self.outer = self.outer, c
                cond = lowc(e[4], cs[e[2]])
                self.outer = was
                e = e[:4] + (cond,)
                return e, self.isdec(e, c, t)
            if k == 'if':
                cond = lowc(e[1], c)
                (a, da), (b, db) = low(e[2], c), low(e[3], c)
                if da != db and self.ty(e[2], c, t) == 'int':
                    a, b = (a if da else cents(a)), (b if db else cents(b))
                return ('if', cond, a, b), da or db
            if k == 'fn':
                a, da = low(e[2], c)
                if e[1] in ('sin', 'cos'):          # worked out on hundredths of a degree
                    return ('fn', e[1], a if da else cents(a)), True
                if e[1] == 'abs':
                    return ('fn', 'abs', a), da
                if e[1] in ('round', 'trunc'):      # a whole number already is its own rounding
                    return (('fn', 'd' + e[1], a) if da else a), False
                return (('fn', 'dsqrt', a), True) if da else (('fn', 'sqrt', a), False)
            if k != 'bin':
                return e, self.isdec(e, c, t)
            (a, da), (b, db) = low(e[2], c), low(e[3], c)
            op = e[1]
            if not (da or db):
                return ('bin', op, a, b), False
            if op in ('add', 'sub'):
                return ('bin', op, a if da else cents(a), b if db else cents(b)), True
            if op == 'mul':
                return ('bin', 'dmul' if da and db else 'mul', a, b), True
            if op == 'div':
                if da and db:
                    return ('bin', 'rdiv', cents(a), b), True
                if da:
                    return ('bin', 'rdiv', a, b), True
                return ('bin', 'rdiv', cents(cents(a)), b), True
            self.d('error', t.line, 'the remainder of a decimal number is not supported yet')
            return ('bin', op, a, b), True

        def lowc(cnd, c):
            if cnd is None:
                return None
            if cnd[0] == 'cmp':
                if cnd[1] in TEXT_OPS:
                    return cnd
                (a, da), (b, db) = low(cnd[2], c), low(cnd[3], c)
                if da != db:
                    a, b = (a if da else cents(a)), (b if db else cents(b))
                return ('cmp', cnd[1], a, b)
            if cnd[0] in ('any', 'none'):
                was, self.outer = self.outer, c
                inner = lowc(cnd[2], cs[cnd[1]])
                self.outer = was
                return (cnd[0], cnd[1], inner)
            return (cnd[0], lowc(cnd[1], c), lowc(cnd[2], c))

        fitted = []
        for f, e in t.assigns:
            e, d = low(e, coll)
            want = coll.fields[f].dec
            if want and not d:
                e = cents(e)
            elif d and not want:
                self.d('error', t.line, f'"{f}" is a whole number, and this would give it a decimal one',
                       f'line {coll.fields[f].line} says so', f'declare it as "{f} (decimal)" if it should keep cents')
            fitted.append((f, e))
        t.assigns = fitted
        t.where = lowc(t.where, coll)
        if t.expr:
            t.expr, t.dec = low(t.expr, coll)
        if t.at:
            at = [low(e, coll) for e in t.at]
            if any(d for _, d in at):
                self.d('error', t.line, 'a place on the board is a whole number')
            t.at = tuple(e for e, _ in at)

    def run(self):
        work = self.prog.work() + self.prog.looks()
        self.infer()
        for _ in range(12):
            if not any([self.spread(t) for t in work]):
                break
        self.validate()
        for t in work:
            self.lower(t)
        return self.diags


def check(prog, src):
    return Checker(prog, src).run()
