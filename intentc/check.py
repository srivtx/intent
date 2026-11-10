"""Semantic checks on Intent IR: infer types, and find every decision the program left open.

Four tiers, in this order, and each is reported differently:
  declared  - the programmer said it
  inferred  - follows from how the property is used (age is multiplied -> number)
  assumed   - a naming convention (email -> text); reported as a note, overridable
  asked     - nothing decides it; compilation stops with a question
"""
from .ir import TEXT_OPS, Diag, cond_cmps, walk_cond_exprs, walk_expr
from .lexicon import CONVENTION

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
        return t.ptypes.get(e[1])

    def name_of(self, e):
        return {'field': f'"{e[1]}"', 'param': f'the given {e[1]}', 'num': str(e[1]),
                'str': f'"{e[1]}"', 'bin': 'a calculation'}[e[0]] if e[0] != 'num' else str(e[1])

    def need(self, e, typ, coll, t):
        k = e[0]
        cur = self.ty(e, coll, t)
        if cur is None:
            if k == 'field':
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
            return False
        exprs = [e for _, e in t.assigns] + list(walk_cond_exprs(t.where))
        for top in exprs:
            for e in walk_expr(top):
                if e[0] == 'bin':
                    ch |= self.need(e[2], 'int', coll, t)
                    ch |= self.need(e[3], 'int', coll, t)
        for f, e in t.assigns:
            ch |= self.equal(('field', f), e, coll, t)
        for c in cond_cmps(t.where):
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

    def infer(self):
        for _ in range(8):
            if not any([self.constrain(t) for t in self.prog.tasks]):
                break
        assumed = False
        for c in self.prog.collections.values():
            for f in c.fields.values():
                if f.type is None and f.name in CONVENTION:
                    f.type, f.how = CONVENTION[f.name], 'assumed'
                    assumed = True
                    self.d('note', f.line, f'assuming "{f.name}" is {TYPE_NAME[f.type]}, from its name',
                           hint=f'write "{f.name} ({"number" if f.type == "text" else "text"})" if that is wrong')
        if assumed:
            for _ in range(8):
                if not any([self.constrain(t) for t in self.prog.tasks]):
                    break
        for c in self.prog.collections.values():
            for f in c.fields.values():
                if f.type is None:
                    self.d('question', f.line, f'is "{f.name}" text or a number?',
                           'nothing in the program decides this',
                           f'write "{f.name} (text)" or "{f.name} (number)"')
        for t in self.prog.tasks:
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
        for t in P.tasks:
            coll = P.collections.get(t.coll)
            exprs = [e for _, e in t.assigns] + list(walk_cond_exprs(t.where)) + ([t.expr] if t.expr else [])
            for top in exprs:
                for e in walk_expr(top):
                    if e[0] == 'bin' and e[1] in ('div', 'rem'):
                        if e[3][0] != 'num' or e[3][1] == 0:
                            self.d('error', t.line, 'dividing by something that could be zero is not supported yet',
                                   'I would have to invent what happens at zero',
                                   'divide by a fixed non-zero number')
                        elif e[1] == 'div':
                            self.d('note', t.line, 'whole-number division drops the remainder (7 / 2 is 3)')
            if t.kind == 'update':
                for f, _ in t.assigns:
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

    def run(self):
        self.infer()
        self.validate()
        return self.diags


def check(prog, src):
    return Checker(prog, src).run()
