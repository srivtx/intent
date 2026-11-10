"""Semantic checks on Intent IR: infer types, and find every decision the program left open.

Four tiers, in this order, and each is reported differently:
  declared  - the programmer said it
  inferred  - follows from how the property is used (age is multiplied -> number)
  assumed   - a naming convention (email -> text); reported as a note, overridable
  asked     - nothing decides it; compilation stops with a question
"""
from .ir import NEGATE, STATE, TEXT_OPS, Diag, cond_cmps, task_conds, task_exprs, walk_expr
from .lexicon import CONVENTION

def nonzero(c, yes):
    """The values that cannot be zero when condition c is true (yes) or false (not yes)."""
    if c is None:
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


TYPE_NAME = {'int': 'a number', 'text': 'text'}


class Checker:
    def __init__(self, prog, src):
        self.prog, self.src = prog, src
        self.diags = []
        self.seen = set()

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
        if k in ('num', 'bin'):
            return 'int'
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
        return {'field': f'"{e[1]}"', 'param': f'the given {e[1]}', 'num': str(e[1]),
                'str': f'"{e[1]}"', 'bin': 'a calculation'}[e[0]] if e[0] != 'num' else str(e[1])

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
        for c in task_conds(t):
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
        if t.kind == 'agg' and t.field:
            ch |= self.need(('field', t.field), 'int', coll, t)
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
            if not any([self.constrain(t) for t in self.prog.work()] + [self.link()]):
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
            if not c.fields:
                self.d('question', c.line, f'what does each {c.name} have?', 'no properties declared',
                       f'e.g. "Each {c.name} has a name and an age."')
            if c.on_dup == 'replace' and len(c.unique_fields()) > 1:
                self.d('error', c.on_dup_line, 'replacing duplicates with more than one unique property is not supported yet')
        if not P.tasks and P.collections:
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
        for t in P.work():
            coll = P.collections.get(t.coll)
            safe = nonzero(t.where, True)
            for _, e in t.assigns:
                self.divisions(e, safe, t)
            if t.expr:
                self.divisions(t.expr, [], t)
            for c in cond_cmps(t.where):
                self.divisions(c[2], [], t)
                self.divisions(c[3], [], t)
            if t.kind == 'update':
                for f, _ in t.assigns:
                    if coll.fields[f].ref:
                        self.d('error', t.line, f'moving a {coll.name} to another {f} is not supported yet')
                    if coll.fields[f].unique:
                        self.d('error', t.line, f'changing "{f}" in bulk is not supported yet because it is unique',
                               f'line {coll.fields[f].unique_line} says so; a bulk change could create duplicates')
            if t.kind == 'add':
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

    def divisions(self, e, safe, t):
        """Every division must be by something that cannot be zero where it happens."""
        if e[0] == 'bin':
            d = e[3]
            if e[1] in ('div', 'rem'):
                if d == ('num', 0):
                    self.d('error', t.line, 'this divides by zero')
                elif d[0] != 'num' and d not in safe:
                    name = self.name_of(d).strip('"')
                    self.d('question', t.line, f'what should happen when {name} is zero?',
                           'dividing by zero has no answer, and I will not invent one',
                           f'say it, e.g. "... divided by {name} if {name} is not 0, otherwise 0"')
                elif e[1] == 'div':
                    self.d('note', t.line, 'whole-number division drops the remainder (7 / 2 is 3)')
            self.divisions(e[2], safe, t)
            self.divisions(d, safe, t)
        elif e[0] == 'if':
            for c in cond_cmps(e[1]):
                self.divisions(c[2], safe, t)
                self.divisions(c[3], safe, t)
            self.divisions(e[2], safe + nonzero(e[1], True), t)
            self.divisions(e[3], safe + nonzero(e[1], False), t)

    def run(self):
        self.infer()
        self.validate()
        return self.diags


def check(prog, src):
    return Checker(prog, src).run()
